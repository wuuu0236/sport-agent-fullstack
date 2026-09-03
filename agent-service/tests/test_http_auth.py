"""HTTP 层回归测试：token 鉴权中间件 + 异常脱敏。

用 FastAPI TestClient（httpx）直接打中间件，不起真实端口。
"""
import pytest
from fastapi.testclient import TestClient

from src import config
from app import app


@pytest.fixture
def client():
    # 默认 .env 里 AGENT_AUTH_TOKEN 为空 = 鉴权关闭
    return TestClient(app, raise_server_exceptions=False)


class TestAuthMiddleware:
    def test_health_always_open(self, client, monkeypatch):
        monkeypatch.setattr(config.CONFIG, "AGENT_AUTH_TOKEN", "secret-token")
        assert client.get("/health").status_code == 200

    def test_token_off_by_default(self, client, monkeypatch):
        monkeypatch.setattr(config.CONFIG, "AGENT_AUTH_TOKEN", "")
        assert client.get("/plan").status_code == 200

    def test_rejects_missing_token(self, client, monkeypatch):
        monkeypatch.setattr(config.CONFIG, "AGENT_AUTH_TOKEN", "secret-token")
        r = client.get("/plan")
        assert r.status_code == 401
        assert r.json()["error"] == "unauthorized"

    def test_rejects_wrong_token(self, client, monkeypatch):
        monkeypatch.setattr(config.CONFIG, "AGENT_AUTH_TOKEN", "secret-token")
        r = client.get("/plan", headers={"X-Agent-Token": "wrong"})
        assert r.status_code == 401

    def test_accepts_correct_token(self, client, monkeypatch):
        monkeypatch.setattr(config.CONFIG, "AGENT_AUTH_TOKEN", "secret-token")
        r = client.get("/plan", headers={"X-Agent-Token": "secret-token"})
        assert r.status_code == 200

    def test_chat_requires_token(self, client, monkeypatch):
        monkeypatch.setattr(config.CONFIG, "AGENT_AUTH_TOKEN", "secret-token")
        r = client.post("/chat", json={"message": "你好"})
        assert r.status_code == 401


class TestErrorSanitization:
    def test_agent_exception_not_leaked(self, client, monkeypatch):
        """内部异常只给通用文案，不得把异常细节（含路径/上游信息）抛给客户端。"""
        from src.agents import get_agent

        monkeypatch.setattr(config.CONFIG, "AGENT_AUTH_TOKEN", "")
        # mock 模式下 memory 意图直接落盘，不走 LLM —— 用它是为了稳定触发
        # agent 内部异常：把 handle 换成会炸的桩
        def boom(msg, ctx=None):
            raise RuntimeError("秘密：/Users/24162/.env 内部路径泄漏")

        monkeypatch.setattr(get_agent("memory"), "handle", boom)
        r = client.post("/chat", json={"message": "记住我静息心率55"})
        assert r.status_code == 500
        detail = r.json().get("detail", "")
        assert "秘密" not in detail
        assert "执行失败" in detail

    def test_unknown_agent_falls_back(self):
        """/agent/{name} 传未知名应回退 general 而非 500（路由层契约）。"""
        from src.agents import get_agent, get_all_agents
        assert get_agent("nonexistent-agent") is get_all_agents()["general"]
