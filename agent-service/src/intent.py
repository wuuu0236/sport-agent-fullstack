"""意图分类：LLM 结构化判断为主，关键词规则为兜底（2026-09-16）。

原实现是 app.py::_needs_orchestration() 的纯关键词规则——只有「周报」「总结+时间
范围」「数据驱动计划」三类魔法词才会升级多 Agent 编排。后果是典型复杂任务被当成
单点问答硬答，例如：

    膝盖疼，分析是不是深蹲姿势问题，给康复方案   → 本该 clinician+expert+planner
    对比上个月和这个月的跑步数据                 → 本该 analyst×2 + 综合
    备战半马，查最新方法，结合我的水平排 8 周计划  → 本该 searcher+analyst+planner

三类实际都掉进了 coach 单 Agent 直答（见 CHANGELOG「2026-09-16」条）。

现在改为：
· 真实模式：一次轻量 LLM 调用输出结构化 JSON（type / reason / suggested_agents）；
· mock 模式、调用失败、JSON 解析失败：退回 rule_needs_orchestration()。
  规则函数因此仍是活代码（不是死代码），也保证「无 LLM key 也能跑通」的既有约束。

安全取向：**分类失败一律按保守方向走**——宁可退回规则（多数情况走单 Agent 直答，
代价是少拆一次），也不因为一次异常把普通问答升级成 20 秒的多 Agent 编排。
"""
import json

from . import config, llm
from .agents import agent_catalog

# 分类结果三态：直接回答 / 数据操作（记录·查询，仍是单 Agent） / 多 Agent 编排
DIRECT = "direct_answer"
DATA_OP = "data_operation"
ORCHESTRATE = "orchestrate"

_CLASSIFY_PROMPT = """你是个人体育训练助理的调度器：判断用户这条消息该由「单个 Agent 直答」还是「多 Agent 协作」处理。

三种类型：
- direct_answer：单点问题/建议/概念，一个教练就能答完。例：「怎么练胸」「膝盖疼还能跑吗」「卧推要点」
- data_operation：读写用户自己的训练数据，单个执行型 Agent 即可。例：「记录6公里配速6分半」「这周跑了多少」「看我的跑步记录」
- orchestrate：必须多个专长协作才能完成的任务——同时需要①外部资料或②历史数据计算，又要③综合成文/出方案。例：「帮我生成周报」「总结这周的训练情况」「根据我的训练数据安排下阶段计划」「备战半马，查最新方法并结合我的水平排8周计划」「对比上个月和这个月的跑步数据」

判据（满足任一即 orchestrate）：
· 需要「查资料 + 算数据 + 出成品」三件事里的两件以上
· 需要跨时间段对比或读取多种历史数据后再下结论
· 明确要「周报 / 阶段总结 / 报告 / 排期计划」这类多源汇合的成品

只输出 JSON（不要 markdown 代码块、不要多余文字）：
{{"type": "direct_answer|data_operation|orchestrate", "reason": "一句话理由", "suggested_agents": ["可派发的子agent名"]}}

可用子 Agent：{catalog}"""


def rule_needs_orchestration(msg: str) -> bool:
    """关键词规则：一条消息是否需要多 Agent 主从编排（原 app.py::_needs_orchestration）。

    保留为 classify() 的兜底路径，语义与历史行为完全一致，便于回归对照。
    """
    # 记录训练类：recorder 单 Agent 即可，不编排（避免『记录一次减脂训练』误判）
    if any(k in msg for k in ("记一次", "记录", "保存", "入库", "添加")) and \
       any(k in msg for k in ("跑", "公里", "km", "组", "次", "kg", "训练")):
        return False
    # 健身域已统一归 coach（谭成义唯一直答）；编排只留给「多源汇合」用例。
    # ① 周报类：汇报表（检索 + 分析 + 综合）。
    #    但「谈论周报」≠「要生成周报」：概念询问类（格式/包含什么/怎么写）不编排。
    if "周报" in msg:
        if any(k in msg for k in ("什么", "格式", "怎么写", "包含", "模板", "例子", "示例")):
            return False
        return True

    # ② 阶段性总结/回顾类：总结类动词 + 时间范围词同时出现。
    #    「总结一下卧推要点」是单点问题（无时间范围），不编排；
    #    「总结这周的训练」需要读周聚合数据再综合，编排。
    _SUMMARY_KW = ("总结", "汇总", "回顾", "复盘", "报告")
    _RANGE_KW = ("这周", "本周", "上周", "最近", "近期", "本月", "这个月",
                 "一个月", "月度", "阶段")
    if any(k in msg for k in _SUMMARY_KW) and any(k in msg for k in _RANGE_KW):
        return True

    # ③ 数据驱动计划类：分析/依据 + 数据来源 + 计划产出，三要素齐才编排。
    _DATA_KW = ("分析", "根据", "结合", "基于", "参考")
    _SRC_KW = ("数据", "情况", "记录", "表现", "进步")
    _PLAN_KW = ("计划", "方案", "安排", "课表")
    if any(k in msg for k in _DATA_KW) and any(k in msg for k in _SRC_KW) \
            and any(k in msg for k in _PLAN_KW):
        return True

    return False


def _parse_classify(raw: str) -> dict:
    """解析 LLM 分类输出；失败返回 {}（调用方据此走规则兜底）。"""
    if not raw:
        return {}
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    kind = str(data.get("type") or "").strip()
    if kind not in (DIRECT, DATA_OP, ORCHESTRATE):
        return {}
    agents = data.get("suggested_agents")
    if not isinstance(agents, list):
        agents = []
    names = {a["name"] for a in agent_catalog()}
    return {
        "kind": kind,
        "reason": str(data.get("reason") or "")[:200],
        "suggested_agents": [str(a) for a in agents if str(a) in names][:6],
    }


def classify(task: str, force_orchestrate: bool = False) -> dict:
    """判断消息走向。返回 {kind, reason, suggested_agents, via}。

    force_orchestrate=True 用于 /supervise 这类显式编排入口（跳过分类）。
    """
    if force_orchestrate:
        return {"kind": ORCHESTRATE, "reason": "显式编排入口", "suggested_agents": [],
                "via": "forced"}
    if config.CONFIG.mock_mode:
        return _from_rule(task)
    catalog = "\n".join(f"- {a['name']}：{a['description']}" for a in agent_catalog())
    try:
        raw = llm.chat(
            [{"role": "system", "content": _CLASSIFY_PROMPT.replace("{catalog}", catalog)},
             {"role": "user", "content": task}],
            temperature=0.0, max_tokens=300,
        )
    except Exception:
        raw = ""
    parsed = _parse_classify(raw)
    if parsed:
        parsed["via"] = "llm"
        return parsed
    return _from_rule(task)


def _from_rule(task: str) -> dict:
    """规则兜底：与历史行为一致（只有三类魔法词才编排）。"""
    return {
        "kind": ORCHESTRATE if rule_needs_orchestration(task) else DIRECT,
        "reason": "关键词规则兜底（mock 模式或分类调用失败）",
        "suggested_agents": [],
        "via": "rule",
    }
