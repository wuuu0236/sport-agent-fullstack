"""技能（Skill）匹配回归测试。

锁两类回归：
1. 触发词跨技能唯一——同一个词挂在两个技能上会让解析 SOP 和分析 SOP 同时注入，
   模型只能自己权衡（多命中无仲裁，与 f7559d6 的「技能 vs 人格冲突」同类）。
   2026-09-07 修：「配速」同时挂在 run_log_parse 与 coach_hr_zones。
2. 典型消息的命中集合稳定——避免改触发词时把别的场景改坏。
"""
from src.skill_loader import load_skills, match_skills


def _names(msg):
    return [s["name"] for s in match_skills(msg)]


def test_triggers_unique_across_skills():
    """同一触发词不允许出现在两个技能里（防止多命中串味）。"""
    owner = {}
    for s in load_skills(force=True):
        for t in s.get("triggers", []):
            t = str(t).strip().lower()
            if not t:
                continue
            assert t not in owner, (
                f"触发词 {t!r} 同时属于 {owner[t]} 和 {s['name']}，"
                "多命中会把两套 SOP 一起注入且无仲裁"
            )
            owner[t] = s["name"]


def test_pace_query_hits_only_analysis_skill():
    """纯配速咨询：只该进心率分析 SOP，不该进解析入库 SOP。"""
    assert _names("我最近配速掉到6分了怎么办") == ["coach_hr_zones"]


def test_run_log_still_hits_parse_skill():
    """删掉「配速」后，跑步记录类消息仍要命中解析技能。"""
    assert "run_log_parse" in _names("记一次5公里跑步")
    assert "run_log_parse" in _names("今天跑了8公里")


def test_pain_query_hits_posture_skill():
    assert _names("我膝盖疼还能跑吗") == ["posture_relief"]
