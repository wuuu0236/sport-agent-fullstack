"""SupervisorAgent：主 Agent 编排的**对外门面**（2026-09-16 起内部为 LangGraph 图）。

历史：这里曾是一个手写主循环（拆解 → for 循环派发 → 评审 → 综合，约 240 行）。
现在编排逻辑迁到 `src/graph.py` 的 StateGraph（plan / validate / dispatch / review /
rewrite / synthesize 六个节点 + 条件边），本模块只保留对外的稳定契约：

    sv = SupervisorAgent()
    final = sv.run(task, emit=emit)   # emit 回调事件序列与迁移前逐字一致
    sv.used_skills                    # 本次各技能命中次数（供 /chat 回传 metadata）

事件序列未变（start / plan / agent_start / agent_done / agent_error / complete /
pending_commit），因此 Java 网关与前端看板无需任何改动。

为什么保留这层门面而不是让调用方直接用图：/chat、/supervise、SSE 三个入口都按
「建实例 → run → 读 used_skills」使用；门面把「图怎么建、状态怎么传」收在一处，
以后换 checkpointer / interrupt（P2）时调用方不用跟着改。
"""
from .graph import (  # noqa: F401  （re-export：兼容旧引用与测试）
    _REF_RE, _fallback_plan, _parse_plan, run_orchestration, validate_steps,
)
from .skill_loader import match_skills_for


class SupervisorAgent:
    name = "supervisor"

    def run(self, task: str, emit=None) -> str:
        """跑一次多 Agent 编排，返回最终输出文本。"""
        final, used = run_orchestration(task, emit)
        self.used_skills = used
        return final

    # 保留：编排路径的技能注入门控（与单 Agent 路径共用同一套判定）
    def _skills_for_step(self, agent_name: str, task: str) -> list:
        """技能注入门控：用**原始用户任务**匹配（step input 已被 @sN 填充过前序产出，
        噪声大会误命中），且 SKILL.md 声明了主理 agent 的只有本步 agent 与之相同才注入。"""
        return match_skills_for(task or "", agent_name)
