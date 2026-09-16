"""暂存队列（SQLite）回归测试：跨重启耐用 + FIFO 顺序 + 并发不丢。

背景（2026-09-16，方案 P2）：暂存队列此前是**进程内 list + 手写 threading.Lock**，
服务一重启「待确认」的解析结果就全丢——而本项目重启服务是常态。迁到 SQLite 后
要钉住的正是这条不变式：**新开一条连接（≈ 另一个 worker / 重启后的服务）仍看得到
此前暂存的记录**。顺带把「手写锁换成 WAL」的并发行为也钉住。

夹具只 patch `MEMORY_DIR`——暂存库路径是**每次调用现算**的（`_staged_db_path()`），
所以这一个 patch 就够；写死成模块常量的那种写法在这里会漏，测试会污染真实 data/。
"""
import sqlite3
import threading

import pytest

from src import config
from src.sport_data import SportStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    """存储目录（含暂存库）指向临时路径——绝不碰真实 data/。"""
    monkeypatch.setattr(config.CONFIG, "MEMORY_DIR", tmp_path)
    return SportStore()


def _stage_run(store, date="2026-08-01", note="t"):
    return store.stage_run(date, 5, 30, 150, 180, note=note)


class TestDurability:
    def test_record_is_on_disk_not_in_memory(self, store, tmp_path):
        """核心不变式：绕开模块函数直接读库，数据必须真的落盘了。"""
        r = _stage_run(store)
        conn = sqlite3.connect(tmp_path / "staged.db")
        try:
            ids = [row[0] for row in
                   conn.execute("SELECT staged_id FROM staged").fetchall()]
        finally:
            conn.close()
        assert ids == [r["_staged_id"]]

    def test_visible_to_another_store_instance(self, store):
        """换一个 SportStore 实例（≈ 另一个 worker）看得到同一队列。

        进程内 list 时代这条也成立（list 是模块级全局），但**换进程就不成立**——
        下一条用例补这个洞。
        """
        r = _stage_run(store)
        assert [x["_staged_id"] for x in SportStore().staged()] == [r["_staged_id"]]

    def test_visible_to_a_separate_sqlite_connection(self, store, tmp_path):
        """模拟「服务重启」：旧连接全关掉，新连接照常读到（这才是 durability 的证据）。

        进程内 list 在这条上必挂——重启即清零，这正是本次要修的痛点。
        """
        _stage_run(store, note="重启前暂存的记录")
        del store  # 丢掉实例，等价于丢掉进程内状态
        fresh = SportStore()
        rows = fresh.staged()
        assert len(rows) == 1 and rows[0]["note"] == "重启前暂存的记录"

    def test_commit_after_restart_still_lands(self, store):
        """重启后仍能完成确认入库（不只是「读得到」，还要「提交得掉」）。"""
        _stage_run(store, date="2026-08-03")
        del store
        fresh = SportStore()
        assert fresh.commit_staged() == 1
        assert fresh.staged() == []
        assert [r["date"] for r in fresh.runs()] == ["2026-08-03"]


class TestFifoOrder:
    def test_snapshot_keeps_enqueue_order(self, store):
        ids = [_stage_run(store, note=f"n{i}")["_staged_id"] for i in range(5)]
        assert [x["_staged_id"] for x in store.staged()] == ids

    def test_commit_dispatches_in_enqueue_order(self, store, monkeypatch):
        """钉住 commit 的取用顺序（FIFO）。

        不比对 `runs()` 的顺序——它读的是目录下文件，顺序没有契约保证；
        改成打桩记录 `add_run` 的调用顺序，这样断言才是确定的。
        """
        _stage_run(store, note="第一")
        _stage_run(store, note="第二")
        _stage_run(store, note="第三")
        order = []
        monkeypatch.setattr(store, "add_run",
                            lambda *a, **kw: order.append(kw.get("note")))
        assert store.commit_staged() == 3
        assert order == ["第一", "第二", "第三"]

    def test_commit_handles_both_record_types(self, store):
        _stage_run(store, date="2026-08-01")
        store.stage_strength("2026-08-02",
                             [{"name": "深蹲", "sets": 4, "reps": 8, "weight_kg": 80}])
        assert store.commit_staged() == 2
        assert len(store.runs()) == 1 and len(store.strengths()) == 1
        assert store.staged() == []


class TestDiscard:
    def test_discard_all(self, store):
        _stage_run(store)
        _stage_run(store)
        assert store.discard_staged() == 2
        assert store.staged() == []

    def test_discard_only_matching_ids(self, store):
        """P0 场景：多会话并发暂存，确认时只清自己的记录，不踩别人。"""
        r1 = _stage_run(store, note="a")
        r2 = _stage_run(store, note="b")
        r3 = _stage_run(store, note="c")
        assert store.discard_staged([r1["_staged_id"], r3["_staged_id"]]) == 2
        rest = store.staged()
        assert [x["_staged_id"] for x in rest] == [r2["_staged_id"]]

    def test_discard_unknown_id_is_noop(self, store):
        _stage_run(store)
        assert store.discard_staged(["不存在的id"]) == 0
        assert len(store.staged()) == 1

    def test_discard_empty_queue(self, store):
        assert store.discard_staged() == 0
        assert store.discard_staged([_stage_run(store)["_staged_id"]]) == 1


class TestCommitEdgeCases:
    def test_commit_empty_queue_returns_zero(self, store):
        assert store.commit_staged() == 0

    def test_staged_ids_are_unique(self, store):
        r1 = _stage_run(store)
        r2 = _stage_run(store)
        assert r1["_staged_id"] != r2["_staged_id"]

    def test_staged_does_not_touch_ledger(self, store):
        """暂存绝不等于落库（隔离工作空间的本意）。"""
        _stage_run(store)
        assert store.runs() == [] and store.strengths() == []


class TestConcurrency:
    def test_parallel_stage_no_loss(self, store):
        """并发保护从手写 _STAGED_LOCK 换成 SQLite WAL，行为不能退化。

        8 线程 × 10 条：一条不丢（80 条且 note 全不重复 = 没有互相覆盖）。
        """
        errors = []

        def worker(tid):
            try:
                for i in range(10):
                    store.stage_run("2026-08-01", 5, 30, 150, 180, note=f"{tid}-{i}")
            except Exception as e:  # 线程内的异常默认吞掉，必须自己收集
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发暂存抛异常：{errors[:2]}"
        rows = store.staged()
        assert len(rows) == 80
        assert len({r["note"] for r in rows}) == 80
