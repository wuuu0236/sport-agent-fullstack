"""运动数据层：手动录入训练记录 + 本地存储 + 分析接口（零依赖）。

数据来源是你自己的运动记录（手表/App 导出或直接录入），存本地 JSON，
不上传、无爬虫、无时效问题——直接解决「数据源麻烦 + 不时效」痛点。
"""
import json
import datetime
import sqlite3
import uuid
from contextlib import contextmanager

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
# 暂存队列（SQLite，跨实例 / 跨重启共享）：训练记录先「暂存」再「确认提交」。
# 这是 Supervisor 编排里子 Agent「独立工作空间（workspace:isolated）」的数据层实现：
# recorder 等写库 Agent 只把解析结果放进暂存区，不直接污染真实训练库，
# 由 Supervisor 综合后 /commit 统一落库（防解析误判，对应图片导入 P0-3 教训）。
#
# 为什么从「进程内 list + threading.Lock」迁到 SQLite（2026-09-16，方案 P2）：
#   · **进程内 list 服务一重启就全丢**。「记录训练 → 看到待确认卡片 → 还没点确认就
#     重启/更新服务」这条路径下，解析结果会无声消失，而本项目重启服务是常态。
#   · 并发保护交给 SQLite 的 WAL，**手写 _STAGED_LOCK 拿掉**（与记忆层同一思路：
#     靠人工记得加锁，漏一次就是竞态）。
#   · 每条暂存记录仍带唯一 _staged_id：前端确认时按 id 精确清除自己的记录，
#     不会把其他会话/请求的暂存一起清掉。
#   · 确认侧是「**原子抢占 + 先落库后出队**」（2026-09-16 复查补的）：status 字段
#     把「写盘途中」显式化，避免两个请求同时确认时把同一条记录写进训练库两次；
#     抢占用租期兜底，抢占方崩溃不会让记录永久卡死。详见 _claim_first_staged。
# 范围提醒：训练记录本身（runs / strengths）仍是 data/sessions 下的 JSON，本次不动，
#           只迁暂存队列——改动面越小越好验证。
# ---------------------------------------------------------------------------

def _staged_db_path():
    """暂存库路径。

    **故意写成函数而非模块级常量**：路径若在 import 时按 MEMORY_DIR 算死，测试里
    patch `config.CONFIG.MEMORY_DIR` 就隔离不掉它，会写进真实 `data/`
    （记忆层的 `MEMORY_DB` 正是这个坑，测试必须额外 patch 一次）。每次调用现算，
    与 `SportStore.__init__` 里 `self.dir` 的算法保持一致。
    """
    return config.CONFIG.MEMORY_DIR / "staged.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS staged (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    staged_id  TEXT NOT NULL UNIQUE,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'staged',
    claimed_at TEXT
);
"""

# 老库（P2 首版）只有前四列。CREATE TABLE IF NOT EXISTS 不会补列，得显式 ALTER。
_MIGRATIONS = (
    "ALTER TABLE staged ADD COLUMN status TEXT NOT NULL DEFAULT 'staged'",
    "ALTER TABLE staged ADD COLUMN claimed_at TEXT",
)
_MIGRATED = set()

# 确认状态的取值：staged = 待确认；committing = 已被某次确认抢占（正在写盘）。
_ROWS = "status='staged'"
# 抢占租期（秒）：抢占方写盘途中进程被杀，记录会停在 committing、谁也确认不了。
# 超过租期即视为「抢占方已死」，下一次确认自动收回重试。
_CLAIM_LEASE = 120


@contextmanager
def _staged_db():
    """暂存库连接：WAL + busy_timeout。

    pragma 顺序与异常容忍都有讲究（8 线程并发测试实测出来的）：
    · `busy_timeout` 必须**先于** `journal_mode`——反过来时，多线程首次并发建库
      那句 pragma 没有等待余量。
    · 但光靠顺序不够：**`PRAGMA journal_mode=WAL` 需要独占访问，冲突时直接返回
      SQLITE_BUSY 且不调用 busy handler**（busy_timeout 对它无效）。多线程同时首次
      连接时，一个线程切成功了、其余立刻拿到 BUSY → 抛 `database is locked`。
      所以这里必须容忍这个异常：库要么已经是 WAL，要么会被先到的那个线程切成 WAL，
      结果都对，不该让调用方为此失败。
    · 建表语句每次连接都跑一遍（`IF NOT EXISTS`，成本可忽略），省掉一个「是否已初始化」
      的模块级标志位——那个标志位本身就是测试里常被忘掉重置的坑。
    """
    path = _staged_db_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # 并发首次建库时别人正在切 WAL；不吃 busy_timeout，容忍即可
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        _migrate(conn, path)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn, path) -> None:
    """给老库补列（`CREATE TABLE IF NOT EXISTS` 不会补，必须显式 ALTER）。

    每个库路径只跑一次，靠模块级集合记；断言失败（列已存在）直接忽略。
    为什么不每次跑：正常路径上这些 ALTER 必然失败，白付两次异常开销。
    """
    key = str(path)
    if key in _MIGRATED:
        return
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # 列已存在
    _MIGRATED.add(key)


def _stage(rec: dict) -> dict:
    """把一条记录放进暂存队列（不落训练库），返回带 _staged_id 的记录。"""
    rec = dict(rec)  # 拷贝，避免外部继续修改污染暂存内容
    rec["_staged_id"] = uuid.uuid4().hex
    with _staged_db() as conn:
        conn.execute(
            "INSERT INTO staged (staged_id, payload, created_at) VALUES (?, ?, ?)",
            (rec["_staged_id"], json.dumps(rec, ensure_ascii=False),
             datetime.datetime.now().isoformat(timespec="seconds")),
        )
    return rec


def staged_records() -> list:
    """当前暂存队列快照，按入队顺序（供 Supervisor / 前端确认用）。"""
    with _staged_db() as conn:
        rows = conn.execute("SELECT payload FROM staged ORDER BY seq").fetchall()
    return [json.loads(r["payload"]) for r in rows]


def _claim_first_staged():
    """**原子抢占**队首待确认记录并返回（FIFO）；无可抢占记录时返回 None。

    抢占 = 把 status 从 staged 改成 committing，**只有 UPDATE 影响行数为 1 的调用者
    才有资格落库**。两个请求同时确认时，第二个的 UPDATE 会拿到 rowcount=0（SQLite 的
    写锁把两个 UPDATE 串行化了），于是它去看下一条——同一条记录只会被写进训练库一次。
    老实现是「都读到队首 → 都写盘 → 都删除」，并发确认会重复入库。

    刻意不在这里删除：`commit_staged` 要「先落库、成功了才出队」，删除由落库之后
    单独做。老实现是「先 pop 再落库」，落库失败时记录既没进磁盘、又不在暂存里
    → 用户数据无声丢失（越界数组、磁盘满、权限问题都会走到这条）。
    """
    now = datetime.datetime.now()
    now_s = now.isoformat(timespec="seconds")
    lease_cut = (now - datetime.timedelta(seconds=_CLAIM_LEASE)).isoformat(timespec="seconds")
    with _staged_db() as conn:
        # 崩溃兜底：收回过期抢占。正常路径上一条都收不到。
        conn.execute(
            "UPDATE staged SET status='staged', claimed_at=NULL "
            "WHERE status='committing' AND (claimed_at IS NULL OR claimed_at < ?)",
            (lease_cut,))
        while True:
            row = conn.execute(
                f"SELECT seq, payload FROM staged WHERE {_ROWS} ORDER BY seq LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            claimed = conn.execute(
                "UPDATE staged SET status='committing', claimed_at=? "
                f"WHERE seq=? AND {_ROWS}", (now_s, row["seq"])).rowcount
            if claimed == 1:
                return json.loads(row["payload"])
            # 被别的连接抢先了：继续看下一条，别退化成「整批放弃」


def _claim_by_ids(staged_ids: list) -> list:
    """**按 id 原子抢占**一批待确认记录（/commit 带 records 的精确路径用）。

    与 `_claim_first_staged` 同一套语义：staged → committing，**只有 UPDATE
    rowcount==1 的才算抢到**（别的连接正在提交同一条 → rowcount=0 → 本请求跳过它）。
    老的 records 路径完全不碰 status 字段、直接落库——两个端同时确认同一批待确认
    卡片时会把同一批记录写进训练库两遍，这是 2026-09-20 修掉的重复入库洞。

    抢占前先收回过期租期（崩溃兜底，与队首抢占共用 _CLAIM_LEASE）。
    返回**实际抢到**的 staged_id 列表（保持传入顺序、去重）。
    """
    now = datetime.datetime.now()
    now_s = now.isoformat(timespec="seconds")
    lease_cut = (now - datetime.timedelta(seconds=_CLAIM_LEASE)).isoformat(timespec="seconds")
    claimed = []
    with _staged_db() as conn:
        conn.execute(
            "UPDATE staged SET status='staged', claimed_at=NULL "
            "WHERE status='committing' AND (claimed_at IS NULL OR claimed_at < ?)",
            (lease_cut,))
        for sid in dict.fromkeys(staged_ids):  # 去重且保序
            if not sid:
                continue
            n = conn.execute(
                "UPDATE staged SET status='committing', claimed_at=? "
                "WHERE staged_id=? AND status='staged'", (now_s, sid)).rowcount
            if n == 1:
                claimed.append(sid)
    return claimed


def _release_claim(staged_id: str) -> None:
    """把抢占退回去（落库失败时调用），让这条记录还能被重试确认。"""
    if not staged_id:
        return
    with _staged_db() as conn:
        conn.execute("UPDATE staged SET status='staged', claimed_at=NULL "
                     "WHERE staged_id=?", (staged_id,))


def _discard_staged(ids: list = None) -> int:
    """清除暂存。ids=None 清空全部；传 _staged_id 列表时只清匹配项。返回清除条数。"""
    with _staged_db() as conn:
        if ids is None:
            n = conn.execute("SELECT COUNT(*) FROM staged").fetchone()[0]
            conn.execute("DELETE FROM staged")
            return n
        # 逐条删：待清 id 数量很小，不做动态 SQL 拼接（免参数个数上限与注入面）
        n = 0
        for sid in set(ids):
            n += conn.execute(
                "DELETE FROM staged WHERE staged_id=?", (sid,)).rowcount
        return n


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
        return staged_records()

    def commit_staged(self) -> int:
        """确认提交：把暂存记录按入队顺序全部落库，返回条数。

        两条不变式：
        1. **先落库、成功了才出队**。落库抛异常时记录仍留在暂存里（`_save` 已改成
           失败即抛，不再静默），调用方 /commit 据此提示「暂存记录已保留」并让用户
           重试；老实现先出队再落库，失败就两头落空。
        2. **一条记录只落库一次**。每轮先原子抢占（staged → committing）再写盘，
           两个请求同时确认时不会双双写到同一条；老实现是「都读到队首、都写盘、
           都删除」，并发下会重复入库。
        """
        n = 0
        while True:
            rec = _claim_first_staged()
            if rec is None:
                break
            sid = rec.get("_staged_id")
            if not sid:
                # 理论上不会发生（_stage 一定写 _staged_id）。真出现就抛出去：
                # 静默跳过会让这条记录永远占着队首、这轮 while 原地死循环。
                # 它会被抢占租期收回去（拿不到 id 就没法精确退抢占），
                # 但至少不会静默丢数据或死循环。
                raise RuntimeError(
                    f"暂存记录缺少 _staged_id，无法出队：type={rec.get('type')}")
            try:
                if rec.get("type") == "run":
                    self.add_run(rec["date"], rec.get("distance_km") or 0,
                                 rec.get("duration_min") or 0, rec.get("avg_hr") or 0,
                                 rec.get("max_hr") or 0, hr_series=rec.get("hr_series"),
                                 rpe=rec.get("rpe") or 0, note=rec.get("note") or "")
                elif rec.get("type") == "strength":
                    self.add_strength(rec["date"], rec.get("exercises") or [],
                                      rpe=rec.get("rpe") or 0, note=rec.get("note") or "")
            except Exception:
                # 落库失败：把抢占退回去再往上抛，记录仍可重试
                # （不退的话它会卡在 committing 里，用户点确认只会「暂存区为空」）。
                _release_claim(sid)
                raise
            # 落库成功后才出队
            _discard_staged([sid])
            n += 1
        return n

    def discard_staged(self, ids: list = None) -> int:
        """清除暂存。ids=None 清空全部；传 _staged_id 列表时只清匹配项
        （前端确认的那批记录），不影响其他会话/请求的暂存。返回清除条数。"""
        return _discard_staged(ids)

    def claim_staged(self, staged_ids: list) -> list:
        """按 id 原子抢占一批待确认记录，返回**实际抢到**的 staged_id 列表。

        /commit 带 records 的路径必须先走这里：抢到的才有资格落库，
        抢不到的是别的请求正在提交同一条，跳过即防重复入库。
        """
        return _claim_by_ids(staged_ids)

    def release_staged(self, staged_id: str) -> None:
        """把按 id 的抢占退回去（落库失败时调用），让这条记录还能被重试确认。"""
        _release_claim(staged_id)

    def _save(self, rec):
        # 微秒级时间戳：同一秒内多条记录（批量导入/连续提交）不会互相覆盖丢数据
        stamp = datetime.datetime.now().strftime("%H%M%S%f")
        fn = self.dir / f"{rec['type']}_{rec['date']}_{stamp}.json"
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
        except Exception as e:
            # 训练记录写失败绝不能只打一行 stdout 就照常返回：调用方（add_run /
            # add_strength / commit_staged）会以为存成功了，用户练了但库里没有，
            # 属于无声数据丢失。改为抛出，由调用方决定「保留暂存 / 报错」。
            print(f"[SportStore] 训练记录落盘失败 {fn.name}: {e}", flush=True)
            raise IOError(f"训练记录落盘失败: {e}") from e

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
