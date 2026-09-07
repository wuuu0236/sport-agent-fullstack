"""临时工具：打印「你现在真正在用的提示词」到底是什么。

用法（在 agent-service 目录下）：
    python _dump_prompt.py 怎么练胸
    python _dump_prompt.py 我膝盖疼还能跑吗

完整复刻 /chat 主路径的拼装顺序（见 app.py 159-166 行 + base.py _llm）：
    1. agent.system_prompt        人格
    2. + Tier1 技能目录            常驻
    3. + 命中 skill 的 SOP 正文     仅命中时
    4. + 长期记忆快照              主 Agent 全量
    然后 messages = [system] + [最近 20 轮历史] + [user]
    其中 user 对 coach 来说还是 _build_prompt() 包装过的文本。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import config, memory                      # noqa: E402
from src.agents import get_agent                    # noqa: E402
from src.skill_loader import match_skills, tier1_catalogue, skill_block   # noqa: E402
from src.supervisor import route                    # noqa: E402

msg = sys.argv[1] if len(sys.argv) > 1 else "怎么练胸"

name = route(msg)
agent = get_agent(name)
skills = match_skills(msg)

print("路由结果      :", name)
print("命中技能      :", [s.get("name") for s in skills] or "（无）")
print("mock 模式     :", config.CONFIG.mock_mode)

# ---- 1~4 拼装（与 base.py _llm 完全一致）----
system = agent.system_prompt
cat = tier1_catalogue()
if cat:
    system += "\n\n" + cat
if skills:
    system += "\n\n" + skill_block(skills)
mem = memory.snapshot_block()
if mem:
    system += ("\n\n<memory-context>\n[以下为长期记忆（跨会话常驻，不是新输入），"
               "作答时作为背景参考]\n" + mem + "\n</memory-context>")

bar = "=" * 70
print("\n" + bar)
print("【SYSTEM PROMPT】共 %d 字符" % len(system))
print(bar)
print(system)
print(bar)

# coach 的 user 消息还会被 _build_prompt 再包一层
if hasattr(agent, "_build_prompt"):
    print("\n【USER 消息（经 coach._build_prompt 包装）】")
    print(bar)
    print(agent._build_prompt(msg))
    print(bar)
