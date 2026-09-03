"""配置加载：读取 .env（OpenAI 兼容接口），无 key 时自动进入 mock 模式。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env(path=None):
    env = {}
    p = path or (BASE_DIR / ".env")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_env = load_env()


class _Config:
    # OpenAI 兼容接口（默认 DeepSeek，可换成 Qwen / OpenAI / 任意兼容服务）
    LLM_API_KEY = _env.get("LLM_API_KEY", "")
    LLM_BASE_URL = _env.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_MODEL = _env.get("LLM_MODEL", "deepseek-chat")

    # 记忆持久化（受 Hermes 双存储启发：USER.md 关于用户 / MEMORY.md 助理笔记）
    MEMORY_DIR = BASE_DIR / "data"
    USER_FILE = MEMORY_DIR / "USER.md"        # 关于用户的事实/偏好/身份
    MEMORY_FILE = MEMORY_DIR / "MEMORY.md"    # 助理自己的笔记/约定/技巧
    SESSION_FILE = MEMORY_DIR / "session.json"  # 短期会话（最近 N 条）

    # HTTP 服务（PORT 可被环境变量覆盖，便于避开被占用的端口）
    HOST = os.environ.get("HOST") or _env.get("HOST", "127.0.0.1")
    PORT = int(os.environ.get("PORT") or _env.get("PORT", "8000"))

    # 微信（iLink Bot API）适配：仅用于 /wechat 回包里的 to_user_id 校验占位，
    # 真正的 iLink token 由持有它的网关（Hermes/HermesClaw）保管，不在 MVP 内核。
    WECHAT_ACCOUNT_ID = _env.get("WECHAT_ACCOUNT_ID", "")

    # 联网搜索（research Agent）：配置 Tavily key 后走真实网页搜索；
    # 未配置时自动降级为免费维基百科兜底，再不行就诚实告知未联网。
    TAVILY_API_KEY = _env.get("TAVILY_API_KEY", "")

    # 服务鉴权：非空时所有端点（除 /health）要求请求头 X-Agent-Token 匹配。
    # 留空 = 关闭鉴权（纯本机开发模式）。调用方（Spring 网关 / Vite 代理）
    # 需在各自配置里带同一个 token。防的是「浏览器里任意网页打 localhost 接口」
    # 与「DNS rebinding」，以及容器化后裸奔在局域网。
    AGENT_AUTH_TOKEN = _env.get("AGENT_AUTH_TOKEN", "")

    @property
    def mock_mode(self) -> bool:
        return not bool(self.LLM_API_KEY)


CONFIG = _Config()
