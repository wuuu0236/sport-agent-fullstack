"""意图管线回归测试：目标检测 / 编排升级判定 / coach 意图分流。

重点覆盖「记忆意图 vs 目标变更」的优先级 bug：
「我想起来了，你记得吗」曾被 _detect_goal 的「我想」正则截走，
误当成目标变更并触发计划生成（2026-09 修复 + 本文件回归锁定）。

另覆盖 coach 的 _classify（2026-09-13 补）：此前只测了编排判定，
coach 内部意图分流零覆盖，「要点/技巧/怎么做」类问法静默答非所问。
"""
import pytest

from app import _detect_goal, _needs_orchestration
from src import config, intent
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

    def test_question_tail_is_not_goal(self):
        """回归（2026-09-17）：问句护栏不能只判句首。

        「我要去跑半马，有什么建议」是「我想…」开头 + 问句结尾的混合句，
        老实现 `goal.startswith(("怎么", "如何", "什么"…))` 只看句首 → 判不是问句
        → 整句被当成新训练目标写进画像、还生成了计划。之后每轮对话都带着这个
        错目标（USER.md 里那行「我要去跑半马有什么建议半马」就是这么来的）。
        """
        assert _detect_goal("我要去跑半马，有什么建议") is None
        assert _detect_goal("我想增肌怎么练") is None
        assert _detect_goal("我要减脂，有什么建议吗") is None

    def test_goal_statement_without_question_still_works(self):
        # 反向锁定：不带疑问尾巴的目标陈述仍要能识别（别把护栏放太宽）
        assert _detect_goal("我要体测") == "体测"
        assert _detect_goal("我想增肌") == "增肌"

    def test_stop_word_at_index_zero_truncates(self):
        """回归（代码审查问题 3）：停用词出现在目标文本**开头**时（idx == 0）。

        老写法 `if 0 < idx` 判假、不截断，于是「我的目标是计划减脂」整句留下
        「计划减脂」这种鬼话，写进 USER.md 还顺带触发计划生成。
        截断成空串后由 `len(goal) < 2` 兜住 → None（宁可不改目标，也别写错目标）。
        """
        assert _detect_goal("我的目标是计划减脂") is None
        # 同类：截断点落在后一个停用词上（「生成」跑到句首）也要能兜住
        assert _detect_goal("我想生成增肌计划") is None

    def test_stop_word_in_the_middle_still_works(self):
        # 反向锁定：停用词在中间的正常截断行为不能被改坏
        assert _detect_goal("我的目标改成增肌") == "增肌"
        assert _detect_goal("我要减脂，给我安排训练计划，要求三分化") == "减脂三分化"


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

    def test_report_with_style_modifier_still_orchestrates(self):
        """回归（代码审查问题 4）：修饰词不能压过产出动作词。

        「帮我生成本周训练周报，格式好看一点」里带「格式」，老实现按概念询问
        判 False → 用户明确要周报，却拿到 coach 一人硬答，不是真正的多 Agent 周报。
        """
        assert _needs_orchestration("帮我生成本周训练周报，格式好看一点") is True
        assert _needs_orchestration("帮我写个周报，格式要清楚") is True
        assert _needs_orchestration("给我一份月度报告，模板随意") is True

    def test_report_concept_question_still_single(self):
        # 反向锁定：纯概念/疑问句式仍不编排（别被上面那条顺手放开）
        for msg in ("周报的格式是什么", "周报怎么写", "周报包含哪些内容",
                    "周报模板", "周报的例子"):
            assert _needs_orchestration(msg) is False, f"「{msg}」被误判成要生成周报"


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

    def test_plain_consult_goes_to_chat(self):
        """回归（2026-09-17）：末尾兜底不能吞掉正常提问。

        「我要去跑半马，有什么建议」正好 12 字，老实现只要能从句子里抠出片段
        （name 非空）就判 analyze_strength，于是抠出伪动作名『去跑半马，』，
        用户收到的回复是「『去跑半马，』还没记录过训练数据，先练一轮，练完用
        『去跑半马， 4组8次60kg』这种格式告诉我」——他要的是半马备赛建议，
        收到的却是让他去记录一个根本不存在的动作。
        """
        for msg in ("我要去跑半马，有什么建议", "我想跑半马，怎么准备",
                    "跑半马要准备什么", "我想练胸，有什么建议"):
            assert _coach._classify(msg) == "chat", f"「{msg}」被塞进固定模板"

    def test_bogus_fragment_never_becomes_action_name(self):
        # 标点必须算停用字：否则字符扫描跨过逗号继续抠，得出『去跑半马，』这种伪动作名
        assert _coach._exercise_name("我要去跑半马，有什么建议") == "去跑半马"

    def test_recorded_exercise_still_gets_trend(self, monkeypatch):
        """反向锁定：消息里真出现**用户记录过的**动作时，仍走结构化趋势分析。

        兜底从「抠出任意片段」收紧为「命中已入库动作名」，不能连正常查询一起收掉。
        """
        from src.agents import coach_agent
        monkeypatch.setattr(
            coach_agent._STORE, "strengths",
            lambda: [{"date": "2026-09-01",
                      "exercises": [{"name": "卧推", "sets": 4, "reps": 8, "weight_kg": 60}]}],
        )
        assert _coach._classify("卧推") == "analyze_strength"

    def test_prompt_focus_only_for_known_targets(self):
        """prompt 里不再把抠出来的片段拼成「XX训练日」。

        focus 收紧前，「我要去跑半马，有什么建议」会让 prompt 出现
        「请直接给一份具体的『去跑半马训练日』」——模型被要求排一个不存在的训练日。
        """
        assert "请直接给一份具体的" not in _coach._build_prompt("我要去跑半马，有什么建议")
        # 部位词仍要保留训练日引导（别把 focus 收没了）
        assert "练「胸」" in _coach._build_prompt("怎么练胸")


class TestClassify:
    """LLM 意图分类（2026-09-16 新增）：关键词规则 → LLM 结构化判断，规则降级为兜底。

    为什么必须锁住：
    · 关键词规则只有「周报 / 总结+时间范围 / 数据驱动计划」三类魔法词才编排，
      「膝盖疼，分析是不是深蹲姿势问题，给康复方案」这类多专长任务被硬答；
    · 但分类一旦走 LLM，就有「模型抽风把普通问答升级成 20 秒编排」的风险，
      所以要锁死两个方向：复杂任务要能识别为编排，简单问答不能被升级。
    """
    @pytest.fixture
    def real_mode(self, monkeypatch):
        """mock_mode 是只读 property（= not LLM_API_KEY），造真实模式得改 key。"""
        monkeypatch.setattr(config.CONFIG, "LLM_API_KEY", "test-key")

    def test_mock_mode_falls_back_to_rule(self, monkeypatch):
        monkeypatch.setattr(config.CONFIG, "LLM_API_KEY", "")
        r = intent.classify("帮我生成周报")
        assert r["kind"] == intent.ORCHESTRATE and r["via"] == "rule"
        r2 = intent.classify("膝盖疼还能跑吗")
        assert r2["kind"] != intent.ORCHESTRATE

    def test_force_orchestrate_skips_classify(self):
        # /supervise 是显式编排入口，不做分类（也不该白花一次调用）
        r = intent.classify("随便一句话", force_orchestrate=True)
        assert r["kind"] == intent.ORCHESTRATE and r["via"] == "forced"

    def test_llm_json_parsed(self, real_mode, monkeypatch):
        payload = ('{"type": "orchestrate", "reason": "需要查资料+算数据+成文",'
                   ' "suggested_agents": ["searcher", "analyst", "planner", "伪造的agent"]}')
        monkeypatch.setattr(intent.llm, "chat", lambda *a, **k: payload)
        r = intent.classify("备战半马，查最新方法，结合我的水平排8周计划")
        assert r["kind"] == intent.ORCHESTRATE and r["via"] == "llm"
        # 不在可派发目录里的名字必须被过滤，否则后面 _parse_plan 会静默丢步
        assert r["suggested_agents"] == ["searcher", "analyst", "planner"]

    def test_llm_markdown_wrapped_json_still_parsed(self, real_mode, monkeypatch):
        payload = '```json\n{"type": "direct_answer", "reason": "单点问题", "suggested_agents": []}\n```'
        monkeypatch.setattr(intent.llm, "chat", lambda *a, **k: payload)
        assert intent.classify("卧推要点")["kind"] == intent.DIRECT

    def test_garbage_output_falls_back_to_rule(self, real_mode, monkeypatch):
        # 分类失败 → 保守回退规则：宁可少拆一次，也不能把问答升级成编排
        monkeypatch.setattr(intent.llm, "chat", lambda *a, **k: "我觉得这个问题很复杂")
        r = intent.classify("膝盖疼还能跑吗")
        assert r["via"] == "rule" and r["kind"] != intent.ORCHESTRATE

    def test_llm_exception_falls_back_to_rule(self, real_mode, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("network down")
        monkeypatch.setattr(intent.llm, "chat", boom)
        r = intent.classify("帮我生成周报")
        assert r["via"] == "rule" and r["kind"] == intent.ORCHESTRATE

    def test_rule_alias_still_exported_from_app(self):
        # app._needs_orchestration 保留为规则别名（测试与历史引用的入口）
        assert _needs_orchestration("帮我生成周报") is True
        assert _needs_orchestration("给我安排一个练胸计划") is False
