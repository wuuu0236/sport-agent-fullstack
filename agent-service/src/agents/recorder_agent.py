"""记录员 Agent：训练/力量数据解析 → 暂存（workspace:isolated）。

从 coach 拆出：只负责「把口语/截图描述变成结构化记录」，不再管分析与知识问答。
写入走 SportStore 暂存队列，不直接落库——由 Supervisor 编排完成后统一确认提交，
防止解析误判直接污染真实训练库（对应图片导入 P0-3 的教训：解析结果必须过确认）。
确定性解析优先（执行门控），不依赖 LLM 自觉。
"""
import re
import datetime

from .base import BaseAgent
from .. import config
from ..sport_data import SportStore

_STORE = SportStore()

# 力量格式：动作 组数×次数×重量kg（如「深蹲 4组8次80kg」）
_STRENGTH_RE = re.compile(
    r"([一-龥A-Za-z]+)\s*(\d+)\s*组\s*(\d+)\s*次\s*(\d+)\s*kg")
# 跑步距离：5km / 5公里 / 5千米
_DIST_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:km|公里|千米)", re.I)
_PACE_RE = re.compile(r"配速[：:\s]*(\d+)\s*分")
# 注意：不能用 `re.compile(a) or re.compile(b)` 合并——编译对象恒为真值会短路，
# 第二个正则永远不生效。必须分开编译、运行时按序匹配。
_DUR_TIME_RE = re.compile(r"用时[：:\s]*(\d+(?:\.\d+)?)")
_DUR_MIN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*分钟")
_AVG_HR_RE = re.compile(r"平均心率[：:\s]*(\d+)")
_MAX_HR_RE = re.compile(r"最大心率[：:\s]*(\d+)")
_RPE_RE = re.compile(r"rpe[：:\s]*(\d+)", re.I)


class RecorderAgent(BaseAgent):
    name = "recorder"
    description = "训练/力量数据解析与记录（解析后暂存，待确认入库）"
    system_prompt = (
        "你是用户的训练记录员。负责把口语化的训练描述解析成结构化记录："
        "跑步（距离、配速、时长、心率、RPE）与力量（动作、组数、次数、重量）。"
        "解析不到关键字段就明确说明缺什么，绝不编造数据。"
    )

    def handle(self, user_msg: str, ctx: dict = None) -> str:
        run = _parse_run(user_msg)
        strength = _parse_strength(user_msg)
        if run is not None:
            _STORE.stage_run(**run)
            return _fmt_run(run) + "\n（已暂存待确认，Supervisor 确认后入库）"
        if strength is not None:
            _STORE.stage_strength(**strength)
            return _fmt_strength(strength) + "\n（已暂存待确认，Supervisor 确认后入库）"
        # 既不是明确的跑步也不是力量 → 引导用户补全字段
        if "跑" in user_msg or "公里" in user_msg or "km" in user_msg.lower():
            return ("没解析到距离。跑步记录需要距离，例如："
                    "『记一次5km跑步，配速6分，平均心率150』")
        if "kg" in user_msg or "组" in user_msg:
            return ("没解析到动作，请用格式：『深蹲 4组8次80kg，卧推 3组10次60kg』"
                    "我来记录力量训练。")
        return (f"🔍 记录员已收到请求：{user_msg}\n"
                "（这不是一条可解析的训练描述。记录训练请用："
                "『记一次5km跑步，配速6分，平均心率150』或『深蹲 4组8次80kg』。）")


def _parse_run(msg: str):
    """解析跑步记录；字段缺得太多（没距离）返回 None。"""
    if "跑" not in msg and "公里" not in msg and "km" not in msg.lower():
        return None
    m = _DIST_RE.search(msg)
    if not m:
        return None
    distance = float(m.group(1))
    p = _PACE_RE.search(msg)
    pace = int(p.group(1)) if p else None
    d = _DUR_TIME_RE.search(msg) or _DUR_MIN_RE.search(msg)
    duration = (float(d.group(1)) if d
                else (pace * distance if pace else 0.0))
    ah = _AVG_HR_RE.search(msg)
    mh = _MAX_HR_RE.search(msg)
    r = _RPE_RE.search(msg)
    return {
        "date": datetime.date.today().isoformat(),
        "distance_km": distance,
        "duration_min": duration,
        "avg_hr": int(ah.group(1)) if ah else 0,
        "max_hr": int(mh.group(1)) if mh else 0,
        "rpe": int(r.group(1)) if r else 0,
    }


def _parse_strength(msg: str):
    exs = []
    for m in _STRENGTH_RE.finditer(msg):
        exs.append({"name": m.group(1), "sets": int(m.group(2)),
                    "reps": int(m.group(3)), "weight_kg": int(m.group(4))})
    if not exs:
        return None
    return {"date": datetime.date.today().isoformat(), "exercises": exs,
            "note": msg[:50]}


def _fmt_run(run: dict) -> str:
    parts = [f"已解析一次跑步：{run['distance_km']}km",
             f"约 {run['duration_min']} 分钟" if run["duration_min"] else "时长未提供"]
    if run["avg_hr"] or run["max_hr"]:
        parts.append(f"平均心率 {run['avg_hr'] or '—'}、最大 {run['max_hr'] or '—'}")
    if run["rpe"]:
        parts.append(f"RPE {run['rpe']}")
    return "，".join(parts)


def _fmt_strength(s: dict) -> str:
    names = "、".join(
        f"{e['name']}({e['sets']}×{e['reps']}×{e['weight_kg']}kg)"
        for e in s["exercises"])
    return f"已解析力量训练：{names}"
