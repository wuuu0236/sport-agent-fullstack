"""SportStore 分析层回归测试：心率区间 / 负荷 / 力量趋势 / 暂存队列。

原则：没有心率数据时必须如实 has_hr=False，绝不编造分布（项目 P0 教训）。
"""
import pytest

from src import config
from src.sport_data import SportStore, hr_zone


class TestHrZone:
    def test_boundaries(self):
        assert hr_zone(0) == "Z1恢复"
        assert hr_zone(50) == "Z1恢复"
        assert hr_zone(65) == "Z2有氧燃脂"
        assert hr_zone(75) == "Z3有氧耐力"
        assert hr_zone(85) == "Z4无氧阈"
        assert hr_zone(95) == "Z5最大"

    def test_upper_edge_included(self):
        # 100% 也必须落在 Z5，不能掉出所有区间
        assert hr_zone(100) == "Z5最大"


class TestAnalyzeRun:
    def test_with_hr_series(self):
        rec = {"type": "run", "date": "2026-08-01", "distance_km": 5,
               "duration_min": 30, "avg_hr": 150, "max_hr": 180,
               "hr_series": [120, 130, 150, 165, 175], "rpe": 7}
        a = SportStore().analyze_run(rec, max_hr=200)
        assert a["has_hr"] is True
        assert abs(sum(a["zones"].values()) - 100) < 0.5  # 区间占比归一到 100%
        assert a["pace_min_km"] == 6.0
        # TRIMP ≈ 时长 × 平均心率/最大心率 = 30 × 150/200
        assert a["load"] == 22.5

    def test_without_hr_is_honest(self):
        rec = {"type": "run", "date": "2026-08-01", "distance_km": 5,
               "duration_min": 30, "avg_hr": 0, "max_hr": 0,
               "hr_series": [], "rpe": 0}
        a = SportStore().analyze_run(rec, max_hr=190)
        assert a["has_hr"] is False
        assert a["zones"] == {}
        assert a["load"] is None

    def test_avg_hr_without_series_still_counts(self):
        # 手动录入只有 avg/max 时也算有心率（模拟区间），分布不得为空
        rec = {"type": "run", "date": "2026-08-01", "distance_km": 5,
               "duration_min": 30, "avg_hr": 150, "max_hr": 180,
               "hr_series": [], "rpe": 0}
        a = SportStore().analyze_run(rec, max_hr=190)
        assert a["has_hr"] is True
        assert sum(a["zones"].values()) > 0


@pytest.fixture
def store(tmp_path, monkeypatch):
    """把存储目录指到临时路径，测试不污染真实训练库。"""
    monkeypatch.setattr(config.CONFIG, "MEMORY_DIR", tmp_path)
    return SportStore()


class TestStrengthTrend:
    def test_progressive_overload(self, store):
        store.add_strength("2026-08-01",
                           [{"name": "深蹲", "sets": 4, "reps": 8, "weight_kg": 70}])
        store.add_strength("2026-08-05",
                           [{"name": "深蹲", "sets": 4, "reps": 8, "weight_kg": 80}])
        t = store.strength_trend("深蹲")
        assert t["samples"] == 2
        assert t["trend"] == "up"
        assert abs(t["delta_pct"] - 14.3) < 0.1  # (80-70)/70 ≈ 14.3%

    def test_first_sample(self, store):
        store.add_strength("2026-08-01",
                           [{"name": "卧推", "sets": 3, "reps": 10, "weight_kg": 50}])
        assert store.strength_trend("卧推")["trend"] == "first"

    def test_unknown_exercise(self, store):
        assert store.strength_trend("不存在的动作")["samples"] == 0


class TestStagedQueue:
    def test_stage_then_commit(self, store):
        store.stage_run("2026-08-01", 5, 30, 150, 180, note="t")
        store.stage_strength("2026-08-02",
                             [{"name": "深蹲", "sets": 4, "reps": 8, "weight_kg": 80}])
        assert len(store.staged()) == 2
        # 暂存不落库
        assert store.runs() == [] and store.strengths() == []
        assert store.commit_staged() == 2
        assert len(store.runs()) == 1 and len(store.strengths()) == 1
        assert store.staged() == []

    def test_discard_by_staged_id(self, store):
        # 修复过的 P0 场景：多会话并发暂存，确认时只清自己的记录
        r1 = store.stage_run("2026-08-01", 5, 30, 150, 180, note="a")
        r2 = store.stage_run("2026-08-02", 8, 48, 155, 185, note="b")
        assert store.discard_staged([r1["_staged_id"]]) == 1
        rest = store.staged()
        assert len(rest) == 1 and rest[0]["_staged_id"] == r2["_staged_id"]

    def test_staged_records_have_unique_ids(self, store):
        r1 = store.stage_run("2026-08-01", 5, 30, 150, 180, note="a")
        r2 = store.stage_run("2026-08-01", 5, 30, 150, 180, note="a")
        assert r1["_staged_id"] != r2["_staged_id"]
