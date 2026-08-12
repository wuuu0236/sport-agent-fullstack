"""Supervisor：意图路由 + skill 检测。优先 LLM 分类，无 key 时关键词兜底。"""
from . import config, llm
from .agents import get_agent, get_all_agents
from .skill_loader import match_skills

ROUTING_PROMPT = """你是一个个人助理的调度器。根据用户消息，判断它属于哪个专业 Agent 的职责。
可选 Agent 及其职责：
- memory：记住/回忆关于用户的事实、偏好、待办
- scheduler：设置提醒、日程、待办、每日简报
- coach：训练记录录入、心率/配速分析、力量渐进超负荷、周期化计划
- posture：跑步膝/下背/体态等疼痛排查、康复动作、就医红线
- research：联网搜索资料、新闻、最新信息
- writer：写、总结、润色、改文案
- general：闲聊、通用问答、其他
只回复一个英文单词（agent 名称），不要解释。"""


def route(user_msg: str) -> str:
    agents = get_all_agents()
    if config.CONFIG.mock_mode:
        return _keyword_route(user_msg, agents)
    try:
        name = llm.chat(
            [{"role": "system", "content": ROUTING_PROMPT}, {"role": "user", "content": user_msg}]
        ).strip().lower()
        if name in agents:
            return name
    except Exception:
        pass
    return _keyword_route(user_msg, agents)


def detect_skills(user_msg: str):
    """返回命中当前消息的 skill 列表（供 server 注入 Agent 上下文）。"""
    return match_skills(user_msg)


def _keyword_route(msg: str, agents) -> str:
    rules = [
        (["记得", "记住", "回忆", "我的偏好", "别忘了", "记下"], "memory"),
        (["提醒", "日程", "待办", "计划", "几点", "闹钟", "简报"], "scheduler"),
        (["跑步", "心率", "配速", "力量", "深蹲", "卧推", "训练", "教练", "记录", "记一次", "渐进", "容量", "拉伸"], "coach"),
        (["膝盖", "下背", "圆肩", "体态", "疼痛", "康复", "受伤", "筋膜", "不适"], "posture"),
        (["搜", "查一下", "新闻", "资讯", "最新", "查查"], "research"),
        (["写", "总结", "润色", "改", "文案", "起草", "帮我写"], "writer"),
    ]
    for kws, name in rules:
        if any(k in msg for k in kws):
            return name
    return "general"
