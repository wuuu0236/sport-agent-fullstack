"""写作 / 总结 Agent：写、总结、润色、改文案。"""
from .base import BaseAgent
from .. import config


class WriterAgent(BaseAgent):
    name = "writer"
    description = "写、总结、润色、改文案"
    system_prompt = (
        "你是用户的写作助理。负责起草、总结、润色、改写文案。"
        "产出直接可用，格式清晰。"
    )

    def handle(self, user_msg: str, ctx: dict) -> str:
        if config.CONFIG.mock_mode:
            return (
                "✍️ 写作 Agent 已收到请求。\n"
                f"· 你的要求：{user_msg}\n"
                "（MVP 阶段：配置 LLM_API_KEY 后，这里会由大模型直接产出草稿/总结。）"
            )
        return self._llm(user_msg, ctx=ctx)
