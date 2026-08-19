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
            {"id": "s3", "agent": "planner", "input": task,
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
                out = self._dispatch(name, step["input"], results)
                results[step["id"]] = {"agent": name, "output": out}
                emit({"type": "agent_done", "agent": name, "step": i,
                      "total": len(plan),
                      "output": out[:200] + ("…" if len(out) > 200 else "")})
            except Exception as e:
                results[step["id"]] = {"agent": name, "output": None}
                emit({"type": "agent_error", "agent": name, "step": i,
                      "total": len(plan), "error": str(e)})

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
        if config.CONFIG.mock_mode:
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
    def _dispatch(self, name: str, inp: str, results: dict) -> str:
        # 依赖引用解析：@s1 → 替换为 s1 的真实产出（隔离回收的产物，截断防超长）
        inp = _REF_RE.sub(
            lambda m: ((results.get(m.group(1)) or {}).get("output")
                       or f"({m.group(1)} 无结果)")[:_REF_TRUNC],
            inp or "")
        agent = get_agent(name)
        # 上下文隔离：子 Agent 各自带 system prompt + 记忆快照，不重复注入技能
        out = agent.handle(inp, {"skills": []})
        if not (out or "").strip():
            raise ValueError(f"{name} 返回空输出")
        # 识别 BaseAgent._llm 的空串兜底文案 → 视为「模型未生成」，判为失败
        # （否则 _synthesize 会把它当有效产出直接采用，用户拿到一句废话）
        if "（模型本次未生成内容）" in out:
            raise ValueError(f"{name} 模型未生成内容")
        return out

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
        sys = ("你是主 Agent（Supervisor）。以下是各子 Agent 完成的任务半成品。"
               "请把它们综合成一份对用户直接可用的完整回答：结构清晰、口语化、"
               "如实引用真实产出；缺失的部分如实说明，不要编造。")
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
