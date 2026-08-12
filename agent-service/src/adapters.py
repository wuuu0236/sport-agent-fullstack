"""消息入口适配器：provider-agnostic，对齐 Hermes gateway 平台的抽象。

设计动机（对齐 Hermes gateway/platforms/base.py 的 BasePlatformAdapter）：
- 你的 MVP 现在只跑 CLI/HTTP，但要证明「可扩展架构」，必须把「消息从哪来」
  和「agent 怎么处理」解耦。MessageAdapter 就是这条边界。
- WeChatAdapter 严格按腾讯 iLink Bot API 的契约收/发（读自 Hermes 的
  gateway/platforms/weixin.py，不是手搓），保证 MVP 能坐到 Hermes/HermesClaw
  后面当「大脑」，由持有 iLink token 的网关负责真正把消息发到微信。

诚实边界：
- 本文件只做「iLink 消息格式 ↔ MVP 内部文本」的适配，不实现二维码登录 /
  长轮询 getupdates / AES-128-ECB 媒体解密——那些是 Hermes 网关在扛（私有协议），
  不在 MVP 的零依赖内核里。MVP 负责「懂微信消息长什么样」，不负责「连微信」。
"""
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

# 注意：process 定义在 server.py，而 server 又导入本适配器，直接顶层
# 导入会循环引用。改为在 receive() 内延迟导入（调用时才触发）。
def _process(text: str) -> str:
    from .server import process  # noqa: PLC0415
    return process(text)


class MessageAdapter(ABC):
    """统一消息入口抽象。receive(raw) 接收平台原始消息，返回出站回包。"""

    name = "base"

    @abstractmethod
    def receive(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        ...


class CLIAdapter(MessageAdapter):
    """本地命令行交互。raw = {"text": "..."}。"""

    name = "cli"

    def receive(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        text = (raw.get("text") or "").strip()
        reply = _process(text)
        return {"text": reply}


class WeChatAdapter(MessageAdapter):
    """微信（iLink Bot API）适配器，契约对齐 Hermes weixin.py。

    入站（微信→MVP）：iLink getupdates 返回的单个 msg 对象，结构：
        {"item_list":[{"type":1,"text_item":{"text":"..."}}],
         "from_user_id":"...", "context_token":"..."}
    出站（MVP→网关）：iLink sendmessage 的 message 对象，结构：
        {"from_user_id":"","to_user_id":"...","client_id":"...",
         "message_type":2,"message_state":2,
         "item_list":[{"type":1,"text_item":{"text":"回复"}}],
         "context_token":"..."}
    注：持有 iLink token 的网关（Hermes/HermesClaw）拿到本回包后，
    自行 POST 到 iLink sendmessage 完成真正的微信下发。
    """

    name = "wechat"
    ITEM_TEXT = 1          # 对齐 weixin.ITEM_TEXT
    MSG_TYPE_BOT = 2       # 对齐 weixin.MSG_TYPE_BOT
    MSG_STATE_FINISH = 2   # 对齐 weixin.MSG_STATE_FINISH

    def __init__(self, account_id: str = ""):
        self.account_id = account_id

    @staticmethod
    def parse_inbound(raw: Dict[str, Any]) -> Optional[str]:
        """从 iLink 消息结构取用户文本（逻辑对齐 weixin._extract_text）。"""
        item_list = raw.get("item_list") or []
        for item in item_list:
            if item.get("type") == WeChatAdapter.ITEM_TEXT:
                text = (item.get("text_item") or {}).get("text") or ""
                if text:
                    return str(text).strip()
        # 兼容纯文本快捷测试（非 iLink 包装）
        if raw.get("text"):
            return str(raw["text"]).strip()
        return None

    def receive(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        # iLink 把单个 msg 包在 {"msg": {...}} 或直接给 msg；两种都兼容
        msg = raw.get("msg") if isinstance(raw.get("msg"), dict) else raw
        text = self.parse_inbound(msg)
        if not text:
            return {"reply_text": "", "reply_msg": None}
        reply = _process(text)
        to = str(msg.get("from_user_id") or "").strip()
        ctx_token = str(msg.get("context_token") or "").strip()
        return {
            "reply_text": reply,
            "reply_msg": self._build_outbound(to, reply, ctx_token),
        }

    @classmethod
    def _build_outbound(cls, to: str, text: str, context_token: str = "") -> Dict[str, Any]:
        """生成 iLink sendmessage 的 message 对象（对齐 weixin._send_message）。"""
        message: Dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": to,
            "client_id": f"mvp-wechat-{uuid.uuid4().hex}",
            "message_type": cls.MSG_TYPE_BOT,
            "message_state": cls.MSG_STATE_FINISH,
            "item_list": [{"type": cls.ITEM_TEXT, "text_item": {"text": text}}],
        }
        if context_token:
            message["context_token"] = context_token
        return message
