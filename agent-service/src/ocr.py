"""图片导入：本地 OCR 把运动截图读成文字，再交给 LLM 解析成结构化数据。

为什么这样走（而不直接让 DeepSeek 看图片）：
- DeepSeek 标准端点（api.deepseek.com/v1）实测不收 image_url（v4-flash/v4-pro/chat
  均返回 400），所以图片不能直传。
- 改为「本地 OCR → 纯文字 → DeepSeek」：OCR 在本地跑（rapidocr-onnxruntime，
  支持中英文，模型随包下载，不上传图片），DeepSeek 只收到文字，天然不报错。
- 隐私：截图不离开本机；只有 OCR 出来的文字片段发给大模型。

适用：华为/Keep/佳明/苹果健身等「训练小结」截图（含距离/平均心率/最大心率/配速
等数字的汇总卡）。注意：纯心率曲线图无数字，OCR 提取不到数值，此时建议用 GPX。
"""
import base64
import io


def _ensure_engine():
    """懒加载 OCR 引擎，避免未安装时影响其它功能。返回 engine 或抛出明确异常。"""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "未安装本地 OCR 引擎（rapidocr-onnxruntime）。\n"
            "请先运行：python -m pip install rapidocr-onnxruntime\n"
            f"原始错误：{e}"
        )
    return RapidOCR()


def ocr_image(b64: str, mime: str = "image/png") -> str:
    """把 base64 图片做 OCR，返回按阅读顺序拼接的纯文本。

    返回空字符串表示未识别到任何文字（例如纯曲线图）。
    """
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return ""
    try:
        from PIL import Image
        import numpy as np
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"缺少图像依赖（Pillow/numpy）：{e}")

    img = Image.open(io.BytesIO(raw)).convert("RGB")
    arr = np.array(img)

    engine = _ensure_engine()
    # RapidOCR 接受 numpy 数组；返回 ([[box, text, score], ...], 耗时) 或 (None, None)
    out = engine(arr)
    boxes = out[0] if isinstance(out, (list, tuple)) and out else None
    if not boxes:
        return ""

    # 按阅读顺序排：先按中心点 y（行），再按 x（列）
    rows = []
    for item in boxes:
        # 兼容两种返回格式：[box, text, score] 或 [box, score, text]
        if len(item) < 3:
            continue
        box, a, b = item[0], item[1], item[2]
        if isinstance(a, str):
            text, score = a, b
        else:
            score, text = a, b
        if not isinstance(text, str) or not text:
            continue
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 1.0
        if score < 0.4:
            continue
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        rows.append((sum(ys) / len(ys), sum(xs) / len(xs), text))
    rows.sort(key=lambda r: (r[0] // 30, r[1]))  # 30px 内视为同一行
    return "\n".join(t for _, _, t in rows)


def parse_import_text(text: str) -> dict:
    """把 OCR 出来的文字交给 LLM，提取结构化训练数据。

    返回 {type, date, ...} 或 {type:'unknown', raw:text}。
    仅在非 mock 模式调用（mock 模式直接在 server 层走规则解析）。
    """
    from . import llm
    prompt = (
        "下面是从一张「运动 App 训练记录截图」OCR 出来的零散文字，"
        "请从中提取结构化训练数据，只输出一个 JSON 对象，不要多余解释。\n\n"
        "规则：\n"
        "1. 如果内容像一次跑步/骑行/有氧（含距离、时长、配速、心率等），"
        "type 填 \"run\"，提取 date(YYYY-MM-DD)、distance_km(number)、"
        "duration_min(number, 分)、avg_hr(number)、max_hr(number)、"
        "pace_min_km(number, 配速 分/公里，如 6分30秒 写 6.5)、rpe(number, 主观疲劳 0-10)。\n"
        "2. 如果内容像一次力量训练（含动作、组数、次数、重量），"
        "type 填 \"strength\"，提取 date，及 exercises 数组，"
        "每个元素 {name, sets, reps, weight_kg}。\n"
        "3. 数字识别可能有误（如 150 被认成 159），请按常识修正明显错误。"
        "无法确认的字段填 0 或空字符串。\n"
        "4. 若文字里没有任何可识别的运动数据，返回 {\"type\":\"unknown\"}。\n\n"
        f"OCR 文字：\n{text}"
    )
    try:
        raw = llm.chat([{"role": "user", "content": prompt}], max_tokens=900, temperature=0.2)
    except Exception:
        return {"type": "unknown", "raw": text}
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1:
        return {"type": "unknown", "raw": text}
    import json
    try:
        data = json.loads(s[start:end + 1])
        data.setdefault("raw", text)
        return data
    except Exception:
        return {"type": "unknown", "raw": text}
