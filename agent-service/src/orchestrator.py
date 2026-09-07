"""SupervisorAgent：主 Agent 决策循环 —— 对齐 Claude Code 的主-从分发机制。

机制（照 Claude Code）：
  1. 主 Agent 持有全量上下文（记忆快照 + 会话历史 + 子 Agent 目录），亲自综合；
  2. _plan：用 LLM 把用户任务拆成结构化子任务（强 JSON schema）——
     拆解是「模型的判断」，但派发/执行是「代码的门控」；
  3. dispatch：显式把每个子任务派给对应子 Agent（同进程调用，独立上下文执行）；
  4. _review：回收子 Agent 摘要后判断是否已足够（MVP：靠模板 + 失败跳过兜底）；
  5. _synthesize：把各子 Agent 的半成品综合成最终答案。

工作空间隔离（workspace:isolated）：写库的子 Agent（recorder）把解析结果放进
SportStore 暂存队列，不直接落库；run 结束发 pending_commit 事件 + 输出附注，
由前端确认后 /commit 统一落库。这是「子 Agent 独立工作空间」在数据层的落地，
同时修复图片导入直接保存的 P0-3 回归。

失败门控：LLM 拆解失败/空返回 → 回退代码模板计划；子 Agent 失败 → 跳过并如实注明，
绝不把错误文本当产出喂给下一步，也不让 LLM 编造缺失的上下文。
"""
import json
import re

from . import config, llm, memory
from .agents import get_agent, agent_catalog
from .skill_loader import match_skills_for
from .sport_data import SportStore

# 步骤引用：input 里的 @s1 在执行时替换为 s1 的真实产出（截断防超长）
_REF_RE = re.compile(r"@(s\d+)")
_REF_TRUNC = 400

# 拆解强 schema：只允许输出 JSON 数组，每步含 id/agent/input/expect
_PLAN_PROMPT = """你是主 Agent（Supervisor），负责把一个用户任务拆成「由专业子 Agent 执行」的子任务。
只输出一个 JSON 数组（不要任何其他文字、不要 markdown 代码块）。每项格式：
{{"id": "s1", "agent": "子agent名", "input": "给该子agent的输入（含必要的上下文）", "expect": "期望产出"}}

可用子 Agent 及职责：
{catalog}

规则：
· 最多 4 步；能 1 步完成就不要拆多步；
· 只选用必要的子 Agent，不重复派同一角色；
· 有依赖的步骤在 input 里用「@{前序id}」引用其结果（如 @s1），执行时会替换成真实产出；
· 需要最新资料时派 searcher，需要用户训练数据时派 analyst，生成周报/计划时最后派 planner。"""

# 代码模板兜底（执行门控：拆解失败时用，保证永不空转）
def _fallback_plan(task: str) -> list:
    # 周报/计划类 → 检索 + 分析 + 编排
    if any(k in task for k in ("周报", "计划", "周期", "编排", "生成", "目标", "安排")):
        return [
            {"id": "s1", "agent": "searcher", "input": task,
             "expect": "最新训练方法与赛事资料"},
            {"id": "s2", "agent": "analyst", "input": "分析我的最近训练",
             "expect": "用户训练数据分析"},
            # s3 必须引用 @s1/@s2：否则拆解失败走兜底时，
            # planner 只拿到原始任务，前两步的资料与分析等于白跑
            {"id": "s3", "agent": "planner",
             "input": f"{task}\n\n请结合 @s1 的最新资料与 @s2 的训练数据分析，综合完成本任务",
             "expect": "综合成训练周报/计划"},
        ]
    # 单 agent 类：关键词路由给一个子 Agent
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
    # 提取第一个 [ ... ] 块
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        steps = json.loads(text[start:end + 1])
    except Exception:
        return []
    if not isinstance(steps, list) or not steps:
        return []
    valid = []
    for s in steps:
        if not isinstance(s, dict):
            continue
        agent = str(s.get("agent") or "").strip()
        if agent not in agent_catalog_names():
            continue
        valid.append({"id": str(s.get("id") or f"s{len(valid) + 1}"),
                      "agent": agent,
                      "input": str(s.get("input") or task_placeholder(s)),
                      "expect": str(s.get("expect") or "")})
    return valid[:6]


def agent_catalog_names() -> set:
    return {a["name"] for a in agent_catalog()}


def task_placeholder(step: dict) -> str:
    return "(子任务输入缺失)"


class SupervisorAgent:
    name = "supervisor"

    def run(self, task: str, emit=None) -> str:
        emit = emit or (lambda e: None)
        self.used_skills = {}  # 本次编排各步骤实际注入的技能（供上层输出 metadata）
        emit({"type": "start"})

        plan = self._plan(task)
        emit({"type": "plan", "steps": [s["agent"] for s in plan],
              "total": len(plan)})

        results = {}
        for i, step in enumerate(plan, 1):
            name = step["agent"]
            emit({"type": "agent_start", "agent": name, "step": i,
                  "total": len(plan)})
            try:
                out = self._dispatch(name, step["input"], results, task)
                results[step["id"]] = {"agent": name, "output": out}
                emit({"type": "agent_done", "agent": name, "step": i,
                      "total": len(plan),
                      "output": out[:200] + ("…" if len(out) > 200 else "")})
            except Exception as e:
                results[step["id"]] = {"agent": name, "output": None}
                emit({"type": "agent_error", "agent": name, "step": i,
                      "total": len(plan), "error": str(e)})

        # ---- 对弈式评审（Generator-Critic）：对最后一个成功产出评审，
        #      planner 产出不合格则按评审意见重写一次（代码门控在质量维度的延伸）----
        self._critic(task, plan, results, emit)

        final = self._synthesize(task, plan, results)
        # complete 事件携带最终输出 + final 标记（前端据此收尾渲染）
        emit({"type": "complete", "status": "ok" if final else "degraded",
              "output": final, "final": True})

        # 工作空间隔离的收尾：若有暂存记录，附注 + 事件供前端确认
        staged = SportStore().staged()
        if staged:
            note = (f"\n\n📥 本次编排解析出 {len(staged)} 条训练记录，"
                    f"等待确认后入库（暂存区，未落库）。")
            final = final + note if final else note
            emit({"type": "pending_commit", "count": len(staged),
                  "records": staged})
        return final

    # ---------- 拆解（模型的判断）----------
    def _plan(self, task: str) -> list:
        from .supervisor import _keyword_route
        # 健身域统一归 coach（谭成义唯一直答）：无论跑步/减脂/增肌/练部位/伤痛，
        # 不经多 Agent 拆分，单步直接交给 coach，由 coach 内部决定分析/对话/记录。
        # 这是用户明确的架构决定：所有健身问题都优先从蒸馏到的谭成义视角回答。
        if _keyword_route(task) == "coach":
            return [{"id": "s1", "agent": "coach", "input": task,
                     "expect": "以谭成义（铁馆老炮）口吻直接给训练建议/分析"}]
        if config.CONFIG.mock_mode:
            return _fallback_plan(task)
        # 周报类：多步汇报表（检索 + 分析 + 编排），保留多 Agent 协作价值
        if "周报" in task:
            return _fallback_plan(task)
        catalog = "\n".join(f"- {a['name']}：{a['description']}" for a in agent_catalog())
        prompt = _PLAN_PROMPT.replace("{catalog}", catalog)
        try:
            raw = llm.chat(
                [{"role": "system", "content": prompt},
                 {"role": "user", "content": task}],
                temperature=0.2, max_tokens=900,
            )
        except Exception:
            raw = ""
        plan = _parse_plan(raw)
        return plan if plan else _fallback_plan(task)

    # ---------- 派发（代码的执行）：子 Agent 隔离执行，只回收产出 ----------
    def _skills_for_step(self, agent_name: str, task: str) -> list:
        """编排路径的技能注入（2026-09-07）：原先一律传 skills:[]，子 Agent 全裸跑。

        与单 Agent 直答路径的两点不同：
        1. 用**原始用户任务**匹配，不用 step input——后者已被 @s1/@s2 替换进
           前序产出（可能含"心率""公里"等词），噪声大、容易误命中；
        2. 多一道门控：SKILL.md 声明了主理 agent 的，只有本步派发的 agent
           与之相同才注入（未声明的技能对所有步骤开放）。
           目的：避免把"解析入库"的 SOP 灌给 planner 造成跨职责串味——
           与 f7559d6 修的「技能 vs 人格冲突」同类，这里在入口就拦掉。
        """
        # 门控规则与单 Agent 路径共用（见 skill_loader.match_skills_for），
        # 避免两处各写一套判定、改一处漏一处。
        return match_skills_for(task or "", agent_name)

    def _dispatch(self, name: str, inp: str, results: dict, task: str = "") -> str:
        # 依赖引用解析：@s1 → 替换为 s1 的真实产出（隔离回收的产物，截断防超长）
        inp = _REF_RE.sub(
            lambda m: ((results.get(m.group(1)) or {}).get("output")
                       or f"({m.group(1)} 无结果)")[:_REF_TRUNC],
            inp or "")
        agent = get_agent(name)
        # 上下文隔离：子 Agent 各自带 system prompt，不重复注入技能；
        # 且关掉短期历史(use_history=False)让前缀稳定、更易命中 DeepSeek 缓存，
        # 记忆走按需召回(recall_mode="recall")只取最相关前 5 条，避免全量记忆重复计费。
        # 主 Agent 仍走全量记忆 + 吃缓存折扣（见 supervisor/server 主路径）。
        # 技能：按「用户任务 + 本步 agent 是否该技能的主理人」注入（见 _skills_for_step）。
        step_skills = self._skills_for_step(agent.name, task)
        for s in step_skills:
            self.used_skills.setdefault(s["name"], 0)
            self.used_skills[s["name"]] += 1
        out = agent.handle(
            inp,
            {"skills": step_skills, "use_history": False, "recall_mode": "recall"},
        )
        if not (out or "").strip():
            raise ValueError(f"{name} 返回空输出")
        # 识别 BaseAgent._llm 的空串兜底文案 → 视为「模型未生成」，判为失败
        # （否则 _synthesize 会把它当有效产出直接采用，用户拿到一句废话）
        if "（模型本次未生成内容）" in out:
            raise ValueError(f"{name} 模型未生成内容")
        return out

    # ---------- 对弈式评审（Generator-Critic）----------
    def _critic(self, task: str, plan: list, results: dict, emit) -> None:
        """对最后一个成功产出做反向评审；planner 产出不合格则按意见重写一次。

        评审是「代码门控」在质量维度的延伸：不止拦空输出/跑偏，还拦「答了但答得差」。
        评审失败不中断链路（不通过也能继续，只是不重写非 planner 节点），保证永不空转。
        """
        last_step, last_out = self._last_success(plan, results)
        if not last_out:
            return
        n = len(plan) + 1
        emit({"type": "agent_start", "agent": "reviewer", "step": n, "total": n})
        try:
            review = get_agent("reviewer").handle(
                f"用户需求：{task}\n\n待评审内容：\n{last_out}",
                {"skills": [], "use_history": False, "recall_mode": "recall"})
            emit({"type": "agent_done", "agent": "reviewer", "step": n, "total": n,
                  "output": (review or "")[:200]})
        except Exception as e:  # noqa: BLE001
            emit({"type": "agent_error", "agent": "reviewer", "step": n, "total": n,
                  "error": str(e)})
            return
        # 仅当「评审不过 + 被评节点是 planner」才重写一次（planner 产出本就是综合结果）
        if not self._review_failed(review) or last_step["agent"] != "planner":
            return
        emit({"type": "agent_start", "agent": "planner", "step": n, "total": n})
        try:
            rewrite = get_agent("planner").handle(
                f"请根据评审意见重写以下内容，修正所有问题：\n\n【评审意见】\n{review}\n\n【待重写内容】\n{last_out}",
                {"skills": [], "use_history": False, "recall_mode": "recall"})
            if (rewrite or "").strip() and "（模型本次未生成内容）" not in (rewrite or ""):
                results[last_step["id"]] = {"agent": "planner", "output": rewrite}
                emit({"type": "agent_done", "agent": "planner", "step": n, "total": n,
                      "output": rewrite[:200]})
            else:
                emit({"type": "agent_error", "agent": "planner", "step": n, "total": n,
                      "error": "重写失败（模型未生成），保留原产出"})
        except Exception as e:  # noqa: BLE001
            emit({"type": "agent_error", "agent": "planner", "step": n, "total": n,
                  "error": str(e)})

    @staticmethod
    def _last_success(plan: list, results: dict):
        """从 plan 里找最后一个成功产出的 (step, output)；无则 (None, None)。"""
        for step in reversed(plan):
            r = results.get(step["id"])
            if r and r.get("output"):
                return step, r["output"]
        return None, None

    @staticmethod
    def _review_failed(review: str) -> bool:
        """评审是否「不过」：仅首行 ISSUES 视为不过；评审异常/空/其他都视为通过
        （评审失败不该惩罚已产出的内容，也不该引发重写风暴）。"""
        s = (review or "").strip()
        if not s or "（模型本次未生成内容）" in s:
            return False
        return s.startswith("ISSUES")

    # ---------- 综合（主 Agent 亲自收口）----------
    def _synthesize(self, task: str, plan: list, results: dict) -> str:
        # 单步 → 该步产出即最终
        if len(plan) == 1:
            r = results.get(plan[0]["id"])
            return r["output"] if r and r.get("output") else "（子 Agent 未产出有效结果，请稍后重试。）"

        # 多步：最后一个成功步骤若是 planner，其产出已综合 → 直接采用
        for step in reversed(plan):
            r = results.get(step["id"])
            if r and r.get("output"):
                if step["agent"] == "planner":
                    return r["output"]
                break

        # 否则主 Agent 亲自综合所有半成品
        blocks, joined = [], []
        for step in plan:
            r = results.get(step["id"])
            if r and r.get("output"):
                blocks.append(f"【{r['agent']}】\n{r['output']}")
                joined.append(f"【{r['agent']}】\n{r['output'][:600]}")
        if not blocks:
            return "（所有子 Agent 节点均未产出有效结果，请稍后重试。）"
        joined_full = "\n\n".join(blocks)
        joined_short = "\n\n".join(joined)
        if config.CONFIG.mock_mode:
            return "主 Agent 已编排完成：\n\n" + joined_full
        # 主 Agent 综合也必须结合用户画像（兜底）：planner 偶发失败时，
        # 综合分支若不带画像，会生成忽略体态/伤病的计划，造成回归。
        memory.load()
        _items = memory.list_store("user") or []
        _profile = "\n".join(f"- {p}" for p in _items) if _items else "（暂无用户画像）"
        sys = ("你是主 Agent（Supervisor）。以下是各子 Agent 完成的任务半成品。"
               "请把它们综合成一份对用户直接可用的完整回答：结构清晰、口语化、"
               "如实引用真实产出；缺失的部分如实说明，不要编造。\n"
               f"用户画像（含体态/伤病/心率基线，务必结合，不可忽略）：\n{_profile}")
        try:
            reply = llm.chat(
                [{"role": "system", "content": sys},
                 {"role": "user", "content": f"用户需求：{task}\n\n子 Agent 产出：\n{joined_short}"}],
                temperature=0.4, max_tokens=1500,
            )
        except Exception as e:
            reply = ""
        # 综合空/异常降级：把各子 Agent 完整产出直接交付，绝不丢结果
        if not (reply or "").strip():
            return ("主 Agent 综合未生成，以下为各子 Agent 的实际产出汇总：\n\n"
                    + joined_full)
        return reply
