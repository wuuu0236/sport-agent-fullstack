"""联网搜索：多后端 + 查询变体 + 诚实降级（零第三方依赖，urllib 实现）。

现实约束（实测确认）：免费无 key 的搜索源里，中文分词稳定可用的非常少——
  · Bing RSS 可用但中文分词不稳：同一句话换几个词，结果可能完全漂移
    （实测『马拉松赛事』→ 快手；『马拉松比赛 2026』→ 马拉松官网）。
  · DuckDuckGo HTML 在本机网络环境超时；维基百科仅覆盖事实类。

因此做三层兜底：
  1. Tavily（.env 配 TAVILY_API_KEY 时）——最稳，直接用它；
  2. 无 key 时：确定性生成多个查询变体（去口语词 / 补年份 / 同义词替换），
     每个变体各搜一次 Bing RSS，结果按 URL 去重合并——只要任一变体命中，
     相关内容就进并集，交给 research Agent 在回答时筛掉无关项；
  3. 全部无结果 → 维基百科再兜一层 → 仍空则由 research Agent 如实告知未联网。
"""
import datetime
import json
import re
import urllib.parse
import urllib.request

from . import config

# 查询变体：去掉这些口语/限定词后，Bing 更可能命中核心实体
_QUALIFIER_RE = re.compile(
    r"最近的|最近|有哪些|有什么|什么|怎样|如何|怎么|帮我|请|一下|"
    r"哪儿|哪里|能否|能不能|请问|查查|搜索|查一下")

_YEAR_RE = re.compile(r"20\d\d")
# 事件类词：命中才补「+年份」变体（Bing 对『名词 + 年份』分词更稳）
_EVENT_RE = re.compile(r"赛事|比赛|马拉松|报名|越野|铁三|半马|全马|跑")
# 同义词替换：实测 Bing 对『比赛』比『赛事』稳
_SYNONYMS = (("赛事", "比赛"),)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(s: str) -> str:
    return _TAG_RE.sub("", s)


def _query_variants(q: str) -> list:
    """确定性生成多个查询变体（不依赖 LLM，保证可复现、不会空结果）。"""
    q = (q or "").strip()
    if not q:
        return []
    year = str(datetime.date.today().year)
    variants = [q]
    stripped = _QUALIFIER_RE.sub("", q)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    if stripped and stripped != q:
        variants.append(stripped)
    # 事件类查询补年份版本
    if _EVENT_RE.search(q):
        for base in dict.fromkeys([stripped or q, q]):
            if not _YEAR_RE.search(base):
                variants.append(f"{base} {year}")
    # 同义词替换版本（赛事→比赛）
    for src, dst in _SYNONYMS:
        for v in list(variants):
            if src in v:
                rep = v.replace(src, dst)
                if rep not in variants:
                    variants.append(rep)
    return list(dict.fromkeys(variants))


def search(query: str, limit: int = 8) -> list:
    """返回 [{title, url, snippet}]；无法联网或无结果时返回 []。

    无 key 时返回「多个查询变体的并集」（URL 去重，最多 16 条）。
    关键：不按 limit 截断——否则前面变体的无关结果会顶掉后面命中变体的好结果
    （实测『马拉松赛事』漂移到快手/双色球，只有『马拉松比赛 2026』命中官网）。
    混合的少量无关项由 research Agent 在回答时筛掉。
    """
    if config.CONFIG.TAVILY_API_KEY:
        return _tavily(query, limit)
    seen, merged = set(), []
    for v in _query_variants(query)[:6]:
        for r in _bing(v, 3):
            u = r.get("url")
            if not u or u in seen:
                continue
            seen.add(u)
            merged.append(r)
    if merged:
        return merged[:16]
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
# Bing RSS（免费，无 key）：中文/通用资讯覆盖广，作为 Tavily 的零成本兜底
# ---------------------------------------------------------------------------
def _bing(query: str, limit: int) -> list:
    """走 Bing 的 format=rss 输出（标准 RSS XML，标准库解析，保持零依赖）。

    www.bing.com 在国内会 302 到 cn.bing.com，urllib 自动跟随重定向；
    带常规浏览器 UA 避免被当爬虫拒绝。
    """
    import html as _html

    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote(query)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0 Safari/537.36"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml = resp.read().decode("utf-8", errors="replace")
        from xml.etree import ElementTree as ET
        root = ET.fromstring(xml)
        out = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = _strip_tags(item.findtext("description") or "")
            if not title or not link:
                continue
            out.append({"title": _html.unescape(title),
                        "url": link,
                        "snippet": _html.unescape(desc)[:300]})
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


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
