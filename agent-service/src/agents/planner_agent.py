"""计划编排 Agent：综合「检索资料 + 训练分析 + 运动知识 + 用户目标」产出周期计划/周报。

创作型角色：本身不搜、不算，只做综合。输入是 Supervisor 喂给它的多源半成品
（研究要点 / 数据分析 / 用户需求），它负责把碎片拼成一份结构化、可执行、口语化的
训练周报或周期计划。资料缺失时如实注明，不编造。
"""
from .base import BaseAgent
from .. import config


class PlannerAgent(BaseAgent):
    name = "planner"
    description = "训练计划编排：周期化计划、周报（综合资料+分析+目标）"
    system_prompt = (
        "你是用户的训练计划编排专家。负责把检索到的训练资料、用户真实训练数据"
        "与训练目标综合成一份结构化、可执行、口语化的训练周报或周期计划。\n"
        "原则：\n"
        "· 基于提供的资料与分析，不编造来源和数据；缺失的部分如实注明；\n"
        "· 给可量化的安排（距离/配速/组数/次数/心率区间）；\n"
        "· 结构清晰、口语化、能直接读给用户听。"
    )

    def handle(self, user_msg: str, ctx: dict = None) -> str:
        if config.CONFIG.mock_mode:
            return (
                "📋 计划编排 Agent 已收到请求。\n"
                f"· 用户需求：{user_msg}\n"
                "（离线演示：配置 LLM_API_KEY 后，这里会综合资料+数据+目标生成周报。）"
            )
        return self._llm(user_msg, ctx=ctx or {})
