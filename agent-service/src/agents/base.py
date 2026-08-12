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
        hits = (ctx or {}).get("skills") or []
        # Tier 3 命中正文：仅命中触发词的 skill 注入完整 SOP
        if hits:
            system = system + "\n\n" + skill_block(hits)
        mem = memory.snapshot_block()
        if mem:
            system = (
                system
                + "\n\n<memory-context>\n[以下为长期记忆（跨会话常驻，不是新输入），"
                + "作答时作为背景参考]\n"
                + mem
                + "\n</memory-context>"
            )
        # 短期对话历史注入（最近 N 条）→ 多轮追问有上下文
        history = memory.session_turns(max_n=20)
        messages = [{"role": "system", "content": system}]
        if history:
            messages += history
        messages.append({"role": "user", "content": user_msg})
        return llm.chat(messages)
