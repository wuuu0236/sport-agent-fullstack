"""所有专业 Agent 的基类。"""
from .. import llm, memory, config
from ..skill_loader import registry_version, skill_block, tier1_catalogue

# 技能目录（tier1_catalogue）缓存：目录只依赖 skills 注册表，很稳定，拼一次复用，
# 既省每次调用的字符串拼装，又让全局前缀字符串保持稳定（更利于命中缓存）。
# 但 `存技能` / `patch 技能` 会热改注册表 —— 所以缓存必须跟着注册表版本号走：
# 只按「第一次调用」永久缓存，会让新蒸馏的技能永远不出现在目录里，LLM 也就
# 不知道自己「有」这个技能可调用（P1-3 修）。
_CATALOGUE_CACHE = None
_CATALOGUE_VERSION = -1


def _get_catalogue() -> str:
    global _CATALOGUE_CACHE, _CATALOGUE_VERSION
    ver = registry_version()
    if _CATALOGUE_CACHE is None or _CATALOGUE_VERSION != ver:
        _CATALOGUE_CACHE = tier1_catalogue() or ""
        _CATALOGUE_VERSION = ver
    return _CATALOGUE_CACHE


def _invalidate_catalogue():
    """手动丢弃目录缓存，强制下次重建。

    正常的热更新由注册表版本号自动触发（见 _get_catalogue），这个函数只是
    留一个手动兜底入口，不需要在 skill_loader 的写路径里回调它（避免反向依赖）。
    """
    global _CATALOGUE_CACHE, _CATALOGUE_VERSION
    _CATALOGUE_CACHE = None
    _CATALOGUE_VERSION = -1


class BaseAgent:
    name = "base"
    description = ""
    system_prompt = ""

    def handle(self, user_msg: str, ctx: dict = None) -> str:
        """处理一条用户消息，返回回复文本。ctx 可携带 {"skills": [...]}. """
        raise NotImplementedError

    def _llm(self, user_msg: str, ctx: dict = None) -> str:
        """真实 LLM 模式：用本 Agent 的 system_prompt + 命中 skill + 常驻记忆 生成回答。

        记忆以「冻结快照」形式注入 system prompt（受 Hermes 启发）：
        长期记忆在会话开始时载入，跨会话常驻、让每个 Agent 都『认识你』。
        """
        system = self.system_prompt
        # Tier 1 技能目录常驻：让 LLM 知道有哪些技能可调用（极轻量，约 20~60 字/技能）
        cat = _get_catalogue()
        if cat:
            system = system + "\n\n" + cat
        ctx = ctx or {}
        hits = ctx.get("skills") or []
        # Tier 3 命中正文：仅命中触发词的 skill 注入完整 SOP
        if hits:
            system = system + "\n\n" + skill_block(hits)
        # 记忆注入：子 Agent 走按需召回(recall_mode="recall")，主 Agent 走全量快照
        if ctx.get("recall_mode") == "recall":
            # 召回 query 用**原始用户任务**，不用 user_msg：后者是编排层/上游拼出来的
            # 指令文本（形如「用户需求：…\n\n待评审内容：…」），掺着大量与用户无关的
            # 噪声，拿它去检索会把召回带偏（旧实现就是拿 user_msg，实测基本召不回东西）。
            mem_hits = memory.recall_relevant(ctx.get("task") or user_msg, limit=5)
            if mem_hits:
                system = (
                    system
                    + "\n\n<memory-context>\n[以下为与本次请求最相关的长期记忆，"
                    + "作答时作为背景参考]\n"
                    + "\n".join(mem_hits)
                    + "\n</memory-context>"
                )
        else:
            mem = memory.snapshot_block()
            if mem:
                system = (
                    system
                    + "\n\n<memory-context>\n[以下为长期记忆（跨会话常驻，不是新输入），"
                    + "作答时作为背景参考]\n"
                    + mem
                    + "\n</memory-context>"
                )
        # 短期对话历史：子 Agent 关掉(use_history=False)，前缀更稳定、缓存更易命中
        use_history = ctx.get("use_history", True)
        history = memory.session_turns(max_n=20) if use_history else []
        messages = [{"role": "system", "content": system}]
        if history:
            messages += history
        messages.append({"role": "user", "content": user_msg})
        # 供应商/模型可被 ctx 覆盖：评审 Agent 用第二个厂商的模型做反方时走这里
        # （未配置则 None，行为与从前完全一致）。
        override = {k: ctx.get(k) for k in ("model", "base_url", "api_key") if ctx.get(k)}
        reply = llm.chat(messages, **override)
        # 空串兜底（执行门控）：模型偶发返回空时，绝不能把「什么都没说」抛给用户/下游。
        # 第一次空回复通常是长上下文/记忆注入导致的偶发问题，用极简 prompt 重试一次。
        if not (reply or "").strip():
            # 重试也要带 override：否则配了 REVIEW_MODEL 的场景会在重试时悄悄退回
            # 默认模型，把「换模型评审」无声降级成自评。
            messages_retry = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_msg},
            ]
            reply = llm.chat(messages_retry, **override)
        if not (reply or "").strip():
            return ("（模型本次未生成内容）可以换个说法再问，或明确告诉我你想做什么："
                    "记录训练/分析数据/联网搜索/写文案。")
        return reply
