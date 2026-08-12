"""日程 / 提醒 Agent：解析提醒与待办意图并确认。"""
from .base import BaseAgent
from .. import config


class SchedulerAgent(BaseAgent):
    name = "scheduler"
    description = "设置提醒、日程、待办、每日简报"
    system_prompt = (
        "你是用户的日程与提醒助理。负责把用户的提醒/待办意图结构化，"
        "确认时间、事项，并说明会如何提醒（主动推送/每日简报）。"
    )

    def handle(self, user_msg: str, ctx: dict) -> str:
        if config.CONFIG.mock_mode:
            return (
                "📅 收到日程/提醒意图。\n"
                f"· 内容：{user_msg}\n"
                "（MVP 阶段：已记录意图；接企业微信后可通过『消息推送』在到点时主动提醒你。\n"
                " 后续可把提醒写入定时任务/日历系统。）"
            )
        return self._llm(user_msg, ctx=ctx)
