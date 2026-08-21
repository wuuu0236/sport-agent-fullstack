"""Agent 注册表：集中管理所有子 Agent（面向 Supervisor 的叶子节点）。

按「能力 + 工具权限」切分（对齐 Claude Code 的 .claude/agents 思路）：
每个子 Agent 只管一件事，Supervisor 用 LLM 决定派谁 + 用代码执行。
coach 已拆成 recorder（记录）/ analyst（分析）/ expert（知识）；
research→searcher；posture→clinician；memory 同时注册 memorist 别名。

旧名保留为同一实例的别名键（memory/scheduler/research/posture），
server.py / demo.py 等旧调用点无需改动。
"""
from .memory_agent import MemoryAgent
from .scheduler_agent import SchedulerAgent
from .coach_agent import CoachAgent          # 兼容旧 import（server.py 用 _user_max_hr）
from .posture_agent import ClinicianAgent
from .research_agent import SearcherAgent
from .writer_agent import WriterAgent
from .general_agent import GeneralAgent
from .recorder_agent import RecorderAgent
from .analyst_agent import AnalystAgent
from .expert_agent import ExpertAgent
from .planner_agent import PlannerAgent
from .reviewer_agent import ReviewerAgent

# 新体系注册表（子 Agent = Supervisor 可派发的叶子）
_AGENTS = {
    a.name: a
    for a in [
        RecorderAgent(),
        AnalystAgent(),
        SearcherAgent(),
        ClinicianAgent(),
        ExpertAgent(),
        PlannerAgent(),
        MemoryAgent(),          # name = memory
        SchedulerAgent(),
        WriterAgent(),
        GeneralAgent(),
        ReviewerAgent(),        # name = reviewer（对弈式评审，见 orchestrator）
    ]
}
# 旧名别名（同一实例，保持旧调用点兼容）
_AGENTS["memorist"] = _AGENTS["memory"]
_AGENTS["research"] = _AGENTS["searcher"]
_AGENTS["posture"] = _AGENTS["clinician"]
_AGENTS["coach"] = _AGENTS["recorder"]      # 语义近似：记录主责

# 供 Supervisor 拆解时枚举的描述目录（Claude Code 风格：description 就是「何时派它」）
# reviewer 是主循环内部的评审节点，不展示给拆解 LLM（避免被当成普通子任务派发）。
AGENT_CATALOG = [
    {"name": name, "description": agent.description}
    for name, agent in _AGENTS.items()
    if name not in ("memorist", "research", "posture", "coach", "reviewer")  # 别名+内部节点不展示
]


def get_all_agents():
    return _AGENTS


def get_agent(name: str):
    return _AGENTS.get(name, _AGENTS["general"])


def agent_catalog() -> list:
    """Supervisor 拆解 prompt 用的子 Agent 目录。"""
    return AGENT_CATALOG
