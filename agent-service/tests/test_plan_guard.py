"""计划落库质量门回归测试：降级/错误文本绝不能变成「计划」。

背景（真实事故）：编排综合降级时会返回
「主 Agent 综合未生成，以下为各子 Agent 的实际产出汇总：…」（orchestrator._synthesize），
这段文本曾被直接 set_pending 存进 plans.json，于是计划模块里出现了一份
以「综合未生成」开头、内容在表格中间截断的「练胸」计划——界面上看不出异常，
用户也不会察觉自己拿到的是半成品。

修法两层：
1. 写入点质量门 `_stage_plan`：空内容 / 命中降级标记一律拒绝入库；
2. `_coach_answer` 失败时抛出异常（而不是把「教练生成建议时出错：…」当回答返回），
   由调用方给出如实话术——错误信息不会有机会流到计划存储。
"""
import pytest
from fastapi.testclient import TestClient

from src import config
from src import plan_store
from src.agents import get_agent
import app as app_module
from app import app


@pytest.fixture
def plans(tmp_path, monkeypatch):
    """计划/会话存储全部指向临时路径，绝不碰真实 data/。"""
    monkeypatch.setattr(config.CONFIG, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(plan_store, "_PLANS_FILE", tmp_path / "plans.json")
    # 这几个路径在 config 类定义时就按 MEMORY_DIR 算好了，只 patch MEMORY_DIR 不够
    monkeypatch.setattr(config.CONFIG, "SESSION_FILE", tmp_path / "session.json", raising=False)
    monkeypatch.setattr(config.CONFIG, "USER_FILE", tmp_path / "USER.md", raising=False)
    return plan_store


@pytest.fixture
def client(plans):
    # 默认 AGENT_AUTH_TOKEN 为空 = 鉴权关闭，直接打端点即可
    return TestClient(app, raise_server_exceptions=False)


# 各种「这次没真正生成出计划」的文本形态
DEGRADED_SAMPLES = [
    # 编排综合降级：原始子 Agent 产出汇总（历史脏计划的来源）
    "主 Agent 综合未生成，以下为各子 Agent 的实际产出汇总：\n\n【searcher】\n…",
    # coach 报错文本
    "教练生成建议时出错：SSLError(UNEXPECTED_EOF_WHILE_READING)",
    # 计划生成分支的报错文本
    "生成计划时出错：ReadTimeout。你可以换个说法再试。",
    # base._llm 空回复兜底
    "（模型本次未生成内容）可以换个说法再问，或明确告诉我你想做什么：记录训练/分析数据。",
    # LLM 不可用
    "LLM 暂时不可用，已降级",
    # 空白内容
    "   ",
    "",
]


class TestStagePlanGuard:
    @pytest.mark.parametrize("text", DEGRADED_SAMPLES)
    def test_rejects_degraded_content(self, plans, text):
        assert app_module._stage_plan("练胸", text) is False
        assert plans.list_plans()["pending"] is None

    def test_accepts_real_plan(self, plans):
        assert app_module._stage_plan("练胸", "# 练胸计划\n\n周一：上斜卧推 4×8") is True
        pending = plans.list_plans()["pending"]
        assert pending["name"] == "练胸"
        assert pending["goal"] == "练胸"
        assert "上斜卧推" in pending["content"]

    def test_coach_answer_raises_on_failure(self, monkeypatch):
        """失败必须抛出：返回错误文本会被调用方当成计划内容暂存。"""

        def boom(msg, ctx=None):
            raise RuntimeError("上游 502")

        monkeypatch.setattr(get_agent("coach"), "handle", boom)
        with pytest.raises(RuntimeError):
            app_module._coach_answer("怎么练胸")


class TestPlanGenerateEndpoint:
    def test_503_when_coach_raises(self, client, plans, monkeypatch):
        def boom(msg):
            raise RuntimeError("上游 502")

        monkeypatch.setattr(app_module, "_coach_answer", boom)
        r = client.post("/plan/generate", json={"goal": "练胸"})
        assert r.status_code == 503
        # 关键：失败不留痕，pending 必须为空
        assert plans.list_plans()["pending"] is None

    def test_503_when_content_degraded(self, client, plans, monkeypatch):
        monkeypatch.setattr(
            app_module, "_coach_answer", lambda msg: "（模型本次未生成内容）可以换个说法再问。"
        )
        r = client.post("/plan/generate", json={"goal": "练胸"})
        assert r.status_code == 503
        assert plans.list_plans()["pending"] is None

    def test_ok_stages_pending(self, client, plans, monkeypatch):
        monkeypatch.setattr(
            app_module, "_coach_answer", lambda msg: "# 练胸计划\n\n周一：上斜卧推 4×8"
        )
        r = client.post("/plan/generate", json={"goal": "练胸"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "上斜卧推" in body["pending"]["content"]
        assert plans.list_plans()["pending"] is not None

    def test_400_without_goal(self, client):
        assert client.post("/plan/generate", json={}).status_code == 400


class TestGoalChangeGuard:
    """目标变更路径：教练产出不可用时不得写计划，且要如实告知。"""

    def _patch_io(self, monkeypatch):
        monkeypatch.setattr(app_module, "_record_goal", lambda goal: None)
        monkeypatch.setattr(app_module, "_read_active_goal", lambda: "")

    def test_degraded_output_not_staged(self, plans, monkeypatch):
        self._patch_io(monkeypatch)
        monkeypatch.setattr(
            app_module, "_coach_answer", lambda msg: "（模型本次未生成内容）可以换个说法再问。"
        )
        r = app_module._handle_goal_change("我要练胸", "练胸")
        assert plans.list_plans()["pending"] is None
        assert "未写入" in r["output"]

    def test_healthy_output_is_staged(self, plans, monkeypatch):
        self._patch_io(monkeypatch)
        monkeypatch.setattr(
            app_module, "_coach_answer", lambda msg: "# 练胸计划\n\n周一：上斜卧推 4×8"
        )
        r = app_module._handle_goal_change("我要练胸", "练胸")
        pending = plans.list_plans()["pending"]
        assert pending is not None
        assert "上斜卧推" in pending["content"]
        assert r["agent"] == "coach"

    def test_coach_exception_no_stage(self, plans, monkeypatch):
        self._patch_io(monkeypatch)

        def boom(msg):
            raise RuntimeError("上游 502")

        monkeypatch.setattr(app_module, "_coach_answer", boom)
        r = app_module._handle_goal_change("我要练胸", "练胸")
        assert plans.list_plans()["pending"] is None
        assert "已记录你的新训练目标" in r["output"]
