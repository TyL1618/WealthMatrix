"""
holdings.py - HOLDINGS 分頁 Widget
即時顯示持倉股票的今日走勢圖表（每 2 分鐘自動更新）
"""
import hashlib
from datetime import datetime, timezone, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QPointF
from PyQt6.QtGui import (
    QPainter, QColor, QLinearGradient, QPen, QBrush, QPolygonF, QFont
)

from wealthmatrix.theme import CP, section_label, muted_label, fmt_ntd, S


REFRESH_SEC = 120
CARD_COLORS = [CP["cyan"], CP["pink"], CP["green"], CP["blue"], CP["gold"]]


def _ticker_color(ticker: str) -> str:
    """Deterministic color per ticker so colors don't shift on add/remove."""
    idx = int(hashlib.md5(ticker.encode()).hexdigest(), 16) % len(CARD_COLORS)
    return CARD_COLORS[idx]


# ── Background fetch thread ──────────────────────────────────────────
class FetchThread(QThread):
    done = pyqtSignal(dict)

    def __init__(self, tickers: list, fx_rate: float = 31.5):
        super().__init__()
        self.tickers = tickers
        self.fx_rate = fx_rate

    def run(self):
        import requests
        import certifi
        results = {}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        tz_cst = timezone(timedelta(hours=8))

        for ticker in self.tickers:
            try:
                url = (
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                    f"?interval=5m&range=1d"
                )
                r = requests.get(url, headers=headers, timeout=12,
                                 verify=certifi.where())
                r.raise_for_status()
                raw    = r.json()
                result = raw["chart"]["result"][0]
                meta   = result["meta"]
                quotes = result["indicators"]["quote"][0]
                timestamps = result.get("timestamp", [])

                is_usd = meta.get("currency", "TWD") != "TWD"
                rate   = self.fx_rate if is_usd else 1.0

                closes = quotes.get("close", [])
                pts = []
                for ts, c in zip(timestamps, closes):
                    if c is None:
                        continue
                    dt = datetime.fromtimestamp(
                        ts, tz=timezone.utc
                    ).astimezone(tz_cst)
                    pts.append((dt.strftime("%H:%M"), c * rate))

                results[ticker] = {
                    "name":         (meta.get("longName")
                                     or meta.get("shortName", ticker)),
                    "price":        meta.get("regularMarketPrice", 0) * rate,
                    "open":         meta.get("regularMarketOpen", 0) * rate,
                    "high":         meta.get("regularMarketDayHigh", 0) * rate,
                    "low":          meta.get("regularMarketDayLow", 0) * rate,
                    "prev_close":   meta.get("previousClose", 0) * rate,
                    "volume":       meta.get("regularMarketVolume", 0),
                    "market_state": meta.get("marketState", "CLOSED"),
                    "is_usd":       is_usd,
                    "pts":          pts,
                }
            except Exception as exc:
                results[ticker] = {"error": str(exc)}

        self.done.emit(results)


# ── Intraday line chart ──────────────────────────────────────────────
class IntradayChart(QWidget):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.color    = color
        self.pts      = []        # [(time_str, price), ...]
        self.open_val = None
        self.setMinimumHeight(S(155))
        self.setStyleSheet("background:transparent;")

    def set_data(self, pts: list, open_val: float):
        self.pts      = pts
        self.open_val = open_val
        self.update()

    def paintEvent(self, event):
        if not self.pts:
            p = QPainter(self)
            p.setPen(QColor(CP["muted"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "— 資料載入中 —")
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        pL, pR, pT, pB = S(60), S(14), S(10), S(26)
        cW = W - pL - pR
        cH = H - pT - pB
        n  = len(self.pts)

        prices = [v for _, v in self.pts]
        mn, mx = min(prices), max(prices)
        spn    = (mx - mn) or 1
        pad    = spn * 0.12
        yMin   = mn - pad
        yMax   = mx + pad
        ySpan  = (yMax - yMin) or 1

        def xof(i):
            return pL + cW * i / max(n - 1, 1)

        def yof(v):
            return pT + cH * (1.0 - (v - yMin) / ySpan)

        # Grid lines
        painter.setPen(QPen(QColor(CP["border"]), 1, Qt.PenStyle.DotLine))
        for i in range(5):
            y = int(pT + cH * i / 4)
            painter.drawLine(pL, y, W - pR, y)

        # Open baseline
        if self.open_val is not None:
            oy = int(yof(self.open_val))
            painter.setPen(QPen(QColor(CP["muted"]), 1, Qt.PenStyle.DashLine))
            painter.drawLine(pL, oy, W - pR, oy)
            painter.setPen(QColor(CP["muted"]))
            painter.setFont(QFont("Courier New", S(8)))
            painter.drawText(2, oy - S(5), pL - S(6), S(12),
                             Qt.AlignmentFlag.AlignRight
                             | Qt.AlignmentFlag.AlignVCenter, "開")

        c = QColor(self.color)

        # Gradient fill
        grad = QLinearGradient(0, pT, 0, pT + cH)
        grad.setColorAt(0, QColor(c.red(), c.green(), c.blue(), 55))
        grad.setColorAt(1, QColor(c.red(), c.green(), c.blue(), 0))
        poly = QPolygonF()
        poly.append(QPointF(xof(0), pT + cH))
        for i, (_, v) in enumerate(self.pts):
            poly.append(QPointF(xof(i), yof(v)))
        poly.append(QPointF(xof(n - 1), pT + cH))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(poly)

        # Line
        painter.setPen(QPen(QColor(self.color), S(2)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(n - 1):
            painter.drawLine(
                QPointF(xof(i),     yof(self.pts[i][1])),
                QPointF(xof(i + 1), yof(self.pts[i + 1][1])),
            )

        # Latest dot + glow
        lx, ly = xof(n - 1), yof(self.pts[-1][1])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(c.red(), c.green(), c.blue(), 45)))
        painter.drawEllipse(QPointF(lx, ly), S(7), S(7))
        painter.setBrush(QBrush(QColor(self.color)))
        painter.drawEllipse(QPointF(lx, ly), S(4), S(4))

        # Y-axis labels
        painter.setPen(QColor(CP["muted"]))
        painter.setFont(QFont("Courier New", S(8)))
        for i in range(5):
            v = yMax - ySpan * i / 4
            lbl = f"{v:,.0f}" if v >= 1000 else f"{v:.2f}"
            painter.drawText(
                0, int(pT + cH * i / 4) - S(5), pL - S(6), S(12),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                lbl,
            )

        # X-axis time labels (~5 evenly spaced)
        step = max(1, n // 5)
        for i in range(0, n, step):
            x = int(xof(i))
            painter.drawText(
                x - S(18), H - pB + S(4), S(36), S(14),
                Qt.AlignmentFlag.AlignCenter,
                self.pts[i][0],
            )


# ── Individual stock card ────────────────────────────────────────────
class StockCard(QFrame):
    def __init__(self, ticker: str, shares: float,
                 holding_cost: float, color: str, parent=None):
        super().__init__(parent)
        self.ticker       = ticker
        self.shares       = shares
        self.holding_cost = holding_cost
        self.color        = color
        self.setStyleSheet(f"""
            QFrame {{
                background: {CP['panel']};
                border: 1px solid #1a3a55;
                border-radius: {S(6)}px;
            }}
        """)
        self._build_ui()

    # ── helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _cs(col):
        return f"color:{col};font-size:{S(12)}px;border:none;"

    @staticmethod
    def _fmt_price(p: float) -> str:
        return f"{p:,.0f}" if p >= 1000 else f"{p:,.2f}"

    # ── build ─────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, S(3), 0, 0)
        root.setSpacing(0)

        # Accent bar
        accent = QWidget()
        accent.setFixedHeight(S(3))
        accent.setStyleSheet(
            f"background:{self.color};border-radius:{S(2)}px;border:none;"
        )
        root.addWidget(accent)

        # ── Header ────────────────────────────────────────────────────
        hdr_w = QWidget()
        hdr_h = QHBoxLayout(hdr_w)
        hdr_h.setContentsMargins(S(16), S(10), S(16), S(8))
        hdr_h.setSpacing(S(14))

        # Ticker + name
        nb = QVBoxLayout()
        nb.setSpacing(S(2))
        self.ticker_lbl = QLabel(self.ticker)
        self.ticker_lbl.setStyleSheet(
            f"color:{self.color};font-family:'Courier New',monospace;"
            f"font-size:{S(17)}px;font-weight:bold;letter-spacing:2px;"
        )
        self.name_lbl = QLabel("")
        self.name_lbl.setStyleSheet(
            f"color:{CP['muted']};font-size:{S(10)}px;letter-spacing:1px;"
        )
        nb.addWidget(self.ticker_lbl)
        nb.addWidget(self.name_lbl)
        hdr_h.addLayout(nb)

        # Price + change
        pb = QVBoxLayout()
        pb.setSpacing(S(2))
        self.price_lbl = QLabel("—")
        self.price_lbl.setStyleSheet(
            f"color:{CP['text']};font-family:'Courier New',monospace;"
            f"font-size:{S(22)}px;font-weight:bold;"
        )
        self.change_lbl = QLabel("—")
        self.change_lbl.setStyleSheet(
            f"color:{CP['muted']};font-size:{S(12)}px;"
        )
        pb.addWidget(self.price_lbl)
        pb.addWidget(self.change_lbl)
        hdr_h.addLayout(pb)

        hdr_h.addStretch()

        self.state_lbl = QLabel("—")
        self.state_lbl.setFixedWidth(S(76))
        self.state_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_state_style("CLOSED")
        hdr_h.addWidget(self.state_lbl)

        root.addWidget(hdr_w)

        # ── Chart ─────────────────────────────────────────────────────
        chart_wrap = QWidget()
        chart_wrap.setStyleSheet("border:none;")
        cw_lay = QHBoxLayout(chart_wrap)
        cw_lay.setContentsMargins(S(10), 0, S(10), 0)
        self.chart = IntradayChart(self.color)
        cw_lay.addWidget(self.chart)
        root.addWidget(chart_wrap)

        # ── Holding strip ──────────────────────────────────────────────
        hold_w = QWidget()
        hold_w.setStyleSheet(
            f"background:rgba(0,245,255,0.025);"
            f"border-top:1px solid {CP['border']};"
            f"border-bottom:1px solid {CP['border']};"
            f"border-left:none;border-right:none;border-radius:0;"
        )
        hold_h = QHBoxLayout(hold_w)
        hold_h.setContentsMargins(S(16), S(7), S(16), S(7))
        hold_h.setSpacing(0)

        self._hold_lbl: dict = {}
        hold_items = [
            ("shares",  "持股"),
            ("value",   "市值"),
            ("day_chg", "今日變動"),
            ("pnl",     "累計損益"),
            ("avg",     "均價"),
        ]
        for idx, (key, title) in enumerate(hold_items):
            blk = QVBoxLayout()
            blk.setSpacing(S(2))
            t = QLabel(title)
            t.setStyleSheet(
                f"color:{CP['muted']};font-size:{S(10)}px;"
                f"letter-spacing:1px;border:none;"
            )
            v = QLabel("—")
            v.setStyleSheet(f"color:{CP['text']};font-size:{S(12)}px;border:none;")
            blk.addWidget(t)
            blk.addWidget(v)
            hold_h.addLayout(blk)
            self._hold_lbl[key] = v
            if idx < len(hold_items) - 1:
                hold_h.addStretch()

        root.addWidget(hold_w)

        # ── Stats row ──────────────────────────────────────────────────
        stats_w = QWidget()
        stats_w.setStyleSheet("border:none;")
        stats_h = QHBoxLayout(stats_w)
        stats_h.setContentsMargins(S(16), S(8), S(16), S(12))
        stats_h.setSpacing(0)

        self._stat_lbl: dict = {}
        stat_items = [
            ("open",    "開盤"),
            ("high",    "最高"),
            ("low",     "最低"),
            ("prev",    "昨收"),
            ("vol",     "成交量"),
            ("updated", "更新時間"),
        ]
        for idx, (key, title) in enumerate(stat_items):
            blk = QVBoxLayout()
            blk.setSpacing(S(2))
            t = QLabel(title)
            t.setStyleSheet(
                f"color:{CP['muted']};font-size:{S(10)}px;"
                f"letter-spacing:1px;border:none;"
            )
            v = QLabel("—")
            v.setStyleSheet(f"color:{CP['text']};font-size:{S(12)}px;border:none;")
            blk.addWidget(t)
            blk.addWidget(v)
            stats_h.addLayout(blk)
            self._stat_lbl[key] = v
            if idx < len(stat_items) - 1:
                stats_h.addStretch()

        root.addWidget(stats_w)

    # ── state badge ───────────────────────────────────────────────────
    def _set_state_style(self, state: str):
        if state == "REGULAR":
            text  = "● OPEN"
            style = (
                f"color:{CP['green']};font-size:{S(10)}px;letter-spacing:1px;"
                f"background:rgba(0,255,136,0.08);"
                f"border:1px solid rgba(0,255,136,0.35);"
                f"border-radius:{S(3)}px;padding:{S(3)}px {S(8)}px;"
            )
        elif state in ("PRE", "PREPRE"):
            text  = "○ PRE"
            style = (
                f"color:{CP['gold']};font-size:{S(10)}px;letter-spacing:1px;"
                f"background:rgba(255,215,0,0.06);"
                f"border:1px solid rgba(255,215,0,0.25);"
                f"border-radius:{S(3)}px;padding:{S(3)}px {S(8)}px;"
            )
        elif state == "POST":
            text  = "○ POST"
            style = (
                f"color:{CP['muted']};font-size:{S(10)}px;letter-spacing:1px;"
                f"background:rgba(122,170,187,0.06);"
                f"border:1px solid rgba(122,170,187,0.25);"
                f"border-radius:{S(3)}px;padding:{S(3)}px {S(8)}px;"
            )
        else:
            text  = "○ CLOSED"
            style = (
                f"color:{CP['muted']};font-size:{S(10)}px;letter-spacing:1px;"
                f"background:rgba(122,170,187,0.06);"
                f"border:1px solid rgba(122,170,187,0.25);"
                f"border-radius:{S(3)}px;padding:{S(3)}px {S(8)}px;"
            )
        self.state_lbl.setText(text)
        self.state_lbl.setStyleSheet(style)

    # ── data update ───────────────────────────────────────────────────
    def update_data(self, d: dict):
        if "error" in d:
            self.name_lbl.setText(f"錯誤：{d['error'][:30]}")
            return

        price      = d.get("price", 0)
        prev_close = d.get("prev_close", 0) or 1
        open_p     = d.get("open", 0)
        high_p     = d.get("high", 0)
        low_p      = d.get("low", 0)
        volume     = d.get("volume", 0)
        state      = d.get("market_state", "CLOSED")
        pts        = d.get("pts", [])

        self.name_lbl.setText(d.get("name", "")[:26])
        self.price_lbl.setText(fmt_ntd(price))

        # Price change
        chg     = price - prev_close
        chg_pct = chg / prev_close * 100
        sign    = "▲" if chg >= 0 else "▼"
        col     = CP["green"] if chg >= 0 else CP["pink"]
        self.change_lbl.setText(
            f"{sign}  {fmt_ntd(abs(round(chg)))}  "
            f"({'+' if chg >= 0 else ''}{chg_pct:.2f}%)"
        )
        self.change_lbl.setStyleSheet(
            f"color:{col};font-size:{S(12)}px;border:none;"
        )

        self._set_state_style(state)
        self.chart.set_data(pts, open_p)

        # ── Holding strip ──────────────────────────────────────────────
        val         = price * self.shares
        day_val_chg = chg * self.shares
        day_col     = CP["green"] if day_val_chg >= 0 else CP["pink"]

        pnl     = (val - self.holding_cost) if self.holding_cost else None
        pnl_pct = ((pnl / self.holding_cost * 100)
                   if (pnl is not None and self.holding_cost) else None)
        pnl_col = CP["green"] if (pnl or 0) >= 0 else CP["pink"]
        avg     = self.holding_cost / self.shares if self.shares else 0

        cs = self._cs

        self._hold_lbl["shares"].setText(f"{int(self.shares):,} 股")
        self._hold_lbl["shares"].setStyleSheet(cs(CP["text"]))

        self._hold_lbl["value"].setText(fmt_ntd(val))
        self._hold_lbl["value"].setStyleSheet(cs(CP["text"]))

        dv_sign = "+" if day_val_chg >= 0 else ""
        self._hold_lbl["day_chg"].setText(
            f"{dv_sign}{fmt_ntd(round(day_val_chg))}  "
            f"({'+' if chg_pct >= 0 else ''}{chg_pct:.2f}%)"
        )
        self._hold_lbl["day_chg"].setStyleSheet(cs(day_col))

        if pnl is not None:
            ps = "+" if pnl >= 0 else ""
            self._hold_lbl["pnl"].setText(
                f"{ps}{fmt_ntd(round(pnl))}  "
                f"({'+' if (pnl_pct or 0) >= 0 else ''}{pnl_pct:.2f}%)"
            )
            self._hold_lbl["pnl"].setStyleSheet(cs(pnl_col))
        else:
            self._hold_lbl["pnl"].setText("—")
            self._hold_lbl["pnl"].setStyleSheet(cs(CP["muted"]))

        self._hold_lbl["avg"].setText(f"NT${avg:,.1f}")
        self._hold_lbl["avg"].setStyleSheet(cs(CP["text"]))

        # ── Stats row ──────────────────────────────────────────────────
        fp = self._fmt_price

        self._stat_lbl["open"].setText(fp(open_p))
        self._stat_lbl["open"].setStyleSheet(cs(CP["text"]))

        self._stat_lbl["high"].setText(fp(high_p))
        self._stat_lbl["high"].setStyleSheet(cs(CP["green"]))

        self._stat_lbl["low"].setText(fp(low_p))
        self._stat_lbl["low"].setStyleSheet(cs(CP["pink"]))

        self._stat_lbl["prev"].setText(fp(prev_close))
        self._stat_lbl["prev"].setStyleSheet(cs(CP["text"]))

        if volume >= 1_000_000:
            vol_str = f"{volume / 1_000_000:.1f}M"
        elif volume >= 1_000:
            vol_str = f"{volume / 1_000:.0f}K"
        else:
            vol_str = str(volume)
        self._stat_lbl["vol"].setText(vol_str)
        self._stat_lbl["vol"].setStyleSheet(cs(CP["text"]))

        self._stat_lbl["updated"].setText(datetime.now().strftime("%H:%M:%S"))
        self._stat_lbl["updated"].setStyleSheet(cs(CP["muted"]))


# ── HOLDINGS tab ─────────────────────────────────────────────────────
class HoldingsWidget(QWidget):
    def __init__(self, data: dict, get_fx_rate_fn, parent=None):
        super().__init__(parent)
        self.data          = data
        self.get_fx_rate   = get_fx_rate_fn
        self._cards: dict  = {}          # ticker → StockCard
        self._fetch_thread = None
        self._countdown    = REFRESH_SEC
        self._build_ui()
        self._rebuild_cards()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

        QTimer.singleShot(600, self._do_fetch)

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer_scroll = QScrollArea()
        outer_scroll.setWidgetResizable(True)
        outer_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        outer_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        content = QWidget()
        self._lay = QVBoxLayout(content)
        self._lay.setContentsMargins(S(10), S(10), S(10), S(10))
        self._lay.setSpacing(S(10))

        # Header
        hdr = QHBoxLayout()
        hdr.setSpacing(S(8))
        hdr.addWidget(section_label("LIVE POSITIONS"))

        self.refresh_btn = QPushButton("↻  REFRESH")
        self.refresh_btn.clicked.connect(self._manual_refresh)
        hdr.addWidget(self.refresh_btn)

        self.countdown_lbl = QLabel()
        self.countdown_lbl.setObjectName("muted")
        self._update_countdown_lbl()
        hdr.addWidget(self.countdown_lbl)

        hdr.addStretch()

        auto_lbl = muted_label(f"⏱  AUTO  {REFRESH_SEC // 60} MIN")
        auto_lbl.setStyleSheet(
            f"color:{CP['muted']};font-size:{S(10)}px;letter-spacing:1px;"
        )
        hdr.addWidget(auto_lbl)
        self._lay.addLayout(hdr)

        # Cards area
        self._cards_lay = QVBoxLayout()
        self._cards_lay.setContentsMargins(0, 0, 0, 0)
        self._cards_lay.setSpacing(S(14))
        self._lay.addLayout(self._cards_lay)
        self._lay.addStretch()

        outer_scroll.setWidget(content)
        outer.addWidget(outer_scroll)

    def _update_countdown_lbl(self):
        m = self._countdown // 60
        s = self._countdown % 60
        self.countdown_lbl.setText(f"次刷新  {m}:{s:02d}")

    # ── Cards ─────────────────────────────────────────────────────────
    def _rebuild_cards(self):
        while self._cards_lay.count():
            item = self._cards_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        stocks = self.data.get("stocks", [])
        if not stocks:
            lbl = muted_label(
                "— 尚無持股，請先在 DASHBOARD 新增股票 —"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._cards_lay.addWidget(lbl)
            return

        for s in stocks:
            color = _ticker_color(s["ticker"])
            card  = StockCard(
                ticker=s["ticker"],
                shares=s["shares"],
                holding_cost=s.get(
                    "holding_cost", s.get("cost", 0) * s["shares"]
                ),
                color=color,
            )
            self._cards[s["ticker"]] = card
            self._cards_lay.addWidget(card)

    # ── Timer / fetch ─────────────────────────────────────────────────
    def _tick(self):
        self._countdown -= 1
        self._update_countdown_lbl()
        if self._countdown <= 0:
            self._countdown = REFRESH_SEC
            self._do_fetch()

    def _manual_refresh(self):
        self._countdown = REFRESH_SEC
        self._update_countdown_lbl()
        self._do_fetch()

    def _do_fetch(self):
        tickers = [s["ticker"] for s in self.data.get("stocks", [])]
        if not tickers:
            return
        if self._fetch_thread and self._fetch_thread.isRunning():
            return
        fx = self.get_fx_rate() if callable(self.get_fx_rate) else 31.5
        self._fetch_thread = FetchThread(tickers, fx_rate=fx)
        self._fetch_thread.done.connect(self._on_fetch_done)
        self._fetch_thread.start()
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("載入中…")

    def _on_fetch_done(self, results: dict):
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("↻  REFRESH")
        for ticker, card in self._cards.items():
            if ticker in results:
                card.update_data(results[ticker])

    # ── Called when stocks list changes ───────────────────────────────
    def refresh_stocks(self):
        """
        Called from app._render_all() when data changes.
        Rebuilds cards only when ticker set actually changed;
        otherwise just updates shares / holding_cost metadata.
        """
        stocks      = self.data.get("stocks", [])
        tickers_now = [s["ticker"] for s in stocks]
        tickers_had = list(self._cards.keys())

        if tickers_now != tickers_had:
            self._rebuild_cards()
            self._do_fetch()
        else:
            for s in stocks:
                card = self._cards.get(s["ticker"])
                if card:
                    card.shares       = s["shares"]
                    card.holding_cost = s.get(
                        "holding_cost", s.get("cost", 0) * s["shares"]
                    )
