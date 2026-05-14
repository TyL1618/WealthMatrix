"""
WEALTH MATRIX - Cyberpunk 財富管理系統 v4.1
依賴: pip install PyQt6 requests cryptography
執行: python main.py

變更（v4.1）:
  - 現金流記錄可選日期
  - 折線圖多走勢切換（總資產/銀行/現金/股票）
  - JSON 加密存檔（cryptography.fernet）
  - Yahoo Finance 失敗提示（toast 通知）
  - 匯率當天快取
  - 視窗位置與大小記憶
  - 刪除操作可 Ctrl+Z 復原（銀行/股票/目標/現金流）
"""

import sys
from datetime import datetime, date

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTabWidget,
    QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QSize
from PyQt6.QtGui import QColor, QPalette, QKeySequence, QShortcut

from styles import CP, STYLESHEET, S
from data_manager import DataFetcher, load_data, save_data, pop_undo, push_undo, add_month_record
from dashboard import DashboardWidget
from cashflow import CashflowWidget
from charts import ChartsWidget


# ── Toast 通知（右下角淡出）─────────────────────────────────────────
class Toast(QLabel):
    def __init__(self, msg, parent):
        super().__init__(msg, parent)
        self.setWordWrap(True)
        self.setStyleSheet(
            f"background:#1a0a00;border:1px solid {CP['orange']};"
            f"color:{CP['orange']};font-family:'Courier New',monospace;"
            f"font-size:{S(11)}px;padding:{S(10)}px {S(14)}px;border-radius:6px;"
        )
        self.adjustSize()
        self._opacity = 1.0
        self._place(parent)
        self.show()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._fade)
        self._timer.start(60)
        self._delay = 40   # ~2.4s 顯示後淡出

    def _place(self, parent):
        pw, ph = parent.width(), parent.height()
        self.move(pw - self.width() - 16, ph - self.height() - 16)

    def _fade(self):
        if self._delay > 0:
            self._delay -= 1
            return
        self._opacity -= 0.04
        self.setStyleSheet(
            f"background:#1a0a00;border:1px solid {CP['orange']};"
            f"color:rgba(255,149,0,{max(0,self._opacity):.2f});"
            f"font-family:'Courier New',monospace;"
            f"font-size:{S(11)}px;padding:{S(10)}px {S(14)}px;border-radius:6px;"
        )
        if self._opacity <= 0:
            self._timer.stop()
            self.deleteLater()


class WealthMatrix(QMainWindow):
    def __init__(self):
        super().__init__()
        self.data         = load_data()
        self.stock_prices = {}
        self.usd_rate     = self.data.get("usd_rate", 31.5)

        self.fetcher = DataFetcher()
        self.fetcher.prices_ready.connect(self._on_prices)
        self.fetcher.fx_ready.connect(self._on_fx)
        self.fetcher.fetch_error.connect(self._on_fetch_error)   # ★ API 失敗提示

        self.setWindowTitle("WEALTH MATRIX v4.1")
        self.setMinimumSize(S(900), S(780))
        self.setStyleSheet(STYLESHEET)

        self._build_ui()
        self._restore_geometry()   # ★ 視窗幾何記憶

        # 目標摺疊狀態
        if not self.data["goals_visible"]:
            self.dashboard.goals_scroll.hide()
            self.dashboard.toggle_goal_btn.setText("SHOW")

        # 時鐘
        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)

        # 定時刷新股價（每60秒）
        self.price_timer = QTimer()
        self.price_timer.timeout.connect(self.refresh_prices)
        self.price_timer.start(60_000)

        # ★ Ctrl+Z 全局復原
        undo_sc = QShortcut(QKeySequence("Ctrl+Z"), self)
        undo_sc.activated.connect(self._undo)

        self._render_all()
        self.refresh_prices()

        QTimer.singleShot(500, self._maybe_record_history)
        QTimer.singleShot(800, self.dashboard.check_dca_reminder)

    # ──────────────────────────────────────────────────────────────
    # 視窗幾何
    # ──────────────────────────────────────────────────────────────
    def _restore_geometry(self):
        geo = self.data.get("window_geometry")
        if geo and len(geo) == 4:
            x, y, w, h = geo
            self.move(QPoint(x, y))
            self.resize(QSize(w, h))
        else:
            self.resize(S(980), S(900))

    def closeEvent(self, event):
        pos = self.pos()
        sz  = self.size()
        self.data["window_geometry"] = [pos.x(), pos.y(), sz.width(), sz.height()]
        save_data(self.data)
        super().closeEvent(event)

    # ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(S(16), S(14), S(16), S(14))
        root.setSpacing(S(10))

        # Header
        header = QHBoxLayout()
        title = QLabel("⬡  WEALTH MATRIX v4.1")
        title.setObjectName("title")
        self.clock_lbl = QLabel()
        self.clock_lbl.setObjectName("clock")
        self.fx_lbl = QLabel()
        self.fx_lbl.setObjectName("fx_rate")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.fx_lbl)
        header.addSpacing(S(16))
        header.addWidget(self.clock_lbl)
        root.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{CP['border']};")
        root.addWidget(sep)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self.dashboard = DashboardWidget(
            data=self.data,
            get_stock_prices_fn=lambda: self.stock_prices,
            refresh_prices_fn=self.refresh_prices,
            on_data_changed=self._render_all,
        )
        self.tabs.addTab(self.dashboard, "DASHBOARD")

        self.cashflow_w = CashflowWidget(
            data=self.data,
            on_data_changed=self._render_all,
        )
        self.tabs.addTab(self.cashflow_w, "CASHFLOW")

        self.charts_w = ChartsWidget()
        self.charts_w.clear_hist_btn.clicked.connect(self._clear_history)
        self.tabs.addTab(self.charts_w, "CHARTS")

    # ──────────────────────────────────────────────────────────────
    # 計算
    # ──────────────────────────────────────────────────────────────
    def _bank_total(self):
        return sum(b["amount"] for b in self.data["banks"])

    def _stocks_total(self):
        return sum(
            self.stock_prices.get(s["ticker"], s.get("cost", 0)) * s["shares"]
            for s in self.data["stocks"]
        )

    def _grand_total(self):
        return self._bank_total() + self.data["cash"] + self._stocks_total()

    # ──────────────────────────────────────────────────────────────
    # 渲染
    # ──────────────────────────────────────────────────────────────
    def _render_all(self):
        self.dashboard.render_all(self._grand_total())
        self.charts_w.update_charts(
            self.data["history"],
            self.data.get("history_bank",  []),
            self.data.get("history_cash",  []),
            self.data.get("history_stock", []),
            self._bank_total(),
            self.data["cash"],
            self._stocks_total()
        )

    def _update_clock(self):
        self.clock_lbl.setText(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))

    # ──────────────────────────────────────────────────────────────
    # 歷史（同時記錄分項）
    # ──────────────────────────────────────────────────────────────
    def _maybe_record_history(self):
        today = date.today().isoformat()
        total = self._grand_total()
        bank  = self._bank_total()
        cash  = self.data["cash"]
        stock = self._stocks_total()

        # 總資產
        history = self.data.setdefault("history", [])
        existing = [h for h in history if h["date"] == today]
        if existing:
            existing[0]["total"] = total
        else:
            history.append({"date": today, "total": total})
        self.data["history"] = sorted(history, key=lambda x: x["date"])[-365:]

        # 銀行
        for key, val, field in [
            ("history_bank",  bank,  "bank"),
            ("history_cash",  cash,  "cash"),
            ("history_stock", stock, "stock"),
        ]:
            arr = self.data.setdefault(key, [])
            ex  = [h for h in arr if h["date"] == today]
            if ex:
                ex[0][field] = val
            else:
                arr.append({"date": today, field: val})
            self.data[key] = sorted(arr, key=lambda x: x["date"])[-365:]

        save_data(self.data)
        self._render_all()

    def _clear_history(self):
        if QMessageBox.question(
            self, "確認", "清除所有歷史走勢資料？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            for key in ["history", "history_bank", "history_cash", "history_stock"]:
                self.data[key] = []
            save_data(self.data)
            self.charts_w.update_charts([], [], [], [], 0, 0, 0)

    # ──────────────────────────────────────────────────────────────
    # 價格刷新（傳入匯率快取）
    # ──────────────────────────────────────────────────────────────
    def refresh_prices(self):
        tickers = [s["ticker"] for s in self.data["stocks"]]
        self.dashboard.refresh_lbl.setText("抓取中...")
        self.fetcher.fetch_all(
            tickers,
            fetch_fx=True,
            cached_rate=self.data.get("usd_rate"),
            cached_date=self.data.get("usd_rate_date", ""),
        )

    def _on_fx(self, rate):
        self.usd_rate = rate
        self.data["usd_rate"]      = rate
        self.data["usd_rate_date"] = date.today().isoformat()   # ★ 快取今天日期
        self.fx_lbl.setText(f"USD/TWD  {rate:.2f}")

    def _on_prices(self, prices):
        self.stock_prices.update(prices)
        self.dashboard.refresh_lbl.setText(datetime.now().strftime("更新 %H:%M"))
        self._render_all()
        self._maybe_record_history()

    def _on_fetch_error(self, msg):
        """Yahoo Finance / 網路失敗 → 右下角 Toast 通知"""
        Toast(msg, self)

    # ──────────────────────────────────────────────────────────────
    # Ctrl+Z 復原
    # ──────────────────────────────────────────────────────────────
    def _undo(self):
        result = pop_undo(self.data)
        if result is None:
            Toast("沒有可復原的操作。", self)
            return

        action, payload = result

        if action == "del_bank":
            bank = payload["bank"]
            idx  = payload.get("idx", len(self.data["banks"]))
            self.data["banks"].insert(min(idx, len(self.data["banks"])), bank)
            save_data(self.data)
            self._render_all()
            Toast(f"已復原：銀行帳戶「{bank['name']}」", self)

        elif action == "del_stock":
            stock = payload["stock"]
            idx   = payload.get("idx", len(self.data["stocks"]))
            self.data["stocks"].insert(min(idx, len(self.data["stocks"])), stock)
            save_data(self.data)
            self._render_all()
            Toast(f"已復原：股票「{stock['ticker']}」", self)

        elif action == "del_goal":
            goal = payload["goal"]
            idx  = payload.get("idx", len(self.data["goals"]))
            self.data["goals"].insert(min(idx, len(self.data["goals"])), goal)
            save_data(self.data)
            self.dashboard.render_goals()
            Toast(f"已復原：目標「{goal['name']}」", self)

        elif action == "del_cashflow":
            year   = payload["year"]
            month  = payload["month"]
            idx    = payload["idx"]
            record = payload["record"]
            key    = f"{year:04d}-{month:02d}"
            arr    = self.data["cashflow_monthly"].setdefault(key, [])
            arr.insert(min(idx, len(arr)), record)
            save_data(self.data)
            self.cashflow_w.refresh()
            Toast(f"已復原：現金流記錄（{record['date']} {record['category']}）", self)

        else:
            Toast(f"不支援的復原類型：{action}", self)


# ── 入口 ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "WealthMatrix.App.1.1"
        )

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,        QColor(CP["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText,    QColor(CP["text"]))
    palette.setColor(QPalette.ColorRole.Base,          QColor(CP["panel"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(CP["panel2"]))
    palette.setColor(QPalette.ColorRole.Text,          QColor(CP["text"]))
    palette.setColor(QPalette.ColorRole.Button,        QColor(CP["panel"]))
    palette.setColor(QPalette.ColorRole.ButtonText,    QColor(CP["text"]))
    palette.setColor(QPalette.ColorRole.Highlight,     QColor(CP["cyan_dim"]))
    app.setPalette(palette)

    win = WealthMatrix()
    win.show()
    sys.exit(app.exec())