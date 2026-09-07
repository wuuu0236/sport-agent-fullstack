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

    def test_summary_with_time_range_orchestrates(self):
        # 阶段总结类：总结/回顾 + 时间范围 → 多源汇合（读周聚合数据 + 综合成文）→ 编排
        assert _needs_orchestration("帮我总结一下这周的训练") is True
        assert _needs_orchestration("回顾最近的训练情况") is True
        assert _needs_orchestration("给我一份本月训练报告") is True

    def test_summary_without_range_stays_single(self):
        # 无时间范围的「总结」是单点问题，coach 直答即可，不编排
        assert _needs_orchestration("总结一下卧推的发力要点") is False

    def test_data_driven_plan_orchestrates(self):
        # 数据驱动计划：分析/依据 + 数据来源 + 计划产出，三要素齐 → 编排
        assert _needs_orchestration("根据我最近的训练数据帮我安排下周计划") is True
        assert _needs_orchestration("分析我的训练情况，出一份方案") is True

    def test_plain_plan_stays_single(self):
        # 单源计划请求（无数据依据）：coach 直答，不编排
        assert _needs_orchestration("给我安排一个练胸计划") is False
        assert _needs_orchestration("新手增肌计划怎么定") is False

    def test_talking_about_report_stays_single(self):
        # 「谈论周报」≠「要生成周报」：问答类不编排
        assert _needs_orchestration("周报一般包含什么内容") is False
