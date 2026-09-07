"""sport-agent-service: 把现有 Python Agent 能力暴露为 HTTP 微服务。

复用 sport-agent-mvp 的 src 包（coach / posture / research / writer / memory / scheduler / general），
零改动迁移。Spring Boot 编排层通过本服务调度各 Agent。

端点：
  GET  /health           健康检查（返回 mock 状态与模型名）
  POST /chat             {message, context?} -> {agent, output, metadata}   内部路由+处理（一站式）
  POST /agent/{name}     {input,  context?} -> {agent, output, metadata}   按名调用（供编排层串流水线）
  POST /route            {message}          -> {agent}                      仅路由，供编排层先问再调
  GET  /sessions         {limit?}           -> {sessions:[{type,date,summary}]}  最近训练记录（供前端展示）
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import base64
import datetime
import json
import re
import threading
import traceback
from queue import Queue

from src import config, memory
from src.supervisor import route
from src.agents import get_agent
from src.agents.memory_agent import is_memory_intent
from src.agents.coach_agent import _user_max_hr
from src.skill_loader import match_skills
from src.server import image_import, _import_save
from src.sport_data import SportStore
from src.orchestrator import SupervisorAgent
from src import plan_store

_store = SportStore()


app = FastAPI(title="sport-agent-service", version="0.1.0")


@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    """简单 token 鉴权：AGENT_AUTH_TOKEN 非空时，除 /health 外一律要求
    请求头 X-Agent-Token 匹配。防三类现实威胁：浏览器恶意网页对本机接口的
    跨站调用、DNS rebinding、容器化后（--host 0.0.0.0）裸奔在局域网。
    留空 = 关闭（纯本机开发模式）。/health 只暴露 mock 状态与模型名，放行。"""
    token = config.CONFIG.AGENT_AUTH_TOKEN
    if token and request.url.path != "/health" and request.method != "OPTIONS":
        if request.headers.get("X-Agent-Token") != token:
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    return await call_next(request)


def _agent_error(name: str, e: Exception) -> HTTPException:
    """内部异常不外泄：完整堆栈只进服务端日志，客户端拿通用文案。"""
    traceback.print_exc()
    return HTTPException(status_code=500,
                         detail=f"agent[{name}] 执行失败，请查看 agent-service 日志")


class ChatReq(BaseModel):
    message: str
    context: dict = None


class AgentReq(BaseModel):
    input: str
    context: dict = None


class RouteReq(BaseModel):
    message: str


class ImportReq(BaseModel):
    image: str           # base64 编码的图片
    mime: str = "image/png"


@app.get("/health")
def health():
    return {"status": "ok", "mock": config.CONFIG.mock_mode, "model": config.CONFIG.LLM_MODEL}


@app.post("/chat")
def chat(req: ChatReq):
    # 短期会话记忆落盘：用户消息先 append，助理回复后再 append。
    # BaseAgent._llm 会自动把最近 N 条 session_turns 注入上下文，多轮追问才有记忆。
    memory.append_session("user", req.message)

    # 计划应用意图（必须最先判断）：用户对待确认计划回复「替换当前计划」/「加入第二方案」。
    # 注意：不能放到记忆意图之后——「加入」是记忆触发词之一，会误被 is_memory_intent
    # 截获，导致"加入第二方案"被当成记忆条目存进 USER.md 而不应用计划。
    # 这两个动作词非常具体，不会与普通记忆请求（如「记住我膝盖不好」）冲突。
    plan_action = _detect_plan_action(req.message)
    if plan_action:
        res = plan_store.apply_pending(plan_action)
        if res["ok"]:
            out = (
                f"{res['msg']}。左侧「计划」模块已刷新，"
                "你可以直接点过去查看。"
            )
        else:
            out = (
                f"{res['msg']}。如果你想生成新计划，"
                "可以直接说「帮我生成减脂三分化计划」。"
            )
        memory.append_session("assistant", out)
        return {"agent": "plan_manager", "output": out, "metadata": {}}

    # 记忆意图（记住/记下/记入/存入/放进…）必须先于目标变更检测：
    # 「我想起来了，你记得吗」这类回忆句会被 _detect_goal 的「我想」正则截走，
    # 误当成目标变更并生成计划（真实回归 bug）。元动作（记忆）优先级更高。
    if is_memory_intent(req.message):
        agent = get_agent("memory")
        try:
            out = agent.handle(req.message)
        except Exception as e:
            raise _agent_error("memory", e)
        memory.append_session("assistant", out)
        return {"agent": "memory", "output": out, "metadata": {}}

    # 训练目标变更意图（如「我要体测」「我想增肌」「目标换成…」）。
    # 这类消息既是画像更新，也隐含要新计划，因此直接生成计划并询问应用方式，
    # 不能交给记忆 Agent 只写 USER.md，否则计划模块不会联动刷新。
    goal = _detect_goal(req.message)
    if goal:
        return _handle_goal_change(req.message, goal)

    # 生成/更新计划意图：用户明确要生成新计划且没有待确认计划时，直接生成并询问如何应用
    if _is_plan_generate_intent(req.message):
        goal = _current_goal_from_message(req.message) or _read_active_goal()
        try:
            task = f"请帮我生成一份{goal}训练计划"
            plan_text = _coach_answer(task)
            plan = {"name": goal, "goal": goal, "content": plan_text}
            plan_store.set_pending(plan)
            out = (
                f"📋 已生成「{goal}」训练计划。\n\n"
                "回复「替换当前计划」即可用新计划覆盖左侧「计划」模块；"
                "回复「加入第二方案」则保留旧计划，把它作为可选方案加入。"
            )
        except Exception as e:
            out = f"生成计划时出错：{e}。你可以换个说法再试。"
        memory.append_session("assistant", out)
        return {"agent": "plan_manager", "output": out, "metadata": {}}


    # 自动升级：复杂任务（多步综合 / 伤病会诊）自动走 SupervisorAgent 主从编排，
    # 普通问答 / 记录仍走单 Agent 路由——对齐业界「主 Agent 运行中自动判断派活」。
    if _needs_orchestration(req.message):
        events: list = []
        def _emit(e):
            events.append(e)
        final = SupervisorAgent().run(req.message, emit=_emit)
        memory.append_session("assistant", final)
        return {"agent": "supervisor", "output": final, "events": events,
                "mode": "orchestrated", "metadata": {}}
    name = route(req.message)
    agent = get_agent(name)
    skills = match_skills(req.message)
    ctx = {"skills": skills}
    if req.context:
        ctx.update(req.context)
    try:
        out = agent.handle(req.message, ctx)
    except Exception as e:
        raise _agent_error(name, e)
    memory.append_session("assistant", out)
    return {
        "agent": name,
        "output": out,
        "metadata": {"used_skills": [s.get("name") for s in skills]},
    }


@app.post("/agent/{name}")
def agent_call(name: str, req: AgentReq):
    agent = get_agent(name)
    skills = match_skills(req.input)
    ctx = {"skills": skills}
    if req.context:
        ctx.update(req.context)
    try:
        out = agent.handle(req.input, ctx)
    except Exception as e:
        raise _agent_error(name, e)
    return {
        "agent": name,
        "output": out,
        "metadata": {"used_skills": [s.get("name") for s in skills]},
    }


@app.post("/route")
def route_only(req: RouteReq):
    return {"agent": route(req.message)}


@app.get("/sessions")
def list_sessions(limit: int = 12):
    """最近训练记录（供前端『最近训练』展示 + 训练图表可视化）。

    新增结构化字段（前端画图表用）：
      run      -> distance_km / duration_min / avg_hr / max_hr / pace_min_km / load / zones / rpe
      strength -> exercises（动作明细）
    summary 保留为人类可读文本，兼容旧前端。
    """
    recs = _store.all()
    recs.sort(key=lambda r: r.get("date") or "", reverse=True)
    out = []
    max_hr = _user_max_hr()
    for r in recs[:limit]:
        if r.get("type") == "run":
            a = _store.analyze_run(r, max_hr)
            s = f"跑步 {r.get('distance_km')}km / {r.get('duration_min')}分"
            if r.get("avg_hr"):
                s += f" / 平均心率{r.get('avg_hr')}"
            out.append({
                "type": "run", "date": r.get("date"), "summary": s,
                "distance_km": r.get("distance_km"),
                "duration_min": r.get("duration_min"),
                "avg_hr": r.get("avg_hr"),
                "max_hr": r.get("max_hr"),
                "rpe": r.get("rpe"),
                "pace_min_km": a["pace_min_km"],
                "load": a["load"],
                "zones": a["zones"],
            })
        elif r.get("type") == "strength":
            exs = "、".join(
                f"{e.get('name')}{e.get('sets')}×{e.get('reps')}×{e.get('weight_kg')}kg"
                for e in r.get("exercises", [])
            )
            s = f"力量：{exs}"
            out.append({"type": "strength", "date": r.get("date"), "summary": s,
                        "exercises": r.get("exercises", [])})
        else:
            s = str(r.get("type", ""))
            out.append({"type": r.get("type"), "date": r.get("date"), "summary": s})
    return {"sessions": out}


@app.get("/memory")
def memory_list():
    """长期记忆查看（工作台「记忆」模块）：USER（关于用户）/ MEMORY（助理笔记）。"""
    from src import memory as mem
    mem.load()  # 每次读盘，新写入的 USER.md / MEMORY.md 立即生效（无需重启服务）
    return {
        "user": mem.list_store("user") or [],
        "memory": mem.list_store("memory") or [],
        "snapshot": mem.snapshot_block(),
    }



@app.get("/plan")
def get_plan():
    """获取当前计划 + 备选方案 + 待确认计划（供左侧「计划」模块展示）。"""
    return plan_store.list_plans()


@app.get("/plans")
def list_plans_api():
    """获取完整计划库。"""
    return plan_store.list_plans()


@app.post("/plan/apply")
def apply_plan(req: dict = None):
    """应用待确认计划：action=replace 替换当前计划；action=add 加入为备选方案。"""
    action = (req or {}).get("action")
    return plan_store.apply_pending(action)


@app.post("/plan/generate")
def generate_plan(req: dict = None):
    """根据目标生成计划并设为待确认。"""
    goal = (req or {}).get("goal", "")
    if not goal:
        raise HTTPException(status_code=400, detail="goal is required")
    task = f"请帮我生成一份{goal}训练计划"
    plan_text = _coach_answer(task)
    plan = {"name": goal, "goal": goal, "content": plan_text}
    plan_store.set_pending(plan)
    return {"ok": True, "pending": plan}


@app.post("/plan/switch")
def switch_plan(req: dict = None):
    """切换到指定计划为当前 active。"""
    plan_id = (req or {}).get("id")
    if not plan_id:
        raise HTTPException(status_code=400, detail="id is required")
    return plan_store.switch_plan(plan_id)


@app.post("/plan/delete")
def delete_plan(req: dict = None):
    """删除指定计划（删激活计划时自动提升下一个为激活）。"""
    plan_id = (req or {}).get("id")
    if not plan_id:
        raise HTTPException(status_code=400, detail="id is required")
    return plan_store.delete_plan(plan_id)


@app.post("/plan/discard")
def discard_plan():
    """放弃当前待确认计划。"""
    return plan_store.clear_pending()

@app.post("/import-image")
def import_image(req: ImportReq):
    """训练截图导入：本地 OCR → 文字 → LLM 解析 → 暂存（不落库）。

    P0-3 修复：解析结果先进暂存区（workspace:isolated），返回 staged 标记，
    由前端确认后调 /commit 落库——防止 OCR/LLM 误解析直接污染真实训练库。
    截图不外传，仅 OCR 文本送 LLM。
    """
    res = image_import(req.image, req.mime)
    if res.get("ok") and res.get("data"):
        try:
            staged = _stage_import_data(res["data"])
            res["saved"] = False
            res["staged"] = staged
        except Exception as e:  # noqa: BLE001
            res["save_error"] = str(e)
    return res


@app.post("/supervise")
def supervise(req: ChatReq, stream: int = 0):
    """多 Agent 主从编排：主 Agent(Supervisor) 拆解→派发→回收→综合。

    stream=1 → SSE 事件流（前端看板实时显示每个子 Agent 状态）；
    默认 → 一次性 JSON（含 events 数组，便于测试/非 SSE 客户端）。
    """
    if stream:
        return StreamingResponse(_supervise_stream(req.message),
                                 media_type="text/event-stream")
    events = []

    def emit(e):
        events.append(e)

    final = SupervisorAgent().run(req.message, emit=emit)
    return {"agent": "supervisor", "output": final, "events": events}


@app.post("/commit")
def commit(req: dict = None):
    """确认暂存记录入库。可带 records 直接保存，或确认全局暂存队列。

    带 records 时按每条记录的 _staged_id 精确清除对应暂存——只清「本次确认」的，
    不误清其他会话/并发请求的暂存（旧实现 discard_staged() 全清，多用户会互相踩）。
    """
    store = SportStore()
    if req and req.get("records"):
        r = _import_save({"records": req["records"]})
        ids = [rec.get("_staged_id") for rec in req["records"]
               if rec.get("_staged_id")]
        if ids:
            store.discard_staged(ids)
        else:
            # 兼容旧调用：记录里没有 _staged_id（如直接 API 传的原始数据）时按旧语义清空
            store.discard_staged()
        return r
    n = store.commit_staged()
    if n:
        return {"ok": True, "msg": f"✅ 已确认入库 {n} 条训练记录"}
    return {"ok": False, "msg": "暂存区为空，无需提交"}


def _stage_import_data(data: dict) -> bool:
    """把图片导入解析出的单条记录放进暂存队列（不落库）。"""
    store = SportStore()
    t = data.get("type")
    date = data.get("date") or datetime.date.today().isoformat()
    try:
        if t == "run":
            dist = float(data.get("distance_km") or 0)
            dur = float(data.get("duration_min") or 0)
            if dist > 0 and dur <= 0:
                dur = round(dist * 6, 1)
            store.stage_run(date, dist, dur, int(data.get("avg_hr") or 0),
                            int(data.get("max_hr") or 0),
                            hr_series=data.get("hr_series") or None,
                            rpe=int(data.get("rpe") or 0),
                            note=data.get("note") or "图片导入")
            return True
        elif t == "strength":
            exs = data.get("exercises") or []
            if exs:
                store.stage_strength(date, exs, note=data.get("note") or "图片导入")
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _supervise_stream(task: str):
    """SSE 生成器：线程跑 Supervisor，事件逐个 yield 成 SSE 帧。"""
    q = Queue()

    def emit(e):
        q.put(e)

    def worker():
        try:
            SupervisorAgent().run(task, emit=emit)
        except Exception as e:  # noqa: BLE001
            # 编排异常必须以 error 事件收尾，否则前端收到的流会静默截断，
            # 看起来像「正常结束但什么都没发生」。
            emit({"type": "error", "message": f"编排失败：{e}"})
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        e = q.get()
        if e is None:
            break
        yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"


def _needs_orchestration(msg: str) -> bool:
    """判断一条消息是否需要多 Agent 主从编排（而非单 Agent 直答）。

    对齐业界「主 Agent 运行中自动判断该不该派 subagent」：默认单 Agent 路由，
    仅在任务明显需要「多步 / 多工具 / 多专长综合」时升级到 SupervisorAgent。
    """
    # 记录训练类：recorder 单 Agent 即可，不编排（避免『记录一次减脂训练』误判）
    if any(k in msg for k in ("记一次", "记录", "保存", "入库", "添加")) and \
       any(k in msg for k in ("跑", "公里", "km", "组", "次", "kg", "训练")):
        return False
    # 健身域已统一归 coach（谭成义唯一直答）；编排只留给「多源汇合」用例：
    # 需要同时用到外部资料 / 历史数据计算 / 综合成文的，才值得多步编排。
    # ① 周报类：汇报表（检索 + 分析 + 综合）。
    #    但「谈论周报」≠「要生成周报」：概念询问类（格式/包含什么/怎么写）不编排。
    if "周报" in msg:
        if any(k in msg for k in ("什么", "格式", "怎么写", "包含", "模板", "例子", "示例")):
            return False
        return True

    # ② 阶段性总结/回顾类：总结类动词 + 时间范围词同时出现。
    #    「总结一下卧推要点」是单点问题（无时间范围），不编排；
    #    「总结这周的训练」需要读周聚合数据再综合，编排。
    _SUMMARY_KW = ("总结", "汇总", "回顾", "复盘", "报告")
    _RANGE_KW = ("这周", "本周", "上周", "最近", "近期", "本月", "这个月",
                 "一个月", "月度", "阶段")
    if any(k in msg for k in _SUMMARY_KW) and any(k in msg for k in _RANGE_KW):
        return True

    # ③ 数据驱动计划类：分析/依据 + 数据来源 + 计划产出，三要素齐才编排。
    #    与单源计划请求区分：「给我安排练胸计划」没有数据依据，coach 直答即可；
    #    「根据我的训练数据安排计划」要先读数据再综合，走编排。
    _DATA_KW = ("分析", "根据", "结合", "基于", "参考")
    _SRC_KW = ("数据", "情况", "记录", "表现", "进步")
    _PLAN_KW = ("计划", "方案", "安排", "课表")
    if any(k in msg for k in _DATA_KW) and any(k in msg for k in _SRC_KW) \
            and any(k in msg for k in _PLAN_KW):
        return True

    return False


def _coach_answer(msg: str) -> str:
    """把消息交给 coach（谭成义）单 Agent 直答，返回输出文本。

    健身域统一出口：跑步/减脂/增肌/练部位/伤痛/计划都先走这里，
    保证用户始终从蒸馏到的谭成义视角得到回答，而非被多 Agent 拆成通用内容。
    """
    agent = get_agent("coach")
    skills = match_skills(msg)
    try:
        return agent.handle(msg, {"skills": skills})
    except Exception as e:
        return f"教练生成建议时出错：{e}"


def _detect_goal(msg: str):
    """识别用户表达的新训练目标/方向，返回目标文本或 None。

    覆盖：我要减脂 / 我想增肌 / 我的目标改成… / 改练三分化 / 换成… / 调整成…
    纯计划请求（不含目标陈述）返回 None，避免与编排关键词重复触发。
    """
    # 记忆意图（记住/记得/别忘了…）不是目标变更：「我想起来了，你记得吗」
    # 会被下面的「我想」正则截走、误生成计划。元动作在意图管线里永远优先。
    if is_memory_intent(msg):
        return None
    m = re.search(
        r"(?:我要|我想|我打算|我的目标(?:是|改为|改成)?|目标是|改练|换成|调整成|调整为|新目标(?:是)?|目前目标(?:是)?)\s*[:：]?\s*(.+)",
        msg,
    )
    if not m:
        return None
    goal = m.group(1).strip()
    # 截到任务执行词，只保留目标本身（如「减脂」而非「减脂给我安排计划」）
    for stop in ("给我安排", "帮我", "安排", "计划", "训练", "方案", "周报",
                 "制定", "规划", "生成", "做一份", "来一份", "像在", "比如",
                 "例如", "类似"):
        idx = goal.find(stop)
        if 0 < idx:
            goal = goal[:idx]
    # 去掉连接词（并且/同时/还有/以及）与逗号/空格，合并成干净复合目标，
    # 如「减脂，并且三分化」→「减脂三分化」，避免出现逗号粘连的计划名。
    for conj in ("并且", "同时", "还有", "以及"):
        goal = goal.replace(conj, "")
    goal = goal.replace("，", "").replace(",", "").replace(" ", "")
    goal = goal.strip(" 。.，,！!？?、\n")
    if len(goal) < 2:
        return None
    # 如果提取出来的是问句/咨询意图，不算目标变更
    if goal.startswith(("怎么", "如何", "为什么", "什么", "怎样", "咋", "该不该", "要不要")):
        return None
    # 把分散在句子里的训练类型/分化词合并进目标，避免只提取到「减脂」而丢掉「三分化」。
    # 例如「我要减脂，给我安排训练计划，要求三分化」→「减脂三分化」。
    type_modifiers = ("三分化", "五分化", "全身训练", "上下肢", "推拉腿",
                      "力量举", "马拉松", "半马", "体测")
    for mod in type_modifiers:
        if mod in msg and mod not in goal:
            goal = goal + mod
    # 体测类目标：保留关键数字指标，如「1km」「3分30秒」「3:30」「330"
    if "体测" in goal or "跑步" in goal or "跑" in goal:
        for metric in ("1km", "3km", "5km", "10km", "800米", "1000米"):
            if metric in msg and metric not in goal:
                goal = goal + metric
    return goal


def _handle_goal_change(msg: str, goal: str) -> dict:
    """处理训练目标变更：写画像、生成计划、设为待确认、提示用户应用。

    目标变更类消息（我要/我想/目标换成…）会走到这里，而不是只落记忆。
    这样左侧「计划」模块会立即出现待确认卡片，聊天里也有即时反馈。
    """
    prev = _read_active_goal()
    _record_goal(goal)
    try:
        # 目标变更也视为健身咨询：交给 coach（谭成义）直答，不再多 Agent 编排
        out = _coach_answer(msg)
        # 教练给出的方案也写入「计划」模块待确认，保持模块联动
        plan_store.set_pending({"name": goal, "goal": goal, "content": out})
        out = _append_plan_prompt(out, goal, goal)
        if prev and prev != goal:
            out = (
                f"📝 已将原目标「{prev}」保留到历史画像，当前目标更新为「{goal}」。\n\n"
                + out
            )
    except Exception as e:
        out = (
            f"📌 已记录你的新训练目标「{goal}」。\n"
            f"教练生成建议时出错：{e}。你可以说「帮我生成{goal}计划」再试。"
        )
    memory.append_session("assistant", out)
    return {"agent": "coach", "output": out, "metadata": {}}


def _record_goal(goal: str) -> None:
    """把新训练目标写入 USER 长期记忆：保留历史目标，只更新当前目标。

    旧『当前训练目标』会降级为『历史训练目标』，避免用户说「我要体测」时
    之前的「减脂」目标被直接覆盖、无迹可寻。
    """
    entries = memory.list_store("user") or []
    new_entries: list[str] = []
    old_current: str | None = None
    for e in entries:
        if e.startswith("当前训练目标："):
            old_current = e
            continue
        # 兼容旧格式：旧版直接写「训练目标：XXX」，全部迁移到当前/历史机制
        if e.startswith("训练目标："):
            continue
        new_entries.append(e)
    if old_current:
        old_goal = old_current[len("当前训练目标："):].strip()
        if old_goal and old_goal != goal:
            hist = f"历史训练目标：{old_goal}"
            if hist not in new_entries:
                new_entries.append(hist)
    new_entry = f"当前训练目标：{goal}"
    if new_entry not in new_entries:
        new_entries.append(new_entry)
    # 写回 USER.md 并刷新内存快照（与 memory 模块共用文件锁，防并发读改写互踩）
    with memory.file_lock:
        user_path = config.CONFIG.USER_FILE
        user_path.parent.mkdir(parents=True, exist_ok=True)
        user_path.write_text("\n§\n".join(new_entries), encoding="utf-8")
    memory.load()


def _append_goal_prompt(text: str, goal: str) -> str:
    """在回复末尾追加『是否据此更新计划』的询问。"""
    note = (
        f"\n\n📌 已记录你的新训练目标「{goal}」到长期记忆。"
        f"要我据此重新编排一份训练计划并更新到「计划」模块吗？（回复「更新计划」即可）"
    )
    return (text or "") + note


def _append_plan_prompt(text: str, goal: str, plan_name: str) -> str:
    """在生成计划后，询问用户是替换当前计划还是加入为第二方案。"""
    note = (
        f"\n\n📌 已记录你的新训练目标「{goal}」，并已生成「{plan_name}」暂存为待确认。"
        f"回复「替换当前计划」即可覆盖左侧「计划」模块；"
        f"回复「加入第二方案」则保留旧计划，把它作为可选方案加入。"
    )
    return (text or "") + note


def _detect_plan_action(msg: str):
    """识别用户对pending计划的应用意图：replace（替换当前） / add（加入第二方案）。"""
    m = msg.strip()
    replace_kw = (
        "替换当前计划", "覆盖当前计划", "替代当前计划", "替换掉之前的",
        "用新的替换", "替换旧的", "覆盖旧的", "更新计划",
    )
    add_kw = (
        "加入第二方案", "作为第二方案", "第二方案", "方案二",
        "新增方案", "添加为备选", "保留旧计划", "作为备选",
        "加入备选", "添加到方案",
    )
    if any(k in m for k in replace_kw):
        return "replace"
    if any(k in m for k in add_kw):
        return "add"
    return None


def _is_plan_generate_intent(msg: str) -> bool:
    """用户明确请求生成/更新训练计划（且无待确认计划时走此分支）。"""
    m = msg.strip()
    kw = (
        "生成计划", "更新计划", "重新编排计划", "给我计划",
        "我要新计划", "重新生成计划", "来一份计划",
    )
    return any(k in m for k in kw)


def _current_goal_from_message(msg: str) -> str:
    """从「生成计划」类消息里提取目标，如「生成减脂三分化计划」。"""
    # 先尝试完整目标句
    m = re.search(
        r"(?:生成|更新|重新编排|给我|我要|来一份)\s*(.+?)\s*(?:计划|方案|安排)?$",
        msg.strip(),
    )
    if m:
        g = m.group(1).strip()
        # 去掉一些前缀
        for pre in ("我的", "一份", "一个"):
            if g.startswith(pre):
                g = g[len(pre):]
        if len(g) >= 2:
            return g
    return _detect_goal(msg)


def _read_active_goal() -> str:
    """从长期记忆或当前计划中读取用户最新训练目标。"""
    # 优先 USER.md 中的当前训练目标
    for entry in memory.list_store("user") or []:
        if entry.startswith("当前训练目标："):
            return entry.replace("当前训练目标：", "").strip()
        # 兼容旧格式
        if entry.startswith("训练目标："):
            return entry.replace("训练目标：", "").strip()
    # 其次当前激活计划
    p = plan_store.active_plan()
    if p and p.get("goal"):
        return p["goal"]
    return "减脂"
