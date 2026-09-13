"""planner 产出类型回归：周报请求必须出周报，不能被套上「计划」的骨架。

回归背景（2026-09-13 实测发现）：planner 的提示词此前写死
「生成一份结构化、可执行的训练计划」，而 `orchestrator._synthesize` 在
「最后一步是 planner」时会**直接采用其产出**作为最终答案，于是
「帮我生成周报」交付出去的东西标题是「你的训练计划（修正版）」。

连「评审不过 → planner 重写」这条路也救不回来：重写调的是同一个写死计划的
提示词，评审就算正确指出「用户要的是周报不是计划」也白搭。所以修的是
planner 的产出类型切换 + 把原始用户任务透传下去（ctx["task"]）。
"""
import pytest

from src import config
from src.agents.planner_agent import PlannerAgent, deliverable_of, PLAN, WEEKLY


class TestDeliverableOf:
    def test_weekly_words(self):
        for t in (
            "帮我生成周报",
            "给我一份本月训练报告",
            "总结这周的训练情况",
            "回顾最近的训练",
            "复盘一下这个月的训练",
        ):
            assert deliverable_of(t) == WEEKLY, t

    def test_plan_words(self):
        for t in (
            "根据我最近的训练数据帮我安排下周计划",
            "给我安排一个练胸计划",
            "帮我生成减脂三分化计划",
        ):
            assert deliverable_of(t) == PLAN, t

    def test_weekly_keyword_wins_over_plan_keyword(self):
        # 一份周报里也会出现「下周计划」字样，所以计划类词不参与判定
        assert deliverable_of("帮我生成周报，包含下周计划建议") == WEEKLY

    def test_empty_is_plan(self):
        assert deliverable_of("") == PLAN


class TestPlannerPrompt:
    def test_weekly_request_builds_weekly_prompt(self):
        p = PlannerAgent()._build_prompt("帮我生成周报", WEEKLY)
        assert "训练周报" in p
        assert "本期概览" in p
        # 抬头不能说「生成训练计划」，否则模型会顺着计划骨架写
        assert "训练计划" not in p.split("【用户需求】")[0]

    def test_plan_request_builds_plan_prompt(self):
        p = PlannerAgent()._build_prompt("给我安排练胸计划", PLAN)
        assert "训练计划" in p
        assert "本期概览" not in p

    def test_both_prompts_carry_user_profile(self):
        # 计划/周报都必须吃到画像（伤病·体态·心率基线），别只为计划保留
        for kind in (WEEKLY, PLAN):
            assert "【用户画像" in PlannerAgent()._build_prompt("随便", kind)


class TestHandleUsesOriginalTask:
    """编排会把 @s1/@s2 的真实产出拼进 planner 的输入，判定必须看原始任务。"""

    @pytest.fixture(autouse=True)
    def _real_mode(self, monkeypatch):
        # 该用例要走到 _llm 分支，强制真实模式，避免依赖 .env 里的 key。
        # mock_mode 是只读 property（= not LLM_API_KEY），所以改底层字段。
        monkeypatch.setattr(config.CONFIG, "LLM_API_KEY", "test-key", raising=False)

    def _capture(self, user_msg, ctx):
        p = PlannerAgent()
        box = {}

        def fake_llm(prompt, ctx=None):
            box["prompt"] = prompt
            return "ok"

        p._llm = fake_llm
        p.handle(user_msg, ctx)
        return box.get("prompt", "")

    def test_injected_subagent_output_does_not_hijack_type(self):
        injected = (
            "帮我生成周报\n\n"
            "请结合 <searcher：建议调整训练计划与周期安排> "
            "与 <analyst：本周 6.0km / 配速 6:00 / 平均心率 145> 综合完成本任务"
        )
        prompt = self._capture(injected, {"task": "帮我生成周报"})
        assert "训练周报" in prompt, "带「计划」字样的子 Agent 产出把周报需求带偏了"

    def test_plan_task_still_builds_plan_prompt(self):
        prompt = self._capture("给我安排练胸计划", {"task": "给我安排练胸计划"})
        assert "训练计划" in prompt

    def test_falls_back_to_user_msg_without_task(self):
        # /agent/planner 直调时没有 ctx["task"]，退回整段 user_msg 判断
        prompt = self._capture("帮我生成周报", None)
        assert "训练周报" in prompt
