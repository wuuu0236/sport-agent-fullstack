"""Skill 加载与匹配（Phase 4 升级：借鉴 Hermes 技能系统）。

对照 Hermes 的两块招牌能力做了落地：

1. 三级渐进加载（progressive disclosure，控 token）：
   - Tier 1 目录常驻：仅「name + description + summary（可选）」，约 20~60 字
     / skill，启动时全部注入 system prompt，作为可调用技能的目录。
   - Tier 2 候选摘要：命中触发词但须「加载」才给正文时，返回 description（已在目录里）。
   - Tier 3 命中正文：触发词匹配的 skill 才注入完整 SOP 正文，未命中的完全不占上下文。
   这样随技能数量增长，上下文成本只随「本次命中数」增长，而不是随「总技能数」增长。

2. 任务后自动蒸馏 + patch 式更新（self-improving 闭环）：
   - 用户说「存技能：<主题> <正文>」→ 把近期对话（session.json 最近 N 条）沉淀成新 SKILL.md。
   - 用户说「patch 技能 <name>：<补丁>」→ 以「补丁」而非整体重写的方式追加/修订要点，
     token 更低、避免回归（Hermes 工程成熟度细节）。
   - 蒸馏出的技能即时进入内存缓存，下一次对话即可命中——「越用越聪明」。

设计目标：零外部依赖（纯标准库），与整个 MVP 一致。
"""
import json
import re
from pathlib import Path

from . import config

SKILL_DIR = config.BASE_DIR / "skills"
_CACHE = None  # 启动后缓存，避免每次请求都扫盘

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)
# 蒸馏命令识别
_DISTILL_RE = re.compile(r"^\s*(存技能|保存技能|蒸馏技能)\s*[:：]?\s*(.*)$", re.S)
_PATCH_RE = re.compile(r"^\s*patch\s+技能\s+([^\s：:]+)\s*[:：]?\s*(.*)$", re.S)


def _parse_frontmatter(text: str):
    """解析 SKILL.md：返回 (frontmatter_dict, body_str)。"""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text.strip()
    fm_raw, body = m.group(1), m.group(2)
    fm = {}
    for line in fm_raw.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            if not inner:
                v = []
            else:
                try:
                    v = json.loads(v)  # 标准 JSON 数组
                except Exception:
                    v = [x.strip().strip('"\'') for x in inner.split(",") if x.strip()]
        fm[k] = v
    return fm, body.strip()


def load_skills(force: bool = False):
    """扫描并缓存所有 skill。返回 [{name, description, summary, triggers, agent, body}]。"""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    skills = []
    if SKILL_DIR.exists():
        for d in sorted(SKILL_DIR.iterdir()):
            p = d / "SKILL.md"
            if p.is_file():
                fm, body = _parse_frontmatter(p.read_text(encoding="utf-8"))
                skills.append({
                    "name": fm.get("name", d.name),
                    "description": fm.get("description", ""),
                    "summary": fm.get("summary", ""),  # tier1 目录里的可选精简摘要
                    "triggers": fm.get("triggers", []) or [],
                    "agent": fm.get("agent"),  # skill 可声明主理 Agent，命中时覆盖路由
                    "body": body,
                })
    _CACHE = skills
    return skills


# ---------------------------------------------------------------------------
# Tier 1：可调用技能目录（常驻 system prompt，极轻量）
# ---------------------------------------------------------------------------
def tier1_catalogue() -> str:
    """渲染「技能目录」块：每个 skill 仅 name + description（+ 可选 summary）。

    约 20~60 字/skill，启动即常驻，让 LLM 知道「有哪些技能可调用」。
    """
    skills = load_skills()
    if not skills:
        return ""
    lines = ["【可调用技能目录 / Skills】遇到下列主题时，可加载对应技能获取完整 SOP："]
    for s in skills:
        entry = f"- {s['name']}：{s['description']}"
        if s.get("summary"):
            entry += f"（{s['summary']}）"
        lines.append(entry)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tier 2/3：命中匹配（仅命中者才注入完整正文）
# ---------------------------------------------------------------------------
def match_skills(message: str):
    """按触发词命中 skill，返回命中的 skill 列表（去重，保持声明顺序）。"""
    msg = (message or "").lower()
    hits = []
    seen = set()
    for s in load_skills():
        for t in s.get("triggers", []):
            if t and str(t).lower() in msg and s["name"] not in seen:
                hits.append(s)
                seen.add(s["name"])
                break
    return hits


def skill_block(hits) -> str:
    """Tier 3：把命中的 skill 正文拼成可注入 system_prompt 的文本块。"""
    if not hits:
        return ""
    lines = ["【已启用技能 / Skills 注入】下面是当前任务需要遵循的专业指令："]
    for s in hits:
        lines.append(f"── skill: {s['name']} ──\n{s['body']}")
    return "\n".join(lines)


def skill_names(hits) -> str:
    return ", ".join(s["name"] for s in hits)


def list_skills():
    """返回 [(name, description)]，用于演示/调试时打印已注册技能。"""
    return [(s["name"], s["description"]) for s in load_skills()]


# ---------------------------------------------------------------------------
# 任务后蒸馏 / patch（self-improving 闭环）
# ---------------------------------------------------------------------------
def is_distill_intent(msg: str) -> bool:
    return bool(_DISTILL_RE.match(msg or ""))


def is_patch_intent(msg: str) -> bool:
    return bool(_PATCH_RE.match(msg or ""))


def _slugify(name: str) -> str:
    """生成目录名：小写、去空格、非文件名字符转下划线。"""
    s = re.sub(r"[^\w一-鿿]+", "_", name.strip().lower()).strip("_")
    return s or "skill"


def distill_skill(msg: str) -> str:
    """「存技能：<主题> <正文>」→ 把近期对话 + 用户正文沉淀成新 SKILL.md。

    返回人类可读的结果摘要（[skill] 标签会在 server 层加）。
    """
    m = _DISTILL_RE.match(msg or "")
    if not m:
        return "（未能识别存技能指令）"
    body_text = m.group(2).strip()
    if not body_text:
        return "（请提供技能正文，格式：存技能：<主题> <SOP/要点>）"

    # 蒸馏命令格式：存技能：<主题词> <正文/SOP...>
    # 主题词取首个空白分隔的短词（如「周报生成」），其余作为正文。
    parts = body_text.split(None, 1)
    theme = parts[0].strip() if parts else body_text.strip()[:8]
    sop_text = parts[1].strip() if len(parts) > 1 else "（请补充执行要点）"
    # 触发词：主题词整词 + 首 2 字兜底，保证「帮我生成周报」这类包含「周报」的消息也能命中。
    triggers = [theme]
    if len(theme) >= 2:
        triggers.append(theme[:2])
    triggers = triggers[:8]

    # 取近期对话作为背景（仅用于提示，不直接塞进 skill body）
    recent = _recent_session()
    skill_dir = SKILL_DIR / _slugify(theme)
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    if skill_file.exists():
        return f"技能目录 {skill_dir.name} 已存在，可用「patch 技能 {skill_dir.name}：...」补丁式更新。"
    fm = {
        "name": skill_dir.name,
        "description": theme,
        "summary": "用户蒸馏的自定义技能",
        "triggers": json.dumps(triggers, ensure_ascii=False),
        "agent": "",
    }
    content = (
        f"---\n"
        f"name: {fm['name']}\n"
        f"description: {fm['description']}\n"
        f"summary: {fm['summary']}\n"
        f"triggers: {fm['triggers']}\n"
        f"agent: {fm['agent']}\n"
        f"---\n"
        f"# {theme}\n\n"
        f"此技能由用户从近期对话中蒸馏生成（self-improving 闭环）。\n\n"
        f"## 执行要点\n{sop_text}\n"
    )
    skill_file.write_text(content, encoding="utf-8")
    load_skills(force=True)  # 即时刷新缓存，下一条对话即可命中
    return (
        f"✅ 已将「{theme}」蒸馏为新技能（{skill_file}）。\n"
        f"· 触发词：{', '.join(triggers) or '（无）'}\n"
        f"· 已写入技能库，下次对话命中触发词即自动加载。"
    )


def patch_skill(msg: str) -> str:
    """「patch 技能 <name>：<补丁>」→ 以补丁方式追加/修订，避免整体重写回归。"""
    m = _PATCH_RE.match(msg or "")
    if not m:
        return "（未能识别 patch 指令）"
    name, patch = m.group(1).strip(), m.group(2).strip()
    if not patch:
        return "（请提供补丁内容）"
    target = _find_skill_dir(name)
    if not target:
        return f"未找到技能 {name}，可用「存技能：...」新建。"
    skill_file = target / "SKILL.md"
    existing = skill_file.read_text(encoding="utf-8")
    # patch 以补丁块追加到正文末尾（不重写整体，token 更低、不丢原内容）
    patched = existing.rstrip() + f"\n\n## 补丁更新\n{patch}\n"
    skill_file.write_text(patched, encoding="utf-8")
    load_skills(force=True)
    return f"✅ 已对技能 {name} 追加补丁（未重写整体，避免回归）。"


def _find_skill_dir(name: str):
    name_l = name.lower()
    if SKILL_DIR.exists():
        for d in SKILL_DIR.iterdir():
            if d.is_dir() and d.name.lower() == name_l:
                return d
    return None


def _recent_session(n: int = 12) -> list:
    """读 session.json 最近 N 条，用于蒸馏时的背景上下文。"""
    p = config.CONFIG.SESSION_FILE
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    return d.get("messages", [])[-n:]
