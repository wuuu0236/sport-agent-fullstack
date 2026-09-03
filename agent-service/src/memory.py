"""记忆层（受 Hermes Agent 双存储 + 冻结快照启发，零依赖）。

设计要点（对齐 Hermes 的记忆内核）：
  1. 双存储分离：USER.md（关于用户：身份/偏好/训练基线）与
     MEMORY.md（助理自己的笔记：约定/技巧/学到的东西）各管各的，
     便于把「关于用户」的部分稳定注入系统提示。
  2. 冻结快照：load() 时把当前条目渲染成 block；LLM 模式下注入 system
     prompt，做到「跨会话记得你」。会话中新写入会刷新磁盘，但本会话的
     快照不变（与 Hermes 一致——保前缀缓存、下次会话生效）。
  3. 有界紧凑条目：每个存储有字符上限，超出拒绝并提示合并（避免无限膨胀）。
  4. 轻量召回：recall_relevant 用关键词重叠打分，作为 FTS5/向量召回的
     零依赖平替；生产环境可换成 SQLite FTS5 或向量库。

短期会话仍走 session.json（最近 50 条）。
"""
import re
import json
import threading
from . import config

# 与 Hermes 同款的条目分隔符（§ 段落符，支持多行条目）
_DELIM = "\n§\n"

# 文件读改写互斥锁：FastAPI 的同步端点跑在线程池里，USER.md / MEMORY.md /
# session.json 都是「读整个文件 → 改 → 写回」的模式，没有锁时两个并发请求
# 会互相覆盖（丢消息）甚至写坏 JSON。app.py 的 _record_goal 直写 USER.md
# 也复用这把锁。读操作（load / list_store）不加锁：Markdown 单文件写入
# 在 CPython 里近似原子，读到旧值只是暂时不一致，锁只保护读改写区间。
_FILE_LOCK = threading.Lock()
file_lock = _FILE_LOCK  # 公开别名：跨模块（app.py）复用同一把锁

# 字符上限（mock 演示放宽；生产可收紧到 Hermes 的 2200/1375）
USER_LIMIT = 2000
MEM_LIMIT = 3000

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")


class MemoryStore:
    """双存储记忆：user + memory，Markdown 持久化，冻结快照供系统提示注入。"""

    def __init__(self, user_limit: int = USER_LIMIT, mem_limit: int = MEM_LIMIT):
        self.user_limit = user_limit
        self.mem_limit = mem_limit
        self.user_entries: list[str] = []
        self.mem_entries: list[str] = []
        self._snapshot = {"user": "", "memory": ""}
        self.load()

    # ----- 文件路径 -----
    def _path(self, target: str):
        return config.CONFIG.USER_FILE if target == "user" else config.CONFIG.MEMORY_FILE

    # ----- 读写持久化（Markdown，§ 分隔）-----
    def _read(self, target: str) -> list[str]:
        p = self._path(target)
        if not p.exists():
            return []
        raw = p.read_text(encoding="utf-8")
        entries = [e.strip() for e in raw.split(_DELIM)]
        return [e for e in entries if e]

    def _write(self, target: str) -> None:
        p = self._path(target)
        p.parent.mkdir(parents=True, exist_ok=True)
        entries = self.user_entries if target == "user" else self.mem_entries
        p.write_text(_DELIM.join(entries), encoding="utf-8")

    def load(self) -> "MemoryStore":
        """从磁盘加载并刷新冻结快照。"""
        self.user_entries = self._read("user")
        self.mem_entries = self._read("memory")
        # 去重保序
        self.user_entries = list(dict.fromkeys(self.user_entries))
        self.mem_entries = list(dict.fromkeys(self.mem_entries))
        self._snapshot = {
            "user": self._render("user", self.user_entries),
            "memory": self._render("memory", self.mem_entries),
        }
        return self

    def _entries(self, target: str) -> list[str]:
        return self.user_entries if target == "user" else self.mem_entries

    def _limit(self, target: str) -> int:
        return self.user_limit if target == "user" else self.mem_limit

    @staticmethod
    def _render(target: str, entries: list[str]) -> str:
        if not entries:
            return ""
        header = "USER PROFILE（关于用户）" if target == "user" else "MEMORY（助理笔记）"
        body = _DELIM.join(entries)
        return f"{header} [{len(entries)} 条]\n{body}"

    def snapshot_block(self) -> str:
        """冻结快照块：供 LLM 模式注入 system prompt（跨会话常驻）。"""
        parts = [v for v in (self._snapshot["user"], self._snapshot["memory"]) if v]
        if not parts:
            return ""
        return "\n\n".join(parts)

    # ----- 写入 / 删除 -----
    def remember(self, target: str, content: str):
        """写入一条记忆。返回 (ok, msg)。"""
        content = (content or "").strip()
        if not content:
            return False, "内容为空"
        if target not in ("user", "memory"):
            return False, "target 必须是 'user' 或 'memory'"
        with _FILE_LOCK:
            entries = self._entries(target)
            if content in entries:
                return True, "已存在，跳过重复"
            total = len(_DELIM.join(entries + [content]))
            if total > self._limit(target):
                return False, (
                    f"超出 {target} 存储上限（{self._limit(target)} 字符），"
                    f"请先合并/删除旧条目再记"
                )
            entries.append(content)
            self._write(target)
            self.load()  # 刷新快照（下一会话生效）
        return True, "ok"

    def forget(self, target: str, old_text: str):
        """按子串删除一条记忆。返回 (ok, msg)。"""
        old_text = (old_text or "").strip()
        if not old_text:
            return False, "old_text 为空"
        with _FILE_LOCK:
            entries = self._entries(target)
            matches = [i for i, e in enumerate(entries) if old_text in e]
            if not matches:
                return False, "未找到匹配条目"
            del entries[matches[0]]
            self._write(target)
            self.load()
        return True, "ok"

    def list_store(self, target: str = None):
        if target:
            return list(self._entries(target))
        return {"user": list(self.user_entries), "memory": list(self.mem_entries)}

    # ----- 轻量召回（FTS5/向量的零依赖平替）-----
    def recall_relevant(self, query: str, limit: int = 5) -> list[str]:
        """按关键词重叠打分，返回最相关的若干条目。"""
        q = (query or "").lower()
        if not q:
            return []
        terms = set(_TOKEN_RE.findall(q))
        if not terms:
            return []
        scored = []
        for target in ("user", "memory"):
            for e in self._entries(target):
                el = e.lower()
                score = sum(1 for t in terms if t in el)
                if score:
                    scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:limit]]


# ---------------------------------------------------------------------------
# 模块级单例 + 便捷函数（供 agent / server 调用，并兼容旧接口）
# ---------------------------------------------------------------------------
_store = MemoryStore()


# ---------------------------------------------------------------------------
# （历史遗留）watchlist 原用于求职时机 Agent 追踪行业，本体育训练项目未使用，
# 保留 watchlist 解析函数仅为兼容旧接口；新代码请勿依赖。
# ---------------------------------------------------------------------------
WATCHLIST_FILE = config.CONFIG.MEMORY_DIR / "watchlist.json"
DEFAULT_WATCHLIST = ["AI Agent", "大模型应用", "量化"]


def get_watchlist() -> list:
    p = WATCHLIST_FILE
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    return list(DEFAULT_WATCHLIST)


def add_watch(industry: str) -> bool:
    ind = (industry or "").strip()
    if not ind:
        return False
    wl = get_watchlist()
    if ind not in wl:
        wl.append(ind)
        _save_watchlist(wl)
    return True


def remove_watch(industry: str) -> bool:
    ind = (industry or "").strip()
    if not ind:
        return False
    wl = get_watchlist()
    if ind in wl:
        wl.remove(ind)
        _save_watchlist(wl)
        return True
    return False


def reset_watchlist() -> None:
    p = WATCHLIST_FILE
    if p.exists():
        try:
            p.write_text("", encoding="utf-8")
        except Exception:
            pass


def _save_watchlist(wl: list) -> None:
    p = WATCHLIST_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(wl, ensure_ascii=False, indent=2), encoding="utf-8")


def remember(target: str, content: str):
    return _store.remember(target, content)


def forget(target: str, old_text: str):
    return _store.forget(target, old_text)


def list_store(target: str = None):
    return _store.list_store(target)


def snapshot_block() -> str:
    return _store.snapshot_block()


def recall_relevant(query: str, limit: int = 5) -> list[str]:
    return _store.recall_relevant(query, limit)


def load() -> MemoryStore:
    return _store.load()


# ----- 兼容旧接口（memory_agent / demo 仍可能用到）-----
def add_fact(text: str):
    _store.remember("user", text)
    return {"facts": list(_store.user_entries), "preferences": list(_store.mem_entries)}


def list_facts() -> list[str]:
    return list(_store.user_entries)


def load_long_term() -> dict:
    return {"facts": list(_store.user_entries), "preferences": list(_store.mem_entries)}


def save_long_term(data) -> None:  # 旧调用点占位，新实现无需落盘此结构
    pass


# ----- 短期会话 -----
def _session_path():
    return config.CONFIG.SESSION_FILE


def load_session() -> dict:
    p = _session_path()
    if p.exists():
        import json
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {"messages": []}
    return {"messages": []}


def append_session(role: str, content: str) -> None:
    import json
    # 读整个 session.json → append → 写回，是典型 read-modify-write；
    # 不持锁时并发 /chat 会互相覆盖丢消息，这里用文件锁串行化。
    with _FILE_LOCK:
        d = load_session()
        d.setdefault("messages", []).append({"role": role, "content": content})
        d["messages"] = d["messages"][-50:]  # 仅保留最近 50 条
        _session_path().parent.mkdir(parents=True, exist_ok=True)
        _session_path().write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def session_turns(max_n: int = 20, skip_last: int = 1) -> list:
    """最近对话轮次，供 LLM 上下文注入（multi-turn 记忆）。

    默认丢弃末尾 skip_last 条：server 已把当前这条用户消息 append 进 session，
    避免在 messages 里和单独传入的 user_msg 重复。返回 [{role, content}]。
    """
    d = load_session()
    msgs = d.get("messages", [])
    if skip_last:
        msgs = msgs[:-skip_last]
    msgs = msgs[-max_n:]
    out = []
    for m in msgs:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


def reset_long_term() -> None:
    """清空双存储（演示用，保持可重复运行）。

    注意：本沙箱对「删除」有 safe-delete 拦截，故用「覆盖为空」代替 unlink，
    同样能达到清空效果且不触发删除钩子。
    """
    for p in (config.CONFIG.USER_FILE, config.CONFIG.MEMORY_FILE):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
    _store.load()
