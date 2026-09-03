"""memory 模块回归测试：双存储读写 / 上限 / 并发追加。

并发用例是 2026-09 加锁修复的直接证据：16 线程 × 10 次 append，
修复前 read-modify-write 竞态会丢消息。
"""
import threading

import pytest

from src import config, memory
from src.memory import MemoryStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config.CONFIG, "USER_FILE", tmp_path / "USER.md")
    monkeypatch.setattr(config.CONFIG, "MEMORY_FILE", tmp_path / "MEMORY.md")
    monkeypatch.setattr(config.CONFIG, "SESSION_FILE", tmp_path / "session.json")
    return MemoryStore()


class TestRememberForget:
    def test_remember_and_list(self, store):
        ok, msg = store.remember("user", "静息心率55")
        assert ok
        assert "静息心率55" in store.list_store("user")

    def test_duplicate_skipped(self, store):
        store.remember("user", "静息心率55")
        ok, msg = store.remember("user", "静息心率55")
        assert ok and "重复" in msg
        assert store.list_store("user").count("静息心率55") == 1

    def test_limit_enforced(self, store):
        big = "x" * (memory.USER_LIMIT + 10)
        ok, msg = store.remember("user", big)
        assert ok is False and "上限" in msg

    def test_invalid_target(self, store):
        assert store.remember("whatever", "x")[0] is False

    def test_forget_by_substring(self, store):
        store.remember("user", "静息心率55")
        ok, _ = store.forget("user", "静息心率")
        assert ok
        assert store.list_store("user") == []

    def test_persisted_across_instances(self, store, tmp_path):
        store.remember("user", "膝盖不好")
        # 新实例从同一磁盘文件加载（模拟进程重启）
        again = MemoryStore()
        assert "膝盖不好" in again.list_store("user")


class TestSession:
    def test_append_and_trim(self, store):
        for i in range(60):
            memory.append_session("user", f"m{i}")
        d = memory.load_session()
        assert len(d["messages"]) == 50  # 上限 50 条
        assert d["messages"][-1]["content"] == "m59"

    def test_concurrent_appends_no_loss(self, store):
        """加锁后并发追加零丢失；这是本次竞态修复的回归锚点。

        总条数必须 < 50（session 上限裁剪），否则裁剪本身会干扰断言。
        """
        N_THREADS, N_MSG = 16, 3

        def worker(tid):
            for i in range(N_MSG):
                memory.append_session("user", f"t{tid:02d}-{i}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        d = memory.load_session()
        assert len(d["messages"]) == N_THREADS * N_MSG
        # 内容完整性：48 条消息一条不少、一条不重
        contents = [m["content"] for m in d["messages"]]
        assert len(set(contents)) == N_THREADS * N_MSG

    def test_session_turns_skips_last(self, store):
        memory.append_session("user", "第一句")
        memory.append_session("assistant", "回复")
        memory.append_session("user", "当前这句")
        turns = memory.session_turns(max_n=20, skip_last=1)
        assert turns[-1]["content"] == "回复"  # 末尾当前消息不重复注入
