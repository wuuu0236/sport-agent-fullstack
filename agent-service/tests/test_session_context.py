"""编排中间产出写进 session（2026-09-16 代码审查 问题 8）。

背景：`/chat` 的编排分支此前只把最终成品 append 进 session，子 Agent 的中间产出
（searcher 查到什么、analyst 算了什么）全部丢弃——用户追问「为什么你这么建议」时，
历史里只有成品没有依据，追问的上下文是断的。

修法：把各 `agent_done` 的产出拼成**一条** `[编排过程]` 摘要也写进 session。
一条而不是每个 agent 一条，是因为 session 是 `SESSION_LIMIT=50` 的滚动窗口，
一次编排写 4 条会把真实历史挤掉，得不偿失。
"""
import pytest
from fastapi.testclient import TestClient

from src import config, memory
import app as app_module
from app import app, _summarize_events


@pytest.fixture
def iso_memory(tmp_path, monkeypatch):
    """session 库指向 tmp。

    ⚠️ 这个夹具是本文件存在的前提：`MEMORY_DB` 是**类定义时**按 `MEMORY_DIR` 算死的，
    只 patch `MEMORY_DIR` 隔离不掉它，`/chat` 的 `append_session` 会直接写进用户真实
    记忆库（已知问题，用户决定暂不修）。所以这里必须把三个文件路径 + MEMORY_DB 一起
    patch，并把建表标志重置（建表是一次性动作，不重置新 tmp 库拿不到 schema）。
    """
    monkeypatch.setattr(config.CONFIG, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(config.CONFIG, "MEMORY_DB", tmp_path / "memory.db")
    monkeypatch.setattr(config.CONFIG, "USER_FILE", tmp_path / "USER.md")
    monkeypatch.setattr(config.CONFIG, "MEMORY_FILE", tmp_path / "MEMORY.md")
    monkeypatch.setattr(config.CONFIG, "SESSION_FILE", tmp_path / "session.json")
    monkeypatch.setattr(memory, "_initialized", False)
    return memory


class TestSummarizeEvents:
    def test_collects_only_agent_outputs(self):
        events = [
            {"type": "start"},
            {"type": "plan", "steps": ["searcher", "analyst"]},
            {"type": "agent_start", "agent": "searcher"},
            {"type": "agent_done", "agent": "searcher", "output": "查到 3 篇"},
            {"type": "agent_done", "agent": "analyst", "output": "配速 5'30"},
            {"type": "complete", "output": "最终成品"},
        ]
        s = _summarize_events(events)
        assert s.startswith("[编排过程]")
        assert "[searcher] 查到 3 篇" in s and "[analyst] 配速 5'30" in s
        # 最终成品由调用方单独 append，不能进摘要（否则同一段内容写两遍、白占窗口）
        assert "最终成品" not in s

    def test_no_output_returns_empty(self):
        assert _summarize_events([]) == ""
        assert _summarize_events(None) == ""
        # 只有失败事件（没有产出）时不该产出一条空摘要
        assert _summarize_events([{"type": "agent_error", "agent": "x",
                                   "error": "boom"}]) == ""
        # output 为空串 / None 的 agent_done 同样不算产出
        assert _summarize_events([{"type": "agent_done", "agent": "x", "output": ""}]) == ""

    def test_long_output_is_truncated(self):
        """只是给追问留依据，不是存档：1500 token 的产出不该整段塞回 session。"""
        s = _summarize_events([{"type": "agent_done", "agent": "planner",
                                "output": "字" * 5000}])
        assert len(s) < 700


class TestChatOrchestrationWritesMidContext:
    def test_mid_summary_lands_in_session_before_final(self, iso_memory, monkeypatch, tmp_path):
        """端点级：走编排分支时 session 里既有中间摘要、也有最终成品。"""
        events = [
            {"type": "agent_done", "agent": "searcher", "output": "查到 3 篇"},
            {"type": "agent_done", "agent": "analyst", "output": "配速 5'30"},
        ]

        class FakeSV:
            used_skills: dict = {}

            def run(self, task, emit=None):
                for e in events:
                    emit(e)
                return "最终成品"

        monkeypatch.setattr(app_module, "SupervisorAgent", FakeSV)
        monkeypatch.setattr(
            app_module.intent, "classify",
            lambda *a, **k: {"kind": app_module.ORCHESTRATE, "reason": "测试",
                             "suggested_agents": [], "via": "test"})

        resp = app_module.chat(app_module.ChatReq(message="帮我总结一下这周的训练"))
        assert resp["mode"] == "orchestrated"

        msgs = [m["content"] for m in iso_memory.load_session()["messages"]]
        mids = [m for m in msgs if m.startswith("[编排过程]")]
        assert len(mids) == 1, f"中间产出必须只写一条摘要，实际 {len(mids)} 条：{msgs}"
        assert "查到 3 篇" in mids[0] and "配速 5'30" in mids[0]
        # 顺序反映真实发生次序：中间过程在前、成品在后
        assert msgs[-1] == "最终成品"
        assert msgs.index(mids[0]) < msgs.index("最终成品")

    def test_mid_summary_is_injected_as_context(self, iso_memory, monkeypatch):
        """写进去还得读得回来：追问时 session_turns 必须能看到中间摘要。

        只断言「行写进表了」不够——上下文注入走的是 session_turns()，
        这条把「写入 → 注入」整条链路钉住。
        """
        iso_memory.append_session("user", "帮我总结这周训练")
        iso_memory.append_session("assistant", _summarize_events(
            [{"type": "agent_done", "agent": "analyst", "output": "配速 5'30"}]))
        iso_memory.append_session("assistant", "最终成品")
        turns = iso_memory.session_turns(max_n=10)
        assert any("配速 5'30" in t["content"] for t in turns)


def test_health_endpoint_still_up():
    """顺带确认 app 能被 TestClient 正常加载（避免 import 级回归）。"""
    assert TestClient(app).get("/health").status_code == 200
