"""LangGraph 编排图：SupervisorAgent 主循环的 StateGraph 实现（2026-09-16 迁移）。

迁移前：orchestrator.py 的 SupervisorAgent 用一个 for 循环 + 若干 if 手写主循环；
迁移后：同样的语义拆成显式节点与条件边，图结构即文档。

    START → plan → validate → dispatch ⇄ dispatch
                                  ↓（步数走完）
                                review ──PASS──→ synthesize → END
                                  └──ISSUES(且被评节点是 planner)──→ rewrite → synthesize

与文档方案的一处**有意偏差**：分类节点没有放进图里，而是留在入口（app.py 调
src/intent.classify）。原因是 /chat 的单 Agent 路径不只有「调一个 Agent」这一步——
它前面还有记忆意图、目标变更、计划生成三个旁路，且单 Agent 分支要吃 req.context。
把 direct 分支搬进图会让这套逻辑出现第二份实现，两处必然漂移。
图因此只负责「多 Agent 协作」这一段，输入时已确定要编排。

节点语义与迁移前逐一对齐（事件序列完全不变，前端与 Java 网关无需改动）：
  plan      LLM 拆解（去掉了「固定管线」暗示与 coach 关键词短路）
  validate  @sN 依赖校验：该用上游产出却没写引用时自动补上（新增，见 CHANGELOG）
  dispatch  代码门控派发：@sN 替换 / 空输出与哨兵判失败 / 技能按主理 Agent 注入
  review    Generator-Critic：最后一个成功产出送评审
  rewrite   planner 产出不合格时按评审意见重写**一次**（不循环，防重写风暴）
  synthesize 主 Agent 亲自收口；有暂存则附注并发 pending_commit
"""
import json
import re
import uuid
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from . import config, llm, memory, review_rules
from .agents import agent_catalog, get_agent
from .skill_loader import match_skills_for
from .sport_data import SportStore

# 步骤引用：input 里的 @s1 在执行时替换为 s1 的真实产出（截断防超长）
_REF_RE = re.compile(r"@(s\d+)")
_REF_TRUNC = 400
_MAX_STEPS = 4
# BaseAgent._llm 的空串兜底文案：出现即视为「模型没生成」，判该节点失败
_SENTINEL = "（模型本次未生成内容）"

# 拆解强 schema：只允许输出 JSON 数组，每步含 id/agent/input/expect
_PLAN_PROMPT = """你是主 Agent（Supervisor），负责把一个用户任务拆成「由专业子 Agent 执行」的子任务。
只输出一个 JSON 数组（不要任何其他文字、不要 markdown 代码块）。每项格式：
{{"id": "s1", "agent": "子agent名", "input": "给该子agent的输入（含必要的上下文）", "expect": "期望产出"}}

可用子 Agent 及职责：
{catalog}

规则：
· 最多 4 步；能 1 步完成就不要拆多步；
· **按任务实际需要选角色，不要套固定管线**。示例：
  - 伤病排查（「膝盖疼，分析是不是深蹲姿势问题，给康复方案」）→ clinician 判断诱因 +
    expert 补充依据 + planner 出康复方案；
  - 跨期对比（「对比上个月和这个月的跑步数据」）→ analyst 取数 + 综合成文，
    不需要 searcher；
  - 查资料型（「备战半马查最新方法并结合我的水平排计划」）→ searcher + analyst + planner；
  - 单纯汇报（「帮我生成周报」）→ analyst 取数 + planner 成文。
· 只选用必要的子 Agent。**跨期对比类可以派两次同一角色**（例：「对比上个月和这个月
  的跑步数据」→ 两次 analyst，input 里分别写明「上个月」「这个月」，最后一步综合），
  其余情况不重复派同一角色；
· 有依赖的步骤必须在 input 里用「@{前序id}」引用其结果（如 @s1），执行时会替换成真实产出。
  **只要这一步用得上前面任一步的产出，就必须写引用**——漏引会导致该步拿不到上下文。"""


class OrchestrationState(TypedDict, total=False):
    task: str
    steps: list
    idx: int
    results: dict
    review: str
    # 评审未通过、但被评步骤不是 planner（没有可重写的综合品）时的意见。
    # 必须在这里声明：LangGraph 按 TypedDict 的字段建通道，没声明的键会被静默丢弃
    # （实测踩过——节点 return 了 review_issues，synthesize 却永远读到空）。
    review_issues: str
    # 评审**没有完成**（评审模型不可用 / 评审节点异常）——与「评审通过」是两回事。
    # 同样必须声明，否则置位被静默丢弃，最终输出上的「未完成评审」提示就永远不出现。
    review_unavailable: bool
    used_skills: dict
    output: str
    filled_refs: list
    thread_id: str


# ---------------------------------------------------------------- 计划相关


def _fallback_plan(task: str) -> list:
    """代码模板兜底（拆解失败/ mock 模式用，保证永不空转）。

    按任务粗分类给不同模板——迁移前一律硬编码 searcher→analyst→planner，
    伤病类任务会被套上「检索+分析」的固定管线。
    """
    if any(k in task for k in ("膝", "疼", "痛", "伤", "康复", "体态", "圆肩", "下背", "不适")):
        return [
            {"id": "s1", "agent": "analyst", "input": "分析我最近的训练负荷，找出可能导致该不适的诱因",
             "expect": "训练数据诱因排查"},
            {"id": "s2", "agent": "planner",
             "input": f"{task}\n\n请结合 @s1 的诱因排查给出可执行的康复/调整方案",
             "expect": "康复与训练调整方案"},
        ]
    if any(k in task for k in ("周报", "报告", "总结", "汇总", "复盘", "回顾")):
        return [
            {"id": "s1", "agent": "analyst", "input": "分析我最近一个周期的训练数据",
             "expect": "周期训练数据分析"},
            {"id": "s2", "agent": "planner",
             "input": f"{task}\n\n请结合 @s1 的数据分析综合完成本任务",
             "expect": "综合成训练周报"},
        ]
    if any(k in task for k in ("计划", "方案", "安排", "课表", "周期", "目标", "备战")):
        return [
            {"id": "s1", "agent": "analyst", "input": "分析我的最近训练数据与水平基线",
             "expect": "水平基线分析"},
            {"id": "s2", "agent": "planner",
             "input": f"{task}\n\n请结合 @s1 的分析结果给出可执行方案",
             "expect": "训练计划"},
        ]
    from .supervisor import _keyword_route
    name = _keyword_route(task)
    return [{"id": "s1", "agent": name, "input": task, "expect": "直接回答"}]


def _parse_plan(raw: str) -> list:
    """解析 LLM 返回的计划。容忍 markdown 代码块包裹；无效则返回 []。"""
    if not raw:
        return []
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        steps = json.loads(text[start:end + 1])
    except Exception:
        return []
    if not isinstance(steps, list) or not steps:
        return []
    names = {a["name"] for a in agent_catalog()}
    valid = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        agent = str(s.get("agent") or "").strip()
        if agent not in names:
            continue
        valid.append({"id": str(s.get("id") or f"s{len(valid) + 1}"),
                      "agent": agent,
                      "input": str(s.get("input") or "(子任务输入缺失)"),
                      "expect": str(s.get("expect") or "")})
    return valid[:_MAX_STEPS]


# 需要上游产出的信号：出现这些词说明该步要「基于前面的结果」做事
_DEP_HINTS = ("结合", "根据", "基于", "参考", "依照", "按照", "汇总", "综合", "基于上文")
# 产出型角色：这类角色的产出天然应当是「基于上游资料/数据」的
_DEP_AGENTS = ("planner", "writer", "general")


def validate_steps(steps: list, task: str = "") -> tuple:
    """依赖校验（新增）：LLM 漏写 @sN 时自动补引用，避免信息静默丢失。

    原始问题：拆解提示词要求「有依赖就写 @s1」，但没有任何校验保证它一定写了。
    LLM 拆出 planner 却没写引用时，planner 拿不到上游产出 → 生成一份「看起来完整
    但实际缺料」的报告，而信息丢失是静默的（评审员也未必看得出）。

    规则：
    1. 指向不存在步骤的引用（@s9）直接删掉，避免把字面量 @s9 塞给子 Agent；
    2. 非首步 + 没写引用 + （input 含依赖词 或 该步是产出型角色）→ 自动补「请结合 @s1 …」；
    3. 引用去重 + 只保留真实存在的前序 id。

    返回 (steps, filled)：filled 记录自动补引的位置，供测试与自查。
    """
    ids = [s["id"] for s in steps]
    out, filled = [], []
    for i, step in enumerate(steps):
        prev = out  # 已校验的前序步骤（真实存在的 id）
        inp = step["input"]
        # 1) 清掉无效引用
        inp = _REF_RE.sub(lambda m: m.group(0) if m.group(1) in ids else "", inp)
        refs = [m.group(1) for m in _REF_RE.finditer(inp)]
        # 2) 补引用
        if i > 0 and prev and not refs:
            need = any(h in inp for h in _DEP_HINTS) or \
                any(h in step.get("expect", "") for h in ("综合", "方案", "报告", "计划", "汇总")) or \
                step["agent"] in _DEP_AGENTS
            if need:
                ref_str = " ".join(f"@{p['id']}" for p in prev[:_MAX_STEPS - 1])
                inp = f"{inp}\n\n请结合 {ref_str} 的产出综合完成本任务"
                filled.append({"step": step["id"], "added": ref_str})
        out.append({**step, "input": inp.strip()})
    return out, filled


# ---------------------------------------------------------------- 图构建


def _build_graph(emit, backend=None):
    """按本次 run 的 emit 回调构建图（节点闭包持有 emit，避免往 state 里塞不可序列化对象）。"""
    store = backend or _GraphBackend()

    def plan_node(state: OrchestrationState) -> dict:
        steps = store.plan(state["task"])
        emit({"type": "plan", "steps": [s["agent"] for s in steps],
              "total": len(steps)})
        return {"steps": steps, "idx": 0, "results": {}, "used_skills": {}}

    def validate_node(state: OrchestrationState) -> dict:
        steps, filled = validate_steps(state["steps"], state.get("task", ""))
        return {"steps": steps, "filled_refs": filled}

    def dispatch_node(state: OrchestrationState) -> dict:
        steps = state["steps"]
        i = state.get("idx", 0)
        step = steps[i]
        name = step["agent"]
        n = len(steps)
        emit({"type": "agent_start", "agent": name, "step": i + 1, "total": n})
        results = dict(state.get("results") or {})
        used = dict(state.get("used_skills") or {})
        try:
            out, step_skills = store.dispatch(name, step["input"], results,
                                              state.get("task", ""))
            for s in step_skills:
                used[s["name"]] = used.get(s["name"], 0) + 1
            results[step["id"]] = {"agent": name, "output": out}
            emit({"type": "agent_done", "agent": name, "step": i + 1, "total": n,
                  "output": out[:200] + ("…" if len(out) > 200 else "")})
        except Exception as e:  # noqa: BLE001
            results[step["id"]] = {"agent": name, "output": None}
            emit({"type": "agent_error", "agent": name, "step": i + 1, "total": n,
                  "error": str(e)})
        return {"results": results, "idx": i + 1, "used_skills": used}

    def review_node(state: OrchestrationState) -> dict:
        """Generator-Critic：对最后一个成功产出评审。评审异常一律视为通过。

        评审三层（方案 P1-1）：
        1. 规则检查先行（纯代码）：空/哨兵/降级/过短直接判不过，省掉一次 LLM 调用；
           疑似编造的数字、缺段落作为「已知疑点」附进评审提示。
        2. LLM 评审按结构化清单逐项判定（见 reviewer_agent 的 system_prompt）。
        3. 评审方走 `REVIEW_MODEL`（若配置）——不同模型避免自评偏差。
        """
        steps, results = state["steps"], state.get("results") or {}
        task = state["task"]
        step, out = _last_success(steps, results)
        if not out:
            return {"review": "", "review_issues": ""}
        # ---- 第一层：规则检查（不花 token，结论可复现）----
        upstream = {sid: (r or {}).get("output")
                    for sid, r in results.items()
                    if (r or {}).get("output")}
        report = review_rules.check(task, out, upstream)
        n = len(steps) + 1
        override = config.CONFIG.review_llm
        reviewer_model = override.get("model") or config.CONFIG.LLM_MODEL
        emit({"type": "agent_start", "agent": "reviewer", "step": n, "total": n})
        if report["blocking"]:
            review = review_rules.format_issues(report)
            emit({"type": "agent_done", "agent": "reviewer", "step": n, "total": n,
                  "output": review[:200], "reviewer_model": "规则检查",
                  "rule_blocking": len(report["blocking"])})
        else:
            hint_block = ""
            if report["hints"]:
                hint_block = ("\n\n【规则检查疑点（请逐条回应）】\n"
                              + "\n".join(f"- {h}" for h in report["hints"]))
            try:
                review = get_agent("reviewer").handle(
                    f"用户需求：{task}\n\n待评审内容：\n{out}{hint_block}",
                    {"skills": [], "use_history": False, "recall_mode": "recall",
                     **override})
                unavailable = review_rules.is_degraded(review)
                emit({"type": "agent_done", "agent": "reviewer", "step": n, "total": n,
                      "output": (review or "")[:200],
                      "reviewer_model": reviewer_model,
                      "review_unavailable": unavailable})
                if unavailable:
                    # 评审模型降级（返回「（LLM 暂时不可用，已降级）…」）= 评审没跑成。
                    # 老实现直接落到下面「不是 ISSUES 就放行」，于是评审服务挂掉时
                    # 质量门静默失效、还对外表现成「已通过评审」。这里单独置位，
                    # 由 synthesize 在最终输出上如实标注。
                    return {"review": "", "review_issues": "", "review_unavailable": True}
            except Exception as e:  # noqa: BLE001
                emit({"type": "agent_error", "agent": "reviewer", "step": n, "total": n,
                      "error": str(e)})
                # 评审节点异常同样是「没完成评审」，不是「通过」。
                return {"review": "", "review_issues": "", "review_unavailable": True}
        # 只有「评审不过 + 被评节点是 planner」才值得重写（planner 产出本是综合结果）。
        # 非 planner 的 ISSUES 不丢弃——交给综合节点当「已知不可靠项」（第三层传递）。
        if not _review_failed(review):
            return {"review": "", "review_issues": ""}
        if (step or {}).get("agent") != "planner":
            return {"review": "", "review_issues": review}
        return {"review": review, "review_issues": ""}

    def rewrite_node(state: OrchestrationState) -> dict:
        steps, results = state["steps"], dict(state.get("results") or {})
        step, out = _last_success(steps, results)
        if not step or not out:
            return {}
        n = len(steps) + 1
        emit({"type": "agent_start", "agent": "planner", "step": n, "total": n})
        try:
            rewrite = get_agent("planner").handle(
                f"请根据评审意见重写以下内容，修正所有问题：\n\n【评审意见】\n{state['review']}"
                f"\n\n【待重写内容】\n{out}",
                # task 必须一起传：否则重写提示词里的产出类型会退回按「重写指令」判断
                # （那段文本里没有「周报」字样），周报会被重写成训练计划。
                {"skills": [], "use_history": False, "recall_mode": "recall",
                 "task": state["task"]})
            if _deliverable(rewrite):
                results[step["id"]] = {"agent": "planner", "output": rewrite}
                emit({"type": "agent_done", "agent": "planner", "step": n, "total": n,
                      "output": rewrite[:200]})
                return {"results": results}
            emit({"type": "agent_error", "agent": "planner", "step": n, "total": n,
                  "error": "重写失败（模型未生成），保留原产出"})
        except Exception as e:  # noqa: BLE001
            emit({"type": "agent_error", "agent": "planner", "step": n, "total": n,
                  "error": str(e)})
        # 重写没成：planner 那份**刚被评审判过没过**的产出被原样保留，而综合层会直出它。
        # 此时评审意见绝不能丢——否则用户拿到的是「已知有问题」的成品，却没有任何提示。
        # 意见必须走 `review_issues` 通道：`state["review"]` 只服务于重写节点，
        # 综合层不读它（老实现只保留产出、意见原地蒸发，坏产出不带警告地漏出）。
        return {"results": results, "review_issues": state.get("review") or ""}

    def synthesize_node(state: OrchestrationState) -> dict:
        steps, results = state["steps"], state.get("results") or {}
        # 第三层传递：非 planner 步骤的评审意见交给综合节点，让主 Agent 知道
        # 哪一步的产出不可靠（原先这类 ISSUES 被记录后即丢弃）。
        final = store.synthesize(state["task"], steps, results,
                                 issues=state.get("review_issues") or "")
        if state.get("review_unavailable"):
            # 评审没跑成时必须让用户知道：否则「评审服务挂了」会被静默读成
            # 「评审通过」，质量门的对外可信度直接归零。
            note = ("\n\n---\n⚠️ 评审服务暂不可用，本轮**未完成质量评审**"
                    "（这不等于通过），请谨慎参考。")
            final = final + note if final else note.lstrip("\n")
        # complete 事件携带最终输出 + final 标记（前端据此收尾渲染）
        emit({"type": "complete", "status": "ok" if final else "degraded",
              "output": final, "final": True})
        # 工作空间隔离的收尾：若有暂存记录，附注 + 事件供前端确认后 /commit 落库
        staged = SportStore().staged()
        if staged:
            note = (f"\n\n📥 本次编排解析出 {len(staged)} 条训练记录，"
                    f"等待确认后入库（暂存区，未落库）。")
            final = final + note if final else note
            emit({"type": "pending_commit", "count": len(staged), "records": staged})
        return {"output": final}

    g = StateGraph(OrchestrationState)
    g.add_node("plan", plan_node)
    g.add_node("validate", validate_node)
    g.add_node("dispatch", dispatch_node)
    g.add_node("review", review_node)
    g.add_node("rewrite", rewrite_node)
    g.add_node("synthesize", synthesize_node)

    g.add_edge(START, "plan")
    g.add_edge("plan", "validate")
    g.add_edge("validate", "dispatch")
    # dispatch 自循环：一次跑一步（步数在派发前由代码门控写死上限），
    # 跑完最后一步才进评审——与迁移前的 for 循环语义一致。
    g.add_conditional_edges("dispatch",
                            lambda s: "more" if s.get("idx", 0) < len(s["steps"]) else "done",
                            {"more": "dispatch", "done": "review"})
    g.add_conditional_edges("review",
                            lambda s: "rewrite" if s.get("review") else "synth",
                            {"rewrite": "rewrite", "synth": "synthesize"})
    g.add_edge("rewrite", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()


class _GraphBackend:
    """节点里用到的副作用（拆解 / 派发 / 综合）。

    抽成类比直接写在节点里好测：pytest 里可以换掉后端做纯图结构测试，
    不必真的调 LLM。
    """

    # ---------- 拆解（模型的判断）----------
    def plan(self, task: str) -> list:
        if config.CONFIG.mock_mode:
            return _fallback_plan(task)
        catalog = "\n".join(f"- {a['name']}：{a['description']}" for a in agent_catalog())
        prompt = _PLAN_PROMPT.replace("{catalog}", catalog)
        try:
            raw = llm.chat(
                [{"role": "system", "content": prompt},
                 {"role": "user", "content": task}],
                # timeout=15：拆解只是输出一段 JSON，默认 60s 太长——真卡满会把 SSE
                # 连接拖到中间层（Nginx/浏览器）先超时断开，前端连 error 事件都收不到。
                temperature=0.2, max_tokens=900, timeout=15,
            )
        except Exception:
            raw = ""
        plan = _parse_plan(raw)
        return plan if plan else _fallback_plan(task)

    # ---------- 派发（代码的执行）：子 Agent 隔离执行，只回收产出 ----------
    def dispatch(self, name: str, inp: str, results: dict, task: str = "") -> tuple:
        # 依赖引用解析：@s1 → 替换为 s1 的真实产出（隔离回收的产物，截断防超长）
        inp = _REF_RE.sub(
            lambda m: ((results.get(m.group(1)) or {}).get("output")
                       or f"({m.group(1)} 无结果)")[:_REF_TRUNC],
            inp or "")
        agent = get_agent(name)
        # 上下文隔离：子 Agent 各带 system prompt，关掉短期历史（前缀稳定、更易命中
        # DeepSeek 缓存），记忆按需召回 Top5，避免全量记忆重复计费。
        # 技能：按「原始用户任务 + 本步 agent 是否该技能的主理人」注入——用原始任务
        # 而非 step input，后者已混入前序产出（含"心率""公里"等词），噪声大易误命中。
        step_skills = match_skills_for(task or "", agent.name)
        out = agent.handle(
            inp,
            {"skills": step_skills, "use_history": False, "recall_mode": "recall",
             "task": task},
        )
        if not (out or "").strip():
            raise ValueError(f"{name} 返回空输出")
        if _SENTINEL in out:
            raise ValueError(f"{name} 模型未生成内容")
        return out, step_skills

    # ---------- 综合（主 Agent 亲自收口）----------
    def synthesize(self, task: str, plan: list, results: dict, issues: str = "") -> str:
        if len(plan) == 1:
            r = results.get(plan[0]["id"])
            # `_deliverable` 兜住空/哨兵/降级文案：单步产出若是这三类，直出等于把
            # 「没生成出来」原样交给用户，改报「未产出有效结果」更诚实。
            if not _deliverable((r or {}).get("output")):
                return "（子 Agent 未产出有效结果，请稍后重试。）"
            return _annotate(r["output"], issues)

        # 多步：最后一个成功步骤若是 planner，其产出已综合 → 直接采用。
        # 但**不能无条件直出**：重写失败时保留的正是那份被评审判过没过的产出，
        # 若它本身还有机械缺陷（空/哨兵/降级），直出就是坏产出漏出。
        # 这种情况落到下面的汇总分支，让主 Agent 基于其它步骤的有效产出重新收口
        # （此时 issues 通道已带着评审意见进来，见 rewrite_node 的收尾）。
        for step in reversed(plan):
            r = results.get(step["id"])
            if r and r.get("output"):
                if step["agent"] == "planner" and _deliverable(r["output"]):
                    return _annotate(r["output"], issues)
                break

        blocks, joined = [], []
        for step in plan:
            r = results.get(step["id"])
            # 汇总分支同样只喂可交付的产出：把降级文案混进综合提示词，
            # 主 Agent 会照抄进成品里。
            if r and _deliverable(r.get("output")):
                blocks.append(f"【{r['agent']}】\n{r['output']}")
                joined.append(f"【{r['agent']}】\n{r['output'][:600]}")
        if not blocks:
            return "（所有子 Agent 节点均未产出有效结果，请稍后重试。）"
        joined_full = "\n\n".join(blocks)
        joined_short = "\n\n".join(joined)
        if config.CONFIG.mock_mode:
            return "主 Agent 已编排完成：\n\n" + joined_full
        # 主 Agent 综合也必须结合用户画像（兜底）：planner 偶发失败时，综合分支
        # 若不带画像，会生成忽略体态/伤病的计划，造成回归。
        memory.load()
        _items = memory.list_store("user") or []
        _profile = "\n".join(f"- {p}" for p in _items) if _items else "（暂无用户画像）"
        sys = ("你是主 Agent（Supervisor）。以下是各子 Agent 完成的任务半成品。"
               "请把它们综合成一份对用户直接可用的完整回答：结构清晰、口语化、"
               "如实引用真实产出；缺失的部分如实说明，不要编造。\n"
               f"用户画像（含体态/伤病/心率基线，务必结合，不可忽略）：\n{_profile}")
        # 第三层传递：把评审未通过项交给主 Agent——它要么修正，要么明确标注，
        # 但绝不能照抄（原先这类意见在评审节点记录后即被丢弃）。
        issue_block = ""
        if issues:
            issue_block = ("\n\n【评审未通过项（请修正或如实标注，不要沿用其中的可疑数据）】\n"
                           + issues)
        try:
            reply = llm.chat(
                [{"role": "system", "content": sys},
                 {"role": "user", "content": f"用户需求：{task}\n\n子 Agent 产出：\n{joined_short}{issue_block}"}],
                # timeout=30：综合要读全部子 Agent 产出、输出最长的一段，比拆解给得多，
                # 但仍短于默认 60s，避免 SSE 被中间层先掐断。超时会走下面的空产出降级。
                temperature=0.4, max_tokens=1500, timeout=30,
            )
        except Exception:
            reply = ""
        # 综合空/异常降级：把各子 Agent 完整产出直接交付，绝不丢结果
        if not (reply or "").strip():
            return ("主 Agent 综合未生成，以下为各子 Agent 的实际产出汇总：\n\n"
                    + joined_full)
        return reply


# ---------------------------------------------------------------- 工具函数


def _last_success(plan: list, results: dict):
    """从 plan 里找最后一个成功产出的 (step, output)；无则 (None, None)。"""
    for step in reversed(plan):
        r = results.get(step["id"])
        if r and r.get("output"):
            return step, r["output"]
    return None, None


# 评审首行协议：模型偶尔会把结论写成「**ISSUES**」「- ISSUES」「> ISSUES」，
# 精确 startswith 会漏判成通过，所以先剥掉行首的 markdown 强调/引用/列表符号。
_VERDICT_PREFIX_RE = re.compile(r"^[\s>*#`\-_]+")


def _review_verdict(review: str) -> str:
    """评审结论三态：``"issues"`` / ``"pass"`` / ``"unavailable"``。

    ``unavailable`` = **没有完成评审**（评审模型降级、返回哨兵或空、评审节点抛异常）。
    它绝不能与 ``pass`` 合并：合并之后「评审服务挂了」会静默变成「一律通过」，
    质量门看起来还在、实际已经失效。
    """
    s = (review or "").strip()
    if review_rules.is_degraded(s):
        return "unavailable"
    head = _VERDICT_PREFIX_RE.sub("", s.splitlines()[0])
    return "issues" if head.upper().startswith("ISSUES") else "pass"


def _review_failed(review: str) -> bool:
    """评审是否「不过」：**只有明确写 ISSUES 才算不过**。

    评审失败（空/异常/降级）故意不算不过——它不该惩罚已产出的内容，也不该引发
    重写风暴；但它也不再被当成「通过」，调用方用 `_review_verdict` 把这种状态
    单独识别出来，在最终输出里如实标注「本轮未完成质量评审」。
    """
    return _review_verdict(review) == "issues"


def _deliverable(text: str) -> bool:
    """产出是否「可以直接交付」。

    只拦**机械可判**的缺陷（空 / 哨兵 / 降级文案）——这三类没有任何解释空间。
    **刻意不含长度阈值**：planner 的短产出也可能是完整结论，用长度判会把好产出
    误杀（评审规则层历史上就吃过误报的亏，见 review_rules 的说明）。
    """
    return not review_rules.is_degraded(text)


def _annotate(output: str, issues: str) -> str:
    """把本轮未被消化的评审意见附在**直出**产出后面（评审三层之第三层）。

    规则判不过、但被评步骤不是 planner 时没有可重写的综合品，评审意见原本到此
    就丢了——用户拿到的是一份「已知有问题」的产出却毫不知情。附注让问题可见。
    LLM 综合路径不调用本函数：那条路径把意见写进提示词，由主 Agent 自行修正或标注。
    """
    if not issues:
        return output
    return (output or "") + "\n\n---\n⚠️ 评审提示（本轮未修复，请谨慎参考）：\n" + issues


def run_orchestration(task: str, emit=None, backend=None) -> tuple:
    """跑一次编排图，返回 (最终输出, 技能命中统计)。

    对外契约与迁移前的 SupervisorAgent.run 一致：事件序列、返回文本都不变。
    """
    emit = emit or (lambda e: None)
    emit({"type": "start"})
    graph = _build_graph(emit, backend)
    init: OrchestrationState = {"task": task, "thread_id": f"run-{uuid.uuid4().hex[:12]}"}
    final_state = graph.invoke(init)
    return final_state.get("output", "") or "", final_state.get("used_skills") or {}
