# -*- coding: utf-8 -*-
"""生成品牌图标 favicon.ico：圆角方形品牌渐变底 + 白色哑铃。

为什么要有这个脚本（而不是直接塞一个 .ico 进仓库）：
  ico 是二进制 blob，改配色 / 改造型时没法 diff 也没法复现。这里把图标的"源码"
  固化下来，任何时候 `python frontend/scripts/gen-favicon.py` 都能重出一份完全
  一致的图标；这份 ico 同时被网页标签页和桌面快捷方式复用。

设计约定
  - 配色取自 frontend/src/styles/tokens.css 的 --accent #3d8bff / --accent-2 #2ad4c8
  - 整体压深一档（DEEPEN），否则白色哑铃压在亮青底上对比度不足、糊成一团
  - 16/24/32/48/64/128 用 BMP 变体（兼容性最好），256 用 PNG 压缩
    （Vista+ 标准做法，省掉 260KB 未压缩位图；全部 BMP 时总大小 372KB → 106KB）
  - 每像素 4x4 超采样，保证小尺寸下边缘不锯齿

只依赖标准库（struct / zlib），不需要 Pillow。
"""
import os
import struct
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ICO = os.path.normpath(os.path.join(HERE, "..", "public", "favicon.ico"))
PREVIEW = os.path.join(tempfile.gettempdir(), "wolf_preview.png")

BMP_SIZES = [16, 24, 32, 48, 64, 128]
PNG_SIZES = [256]
SS = 4  # 每像素 4x4 超采样

# ---- 品牌色 ----
DEEPEN = 0.84
C_TOP = tuple(int(round(v * DEEPEN)) for v in (0x3D, 0x8B, 0xFF))
C_BOT = tuple(int(round(v * DEEPEN)) for v in (0x2A, 0xD4, 0xC8))


def rr(x, y, x0, y0, x1, y1, r):
    """点 (x, y)（单位坐标 0..1）是否落在圆角矩形内"""
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= r * r


BG = (0.030, 0.030, 0.970, 0.970, 0.235)

# 哑铃 = 横杆 + 两侧内外配重片（彼此重叠，形成连贯剪影）
GLYPH = [
    (0.200, 0.452, 0.800, 0.548, 0.042),  # 横杆
    (0.252, 0.302, 0.350, 0.698, 0.042),  # 左内片
    (0.650, 0.302, 0.748, 0.698, 0.042),  # 右内片
    (0.136, 0.380, 0.228, 0.620, 0.036),  # 左外片
    (0.772, 0.380, 0.864, 0.620, 0.036),  # 右外片
]


def in_bg(x, y):
    return rr(x, y, *BG)


def in_glyph(x, y):
    return any(rr(x, y, *p) for p in GLYPH)


def grad(y):
    t = min(max((y - BG[1]) / (BG[3] - BG[1]), 0.0), 1.0)
    return tuple(int(round(C_TOP[i] + (C_BOT[i] - C_TOP[i]) * t)) for i in range(3))


_cache = {}


def render(size):
    """返回 size 行、每行 size*4 字节的 BGRA（自上而下）"""
    if size in _cache:
        return _cache[size]
    n = SS
    total = n * n
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            bg_hits = 0
            gl_hits = 0
            acc = [0.0, 0.0, 0.0]
            for sy in range(n):
                for sx in range(n):
                    x = (px + (sx + 0.5) / n) / size
                    y = (py + (sy + 0.5) / n) / size
                    if not in_bg(x, y):
                        continue
                    bg_hits += 1
                    c = grad(y)
                    acc[0] += c[0]
                    acc[1] += c[1]
                    acc[2] += c[2]
                    if in_glyph(x, y):
                        gl_hits += 1
            if bg_hits == 0:
                row += b"\x00\x00\x00\x00"
                continue
            base = [acc[i] / bg_hits for i in range(3)]
            k = gl_hits / total  # 白色哑铃按覆盖度混合
            col = [int(round(base[i] + (255 - base[i]) * k)) for i in range(3)]
            a = int(round(255 * bg_hits / total))
            row += bytes((col[2], col[1], col[0], a))
        rows.append(bytes(row))
    _cache[size] = rows
    return rows


def to_rgba(size):
    """render 给的是 BGRA，PNG 要 RGBA"""
    out = []
    for r in render(size):
        line = bytearray()
        for i in range(0, len(r), 4):
            line += bytes((r[i + 2], r[i + 1], r[i], r[i + 3]))
        out.append(bytes(line))
    return out


def png_chunk(tag, data):
    c = tag + data
    return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)


def make_png(w, h=None, rows_rgba=None):
    """正方形时 h 可省略（默认等于 w）；rows_rgba 省略时内部自行渲染"""
    if h is None:
        h = w
    if rows_rgba is None:
        rows_rgba = to_rgba(w)
    raw = b"".join(b"\x00" + r for r in rows_rgba)
    return (b"\x89PNG\r\n\x1a\n"
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(raw, 9))
            + png_chunk(b"IEND", b""))


def bmp_entry(size):
    """ICO 内的 BMP 变体：BITMAPINFOHEADER + 自下而上 BGRA + AND 掩码"""
    rows = render(size)
    xor = b"".join(reversed(rows))
    stride = ((size + 31) // 32) * 4
    and_mask = bytearray()
    for r in reversed(rows):
        line = bytearray(stride)
        for px in range(size):
            if r[px * 4 + 3] < 128:  # 全透明像素在 AND 掩码中置 1
                line[px // 8] |= 0x80 >> (px % 8)
        and_mask += bytes(line)
    hdr = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                      len(xor) + len(and_mask), 0, 0, 0, 0)
    return hdr + xor + bytes(and_mask)


def build_ico():
    entries = [(s, bmp_entry(s)) for s in BMP_SIZES]
    entries += [(s, make_png(s)) for s in PNG_SIZES]
    out = bytearray(struct.pack("<HHH", 0, 1, len(entries)))
    offset = 6 + 16 * len(entries)
    for s, blob in entries:
        dim = 0 if s >= 256 else s  # ICO 里 256 用 0 表示
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    for _, blob in entries:
        out += blob
    return bytes(out)


def preview():
    """导出 64px 原尺寸 + 放大版，便于人眼复核边缘与造型"""
    real256 = os.path.join(os.path.dirname(PREVIEW), "wolf_preview_256.png")
    open(real256, "wb").write(make_png(256))
    rows = to_rgba(64)
    big, k = 256, 4
    zoom = []
    for y in range(big):
        src = rows[y // k]
        line = bytearray()
        for x in range(big):
            line += src[(x // k) * 4:(x // k) * 4 + 4]
        zoom.append(bytes(line))
    big_path = os.path.join(os.path.dirname(PREVIEW), "wolf_preview_zoom.png")
    open(big_path, "wb").write(make_png(big, big, zoom))
    print("preview:", real256, "|", big_path)


def main():
    data = build_ico()
    os.makedirs(os.path.dirname(OUT_ICO), exist_ok=True)
    with open(OUT_ICO, "wb") as f:
        f.write(data)
    print("wrote", OUT_ICO, len(data), "bytes")
    print("sizes", BMP_SIZES, "(BMP) +", PNG_SIZES, "(PNG)")
    if os.environ.get("PREVIEW"):
        preview()


if __name__ == "__main__":
    main()
