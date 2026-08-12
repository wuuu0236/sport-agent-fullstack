"""联网搜索：多后端 + 诚实降级（零第三方依赖，urllib 实现，与整个 MVP 一致）。

后端优先级：
  1. Tavily（.env 配置 TAVILY_API_KEY 时）——真正的网页搜索，返回带摘要的结果。
  2. 维基百科（免费无 key）——事实类查询兜底（什么是XX / 简介）。
  3. 都不可用/无结果 → 返回空列表，由 research Agent 如实告知「未联网」，绝不编造。

所有后端异常均捕获并降级，保证搜索失败不拖垮对话。
"""
import json
import urllib.parse
import urllib.request

from . import config


def search(query: str, limit: int = 5) -> list:
    """返回 [{title, url, snippet}]；无法联网或无结果时返回 []。"""
    if config.CONFIG.TAVILY_API_KEY:
        return _tavily(query, limit)
    return _wikipedia(query, limit)


def format_sources(results: list) -> str:
    """把搜索结果渲染成给 LLM 的检索块。"""
    if not results:
        return ""
    lines = ["已检索到以下资料（回答时如实引用，不要编造来源）："]
    for i, r in enumerate(results, 1):
        snip = (r.get("snippet") or "").strip()[:300]
        lines.append(f"{i}. {r.get('title') or '(无标题)'}\n   {r.get('url') or ''}\n   {snip}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tavily（需 key）
# ---------------------------------------------------------------------------
def _tavily(query: str, limit: int) -> list:
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": config.CONFIG.TAVILY_API_KEY,
        "query": query,
        "max_results": limit,
        "search_depth": "basic",
    }
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = []
        for r in data.get("results", [])[:limit]:
            out.append({"title": r.get("title", ""), "url": r.get("url", ""),
                        "snippet": r.get("content", "")})
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 维基百科（免费，无 key）：中文优先，其次英文
# ---------------------------------------------------------------------------
def _wikipedia(query: str, limit: int) -> list:
    for lang in ("zh", "en"):
        res = _wiki_lang(lang, query, limit)
        if res:
            return res
    return []


def _wiki_lang(lang: str, query: str, limit: int) -> list:
    # opensearch 返回 [query, [标题], [简介], [urls]]
    url = (f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&limit={limit}"
           f"&format=json&search={urllib.parse.quote(query)}")
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        titles, descs, urls = data[1], data[2], data[3]
    except Exception:
        return []
    out = []
    for i, t in enumerate(titles[:limit]):
        snip = descs[i] if i < len(descs) else ""
        if not snip:  # opensearch 简介经常为空，取前 1-2 条的真实摘要补上
            snip = _wiki_summary(lang, t)
        out.append({"title": t, "url": urls[i] if i < len(urls) else "",
                    "snippet": snip[:300]})
    return out


def _wiki_summary(lang: str, title: str) -> str:
    url = (f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
           f"{urllib.parse.quote(title)}")
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("extract", "")
    except Exception:
        return ""
