"""体态修复专家 Agent：疼痛排查、体态评估、康复动作、就医红线。"""
from .base import BaseAgent
from .. import config, llm

_RELIEF = {
    "膝盖": ("跑步膝 / 髌股疼痛", [
        "靠墙静蹲 3×30s（股四头强化）",
        "直腿抬高 3×15（髌骨轨迹稳定）",
        "泡沫轴放松大腿外侧髂胫束",
        "减少下坡与硬地跑量，跑鞋加缓冲",
    ]),
    "下背": ("下背酸 / 腰肌紧张", [
        "猫牛式 10 次（脊柱活动）",
        "死虫式核心激活 3×12",
        "婴儿式放松 30s",
        "避免久坐，每小时起身走动",
    ]),
    "圆肩": ("上交叉综合征 / 圆肩", [
        "胸椎伸展 10 次",
        "弹力带肩外旋 3×15（强化后链）",
        "收下巴训练（颈深屈肌）",
        "办公每 1h 做扩胸+沉肩",
    ]),
    "足底": ("足底筋膜炎", [
        "踩网球滚动足底 2min",
        "小腿腓肠肌拉伸 3×30s",
        "足弓抓毛巾 3×15",
        "换缓冲跑鞋，避免赤脚硬地",
    ]),
}
_RED = ["剧烈疼痛伴肿胀", "麻木 / 放射痛到腿", "休息 3 天无缓解",
        "关节明显红肿热", "外伤后无法负重"]


class PostureAgent(BaseAgent):
    name = "posture"
    description = "体态修复专家：跑步膝/下背酸/圆肩等疼痛排查、康复动作、就医红线"

    def handle(self, msg: str, ctx=None) -> str:
        # 确定性知识库优先（mock / 真实模式一致：康复动作与红线是招牌，不能靠 LLM 自由发挥）
        hit = None
        for k in _RELIEF:
            if k in msg:
                hit = k
                break
        if hit:
            name, acts = _RELIEF[hit]
            red = "、".join(_RED[:3])
            result = (f"可能：{name}\n居家康复：\n" +
                      "\n".join(f"· {a}" for a in acts) +
                      f"\n\n⚠️ 就医红线（出现任一项立即停训就医）：{red} 等。")
            if not config.CONFIG.mock_mode:
                try:
                    tip = llm.chat(
                        [{"role": "system", "content":
                          "你是体态修复专家。基于下面的康复建议，只用一句话给补充提醒，"
                          "务必完整通顺、不要重复已知内容、不要使用 Markdown 标题、强调不替代诊断。"},
                         {"role": "user", "content": result}],
                        max_tokens=80, temperature=0.3,
                    )
                    if tip and not tip.startswith("[LLM"):
                        result = result + "\n\n💡 " + tip
                except Exception:
                    pass
            return result
        # 未识别部位：真实模式用 LLM 通用建议，mock 给引导语
        if config.CONFIG.mock_mode:
            return ("请描述具体不适部位（如膝盖、下背、圆肩、足底），"
                    "我帮你排查原因并给居家康复动作。\n"
                    "⚠️ 我不做诊断，严重请就医。")
        return self._llm(self._build_prompt(msg), ctx=ctx or {})

    @staticmethod
    def _build_prompt(msg):
        red = "、".join(_RED)
        return (f"用户消息：{msg}\n"
                f"你是体态修复专家，给出：①可能诱因 ②3-4 个居家康复动作 "
                f"③明确就医红线（{red}）。强调不替代诊断。")
