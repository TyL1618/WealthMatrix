"""
charts.py - 圖表分頁 Widget（折線圖 + 圓餅圖）
折線圖支援多走勢（總資產 / 銀行 / 現金 / 股票）切換
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QMessageBox, QPushButton, QLabel
)
from PyQt6.QtGui import (
    QColor, QPainter, QLinearGradient, QPen, QBrush,
    QPolygonF, QFont
)
from PyQt6.QtCore import Qt, QPointF, QRectF

from styles import CP, CpPanel, section_label, S


# ── 走勢系列定義 ──────────────────────────────────────────────────────
SERIES_DEFS = [
    ("total",  "總資產",  CP["cyan"]),
    ("bank",   "銀行",    CP["blue"]),
    ("cash",   "現金",    CP["green"]),
    ("stock",  "股票/ETF", CP["pink"]),
]


# ── 多走勢折線圖 ──────────────────────────────────────────────────────
class LineChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # series_data: dict  key -> list of (date_str, value)
        self.series_data   = {}
        self.active_series = {"total"}   # 預設只顯示總資產
        self.setMinimumHeight(S(200))
        self.setStyleSheet("background:transparent;")

    def set_data(self, series_data: dict):
        """series_data = {"total": [...], "bank": [...], "cash": [...], "stock": [...]}"""
        self.series_data = series_data
        self.update()

    def toggle_series(self, key):
        if key in self.active_series:
            if len(self.active_series) > 1:   # 至少保留一條線
                self.active_series.discard(key)
        else:
            self.active_series.add(key)
        self.update()

    def paintEvent(self, event):
        # 收集所有啟用走勢的資料
        active = [(k, l, c) for k, l, c in SERIES_DEFS
                  if k in self.active_series and self.series_data.get(k)]
        if not active:
            p = QPainter(self)
            p.setPen(QColor(CP["muted"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "— 尚無歷史資料 —")
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = S(84), S(20), S(20), S(40)
        chart_w = W - pad_l - pad_r
        chart_h = H - pad_t - pad_b

        # ── 全局 Y 範圍：智慧貼近資產規模 ───────────────────────────
        all_vals = []
        for k, _, _ in active:
            all_vals += [v for _, v in self.series_data[k]]
        if not all_vals:
            return
        data_min, data_max = min(all_vals), max(all_vals)

        # 資料差距太小時，給一個合理的 padding 讓線不要水平
        data_span = data_max - data_min
        if data_span < data_max * 0.005:          # 差距小於 0.5%
            data_span = max(data_max * 0.05, 100) # 至少 5% 或 100 元的顯示空間

        # Y 軸顯示範圍：貼近資料，上下各留 10% padding
        pad_amt  = data_span * 0.10
        y_min    = max(0, data_min - pad_amt)
        y_max    = data_max + pad_amt
        y_span   = y_max - y_min or 1

        # ── Y 軸刻度：根據資料規模自動選單位 ────────────────────────
        def _fmt_val(v):
            if y_max >= 1_000_000:
                return f"NT${v/10000:.0f}萬"
            elif y_max >= 10_000:
                return f"NT${v/10000:.1f}萬"
            else:
                return f"NT${v:,.0f}"

        # 格線 & Y 軸標籤（5條格線，含頂底）
        painter.setFont(QFont("Courier New", S(8)))
        for i in range(5):
            y = pad_t + int(chart_h * i / 4)
            val = y_max - y_span * i / 4
            # 格線
            painter.setPen(QPen(QColor(CP["border"]), 1, Qt.PenStyle.DotLine))
            painter.drawLine(pad_l, y, W - pad_r, y)
            # 標籤
            painter.setPen(QColor(CP["muted"]))
            painter.drawText(0, y - S(9), pad_l - S(4), S(18),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             _fmt_val(val))

        # ── X 軸日期（取所有走勢的聯集日期排序）────────────────────
        all_dates = sorted(set(
            d for k, _, _ in active
            for d, _ in self.series_data[k]
        ))
        n_dates = len(all_dates)
        date_x  = {d: pad_l + chart_w * i / max(n_dates - 1, 1)
                   for i, d in enumerate(all_dates)}

        painter.setPen(QColor(CP["muted"]))
        painter.setFont(QFont("Courier New", S(8)))
        step = max(1, n_dates // 6)
        for i in range(0, n_dates, step):
            d = all_dates[i]
            x = int(date_x[d])
            painter.drawText(x - S(24), H - pad_b + S(6), S(48), S(16),
                             Qt.AlignmentFlag.AlignCenter, d[-5:])

        # ── 畫每條走勢 ──────────────────────────────────────────────
        def _y_pos(v):
            return pad_t + chart_h * (1 - (v - y_min) / y_span)

        for key, label, color in active:
            pts_data = self.series_data[key]
            if not pts_data:
                continue

            # 只取有在聯集日期裡的點，依日期排序
            pts_sorted = sorted(pts_data, key=lambda p: p[0])

            c = QColor(color)

            if len(pts_sorted) == 1:
                # 只有一筆資料：畫一個大節點 + 水平虛線提示
                d, v = pts_sorted[0]
                x = int(date_x.get(d, pad_l + chart_w / 2))
                y = int(_y_pos(v))
                painter.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 80),
                                    1, Qt.PenStyle.DashLine))
                painter.drawLine(pad_l, y, W - pad_r, y)
                painter.setBrush(QBrush(QColor(color)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(x, y), S(5), S(5))
                continue

            xys = [(int(date_x.get(d, 0)), int(_y_pos(v))) for d, v in pts_sorted]

            # 填充漸層
            grad = QLinearGradient(0, pad_t, 0, pad_t + chart_h)
            grad.setColorAt(0, QColor(c.red(), c.green(), c.blue(), 40))
            grad.setColorAt(1, QColor(c.red(), c.green(), c.blue(), 0))
            poly = QPolygonF()
            poly.append(QPointF(xys[0][0], pad_t + chart_h))
            for x, y in xys:
                poly.append(QPointF(x, y))
            poly.append(QPointF(xys[-1][0], pad_t + chart_h))
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(poly)

            # 折線
            painter.setPen(QPen(QColor(color), S(2)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(len(xys) - 1):
                painter.drawLine(QPointF(*xys[i]), QPointF(*xys[i + 1]))

            # 節點
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(Qt.PenStyle.NoPen)
            for x, y in xys:
                painter.drawEllipse(QPointF(x, y), S(3), S(3))


# ── 圓餅圖 ────────────────────────────────────────────────────────────
class PieChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.slices = []
        self.setMinimumHeight(S(200))
        self.setStyleSheet("background:transparent;")

    def set_data(self, slices):
        self.slices = [(l, v, c) for l, v, c in slices if v > 0]
        self.update()

    def paintEvent(self, event):
        if not self.slices:
            p = QPainter(self)
            p.setPen(QColor(CP["muted"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "— 無資料 —")
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        diameter = min(W - 180, H - 20)
        cx = diameter // 2 + 10
        cy = H // 2
        r  = diameter // 2

        rect  = QRectF(cx - r, cy - r, diameter, diameter)
        total = sum(v for _, v, _ in self.slices)
        angle = 90 * 16

        for label, value, color in self.slices:
            span = int(360 * 16 * value / total)
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(QPen(QColor(CP["bg"]), 2))
            painter.drawPie(rect, angle, span)
            angle += span

        legend_x = cx + r + S(20)
        legend_y = cy - len(self.slices) * S(18) // 2
        painter.setFont(QFont("Courier New", S(10)))
        for i, (label, value, color) in enumerate(self.slices):
            y = legend_y + i * S(22)
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(legend_x, y, S(12), S(12), S(3), S(3))
            painter.setPen(QColor(CP["text"]))
            pct = value / total * 100
            painter.drawText(legend_x + S(18), y, S(200), S(14),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             f"{label}  {pct:.1f}%")


# ── 圖表分頁 Widget ───────────────────────────────────────────────────
class ChartsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S(10), S(10), S(10), S(10))
        lay.setSpacing(S(14))

        # ── 折線圖面板 ────────────────────────────────────────────
        line_panel = CpPanel(accent=CP["cyan"])
        line_lay   = QVBoxLayout(line_panel)
        line_lay.setContentsMargins(S(12), S(10), S(12), S(10))

        line_header = QHBoxLayout()
        line_header.addWidget(section_label("ASSET HISTORY"))
        line_header.addStretch()

        # 走勢切換按鈕
        self._series_btns = {}
        for key, label, color in SERIES_DEFS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == "total")
            btn.setStyleSheet(
                f"border:1px solid {color}44;color:{color};"
                f"border-radius:3px;padding:{S(2)}px {S(8)}px;font-size:{S(11)}px;"
                f"font-family:'Courier New',monospace;"
            )
            btn.toggled.connect(lambda checked, k=key, b=btn, c=color: (
                b.setStyleSheet(
                    f"border:1px solid {c}{'ff' if checked else '44'};"
                    f"color:{c};background:{'rgba'+str(QColor(c).getRgb()[:3]+(30,)).replace('(','(').replace(',',',' ) if checked else 'transparent'};"
                    f"border-radius:3px;padding:{S(2)}px {S(8)}px;font-size:{S(11)}px;"
                    f"font-family:'Courier New',monospace;"
                ),
                self.line_chart.toggle_series(k)
            ))
            self._series_btns[key] = btn
            line_header.addWidget(btn)

        self.clear_hist_btn = QPushButton("CLEAR")
        self.clear_hist_btn.setObjectName("btn_pink")
        line_header.addWidget(self.clear_hist_btn)
        line_lay.addLayout(line_header)

        self.line_chart = LineChartWidget()
        line_lay.addWidget(self.line_chart)
        lay.addWidget(line_panel)

        # ── 圓餅圖面板 ────────────────────────────────────────────
        pie_panel = CpPanel(accent=CP["blue"])
        pie_lay   = QVBoxLayout(pie_panel)
        pie_lay.setContentsMargins(S(12), S(10), S(12), S(10))
        pie_lay.addWidget(section_label("ASSET ALLOCATION"))
        self.pie_chart = PieChartWidget()
        pie_lay.addWidget(self.pie_chart)
        lay.addWidget(pie_panel)

    def update_charts(self, history, bank_history, cash_history, stock_history,
                      bank_total, cash_total, stock_total):
        """
        history       : list of {"date": str, "total": float}
        bank_history  : list of {"date": str, "bank": float}
        cash_history  : list of {"date": str, "cash": float}
        stock_history : list of {"date": str, "stock": float}
        """
        total_pts = [(h["date"], h["total"]) for h in history]
        bank_pts  = [(h["date"], h["bank"])  for h in bank_history]
        cash_pts  = [(h["date"], h["cash"])  for h in cash_history]
        stock_pts = [(h["date"], h["stock"]) for h in stock_history]

        self.line_chart.set_data({
            "total": total_pts,
            "bank":  bank_pts,
            "cash":  cash_pts,
            "stock": stock_pts,
        })
        self.pie_chart.set_data([
            ("銀行存款", bank_total,  CP["cyan"]),
            ("手頭現金", cash_total,  CP["green"]),
            ("股票/ETF",  stock_total, CP["pink"]),
        ])