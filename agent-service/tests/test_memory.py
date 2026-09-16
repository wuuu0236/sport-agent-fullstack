"""memory 模块回归测试：双存储读写 / 上限 / 并发追加 / Markdown 迁移。

并发用例是 2026-09 加锁修复的直接证据：16 线程 × 3 次 append，修复前
read-modify-write 竞态会丢消息。2026-09-16 起存储迁到 SQLite（WAL），
这条用例改成**验证 WAL 真的顶住了并发**，性质从「锁有没有加」变成「换引擎后没退化」。
"""
import threading

import pytest

from src import config, memory
from src.memory import MemoryStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config.CONFIG, "MEMORY_DB", tmp_path / "memory.db")
    monkeypatch.setattr(config.CONFIG, "USER_FILE", tmp_path / "USER.md")
    monkeypatch.setattr(config.CONFIG, "MEMORY_FILE", tmp_path / "MEMORY.md")
    monkeypatch.setattr(config.CONFIG, "SESSION_FILE", tmp_path / "session.json")
    # 建表是一次性动作（模块级 _initialized 记住），不重置的话新 tmp 库拿不到 schema
    monkeypatch.setattr(memory, "_initialized", False)
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
        """SQLite WAL 顶住并发追加，零丢失；换引擎后的回归锚点。

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


class TestSqliteMigration:
    """从旧 Markdown 双文件迁到 SQLite 的一次性迁移（方案 P1-2）。"""

    def test_imports_legacy_markdown(self, store, tmp_path):
        # store 夹具已建库；模拟「老库为空 + 磁盘上有旧 Markdown + 迁移标记未写」
        (tmp_path / "USER.md").write_text("膝盖不好\n§\n静息心率55", encoding="utf-8")
        (tmp_path / "MEMORY.md").write_text("用户偏好早上训练", encoding="utf-8")
        with memory._db() as conn:                     # 清标记，模拟首次升级
            conn.execute("DELETE FROM meta WHERE k='md_migrated'")
            memory._migrate_markdown(conn)
        again = MemoryStore()
        assert "膝盖不好" in again.list_store("user")
        assert "静息心率55" in again.list_store("user")
        assert "用户偏好早上训练" in again.list_store("memory")

    def test_migration_is_idempotent(self, store, tmp_path):
        """迁移只做一次：用户删空记忆后重启，旧的 Markdown 不该被灌回来。"""
        (tmp_path / "USER.md").write_text("会被导入一次", encoding="utf-8")
        with memory._db() as conn:
            conn.execute("DELETE FROM meta WHERE k='md_migrated'")
            memory._migrate_markdown(conn)
        assert "会被导入一次" in MemoryStore().list_store("user")
        memory.reset_long_term()
        assert MemoryStore().list_store("user") == []   # 没被二次导入

    def test_markdown_view_is_written_but_not_read(self, store, tmp_path):
        """Markdown 退化为只读视图：写入后同步，但读取一律以 SQLite 为准。"""
        store.remember("user", "从 SQLite 来的一条")
        assert "从 SQLite 来的一条" in (tmp_path / "USER.md").read_text(encoding="utf-8")
        # 手动改视图文件，不应影响读取结果（证明它不参与读取）
        (tmp_path / "USER.md").write_text("篡改的视图内容", encoding="utf-8")
        assert MemoryStore().list_store("user") == ["从 SQLite 来的一条"]

    def test_imports_legacy_session(self, store, tmp_path):
        """旧 session.json 的对话历史要迁进来——否则重启后「最近对话」变空。"""
        import json
        (tmp_path / "session.json").write_text(json.dumps({
            "messages": [{"role": "user", "content": "旧问题"},
                         {"role": "assistant", "content": "旧回答"}],
        }, ensure_ascii=False), encoding="utf-8")
        with memory._db() as conn:
            conn.execute("DELETE FROM meta WHERE k='session_migrated'")
            memory._migrate_session(conn)
        assert [m["content"] for m in memory.load_session()["messages"]] == ["旧问题", "旧回答"]

    def test_session_migration_is_idempotent(self, store, tmp_path):
        import json
        (tmp_path / "session.json").write_text(json.dumps(
            {"messages": [{"role": "user", "content": "只该出现一次"}]},
            ensure_ascii=False), encoding="utf-8")
        with memory._db() as conn:
            conn.execute("DELETE FROM meta WHERE k='session_migrated'")
            memory._migrate_session(conn)
            memory._migrate_session(conn)      # 第二次应被 meta 标记挡住
        contents = [m["content"] for m in memory.load_session()["messages"]]
        assert contents.count("只该出现一次") == 1


class TestReplaceAll:
    def test_replaces_and_reorders(self, store):
        store.remember("user", "当前训练目标：减脂")
        store.remember("user", "不动的一条")
        ok, _ = store.replace_all("user", ["不动的一条", "当前训练目标：练胸"])
        assert ok
        assert store.list_store("user") == ["不动的一条", "当前训练目标：练胸"]

    def test_replace_is_searchable_afterwards(self, store):
        """整套替换后 FTS 索引必须重建——否则新内容搜不到、旧内容幽灵命中。"""
        store.remember("user", "当前训练目标：减脂")
        store.replace_all("user", ["当前训练目标：练胸"])
        assert store.recall_relevant("练胸") == ["当前训练目标：练胸"]
        assert store.recall_relevant("减脂") == []
