"""plan_store 回归测试：pending 流转 / replace / add / 切换 / 删除提升。

存储指向临时路径，不碰真实 data/plans.json。
"""
import pytest

from src import config
from src import plan_store


@pytest.fixture
def plans(tmp_path, monkeypatch):
    monkeypatch.setattr(config.CONFIG, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(plan_store, "_PLANS_FILE", tmp_path / "plans.json")
    return plan_store


class TestPendingFlow:
    def test_no_pending_initially(self, plans):
        assert plans.list_plans()["pending"] is None
        assert plans.list_plans()["plans"] == []

    def test_set_and_replace(self, plans):
        plans.set_pending({"name": "减脂", "goal": "减脂", "content": "# 计划A"})
        r = plans.apply_pending("replace")
        assert r["ok"] is True
        data = plans.list_plans()
        assert data["pending"] is None
        assert data["activeId"] is not None
        assert len(data["plans"]) == 1

    def test_replace_keeps_plan_id(self, plans):
        # 已有 active 计划时，replace 应复用其 id（前端按 id 定位）
        plans.set_pending({"name": "A", "goal": "减脂", "content": "A"})
        old_id = plans.apply_pending("replace")["active"]["id"]
        plans.set_pending({"name": "B", "goal": "增肌", "content": "B"})
        r = plans.apply_pending("replace")
        assert r["active"]["id"] == old_id
        # 替换不新增条目
        assert len(plans.list_plans()["plans"]) == 1

    def test_add_keeps_old_active(self, plans):
        plans.set_pending({"name": "A", "goal": "减脂", "content": "A"})
        first = plans.apply_pending("replace")["active"]
        plans.set_pending({"name": "B", "goal": "增肌", "content": "B"})
        r = plans.apply_pending("add")
        assert r["ok"] is True
        data = plans.list_plans()
        assert len(data["plans"]) == 2
        assert data["activeId"] == first["id"]  # add 不改变激活计划

    def test_apply_without_pending(self, plans):
        r = plans.apply_pending("replace")
        assert r["ok"] is False

    def test_unsupported_action(self, plans):
        plans.set_pending({"name": "A", "goal": "减脂", "content": "A"})
        assert plans.apply_pending("delete")["ok"] is False


class TestSwitchAndDelete:
    def test_switch(self, plans):
        plans.set_pending({"name": "A", "goal": "减脂", "content": "A"})
        a = plans.apply_pending("replace")["active"]
        plans.set_pending({"name": "B", "goal": "增肌", "content": "B"})
        b = plans.apply_pending("add")["ok"]
        assert b
        r = plans.switch_plan(a["id"])
        assert r["ok"] is True
        assert plans.list_plans()["activeId"] == a["id"]

    def test_switch_unknown_id(self, plans):
        assert plans.switch_plan("nope")["ok"] is False

    def test_delete_active_promotes_next(self, plans):
        plans.set_pending({"name": "A", "goal": "减脂", "content": "A"})
        a = plans.apply_pending("replace")["active"]
        plans.set_pending({"name": "B", "goal": "增肌", "content": "B"})
        plans.apply_pending("add")
        r = plans.delete_plan(a["id"])
        assert r["ok"] is True
        data = plans.list_plans()
        assert len(data["plans"]) == 1
        assert data["activeId"] == data["plans"][0]["id"]  # 自动提升，不留悬空 active

    def test_delete_last_clears_active(self, plans):
        plans.set_pending({"name": "A", "goal": "减脂", "content": "A"})
        a = plans.apply_pending("replace")["active"]
        plans.delete_plan(a["id"])
        data = plans.list_plans()
        assert data["plans"] == []
        assert data["activeId"] is None


class TestConcurrency:
    def test_concurrent_apply_no_loss(self, plans):
        """两个线程同时 add 两份计划：加锁后两条都必须落库（修复前会互相覆盖）。"""
        import threading
        plans.set_pending({"name": "seed", "goal": "减脂", "content": "seed"})
        plans.apply_pending("replace")

        def worker(name):
            # 并发场景必须走原子组合操作：分开调 set_pending + apply_pending
            # 两步间锁会释放，另一线程的 pending 会覆盖当前线程的（丢计划）
            plans.stage_and_apply({"name": name, "goal": name, "content": name}, "add")

        threads = [threading.Thread(target=worker, args=(n,)) for n in ("X", "Y")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        names = {p["name"] for p in plans.list_plans()["plans"]}
        assert {"seed", "X", "Y"} <= names
