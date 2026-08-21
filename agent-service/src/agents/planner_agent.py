"""计划编排 Agent：综合「检索资料 + 训练分析 + 运动知识 + 用户目标」产出周期计划/周报。

创作型角色：本身不搜、不算，只做综合。输入是 Supervisor 喂给它的多源半成品
（研究要点 / 数据分析 / 用户需求），它负责把碎片拼成一份结构化、可执行、口语化的
训练周报或周期计划。资料缺失时如实注明，不编造。
"""
from .base import BaseAgent
from .. import config, memory


class PlannerAgent(BaseAgent):
    name = "planner"
    description = "训练计划编排：周期化计划、周报（综合资料+分析+目标）"
    system_prompt = (
        "你是用户的训练计划编排专家。负责把用户的运动目标、身体限制（如有伤病/体态问题）"
        "与运动科学知识综合成一份结构化、可执行、口语化的训练计划。\n"
        "原则：\n"
        "· 不编造来源和数据；没有外部资料时基于运动科学常识直接给出计划；\n"
        "· 给可量化的安排（距离/配速/组数×次数/心率区间/热量缺口/蛋白质）；\n"
        "· 结合用户画像中的伤病/体态限制，给出动作替换和保护提示；\n"
        "· 结构清晰、口语化、能直接读给用户听。"
    )

    def handle(self, user_msg: str, ctx: dict = None) -> str:
        if config.CONFIG.mock_mode:
            return (
                "📋 计划编排 Agent 已收到请求。\n"
                f"· 用户需求：{user_msg}\n"
                "（离线演示：配置 LLM_API_KEY 后，这里会综合资料+数据+目标生成周报。）"
            )
        # 构造明确请求：把用户目标和画像限制一起传给 LLM，
        # 避免模型因"没被提供资料"而迷茫、偶发空回复。
        prompt = self._build_plan_prompt(user_msg)
        return self._llm(prompt, ctx=ctx or {})

    def _build_plan_prompt(self, user_msg: str) -> str:
        # 计划必须考虑身体限制——强制全量注入用户画像，不依赖相关性召回。
        # 否则『减脂计划』语义上召回不到『高低肩/膝痛』等关键限制，
        # planner 会误判为『没有提供伤病/体态』而忽略，造成计划回归。
        memory.load()
        items = memory.list_store("user") or []
        profile = "\n".join(f"- {p}" for p in items) if items else "（暂无用户画像记录）"
        return (
            f"请根据以下用户画像和运动目标，生成一份结构化、可执行的训练计划。\n\n"
            f"【用户目标】\n{user_msg}\n\n"
            f"【用户画像（含体态/伤病/心率基线，务必结合，不可忽略）】\n{profile}\n\n"
            f"要求：\n"
            f"1. 若目标含减脂/增肌，给出热量缺口/盈余、蛋白质建议、有氧安排；\n"
            f"2. 若目标含三分化/五分化/全身训练，列出每周分化安排、具体动作、组数×次数；\n"
            f"3. 结合画像中的体态问题或伤病，做动作替换或保护提示；\n"
            f"4. 所有安排必须量化；结构清晰，用 Markdown 表格/列表呈现。"
        )
