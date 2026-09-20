r"""记忆层：SQLite 唯一真源 + WAL 并发 + jieba/FTS5 混合召回（2026-09-16，方案 P1-2）。

## 为什么从「双 Markdown 文件」迁到 SQLite

旧实现用 `USER.md` / `MEMORY.md` 两个文件，靠一把手写 `threading.Lock` 保护读改写。
三个问题：① 每次新增读写都要记得加锁，漏一次就是并发丢数据；② 检索只能用正则做
字面重叠，**对中文实际近乎恒为 0 命中**（详见下方「召回为什么重写」）；③ 想加向量
召回没有地方放向量。现在唯一真源是 `data/memory.db`，并发交给 SQLite 的 WAL 模式，
写入时同步导出一份 Markdown 只读视图（`USER.md` / `MEMORY.md`）方便人肉查看——
**这两个 .md 不再被读取**，只是产物（写失败不影响主流程）。

## 召回为什么重写（这一段是这次改动最实在的收获）

旧 `recall_relevant()` 用 `re.compile(r"[\w\u4e00-\u9fff]+")` 切词再数字符交集。
实测问题：Python 的 `\w` **本身就匹配 CJK**，所以这个正则在连续中文上根本不切词——
`findall("膝盖疼还能深蹲吗")` 得到的是**一整个字符串**，再拿它去记忆条目里找子串，
自然永不命中。独立复核：5 条中文记忆 × 14 个真实中文问句 = **0/14 命中**；而且生产
路径调用点传进来的是合成 prompt（`用户需求：…\n\n待评审内容：…`），连「整句子串」
这条退路也用不上。也就是说 `if mem_hits:` 恒假，「按需召回 Top5」**实际是空注入**。

重写方案（三件事，都有实测依据）：

1. **jieba 分词**（引入依赖，替代那个正则）；
2. **词 + bigram 双索引列**——只靠 jieba 词也是不够的：`卧推`/`练胸`/`深蹲` 会被
   jieba 切成单字（`['卧','推']`），过滤掉单字后查询直接变空；文档侧补上全文字符
   bigram 后这些词才命中。实测有召回问句数 **7/12 → 11/12**；
3. **FTS5 两列 + 分列权重**（`bm25(entries_fts, 2.0, 0.5)`）——词级命中权重是 bigram
   的两倍，因为 bigram 会命中「注意」「什么」这类泛词，权重不分层噪声会盖过信号。

顺带修掉一个真 bug：SQLite 的 FTS5 **默认分词器 `unicode61` 对中文是全 0 命中**
（整句一个 token），而 `trigram` 分词器**只支持 ≥3 字符**、中文最高频的 2 字词
（膝盖/心率/卧推/增肌）全部失效。所以中文 FTS5 必须自己喂切好的 token，不能指望
内置分词器——这也是为什么索引列存的是空格分隔的 token 串而不是原文。

## 向量侧（可选增强，不配 key 就是正常状态）

DeepSeek 不提供 embedding 接口，所以向量召回默认**不启用**，`EMBED_API_KEY` 留空即
纯 FTS5 召回。配了 key 才会在写入时算向量、召回时把「关键词得分 + 余弦相似度」
加权融合，并按 `SIM_MERGE`（0.9）把高度相似的条目**更新**而非新增（防止重复膨胀）。
**局限要说清**：`膝盖` 与 `膝关节` 这类同义词/近义词的字面不重合，FTS5 **永远解决
不了**（实测两者互相 0 命中），只有向量侧能救——所以“配了 key 才有语义召回”不是
敷衍，是这条链路真实的能力边界。
"""
import json
import math
import re
import sqlite3
import struct
import threading
import time
from contextlib import contextmanager

from . import config, llm

# 仅用于 Markdown 只读视图导出（保持旧 § 格式，便于人读与回退）
_DELIM = "\n§\n"

# 字符上限（mock 演示放宽；生产可收紧到 Hermes 的 2200/1375）
USER_LIMIT = 2000
MEM_LIMIT = 3000

_TARGETS = ("user", "memory")

# FTS5 分列权重：words 权重 2.0 / bigrams 0.5（见模块 docstring 第 3 点）
_BM25_WEIGHTS = (2.0, 0.5)
# 融合权重（仅向量侧可用时生效）
_W_KEYWORD = 0.5
_W_VECTOR = 0.5
# 写入去重：余弦相似度高于此值视为同一事实的更新，不再新增条目
SIM_MERGE = 0.9
# 候选池倍数：先取 limit 的若干倍再做融合排序，避免关键词侧把向量侧的好结果挤掉
_CANDIDATE_FACTOR = 4

# ------------------------------------------------------------------ 中文分词
_jieba = None
_jieba_lock = threading.Lock()

# 只在这些词上过滤：真正无信息量的疑问词/虚词。
# 故意**收得很紧**——「训练」「跑量」「心率」这类实词绝不能进停用表，
# 否则会把最该命中的词过滤掉（这是检索里最容易自伤的一步）。
_STOPWORDS = frozenset({
    "的", "了", "我", "你", "他", "她", "它", "这", "那", "吗", "呢", "啊", "吧",
    "是", "在", "和", "与", "就", "都", "也", "还", "有", "要", "会", "能", "可以",
    "什么", "怎么", "多少", "如何", "请问", "帮我", "一下", "一个", "时候", "应该",
})
_WORDISH = re.compile(r"[\w\u4e00-\u9fff]")


def _jieba_mod():
    """延迟加载 jieba：首次 import 要读词典（实测约 0.5s），只读快照的调用点
    （demo / health / 前端列表）不该为它付这个代价。"""
    global _jieba
    if _jieba is None:
        with _jieba_lock:
            if _jieba is None:
                import jieba
                jieba.setLogLevel(60)      # 关掉 "Building prefix dict..." 日志
                _jieba = jieba
    return _jieba


def _words(text: str) -> list:
    """jieba 分词 + 去噪：丢单字、停用词、纯标点。"""
    out = []
    for t in _jieba_mod().cut(text or ""):
        t = t.strip().lower()
        if len(t) < 2 or t in _STOPWORDS or not _WORDISH.search(t):
            continue
        out.append(t)
    return out


def _bigrams(text: str) -> list:
    """全文字符 bigram（丢空白/标点后相邻两字）。

    存在的理由：jieba 会把「卧推」「练胸」「深蹲」这类词切成单字，而单字被
    `_words` 过滤掉后查询会变成空串——bigram 是这类词的兜底索引。实测把有召回
    问句数从 7/12 提到 11/12。
    """
    s = "".join(ch for ch in (text or "").lower() if _WORDISH.match(ch))
    return [s[i:i + 2] for i in range(len(s) - 1)] if len(s) >= 2 else []


def _dedup(seq) -> list:
    return list(dict.fromkeys(seq))


def _fts_expr(terms, column: str) -> str:
    return f"{{{column}}} : (" + " OR ".join(f'"{t}"' for t in terms) + ")"


def build_match_query(text: str) -> str:
    """把自然语言拼成 FTS5 查询串：词走 words 列、bigram 走 bigrams 列，中间 OR。

    OR 而不是 AND 是刻意的：AND 要求查询里的**每个** token 都出现，用户问
    「我的心率区间是多少」时「区间/是多少」常常不在记忆里，AND 会直接掐死召回
    （实测同样的语料，AND 只有 2/12，OR 有 11/12）。精度交给 bm25 排序与分词权重。
    """
    parts = []
    words = _dedup(_words(text))
    if words:
        parts.append(_fts_expr(words, "words"))
    bgs = _dedup(_bigrams(text))
    if bgs:
        parts.append(_fts_expr(bgs, "bigrams"))
    return " OR ".join(parts)


# ------------------------------------------------------------------ SQLite
_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries(
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  target      TEXT    NOT NULL,
  content     TEXT    NOT NULL,
  created_at  TEXT    NOT NULL,
  updated_at  TEXT    NOT NULL,
  embedding   BLOB,
  embed_model TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_entries_target_content ON entries(target, content);
CREATE INDEX IF NOT EXISTS ix_entries_target ON entries(target, id);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
  words, bigrams, eid UNINDEXED, tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS session_messages(
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  role       TEXT NOT NULL,
  content    TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""

SESSION_LIMIT = 50       # 短期会话仅保留最近 N 条（与旧实现一致）
_BACKFILL_LIMIT = 50     # 补齐历史条目向量的上限（一次批量请求的最大条数）

_init_lock = threading.Lock()
_initialized = False


@contextmanager
def _db():
    """开一个连接并保证关闭。

    每次操作开新连接：sqlite3 的连接对象不能跨线程共享（FastAPI 同步端点跑在线程池
    里），连接级缓存反而是负担。并发安全由 WAL + busy_timeout 保证——这正是把
    手写 `threading.Lock` 拿掉的依据。
    """
    path = config.CONFIG.MEMORY_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        # busy_timeout 必须最先设：它是**后续所有语句**（含下面那条 journal_mode）
        # 的锁等待上限。反过来先设 journal_mode 的话，多线程首次并发建库时那一句
        # 没有等待余量，会直接抛 "database is locked"。
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _ensure_schema() -> None:
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        with _db() as conn:
            conn.executescript(_SCHEMA)
            _migrate_markdown(conn)
        _initialized = True


def _read_md(path) -> list:
    """读旧 Markdown 存储（§ 分隔）。仅在一次性迁移时使用。"""
    try:
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return []
    return [e.strip() for e in raw.split(_DELIM) if e.strip()]


def _migrate_markdown(conn) -> None:
    """把旧 USER.md / MEMORY.md 一次性导入 SQLite。

    只在「entries 表为空 且 从未迁移过」时执行，靠 meta 标记保证幂等——否则用户
    删空记忆后重启服务，旧文件内容会被重新灌回来。
    """
    row = conn.execute("SELECT v FROM meta WHERE k='md_migrated'").fetchone()
    if not row:
        count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        imported = 0
        if count == 0:
            for target, path in (("user", config.CONFIG.USER_FILE),
                                 ("memory", config.CONFIG.MEMORY_FILE)):
                for content in _read_md(path):
                    if _insert_entry(conn, target, content):
                        imported += 1
        conn.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('md_migrated', ?)",
                     (f"{_now()} imported={imported}",))
    _migrate_session(conn)


def _migrate_session(conn) -> None:
    """把旧 session.json 的对话历史一次性导入 SQLite。

    不做的话重启后「最近对话」直接变空——对用户是可见的回归（那份文件里是真实
    对话记录）。同样靠 meta 标记保证只做一次，且只取最近 SESSION_LIMIT 条，
    与旧实现每次 append 时裁剪的行为对齐。
    """
    if conn.execute("SELECT v FROM meta WHERE k='session_migrated'").fetchone():
        return
    imported = 0
    try:
        path = config.CONFIG.SESSION_FILE
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            msgs = (data or {}).get("messages", [])[-SESSION_LIMIT:]
            for m in msgs:
                role, content = m.get("role"), (m.get("content") or "")
                if role in ("user", "assistant") and content:
                    conn.execute(
                        "INSERT INTO session_messages(role, content, created_at) VALUES(?,?,?)",
                        (role, content, _now()))
                    imported += 1
    except Exception:  # noqa: BLE001
        imported = 0            # 文件损坏不该阻塞建库
    conn.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('session_migrated', ?)",
                 (f"{_now()} imported={imported}",))


def _index_entry(conn, eid: int, content: str) -> None:
    """写入 FTS5 索引。索引列存**切好的 token**（不是原文）——中文的内置分词器
    用不了，详见模块 docstring。"""
    conn.execute("DELETE FROM entries_fts WHERE eid=?", (eid,))
    conn.execute(
        "INSERT INTO entries_fts(words, bigrams, eid) VALUES(?,?,?)",
        (" ".join(_dedup(_words(content))), " ".join(_dedup(_bigrams(content))), eid),
    )


def _unindex_entry(conn, eid: int) -> None:
    conn.execute("DELETE FROM entries_fts WHERE eid=?", (eid,))


def _insert_entry(conn, target: str, content: str, embedding=None) -> bool:
    ts = _now()
    try:
        cur = conn.execute(
            "INSERT INTO entries(target, content, created_at, updated_at, embedding, embed_model)"
            " VALUES(?,?,?,?,?,?)",
            (target, content, ts, ts,
             _pack(embedding) if embedding else None,
             config.CONFIG.EMBED_MODEL if embedding else None),
        )
    except sqlite3.IntegrityError:      # 唯一索引拦下的重复内容
        return False
    _index_entry(conn, cur.lastrowid, content)
    return True


def _pack(vec) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob):
    if not blob:
        return None
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def _cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


# ------------------------------------------------------------------ 只读视图导出
def _export_markdown(conn) -> None:
    """把 SQLite 内容同步成 Markdown 只读视图（**不参与读取**，仅供人看）。

    失败静默：这是产物不是真源，导不出来不该让一次记忆写入失败。
    """
    for target, path in (("user", config.CONFIG.USER_FILE),
                         ("memory", config.CONFIG.MEMORY_FILE)):
        try:
            rows = conn.execute(
                "SELECT content FROM entries WHERE target=? ORDER BY id", (target,)
            ).fetchall()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_DELIM.join(r[0] for r in rows), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ 存储主体
class MemoryStore:
    """双存储记忆：user（关于用户）+ memory（助理笔记），SQLite 持久化。"""

    def __init__(self, user_limit: int = USER_LIMIT, mem_limit: int = MEM_LIMIT):
        self.user_limit = user_limit
        self.mem_limit = mem_limit
        self.user_entries: list = []
        self.mem_entries: list = []
        self._snapshot = {"user": "", "memory": ""}
        self.load()

    # ----- 读取 -----
    def load(self) -> "MemoryStore":
        """重新读库并刷新冻结快照。"""
        _ensure_schema()
        with _db() as conn:
            rows = conn.execute(
                "SELECT target, content FROM entries ORDER BY id").fetchall()
        self.user_entries = [r["content"] for r in rows if r["target"] == "user"]
        self.mem_entries = [r["content"] for r in rows if r["target"] == "memory"]
        self._snapshot = {
            "user": self._render("user", self.user_entries),
            "memory": self._render("memory", self.mem_entries),
        }
        return self

    def _entries(self, target: str) -> list:
        return self.user_entries if target == "user" else self.mem_entries

    def _limit(self, target: str) -> int:
        return self.user_limit if target == "user" else self.mem_limit

    @staticmethod
    def _render(target: str, entries: list) -> str:
        if not entries:
            return ""
        header = "USER PROFILE（关于用户）" if target == "user" else "MEMORY（助理笔记）"
        return f"{header} [{len(entries)} 条]\n{_DELIM.join(entries)}"

    def snapshot_block(self) -> str:
        """冻结快照块：供 LLM 模式注入 system prompt（跨会话常驻）。"""
        parts = [v for v in (self._snapshot["user"], self._snapshot["memory"]) if v]
        return "\n\n".join(parts) if parts else ""

    def list_store(self, target: str = None):
        if target:
            return list(self._entries(target))
        return {"user": list(self.user_entries), "memory": list(self.mem_entries)}

    # ----- 写入 / 删除 -----
    def remember(self, target: str, content: str):
        """写入一条记忆。返回 (ok, msg)。

        去重分两级：① 完全相同 → 直接跳过；② 配了 embedding 且与已有条目余弦
        相似度 > `SIM_MERGE` → 视为同一事实的**更新**，改已有条目而不是新增
        （方案 P1-2 阶段三「防重复膨胀」）。
        """
        content = (content or "").strip()
        if not content:
            return False, "内容为空"
        if target not in _TARGETS:
            return False, "target 必须是 'user' 或 'memory'"
        _ensure_schema()
        merged = False
        with _db() as conn:
            rows = _select_rows(conn, target)
            if any(r["content"] == content for r in rows):
                return True, "已存在，跳过重复"
            existed = [r["content"] for r in rows]
            total = len(_DELIM.join(existed + [content]))
            if total > self._limit(target):
                return False, (
                    f"超出 {target} 存储上限（{self._limit(target)} 字符），"
                    f"请先合并/删除旧条目再记"
                )
            vector = llm.embed_one(content) if config.CONFIG.embed_enabled else None
            if vector:
                # 先补齐历史条目的向量，否则「近重复合并」对它们永远不生效
                if _backfill_embeddings(conn, target):
                    rows = _select_rows(conn, target)
                near = _nearest(rows, vector)
                if near is not None:
                    conn.execute(
                        "UPDATE entries SET content=?, updated_at=?, embedding=?, embed_model=?"
                        " WHERE id=?",
                        (content, _now(), _pack(vector), config.CONFIG.EMBED_MODEL, near["id"]))
                    _index_entry(conn, near["id"], content)
                    merged = True
            if not merged:
                _insert_entry(conn, target, content, vector)
            _export_markdown(conn)
        # load() 必须在 with 之外：_db() 是退出时才 commit，而 load() 会另开一条连接——
        # 在提交前读，读到的是旧数据（这个坑踩过一次：内容写进去了，快照还是旧的）。
        self.load()
        return True, ("与已有条目高度相似，已更新而非新增" if merged else "ok")

    def replace_all(self, target: str, entries: list):
        """整套替换某个存储的条目（保持给定顺序）。返回 (ok, msg)。

        给「当前/历史训练目标」这种需要重排的调用点用（`app._record_goal`）——
        旧实现是绕过 memory 模块直接读改写 USER.md，迁到 SQLite 后那条路没了。
        """
        items = _dedup([(e or "").strip() for e in (entries or []) if (e or "").strip()])
        if len(_DELIM.join(items)) > self._limit(target):
            return False, f"超出 {target} 存储上限（{self._limit(target)} 字符）"
        _ensure_schema()
        with _db() as conn:
            old = conn.execute("SELECT id FROM entries WHERE target=?", (target,)).fetchall()
            for r in old:
                _unindex_entry(conn, r["id"])
            conn.execute("DELETE FROM entries WHERE target=?", (target,))
            for content in items:
                _insert_entry(conn, target, content)
            _export_markdown(conn)
        self.load()
        return True, "ok"

    def forget(self, target: str, old_text: str):
        """按子串删除一条记忆。返回 (ok, msg)。

        ⚠️ 子串匹配 + 只删第一条命中是**对话侧「忘掉…」的既有语义**；HTTP 删除
        入口（画像面板）应走 `forget_by_id`——两条条目存在包含关系时子串会删错。
        """
        old_text = (old_text or "").strip()
        if not old_text:
            return False, "old_text 为空"
        _ensure_schema()
        with _db() as conn:
            row = conn.execute(
                "SELECT id FROM entries WHERE target=? AND content LIKE ? ORDER BY id LIMIT 1",
                (target, f"%{old_text}%")).fetchone()
            if not row:
                return False, "未找到匹配条目"
            _unindex_entry(conn, row["id"])
            conn.execute("DELETE FROM entries WHERE id=?", (row["id"],))
            _export_markdown(conn)
        self.load()
        return True, "ok"

    def forget_by_id(self, entry_id):
        """按稳定主键精确删除一条记忆。返回 (ok, msg)。

        画像面板的删除走这里：`/memory` 列表现在返回每条的 id，前端删谁传谁的
        主键——即使两条条目内容有包含关系（「历史训练目标：练胸」vs「当前训练
        目标：练胸」），也不会像子串匹配那样删错第一条。删除动作与 `forget`
        完全一致（清 FTS 索引 → 删行 → 同步 Markdown 视图），不另开写库路径。
        """
        try:
            entry_id = int(entry_id)
        except (TypeError, ValueError):
            return False, "id 必须是整数"
        _ensure_schema()
        with _db() as conn:
            row = conn.execute(
                "SELECT id FROM entries WHERE id=?", (entry_id,)).fetchone()
            if not row:
                return False, "条目不存在或已删除"
            _unindex_entry(conn, row["id"])
            conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))
            _export_markdown(conn)
        self.load()
        return True, "ok"

    def list_with_ids(self, target: str) -> list:
        """返回某存储的条目列表，**每条带稳定主键**：[{"id": int, "text": str}, …]。

        供 /memory 端点与画像面板的按 id 删除使用。`list_store` 返回纯字符串列表
        的旧契约保持不变（对话侧多个消费点依赖它）。
        """
        if target not in _TARGETS:
            return []
        _ensure_schema()
        with _db() as conn:
            rows = conn.execute(
                "SELECT id, content FROM entries WHERE target=? ORDER BY id", (target,)
            ).fetchall()
        return [{"id": r["id"], "text": r["content"]} for r in rows]

    # ----- 召回（词 + bigram 关键词得分，配了 embedding 再融合向量）-----
    def recall_relevant(self, query: str, limit: int = 5) -> list:
        """返回与 query 最相关的若干条记忆（跨两个存储一起排）。

        关键词侧用 FTS5 + bm25；向量侧可用时按 `_W_KEYWORD/_W_VECTOR` 加权融合。
        两侧都拿不到结果就返回空表——调用方（`agents/base.py`）据此**不注入**
        `<memory-context>`，这是正确行为：注入一堆无关记忆比不注入更糟。
        """
        expr = build_match_query(query)
        if not expr:
            return []
        _ensure_schema()
        pool = max(limit * _CANDIDATE_FACTOR, limit)
        with _db() as conn:
            rows = conn.execute(
                "SELECT e.id, e.content, e.embedding, bm25(entries_fts, ?, ?) AS score"
                " FROM entries_fts JOIN entries e ON e.id = entries_fts.eid"
                " WHERE entries_fts MATCH ? ORDER BY score LIMIT ?",
                (*_BM25_WEIGHTS, expr, pool),
            ).fetchall()
        if not rows:
            return []

        # bm25 返回负值、越小越相关 → 取相反数后按最大值归一化到 1 以内
        raw = [-r["score"] for r in rows]
        top = max(raw) or 1.0
        scored = [(raw[i] / top, rows[i]["content"], _unpack(rows[i]["embedding"]))
                  for i in range(len(rows))]

        vector = llm.embed_one(query) if config.CONFIG.embed_enabled else None
        if vector:
            scored = [(_W_KEYWORD * kw + _W_VECTOR * _cosine(vector, emb), text, emb)
                      for kw, text, emb in scored]
        scored.sort(key=lambda x: -x[0])
        return [text for _, text, _ in scored[:limit]]


def _nearest(rows, vector):
    """返回与 vector 余弦相似度最高且 > SIM_MERGE 的那一行；没有则 None。"""
    best, best_sim = None, SIM_MERGE
    for r in rows:
        sim = _cosine(vector, _unpack(r["embedding"]))
        if sim > best_sim:
            best, best_sim = r, sim
    return best


def _select_rows(conn, target: str):
    return conn.execute(
        "SELECT id, content, embedding FROM entries WHERE target=? ORDER BY id",
        (target,)).fetchall()


def _backfill_embeddings(conn, target: str) -> bool:
    """给该存储里还没有向量的条目补算（有界批处理）。返回是否有更新。

    为什么必须有这一步：`EMBED_API_KEY` 是**后配**的——之前写入的条目 embedding 为
    NULL，不补齐的话「近重复合并」对这些历史条目永远不生效，整个阶段三形同虚设。
    用批量接口一次请求算完，并用 `_BACKFILL_LIMIT` 封顶，避免首次开启时打太多请求。
    """
    rows = _select_rows(conn, target)
    missing = [r for r in rows if not r["embedding"]][:_BACKFILL_LIMIT]
    if not missing:
        return False
    vectors = llm.embed_many([r["content"] for r in missing])
    changed = False
    for r, v in zip(missing, vectors):
        if v:
            conn.execute("UPDATE entries SET embedding=?, embed_model=? WHERE id=?",
                         (_pack(v), config.CONFIG.EMBED_MODEL, r["id"]))
            changed = True
    return changed


# ---------------------------------------------------------------------------
# 模块级单例 + 便捷函数（供 agent / server 调用，并兼容旧接口）
# ---------------------------------------------------------------------------
_store = MemoryStore()


def baseline_max_hr() -> int:
    """从 USER 记忆里取最大心率基线；没有就用 220-年龄；再没有退回 190。

    原先 coach / analyst 各自直接 `USER_FILE.read_text()` 再正则抓——两处重复实现，
    且迁到 SQLite 后那个文件已不是真源。收敛到这里，读的是记忆库本身。
    """
    text = "\n".join(_store.list_store("user") or [])
    m = re.search(r"最大心率[：:\s]*(\d+)", text) or re.search(r"最大心率约\s*(\d+)", text)
    if m:
        return int(m.group(1))
    m = re.search(r"年龄[：:\s]*(\d+)", text)
    if m:
        return 220 - int(m.group(1))
    return 190


def remember(target: str, content: str):
    return _store.remember(target, content)


def forget(target: str, old_text: str):
    return _store.forget(target, old_text)


def forget_by_id(entry_id):
    return _store.forget_by_id(entry_id)


def list_with_ids(target: str):
    return _store.list_with_ids(target)


def replace_all(target: str, entries: list):
    return _store.replace_all(target, entries)


def list_store(target: str = None):
    return _store.list_store(target)


def snapshot_block() -> str:
    return _store.snapshot_block()


def recall_relevant(query: str, limit: int = 5) -> list:
    return _store.recall_relevant(query, limit)


def load() -> MemoryStore:
    return _store.load()


# ----- 兼容旧接口（memory_agent / demo 仍可能用到）-----
def add_fact(text: str):
    _store.remember("user", text)
    return {"facts": list(_store.user_entries), "preferences": list(_store.mem_entries)}


def list_facts() -> list:
    return list(_store.user_entries)


def load_long_term() -> dict:
    return {"facts": list(_store.user_entries), "preferences": list(_store.mem_entries)}


def save_long_term(data) -> None:  # 旧调用点占位，新实现无需落盘此结构
    pass


# ----- 短期会话（同样进 SQLite，不再用 session.json + 手写锁）-----
def load_session() -> dict:
    _ensure_schema()
    with _db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM session_messages ORDER BY id").fetchall()
    return {"messages": [{"role": r["role"], "content": r["content"]} for r in rows]}


def append_session(role: str, content: str) -> None:
    _ensure_schema()
    with _db() as conn:
        conn.execute(
            "INSERT INTO session_messages(role, content, created_at) VALUES(?,?,?)",
            (role, content, _now()))
        # 裁剪到最近 SESSION_LIMIT 条（旧实现在每次 append 时截断，语义保持一致）
        conn.execute(
            "DELETE FROM session_messages WHERE id NOT IN"
            " (SELECT id FROM session_messages ORDER BY id DESC LIMIT ?)", (SESSION_LIMIT,))


def session_turns(max_n: int = 20, skip_last: int = 1) -> list:
    """最近对话轮次，供 LLM 上下文注入（multi-turn 记忆）。

    默认丢弃末尾 skip_last 条：server 已把当前这条用户消息 append 进 session，
    避免在 messages 里和单独传入的 user_msg 重复。返回 [{role, content}]。
    """
    msgs = load_session().get("messages", [])
    if skip_last:
        msgs = msgs[:-skip_last]
    out = []
    for m in msgs[-max_n:]:
        role, content = m.get("role"), (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


def reset_long_term() -> None:
    """重置**全部记忆**（演示/测试用）：长期记忆 + 会话历史 + 向量一并清掉。

    为什么连会话一起清（2026-09-16 复查修正）：本函数是 `demo.py` 的「开演前重置」
    入口，语义就是**重置演示数据**，而 docstring 一直写着「会话与向量一并清掉」，
    实现却只删了 `entries` / `entries_fts`——会话表残留，上一轮演示的对话会被当成
    历史上下文带进下一轮，演示不可重复。**注释与行为不一致本身就是坑**：读代码的人
    会以为会话已经清了。

    影响范围（调用前请确认你要的就是这些）：
    · `entries` / `entries_fts`：user + memory 长期记忆（含向量列），
      `USER.md` / `MEMORY.md` 只读视图同步清空；
    · `session_messages`：会话历史；
    · **不动** `meta`（迁移标记必须保留，否则删空记忆后重启，旧 Markdown 会被重新灌回来）；
    · **不在范围内**：训练记录（`data/sessions/*.json`）、暂存队列（`data/staged.db`）。
    """
    _ensure_schema()
    with _db() as conn:
        conn.execute("DELETE FROM entries")
        conn.execute("DELETE FROM entries_fts")
        conn.execute("DELETE FROM session_messages")
        _export_markdown(conn)
    _store.load()


# ---------------------------------------------------------------------------
# （历史遗留）watchlist 原用于求职时机 Agent 追踪行业，本体育训练项目未使用，
# 保留 watchlist 解析函数仅为兼容旧接口；新代码请勿依赖。
# ---------------------------------------------------------------------------
WATCHLIST_FILE = config.CONFIG.MEMORY_DIR / "watchlist.json"
DEFAULT_WATCHLIST = ["AI Agent", "大模型应用", "量化"]


def _save_watchlist(wl: list) -> None:
    p = WATCHLIST_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(wl, ensure_ascii=False, indent=2), encoding="utf-8")


def get_watchlist() -> list:
    p = WATCHLIST_FILE
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
            pass
