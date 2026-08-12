"""搜索 / 资讯 Agent：联网搜索资料、新闻、最新信息。

真实模式：优先 Tavily（.env 配 TAVILY_API_KEY），否则免费维基百科兜底，
再不行就如实告知「未联网检索」——不再让 LLM 假装自己搜过（旧版硬伤）。
"""
from .base import BaseAgent
from .. import config, search


class ResearchAgent(BaseAgent):
    name = "research"
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
                "优先 Tavily，否则维基百科免费兜底。）"
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
            "请基于以上检索结果回答，要点化、附来源序号；"
            "检索结果不足时如实说明。",
            ctx=ctx)
