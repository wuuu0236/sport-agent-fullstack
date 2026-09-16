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


class StubBackend:
    """替换真实副作用（拆解/派发/综合），让图结构本身可测。"""

    def __init__(self, steps, fail_on=(), review=""):
        self.steps = steps
        self.fail_on = set(fail_on)
        self.review = review
        self.dispatched = []

    def plan(self, task):
        return self.steps

    def dispatch(self, name, inp, results, task=""):
        self.dispatched.append({"agent": name, "input": inp})
        if name in self.fail_on:
            raise ValueError(f"{name} 返回空输出")
        return f"{name}的真实产出", []

    def synthesize(self, task, plan, results):
        parts = [r["output"] for _, r in sorted(results.items()) if r.get("output")]
        return "综合：" + " | ".join(parts)


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
