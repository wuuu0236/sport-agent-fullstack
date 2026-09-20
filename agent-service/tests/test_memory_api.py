"""长期记忆删除接口（`POST /memory/forget`）回归测试。

对应功能：对话页「用户画像」面板支持**用户自主逐条删除**不用的画像（2026-09-17）。

为什么这些用例值得存在：这个接口走的是 `memory.forget()` 的**返回值式错误**
（返回 `(ok, msg)`、不抛异常），端点必须显式判 `ok`——不判的话前端会
「显示删除成功、条目其实还在」。这类静默失败是本项目反复踩过的坑（见 CHANGELOG
的「代码审查 9 项」），所以正面（真删掉）和负面（没删掉要如实说）两条路径都要钉住。
"""
import pytest
from fastapi.testclient import TestClient

from src import config, memory
from app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 记忆库指向 tmp：删除会写库并重写 USER.md 视图，绝不能落到真实 data/
    monkeypatch.setattr(config.CONFIG, "MEMORY_DB", tmp_path / "memory.db")
    monkeypatch.setattr(config.CONFIG, "USER_FILE", tmp_path / "USER.md")
    monkeypatch.setattr(config.CONFIG, "MEMORY_FILE", tmp_path / "MEMORY.md")
    monkeypatch.setattr(config.CONFIG, "SESSION_FILE", tmp_path / "session.json")
    # 建表是一次性动作（模块级 _initialized 记住），不重置的话新 tmp 库拿不到 schema
    monkeypatch.setattr(memory, "_initialized", False)
    return TestClient(app, raise_server_exceptions=False)


def _seed_user(*texts):
    for t in texts:
        ok, msg = memory.remember("user", t)
        assert ok, msg


def _texts(items):
    """/memory 现在返回 [{"id","text"}]，测试里大多只关心文本序列。"""
    return [e["text"] for e in items]


def _find_id(items, text):
    for e in items:
        if e["text"] == text:
            return e["id"]
    raise AssertionError(f"条目不存在：{text!r} in {items}")


class TestMemoryListShape:
    def test_list_returns_stable_ids(self, client):
        """/memory 每条必须带稳定主键——按 id 删除的前端契约。"""
        _seed_user("静息心率55", "当前训练目标：练胸")

        data = client.get("/memory").json()["user"]
        assert [e["text"] for e in data] == ["静息心率55", "当前训练目标：练胸"]
        assert all(isinstance(e["id"], int) for e in data)
        # id 必须稳定：重读一次还是同一批（不能是索引式的假 id）
        again = client.get("/memory").json()["user"]
        assert [e["id"] for e in again] == [e["id"] for e in data]


class TestForgetEndpoint:
    def test_forget_removes_entry_and_syncs_view(self, client):
        _seed_user("静息心率55", "当前训练目标：练胸")

        r = client.post("/memory/forget", json={"target": "user", "text": "静息心率55"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        assert _texts(client.get("/memory").json()["user"]) == ["当前训练目标：练胸"]
        # USER.md 只是只读视图，但视图必须跟着改（否则用户打开文件会看到「已删除」的条目）
        assert "静息心率55" not in config.CONFIG.USER_FILE.read_text(encoding="utf-8")

    def test_unknown_text_reports_not_ok(self, client):
        _seed_user("静息心率55")

        r = client.post("/memory/forget", json={"target": "user", "text": "根本没有这条"})
        assert r.status_code == 200  # 契约与 /plan/delete 一致：找不到是 ok:false，不是 4xx/5xx
        assert r.json()["ok"] is False
        assert r.json()["msg"] == "未找到匹配条目"
        assert _texts(client.get("/memory").json()["user"]) == ["静息心率55"]

    def test_target_isolation(self, client):
        """删 user 存储不得动到 memory 存储。"""
        _, _ = memory.remember("user", "静息心率55"), memory.remember("memory", "静息心率55 用于区间计算")

        r = client.post("/memory/forget", json={"target": "user", "text": "静息心率55"})
        assert r.json()["ok"] is True
        data = client.get("/memory").json()
        assert data["user"] == []
        assert _texts(data["memory"]) == ["静息心率55 用于区间计算"]

    def test_rejects_bad_target(self, client):
        r = client.post("/memory/forget", json={"target": "session", "text": "x"})
        assert r.status_code == 400

    def test_rejects_empty_text(self, client):
        assert client.post("/memory/forget", json={"target": "user", "text": "   "}).status_code == 400
        assert client.post("/memory/forget", json={}).status_code == 400


class TestForgetSemantics:
    def test_full_text_deletes_exactly_that_entry(self, client):
        """前端必须传**条目原文整条**：传整条时只会命中它自己。"""
        _seed_user("偏好：晚上练", "偏好：晚上练，不喜欢早起")

        r = client.post("/memory/forget", json={"target": "user", "text": "偏好：晚上练，不喜欢早起"})
        assert r.json()["ok"] is True
        assert _texts(client.get("/memory").json()["user"]) == ["偏好：晚上练"]

    def test_substring_deletes_first_match_only(self, client):
        """按子串匹配、只删第一条命中的——这是既有语义（对话里「忘掉…」也走它），钉住它。"""
        _seed_user("偏好：晚上练", "偏好：晚上练，不喜欢早起")

        r = client.post("/memory/forget", json={"target": "user", "text": "晚上练"})
        assert r.json()["ok"] is True
        assert _texts(client.get("/memory").json()["user"]) == ["偏好：晚上练，不喜欢早起"]

    def test_deleted_entry_no_longer_recalled(self, client):
        """删除要连 FTS 索引一起清：否则被删的条目还会被召回注入上下文（静默残留）。"""
        _seed_user("静息心率55")

        # 先证明「删除前确实召回得到它」——不然下面的断言可能只是空注入造成的假绿
        assert any("静息心率55" in c for c in memory.recall_relevant("静息心率是多少"))

        client.post("/memory/forget", json={"target": "user", "text": "静息心率55"})
        assert all("静息心率55" not in c for c in memory.recall_relevant("静息心率是多少"))

    def test_delete_is_idempotent(self, client):
        """连点两次删除：第二次如实报「未找到」，不会假装成功也不会报错。"""
        _seed_user("静息心率55")
        first = client.post("/memory/forget", json={"target": "user", "text": "静息心率55"})
        second = client.post("/memory/forget", json={"target": "user", "text": "静息心率55"})
        assert first.json()["ok"] is True
        assert second.json() == {"ok": False, "msg": "未找到匹配条目"}


class TestForgetById:
    """按稳定主键删除（2026-09-20）：子串匹配在两条内容有包含关系的条目上会删错，
    /memory 返回 id 后前端一律按 id 删。"""

    def test_delete_by_id_hits_exact_entry_even_when_substrings_overlap(self, client):
        """核心场景：删「长条」时短条必须安然无恙——旧的子串匹配会命中短条删错。"""
        _seed_user("偏好：晚上练", "偏好：晚上练，不喜欢早起")
        items = client.get("/memory").json()["user"]
        long_id = _find_id(items, "偏好：晚上练，不喜欢早起")

        r = client.post("/memory/forget", json={"id": long_id})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "msg": "ok"}
        assert _texts(client.get("/memory").json()["user"]) == ["偏好：晚上练"]

    def test_delete_by_id_missing_reports_not_ok(self, client):
        _seed_user("静息心率55")

        r = client.post("/memory/forget", json={"id": 999999})
        assert r.status_code == 200
        assert r.json() == {"ok": False, "msg": "条目不存在或已删除"}
        assert len(client.get("/memory").json()["user"]) == 1

    def test_delete_by_id_rejects_non_integer(self, client):
        r = client.post("/memory/forget", json={"id": "abc"})
        assert r.json()["ok"] is False

    def test_delete_by_id_across_stores(self, client):
        """id 是全表主键：删 memory 存储的条目不需要传 target，也不误删 user 的同名内容。"""
        memory.remember("user", "静息心率55")
        memory.remember("memory", "静息心率55 用于区间计算")
        mem_items = client.get("/memory").json()["memory"]
        target_id = _find_id(mem_items, "静息心率55 用于区间计算")

        r = client.post("/memory/forget", json={"id": target_id})
        assert r.json()["ok"] is True
        data = client.get("/memory").json()
        assert _texts(data["memory"]) == []
        assert _texts(data["user"]) == ["静息心率55"]
