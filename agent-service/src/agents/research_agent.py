"""搜索 / 资讯 Agent：联网搜索资料、新闻、最新信息。

真实模式：走 search 的「查询变体 + 多结果并集」（Bing 中文分词不稳，单个查询可能漂移，
见 search.py 说明），把并集交给 LLM 时明确要求「只采用相关来源、忽略无关项、
不足就如实说」；最终仍不可用时如实告知未联网——不再让 LLM 假装自己搜过（旧版硬伤）。
"""
from .base import BaseAgent
from .. import config, search


class SearcherAgent(BaseAgent):
    name = "searcher"
    description = "联网搜索资料、新闻、最新信息"
    system_prompt = (
        "你是用户的搜索与调研助理。会基于【本次提供的联网检索结果】汇总要点、"
        "给出来源线索；检索结果不足或未联网时，如实说明，不编造来源。"
        "回答结构化、好读。"
    )

    def handle(self, user_msg: str, ctx: dict = None) -> str:
        if config.CONFIG.mock_mode:
            return (
                "🔍 搜索 Agent 已收到请求。\n"
                f"· 你想查：{user_msg}\n"
                "（离线演示：未配置 LLM_API_KEY。配置后会自动联网检索——"
                "优先 Tavily，否则免费 Bing / 维基百科兜底。）"
            )
        results = search.search(user_msg)
        if not results:
            # 无法联网或没搜到：诚实降级，不让 LLM 假装搜过
            return self._llm(
                f"用户想查：{user_msg}\n"
                "（当前没有可用的联网检索结果。若无法给出确凿答案，"
                "请如实说明『未能联网检索』，并基于已知信息谨慎作答，不要编造来源。）",
                ctx=ctx)
        snippet = search.format_sources(results)
        return self._llm(
            f"用户想查：{user_msg}\n\n{snippet}\n"
            "注意：检索来自多个查询变体，结果里可能混有少量无关内容（搜索引擎分词漂移所致）。"
            "请只采用与问题相关的来源，忽略明显无关的，并在回答末尾列出实际使用的来源序号；"
            "若相关来源太少，如实说明并基于可用部分作答，不要编造。",
            ctx=ctx)


# 兼容旧名（旧代码/外部可能仍引用 ResearchAgent）
ResearchAgent = SearcherAgent
