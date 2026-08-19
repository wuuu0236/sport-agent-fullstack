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
        except Exception:
            pass

    # ---------- 读取 ----------
    def all(self):
        out = []
        try:
            for fn in sorted(self.dir.glob("*.json")):
                try:
                    out.append(json.load(open(fn, encoding="utf-8")))
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
