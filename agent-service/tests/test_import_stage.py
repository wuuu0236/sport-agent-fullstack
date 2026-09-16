"""截图导入闭环回归测试（2026-09-16 修复复查 问题 1）。

病根：后端已经把图片导入改成「先暂存、确认后入库」，前端却只认 `res.saved`。
`saved` 现在恒为 `False`（本端点不再直接落库），于是每次导入都掉进前端的
「导入失败」兜底分支——后端明明有待确认记录，用户看到的是失败，而且**没有任何
入库入口**，记录就永远躺在暂存里。

修法两条：
· 后端 `_stage_import_data` 返回**带 `_staged_id` 的记录本体**（以前返回 bool），
  并由 `/import-image` 用 `staged_records` 吐出来。前端要拿 `_staged_id` 才能
  在确认时只清自己这条（`/commit` 按 id 精确 discard）。
· 前端 `importFile` 补 `res.ok && res.staged` 分支，把记录放进 `pendingCommit`。

本文件锁后端那一半：**返回值契约**与**闭环能不能走通**。前端那半靠 `npm run build`
加实机验收（本项目没有前端测试框架）。
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
    return TestClient(app, raise_server_exceptions=False)


def _run_payload():
    return {"ok": True, "raw": "5.02 公里 28:30 平均心率 152",
            "data": {"type": "run", "date": "2026-09-10", "distance_km": 5.02,
                     "duration_min": 28.5, "avg_hr": 152, "max_hr": 171}}


def _staged_files(store):
    """训练库已落盘的记录文件（`sessions/*.json`）。"""
    return sorted(store.dir.glob("*.json")) if store.dir.exists() else []


class TestStageImportDataReturnContract:
    def test_returns_record_with_staged_id(self, store):
        """必须返回记录本体（带 _staged_id），不是 bool。

        返回 bool 的话前端只知道「进队了」，确认时只能整队清空——
        多会话并发时会把别人的暂存一起清掉（P0 修过的踩踏问题）。
        """
        rec = app_module._stage_import_data(_run_payload()["data"])
        assert isinstance(rec, dict)
        assert rec["_staged_id"]
        assert [x["_staged_id"] for x in store.staged()] == [rec["_staged_id"]]

    def test_returns_none_when_not_stageable(self, store):
        """不能入库的解析结果返回 None，而不是 False/True 这种含糊的布尔量。"""
        assert app_module._stage_import_data({"type": "unknown"}) is None
        assert app_module._stage_import_data({"type": "strength", "exercises": []}) is None
        assert store.staged() == []


class TestImportImageEndpoint:
    def test_success_returns_staged_records_and_does_not_save(self, store, client, monkeypatch):
        """P0 核心：解析成功 → 进暂存 + 返回带 id 的记录，且**没有落库**。"""
        monkeypatch.setattr(app_module, "image_import", lambda *a, **k: _run_payload())
        body = client.post("/import-image", json={"image": "x", "mime": "image/png"}).json()

        assert body["ok"] is True
        assert body["saved"] is False          # 本端点不直接落库
        assert body["staged"] is True          # 前端认的成功信号
        recs = body["staged_records"]
        assert len(recs) == 1
        assert recs[0]["_staged_id"]         # 前端靠它做精确确认
        assert recs[0]["distance_km"] == 5.02
        # 暂存里有、训练库里没有
        assert [x["_staged_id"] for x in store.staged()] == [recs[0]["_staged_id"]]
        assert _staged_files(store) == []

    def test_parsed_but_not_stageable_reports_reason(self, store, client, monkeypatch):
        """解析出来了却进不了队（动作列表为空）时，要给出原因，
        否则前端只能显示「导入失败」这种看不出所以然的兜底文案。"""
        monkeypatch.setattr(app_module, "image_import", lambda *a, **k: {
            "ok": True, "raw": "卧推 60kg",
            "data": {"type": "strength", "date": "2026-09-10", "exercises": []}})
        body = client.post("/import-image", json={"image": "x", "mime": "image/png"}).json()
        assert body["staged"] is False
        assert body["staged_records"] == []
        assert body["save_error"]

    def test_ocr_failure_still_returns_raw_and_no_stage(self, store, client, monkeypatch):
        """OCR/解析失败路径不受影响：不产生暂存记录，raw 照旧给前端展示。"""
        monkeypatch.setattr(app_module, "image_import", lambda *a, **k: {
            "ok": False, "error": "OCR 未识别到文字（纯曲线图或空白图片）", "raw": ""})
        body = client.post("/import-image", json={"image": "x", "mime": "image/png"}).json()
        assert body["ok"] is False
        assert "staged" not in body          # 没走到暂存分支，别凭空造一个 False
        assert store.staged() == []

    def test_closed_loop_import_then_commit(self, store, client, monkeypatch):
        """整条闭环：导入 → 拿到 staged_records → 确认入库 → 训练库有、暂存清空。

        老实现里前端拿不到记录 id（后端只给 bool），这条闭环根本接不上。
        """
        monkeypatch.setattr(app_module, "image_import", lambda *a, **k: _run_payload())
        rec = client.post("/import-image",
                          json={"image": "x", "mime": "image/png"}).json()["staged_records"]
        assert _staged_files(store) == []

        done = client.post("/commit", json={"records": rec}).json()
        assert done["ok"] is True
        assert store.staged() == []
        assert len(_staged_files(store)) == 1

    def test_confirm_only_own_record(self, store, client, monkeypatch):
        """两张截图先后导入：确认其中一张不该把另一张的暂存吞掉。

        前端 `importFile` 是**累加**进 pendingCommit 的，但万一漏传一条，
        后端也必须只清传进来的那批（契约层面兜住）。
        """
        monkeypatch.setattr(app_module, "image_import", lambda *a, **k: _run_payload())
        first = client.post("/import-image",
                            json={"image": "x", "mime": "image/png"}).json()["staged_records"]
        second = client.post("/import-image",
                             json={"image": "y", "mime": "image/png"}).json()["staged_records"]
        assert first[0]["_staged_id"] != second[0]["_staged_id"]

        client.post("/commit", json={"records": first})
        assert [x["_staged_id"] for x in store.staged()] == [second[0]["_staged_id"]]
