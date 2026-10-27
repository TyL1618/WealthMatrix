#!/usr/bin/env python3
"""
make_icon.py — 產生 WealthMatrix 的所有 icon（只用 PyQt6，不需要額外套件）

設計：深色圓角方塊 + 淡淡的矩陣點陣 + 一條「W」形的上升折線（W = Wealth，也是向上的走勢圖），
      線條由藍到綠漸層並帶柔光，終點是發亮的節點。配色與 App 一致（#5ab0e8 → #3ecf8e）。

輸出
  icon.ico                         桌面版 / exe（16/24/32/48/64/128/256，透明圓角）
  docs/icon-192.png, icon-512.png  PWA（purpose: any，透明圓角）
  docs/icon-maskable-512.png       PWA（purpose: maskable，滿版方形，內容縮在安全區內）
  docs/apple-touch-icon.png        iOS 主畫面（180，滿版方形，系統自己切圓角）

執行
    python scripts/make_icon.py            # 重新產生全部
    python scripts/make_icon.py --preview  # 另外輸出預覽圖 icon_preview.png（不會被 git 追蹤）
"""
import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath,
    QPen, QRadialGradient,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER = 1024

# 色票（與 App 一致）
BG_TOP, BG_BOTTOM = QColor("#1c2738"), QColor("#0b1016")
ACCENT_A, ACCENT_B = QColor("#5ab0e8"), QColor("#3ecf8e")

# W 形折線（0..1 座標，原點在左上）：左上 → 谷 → 中峰 → 谷 → 右上（終點最高 = 向上的趨勢）
W_POINTS = [(0.185, 0.345), (0.335, 0.665), (0.500, 0.445), (0.665, 0.665), (0.815, 0.235)]


def _with_alpha(color: QColor, a: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def render_master(rounded: bool, content_scale: float = 1.0, size: int = MASTER, bold: bool = False) -> QImage:
    """bold=True：給 16–32px 的小尺寸用——線條加粗、拿掉點陣與柔光，縮小後仍然看得清楚。"""
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    S = float(size)

    # ── 背景 ──
    shape = QPainterPath()
    if rounded:
        shape.addRoundedRect(QRectF(0, 0, S, S), S * 0.225, S * 0.225)
    else:
        shape.addRect(QRectF(0, 0, S, S))
    p.setClipPath(shape)

    bg = QLinearGradient(0, 0, 0, S)
    bg.setColorAt(0.0, BG_TOP)
    bg.setColorAt(1.0, BG_BOTTOM)
    p.fillPath(shape, QBrush(bg))

    glow = QRadialGradient(QPointF(S * 0.28, S * 0.18), S * 0.85)       # 左上角一點冷光
    glow.setColorAt(0.0, _with_alpha(ACCENT_A, 0.22))
    glow.setColorAt(1.0, _with_alpha(ACCENT_A, 0.0))
    p.fillPath(shape, QBrush(glow))

    # ── 內容（maskable 時整體縮小，留出安全區）──
    p.save()
    p.translate(S / 2, S / 2)
    p.scale(content_scale, content_scale)
    p.translate(-S / 2, -S / 2)

    # 矩陣點陣
    dot = S * 0.0075
    n = 7
    for i in range(0 if bold else n):
        for j in range(n):
            x = S * (0.15 + 0.70 * i / (n - 1))
            y = S * (0.15 + 0.70 * j / (n - 1))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(150, 185, 215, 34))
            p.drawEllipse(QPointF(x, y), dot, dot)

    pts = [QPointF(x * S, y * S) for x, y in W_POINTS]
    path = QPainterPath(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)

    grad = QLinearGradient(pts[0], pts[-1])
    grad.setColorAt(0.0, ACCENT_A)
    grad.setColorAt(1.0, ACCENT_B)

    def stroke(width, color_or_brush, alpha=None):
        brush = QBrush(color_or_brush)
        pen = QPen(brush, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    # 柔光（疊幾層半透明的粗線）
    for w, a in (() if bold else ((0.20, 0.05), (0.15, 0.07), (0.115, 0.10))):
        g = QLinearGradient(pts[0], pts[-1])
        g.setColorAt(0.0, _with_alpha(ACCENT_A, a))
        g.setColorAt(1.0, _with_alpha(ACCENT_B, a))
        stroke(S * w, g)
    stroke(S * (0.125 if bold else 0.078), grad)

    # 終點節點
    end = pts[-1]
    halo = QRadialGradient(end, S * 0.13)
    halo.setColorAt(0.0, _with_alpha(ACCENT_B, 0.55))
    halo.setColorAt(1.0, _with_alpha(ACCENT_B, 0.0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(halo))
    p.drawEllipse(end, S * 0.13, S * 0.13)
    p.setBrush(QColor("#f2fffa"))
    p.drawEllipse(end, S * (0.085 if bold else 0.052), S * (0.085 if bold else 0.052))
    p.setBrush(ACCENT_B)
    p.drawEllipse(end, S * (0.050 if bold else 0.030), S * (0.050 if bold else 0.030))
    p.restore()

    # 細邊框（圓角版才有，讓邊緣在深色背景上也看得出來）
    if rounded:
        p.setClipping(False)
        edge = QLinearGradient(0, 0, 0, S)
        edge.setColorAt(0.0, QColor(255, 255, 255, 46))
        edge.setColorAt(1.0, QColor(255, 255, 255, 10))
        pen = QPen(QBrush(edge), S * 0.006)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        inset = S * 0.003
        p.drawRoundedRect(QRectF(inset, inset, S - 2 * inset, S - 2 * inset), S * 0.225, S * 0.225)

    p.end()
    return img


def scaled(img: QImage, size: int) -> QImage:
    return img.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def write_ico(path: str, images: dict):
    """images: {size: QImage}。以 PNG 壓縮格式寫入多尺寸 .ico（Windows Vista 以後都支援）。"""
    sizes = sorted(images)
    blobs = [png_bytes(images[s]) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, blob in zip(sizes, blobs):
        entries += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    with open(path, "wb") as f:
        f.write(header + entries + b"".join(blobs))


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)

    rounded = render_master(rounded=True)
    rounded_bold = render_master(rounded=True, bold=True)
    maskable = render_master(rounded=False, content_scale=0.80)       # 安全區：內容縮到 80%
    apple = render_master(rounded=False, content_scale=0.92)

    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    write_ico(os.path.join(ROOT, "icon.ico"),
              {s: scaled(rounded_bold if s <= 32 else rounded, s) for s in ico_sizes})
    outs = {
        "docs/icon-192.png": scaled(rounded, 192),
        "docs/icon-512.png": scaled(rounded, 512),
        "docs/icon-maskable-512.png": scaled(maskable, 512),
        "docs/apple-touch-icon.png": scaled(apple, 180),
    }
    for rel, img in outs.items():
        img.save(os.path.join(ROOT, rel), "PNG")
    print("OK  icon.ico  (" + ", ".join(map(str, ico_sizes)) + ")")
    for rel in outs:
        print("OK ", rel)

    if "--preview" in sys.argv:
        # 預覽：深色/淺色底、各尺寸，方便檢查小尺寸的可讀性
        sheet = QImage(1500, 700, QImage.Format.Format_ARGB32)
        sheet.fill(QColor("#0f1419"))
        p = QPainter(sheet)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(0, 350, 1500, 350, QColor("#f2f4f7"))
        x = 30
        for size in (256, 128, 64, 48, 32, 24, 16):
            for y0 in (30, 380):
                p.drawImage(x, y0 + (256 - size) // 2, scaled(rounded_bold if size <= 32 else rounded, size))
            x += size + 40
        p.drawImage(1130, 30, scaled(maskable, 160))
        p.drawImage(1320, 30, scaled(apple, 160))
        # 圓形遮罩示意（Android maskable）
        circ = QImage(160, 160, QImage.Format.Format_ARGB32)
        circ.fill(Qt.GlobalColor.transparent)
        cp = QPainter(circ)
        cp.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addEllipse(0, 0, 160, 160)
        cp.setClipPath(path)
        cp.drawImage(0, 0, scaled(maskable, 160))
        cp.end()
        p.drawImage(1130, 220, circ)
        p.end()
        out = os.path.join(ROOT, "icon_preview.png")
        sheet.save(out, "PNG")
        print("OK  preview ->", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
