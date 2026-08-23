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
    """关键词兜底路由（新体系 agent 名）。

    健身域（跑步/减脂/增肌/练部位/动作/饮食/心率/伤痛康复/训练计划/概念）
    全部归 coach（谭成义唯一直答教练）。searcher 仅留「新闻/赛事/最新资料」等
    纯信息检索；planner 仅用于「周报」这类汇报表；其余健身意图一律 coach。
    """
    # 元动作优先：记忆 / 日程
    if any(k in msg for k in ("记得", "记住", "回忆", "我的偏好", "别忘了", "记下", "记着")):
        return "memory"
    if any(k in msg for k in ("提醒", "日程", "待办", "几点", "闹钟", "简报")):
        return "scheduler"
    # 记录训练（先于教练：『记一次5km』vs『今天怎么练胸』）
    has_record = any(k in msg for k in ("记一次", "记录", "保存", "入库", "添加"))
    is_strength_fmt = ("组" in msg and "次" in msg and "kg" in msg)
    if (has_record or is_strength_fmt) and (
            "跑" in msg or "公里" in msg or "km" in msg.lower() or is_strength_fmt):
        return "recorder"
    # 联网搜索（仅纯信息检索：新闻/赛事/最新资料；健身建议已全归 coach）
    if any(k in msg for k in ("搜", "查一下", "查查", "新闻", "资讯", "最新研究", "赛事",
                              "马拉松比赛", "比赛", "最新赛事", "消息")):
        return "searcher"
    # ---------- 健身域：谭成义唯一直答教练（覆盖一切训练/身体问题）----------
    if any(k in msg for k in (
            # 有氧 / 跑步
            "跑步", "跑", "公里", "km", "配速", "有氧", "hiit", "爬坡",
            # 部位 / 动作
            "胸", "背", "腿", "肩", "臂", "手臂", "核心", "腹", "臀", "腰",
            "力量", "卧推", "深蹲", "硬拉", "引体", "划船", "推举", "弯举",
            "动作", "标准", "发力", "泵感", "找不到感觉", "没感觉",
            # 目标 / 计划
            "增肌", "减脂", "减脂怎么", "增重", "塑形", "练肌肉", "刷脂",
            "怎么练", "如何练", "今天", "计划", "方案", "周期", "编排",
            "安排", "入门", "新手", "教我", "练了", "练得", "组数", "次数怎么",
            "训练日", "训练建议", "练胸", "练背", "练腿", "练肩",
            # 数据 / 负荷（含分析意图：进步/趋势/区间/负荷 → 也归 coach，由 coach 内部判断）
            "心率", "zone", "rpe", "区间", "负荷", "trimp", "渐进", "容量",
            "进步", "趋势", "练得如何", "增长", "退步", "分析", "我的跑步",
            "查询", "显示", "最近一次",
            # 饮食
            "吃", "饮食", "蛋白", "碳水", "热量", "减脂餐", "增肌餐",
            # 伤痛 / 康复（教练答 + 标红线，不再走 clinician 三 Agent 会诊）
            "膝盖", "下背", "圆肩", "体态", "疼痛", "康复", "受伤", "筋膜",
            "不适", "脚底", "脚踝", "跟腱", "拉伤", "扭伤", "酸", "疼",
            # 恢复
            "拉伸", "热身", "休息", "恢复",
    )):
        return "coach"
    # 概念解释（非健身常识类，健身概念已归 coach）
    if any(k in msg for k in ("是什么", "什么意思", "解释", "怎么理解", "含义",
                              "区别", "为什么", "怎么算", "科普", "讲讲")):
        return "expert"
    # 周报（汇报表，保留多步编排；训练计划已归 coach）
    if "周报" in msg:
        return "planner"
    # 写作
    if any(k in msg for k in ("写", "总结", "润色", "改", "文案", "起草")):
        return "writer"
    return "general"
