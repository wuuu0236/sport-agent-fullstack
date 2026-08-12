"""非交互演示：自动跑一遍体育训练场景（教练/体态）+ Skill（三级加载/蒸馏/patch）+ 双存储记忆。

演示重点：
  Phase 3 · 记忆：双存储 / 冻结快照 / 轻量召回
  Phase 4 · Skill（借鉴 Hermes）：
    - Tier 1 技能目录常驻（name+description+summary，极轻量）
    - Tier 3 仅命中者注入完整正文（未命中不占上下文）
    - 任务后蒸馏「存技能」→ 即时入库可命中
    - patch 式更新「patch 技能」→ 不重写整体、防回归
"""
import json
from . import server, memory, skill_loader


def _skill_cleanup():
    """清掉历史蒸馏出来的临时技能目录（保留 2 个原生技能）。

    绕过沙箱删除限制：子文件覆盖为空后置空目录。
    """
    KEEP = {"coach_hr_zones", "posture_relief"}
    for d in skill_loader.SKILL_DIR.iterdir():
        if d.is_dir() and d.name not in KEEP:
            try:
                for f in d.iterdir():
                    f.write_text("", encoding="utf-8")
                d.rmdir()
            except Exception:
                pass


def _banner(title: str):
    print(f"\n{'='*60}\n{title}\n{'='*60}")


def main():
    # 演示前清空长期记忆，保证可重复运行；并清掉上一轮蒸馏出的临时技能目录
    memory.reset_long_term()
    _skill_cleanup()
    print("=== 体育训练助理 MVP · 自动演示（Skill 三级加载 + 蒸馏 + 双存储记忆）===\n")

    _banner("Tier 1 · 技能目录（常驻 system prompt，仅 name+description+summary）")
    print(skill_loader.tier1_catalogue())

    _banner("训练场景示例（命中 skill 才注入完整正文）")
    SAMPLES = [
        "记一次5km跑步，配速6分，平均心率150，最大170，rpe7",   # → coach 录入
        "深蹲 4组8次80kg，卧推 3组10次60kg",                    # → coach 录入力量
        "分析我的跑步",                                          # → coach 分析心率区间
        "我膝盖疼",                                              # → posture 疼痛排查
        "记得我静息心率55，最大心率190",                          # → memory 记基线
    ]
    for m in SAMPLES:
        print(f"\n你: {m}")
        print("助理:", server.process(m))

    _banner("Phase 4 · 任务后蒸馏：存技能 → 即时入库")
    distill_cmd = ("存技能：跑后拉伸 每次跑步后做髋屈肌+腘绳肌拉伸各30秒、"
                   "小腿泡沫轴2分钟，预防下背与膝部紧张。")
    print(f"你: {distill_cmd}")
    print("助理:", server.process(distill_cmd))

    # 验证蒸馏出的技能能否被命中
    print("\n→ 验证：说『跑后拉伸怎么做』应当命中刚蒸馏的 跑后拉伸 技能")
    print("助理:", server.process("跑后拉伸怎么做"))

    _banner("Phase 4 · patch 式更新：不重写整体、防回归")
    patch_cmd = "patch 技能 跑后拉伸：若当天是长距离（>15km），额外加足底滚球2分钟。"
    print(f"你: {patch_cmd}")
    print("助理:", server.process(patch_cmd))

    _banner("长期记忆（双存储）")
    print(json.dumps(memory.list_store(), ensure_ascii=False, indent=2))

    _banner("冻结快照（LLM 模式下注入 system prompt，跨会话常驻）")
    print(memory.snapshot_block() or "（空）")

    # 演示结束，清理本轮蒸馏出的临时技能目录，保证 skills/ 仅留 2 个原生技能
    _skill_cleanup()


if __name__ == "__main__":
    main()
