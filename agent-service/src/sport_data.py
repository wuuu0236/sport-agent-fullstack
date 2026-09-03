"""运动数据层：手动录入训练记录 + 本地存储 + 分析接口（零依赖）。

数据来源是你自己的运动记录（手表/App 导出或直接录入），存本地 JSON，
不上传、无爬虫、无时效问题——直接解决「数据源麻烦 + 不时效」痛点。
"""
import json
import datetime
import threading
import uuid
from . import config

# 心率 5 区模型（基于最大心率 HRmax 百分比）
_ZONES = [
    (0, 60, "Z1恢复"),
    (60, 70, "Z2有氧燃脂"),
    (70, 80, "Z3有氧耐力"),
    (80, 90, "Z4无氧阈"),
    (90, 101, "Z5最大"),
]


def hr_zone(pct: float) -> str:
    for lo, hi, name in _ZONES:
        if lo <= pct < hi:
            return name
    return "Z5最大" if pct >= 90 else "Z1恢复"


# ---------------------------------------------------------------------------
# 暂存队列（模块级，跨实例共享）：训练记录先「暂存」再「确认提交」。
# 这是 Supervisor 编排里子 Agent「独立工作空间（workspace:isolated）」的数据层实现：
# recorder 等写库 Agent 只把解析结果放进暂存区，不直接污染真实训练库，
# 由 Supervisor 综合后 /commit 统一落库（防解析误判，对应图片导入 P0-3 教训）。
#
# 并发安全（2026-08-19 修复）：
#   · 所有对 _STAGED 的读写都走 _STAGED_LOCK（FastAPI 多线程下并发暂存/提交不丢不坏）；
#   · 每条暂存记录带唯一 _staged_id：前端确认时按 id 精确清除自己的记录，
#     不会把其他会话/请求的暂存一起清掉。
# ---------------------------------------------------------------------------
_STAGED = []
_STAGED_LOCK = threading.Lock()


def _stage(rec: dict) -> dict:
    rec = dict(rec)  # 拷贝，避免外部继续修改污染暂存内容
    rec["_staged_id"] = uuid.uuid4().hex
    with _STAGED_LOCK:
        _STAGED.append(rec)
    return rec


class SportStore:
    """本地训练记录存储 + 分析。"""

    def __init__(self):
        self.dir = config.CONFIG.MEMORY_DIR / "sessions"
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    # ---------- 写入 ----------
    def add_run(self, date, distance_km, duration_min, avg_hr, max_hr,
                hr_series=None, rpe=0, note=""):
        rec = {"type": "run", "date": date, "distance_km": distance_km,
               "duration_min": duration_min, "avg_hr": avg_hr, "max_hr": max_hr,
               "hr_series": hr_series or [], "rpe": rpe, "note": note}
        self._save(rec)
        return rec

    def add_strength(self, date, exercises, rpe=0, note=""):
        # exercises: list of {name, sets, reps, weight_kg}
        rec = {"type": "strength", "date": date, "exercises": exercises,
               "rpe": rpe, "note": note}
        self._save(rec)
        return rec

    # ---------- 暂存（隔离工作空间的数据层：不落库，待确认）----------
    def stage_run(self, date, distance_km, duration_min, avg_hr, max_hr,
                  hr_series=None, rpe=0, note=""):
        return _stage({"type": "run", "date": date, "distance_km": distance_km,
                       "duration_min": duration_min, "avg_hr": avg_hr,
                       "max_hr": max_hr, "hr_series": hr_series or [],
                       "rpe": rpe, "note": note})

    def stage_strength(self, date, exercises, rpe=0, note=""):
        return _stage({"type": "strength", "date": date, "exercises": exercises,
                       "rpe": rpe, "note": note})

    def staged(self) -> list:
        """当前暂存队列快照（供 Supervisor/前端确认用）。"""
        with _STAGED_LOCK:
            return list(_STAGED)

    def commit_staged(self) -> int:
        """确认提交：把暂存记录全部落库，返回条数。"""
        n = 0
        while True:
            with _STAGED_LOCK:
                if not _STAGED:
                    break
                rec = _STAGED.pop(0)
            if rec.get("type") == "run":
                self.add_run(rec["date"], rec.get("distance_km") or 0,
                             rec.get("duration_min") or 0, rec.get("avg_hr") or 0,
                             rec.get("max_hr") or 0, hr_series=rec.get("hr_series"),
                             rpe=rec.get("rpe") or 0, note=rec.get("note") or "")
            elif rec.get("type") == "strength":
                self.add_strength(rec["date"], rec.get("exercises") or [],
                                  rpe=rec.get("rpe") or 0, note=rec.get("note") or "")
            n += 1
        return n

    def discard_staged(self, ids: list = None) -> int:
        """清除暂存。ids=None 清空全部；传 _staged_id 列表时只清匹配项
        （前端确认的那批记录），不影响其他会话/请求的暂存。返回清除条数。"""
        with _STAGED_LOCK:
            if ids is None:
                n = len(_STAGED)
                _STAGED.clear()
                return n
            id_set = set(ids)
            keep = [r for r in _STAGED if r.get("_staged_id") not in id_set]
            n = len(_STAGED) - len(keep)
            _STAGED[:] = keep
            return n

    def _save(self, rec):
        # 微秒级时间戳：同一秒内多条记录（批量导入/连续提交）不会互相覆盖丢数据
        stamp = datetime.datetime.now().strftime("%H%M%S%f")
        fn = self.dir / f"{rec['type']}_{rec['date']}_{stamp}.json"
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
        except Exception as e:
            # 训练记录写失败绝不能静默：用户练了但库里没有，属于无声数据丢失
            print(f"[SportStore] 训练记录落盘失败 {fn.name}: {e}", flush=True)

    # ---------- 读取 ----------
    def all(self):
        out = []
        try:
            for fn in sorted(self.dir.glob("*.json")):
                try:
                    with open(fn, encoding="utf-8") as f:
                        out.append(json.load(f))
                except Exception:
                    pass
        except Exception:
            pass
        return out

    def runs(self):
        return [r for r in self.all() if r.get("type") == "run"]

    def strengths(self):
        return [r for r in self.all() if r.get("type") == "strength"]

    # ---------- 分析 ----------
    def analyze_run(self, rec, max_hr=190):
        """心率区间分布 + 配速 + 训练负荷（TRIMP≈时长×强度）。

        has_hr 标记：仅当记录确实带有心率（逐拍序列或 avg_hr>0）时才计算区间；
        否则返回空区间 + has_hr=False，绝不编造心率分布。
        （华为运动健康「导出路线文件」GPX 实测不含心率，即此情况。）
        """
        has_hr = bool(rec.get("hr_series")) or (rec.get("avg_hr") or 0) > 0
        if not has_hr:
            d = rec.get("distance_km") or 1
            dur = rec.get("duration_min") or 0
            return {"zones": {}, "pace_min_km": round(dur / d, 2) if d else 0,
                    "load": None, "avg_hr": rec.get("avg_hr"), "max_hr": rec.get("max_hr"),
                    "rpe": rec.get("rpe"), "hrmax": max_hr, "has_hr": False}
        hr = rec.get("hr_series") or []
        if not hr:
            # 无逐拍序列但给了 avg/max（手动录入场景），按热身-主跑-冷却模拟一段
            base = rec.get("avg_hr", 0) or 0
            mx = rec.get("max_hr", 0) or base
            hr = [base-15, base-8, base-2, base+3, mx-12, mx-6, base, base-5, base-10, base-15]
            hr = [max(h, 1) for h in hr]
        dist = {}
        for b in hr:
            if not b:
                continue
            z = hr_zone(b / max_hr * 100)
            dist[z] = dist.get(z, 0) + 1
        total = sum(dist.values()) or 1
        zone_pct = {z: round(c / total * 100, 1) for z, c in dist.items()}
        d = rec.get("distance_km") or 1
        dur = rec.get("duration_min") or 0
        pace = round(dur / d, 2) if d else 0
        intensity = (rec.get("avg_hr", 0) / max_hr) if max_hr else 0
        load = round(dur * intensity, 1)
        return {"zones": zone_pct, "pace_min_km": pace, "load": load,
                "avg_hr": rec.get("avg_hr"), "max_hr": rec.get("max_hr"),
                "rpe": rec.get("rpe"), "hrmax": max_hr, "has_hr": True}

    def strength_trend(self, exercise_name):
        """同一动作最近几次容量（sets*reps*weight）趋势，判断渐进超负荷。"""
        rows = []
        for r in self.strengths():
            for ex in r.get("exercises", []):
                if ex.get("name") == exercise_name:
                    cap = ex.get("sets", 0) * ex.get("reps", 0) * ex.get("weight_kg", 0)
                    rows.append((r.get("date"), cap, ex))
        rows.sort(key=lambda x: x[0])
        if len(rows) < 2:
            return {"name": exercise_name, "samples": len(rows), "trend": "first",
                    "latest": rows[-1][2] if rows else None}
        last, prev = rows[-1][1], rows[-2][1]
        delta = (last - prev) / prev if prev else 0
        trend = "up" if delta > 0.05 else ("down" if delta < -0.05 else "flat")
        return {"name": exercise_name, "samples": len(rows), "trend": trend,
                "delta_pct": round(delta * 100, 1),
                "latest": rows[-1][2], "prev": rows[-2][2]}

    # ---------- 周聚合（多 Agent 会诊的「硬数据」地基）----------
    @staticmethod
    def _parse_date(rec: dict):
        """解析记录的 date 字段；无法解析返回 None（日期绝不猜、绝不兜底成今天）。"""
        raw = str(rec.get("date") or "").strip()
        if not raw:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.datetime.strptime(raw[:19], fmt).date()
            except ValueError:
                continue
        return None

    def weekly_summary(self, weeks: int = 3, max_hr: int = 190) -> list:
        """按 ISO 周聚合跑量/时长/负荷，返回最近 weeks 个「有记录」的周（由旧到新）。

        只统计真实存在的记录：某周没跑就不出现在结果里，不补零、不插值、不编造。
        load 仅在记录带心率时才有值（沿用 analyze_run 的 has_hr 约定），否则为 None。
        """
        buckets = {}
        for r in self.runs():
            d = self._parse_date(r)
            if d is None:
                continue
            iso = d.isocalendar()
            key = (iso[0], iso[1])
            b = buckets.setdefault(key, {"km": 0.0, "min": 0.0, "load": 0.0,
                                         "count": 0, "has_hr": False,
                                         "start": None, "end": None})
            b["km"] += float(r.get("distance_km") or 0)
            b["min"] += float(r.get("duration_min") or 0)
            a = self.analyze_run(r, max_hr)
            if a.get("load") is not None:
                b["load"] += float(a["load"])
                b["has_hr"] = True
            b["count"] += 1
            s = d.isoformat()
            b["start"] = s if b["start"] is None or s < b["start"] else b["start"]
            b["end"] = s if b["end"] is None or s > b["end"] else b["end"]
        if not buckets:
            return []
        out = []
        for key in sorted(buckets.keys())[-weeks:]:
            b = buckets[key]
            out.append({
                "iso_year": key[0], "iso_week": key[1],
                "start": b["start"], "end": b["end"],
                "runs": b["count"],
                "km": round(b["km"], 2),
                "min": round(b["min"], 1),
                "load": round(b["load"], 1) if b["has_hr"] else None,
                "has_hr": b["has_hr"],
            })
        return out

    def daily_load(self, days: int = 28, max_hr: int = 190) -> dict:
        """最近 days 天里，每天的训练负荷（TRIMP）；只含真正有带心率记录的日期。

        不带心率的记录不参与（load 为 None），绝不拿距离或时长硬凑负荷。
        """
        today = datetime.date.today()
        start = today - datetime.timedelta(days=days - 1)
        out = {}
        for r in self.runs():
            d = self._parse_date(r)
            if d is None or d < start or d > today:
                continue
            a = self.analyze_run(r, max_hr)
            if a.get("load") is None:
                continue
            out[d.isoformat()] = out.get(d.isoformat(), 0.0) + float(a["load"])
        return dict(sorted(out.items()))

    def acwr(self, max_hr: int = 190) -> dict:
        """急性:慢性负荷比（ACWR）——运动医学通用的伤病风险指标。

        急性 = 最近 7 天负荷；慢性 = 最近 28 天负荷 / 4（周均）。
        阈值是代码里的硬规则，不交给模型判断：
          >1.5 高危（过载）｜1.3~1.5 偏高｜0.8~1.3 安全区｜<0.8 训练不足或减量期。
        数据不足以支撑计算时如实返回 status，绝不估算一个比值出来。
        """
        daily = self.daily_load(days=28, max_hr=max_hr)
        if not daily:
            return {"status": "empty", "risk": "unknown",
                    "message": "最近 28 天没有带心率的训练记录，算不出负荷"}

        def _sum(days_back: int) -> float:
            s = (datetime.date.today() - datetime.timedelta(days=days_back - 1)).isoformat()
            return sum(v for k, v in daily.items() if k >= s)

        today_s = datetime.date.today().isoformat()
        acute = _sum(7)
        chronic = _sum(28) / 4.0
        base = {"acute_load": round(acute, 1), "chronic_load": round(chronic, 1),
                "days_with_data": len(daily), "latest_date": max(daily.keys()),
                "stale_days": (datetime.date.today()
                               - datetime.date.fromisoformat(max(daily.keys()))).days}
        # 数据陈旧优先判定：最近一次训练距今过久，任何负荷趋势结论都不可信，
        # 绝不拿「很久没练」冒充「训练不足」——这两者对会诊的含义完全不同。
        if base["stale_days"] > 14:
            base.update({"status": "stale", "acwr": None, "risk": "unknown",
                         "message": (f"最近一次记录是 {base['stale_days']} 天前，"
                                     f"数据已过期，无法判断当前负荷趋势")})
            return base
        if chronic <= 0:
            base.update({"status": "insufficient", "acwr": None, "risk": "unknown",
                         "message": "近 28 天训练太少，慢性负荷为 0，比值不可用"})
            return base
        ratio = acute / chronic
        risk = ("high" if ratio > 1.5 else
                "elevated" if ratio >= 1.3 else
                "low" if ratio >= 0.8 else "detraining")
        base.update({"status": "ok", "acwr": round(ratio, 2), "risk": risk,
                     "today": today_s})
        return base

    def week_over_week(self, max_hr: int = 190) -> dict:
        """最近两个「有记录」的 ISO 周对比（跑量/时长/负荷 + 增幅%）。

        数据不足或心率缺失时如实标注 status，绝不估算——这是伤痛会诊里
        「单周增幅 >10% 触发安全驳回」硬规则的唯一数据来源，只能由代码算。
        """

        def _pct(a, b):
            if a is None or b is None or not b:
                return None
            return round((a - b) / b * 100, 1)

        weeks = self.weekly_summary(weeks=2, max_hr=max_hr)
        if not weeks:
            return {"status": "empty", "message": "还没有任何跑步记录"}
        if len(weeks) < 2:
            return {"status": "insufficient", "weeks": weeks,
                    "message": "只有一个周有记录，无法做周环比"}
        prev, cur = weeks[-2], weeks[-1]
        gap = (cur["iso_year"] - prev["iso_year"]) * 52 + (cur["iso_week"] - prev["iso_week"])
        return {
            "status": "ok",
            "prev": prev, "cur": cur,
            "gap_weeks": gap,
            "contiguous": gap == 1,
            "km_delta_pct": _pct(cur["km"], prev["km"]),
            "min_delta_pct": _pct(cur["min"], prev["min"]),
            "load_delta_pct": _pct(cur["load"], prev["load"]),
        }
