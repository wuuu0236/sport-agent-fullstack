"""记忆检索质量回归测试（方案 P1-2）。

这个文件存在的唯一理由：**旧实现的中文召回实测恒为 0 命中**，而这一点在没有
断言的情况下会悄悄退化回去。所以这里的用例不是「函数能跑」，而是钉住三件事：

1. 自然语言问句能召回到语义相关的记忆（旧实现的正则切词做不到——`\\w` 本身就
   匹配 CJK，整句被当成一个 token，再拿整句去条目里找子串，永不命中）；
2. 词与 bigram 双索引都在起作用——jieba 会把「卧推 / 练胸 / 深蹲」切成单字，
   只靠词的话这些高频健身词直接召回为空；
3. 向量侧不可用时（没配 EMBED_API_KEY，这是**默认状态**）纯关键词路径必须正常，
   配了之后融合与近重复合并才生效。
"""
import zlib

import pytest

from src import config, llm, memory
from src.memory import MemoryStore, build_match_query

# 语料 = 真实 USER.md 条目 + 贴近真实使用的新条目
CORPUS = [
    "体态问题：高低肩、翼状肩胛（用户自述；训练与康复动作选择需规避加重）",
    "膝痛史：跑步时膝盖疼，需注意髌股疼痛 / 跑步膝风险，控制下坡与硬地跑量、跑鞋加缓冲",
    "身体基线：静息心率约 55 bpm，最大心率 190 bpm（用于心率区间与训练负荷计算）",
    "我有睡眠障碍",
    "历史训练目标：减脂三分化",
    "历史训练目标：体测1km",
    "当前训练目标：练胸",
    "卧推极限 60kg，深蹲 90kg，硬拉还没测",
    "每周可训练 3 次，每次 60 分钟左右，周末有空",
    "不喜欢跑步机，偏好户外跑",
    "引体向上最多做 6 个，想提升",
    "左肩曾经拉伤过，推举类动作要小心",
]

# 真实用户会问的话（自然语言整句，含大量虚词）
QUERIES = [
    "膝盖疼还能深蹲吗",
    "我的心率区间是多少",
    "怎么练胸",
    "卧推能加多少重量",
    "我该怎么练胸",
    "睡眠不好影响训练吗",
    "肩伤要注意什么",
    "体测1km怎么办",
    "我想提升引体向上",
    "户外跑好还是跑步机好",
]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config.CONFIG, "MEMORY_DB", tmp_path / "memory.db")
    monkeypatch.setattr(config.CONFIG, "USER_FILE", tmp_path / "USER.md")
    monkeypatch.setattr(config.CONFIG, "MEMORY_FILE", tmp_path / "MEMORY.md")
    monkeypatch.setattr(memory, "_initialized", False)
    s = MemoryStore()
    for e in CORPUS:
        s.remember("user", e)
    return s


class TestTokenization:
    def test_natural_language_is_tokenized(self):
        """旧实现这里得到的是整句一个 token —— 这条断言就是那次 bug 的锚点。"""
        expr = build_match_query("膝盖疼还能深蹲吗")
        assert '"膝盖疼还能深蹲吗"' not in expr   # 绝不允许整句当 token
        assert '"膝盖"' in expr                    # jieba 切出的词
        assert '"深蹲"' in expr                    # bigram 兜住的词（jieba 会切成单字）
        assert "{words}" in expr and "{bigrams}" in expr

    def test_short_word_survives_bigram_fallback(self):
        """「卧推」被 jieba 切成 ['卧','推']，过滤单字后只剩 bigram 一条路。"""
        expr = build_match_query("卧推")
        assert '"卧推"' in expr

    def test_empty_query_yields_empty_expr(self):
        assert build_match_query("") == ""
        assert build_match_query("   ") == ""


class TestKeywordRecall:
    def test_old_implementation_would_have_failed_here(self, store):
        """整句自然语言问句必须能召回——这正是旧实现 0/14 的那个场景。"""
        assert store.recall_relevant("膝盖疼还能深蹲吗")
        assert "膝痛史" in store.recall_relevant("膝盖疼还能深蹲吗")[0]

    def test_semantic_target_is_ranked_first(self, store):
        cases = {
            "我的心率区间是多少": "静息心率",
            "睡眠不好影响训练吗": "睡眠障碍",
            "体测1km怎么办": "体测1km",
            "我想提升引体向上": "引体向上",
            "卧推能加多少重量": "卧推极限",
        }
        for query, expected in cases.items():
            hits = store.recall_relevant(query)
            assert hits, f"「{query}」零召回"
            assert expected in hits[0], f"「{query}」首位是 {hits[0]!r}，期望含 {expected!r}"

    def test_recall_rate_on_realistic_corpus(self, store):
        """有召回的问句比例。旧实现（正则重叠打分）在同一语料下实测 0/10。"""
        got = sum(1 for q in QUERIES if store.recall_relevant(q))
        assert got >= 8, f"仅 {got}/{len(QUERIES)} 问句有召回，检索质量退化"

    def test_limit_is_respected(self, store):
        assert len(store.recall_relevant("训练", limit=3)) <= 3

    def test_irrelevant_query_returns_nothing(self, store):
        """完全不相关的问句宁可召回为空——注入无关记忆比不注入更糟。"""
        assert store.recall_relevant("公司年假怎么申请") == []

    def test_word_hit_outranks_bigram_only_hit(self, store):
        """分列权重生效：词级命中应排在只有 bigram 命中的条目之前。"""
        hits = store.recall_relevant("心率")
        assert hits and "静息心率" in hits[0]


class TestVectorDegradation:
    def test_disabled_by_default(self, store):
        """没配 key 是**正常状态**：纯关键词路径必须照常工作，不报错。"""
        assert config.CONFIG.embed_enabled is False
        assert store.recall_relevant("我的心率区间是多少")

    def test_recall_survives_embedding_failure(self, store, monkeypatch):
        """配了 key 但接口挂了，召回必须退回关键词侧而不是抛异常。"""
        monkeypatch.setattr(config.CONFIG, "EMBED_API_KEY", "test-key")
        monkeypatch.setattr(llm, "embed_many", lambda texts: [None] * len(texts))
        assert store.recall_relevant("我的心率区间是多少")


_FAKE_DIMS = 64
_FAKE_KEYS = ("睡眠", "膝盖", "心率", "体测", "引体")


def _fake_embed(text):
    """确定性假向量，模拟真实 embedding 的两个关键性质：

    ① 语义相近的文本向量相近（同一关键词 → 同一维度）；
    ② **无关文本向量正交**（相似度 0）——这一条容易漏：早先的实现让所有未命中
    关键词的文本都落到同一个兜底维度，余弦相似度恒为 1.0，于是「不相似」的用例
    被判成近重复而误报。用 crc32 而非内置 hash：内置 hash 有进程级随机化，
    同一输入在不同次运行会落到不同维度，测试会间歇性飘。
    """
    vec = [0.0] * _FAKE_DIMS
    for i, k in enumerate(_FAKE_KEYS):
        if k in text:
            vec[i] = 1.0
            return vec
    vec[5 + (zlib.crc32(text.encode("utf-8")) % (_FAKE_DIMS - 5))] = 1.0
    return vec


class TestNearDuplicateMerge:
    """方案 P1-2 阶段三：相似度 > SIM_MERGE 时更新而非新增（防重复膨胀）。"""

    def test_merges_similar_entry(self, store, monkeypatch):
        monkeypatch.setattr(config.CONFIG, "EMBED_API_KEY", "test-key")
        monkeypatch.setattr(llm, "embed_many",
                            lambda texts: [_fake_embed(t) for t in texts])
        ok, msg = store.remember("user", "我最近睡眠不太好")
        assert ok and "更新" in msg
        user = store.list_store("user")
        assert "我最近睡眠不太好" in user
        assert "我有睡眠障碍" not in user          # 旧条目被更新掉，没有膨胀
        assert len(user) == len(CORPUS)

    def test_keeps_dissimilar_entries(self, store, monkeypatch):
        monkeypatch.setattr(config.CONFIG, "EMBED_API_KEY", "test-key")
        monkeypatch.setattr(llm, "embed_many",
                            lambda texts: [_fake_embed(t) for t in texts])
        # 这句与语料里任何一条都不相似（假向量落到独热维度），应当正常新增
        store.remember("user", "我最近开始喝蛋白粉了")
        user = store.list_store("user")
        assert "我最近开始喝蛋白粉了" in user
        assert len(user) == len(CORPUS) + 1        # 不同事实，正常新增

    def test_merge_refreshes_search_index(self, store, monkeypatch):
        """合并后索引必须指向新内容，否则旧内容会幽灵命中。"""
        monkeypatch.setattr(config.CONFIG, "EMBED_API_KEY", "test-key")
        monkeypatch.setattr(llm, "embed_many",
                            lambda texts: [_fake_embed(t) for t in texts])
        store.remember("user", "我最近睡眠不太好")
        hits = store.recall_relevant("我最近睡眠不太好")
        assert hits and "我最近睡眠不太好" in hits[0]
