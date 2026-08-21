"""评审 Agent（Critic）：审查另一个 Agent 的产出质量。

对弈式多 Agent 协作（Generator-Critic）的「审」方：
  - 主循环执行完子任务后，派 reviewer 对最后一个成功产出做反向审查；
  - 审查维度：数据真实性 / 安全红线 / 完整性 / 幻觉；
  - 输出约定：第一行「PASS」= 通过；第一行「ISSUES」= 有问题（后续逐条列问题）；
    评审意见会反馈给生成方重写（主循环控制，最多重写 1 次）。

这是「代码门控模型」在质量维度的延伸：不止拦空输出/跑偏，还拦「答了但答得差」。
"""
from .base import BaseAgent
from .. import config


class ReviewerAgent(BaseAgent):
    name = "reviewer"
    description = "内容评审：审查 Agent 产出的数据真实性/安全/完整性/幻觉"
    system_prompt = (
        "你是内容评审 Agent（Critic）。负责审查另一个 Agent 产出的内容，找出问题。\n"
        "审查维度：\n"
        "1. 数据真实性：内容里的数据/事实是否与提供的材料一致，有无编造；\n"
        "2. 安全红线：训练/康复建议是否超出用户的伤病或体能限制（比如用户有伤还建议加大跑量）；\n"
        "3. 完整性：该覆盖的关键部分（数据、建议、计划）是否缺失；\n"
        "4. 幻觉：有无凭空编造的内容（不存在的训练记录、事件、来源）。\n\n"
        "输出格式（严格）：\n"
        "- 没有问题：第一行写 PASS，可附一句简短肯定；\n"
        "- 有问题：第一行写 ISSUES，然后逐条列出具体问题（每条一行，指出哪里不对）。"
    )

    def handle(self, user_msg: str, ctx: dict = None) -> str:
        if config.CONFIG.mock_mode:
            return "PASS 评审通过（mock 模式）"
        return self._llm(user_msg, ctx=ctx)
