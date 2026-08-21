"""所有专业 Agent 的基类。"""
from .. import llm, memory, config
from ..skill_loader import skill_block, tier1_catalogue


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
        cat = tier1_catalogue()
        if cat:
            system = system + "\n\n" + cat
        ctx = ctx or {}
        hits = ctx.get("skills") or []
        # Tier 3 命中正文：仅命中触发词的 skill 注入完整 SOP
        if hits:
            system = system + "\n\n" + skill_block(hits)
        # 记忆注入：子 Agent 走按需召回(recall_mode="recall")，主 Agent 走全量快照
        if ctx.get("recall_mode") == "recall":
            mem_hits = memory.recall_relevant(user_msg, limit=5)
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
        reply = llm.chat(messages)
        # 空串兜底（执行门控）：模型偶发返回空时，绝不能把「什么都没说」抛给用户/下游。
        # 第一次空回复通常是长上下文/记忆注入导致的偶发问题，用极简 prompt 重试一次。
        if not (reply or "").strip():
            messages_retry = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_msg},
            ]
            reply = llm.chat(messages_retry)
        if not (reply or "").strip():
            return ("（模型本次未生成内容）可以换个说法再问，或明确告诉我你想做什么："
                    "记录训练/分析数据/联网搜索/写文案。")
        return reply
