"""LLM 调用层回归测试（2026-09-16 代码审查 问题 7 / 问题 9）。

· 问题 7：`chat()` 吞掉所有异常后只回一句降级文案，服务端日志里分不清是超时、
  401 鉴权还是 429 配额（`_post_json` 内部其实已经区分了 4xx/5xx，到这一层全丢）。
· 问题 9：`chat()` 不转发 timeout，所有调用点硬吃 `_post_json` 的默认 60s。编排的
  「拆解」只是输出一段 JSON，卡满 60s 会把 SSE 连接拖到中间层（Nginx/浏览器）先超时
  断开——前端只看到转圈，连 error 事件都收不到。现在拆解 15s、综合 30s，其余保持 60s。

断言方式：打桩 `_post_json` / `llm.chat` 捕获实参 kwargs，比读源码可靠
（源码里加个 timeout 但忘了往下传，读源码是看不出来的）。
"""
import pytest

from src import config, llm, memory


@pytest.fixture
def real_mode(monkeypatch):
    """mock_mode 是只读 property（= not LLM_API_KEY），造真实模式得改 key。"""
    monkeypatch.setattr(config.CONFIG, "LLM_API_KEY", "test-key")


@pytest.fixture
def iso_memory(tmp_path, monkeypatch):
    """synthesize 会读用户画像；把记忆库指到 tmp，别碰真实 data/memory.db。"""
    monkeypatch.setattr(config.CONFIG, "MEMORY_DB", tmp_path / "memory.db")
    monkeypatch.setattr(config.CONFIG, "USER_FILE", tmp_path / "USER.md")
    monkeypatch.setattr(config.CONFIG, "MEMORY_FILE", tmp_path / "MEMORY.md")
    monkeypatch.setattr(config.CONFIG, "SESSION_FILE", tmp_path / "session.json")
    monkeypatch.setattr(memory, "_initialized", False)
    return memory


def _capture_llm(monkeypatch, module):
    """把 module.llm.chat 换成只记录 kwargs 的桩，返回捕获字典。

    返回一段对拆解与综合都能用的文本（拆解解析失败会自动走 _fallback_plan，
    这里只关心 kwargs，不关心内容）。
    """
    captured = {}

    def fake_chat(messages, **kw):
        captured.update(kw)
        return '{"steps": []}'

    monkeypatch.setattr(module.llm, "chat", fake_chat)
    return captured


class TestTimeoutPassthrough:
    def test_default_timeout_is_60(self, real_mode, monkeypatch):
        seen = {}

        def fake_post(url, payload, timeout=60, api_key=None):
            seen["timeout"] = timeout
            return {"choices": [{"message": {"content": "ok"}}]}

        monkeypatch.setattr(llm, "_post_json", fake_post)
        llm.chat([{"role": "user", "content": "hi"}])
        assert seen["timeout"] == 60

    def test_explicit_timeout_reaches_post_json(self, real_mode, monkeypatch):
        seen = {}

        def fake_post(url, payload, timeout=60, api_key=None):
            seen["timeout"] = timeout
            return {"choices": [{"message": {"content": "ok"}}]}

        monkeypatch.setattr(llm, "_post_json", fake_post)
        llm.chat([{"role": "user", "content": "hi"}], timeout=15)
        assert seen["timeout"] == 15

    def test_plan_step_uses_15s(self, real_mode, monkeypatch):
        """拆解：只是吐一段 JSON，不该吃默认 60s。"""
        from src import graph
        captured = _capture_llm(monkeypatch, graph)
        graph._GraphBackend().plan("帮我生成周报")
        assert captured.get("timeout") == 15

    def test_synthesize_uses_30s(self, real_mode, iso_memory, monkeypatch):
        """综合：读全部子 Agent 产出、输出最长，给 30s，但仍短于默认 60s。

        构造「两个非 planner 步骤」让它走到综合的 LLM 分支（单步 / 末尾是 planner
        都会提前 return，不调 LLM）。
        """
        from src import graph
        captured = _capture_llm(monkeypatch, graph)
        plan = [{"id": "s1", "agent": "searcher", "input": "查资料"},
                {"id": "s2", "agent": "analyst", "input": "算数据"}]
        results = {"s1": {"agent": "searcher", "output": "查到 3 篇"},
                   "s2": {"agent": "analyst", "output": "配速 5'30"}}
        graph._GraphBackend().synthesize("帮我生成周报", plan, results)
        assert captured.get("timeout") == 30


class TestFailureIsLoggedNotSwallowed:
    def test_client_still_gets_graceful_text(self, real_mode, monkeypatch):
        """降级文案对用户不变（不能把异常堆栈甩给用户）。"""

        def boom(url, payload, timeout=60, api_key=None):
            raise RuntimeError("LLM 接口返回 HTTP 401")

        monkeypatch.setattr(llm, "_post_json", boom)
        out = llm.chat([{"role": "user", "content": "hi"}])
        assert "暂时不可用" in out and "traceback" not in out.lower()

    def test_exception_type_and_reason_reach_the_log(self, real_mode, monkeypatch, capsys):
        """问题 7 的正题：服务端日志必须能区分错误类型/原因。"""

        def boom(url, payload, timeout=60, api_key=None):
            raise RuntimeError("LLM 接口返回 HTTP 401")

        monkeypatch.setattr(llm, "_post_json", boom)
        llm.chat([{"role": "user", "content": "hi"}])
        logged = capsys.readouterr().out
        assert "[LLM] 调用失败" in logged
        assert "RuntimeError" in logged and "401" in logged

    def test_network_error_is_distinguishable_from_http_error(self, real_mode, monkeypatch, capsys):
        """401（鉴权，不该重试）与网络异常（重试后仍失败）日志要能分开。"""

        def boom(url, payload, timeout=60, api_key=None):
            raise RuntimeError("LLM 接口请求失败（网络异常）")

        monkeypatch.setattr(llm, "_post_json", boom)
        llm.chat([{"role": "user", "content": "hi"}])
        logged = capsys.readouterr().out
        assert "网络异常" in logged and "HTTP 401" not in logged
