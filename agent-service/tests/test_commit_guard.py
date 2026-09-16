"""落库失败防线回归测试（2026-09-16 代码审查 问题 1 / 问题 6）。

两条是同一个病：**落库没成功，暂存却没了**——记录既不在磁盘、也不在待确认队列，
用户数据无声丢失，而且界面上看不出任何异常。

· 问题 1：`/commit` 不看 `_import_save` 的返回值。它落库失败时**只返回
  `{"ok": False}`、不抛异常**，老实现直接往下走 `discard_staged(ids)` → 两头落空。
· 问题 6：`SportStore._save` 写盘失败只打一行 stdout 就照常返回；而 `commit_staged`
  又是「先出队、再落库」，写盘一失败那条记录就永久消失（磁盘满/权限/路径异常都会走到）。

修法把顺序反过来：**先落库、成功了才出队**；写盘失败抛 `IOError`，由 `/commit` 兜住
并返回 `ok=False + kept=True`，前端据此保留待确认卡片让用户重试。
"""
import pytest
from fastapi.testclient import TestClient

from src import config
from src.sport_data import SportStore
import app as app_module
from app import app


@pytest.fixture
def store(tmp_path, monkeypatch):
    """存储目录（含暂存库）指向临时路径——绝不碰真实 data/。"""
    monkeypatch.setattr(config.CONFIG, "MEMORY_DIR", tmp_path)
    return SportStore()


@pytest.fixture
def client(store):
    """端点内部的 SportStore() 也读同一份 config，所以复用 store 的隔离。"""
    return TestClient(app, raise_server_exceptions=False)


def _break_disk(store, tmp_path):
    """把落盘目录变成一个**普通文件**，让写入必然失败（跨平台，不依赖权限位）。"""
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    store.dir = blocker


class TestSaveFailureIsNotSilent:
    def test_save_raises_instead_of_swallowing(self, store, tmp_path):
        """问题 6 前半：写盘失败必须抛出。以前只打 stdout 就 return rec，
        调用方以为存成功了（用户练了但库里没有）。"""
        _break_disk(store, tmp_path)
        with pytest.raises(IOError):
            store.add_run("2026-08-01", 5, 30, 150, 180)

    def test_commit_keeps_record_when_save_fails(self, store, tmp_path):
        """问题 6 后半（核心不变式）：落库失败时记录必须**仍在暂存里**。

        老实现先 `_pop_first_staged()` 再落库，失败时记录已经出队
        → 磁盘没有、暂存也没有，无声丢失。
        """
        r = store.stage_run("2026-08-01", 5, 30, 150, 180, note="不能被吞")
        orig_dir = store.dir
        _break_disk(store, tmp_path)
        with pytest.raises(IOError):
            store.commit_staged()
        store.dir = orig_dir  # 磁盘恢复
        assert [x["_staged_id"] for x in store.staged()] == [r["_staged_id"]]

    def test_retry_after_failure_succeeds_and_clears_queue(self, store, tmp_path):
        """失败保留 → 修好后重试能真正落库，且队列清空（不会重复入库）。"""
        store.stage_run("2026-08-01", 5, 30, 150, 180, note="重试")
        orig_dir = store.dir
        _break_disk(store, tmp_path)
        with pytest.raises(IOError):
            store.commit_staged()
        store.dir = orig_dir
        assert store.commit_staged() == 1
        assert store.staged() == []
        assert len(store.runs()) == 1


class TestCommitEndpointKeepsStaged:
    def test_import_save_failure_keeps_staged(self, store, client, monkeypatch):
        """问题 1：`_import_save` 返回 ok=False（不抛异常）时不许清暂存。"""
        r = store.stage_run("2026-08-01", 5, 30, 150, 180, note="导入的")
        monkeypatch.setattr(app_module, "_import_save",
                            lambda payload: {"ok": False, "error": "磁盘只读"})
        body = client.post("/commit", json={"records": [r]}).json()
        assert body["ok"] is False and body["kept"] is True
        assert [x["_staged_id"] for x in store.staged()] == [r["_staged_id"]]

    def test_import_save_success_discards_only_own_records(self, store, client):
        """反向锁定：成功路径仍按 _staged_id 精确清除，不误伤别人的暂存。"""
        mine = store.stage_run("2026-08-01", 5, 30, 150, 180, note="mine")
        other = store.stage_run("2026-08-02", 5, 30, 150, 180, note="other")
        body = client.post("/commit", json={"records": [mine]}).json()
        assert body["ok"] is True
        assert [x["_staged_id"] for x in store.staged()] == [other["_staged_id"]]

    def test_queue_commit_failure_returns_kept_not_500(self, client, monkeypatch, store):
        """无 records 路径：commit_staged 抛异常时回 ok=False + kept=True，
        而不是把 IOError 变成一句看不出所以然的 500。"""
        store.stage_run("2026-08-01", 5, 30, 150, 180)

        def boom(self):
            raise IOError("磁盘满了")

        monkeypatch.setattr(SportStore, "commit_staged", boom)
        resp = client.post("/commit", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False and body["kept"] is True and "磁盘满了" in body["msg"]
        # 记录确实还在（端点没有偷偷清掉）
        assert len(store.staged()) == 1

    def test_queue_commit_success_still_reports_count(self, store, client):
        store.stage_run("2026-08-01", 5, 30, 150, 180)
        body = client.post("/commit", json={}).json()
        assert body["ok"] is True and "已确认入库 1 条" in body["msg"]
        assert store.staged() == []

    def test_empty_queue_is_not_marked_kept(self, client):
        """空队列是「没东西可提交」而不是「落库失败」——不能带 kept，
        否则前端会留着一张永远确认不掉的卡片。"""
        body = client.post("/commit", json={}).json()
        assert body["ok"] is False and not body.get("kept")
