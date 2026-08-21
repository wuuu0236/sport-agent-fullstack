"""记忆 Agent：记住 / 回忆关于用户的事实与偏好（双存储：USER.md / MEMORY.md）。

存储路由（受 Hermes 双存储启发）：
  - USER（关于用户）：身份、偏好、训练基线、个人事实
  - MEMORY（助理笔记）：约定、技巧、学到的流程——偏「助理自己」的内容
"""
from .base import BaseAgent
from .. import config, memory

# 偏「助理自己笔记」的触发词 → 落 MEMORY 存储
_MEMNOTE_KW = ["笔记", "技巧", "约定", "学到", "流程", "记住这个技巧", "记一下技巧", "怎么弄", "怎么用"]


class MemoryAgent(BaseAgent):
    name = "memory"
    description = "记住/回忆关于用户的事实、偏好、待办（双存储长期记忆）"
    system_prompt = (
        "你是用户的记忆管家。负责把用户提到的重要事实、偏好、待办记到长期记忆，"
        "在被问到『你记得我什么』时清晰复述。身份/偏好/训练基线类记到 user 存储，"
        "技巧/约定/流程类记到 memory 存储。回答简洁、口语化。"
    )

    # 「存储」触发词（覆盖口语化说法：记住/记下/记入/存入/写入/放进/加入）
    _STORE_KW = ["记住", "记下", "记一下", "别忘了", "记着", "记笔记", "记个笔记",
                 "记入", "存入", "写入", "放进", "放入", "加入"]
    # 「回忆」触发词（问句）
    _RECALL_KW = ["你记得", "还记得", "回忆", "记得我什么", "记得什么", "记得吗", "记得不"]

    def handle(self, user_msg: str, ctx: dict = None) -> str:
        is_store = any(k in user_msg for k in self._STORE_KW)
        is_recall = any(k in user_msg for k in self._RECALL_KW)
        is_question = any(q in user_msg for q in ["？", "?", "什么", "吗", "哪", "谁"])
        want_store = is_store or ("记得" in user_msg and not (is_recall or is_question))
        want_recall = is_recall or ("记得" in user_msg and is_question)

        # 召回：两种模式都直接读盘（持久记忆是招牌功能，不走 LLM 聊天）
        if want_recall and not want_store:
            return self._recall()

        # 存储：两种模式都真正写盘（关键修复——真实模式此前只聊天不落库）
        if want_store:
            fact = _extract_fact(user_msg)
            if fact and fact not in ("什么", "什么？", "什么?"):
                target = "memory" if any(k in user_msg for k in _MEMNOTE_KW) else "user"
                ok, msg = memory.remember(target, fact)
                if not ok:
                    return f"🤔 没记下：{msg}"
                store_label = "USER（关于你）" if target == "user" else "MEMORY（助理笔记）"
                return (
                    f"✅ 已记住到 {store_label}：{fact}\n"
                    f"（已存入长期记忆，下次可直接问我『你记得我什么』）"
                )
            return "🤔 没听清要记什么，可以说「记住我……」「记下……」。"

        # 非明确的存储/召回：真实模式用 LLM 闲聊，mock 直接给召回便于演示
        if config.CONFIG.mock_mode:
            return self._recall()
        return self._llm(user_msg, ctx=ctx)

    def _recall(self) -> str:
        stores = memory.list_store()
        user_facts = stores.get("user") or []
        mem_notes = stores.get("memory") or []
        if not user_facts and not mem_notes:
            return "🧠 我目前还没记住什么。你可以说「记住我……」「记下……」来让我记住。"
        lines = []
        if user_facts:
            lines.append("👤 关于你（USER）：")
            lines += [f"  · {f}" for f in user_facts]
        if mem_notes:
            lines.append("📝 助理笔记（MEMORY）：")
            lines += [f"  · {f}" for f in mem_notes]
        return "🧠 我记得：\n" + "\n".join(lines)


def is_memory_intent(msg: str) -> bool:
    """判断消息是否为记忆存/取意图（存/取是元动作，应优先于领域 skill 路由）。"""
    if any(k in msg for k in MemoryAgent._STORE_KW):
        return True
    if any(k in msg for k in MemoryAgent._RECALL_KW):
        return True
    return "记得" in msg


def _extract_fact(msg: str) -> str:
    s = (msg or "").strip()
    # 去掉开头引导语（帮我把 / 把 / 请帮我…）
    for lead in ("帮我把", "帮我", "请帮我", "请记", "把"):
        if s.startswith(lead):
            s = s[len(lead):]
            break
    # 去掉结尾指令壳（记入用户画像 / 存入我的userid / 画像…）
    for tail in ("记入用户画像", "记入用户id", "记入我的userid", "存入用户画像",
                 "存入我的userid", "存入用户id", "记入画像", "存入画像",
                 "用户画像", "我的userid", "用户id", "画像"):
        if s.endswith(tail):
            s = s[: -len(tail)]
            break
    # 处理「把 X 放进/存入/记入 Y」结构：事实在动词之前
    for verb in ("放进", "放入", "存入", "记入", "写入"):
        if verb in s:
            s = s.split(verb, 1)[0]
            break
    # 再尝试已知 store 前缀（记住我… / 记下… / 记入…）
    for p in ("记住我", "记得我", "记一下", "记个笔记", "记笔记", "记下", "记住",
              "记着", "别忘了", "记入", "存入", "写入", "放进", "放入", "加入"):
        if p in s:
            s = s.split(p, 1)[1]
            break
    # 去掉无意义的连接词
    s = s.rstrip("也一下")
    return s.strip(" ：:，.。?？!！吗、")
