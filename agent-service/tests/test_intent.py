"""意图管线回归测试：目标检测 / 编排升级判定 / coach 意图分流。

重点覆盖「记忆意图 vs 目标变更」的优先级 bug：
「我想起来了，你记得吗」曾被 _detect_goal 的「我想」正则截走，
误当成目标变更并触发计划生成（2026-09 修复 + 本文件回归锁定）。

另覆盖 coach 的 _classify（2026-09-13 补）：此前只测了编排判定，
coach 内部意图分流零覆盖，「要点/技巧/怎么做」类问法静默答非所问。
"""
from app import _detect_goal, _needs_orchestration
from src.agents.coach_agent import CoachAgent

_coach = CoachAgent()


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


class TestCoachClassify:
    """coach 单 Agent 的意图分流回归。

    回归背景：_classify 末尾的兜底是「消息 ≤12 字 + 能抠出一个动作名 →
    力量趋势分析」，而「要点 / 技巧 / 怎么做」这组技术问法此前不在任何
    白名单里，于是掉进兜底去查渐进超负荷，答非所问：

        「总结一下卧推要点」→ 抠出动作名「总结」→「『总结』还没记录过训练数据」

    对照组很说明问题：「总结一下卧推的发力要点」因为带了「发力」（属于下方
    training-advice 白名单）而侥幸走对，说明漏的是这组技术问法词本身。
    """

    def test_technique_questions_go_to_chat(self):
        # 问动作要领 / 技巧 / 怎么做的，必须走对话直答，不能被当成查数据
        for msg in (
            "总结一下卧推要点",
            "卧推要点",
            "深蹲技巧",
            "引体向上怎么做",
            "深蹲怎么做才标准",
            "卧推的发力要点",
            "硬拉的注意事项",
        ):
            assert _coach._classify(msg) == "chat", f"「{msg}」被误判为查数据"

    def test_real_analysis_intent_still_analyses(self):
        # 反向锁定：真要看渐进超负荷趋势的仍走力量分析，别被上面那组顺手改坏
        for msg in (
            "深蹲有进步吗",
            "卧推怎么样",
            "硬拉容量趋势",
            "卧推数据分析",
        ):
            assert _coach._classify(msg) == "analyze_strength", f"「{msg}」丢了分析路径"

    def test_run_data_analysis_unchanged(self):
        # 跑步数据分析路径不受影响
        assert _coach._classify("分析我最近的跑步心率") == "analyze_run"

    def test_pain_still_goes_to_chat(self):
        # 伤痛红线：仍走对话（不能被任何新白名单截去别处）
        assert _coach._classify("我膝盖疼还能跑吗") == "chat"
