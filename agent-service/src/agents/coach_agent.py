"""专业教练 Agent：训练记录录入 + 心率/力量分析 + 结构化日志 + 周期化建议。"""
import re
from .base import BaseAgent
from .. import config, llm
from ..sport_data import SportStore, hr_zone

_STORE = SportStore()


def _user_max_hr():
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


class CoachAgent(BaseAgent):
    name = "coach"
    description = "专业教练：训练记录录入、心率区间/配速分析、力量渐进超负荷、周期化计划"
    system_prompt = (
        "你是专业的运动教练 Agent，精通跑步训练、心率区间（Z1–Z5）、配速、"
        "训练负荷（TRIMP）、力量渐进超负荷等运动科学知识。\n"
        "你能做两类事：\n"
        "1）分析用户的真实训练数据并给出可行动建议；\n"
        "2）用通俗语言解释运动科学概念（如心率区间含义、配速、恢复、训练周期等）。\n"
        "回答要简洁、专业、不说教；用户问概念就好好解释概念，不要硬塞训练记录；"
        "涉及用户数据时结合其真实记录举例。"
    )

    def handle(self, msg: str, ctx=None) -> str:
        action = self._classify(msg)
        # 结构化动作（mock / 真实模式一致：记录与分析是招牌功能，必须真落库、真计算）
        if action == "log_run":
            result = self._log_run(msg)
        elif action == "log_strength":
            result = self._log_strength(msg)
        elif action == "analyze_run":
            result = self._analyze_run()
        elif action == "analyze_strength":
            result = self._analyze_strength(msg)
        else:
            # 通用对话：真实模式用 LLM，mock 给引导语
            if config.CONFIG.mock_mode:
                return self._mock(msg)
            result = self._llm(self._build_prompt(msg), ctx=ctx or {})
            if not result or not result.strip():
                return ("我是你的教练 Agent，可以帮你：\n"
                        "· 记录训练：『记一次5km跑步，配速6分，平均心率150』\n"
                        "· 分析数据：『分析我的跑步』『深蹲进步了吗』\n"
                        "· 训练建议：告诉我你想了解哪方面（心率区间/配速/力量渐进/周期计划）")
            return result
        # 真实模式：在结构化结果之上让 LLM 补一句个性化建议（失败不影响主结果）
        if not config.CONFIG.mock_mode and result:
            try:
                tip = llm.chat(
                    [{"role": "system", "content":
                      "你是运动教练。基于下面的训练事实，只用一句话给补充建议，"
                      "务必完整通顺、不要重复已知数据、不要使用 Markdown 标题。"},
                     {"role": "user", "content": result}],
                    max_tokens=80, temperature=0.3,
                )
                if tip and not tip.startswith("[LLM"):
                    result = result + "\n\n💡 " + tip
            except Exception:
                pass
        return result

    # ---------- 录入 ----------
    def _log_run(self, msg):
        d = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|公里|千米)", msg, re.I)
        if not d:
            return ("没解析到距离。跑步记录需要距离，例如："
                    "『记一次5km跑步，配速6分，平均心率150』")
        distance = float(d.group(1))
        p = re.search(r"配速[：:\s]*(\d+)\s*分", msg)
        pace = int(p.group(1)) if p else None
        dur_m = (re.search(r"用时[：:\s]*(\d+(?:\.\d+)?)", msg)
                 or re.search(r"(\d+(?:\.\d+)?)\s*分钟", msg))
        # 时长：显式给出→用它；只给配速→距离×配速估算；都没给→0（不编造）
        duration = (float(dur_m.group(1)) if dur_m
                    else (pace * distance if pace else 0.0))
        # 心率：没提就不写（默认 0 → sport_data 的 has_hr=False，不算分布，避免假数据）
        ah = re.search(r"平均心率[：:\s]*(\d+)", msg)
        avg_hr = int(ah.group(1)) if ah else 0
        mh = re.search(r"最大心率[：:\s]*(\d+)", msg)
        max_hr = int(mh.group(1)) if mh else 0
        rm = re.search(r"rpe[：:\s]*(\d+)", msg, re.I)
        rpe = int(rm.group(1)) if rm else 0
        _STORE.add_run(self._today(), distance, duration, avg_hr, max_hr, rpe=rpe)
        parts = [f"已记录一次跑步：{distance}km",
                 f"约 {duration} 分钟" if duration else "时长未提供"]
        if avg_hr or max_hr:
            parts.append(f"平均心率 {avg_hr or '—'}、最大 {max_hr or '—'}")
        else:
            parts.append("未记录心率")
        if rpe:
            parts.append(f"RPE {rpe}")
        return ("，".join(parts) + "\n"
                "（下次说『分析我的跑步』可看心率区间与训练负荷；"
                "没填的心率/时长不会伪造进分析）")

    def _log_strength(self, msg):
        # 简易解析：动作 组数×次数×重量，例如「深蹲 4组8次80kg」
        exercises = []
        for m in re.finditer(r"([一-龥A-Za-z]+)\s*(\d+)\s*组\s*(\d+)\s*次\s*(\d+)\s*kg", msg):
            exercises.append({"name": m.group(1), "sets": int(m.group(2)),
                              "reps": int(m.group(3)), "weight_kg": int(m.group(4))})
        if not exercises:
            return ("没解析到动作，请用格式：『深蹲 4组8次80kg，卧推 3组10次60kg』"
                    "我来记录力量训练。")
        _STORE.add_strength(self._today(), exercises, note=msg[:50])
        names = "、".join(f"{e['name']}({e['sets']}×{e['reps']}×{e['weight_kg']}kg)" for e in exercises)
        return f"已记录力量训练：{names}。\n（下次说『深蹲进步了吗』可看渐进超负荷趋势）"

    # ---------- 分析 ----------
    def _analyze_run(self):
        runs = _STORE.runs()
        if not runs:
            return "还没有跑步记录，先说『记一次5km跑步，配速6分，平均心率150，最大170』吧。"
        rec = runs[-1]
        a = _STORE.analyze_run(rec, _user_max_hr())
        zone_lines = "、".join(f"{z} {v}%" for z, v in a["zones"].items()) or "无序列数据"
        return (f"最近一次跑步（{rec.get('date')}）：{rec.get('distance_km')}km，"
                f"配速 {a['pace_min_km']} 分/km，平均心率 {a['avg_hr']}、最大 {a['max_hr']}，"
                f"RPE {a['rpe']}。\n心率区间分布：{zone_lines}。\n训练负荷(TRIMP)：{a['load']}。"
                f"\n建议：有氧 base(Z2+Z3) 为主说明恢复充分；若 Z4/Z5 占比高，下次安排恢复跑或休息。")

    # 动作名提取时的停用字（代词/助词/意图词），避免「我深蹲有进步吗」取到『我』
    _CHAR_STOP = frozenset(
        "我你他她它们有没是否在来了吗么吧啊呀呢的得地很还也都就"
        "要想看看帮我最近一下进步分析力量训练容量趋势负荷怎么如何多少"
        "几次今天昨天上次这次那个这个再帮给让咱咱们您什刚才")

    def _exercise_name(self, msg):
        """从消息里提取动作名。策略A用已入库的动作名精确匹配（最稳，不依赖分词）；
        策略B做字符级扫描兜底（冷启动无记录时也够用）。"""
        # A：消息里含已入库的动作名 → 直接命中，取最长（避免「卧推」误中「卧推车」）
        known = []
        for r in _STORE.strengths():
            for ex in r.get("exercises", []):
                n = ex.get("name")
                if n and n not in known:
                    known.append(n)
        for k in sorted(known, key=len, reverse=True):
            if k in msg:
                return k
        # B1：优先取「进步/分析」前面的词：深蹲有进步吗 → 深蹲
        for key in ("进步", "分析"):
            i = msg.find(key)
            if i != -1:
                run = []
                j = i - 1
                while j >= 0 and msg[j] not in self._CHAR_STOP:
                    run.append(msg[j])
                    j -= 1
                if run:
                    return "".join(reversed(run))
        # B2：取开头第一个非停用字连续段：卧推怎么样 → 卧推
        run = []
        for ch in msg:
            if ch in self._CHAR_STOP:
                if run:
                    break
            else:
                run.append(ch)
        return "".join(run)

    def _analyze_strength(self, msg):
        name = self._exercise_name(msg)
        if not name:
            return ("想分析哪个动作？例如『深蹲进步了吗』『卧推分析』"
                    "——我来算渐进超负荷趋势。")
        t = _STORE.strength_trend(name)
        if t["trend"] == "first":
            return f"『{name}』只有 {t['samples']} 次记录，先多积累几次再看渐进超负荷趋势。"
        arrow = {"up": "↑ 容量在涨（渐进超负荷，进步中）",
                 "down": "↓ 容量下降（可能减载/疲劳，注意恢复）",
                 "flat": "→ 容量持平（维持期）"}[t["trend"]]
        return f"『{name}』最近 {t['samples']} 次：{arrow}（{t['delta_pct']:+}%）。"

    # ---------- 意图分类（mock / 真实模式共用）----------
    def _classify(self, msg):
        has_log = ("记" in msg or "录" in msg or "添加" in msg or "保存" in msg)
        is_strength_fmt = ("组" in msg and "次" in msg and "kg" in msg)
        if (has_log or is_strength_fmt) and "跑" not in msg:
            return "log_strength"
        if has_log and "跑" in msg:
            return "log_run"

        # 概念解释类：问「是什么 / 什么意思 / 解释 / 区别」等，
        # 交给 LLM 对话解答，不要误判成「分析数据」而硬塞训练记录。
        is_concept_q = any(k in msg for k in (
            "是什么", "什么意思", "意思是", "解释", "怎么理解", "含义",
            "指什么", "为什么", "区别", "如何定义", "科普", "讲讲", "说明", "怎么算",
        ))
        # 明确要求「分析 / 看我的 / 上次 / 最近」跑步数据 → 才走数据分析
        is_data_request = any(k in msg for k in (
            "分析", "我的", "上次", "最近", "这次", "看我的", "查询", "显示", "多少",
        ))
        data_term = (
            "跑步" in msg or "心率" in msg or "配速" in msg or "训练" in msg
            or "区间" in msg or "zone" in msg.lower()
            or any(f"z{i}" in msg.lower() for i in range(1, 6))
            or "trimp" in msg.lower() or "负荷" in msg or "rpe" in msg.lower()
        )

        if is_concept_q:
            return "chat"
        if data_term and is_data_request:
            return "analyze_run"
        if data_term:
            # 提到数据词但没明确要分析、也没问概念 → 默认展示分析（保留原有行为）
            return "analyze_run"
        if "力量" in msg or "渐进" in msg or "进步" in msg or "组" in msg:
            return "analyze_strength"
        # 短问题 + 命中动作名才归力量分析（卧推怎么样 → 卧推）；
        # 长句（如「刚才那个马拉松的问题，我想跑首马」）是聊天/上下文问答，别误判
        if len(msg) <= 12 and self._exercise_name(msg):
            return "analyze_strength"
        return "chat"

    # ---------- mock 分流 ----------
    def _mock(self, msg):
        action = self._classify(msg)
        if action == "log_strength":
            return self._log_strength(msg)
        if action == "log_run":
            return self._log_run(msg)
        if action == "analyze_run":
            return self._analyze_run()
        if action == "analyze_strength":
            return self._analyze_strength(msg)
        return ("我是你的教练 Agent。可以：\n"
                "· 记录：『记一次5km跑步，配速6分，平均心率150，最大170，rpe7』\n"
                "· 记录：『深蹲 4组8次80kg，卧推 3组10次60kg』\n"
                "· 分析：『分析我的跑步』『深蹲进步了吗』")

    @staticmethod
    def _today():
        return __import__("datetime").date.today().isoformat()

    def _build_prompt(self, msg):
        max_hr = _user_max_hr()
        runs = _STORE.runs()
        recent = _STORE.analyze_run(runs[-1], max_hr) if runs else None
        data = (f"用户最大心率基线：{max_hr}。\n"
                f"最近跑步分析：{recent}\n" if recent else "尚无跑步记录。")
        return (f"{data}\n用户消息：{msg}\n"
                f"请以专业教练口吻，给结构化训练日志与可行动建议（含心率区间/配速/负荷解读）。")
