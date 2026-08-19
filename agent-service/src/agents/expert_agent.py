"""运动科学家 Agent：纯知识答疑（概念/原理），不碰数据、不写记录。

从 coach 拆出：只负责「解释运动科学概念」——心率区间、配速、恢复、
训练周期、力量渐进原理等。LLM 输出，但注入用户基线（最大心率）辅助回答更贴。
"""
from .base import BaseAgent
from .. import config
from .analyst_agent import user_max_hr


class ExpertAgent(BaseAgent):
    name = "expert"
    description = "运动科学知识问答：心率区间/配速/恢复/训练周期/力量原理"
    system_prompt = (
        "你是用户的运动科学专家，精通跑步训练、心率区间（Z1–Z5）、配速、"
        "训练负荷（TRIMP）、恢复、力量渐进超负荷、周期化训练等运动科学。\n"
        "用户问概念就好好解释概念，不要硬塞训练记录，也不要编造用户数据；"
        "解释要通俗、结构化、给可行动的原则。"
    )

    def handle(self, user_msg: str, ctx: dict = None) -> str:
        if config.CONFIG.mock_mode:
            return (
                "🎓 运动科学专家已收到请求。\n"
                f"· 你想了解：{user_msg}\n"
                "（离线演示：配置 LLM_API_KEY 后，这里会由大模型讲解运动科学原理。）"
            )
        # 注入用户基线（最大心率），让讲解能落到用户的真实区间
        mh = user_max_hr()
        prompt = (
            f"（用户基线参考：最大心率约 {mh}。仅作背景，不要编造其他用户数据。）\n"
            f"用户想了解：{user_msg}\n"
            "请以专业但通俗的口吻解释原理，结构化输出，末尾给 1 条可行动建议。"
        )
        return self._llm(prompt, ctx=ctx or {})
