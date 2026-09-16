"""评审第一层：规则检查（纯代码硬校验，不调 LLM）。

为什么需要这一层（方案 P1-1）：评审原先只有一次 LLM 调用，它有两个结构性弱点——
① 明显的机械问题（空产出、降级文案、短得没法交付）也要花一次调用才发现；
② 没有确定性基线，评审结论完全取决于模型当时的状态。

现在把「能硬判的」交给代码，LLM 只处理「需要理解」的：

- **blocking**：空 / 哨兵 / 降级文案 / 过短 —— 直接判不过，**不再调用 LLM 评审**
  （省一次调用，也让失败原因可复现、可写进测试）；
- **hints**：疑似编造的数字、缺失的必备段落 —— 只作为「已知疑点」附加到评审提示里，
  由 LLM 结合上下文判断。**故意不设 blocking**：误报会惩罚正确产出（历史上评审误报
  已经出现过一次），所以凡是有疑义的规则都只提示、不裁决。

数字核对为什么只做「可疑提示」：计划类产出天然包含大量非资料数字（8 周、4 组、80kg、
半马 21km），一律当编造会把好产出判死。所以只标注「带度量单位的数字在上游材料里找不到
出处」，并把判断权交给评审模型。
"""
import re

# 与 graph.py 保持一致的哨兵/降级标记
_SENTINEL = "（模型本次未生成内容）"
_DEGRADED = ("（LLM 暂时不可用，已降级）", "主 Agent 综合未生成，以下为各子 Agent 的实际产出汇总")

_MIN_LEN = 80          # 少于这个长度不可能构成可交付内容
_HINT_LIMIT = 3        # 提示条数上限，避免把评审提示淹掉

# 带度量单位的数字（只收「记录型」单位：距离/配速/心率/负荷；不收组次重量这类计划参数）
_METRIC_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(km|公里|千米|bpm|次/分|分/km|分/公里|配速|TRIMP)"
)
_UNIT_NORM = {"千米": "km", "公里": "km", "分/公里": "分/km"}

# 必备段落（按任务类型）：命中任务关键词时检查产出里至少出现两个段落词
_SECTION_RULES = (
    (("周报", "报告", "总结", "汇总", "复盘", "回顾"),
     ("概览", "数据", "问题", "建议", "下周", "结论")),
    (("计划", "方案", "安排", "课表"),
     ("动作", "组", "次", "频", "周", "热身")),
)


def check(task: str, output: str, upstream: dict = None) -> dict:
    """检查产出，返回 {"blocking": [...], "hints": [...]}。

    upstream：{步骤id: 产出文本}——用于数字出处核对（只对真实产出的步骤取并集）。
    """
    text = (output or "").strip()
    blocking, hints = [], []

    # ---------- blocking：机械性缺陷 ----------
    if not text:
        blocking.append("产出为空")
    else:
        if _SENTINEL in text:
            blocking.append("产出为模型空串兜底文案（未真正生成）")
        for marker in _DEGRADED:
            if marker in text:
                blocking.append(f"产出命中降级文案：{marker}")
        if len(text) < _MIN_LEN:
            blocking.append(f"产出过短（{len(text)} 字 < {_MIN_LEN}），不足以交付")

    if blocking:                      # 已经明确不过，不必再猜
        return {"blocking": blocking, "hints": []}

    # ---------- hints：段落完整性 ----------
    for task_kw, section_kw in _SECTION_RULES:
        if any(k in task for k in task_kw):
            missing = [s for s in section_kw if s not in text]
            if len(missing) >= len(section_kw) - 1:
                hints.append(f"疑似缺段落：{task_kw[0]}类产出通常需要"
                             f"{'/'.join(section_kw)}，当前几乎都没出现")
            break

    # ---------- hints：数字出处 ----------
    if upstream:
        material = "\n".join(v for v in upstream.values() if v)
        if material:
            seen = set()
            for m in _METRIC_RE.finditer(text):
                raw_num, unit = m.group(1), m.group(2)
                unit = _UNIT_NORM.get(unit, unit)
                key = f"{raw_num}{unit}"
                if key in seen or raw_num in material:
                    continue
                seen.add(key)
                hints.append(f"数字待核对：{key} 未在本轮材料中出现，可能编造")
                if len(seen) >= _HINT_LIMIT:
                    break

    return {"blocking": blocking, "hints": hints[:_HINT_LIMIT]}


def format_issues(report: dict) -> str:
    """把规则检查结果转成评审协议文本（第一行 ISSUES，供 _review_failed 识别）。"""
    lines = ["ISSUES（规则检查）"]
    lines += [f"- {b}" for b in report.get("blocking", [])]
    lines += [f"- {h}" for h in report.get("hints", [])]
    return "\n".join(lines)
