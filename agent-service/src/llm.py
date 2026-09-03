"""LLM 调用层：OpenAI 兼容 chat/completions，无 key 时返回 mock 占位。

容错策略（2026-08-20 优化）：
- 网络/5xx 瞬时错误：指数退避重试（默认 3 次），避免偶发抖动直接把英文异常抛给用户；
- 4xx（401 鉴权 / 400 参数 / 429 配额）不重试，直接降级——重试无意义且浪费配额；
- 全部失败后降级为人类可读的提示，不再把原始异常堆栈甩给用户。
"""
import json
import time
import urllib.request
from urllib.error import HTTPError, URLError
from . import config

# 重试参数
_MAX_RETRIES = 3
_BASE_DELAY_S = 0.6


def _should_retry(exc: Exception) -> bool:
    """判断错误是否值得重试：5xx 服务端错误 / 网络错误可重试；4xx 不重试。

    注意：HTTPError 是 URLError 的子类，必须先判 HTTPError（有明确状态码），
    否则 4xx 会被当成纯网络错误误重试。
    """
    if isinstance(exc, HTTPError):
        return 500 <= exc.code < 600
    if isinstance(exc, (URLError, TimeoutError)):
        return True
    return False


def _log_usage(data: dict):
    """打印每次真实调用的 token 用量，重点看上下文缓存命中（DeepSeek 默认开启、
    命中部分约 1/10 计费）。usage 字段名随模型/版本变化，这里整段打印便于核对。"""
    try:
        u = (data or {}).get("usage")
        if u:
            print(f"[LLM usage] {u}", flush=True)
    except Exception:  # noqa: BLE001
        pass


def _post_json(url: str, payload: dict, timeout: int = 60) -> dict:
    """带重试的 POST JSON，返回解析后的响应 dict。"""
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {config.CONFIG.LLM_API_KEY}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                _log_usage(data)
                return data
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if not _should_retry(e) or attempt >= _MAX_RETRIES:
                break
            time.sleep(_BASE_DELAY_S * (2 ** attempt))
    # 失败时抛统一异常（不在这里拼英文堆栈）
    if isinstance(last_exc, HTTPError):
        raise RuntimeError(f"LLM 接口返回 HTTP {last_exc.code}")
    raise RuntimeError("LLM 接口请求失败（网络异常）")


def chat(messages, model=None, temperature=0.7, max_tokens=2048, thinking="disabled"):
    """messages: [{"role":"system"|"user"|"assistant", "content": "..."}]

    thinking：DeepSeek V4 思考模式开关（"disabled" / "enabled"），默认关闭。
    默认关闭的原因（2026-08-30 实测）：V4 默认 enabled + high 强度，链式推理会把
    max_tokens 额度全部耗在 reasoning 上，导致最终回答为空（表现为"模型本次未生成内容"）。
    教练直答/任务拆解这类场景不需要深度链式推理，关闭后响应更快、更省、且必定有输出。
    确需深度推理的调用点可显式传 thinking="enabled"（记得同步调大 max_tokens）。
    """
    if config.CONFIG.mock_mode:
        return _mock_chat(messages)
    url = config.CONFIG.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": model or config.CONFIG.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": {"type": thinking},
    }
    try:
        data = _post_json(url, payload)
        return data["choices"][0]["message"]["content"].strip()
    except Exception:  # noqa: BLE001
        return ("（LLM 暂时不可用，已降级）请稍后再试，或检查 .env 中的 "
                "LLM_API_KEY / LLM_BASE_URL 配置。")


def _mock_chat(messages):
    last = messages[-1]["content"] if messages else ""
    return (
        "[MOCK 模式 · 未配置 LLM_API_KEY]\n"
        f"已收到你的消息：「{last}」\n"
        "配置 .env 中的 LLM_API_KEY 后即可由真实大模型生成回答。"
    )


def vision(prompt, image_b64, mime="image/png", model=None, max_tokens=1024):
    """多模态：图文一起发给支持视觉的模型（DeepSeek V4-Flash/Pro 原生支持）。
    image_b64: 图片 base64 字符串（不含 data URI 前缀）；mime: 如 image/png。
    """
    if config.CONFIG.mock_mode:
        return _mock_vision(prompt)
    url = config.CONFIG.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
    ]
    payload = {
        "model": model or config.CONFIG.LLM_MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
    }
    try:
        data = _post_json(url, payload)
        return data["choices"][0]["message"]["content"].strip()
    except Exception:  # noqa: BLE001
        return ("（视觉识别暂时不可用，已降级）请稍后再试，或检查 .env 中的 "
                "LLM_API_KEY / 模型是否支持视觉。")


def _mock_vision(prompt):
    return (
        "[MOCK 模式 · 未配置 LLM_API_KEY]\n"
        f"已收到图片 + 指令：「{prompt}」\n"
        "配置 .env 的 LLM_API_KEY（需支持视觉的模型，如 deepseek-v4-flash）"
        "后即可由真实多模态模型识别图片中的训练数据。"
    )
