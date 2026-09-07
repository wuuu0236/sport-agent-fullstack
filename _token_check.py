"""临时对照脚本（只读，不改任何数据）：在一句请求上对比
子 Agent 优化前(全量记忆+20轮历史) vs 优化后(按需召回+关历史) 的输入体量。
"""
import sys, types
sys.path.insert(0, "agent-service")

import src.llm as llm
import src.memory as memory
from src.agents import get_agent

# —— 打桩：不触网，只记录每次 _llm 调用拼出的 messages 总字符数 ——
captured = {"calls": []}
def fake_chat(messages, **kw):
    total_chars = sum(len(m.get("content", "")) for m in messages)
    captured["calls"].append(total_chars)
    return "（打桩）计划文本"
llm.chat = fake_chat

# —— 模拟 20 轮真实对话历史（仅用于本测量，不写入文件） ——
SYNTH_HISTORY = []
for i in range(1, 11):
    SYNTH_HISTORY.append({"role": "user",
                          "content": f"今天第{i}次记录：跑步{i}公里，平均心率13{i}"})
    SYNTH_HISTORY.append({"role": "assistant",
                          "content": f"收到，已记录你今天的第{i}次训练数据，继续保持。"})
_orig_session = memory.session_turns
def fake_session(max_n=20):
    return SYNTH_HISTORY[:max_n]
memory.session_turns = fake_session

Q = "帮我生成减脂三分化训练计划"

def run_once(ctx):
    captured["calls"] = []
    agent = get_agent("planner")
    agent.handle(Q, ctx)
    return sum(captured["calls"])  # 该子 Agent 本次调用的总输入字符数

# BEFORE：默认路径（全量记忆 snapshot_block + 20 轮历史）
before_chars = run_once({"skills": []})

# AFTER：优化路径（recall_relevant 按需 ≤5 + 关历史）
after_chars = run_once({"skills": [], "use_history": False, "recall_mode": "recall"})

# 记忆两部分体量（真实读取，只读）
full_mem = memory.snapshot_block() or ""
recall = memory.recall_relevant(Q, limit=5)
recall_chars = sum(len(x) for x in recall)
hist_chars = sum(len(t["content"]) for t in SYNTH_HISTORY)

def tok(c):  # 中文为主，约 1.6 字符/token 粗估
    return round(c / 1.6)

print("=" * 60)
print("子 Agent（planner）单次调用 输入体量对照")
print("=" * 60)
print(f"全量记忆 snapshot_block : {len(full_mem):>6} 字符  ≈ {tok(len(full_mem)):>5} token")
print(f"按需召回 recall(≤5)     : {recall_chars:>6} 字符  ≈ {tok(recall_chars):>5} token")
print(f"20 轮历史(模拟)         : {hist_chars:>6} 字符  ≈ {tok(hist_chars):>5} token")
print("-" * 60)
print(f"BEFORE 总输入 : {before_chars:>6} 字符  ≈ {tok(before_chars):>5} token")
print(f"AFTER  总输入 : {after_chars:>6} 字符  ≈ {tok(after_chars):>5} token")
print(f"单次调用省下 : {before_chars-after_chars:>6} 字符  ≈ {tok(before_chars-after_chars):>5} token")
print("=" * 60)
print("注：一次「生成计划」编排会调 5~7 次 LLM，子 Agent 占多数，")
print("    故整次编排省下的 token ≈ 上面单次省 × 子 Agent 次数。")
print("=" * 60)

# 还原，避免影响其他逻辑
memory.session_turns = _orig_session
