"""教练人格分层回归测试（方案 P1-3，2026-09-16）。

锁三条不变式——每一条都对应一个「静默失效」的风险点，不是形式主义：

1. **人格层不可被自进化写入**：`存技能` / `patch 技能` 的落盘目标只有 `skills/`，
   `PERSONA_CORE` 必须一个字节都不变。这是「LLM 自进化不会把人格改跑偏」的**结构保证**，
   没有这条测试，将来某次顺手改动就可能给它开出一条回写路径。
2. **知识层每次运行都注入**：对话路径经基类 Tier 3 注入；结构化路径（记录/分析）唯一由
   LLM 生成的是「补一句建议」，也必须带上知识层——此前那处直连 `llm.chat` 绕过基类，
   导致「patch 技能 → 下次就能用到新知识」在记录/分析路径上**完全无效**（P1-3 实测发现）。
3. **技能目录缓存热更新**：`存技能` 后目录必须刷新。此前 `_get_catalogue()` 一旦算过就
   永久复用（`_invalidate_catalogue()` 定义了但无人调用），新技能永远不出现在目录里。

测试会把 `SKILL_DIR` 指向临时副本——本文件会真的执行 `patch_skill` / `distill_skill`
（要覆盖真实写盘路径），不能碰仓库里的真技能文件。
"""
import shutil

import pytest

from src import config, memory, skill_loader
from src.agents import base as base_mod
from src.agents.coach_agent import CoachAgent
from src.skill_loader import distill_skill, load_skills, match_skills_for, patch_skill

SENTINEL = "Z5 判定补充：心率持续超 90% 且无法维持对话时判为 Z5。"


def _sys(messages) -> str:
    """取一次 llm.chat 调用里的 system prompt。"""
    return next((m["content"] for m in messages if m.get("role") == "system"), "")


@pytest.fixture
def tmp_skills(tmp_path, monkeypatch):
    """技能目录指向临时副本，避免测试改写仓库里的真 SKILL.md。"""
    dst = tmp_path / "skills"
    shutil.copytree(skill_loader.SKILL_DIR, dst)
    monkeypatch.setattr(skill_loader, "SKILL_DIR", dst)
    monkeypatch.setattr(skill_loader, "_CACHE", None)
    skill_loader.load_skills(force=True)
    # 目录缓存也重置，让每个用例都从"没算过"的状态起步
    monkeypatch.setattr(base_mod, "_CATALOGUE_CACHE", None)
    monkeypatch.setattr(base_mod, "_CATALOGUE_VERSION", -1)
    return dst


@pytest.fixture
def chat_spy(tmp_path, monkeypatch):
    """桩掉 llm.chat 并记录入参；同时隔离记忆库、强制非 mock 模式。

    强制非 mock 是必须的：`mock_mode` 取决于有没有 LLM_API_KEY，测试机不配 key 时
    补建议路径会被跳过，用例就变成了"什么都没验证的绿"。
    """
    monkeypatch.setattr(config.CONFIG, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(config.CONFIG, "MEMORY_DB", tmp_path / "memory.db")
    monkeypatch.setattr(memory, "_initialized", False)
    from src.agents import coach_agent as coach_mod
    calls = []

    def fake_chat(messages, **kwargs):
        calls.append(list(messages))
        return "一句建议"

    monkeypatch.setattr(coach_mod.llm, "chat", fake_chat)
    return calls


class TestPersonaLayer:
    def test_system_prompt_is_the_same_object_as_persona_core(self):
        """基类/直出路径读的 system_prompt 必须就是人格层本身，不能是复制出来的字符串。"""
        assert CoachAgent.system_prompt is CoachAgent.PERSONA_CORE

    def test_persona_core_holds_all_skeleton_sections(self):
        """人格骨架的五块必须齐全（身份/核心原则/动作铁律/表达风格/边界）。"""
        core = CoachAgent.PERSONA_CORE
        for section in ("【身份】", "【核心原则", "【动作铁律", "【表达风格】", "【边界】"):
            assert section in core, f"人格层缺了 {section}"

    def test_persona_core_does_not_contain_skill_sop(self):
        """人格层里不能掺进技能正文——知识归 skills/、人格归代码，混了就是分层失效。"""
        core = CoachAgent.PERSONA_CORE
        for s in load_skills(force=True):
            body = (s.get("body") or "").strip()
            if len(body) > 40:  # 跳过空/过短正文，避免假命中
                assert body[:40] not in core, f"{s['name']} 的 SOP 正文混进了人格层"

    def test_persona_core_immutable_by_patch(self, tmp_skills):
        """核心不变式：patch 知识层不改人格层一个字节。"""
        before = CoachAgent.PERSONA_CORE
        result = patch_skill(f"patch 技能 coach_hr_zones：{SENTINEL}")
        assert "已对技能" in result, result
        assert CoachAgent.PERSONA_CORE == before, "patch 技能污染了人格层"


class TestKnowledgeLayer:
    def test_hits_trigger_when_ctx_absent(self):
        """调用方没给 ctx 时就地按触发词算——注入不依赖调用方自觉。"""
        names = [s["name"] for s in CoachAgent._knowledge("心率区间是什么意思")]
        assert names == ["coach_hr_zones"]

    def test_ctx_skills_take_priority(self):
        """调用方（app/graph）已预筛过就直接用，不重复扫盘。"""
        sentinel = [{"name": "x", "body": "y", "triggers": []}]
        assert CoachAgent._knowledge("随便什么", {"skills": sentinel}) is sentinel

    def test_explicit_empty_ctx_skills_are_respected(self):
        """调用方明确给空列表 = 本轮不注入，不能自作主张补算。"""
        assert CoachAgent._knowledge("心率区间是什么意思", {"skills": []}) == []

    def test_knowledge_layer_is_injected_on_chat_path(self, tmp_skills, chat_spy):
        """对话路径：patch 过的新知识要出现在交给模型的 system prompt 里。"""
        patch_skill(f"patch 技能 coach_hr_zones：{SENTINEL}")
        chat_spy.clear()
        CoachAgent().handle("心率区间是什么意思")  # 概念问法 → 走 chat
        assert chat_spy, "对话路径没有调用 llm.chat"
        assert any(SENTINEL in _sys(m) for m in chat_spy), (
            "知识层没进对话路径的 system prompt，patch 出的新知识对 coach 不可见"
        )

    def test_knowledge_layer_is_injected_on_structured_path(self, tmp_skills, chat_spy):
        """结构化路径：记录/分析的正文是确定性代码算的，唯一 LLM 生成的只有「补一句建议」，
        知识层必须也注入那里——否则 patch 的技能对记录/分析路径完全无效。"""
        patch_skill(f"patch 技能 coach_hr_zones：{SENTINEL}")
        chat_spy.clear()
        out = CoachAgent().handle("我的心率区间是多少")  # 数据问法 → 走分析（结构化）
        assert "💡" in out, f"补建议没走上桩函数，实际输出：{out[:80]}"
        assert any(SENTINEL in _sys(m) for m in chat_spy), (
            "知识层没进「补一句建议」的 system prompt"
        )

    def test_tip_failure_does_not_break_main_result(self, tmp_skills, monkeypatch):
        """补建议是可选增强：它炸了也绝不能影响结构化主结果。"""
        from src.agents import coach_agent as coach_mod

        def boom(messages, **kwargs):
            raise RuntimeError("LLM 挂了")

        monkeypatch.setattr(coach_mod.llm, "chat", boom)
        monkeypatch.setattr(config.CONFIG, "LLM_API_KEY", "test-key")
        out = CoachAgent().handle("我的心率区间是多少")
        assert out.strip(), "补建议抛异常后主结果丢了"
        assert "💡" not in out


class TestCatalogueHotReload:
    def test_distilled_skill_appears_in_catalogue(self, tmp_skills):
        """`存技能` 后目录必须刷新：此前缓存一旦算过就永不更新，新技能对 LLM 不可见。"""
        before = base_mod._get_catalogue()
        assert "练后拉伸" not in before

        out = distill_skill("存技能：练后拉伸 练完必做：小腿、股四、胸小肌各 30 秒静态拉伸。")
        assert "已将" in out, out

        after = base_mod._get_catalogue()
        assert "练后拉伸" in after, "新蒸馏的技能没进目录"
        assert after is not before, "目录没重建，还在复用旧对象"

    def test_catalogue_survives_repeated_calls(self, tmp_skills):
        """目录本身仍要缓存（不能因为要热更新就每次重算，那就丢了缓存的意义）。"""
        first = base_mod._get_catalogue()
        assert base_mod._get_catalogue() is first

    def test_distilled_skill_reaches_coach(self, tmp_skills, chat_spy):
        """端到端：`存技能` → 下次对话 coach 就能用到（这正是 P1-3 要打通的路径）。"""
        distill_skill("存技能：练后拉伸 练完必做：小腿、股四、胸小肌各 30 秒静态拉伸。")
        chat_spy.clear()
        CoachAgent().handle("练后拉伸要注意什么")  # 概念问法 → 走 chat
        assert any("静态拉伸" in _sys(m) for m in chat_spy), (
            "刚蒸馏的知识没进 coach 的 prompt"
        )


class TestKnowledgeGating:
    def test_coach_still_absorbs_clinician_skill(self):
        """回归：分层重构不能把 coach 吸收 posture_relief 的白名单弄丢。"""
        names = [s["name"] for s in match_skills_for("我膝盖疼还能跑吗", "coach")]
        assert "posture_relief" in names
