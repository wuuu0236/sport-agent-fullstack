"""意图管线回归测试：目标检测 / 编排升级判定。

重点覆盖「记忆意图 vs 目标变更」的优先级 bug：
「我想起来了，你记得吗」曾被 _detect_goal 的「我想」正则截走，
误当成目标变更并触发计划生成（2026-09 修复 + 本文件回归锁定）。
"""
from app import _detect_goal, _needs_orchestration


class TestDetectGoal:
    def test_goal_with_modifier(self):
        # 「减脂」+「三分化」要合并成复合目标，不能只提取到「减脂」
        assert _detect_goal("我要减脂，给我安排训练计划，要求三分化") == "减脂三分化"

    def test_goal_simple(self):
        assert _detect_goal("我的目标改成增肌") == "增肌"

    def test_goal_with_metric(self):
        # 体测目标要保留关键数字指标
        goal = _detect_goal("我的目标是体测1km")
        assert goal and "体测" in goal

    def test_recall_phrase_is_not_goal(self):
        # 回归：回忆句曾被「我想」正则误判成目标变更
        assert _detect_goal("我想起来了，你记得吗") is None

    def test_memory_store_phrase_is_not_goal(self):
        assert _detect_goal("记住我今年目标体测") is None

    def test_plain_chat_is_not_goal(self):
        assert _detect_goal("今天天气怎么样") is None

    def test_question_is_not_goal(self):
        assert _detect_goal("怎么才能减脂") is None


class TestNeedsOrchestration:
    def test_recording_stays_single_agent(self):
        # 记录训练不需要多 Agent 编排（避免「记录一次减脂训练」误判）
        assert _needs_orchestration("记一次5公里跑步配速6分") is False
        assert _needs_orchestration("深蹲 4组8次80kg") is False

    def test_weekly_report_orchestrates(self):
        assert _needs_orchestration("帮我生成训练周报") is True
