"""消息入口：CLI 交互 + HTTP（可插拔，微信/飞书可选）。"""
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

from . import memory, supervisor, skill_loader
from . import config
from .sport_data import SportStore
from .importers import parse_gpx, parse_csv
from .ocr import ocr_image, parse_import_text
from .agents.coach_agent import _user_max_hr
from .agents.memory_agent import is_memory_intent
from .adapters import CLIAdapter, WeChatAdapter


# 多意图拆分用的连接词：句号/分号/换行 + 明确的递进连接词
_SPLIT_RE = re.compile(r"[。；;\n]|还有|顺便|另外|再来")


def _split_intents(user_msg: str) -> list:
    """把一条消息按连接词拆成多个意图段。每段要求≥2 字，避免拆出碎片。"""
    parts = re.split(_SPLIT_RE, user_msg)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) >= 2]


def _strip_meta(reply: str) -> str:
    """去掉 server 内部的路由标签（[agent] 前缀 + 技能 tag），存进会话的是自然对话文本。

    关键：LLM 上下文若含『[agent] 回复』这种格式，模型会模仿输出同样的标签
    （实测出现双 [research] 前缀、照抄记忆块）。历史必须干净。
    """
    s = (reply or "").strip()
    if s.startswith("["):
        j = s.find("] ")
        if j != -1:
            s = s[j + 2:]
    if "\n🔌 已启用技能：" in s:
        s = s.split("\n🔌 已启用技能：", 1)[0]
    return s.strip()


def process(user_msg: str) -> str:
    """端到端处理一条用户消息：路由 → skill 注入 → Agent → 记忆。

    多意图：一条消息含多件事（「记下膝盖疼,顺便查下周天气」）时拆开逐一处理，
    合并回复。元动作（记住/存技能/补丁）整体优先，不拆分——避免拆坏技能正文。
    """
    user_msg = (user_msg or "").strip()
    if not user_msg:
        return "（空消息）"
    memory.append_session("user", user_msg)

    # 技能蒸馏/补丁 有结构化正文（可能含句号），必须整体处理、不能拆分；
    # 记忆意图允许拆分——记忆事实很短，且常与其他意图并存（「记下X，顺便查Y」）。
    if (skill_loader.is_distill_intent(user_msg)
            or skill_loader.is_patch_intent(user_msg)):
        reply = _process_one(user_msg)
        memory.append_session("assistant", _strip_meta(reply))
        return reply

    segs = _split_intents(user_msg)
    if len(segs) > 1:
        replies = [_process_one(s) for s in segs]
        reply = "\n\n".join(r for r in replies if r)
        memory.append_session("assistant", _strip_meta(reply))
        return reply
    reply = _process_one(user_msg)
    memory.append_session("assistant", _strip_meta(reply))
    return reply


def _process_one(user_msg: str) -> str:
    """单条消息的完整链路：元动作 → 领域路由 → skill → Agent → 记忆。"""
    # 元动作（meta-action）优先级最高：记忆 / 技能蒸馏 / 技能补丁
    # —— 这类「关于系统本身」的指令要先于领域路由与 skill agent 覆盖判定。
    if is_memory_intent(user_msg):
        agent_name = "memory"
        agent = supervisor.get_agent(agent_name)
        return f"[{agent_name}] {agent.handle(user_msg)}"

    if skill_loader.is_distill_intent(user_msg):
        return f"[skill] {skill_loader.distill_skill(user_msg)}"

    if skill_loader.is_patch_intent(user_msg):
        return f"[skill] {skill_loader.patch_skill(user_msg)}"

    # —— 以下是常规领域路由 ——
    agent_name = supervisor.route(user_msg)
    hits = supervisor.detect_skills(user_msg)
    # 记忆已在上层拦截；此处仅处理领域 skill 的 agent 覆盖：
    # 命中 skill 声明的主理 agent（如 coach_hr_zones→coach）时渐进式覆盖路由。
    for s in hits:
        sa = s.get("agent")
        if sa and sa in supervisor.get_all_agents():
            agent_name = sa
            break
    agent = supervisor.get_agent(agent_name)
    ctx = {"skills": hits}
    reply = agent.handle(user_msg, ctx=ctx)
    # 空回复兜底：模型偶发返回空串时，绝不把「什么都没说」抛给用户
    if not (reply or "").strip():
        reply = ("抱歉，这个方向的回答暂时没生成出来。可以换个说法再问，"
                 "或明确告诉我你想做什么：记录训练/分析数据/联网搜索/写文案。")
    tag = f"\n🔌 已启用技能：{skill_loader.skill_names(hits)}" if hits else ""
    return f"[{agent_name}] {reply}{tag}"


def _state():
    """仪表盘数据源：身体基线 + 跑步心率区间 + 力量渐进趋势 + 最近训练。"""
    store = SportStore()
    max_hr = _user_max_hr()

    # 身体基线（USER.md 双存储 + MEMORY 笔记里的伤痛史）
    user_entries = memory.list_store("user") or []
    mem_entries = memory.list_store("memory") or []
    resting = None
    injuries = []
    for e in user_entries + mem_entries:
        m = re.search(r"静息心率[：:\s]*(\d+)", e)
        if m:
            resting = int(m.group(1))
        if any(k in e for k in ("伤", "痛", "膝盖", "下背", "圆肩", "足底", "康复", "椎间盘")):
            if e not in injuries:
                injuries.append(e)

    # 跑步记录 + 心率区间分布
    runs = []
    for r in store.runs():
        a = store.analyze_run(r, max_hr)
        runs.append({
            "date": r.get("date"),
            "distance_km": r.get("distance_km"),
            "duration_min": r.get("duration_min"),
            "avg_hr": r.get("avg_hr"),
            "max_hr": r.get("max_hr"),
            "rpe": r.get("rpe"),
            "pace_min_km": a["pace_min_km"],
            "load": a["load"],
            "zones": a["zones"],
        })

    # 力量渐进超负荷趋势（按动作聚合）
    ex_names = []
    for r in store.strengths():
        for ex in r.get("exercises", []):
            n = ex.get("name")
            if n and n not in ex_names:
                ex_names.append(n)
    strengths = []
    for name in ex_names:
        t = store.strength_trend(name)
        latest = t.get("latest") or {}
        strengths.append({
            "name": name,
            "trend": t["trend"],
            "delta_pct": t.get("delta_pct"),
            "samples": t["samples"],
            "latest_sets": latest.get("sets"),
            "latest_reps": latest.get("reps"),
            "latest_weight": latest.get("weight_kg"),
        })

    # 最近训练会话（按日期倒序）
    sessions = []
    for r in runs:
        sessions.append({"type": "run", "date": r["date"],
                         "summary": f"{r['distance_km']}km · 平均心率{r['avg_hr']} · 负荷{r['load']}"})
    for r in store.strengths():
        exs = "、".join(f"{e['name']}{e['sets']}×{e['reps']}×{e['weight_kg']}"
                        for e in r.get("exercises", []))
        sessions.append({"type": "strength", "date": r.get("date"), "summary": exs})
    sessions.sort(key=lambda x: x["date"] or "", reverse=True)

    return {
        "max_hr": max_hr,
        "resting_hr": resting,
        "injuries": injuries,
        "runs": runs,
        "strengths": strengths,
        "sessions": sessions[:12],
        "user_facts": user_entries,
        "mem_notes": mem_entries,
    }


def _rule_parse_ocr(text: str) -> dict:
    """规则兜底：从 OCR 文字里抓常见字段（mock 离线演示 + 真实模式 LLM 未接住时用）。

    兼容两种写法：中文标签（平均心率 / 最大心率 / 配速）+ 紧凑英文 token
    （avg_hr165 / max_hr178 / pace5.5 / rpe7），以及 公里km、组×次×kg 力量格式。
    """
    import re as _re
    d = {"type": "unknown", "date": "", "distance_km": 0, "duration_min": 0,
         "avg_hr": 0, "max_hr": 0, "pace_min_km": 0, "rpe": 0, "exercises": []}
    m = _re.search(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})", text)
    if m:
        d["date"] = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = _re.search(r"(\d+(?:\.\d+)?)\s*(?:km|公里|千米|KM)", text, _re.I)
    if m:
        d["distance_km"] = float(m.group(1))
    # 时长：兼容「时长28」「30分钟」「28:30(MM:SS)」「1:02:30(HH:MM:SS)」。
    # 不能把多个正则用 or 链合并后直接取组——match 对象只认「实际命中」那个正则的组，
    # 命中第一个正则时 m.group(2)/group(3) 不存在，会 IndexError。故分两步匹配。
    # 「运动时间: 00:47:22」走 MM:SS 分支且优先于全局 MM:SS，避免状态栏时间
    # （如 00:12:46）抢匹配导致时长取错。
    d["duration_min"] = 0.0
    m = (_re.search(r"时长[：:\s]*(\d+(?:\.\d+)?)", text)
         or _re.search(r"(\d+(?:\.\d+)?)\s*分钟?", text)
         or _re.search(r"用时[：:\s]*(\d+(?:\.\d+)?)", text))
    if m:
        d["duration_min"] = float(m.group(1))
    else:
        m = (_re.search(r"运动时间[：:\s]*(\d{1,2})[：:](\d{2})(?:[：:](\d{2}))?", text)
             or _re.search(r"(\d{1,2})[：:](\d{2})(?:[：:](\d{2}))?", text))  # MM:SS 或 HH:MM:SS
        if m:
            if m.group(3) is not None:  # HH:MM:SS
                d["duration_min"] = int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 60.0
            else:  # MM:SS
                d["duration_min"] = int(m.group(1)) + int(m.group(2)) / 60.0
    m = _re.search(r"平均心率[：:\s]*(\d+)", text) or _re.search(r"avg_?hr[：:\s]*(\d+)", text, _re.I)
    if m:
        d["avg_hr"] = int(m.group(1) or m.group(2))
    m = _re.search(r"最大心率[：:\s]*(\d+)", text) or _re.search(r"max_?hr[：:\s]*(\d+)", text, _re.I)
    if m:
        d["max_hr"] = int(m.group(1) or m.group(2))
    # 配速：兼容中文「配速6'30"」（分+秒）与英文「pace5.5」（小数）。
    # 同样分步匹配，避免 or 链合并后跨正则取组导致 IndexError。
    m = _re.search(r"配速[：:\s]*(\d+)[′'\"]?\s*(\d+)?", text)
    if m:
        d["pace_min_km"] = round(int(m.group(1)) + int(m.group(2) or 0) / 60.0, 2)
    else:
        m = _re.search(r"pace[：:\s]*(\d+(?:\.\d+)?)", text, _re.I)
        if m:
            d["pace_min_km"] = float(m.group(1))
    m = _re.search(r"rpe[：:\s]*(\d+)", text, _re.I) or _re.search(r"疲劳[：:\s]*(\d+)", text)
    if m:
        d["rpe"] = int(m.group(1) or m.group(2))
    for line in text.splitlines():
        m = _re.search(r"([一-龥A-Za-z]+)\s*(\d+)\s*[组×xX]\s*(\d+)\s*[次×xX]\s*(\d+(?:\.\d+)?)\s*kg", line)
        if m:
            d["exercises"].append({"name": m.group(1), "sets": int(m.group(2)),
                                   "reps": int(m.group(3)), "weight_kg": float(m.group(4))})
    if d["exercises"]:
        d["type"] = "strength"
    elif d["distance_km"] or any(k in text for k in ("跑步", "骑行", "有氧", "公里", "km", "run")):
        d["type"] = "run"
    return d


def image_import(image_b64, mime="image/png"):
    """图片导入：本地 OCR 读图 → 文字 → LLM 解析成结构化数据。

    DeepSeek 当前端点不收图片，故走「OCR→文字→LLM(text)」；截图不离开本机。
    返回 {ok, raw(ocr文字), data(结构化)}。data.type 为 unknown 表示未识别。
    """
    try:
        ocr_text = ocr_image(image_b64, mime)
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "raw": ""}
    if not ocr_text.strip():
        return {"ok": False, "error": "OCR 未识别到文字（纯曲线图或空白图片）", "raw": ""}
    if config.CONFIG.mock_mode:
        data = _rule_parse_ocr(ocr_text)
    else:
        data = parse_import_text(ocr_text)
        # 真实模式 LLM 偶发返回 unknown（如冷启动没接住），用规则兜底保证可用
        if (data or {}).get("type") == "unknown":
            data = _rule_parse_ocr(ocr_text)
    data = data or {}
    data.setdefault("note", "图片OCR导入")
    data.setdefault("type", "unknown")
    return {"ok": data.get("type") != "unknown", "raw": ocr_text, "data": data}


def _import_save(payload):
    """把导入解析出的结构化数据落库。payload 可为 {records:[...]} 或单条 {data:{...}}。

    支持 run 的逐拍 hr_series（GPX 提供）以算真实心率区间；cadence 仅作备注。
    """
    import datetime
    store = SportStore()
    records = payload.get("records")
    if records is None:
        single = payload.get("data")
        if single is None and isinstance(payload, dict) and "type" in payload:
            single = payload
        records = [single] if single else []
    saved = 0
    for d in records:
        if not d:
            continue
        t = d.get("type")
        date = d.get("date") or datetime.date.today().isoformat()
        try:
            if t == "run":
                dist = float(d.get("distance_km") or 0)
                dur = float(d.get("duration_min") or 0)
                # 有距离但时长为 0（OCR/LLM 未解析出）：按 6 分/km 估算，避免配速显示 0
                if dist > 0 and dur <= 0:
                    dur = round(dist * 6, 1)
                store.add_run(date, dist, dur,
                              int(d.get("avg_hr") or 0), int(d.get("max_hr") or 0),
                              hr_series=d.get("hr_series") or None,
                              rpe=int(d.get("rpe") or 0), note=d.get("note") or "文件导入")
                saved += 1
            elif t == "strength":
                exs = d.get("exercises") or []
                if exs:
                    store.add_strength(date, exs, note=d.get("note") or "文件导入")
                    saved += 1
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if saved:
        return {"ok": True, "msg": f"已保存 {saved} 条训练记录"}
    return {"ok": False, "error": "没有可保存的记录"}


def run_cli():
    mode = "MOCK 模式（未配置 LLM_API_KEY）" if config.CONFIG.mock_mode else f"LLM={config.CONFIG.LLM_MODEL}"
    print(f"=== 个人体育训练助理 MVP · {mode} ===")
    print("输入消息开始对话；输入 /exit 退出。\n")
    while True:
        try:
            u = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见 👋")
            break
        if not u:
            continue
        if u in ("/exit", "exit", "quit"):
            print("再见 👋")
            break
        print("助理:", process(u))


# 网页对话 + 训练仪表盘（GET / 返回；POST /chat 走 API；GET /state 供右侧面板）
_CHAT_HTML = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>体育训练助理</title>
<style>
  :root{ --bg:#eef1f6; --card:#fff; --pri:#2f6df0; --txt:#1f2430; --mut:#8a93a6; --bub:#eef3ff; --line:#e6eaf0; }
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--txt);height:100vh;display:flex;flex-direction:column}
header{padding:13px 18px;background:var(--card);border-bottom:1px solid var(--line);font-weight:600;display:flex;justify-content:space-between;align-items:center}
header .sub{font-weight:400;font-size:12px;color:var(--mut)}
#connStatus{font-size:12px;padding:2px 8px;border-radius:8px;display:inline-flex;align-items:center;gap:4px}
#connStatus.ok{background:#e3f6ec;color:#1e8e4e}
#connStatus.err{background:#fdecec;color:#c0392b}
#connStatus.wait{background:#fff4e5;color:#b9770e}
  .main{flex:1;display:flex;overflow:hidden}
  .left{flex:1 1 56%;display:flex;flex-direction:column;min-width:0;border-right:1px solid var(--line);background:var(--card)}
  .right{flex:1 1 44%;max-width:460px;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:14px}
  #log{flex:1;overflow:auto;padding:18px;display:flex;flex-direction:column;gap:12px}
  .msg{max-width:80%;padding:10px 13px;border-radius:14px;line-height:1.55;white-space:pre-wrap;word-break:break-word}
  .u{align-self:flex-end;background:var(--pri);color:#fff;border-bottom-right-radius:4px}
  .a{align-self:flex-start;background:var(--bub);border-bottom-left-radius:4px}
  .tag{color:var(--mut);font-size:11px;margin-bottom:3px}
  form{display:flex;gap:10px;padding:12px 16px;background:var(--card);border-top:1px solid var(--line)}
  input{flex:1;border:1px solid #d8dee9;border-radius:10px;padding:11px 13px;font-size:14px;outline:none}
  input:focus{border-color:var(--pri)}
  button{border:0;background:var(--pri);color:#fff;border-radius:10px;padding:0 18px;font-size:14px;cursor:pointer}
  button:disabled{opacity:.6}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
  .card h3{margin:0 0 11px;font-size:14px;display:flex;align-items:center;gap:7px;color:var(--txt)}
  .card h3 .ic{font-size:15px}
  .bgrid{display:flex;gap:10px}
  .kv{flex:1;background:#f5f7fa;border-radius:10px;padding:11px 8px;text-align:center}
  .kv .k{font-size:11px;color:var(--mut)}
  .kv .v{font-size:21px;font-weight:700;color:var(--pri);margin-top:3px}
  .bcap{font-size:12px;color:var(--mut);margin:11px 0 4px}
  .injury{font-size:12px;color:#c0392b;line-height:1.5}
  .cap{font-size:12px;color:var(--mut);margin-bottom:7px}
  .zonebar{display:flex;height:20px;border-radius:10px;overflow:hidden;margin:4px 0 10px}
  .seg{height:100%}
  .legend{display:flex;flex-direction:column;gap:5px}
  .lrow{display:flex;align-items:center;gap:7px;font-size:12px;color:#5b6577}
  .dot{width:11px;height:11px;border-radius:50%;flex:none}
  .pct{margin-left:auto;font-variant-numeric:tabular-nums;color:var(--txt);font-weight:600}
  .srow{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px dashed #eef1f6}
  .srow:last-child{border-bottom:0}
  .sname{flex:1;font-weight:600;font-size:13px;display:flex;align-items:center;gap:7px;flex-wrap:wrap}
  .stag{font-size:11px;padding:1px 8px;border-radius:10px}
  .stag.up{background:#e3f6ec;color:#1e8e4e}
  .stag.down{background:#fdecec;color:#c0392b}
  .stag.flat{background:#eef1f6;color:var(--mut)}
  .smeta{font-size:12px;color:#5b6577}
  .sdelta{font-size:12px;font-weight:700;color:#1e8e4e;min-width:46px;text-align:right}
  .xrow{display:flex;gap:9px;align-items:center;padding:8px 0;border-bottom:1px dashed #eef1f6}
  .xrow:last-child{border-bottom:0}
  .xic{font-size:16px}
  .xcol{flex:1;min-width:0}
  .xdate{font-size:11px;color:var(--mut)}
  .xsum{font-size:13px;color:var(--txt);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .empty{font-size:12px;color:var(--mut);text-align:center;padding:10px}
  .fact{font-size:12px;color:#1f2430;line-height:1.5;padding:3px 0;border-bottom:1px dashed #eef1f6}
  .fact:last-child{border-bottom:0}
  .recall{margin-top:10px;width:100%;background:#eef3ff;color:var(--pri);border:1px solid #d6e2ff;font-size:13px;padding:8px;border-radius:10px;cursor:pointer}
  .recall:hover{background:#e2ecff}
  #importBox{display:none;margin:10px 16px 0;background:#f5f7fa;border:1px solid var(--line);border-radius:12px;padding:12px 14px}
  .impjson{background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px;font-size:12px;white-space:pre-wrap;word-break:break-word;max-height:200px;overflow:auto;margin:8px 0;color:#1f2430}
  .improw{display:flex;gap:8px}
  button.ghost{background:#eef1f6;color:var(--mut)}
  .imp{background:#eef3ff;color:var(--pri);border:1px solid #d6e2ff;font-size:14px;padding:0 14px;border-radius:10px;cursor:pointer;display:inline-flex;align-items:center;gap:5px;font-weight:600}
  .imp:hover{background:#e2ecff}
  .filehide{position:absolute;width:1px;height:1px;opacity:0;left:-9999px;overflow:hidden}
  .drop{border:2px dashed #cdd6e4;border-radius:12px;padding:16px 12px;text-align:center;color:var(--mut);font-size:13px;margin:0 16px 10px;background:#fafbfd;transition:.15s}
  .drop.drag{border-color:var(--pri);background:#eef3ff;color:var(--pri)}
  .drop b{color:var(--pri)}
  #frameTip{display:none;background:#fff4e5;color:#b9770e;border-bottom:1px solid #ffe2b8;padding:9px 16px;font-size:13px;line-height:1.55}
  #frameTip code{background:#fff;padding:1px 6px;border-radius:5px;border:1px solid #ffe2b8}
  @media(max-width:820px){ .main{flex-direction:column} .left{border-right:0;border-bottom:1px solid var(--line)} .right{max-width:none} }
</style>
</head>
<body>
<header>🏃 个人体育训练助理 <span class="sub" id="mode"></span> <span id="connStatus" class="wait">⏳ 检测中</span></header>
<div id="frameTip"></div>
<div class="main">
  <div class="left">
    <div id="log"></div>
    <div id="importBox"></div>
    <div id="drop" class="drop">🖼️ 把训练截图<b>拖到这里</b>（或点 📷 上传图片）</div>
    <form id="f">
      <label class="imp" for="imgFile" title="从训练截图导入（本地 OCR 识别文字，图片不上传）">📷 上传图片</label>
      <input id="imgFile" type="file" accept="image/*" class="filehide">
      <input id="t" placeholder="与助理对话，或记一次训练（如：跑步5公里配速6分心率150）" autocomplete="off">
      <button id="b" type="submit">发送</button>
    </form>
    <div id="pasteBox" style="margin:0 16px 10px">
      <div class="cap">📝 文字录入：粘贴训练记录文本（如「8月1日跑步5公里配速6分心率150」，或 GPX / CSV 原文），点「解析文字」自动入库：</div>
      <textarea id="pasteArea" rows="3" placeholder="例如：2026-08-01,run,5,6,150" style="width:100%;box-sizing:border-box;border:1px solid #d8dee9;border-radius:10px;padding:9px;font-size:13px;resize:vertical"></textarea>
      <button id="pasteBtn" class="imp" type="button" style="margin-top:6px">解析文字</button>
    </div>
  </div>
  <div class="right">
    <div class="card"><h3><span class="ic">❤️</span>身体基线</h3><div id="baseline"></div></div>
    <div class="card"><h3><span class="ic">🧠</span>记忆（持久化）</h3><div id="memory"></div><button id="recall" class="recall">你记得我什么？</button></div>
    <div class="card"><h3><span class="ic">📊</span>心率区间（最近一次跑）</h3><div id="zones"></div></div>
    <div class="card"><h3><span class="ic">🏋️</span>力量渐进趋势</h3><div id="strength"></div></div>
    <div class="card"><h3><span class="ic">📅</span>最近训练</h3><div id="sessions"></div></div>
  </div>
</div>
<script>
const log=document.getElementById('log');
const ZONE_COLORS={"Z1恢复":"#bfe3cf","Z2有氧燃脂":"#8fd3c8","Z3有氧耐力":"#ffd58a","Z4无氧阈":"#ff9f6b","Z5最大":"#ff6b6b"};
const ZONE_ORDER=["Z1恢复","Z2有氧燃脂","Z3有氧耐力","Z4无氧阈","Z5最大"];
function el(tag,cls,text){const d=document.createElement(tag);if(cls)d.className=cls;if(text!=null)d.textContent=text;return d;}
function add(role,text,tag){
  const d=el('div','msg '+(role==='u'?'u':'a'));
  if(tag){d.appendChild(el('div','tag',tag));}
  d.appendChild(el('div',null,text));
  log.appendChild(d);log.scrollTop=log.scrollHeight;
}
function renderBaseline(s){
  const box=document.getElementById('baseline');box.innerHTML='';
  const grid=el('div','bgrid');
  const a=el('div','kv');a.appendChild(el('div','k','最大心率'));a.appendChild(el('div','v',s.max_hr?String(s.max_hr):'—'));
  const b=el('div','kv');b.appendChild(el('div','k','静息心率'));b.appendChild(el('div','v',s.resting_hr?String(s.resting_hr):'—'));
  grid.appendChild(a);grid.appendChild(b);box.appendChild(grid);
  if(s.injuries&&s.injuries.length){
    box.appendChild(el('div','bcap','伤痛 / 注意'));
    s.injuries.forEach(x=>box.appendChild(el('div','injury','· '+x)));
  }
}
function renderZones(s){
  const box=document.getElementById('zones');box.innerHTML='';
  const run=(s.runs||[]).slice(-1)[0];
  if(!run){box.appendChild(el('div','empty','暂无跑步记录'));return;}
  box.appendChild(el('div','cap',run.date+' · '+run.distance_km+'km · 配速'+run.pace_min_km+'分/km · 负荷'+run.load));
  const bar=el('div','zonebar');const legend=el('div','legend');
  ZONE_ORDER.forEach(z=>{
    const pct=(run.zones&&run.zones[z])||0;
    if(pct>0){
      const seg=el('div','seg');seg.style.width=pct+'%';seg.style.background=ZONE_COLORS[z];seg.title=z+' '+pct+'%';bar.appendChild(seg);
      const li=el('div','lrow');const dot=el('span','dot');dot.style.background=ZONE_COLORS[z];
      li.appendChild(dot);li.appendChild(el('span',null,z));li.appendChild(el('span','pct',pct+'%'));legend.appendChild(li);
    }
  });
  box.appendChild(bar);box.appendChild(legend);
}
function renderStrength(s){
  const box=document.getElementById('strength');box.innerHTML='';
  const arr=s.strengths||[];
  if(!arr.length){box.appendChild(el('div','empty','暂无力量记录'));return;}
  arr.forEach(t=>{
    const row=el('div','srow');
    const name=el('div','sname',t.name);
    const tag=el('span','stag '+(t.trend||''),(t.trend==='up'?'↑ 进步':(t.trend==='down'?'↓ 减载':'→ 持平')));
    name.appendChild(tag);
    row.appendChild(name);
    row.appendChild(el('div','smeta',(t.latest_sets||'?')+'×'+(t.latest_reps||'?')+'×'+(t.latest_weight||'?')+'kg'));
    if(t.samples>=2&&t.delta_pct!=null){row.appendChild(el('div','sdelta',(t.delta_pct>0?'+':'')+t.delta_pct+'%'));}
    box.appendChild(row);
  });
}
function renderSessions(s){
  const box=document.getElementById('sessions');box.innerHTML='';
  const arr=s.sessions||[];
  if(!arr.length){box.appendChild(el('div','empty','还没有训练记录'));return;}
  arr.forEach(x=>{
    const row=el('div','xrow');
    row.appendChild(el('span','xic',x.type==='run'?'🏃':'🏋'));
    const col=el('div','xcol');col.appendChild(el('div','xdate',x.date||''));col.appendChild(el('div','xsum',x.summary||''));
    row.appendChild(col);box.appendChild(row);
  });
}
function renderMemory(s){
  const box=document.getElementById('memory');box.innerHTML='';
  const uf=s.user_facts||[];const mf=s.mem_notes||[];
  if(!uf.length&&!mf.length){box.appendChild(el('div','empty','还没有记忆，试试「记得我静息心率55」'));return;}
  if(uf.length){box.appendChild(el('div','bcap','关于你'));uf.forEach(x=>box.appendChild(el('div','fact',x)));}
  if(mf.length){box.appendChild(el('div','bcap','助理笔记'));mf.forEach(x=>box.appendChild(el('div','fact',x)));}
}
function applyState(s){renderBaseline(s);renderZones(s);renderStrength(s);renderSessions(s);renderMemory(s);}
// API 基地址 + 连接状态检测
const API=(location.hostname==='localhost'||location.hostname==='127.0.0.1'||location.hostname==='[::1]')?'':'__API_BASE__';
const cs=document.getElementById('connStatus');
function setConn(st,text){cs.className=st;cs.textContent=text;}
async function checkConn(){
  try{
    const r=await fetch(API+'/health',{method:'GET',cache:'no-store'});
    const j=await r.json();
    document.getElementById('mode').textContent=j.mock?'（离线演示）':'（真实 LLM）';
    setConn('ok','✅ 已连接'+(j.mock?'(离线模式)':''));
  }catch(e){setConn('err','❌ 无法连接后端 — 请确认服务在运行');}
}
async function refresh(){try{const r=await fetch(API+'/state',{cache:'no-store'});const s=await r.json();applyState(s);setConn(cs.className.includes('err')?'err':'ok',cs.textContent);}catch(e){setConn('err','❌ 数据加载失败');}}
async function send(){
  const inp=document.getElementById('t');const btn=document.getElementById('b');
  const text=inp.value.trim();
  if(!text){add('a','💬 请先输入文字再发送哦','提示');return;}
  add('u',text);inp.value='';btn.disabled=true;setConn('wait','⏳ 发送中...');
  try{
    const r=await fetch(API+'/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})});
    const j=await r.json();const reply=j.reply||JSON.stringify(j);
    let tag='',body=reply;
    if(reply.startsWith('[')){const i=reply.indexOf('] ');if(i!==-1){tag=reply.slice(1,i);body=reply.slice(i+2);}}
    add('a',body,tag);
    checkConn();
  }catch(e){add('a','⚠️ 网络请求失败：'+e+'\\n请检查：1) 服务是否在运行 2) 地址是否为 http://127.0.0.1:8019','错误');setConn('err','❌ 请求失败')}
  btn.disabled=false;
}
// 环境检测：内置预览面板是受限 iframe，会拦截文件框与拖拽事件；提示用外部浏览器
if(window.self!==window.top){
  const ft=document.getElementById('frameTip');
  if(ft){ft.style.display='block';ft.style.background='#fff4e5';ft.style.color='#b9770e';ft.style.borderBottom='1px solid #ffe2b8';ft.innerHTML='⚠️ 你正在<b>内置预览面板</b>中，<b>图片上传与拖拽不可用</b>（面板会拦截文件事件）。请把地址 <code style="background:#fff;padding:1px 6px;border-radius:5px;border:1px solid #ffe2b8">http://localhost:8019</code> 复制到 <b>Edge / Chrome</b> 打开即可正常使用。也可直接用下方「📝 文字录入」粘贴文本入库。';}
}
document.getElementById('f').addEventListener('submit',e=>{e.preventDefault();send();});
document.getElementById('recall').addEventListener('click',()=>{document.getElementById('t').value='你记得我什么';send();});
function fileToB64(f){return new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(r.result.split(',')[1]);r.onerror=rej;r.readAsDataURL(f);});}
function toRecords(d){if(!d||d.type==='unknown')return [];if(d.type==='strength')return [d];return [d];}
const imgInput=document.getElementById('imgFile');
imgInput.addEventListener('change',e=>handleImageFile(e.target.files[0]));
const drop=document.getElementById('drop');
['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();e.stopPropagation();drop.classList.add('drag');}));
['dragleave','dragend'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('drag');}));
drop.addEventListener('drop',e=>{
  e.preventDefault();e.stopPropagation();drop.classList.remove('drag');
  let f=null;
  if(e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files.length){f=e.dataTransfer.files[0];}
  else if(e.dataTransfer&&e.dataTransfer.items){for(const it of e.dataTransfer.items){if(it.kind==='file'){f=it.getAsFile();if(f)break;}}}
  if(f)handleImageFile(f);
});
// Ctrl+V 粘贴图片兜底（真实浏览器可用）：从剪贴板取图片直接 OCR 入库
window.addEventListener('paste',e=>{
  const items=e.clipboardData&&e.clipboardData.items;
  if(!items)return;
  for(const it of items){
    if(it.kind==='file'&&/^image\//.test(it.type)){
      const f=it.getAsFile();
      if(f){handleImageFile(f);e.preventDefault();}
      break;
    }
  }
});
// 全局兜底：拖文件到页面任意处都不让浏览器跳转，交给上面的 drop 区处理
window.addEventListener('dragover',e=>{if(e.dataTransfer&&e.dataTransfer.types&&[].indexOf.call(e.dataTransfer.types,'Files')>-1)e.preventDefault();});
window.addEventListener('drop',e=>{if(e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files.length)e.preventDefault();});
window.addEventListener('error',e=>{const b=document.getElementById('frameTip');if(b){b.style.display='block';b.style.background='#ffe9e9';b.style.color='#c0392b';b.innerHTML='⚠️ 页面脚本出错：'+((e&&e.message)||e)+'。请复制 http://localhost:8019 到外部浏览器打开，或用下方「文字录入」粘贴文本。';}});
const pasteArea=document.getElementById('pasteArea');
const pasteBtn=document.getElementById('pasteBtn');
pasteBtn.addEventListener('click',async()=>{
  const text=(pasteArea.value||'').trim();if(!text){alert('请先粘贴文本');return;}
  const box=document.getElementById('importBox');box.style.display='block';box.innerHTML='';box.appendChild(el('div','cap','解析中...'));
  try{
    const r=await fetch(API+'/import_file',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:text,name:'pasted.txt'})});
    const j=await r.json();
    if(!j.ok){box.innerHTML='';box.appendChild(el('div','cap','识别失败：'+(j.error||'')));if(j.raw)box.appendChild(el('pre','impjson',j.raw));return;}
    pasteArea.value='';renderImportPreview(j.records);
  }catch(err){box.innerHTML='';box.appendChild(el('div','cap','请求失败：'+err));}
});
async function handleImageFile(f){
  if(!f)return;
  const box=document.getElementById('importBox');box.style.display='block';box.innerHTML='';
  box.appendChild(el('div','cap','📷 OCR 识别中：'+(f.name||'截图')));
  try{
    const b64=await fileToB64(f);
    const r=await fetch(API+'/import_image',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image:b64,mime:f.type||'image/png'})});
    const j=await r.json();
    if(!j.ok){box.innerHTML='';box.appendChild(el('div','cap','识别失败：'+(j.error||'')));if(j.raw)box.appendChild(el('pre','impjson','OCR 原文：\\n'+j.raw));return;}
    const recs=toRecords(j.data);
    if(!recs.length){box.innerHTML='';box.appendChild(el('div','cap','未从图中识别到结构化训练数据'));if(j.raw)box.appendChild(el('pre','impjson','OCR 原文：\\n'+j.raw));return;}
    renderImportPreview(recs,j.raw);
  }catch(err){box.innerHTML='';box.appendChild(el('div','cap','请求失败：'+err));}
  imgInput.value='';
}
function renderImportPreview(recs,raw){
  const box=document.getElementById('importBox');box.innerHTML='';
  box.appendChild(el('div','cap','📷 识别结果（'+recs.length+' 条，确认后入库）：'));
  box.appendChild(el('pre','impjson',JSON.stringify(recs,null,2)));
  if(raw){box.appendChild(el('div','cap','OCR 原文（供核对）：'));box.appendChild(el('pre','impjson',raw));}
  const row=el('div','improw');
  const ok=el('button',null,'确认入库');ok.type='button';
  ok.onclick=async()=>{
    const r=await fetch(API+'/import_save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({records:recs})});
    const j=await r.json();
    box.innerHTML='';box.appendChild(el('div','cap',(j.ok?('✅ '+j.msg):('❌ '+(j.error||'')))));
    refresh();setTimeout(()=>{box.style.display='none';},1600);
  };
  const cancel=el('button','ghost','取消');cancel.type='button';
  cancel.onclick=()=>{box.style.display='none';};
  row.appendChild(ok);row.appendChild(cancel);box.appendChild(row);
}
// 图片上传改用 <label for="imgFile"> 原生触发，不再依赖 JS .click()
checkConn();
refresh();
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    _cli = CLIAdapter()
    _wechat = WeChatAdapter(account_id=config.CONFIG.WECHAT_ACCOUNT_ID)

    def _respond(self, payload: dict):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        # /health 返回 JSON 健康检查；/state 返回仪表盘数据；其余返回网页界面
        if self.path.startswith("/health"):
            self._respond({"status": "ok", "msg": "sport-agent-mvp running", "mock": config.CONFIG.mock_mode})
            return
        if self.path.startswith("/state"):
            self._respond(_state())
            return
        html = _CHAT_HTML.replace("__API_BASE__", f"http://127.0.0.1:{config.CONFIG.PORT}")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}
        path = (self.path or "/").split("?")[0]
        if path == "/import_image":
            img = body.get("image") or ""
            mime = body.get("mime") or "image/png"
            if not img:
                self._respond({"ok": False, "error": "empty image"})
                return
            self._respond(image_import(img, mime))
            return
        if path == "/import_file":
            content = body.get("content") or ""
            name = (body.get("name") or "").lower()
            if not content.strip():
                self._respond({"ok": False, "error": "空文件"})
                return
            try:
                # 按扩展名或内容特征选择解析器
                if name.endswith(".csv") or ("," in content.splitlines()[0] if content.splitlines() else False):
                    recs = parse_csv(content)
                    fmt = "csv"
                else:
                    recs = [parse_gpx(content)]
                    fmt = "gpx"
            except Exception as e:
                self._respond({"ok": False, "error": str(e),
                               "raw": content[:400]})
                return
            summary = f"识别为 {fmt.upper()}，共 {len(recs)} 条记录"
            self._respond({"ok": True, "format": fmt, "records": recs, "summary": summary})
            return
        if path == "/import_save":
            self._respond(_import_save(body))
            return
        if path in ("/wechat", "/weixin"):
            # iLink Bot API 契约入站：吃 weixin.py 的 getupdates 单条 msg，
            # 出站回 iLink sendmessage 的 message 对象（由网关真正发微信）。
            out = self._wechat.receive(body)
            self._respond({"reply_msg": out["reply_msg"], "reply_text": out["reply_text"]})
        else:
            # 通用明文入口（/chat 或 /）：text/message/Content 字段兼容
            msg = body.get("message") or body.get("Content") or body.get("text") or ""
            reply = self._cli.receive({"text": msg}).get("text", "")
            self._respond({"reply": reply})


def run_server():
    httpd = ThreadingHTTPServer((config.CONFIG.HOST, config.CONFIG.PORT), _Handler)
    print(f"=== 个人体育训练助理 MVP HTTP 服务已启动 ===")
    print(f"健康检查: GET  http://{config.CONFIG.HOST}:{config.CONFIG.PORT}/health")
    print(f"仪表盘:   GET  http://{config.CONFIG.HOST}:{config.CONFIG.PORT}/")
    print(f"对话(明文): POST http://{config.CONFIG.HOST}:{config.CONFIG.PORT}/chat     {{\"message\":\"...\"}}")
    print(f"仪表盘数据: GET http://{config.CONFIG.HOST}:{config.CONFIG.PORT}/state")
    print(f"微信(iLink): POST http://{config.CONFIG.HOST}:{config.CONFIG.PORT}/wechat   {{iLink msg 包}}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")


if __name__ == "__main__":
    run_server()
