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
import re

# 布局配对参数（华为运动健康等「左右两列、标签在值上方」的训练截图布局）
# 实测（2026-08，华为户外跑步小结 1080x2414）：标签与正下方数值 cy 差约 70~80px；
# tab 栏标签（轨迹/配速/图表/详情）与下方时间戳 cy 差约 146px —— 用 110 阈值排除误配。
_COL_TOL = 180    # 标签与值中心 x 的最大列偏差（两列中心相距约 470px，不会跨列误配）
_ROW_GAP = 110    # 标签正下方取值的最大行距
_DIGIT_RE = re.compile(r"\d")
# 度量单位短词：可与邻近数值块合并（5.92 + 公里 → 5.92 公里），避免数字与单位被拆两行
_UNIT_WORDS = {"公里", "千米", "米", "厘米", "千卡", "卡", "分钟", "小时", "秒", "步"}


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
    """把 base64 图片做 OCR，返回结构化文本。

    不再按行平铺：华为/Keep 等截图是「左右两列」布局，纯文本行拼接会把右列内容
    插进左列标签与数值之间（实测『平均心率』后接『步数』，心率值 149 被挤到远处，
    正则/LLM 取不到数字）。这里保留每个识别块的坐标，把标签与最近的数值块
    空间配对，输出『平均心率: 149次/分钟』这种可直接解析的文本。
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

    blocks = []
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
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        blocks.append({
            "cx": sum(xs) / len(xs),
            "cy": sum(ys) / len(ys),
            "text": text,
        })
    if not blocks:
        return ""
    return _assemble(blocks)


def _assemble(blocks: list) -> str:
    """按坐标把「标签块」与最近的「数值块」配对成 '标签: 值'，再按阅读顺序输出。

    步骤：
      1. 单位词并入邻近数值块（5.92 + 公里 → 5.92 公里）；
      2. 标签（无数字块）→ 找最近的数值块：优先「正下方」（cx 同列、cy 在下且 < _ROW_GAP），
         其次「同行右邻」（cy 同行、cx 在右且 < _COL_TOL）；
      3. 未配对的数值块/标签按原样输出；整体按 (行, 列) 排序。
    """
    digit_blocks = [b for b in blocks if _DIGIT_RE.search(b["text"])]
    text_blocks = [b for b in blocks if not _DIGIT_RE.search(b["text"])]

    # 1) 单位词并入最近的邻近数值块
    units = [b for b in text_blocks if b["text"] in _UNIT_WORDS]
    labels = [b for b in text_blocks if b["text"] not in _UNIT_WORDS]
    used_units = set()
    for u in units:
        best_i, best_d = None, 1e18
        for i, v in enumerate(digit_blocks):
            if abs(v["cy"] - u["cy"]) <= 60 and abs(v["cx"] - u["cx"]) <= 300:
                d = abs(v["cy"] - u["cy"]) + abs(v["cx"] - u["cx"]) * 0.5
                if d < best_d:
                    best_i, best_d = i, d
        if best_i is not None:
            v = digit_blocks[best_i]
            digit_blocks[best_i] = {**v, "text": f"{v['text']} {u['text']}"}
            used_units.add(id(u))
    leftover_units = [u for u in units if id(u) not in used_units]

    # 2) 标签 → 最近数值块配对
    used_digits = set()
    lines = []
    for lb in sorted(labels + leftover_units, key=lambda b: (b["cy"], b["cx"])):
        best_i, best_d = None, 1e18
        for i, v in enumerate(digit_blocks):
            if i in used_digits:
                continue
            dx = v["cx"] - lb["cx"]
            dy = v["cy"] - lb["cy"]
            if abs(dy) <= 40 and 0 < dx <= _COL_TOL:        # 同行右邻
                d = dx * 0.5 + abs(dy)
            elif abs(dx) <= _COL_TOL and 0 < dy <= _ROW_GAP:  # 正下方
                # x 偏差权重要高（*2）：同列优先——否则 y 略近但 x 偏远的干扰块
                # （如孤立的 88）会抢走真正同列的值（如 167步/分钟）
                d = dy + abs(dx) * 2
            else:
                continue
            if d < best_d:
                best_i, best_d = i, d
        if best_i is not None:
            used_digits.add(best_i)
            v = digit_blocks[best_i]
            lines.append((lb["cy"], lb["cx"], f"{lb['text']}: {v['text']}"))
        else:
            lines.append((lb["cy"], lb["cx"], lb["text"]))

    # 3) 未配对的数值块原样输出
    for i, v in enumerate(digit_blocks):
        if i not in used_digits:
            lines.append((v["cy"], v["cx"], v["text"]))

    # 按阅读顺序：先按行（30px 内视为同一行），同行再按列
    lines.sort(key=lambda t: (t[0] // 30, t[1]))
    return "\n".join(t for _, _, t in lines)


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
