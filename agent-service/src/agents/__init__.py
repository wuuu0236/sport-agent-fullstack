"""Agent 注册表：集中管理所有专业 Agent。"""
from .memory_agent import MemoryAgent
from .scheduler_agent import SchedulerAgent
from .coach_agent import CoachAgent
from .posture_agent import PostureAgent
from .research_agent import ResearchAgent
from .writer_agent import WriterAgent
from .general_agent import GeneralAgent

_AGENTS = {
    a.name: a
    for a in [
        MemoryAgent(),
        SchedulerAgent(),
        CoachAgent(),
        PostureAgent(),
        ResearchAgent(),
        WriterAgent(),
        GeneralAgent(),
    ]
}


def get_all_agents():
    return _AGENTS


def get_agent(name: str):
    return _AGENTS.get(name, _AGENTS["general"])
