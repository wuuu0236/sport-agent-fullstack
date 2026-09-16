"""LangGraph 编排图回归测试（2026-09-16 迁移时新增）。

迁移把手写主循环换成了 StateGraph，必须锁住三件事，否则「换框架」很容易悄悄改变行为：

1. **事件序列不变**——前端看板与 Java 网关按事件类型渲染，多一种/少一种都是回归；
2. **依赖校验生效**——@sN 漏引时自动补，无效引用要清掉（这是本次新增的防线）；
3. **重写只做一次**——评审不过才重写、且被评节点必须是 planner，不许出现重写风暴。

全部用打桩后端跑，不调 LLM、不碰真实数据目录。
"""
import pytest

from src import graph as graph_mod
from src.graph import _GraphBackend, _review_failed, run_orchestration, validate_steps

# 打桩产出：必须**够长且含必备段落**，否则会被评审第一层（规则检查）判为
# 「过短/缺段落」，用例就测不到第二、三层的接线的了。真实子 Agent 产出只会更长。
STUB_OUT = ("本周训练概览：共完成 4 次训练，累计跑量 23.5 km，平均配速 5:42 分/km，"
            "力量训练 2 次。数据显示跑量比上周增加 12%，问题在于周三强度课配速掉到 6:10。"
            "建议下周把间歇课挪到周二，下周目标跑量 26 km。")


class StubBackend:
    """替换真实副作用（拆解/派发/综合），让图结构本身可测。"""

    def __init__(self, steps, fail_on=(), review="", output=None):
        self.steps = steps
        self.fail_on = set(fail_on)
        self.review = review
        self.output = output
        self.dispatched = []

    def plan(self, task):
        return self.steps

    def dispatch(self, name, inp, results, task=""):
        self.dispatched.append({"agent": name, "input": inp})
        if name in self.fail_on:
            raise ValueError(f"{name} 返回空输出")
        return (self.output if self.output is not None else f"{name}：{STUB_OUT}"), []

    def synthesize(self, task, plan, results, issues=""):
        parts = [r["output"] for _, r in sorted(results.items()) if r.get("output")]
        out = "综合：" + " | ".join(parts)
        return out + f"\n[issues]{issues}" if issues else out


@pytest.fixture(autouse=True)
def _no_staged(monkeypatch):
    """默认无暂存记录，避免真实 data/ 目录里的残留影响事件断言。"""
    class _Store:
        def staged(self):
            return []
    monkeypatch.setattr(graph_mod, "SportStore", _Store)


def _steps(*names):
    return [{"id": f"s{i + 1}", "agent": n, "input": f"输入{i + 1}", "expect": ""}
            for i, n in enumerate(names)]


def _run(steps, backend=None, expected_events=None):
    events = []
    backend = backend or StubBackend(steps)
    out, used = run_orchestration("帮我生成周报", emit=events.append, backend=backend)
    return out, used, events, backend


# ---------------------------------------------------------------- 1. 事件序列


class TestEventSequence:
    def test_event_types_match_frontend_contract(self):
        steps = _steps("analyst", "planner")
        out, _used, events, _b = _run(steps)
        assert [e["type"] for e in events] == [
            "start",
            "plan",
            "agent_start", "agent_done",     # s1 analyst
            "agent_start", "agent_done",     # s2 planner
            "agent_start", "agent_done",     # reviewer（固定挂载）
            "complete",
        ]
        assert events[-1]["final"] is True
        assert events[-1]["output"] == out   # complete 携带的正是最终输出

    def test_dispatch_runs_once_per_step(self):
        steps = _steps("analyst", "searcher", "planner")
        _out, _u, events, backend = _run(steps)
        assert [d["agent"] for d in backend.dispatched] == ["analyst", "searcher", "planner"]
        assert events[1]["steps"] == ["analyst", "searcher", "planner"]
        assert events[1]["total"] == 3

    def test_failed_node_emits_agent_error_and_continues(self):
        # 中间节点失败不影响后续节点（失败跳过继续，绝不空转）
        steps = _steps("analyst", "searcher", "planner")
        backend = StubBackend(steps, fail_on=["searcher"])
        _out, _u, events, _b = _run(steps, backend)
        types = [(e["type"], e.get("agent")) for e in events if "agent" in e]
        assert ("agent_error", "searcher") in types
        assert ("agent_done", "planner") in types

    def test_pending_commit_emitted_when_staged(self, monkeypatch):
        class _Store:
            def staged(self):
                return [{"_staged_id": "x", "distance_km": 6}]
        monkeypatch.setattr(graph_mod, "SportStore", _Store)
        out, _u, events, _b = _run(_steps("planner"))
        assert [e["type"] for e in events][-1] == "pending_commit"
        assert events[-1]["count"] == 1
        # 暂存附注必须出现在**返回文本**里（complete 事件里的 output 不含附注，与迁移前一致）
        assert "等待确认后入库" in out


# ---------------------------------------------------------------- 2. 评审与重写


class _FakeAgent:
    def __init__(self, out):
        self.out = out
        self.calls = 0

    def handle(self, inp, ctx=None):
        self.calls += 1
        return self.out


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """让这套测试完全离线：评审/重写节点默认用打桩 Agent。

    没有这道夹具时，review 节点会真的调 LLM（本地 .env 有 key）——不仅慢（首轮实测
    38s），还会因为模型返回 ISSUES 而触发真实重写，让事件序列断言变得不确定。
    需要验证重写路径的用例自己再 monkeypatch 覆盖即可。
    """
    reviewer = _FakeAgent("PASS 无问题")
    other = _FakeAgent("打桩产出")
    monkeypatch.setattr(graph_mod, "get_agent",
                        lambda n: reviewer if n == "reviewer" else other)
    return {"reviewer": reviewer, "other": other}


class TestReviewGate:
    def test_review_failed_only_on_issues_prefix(self):
        assert _review_failed("ISSUES: 数据不一致") is True
        assert _review_failed("PASS") is False
        assert _review_failed("") is False
        assert _review_failed("（模型本次未生成内容）") is False

    def test_planner_issues_triggers_single_rewrite(self, monkeypatch):
        steps = _steps("analyst", "planner")
        reviewer = _FakeAgent("ISSUES: 缺数据引用")
        planner = _FakeAgent("重写后的周报")
        monkeypatch.setattr(graph_mod, "get_agent",
                            lambda n: reviewer if n == "reviewer" else planner)
        out, _u, events, _b = _run(steps)
        assert planner.calls == 1                      # 只重写一次，不循环
        assert "重写后的周报" in out                    # 重写结果进入最终输出
        assert any(e.get("agent") == "planner" and e["type"] == "agent_done"
                   for e in events)

    def test_non_planner_issues_does_not_rewrite(self, monkeypatch):
        # 最后成功节点是 analyst 时，即使评审不过也不重写（无综合品可改）
        steps = _steps("analyst")
        reviewer = _FakeAgent("ISSUES: 数据可疑")
        other = _FakeAgent("不该被调用")
        monkeypatch.setattr(graph_mod, "get_agent",
                            lambda n: reviewer if n == "reviewer" else other)
        _run(steps)
        assert other.calls == 0

    def test_pass_skips_rewrite(self, monkeypatch):
        reviewer = _FakeAgent("PASS 很好")
        other = _FakeAgent("不该被调用")
        monkeypatch.setattr(graph_mod, "get_agent",
                            lambda n: reviewer if n == "reviewer" else other)
        _run(_steps("analyst", "planner"))
        assert other.calls == 0


# ------------------------------------------------- 2b. 评审三层（方案 P1-1）


class TestReviewLayers:
    def test_rule_blocking_skips_llm_review(self, monkeypatch):
        """第一层：规则判不过时不调 LLM 评审（省一次调用，结论可复现）。"""
        reviewer = _FakeAgent("PASS")
        other = _FakeAgent("不该被调用")
        monkeypatch.setattr(graph_mod, "get_agent",
                            lambda n: reviewer if n == "reviewer" else other)
        steps = _steps("analyst")
        backend = StubBackend(steps, output="太短")
        out, _u, events, _b = _run(steps, backend)
        assert reviewer.calls == 0                     # 规则层短路了 LLM
        assert events[-1]["final"] is True
        # 第三层：非 planner 步骤的评审意见必须活着传到综合节点（桩后端把它回显出来）
        assert "ISSUES（规则检查）" in out and "过短" in out

    def test_rule_pass_falls_through_to_llm(self, monkeypatch):
        """规则层放行 → 仍走 LLM 评审（且打上实际使用的评审模型名）。"""
        reviewer = _FakeAgent("PASS 没问题")
        monkeypatch.setattr(graph_mod, "get_agent",
                            lambda n: reviewer if n == "reviewer" else _FakeAgent("x"))
        _out, _u, events, _b = _run(_steps("analyst", "planner"))
        assert reviewer.calls == 1
        rev = [e for e in events if e.get("agent") == "reviewer"][-1]
        assert rev["reviewer_model"]          # 事件里带评审模型，便于排查

    def test_planner_issues_not_left_in_review_issues(self, monkeypatch):
        """planner 的情报靠重写消化，不该再进 synthesize 的「已知不可靠项」。"""
        reviewer = _FakeAgent("ISSUES: 缺数据引用")
        monkeypatch.setattr(graph_mod, "get_agent",
                            lambda n: reviewer if n == "reviewer" else _FakeAgent("重写后的周报"))
        out, _u, _e, _b = _run(_steps("analyst", "planner"))
        assert "ISSUES" not in out                     # 已重写，不再把意见透给综合


class TestSynthesizeIssues:
    def _patch_llm(self, monkeypatch, captured):
        def fake_chat(messages, **kw):
            captured["messages"] = messages
            return "主 Agent 综合结果"
        monkeypatch.setattr(graph_mod.llm, "chat", fake_chat)
        monkeypatch.setattr(graph_mod.memory, "load", lambda: None)
        monkeypatch.setattr(graph_mod.memory, "list_store", lambda k: [])
        monkeypatch.setattr(type(graph_mod.config.CONFIG), "mock_mode",
                            property(lambda self: False))

    def test_issues_reach_synthesis_prompt(self, monkeypatch):
        captured = {}
        self._patch_llm(monkeypatch, captured)
        plan = _steps("analyst", "searcher", "writer")
        results = {s["id"]: {"agent": s["agent"], "output": STUB_OUT} for s in plan}
        out = _GraphBackend().synthesize("帮我生成周报", plan, results,
                                         issues="ISSUES: 数字待核对 23.5km")
        assert out == "主 Agent 综合结果"
        blob = captured["messages"][1]["content"]
        assert "评审未通过项" in blob and "数字待核对" in blob

    def test_no_issues_keeps_prompt_clean(self, monkeypatch):
        captured = {}
        self._patch_llm(monkeypatch, captured)
        plan = _steps("analyst", "searcher", "writer")
        results = {s["id"]: {"agent": s["agent"], "output": STUB_OUT} for s in plan}
        _GraphBackend().synthesize("帮我生成周报", plan, results)
        assert "评审未通过项" not in captured["messages"][1]["content"]

    def test_direct_return_annotated_with_issues(self):
        """直出路径（单步 / planner 产出采用）不经过 LLM，意见要附注在产出后面。"""
        plan = _steps("analyst")
        results = {plan[0]["id"]: {"agent": "analyst", "output": STUB_OUT}}
        out = _GraphBackend().synthesize("看看我的数据", plan, results,
                                         issues="ISSUES: 数字待核对 88km")
        assert STUB_OUT in out and "评审提示" in out and "88km" in out

    def test_direct_return_clean_without_issues(self):
        plan = _steps("planner")
        results = {plan[0]["id"]: {"agent": "planner", "output": STUB_OUT}}
        assert _GraphBackend().synthesize("排个计划", plan, results) == STUB_OUT


# --------------------------------- 2c. 重写失败不得泄露坏产出（2026-09-16 复查）
#
# 病根是一条「三个节点接力丢信息」的链：
#   review 判 planner 产出不过 → 走重写；重写失败 → 只保留原产出、**评审意见原地蒸发**
#   （state["review"] 只服务重写节点，综合层不读）→ synthesize 看到最后一步是 planner
#   就直出 → 用户拿到一份「已知有问题、且可能根本没生成出来」的成品，却毫无提示。


def _patch_llm_synth(monkeypatch, captured):
    """让 `_GraphBackend.synthesize` 的 LLM 综合分支可测（离线）。"""
    def fake_chat(messages, **kw):
        captured["messages"] = messages
        return "主 Agent 综合结果"
    monkeypatch.setattr(graph_mod.llm, "chat", fake_chat)
    monkeypatch.setattr(graph_mod.memory, "load", lambda: None)
    monkeypatch.setattr(graph_mod.memory, "list_store", lambda k: [])
    monkeypatch.setattr(type(graph_mod.config.CONFIG), "mock_mode",
                        property(lambda self: False))


class TestRewriteFailureDoesNotLeak:
    def test_failed_rewrite_passes_review_to_synthesize(self, monkeypatch):
        """重写失败时评审意见必须继续传递（方案 A）。

        老实现 `return {"results": results}`：产出留下、意见丢掉，于是综合层
        拿到的是一份「评审判过没过」的成品 + 一句空 issues。
        注意图里的 `get_agent` 只被评审节点与重写节点调用（派发走的是打桩后端）。
        """
        reviewer = _FakeAgent("ISSUES: 缺数据引用")
        rewrite_fail = _FakeAgent("（模型本次未生成内容）")
        monkeypatch.setattr(graph_mod, "get_agent",
                            lambda n: reviewer if n == "reviewer" else rewrite_fail)
        out, _u, events, _b = _run(_steps("analyst", "planner"))
        assert rewrite_fail.calls == 1                   # 重写确实跑了，且只跑一次
        # 桩后端把 issues 回显进产出，据此确认意见真的到了综合层
        assert "ISSUES" in out and "缺数据引用" in out
        assert any(e["type"] == "agent_error" and e.get("agent") == "planner"
                   for e in events)

    def test_undeliverable_planner_output_not_returned_directly(self, monkeypatch):
        """方案 B：机械缺陷产出不得被综合层直出，改走汇总兜底。"""
        captured = {}
        _patch_llm_synth(monkeypatch, captured)
        plan = _steps("analyst", "planner")
        results = {
            plan[0]["id"]: {"agent": "analyst", "output": STUB_OUT},
            plan[1]["id"]: {"agent": "planner", "output": "（模型本次未生成内容）"},
        }
        out = _GraphBackend().synthesize("帮我生成周报", plan, results)
        assert out == "主 Agent 综合结果"                 # 走了 LLM 综合，不是直出
        blob = captured["messages"][1]["content"]
        assert STUB_OUT in blob                          # 有效产出喂给了综合
        assert "模型本次未生成内容" not in blob            # 坏产出没有被喂进去

    def test_undeliverable_single_output_reports_honestly(self):
        """单步产出是降级文案时，报「未产出有效结果」而不是把降级文案直出。"""
        plan = _steps("planner")
        results = {plan[0]["id"]: {"agent": "planner",
                                   "output": "（LLM 暂时不可用，已降级）请稍后再试"}}
        out = _GraphBackend().synthesize("排个计划", plan, results)
        assert "未产出有效结果" in out
        assert "暂时不可用" not in out

    def test_deliverable_planner_output_still_direct(self):
        """反向锁定：正常 planner 产出仍直出（别把兜底改成了永远多花一次 LLM）。"""
        plan = _steps("planner")
        results = {plan[0]["id"]: {"agent": "planner", "output": STUB_OUT}}
        assert _GraphBackend().synthesize("排个计划", plan, results) == STUB_OUT


# ------------------------------- 2d. 区分「评审失败」与「评审通过」（2026-09-16 复查）
#
# 评审模型不可用时 `llm.chat` 会吞异常、返回降级文案；老实现「首行不是 ISSUES 就放行」
# 于是把「没完成评审」读成「评审通过」——质量门在评审服务挂掉时静默失效，
# 对外还表现成「已通过评审」。

REVIEW_DOWN = "（LLM 暂时不可用，已降级）请稍后再试，或检查 .env 中的 LLM_API_KEY / LLM_BASE_URL 配置。"


class TestReviewUnavailableIsNotPass:
    def test_verdict_is_tristate(self):
        from src.graph import _review_verdict
        assert _review_verdict("ISSUES: 数据不一致") == "issues"
        assert _review_verdict("PASS 无问题") == "pass"
        assert _review_verdict(REVIEW_DOWN) == "unavailable"
        assert _review_verdict("（模型本次未生成内容）") == "unavailable"
        assert _review_verdict("") == "unavailable"

    def test_markdown_emphasis_still_counts_as_issues(self):
        """模型偶尔输出「**ISSUES**」「- ISSUES」，别因为行首符号漏判成通过。"""
        assert _review_failed("**ISSUES**: 缺数据引用") is True
        assert _review_failed("> ISSUES: 数字可疑") is True
        assert _review_failed("## PASS") is False

    def test_markdown_issues_triggers_rewrite(self, monkeypatch):
        reviewer = _FakeAgent("**ISSUES**: 缺数据引用")
        planner = _FakeAgent("重写后的周报")
        monkeypatch.setattr(graph_mod, "get_agent",
                            lambda n: reviewer if n == "reviewer" else planner)
        out, _u, _e, _b = _run(_steps("analyst", "planner"))
        assert planner.calls == 1 and "重写后的周报" in out

    def test_degraded_review_annotates_output(self, monkeypatch):
        """评审降级 → 最终输出必须如实标注「未完成质量评审」。"""
        _patch_llm_synth(monkeypatch, {})
        monkeypatch.setattr(graph_mod, "get_agent",
                            lambda n: _FakeAgent(REVIEW_DOWN))
        out, _u, events, _b = _run(_steps("analyst", "planner"))
        assert "未完成质量评审" in out
        rev = [e for e in events if e.get("agent") == "reviewer"][-1]
        assert rev["review_unavailable"] is True

    def test_reviewer_crash_annotates_output(self, monkeypatch):
        """评审节点抛异常同样是「没完成评审」，不是通过。"""
        class _Boom:
            def handle(self, inp, ctx=None):
                raise TimeoutError("评审超时")
        monkeypatch.setattr(graph_mod, "get_agent", lambda n: _Boom())
        out, _u, events, _b = _run(_steps("analyst", "planner"))
        assert "未完成质量评审" in out
        assert any(e["type"] == "agent_error" and e.get("agent") == "reviewer"
                   for e in events)

    def test_normal_pass_has_no_unavailable_note(self, monkeypatch):
        out, _u, events, _b = _run(_steps("analyst", "planner"))
        assert "未完成质量评审" not in out
        rev = [e for e in events if e.get("agent") == "reviewer"][-1]
        assert not rev.get("review_unavailable")


# ---------------------------------------------------------------- 3. 依赖校验


class TestValidateSteps:
    def test_fills_missing_reference_for_planner(self):
        raw = _steps("analyst", "planner")
        raw[1]["input"] = "请生成周报"
        steps, filled = validate_steps(raw)
        assert "@s1" in steps[1]["input"]
        assert filled and filled[0]["step"] == "s2"

    def test_keeps_existing_reference(self):
        raw = _steps("analyst", "planner")
        raw[1]["input"] = "请结合 @s1 的分析生成周报"
        steps, filled = validate_steps(raw)
        assert steps[1]["input"].count("@s1") == 1   # 不重复补
        assert filled == []

    def test_first_step_never_gets_reference(self):
        raw = _steps("analyst")
        steps, filled = validate_steps(raw)
        assert "@" not in steps[0]["input"]
        assert filled == []

    def test_invalid_reference_removed(self):
        # 指向不存在的步骤（@s9）会变成字面量塞给子 Agent，必须清掉
        raw = _steps("analyst", "planner")
        raw[1]["input"] = "请结合 @s9 的产出生成周报"
        steps, _filled = validate_steps(raw)
        assert "@s9" not in steps[1]["input"]

    def test_independent_step_not_forced_to_depend(self):
        # 两个互不相关的步骤（searcher 查资料）不该被硬塞引用
        raw = _steps("searcher", "searcher")
        raw[1]["expect"] = "另一批资料"
        steps, filled = validate_steps(raw)
        assert filled == []


# ---------------------------------------------------------------- 4. 拆解兜底模板


class TestFallbackPlan:
    def test_injury_task_gets_injury_template(self):
        # 迁移前一律 searcher→analyst→planner：伤病类会被套上「检索最新方法」的管线
        from src.graph import _fallback_plan
        plan = _fallback_plan("膝盖疼，分析是不是深蹲姿势问题")
        assert [s["agent"] for s in plan] == ["analyst", "planner"]
        assert "@s1" in plan[1]["input"]

    def test_weekly_report_template_references_upstream(self):
        from src.graph import _fallback_plan
        plan = _fallback_plan("帮我生成周报")
        assert [s["agent"] for s in plan] == ["analyst", "planner"]
        assert "@s1" in plan[1]["input"]

    def test_parse_plan_drops_unknown_agent_and_clamps_steps(self):
        from src.graph import _parse_plan
        raw = ('[{"id":"s1","agent":"analyst","input":"a"},'
               '{"id":"s2","agent":"不存在的agent","input":"b"},'
               '{"id":"s3","agent":"planner","input":"c"},'
               '{"id":"s4","agent":"planner","input":"d"},'
               '{"id":"s5","agent":"planner","input":"e"},'
               '{"id":"s6","agent":"planner","input":"f"}]')
        steps = _parse_plan(raw)
        assert [s["agent"] for s in steps] == ["analyst", "planner", "planner", "planner"]
        assert len(steps) <= 4
