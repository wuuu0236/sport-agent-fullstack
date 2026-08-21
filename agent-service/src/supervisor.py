"""Supervisor（轻量路由）：供 /chat 单 Agent 路径的一次性意图路由 + skill 检测。

注意：真正的多 Agent 主从分发在 orchestrator.py 的 SupervisorAgent（/supervise）。
这里保留的是「一条消息 → 一个 Agent」的快速路由，供普通问答使用。
路由结果用新体系 agent 名（recorder/analyst/searcher/clinician/expert/planner/...）。
"""
from . import config, llm
from .agents import get_agent, get_all_agents, agent_catalog
from .skill_loader import match_skills

_ROUTING_PROMPT_TMPL = """你是一个个人助理的调度器。根据用户消息，判断它属于哪个专业 Agent 的职责。
可选 Agent 及其职责：
{catalog}
只回复一个英文单词（agent 名称），不要解释。"""


def route(user_msg: str) -> str:
    agents = get_all_agents()
    if config.CONFIG.mock_mode:
        return _keyword_route(user_msg)
    # 关键词快速路由先行（2026-08-20 优化）：
    # 明确的「记录/分析/记忆/搜索/伤病」等意图直接命中，省掉一次 LLM 路由调用（快 + 省 token）；
    # 只有关键词拿不准（返回 general）时才用 LLM 路由兜底，保证模糊请求的路由质量。
    kw = _keyword_route(user_msg)
    if kw != "general":
        return kw
    try:
        catalog = "\n".join(f"- {a['name']}：{a['description']}" for a in agent_catalog())
        name = llm.chat(
            [{"role": "system", "content": _ROUTING_PROMPT_TMPL.format(catalog=catalog)},
             {"role": "user", "content": user_msg}]
        ).strip().lower()
        if name in agents:
            return name
    except Exception:
        pass
    return kw


def detect_skills(user_msg: str):
    """返回命中当前消息的 skill 列表（供 server 注入 Agent 上下文）。"""
    return match_skills(user_msg)


def _keyword_route(msg: str) -> str:
    """关键词兜底路由（新体系 agent 名）。"""
    # 元动作优先：记忆 / 日程
    if any(k in msg for k in ("记得", "记住", "回忆", "我的偏好", "别忘了", "记下", "记着")):
        return "memory"
    if any(k in msg for k in ("提醒", "日程", "待办", "几点", "闹钟", "简报")):
        return "scheduler"
    # 记录训练（先于分析：『记一次5km』vs『分析我的跑步』）
    has_record = any(k in msg for k in ("记一次", "记录", "保存", "入库", "添加"))
    is_strength_fmt = ("组" in msg and "次" in msg and "kg" in msg)
    if (has_record or is_strength_fmt) and (
            "跑" in msg or "公里" in msg or "km" in msg.lower() or is_strength_fmt):
        return "recorder"
    # 分析数据
    if any(k in msg for k in ("分析", "我的跑步", "进步", "趋势", "区间", "负荷",
                              "查询", "显示", "最近一次", "配速")):
        if any(k in msg for k in ("跑步", "心率", "力量", "深蹲", "卧推", "训练", "zone", "rpe")):
            return "analyst"
    # 联网搜索
    if any(k in msg for k in ("搜", "查一下", "查查", "新闻", "资讯", "最新", "赛事",
                              "马拉松", "比赛", "消息")):
        return "searcher"
    # 体态/疼痛（安全门控优先级高）
    if any(k in msg for k in ("膝盖", "下背", "圆肩", "体态", "疼痛", "康复",
                              "受伤", "筋膜", "不适", "脚底")):
        return "clinician"
    # 概念解释
    if any(k in msg for k in ("是什么", "什么意思", "解释", "怎么理解", "含义",
                              "区别", "为什么", "怎么算", "科普")):
        return "expert"
    # 计划/周报
    if any(k in msg for k in ("周报", "计划", "周期", "编排", "生成", "目标")):
        return "planner"
    # 写作
    if any(k in msg for k in ("写", "总结", "润色", "改", "文案", "起草")):
        return "writer"
    return "general"
