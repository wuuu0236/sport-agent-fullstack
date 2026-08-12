"""通用 Agent：闲聊、通用问答、兜底。"""
from .base import BaseAgent
from .. import config


class GeneralAgent(BaseAgent):
    name = "general"
    description = "闲聊、通用问答、其他"
    system_prompt = (
        "你是用户的通用助理，友好、简洁、像靠谱朋友。回答不确定的事就直说，不瞎编。"
    )

    def handle(self, user_msg: str, ctx: dict) -> str:
        if config.CONFIG.mock_mode:
            return (
                "👋 通用 Agent 收到。\n"
                f"· 你说：{user_msg}\n"
                "（MVP 阶段：配置 LLM_API_KEY 后即可正常闲聊/问答。）"
            )
        return self._llm(user_msg, ctx=ctx)
