"""文件导入解析器回归测试：GPX / CSV / OCR 规则兜底。

这些是纯函数、零 LLM 依赖，是导入链路「真落库」前的最后一道门，
解析错 = 脏数据进训练库，值得优先覆盖。
"""
import pytest

from src.importers import parse_csv, parse_gpx
from src.server import _rule_parse_ocr


class TestParseCsv:
    def test_run_rows(self):
        csv = (
            "日期,类型,距离,时长,平均心率,最大心率,配速,rpe\n"
            "2026-08-01,跑步,5,30,150,172,6,7\n"
            "2026-08-02,跑步,10,60,155,175,,\n"
        )
        recs = parse_csv(csv)
        assert len(recs) == 2
        r = recs[0]
        assert r["type"] == "run"
        assert r["date"] == "2026-08-01"
        assert r["distance_km"] == 5.0
        assert r["duration_min"] == 30.0
        assert r["avg_hr"] == 150
        assert r["rpe"] == 7
        assert recs[1]["rpe"] == 0  # 空单元格容忍

    def test_strength_rows(self):
        csv = (
            "日期,动作,组数,次数,重量\n"
            "2026-08-01,深蹲,4,8,80\n"
        )
        recs = parse_csv(csv)
        assert len(recs) == 1
        assert recs[0]["type"] == "strength"
        ex = recs[0]["exercises"][0]
        assert ex == {"name": "深蹲", "sets": 4, "reps": 8, "weight_kg": 80.0}

    def test_mixed_type_column(self):
        csv = (
            "date,type,distance_km,duration_min\n"
            "2026-08-01,力量,,\n"
        )
        recs = parse_csv(csv)
        assert recs[0]["type"] == "strength"

    def test_no_header_raises(self):
        with pytest.raises(ValueError):
            parse_csv("")

    def test_blank_rows_skipped(self):
        csv = (
            "date,distance_km,duration_min\n"
            "2026-08-01,5,30\n"
            ",,\n"
        )
        assert len(parse_csv(csv)) == 1


class TestParseGpx:
    GPX = """<?xml version="1.0" encoding="UTF-8"?>
    <gpx version="1.0" creator="Huawei">
      <trk>
        <extensions><totalDistance>5920</totalDistance><totalTime>2120</totalTime></extensions>
        <trkseg>
          <trkpt lat="30.00" lon="120.00"><time>2026-06-25T07:30:00Z</time></trkpt>
          <trkpt lat="30.01" lon="120.01"><time>2026-06-25T08:05:20Z</time></trkpt>
        </trkseg>
      </trk>
    </gpx>"""

    def test_summary_fields_preferred(self):
        rec = parse_gpx(self.GPX)
        # 优先用 <extensions> 官方汇总：5920m -> 5.92km，2120s -> ~35.3min
        assert rec["distance_km"] == 5.92
        assert abs(rec["duration_min"] - 2120 / 60.0) < 0.1
        assert rec["date"] == "2026-06-25"
        assert rec["type"] == "run"

    def test_no_hr_is_honest(self):
        # 华为轨迹 GPX 不含心率：必须如实标记 has_hr=False，绝不编造
        rec = parse_gpx(self.GPX)
        assert rec["hr_series"] == []
        assert rec["has_hr"] is False
        assert rec["avg_hr"] == 0

    def test_no_points_raises(self):
        with pytest.raises(ValueError):
            parse_gpx('<gpx version="1.0"><trk></trk></gpx>')


class TestRuleParseOcr:
    def test_run_fields(self):
        text = "2026年8月9日\n5.92 公里\n时长47\n平均心率149\n最大心率178\n配速7'55"
        d = _rule_parse_ocr(text)
        assert d["type"] == "run"
        assert d["date"] == "2026-08-09"
        assert d["distance_km"] == 5.92
        assert d["duration_min"] == 47.0
        assert d["avg_hr"] == 149
        assert d["max_hr"] == 178
        # 7'55" -> 7 + 55/60 ≈ 7.92 分/km
        assert abs(d["pace_min_km"] - (7 + 55 / 60)) < 0.01

    def test_strength_lines(self):
        text = "深蹲4组×8次×80kg\n卧推3组×10次×60kg"
        d = _rule_parse_ocr(text)
        assert d["type"] == "strength"
        assert len(d["exercises"]) == 2
        assert d["exercises"][0]["name"] == "深蹲"
        assert d["exercises"][0]["weight_kg"] == 80.0

    def test_strength_without_x_separator(self):
        # 回归：正则原本只认「4组8次80kg」，带 × 的整行匹配不上
        d = _rule_parse_ocr("深蹲4组8次80kg")
        assert d["type"] == "strength"
        assert d["exercises"] == [{"name": "深蹲", "sets": 4, "reps": 8, "weight_kg": 80.0}]

    def test_unknown_when_nothing_matches(self):
        d = _rule_parse_ocr("今天天气不错")
        assert d["type"] == "unknown"

    def test_hhmmss_duration(self):
        d = _rule_parse_ocr("运动时间: 00:47:22\n5公里")
        # 47min22s ≈ 47.37
        assert abs(d["duration_min"] - (47 + 22 / 60)) < 0.01
