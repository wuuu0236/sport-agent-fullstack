"""训练文件导入：华为运动健康 GPX + 通用 CSV 解析。

GPX（华为运动健康「导出路线文件」）：
- 携带完整 GPS 轨迹、海拔，并在 <trk><extensions> 内给出 totalDistance /
  totalTime 权威汇总；本解析器优先用官方汇总值，距离与时长比手动录入稳。
- ⚠️ 实测关键结论（2026-08-09，用户真实样本 20260625户外跑步.gpx，GPX 1.0）：
  华为轨迹页导出的 GPX **不含逐拍心率**（trkpt 仅 ele+time）。心率仅存在于华为
  隐私中心「申请数据副本」的 JSON 导出。因此本解析器对心率如实标记 has_hr=False，
  绝不编造心率区间；真实心率需走 JSON 数据副本解析（待补），或走图片 OCR 导入。

图片 OCR 导入见 ocr.py（本地 rapidocr → 文字 → LLM 解析），用于训练小结截图。
"""
import csv
import io
import math
import datetime


# ---------------- GPX ----------------
def _local(tag: str) -> str:
    """从带命名空间的元素 tag 取 local-name，如 '{ns}trkpt' -> 'trkpt'。"""
    return tag.split("}")[-1] if "}" in tag else tag


def _haversine(lat1, lon1, lat2, lon2):
    """两经纬点间距离（km）。"""
    R = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


def _trk_summary(root):
    """读取 <trk><extensions> 内的权威汇总字段（命名空间无关）。

    华为 GPX 实测在扩展里给出 totalDistance(米) / totalTime(秒) 等，
    比从 GPS 点累加更准。返回 {lower_localname: value_text}。
    """
    summary = {}
    trk = next((e for e in root.iter() if _local(e.tag) == "trk"), None)
    if trk is None:
        return summary
    ext = next((e for e in trk.iter() if _local(e.tag) == "extensions"), None)
    if ext is None:
        return summary
    for c in ext.iter():
        if c is ext:
            continue
        if c.text and c.text.strip():
            summary[_local(c.tag).lower()] = c.text.strip()
    return summary


def parse_gpx(text: str) -> dict:
    """解析华为运动健康导出的 GPX，返回一条 run 记录。

    优先用 <trk><extensions> 内的 totalDistance / totalTime 官方汇总；
    距离/时长以官方值为准，GPS 累加仅作回退。心率：华为轨迹 GPX 实测不含，
    故 hr_series 为空、avg_hr=0，下游 analyze_run 会如实标记 has_hr=False。
    """
    import xml.etree.ElementTree as ET

    root = ET.fromstring(text)
    # 轨迹点优先 trkpt，回退 rtept（路线导出）
    pts = [e for e in root.iter() if _local(e.tag) in ("trkpt", "rtept")]
    if not pts:
        raise ValueError("未解析到轨迹点（trkpt/rtept）")

    parsed = []
    for tp in pts:
        lat = tp.get("lat")
        lon = tp.get("lon")
        if lat is None or lon is None:
            continue
        try:
            lat, lon = float(lat), float(lon)
        except ValueError:
            continue
        time = None
        for c in tp:
            lt = _local(c.tag)
            if lt == "time":
                time = (c.text or "").strip()
        parsed.append({"time": time})

    if not parsed:
        raise ValueError("轨迹点解析为空（缺少经纬度）")

    # 距离：优先官方汇总，否则 GPS 累计
    summary = _trk_summary(root)
    dist_km = 0.0
    if "totaldistance" in summary:
        try:
            dist_km = float(summary["totaldistance"]) / 1000.0
        except ValueError:
            dist_km = 0.0
    if dist_km <= 0:
        for i in range(1, len(pts)):
            a, b = pts[i - 1], pts[i]
            try:
                dist_km += _haversine(float(a.get("lat")), float(a.get("lon")),
                                      float(b.get("lat")), float(b.get("lon")))
            except (TypeError, ValueError):
                pass

    # 时长：优先官方汇总（秒），否则首末时间差
    dur_min = 0.0
    if "totaltime" in summary:
        try:
            dur_min = float(summary["totaltime"]) / 60.0
        except ValueError:
            dur_min = 0.0
    if dur_min <= 0:
        times = [p["time"] for p in parsed if p["time"]]
        if len(times) >= 2:
            try:
                t0 = datetime.datetime.fromisoformat(times[0].replace("Z", "+00:00"))
                t1 = datetime.datetime.fromisoformat(times[-1].replace("Z", "+00:00"))
                dur_min = max(0.0, (t1 - t0).total_seconds() / 60.0)
            except ValueError:
                dur_min = 0.0

    date = next((p["time"][:10] for p in parsed if p["time"]), "")
    pace = round(dur_min / dist_km, 2) if dist_km > 0 else 0.0

    # 华为轨迹 GPX 不含心率：如实标记
    return {
        "type": "run",
        "date": date,
        "distance_km": round(dist_km, 2),
        "duration_min": round(dur_min, 1),
        "avg_hr": 0,
        "max_hr": 0,
        "pace_min_km": pace,
        "rpe": 0,
        "hr_series": [],            # 华为轨迹 GPX 无逐拍心率
        "cadence": None,
        "note": "华为运动健康 GPX 导入",
        "has_hr": False,
    }


# ---------------- CSV ----------------
# 通用汇总表头映射（中英文、大小写/空格无关）
_RUN_HEADERS = {
    "date": ["date", "日期"],
    "type": ["type", "类型", "运动类型"],
    "distance_km": ["distance_km", "distance", "距离", "里程", "公里"],
    "duration_min": ["duration_min", "duration", "时长", "时间", "耗时", "分钟"],
    "avg_hr": ["avg_hr", "average_hr", "平均心率", "平均hr"],
    "max_hr": ["max_hr", "最大心率", "最大hr"],
    "pace_min_km": ["pace_min_km", "pace", "配速"],
    "rpe": ["rpe", "主观疲劳", "主观强度"],
}
_STR_HEADERS = {
    "date": ["date", "日期"],
    "name": ["name", "动作", "动作名", "项目"],
    "sets": ["sets", "组数", "组"],
    "reps": ["reps", "次数", "次", "rep"],
    "weight_kg": ["weight_kg", "weight", "重量", "kg", "负重", "负重kg"],
}
_TYPE_MAP = {"跑步": "run", "run": "run", "有氧": "run", "骑行": "run", "骑车": "run",
             "力量": "strength", "strength": "strength", "举铁": "strength", "撸铁": "strength"}


def _norm(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "")


def _map_headers(headers):
    """把原始表头映射到标准字段键，返回 {标准键: 原始列名}。"""
    out = {}
    for std, aliases in {**_RUN_HEADERS, **_STR_HEADERS}.items():
        for h in headers:
            if _norm(h) in [_norm(a) for a in aliases]:
                out[std] = h
                break
    return out


def _to_float(v, default=0.0):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def parse_csv(text: str):
    """解析通用训练汇总 CSV，返回 records 列表（run 与 strength 混合）。

    两种常见布局：
      - 跑步/有氧汇总：date,type,distance_km,duration_min,avg_hr,max_hr,pace,rpe
      - 力量动作：date,name,sets,reps,weight_kg
    """
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV 无表头")
    mapping = _map_headers(reader.fieldnames)
    has_name = "name" in mapping
    records = []
    for row in reader:
        if not any((row.get(c) or "").strip() for c in reader.fieldnames):
            continue  # 空行跳过
        if has_name:
            name = (row.get(mapping["name"]) or "").strip()
            if not name:
                continue
            records.append({
                "type": "strength",
                "date": (row.get(mapping.get("date", ""), "") or "").strip()[:10],
                "exercises": [{
                    "name": name,
                    "sets": int(_to_float(row.get(mapping["sets"], ""), 0)),
                    "reps": int(_to_float(row.get(mapping["reps"], ""), 0)),
                    "weight_kg": _to_float(row.get(mapping["weight_kg"], ""), 0),
                }],
                "note": "CSV 导入",
            })
        else:
            # 跑步/有氧汇总
            t = _TYPE_MAP.get((row.get(mapping.get("type", ""), "") or "").strip(), "run")
            rec = {
                "type": t,
                "date": (row.get(mapping.get("date", ""), "") or "").strip()[:10],
                "distance_km": _to_float(row.get(mapping.get("distance_km", ""), 0)),
                "duration_min": _to_float(row.get(mapping.get("duration_min", ""), 0)),
                "avg_hr": int(_to_float(row.get(mapping.get("avg_hr", ""), 0))),
                "max_hr": int(_to_float(row.get(mapping.get("max_hr", ""), 0))),
                "pace_min_km": _to_float(row.get(mapping.get("pace_min_km", ""), 0)),
                "rpe": int(_to_float(row.get(mapping.get("rpe", ""), 0))),
                "hr_series": [],
                "note": "CSV 导入",
            }
            records.append(rec)
    if not records:
        raise ValueError("未识别到有效训练行（检查表头：日期/距离/平均心率 或 动作/组数/次数/重量）")
    return records
