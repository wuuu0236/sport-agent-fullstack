"""分析师 Agent：查询训练库 + 计算心率区间/TRIMP/渐进超负荷趋势。

从 coach 拆出：只负责「基于真实训练数据算数」，不做知识问答、不写记录。
全部走确定性代码（sport_data），绝不编造数据——没记录就如实说没有。
"""
import re

from .base import BaseAgent
from .. import config
from ..sport_data import SportStore, hr_zone

_STORE = SportStore()


def user_max_hr():
    """从 USER.md 基线取最大心率；否则 220-年龄；再否则默认 190。"""
    try:
        txt = config.CONFIG.USER_FILE.read_text(encoding="utf-8")
    except Exception:
        txt = ""
    m = re.search(r"最大心率[：:\s]*(\d+)", txt)
    if m:
        return int(m.group(1))
    m = re.search(r"年龄[：:\s]*(\d+)", txt)
    if m:
        return 220 - int(m.group(1))
    return 190


class AnalystAgent(BaseAgent):
    name = "analyst"
    description = "训练数据分析：心率区间/配速/负荷(TRIMP)/力量渐进趋势"
    system_prompt = (
        "你是用户的训练分析师。基于真实的训练记录计算心率区间分布、配速、"
        "训练负荷与力量渐进超负荷趋势。没数据就说没数据，不编造、不推测。"
        "输出结构化、可行动的建议。"
    )

    def handle(self, user_msg: str, ctx: dict = None) -> str:
        # 力量动作名提取的停用字（避免「我深蹲有进步吗」取到『我』）
        stop = frozenset(
            "我你他她它们有没是否在来了吗么吧啊呀呢的得地很还也都就"
            "要想看看帮我最近一下进步分析力量训练容量趋势负荷怎么如何多少"
            "几次今天昨天上次这次那个这个再帮给让咱咱们您什刚才")
        known = []
        for r in _STORE.strengths():
            for ex in r.get("exercises", []):
                n = ex.get("name")
                if n and n not in known:
                    known.append(n)
        # 明确提到力量/动作 → 力量趋势
        if ("力量" in user_msg or "进步" in user_msg or "组" in user_msg
                or any(k in user_msg for k in known)):
            name = _exercise_name(user_msg, known, stop)
            if name:
                return _strength_report(name)
        # 提到跑步/心率/配速/训练/区间 数据词 → 跑步分析
        data_term = (
            "跑步" in user_msg or "心率" in user_msg or "配速" in user_msg
            or "训练" in user_msg or "区间" in user_msg or "zone" in user_msg.lower()
            or "负荷" in user_msg or "rpe" in user_msg.lower() or "trimp" in user_msg.lower()
        )
        if data_term and "概念" not in user_msg and "是什么" not in user_msg:
            return _run_report()
        # 都不是明确的分析请求 → 交给知识问答（expert）语义由 Supervisor 路由，这里给引导
        return (f"🔍 分析师需要明确的查询，例如：『分析我的跑步』『深蹲进步了吗』"
                f"『我的心率区间怎么样』。\n（收到：{user_msg}）")


def _exercise_name(msg: str, known: list, stop: frozenset) -> str:
    """提取动作名：A 精确匹配已入库动作（最稳），B 字符级扫描兜底。"""
    for k in sorted(known, key=len, reverse=True):
        if k in msg:
            return k
    for key in ("进步", "分析"):
        i = msg.find(key)
        if i != -1:
            run = []
            j = i - 1
            while j >= 0 and msg[j] not in stop:
                run.append(msg[j])
                j -= 1
            if run:
                return "".join(reversed(run))
    run = []
    for ch in msg:
        if ch in stop:
            if run:
                break
        else:
            run.append(ch)
    return "".join(run)


def _strength_report(name: str) -> str:
    t = _STORE.strength_trend(name)
    if t["trend"] == "first":
        return (f"『{name}』只有 {t['samples']} 次记录，先多积累几次再看渐进超负荷趋势。")
    arrow = {"up": "↑ 容量在涨（渐进超负荷，进步中）",
             "down": "↓ 容量下降（可能减载/疲劳，注意恢复）",
             "flat": "→ 容量持平（维持期）"}[t["trend"]]
    return (f"『{name}』最近 {t['samples']} 次：{arrow}（{t['delta_pct']:+}%）。")


def _run_report() -> str:
    runs = _STORE.runs()
    if not runs:
        return "还没有跑步记录，先让记录员记一次：『记一次5km跑步，配速6分，平均心率150』。"
    rec = runs[-1]
    max_hr = user_max_hr()
    a = _STORE.analyze_run(rec, max_hr)
    zone_lines = ("、".join(f"{z} {v}%" for z, v in a["zones"].items())
                  or "无心率序列数据")
    pace = f"{a['pace_min_km']} 分/km"
    load = f"{a['load']}" if a["load"] is not None else "—"
    return (f"最近一次跑步（{rec.get('date')}）：{rec.get('distance_km')}km，"
            f"配速 {pace}，平均心率 {a['avg_hr']}、最大 {a['max_hr']}，"
            f"RPE {a['rpe']}。\n心率区间分布：{zone_lines}。\n训练负荷(TRIMP)：{load}。"
            f"\n建议：有氧 base(Z2+Z3) 为主说明恢复充分；若 Z4/Z5 占比高，"
            f"下次安排恢复跑或休息。")
