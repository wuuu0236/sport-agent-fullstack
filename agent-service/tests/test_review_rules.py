"""评审第一层（规则检查）测试 —— 方案 P1-1。

这一层的价值全在「**判据可复现**」上，所以测试也必须钉住边界：

1. blocking 只在「机械性缺陷」上成立（空/哨兵/降级/过短）——判错会把好产出打回；
2. hints（缺段落、数字无出处）**永远不 blocking**——历史上有过评审误报把正确产出
   判死的教训，凡有疑义的规则只提示、不裁决；
3. blocking 成立时必须短路，不再去猜 hints（省 token 且结论单一）。
"""
from src import review_rules
from src.graph import _review_failed

GOOD_REPORT = """本周训练概览：共完成 4 次训练，累计跑量 23.5 km，平均配速 5:42 分/km，
力量训练 2 次。数据显示跑量比上周增加 12%，问题在于周三强度课配速掉到 6:10（心率偏高）。
建议下周把间歇课挪到周二，先做 10 分钟动态热身。下周目标跑量 26 km，结论：负荷可再加 5%。"""


def _check(task="帮我生成周报", out=GOOD_REPORT, upstream=None):
    return review_rules.check(task, out, upstream or {})


class TestBlocking:
    def test_empty_output_blocks(self):
        rep = _check(out="   ")
        assert any("产出为空" in b for b in rep["blocking"])

    def test_sentinel_blocks(self):
        rep = _check(out="（模型本次未生成内容）")
        assert any("兜底文案" in b for b in rep["blocking"])

    def test_degraded_marker_blocks(self):
        rep = _check(out="（LLM 暂时不可用，已降级）" + "内容" * 60)
        assert any("降级文案" in b for b in rep["blocking"])

    def test_too_short_blocks(self):
        rep = _check(out="跑了 5 公里")
        assert any("过短" in b for b in rep["blocking"])

    def test_blocking_short_circuits_hints(self):
        """已明确不过就不再猜——结论单一，也省一次字符串扫描。"""
        rep = _check(out="（模型本次未生成内容）")
        assert rep["hints"] == []

    def test_good_report_passes(self):
        assert _check()["blocking"] == []


class TestHints:
    def test_missing_sections_hinted_for_report(self):
        # 通篇只有「概览」，周报该有的数据/问题/建议/下周全缺
        rep = _check(out="本周训练概览：一切正常，继续保持。" + "状态稳定。" * 15)
        assert any("疑似缺段落" in h for h in rep["hints"])

    def test_metric_absent_from_upstream_hinted(self):
        upstream = {"s1": "本周跑量 23.5 km，平均配速 5:42 分/km。"}
        rep = _check(out=GOOD_REPORT + "\n另外你还跑了 88 km 的长距离。", upstream=upstream)
        assert any("88" in h and "待核对" in h for h in rep["hints"])

    def test_metric_present_in_upstream_not_hinted(self):
        upstream = {"s1": "本周跑量 23.5 km"}
        rep = _check(out=GOOD_REPORT, upstream=upstream)
        assert not any("23.5" in h for h in rep["hints"])

    def test_hints_are_capped(self):
        upstream = {"s1": "材料里没有数字"}
        noisy = GOOD_REPORT + "\n" + "、".join(f"{i}公里" for i in range(90, 100))
        rep = _check(out=noisy, upstream=upstream)
        assert len(rep["hints"]) <= review_rules._HINT_LIMIT

    def test_plan_task_without_upstream_has_no_number_hint(self):
        """计划类产出（8 周 / 4 组 / 80kg）天然带数字，没有上游材料时不该乱标。"""
        rep = _check(task="给我排个 8 周增肌计划",
                     out="第 1-4 周：每周 3 练，隔天一次，保证充足睡眠。"
                         "A 日卧推 4 组 8 次，重量 80kg，组间休息 2 分钟；"
                         "B 日划船 4 组 10 次，重量 60kg；C 日深蹲 5 组 5 次，重量 90kg。"
                         "每次训练前热身 10 分钟。每周总容量增加 2.5kg。")
        assert not any("待核对" in h for h in rep["hints"])


class TestFormatIssues:
    def test_first_line_is_issues_for_gate(self):
        """format_issues 的输出必须能被评审闸门识别为「不过」。"""
        text = review_rules.format_issues({"blocking": ["产出为空"], "hints": []})
        assert text.startswith("ISSUES")
        assert _review_failed(text) is True

    def test_lists_every_item(self):
        text = review_rules.format_issues({"blocking": ["甲"], "hints": ["乙", "丙"]})
        assert "甲" in text and "乙" in text and "丙" in text
