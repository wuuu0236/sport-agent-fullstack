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
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import base64
import datetime
import json
import threading
from queue import Queue

from src import config, memory
from src.supervisor import route
from src.agents import get_agent
from src.skill_loader import match_skills
from src.server import image_import, _import_save
from src.sport_data import SportStore
from src.orchestrator import SupervisorAgent

_store = SportStore()


app = FastAPI(title="sport-agent-service", version="0.1.0")


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
    name = route(req.message)
    agent = get_agent(name)
    skills = match_skills(req.message)
    ctx = {"skills": skills}
    if req.context:
        ctx.update(req.context)
    try:
        out = agent.handle(req.message, ctx)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"agent[{name}] failed: {e}")
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
        raise HTTPException(status_code=500, detail=f"agent[{name}] failed: {e}")
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
    from src.agents.coach_agent import _user_max_hr
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
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        e = q.get()
        if e is None:
            break
        yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
