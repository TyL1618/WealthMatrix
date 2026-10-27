"""
app.py - 主視窗、Toast 通知、應用程式入口
"""
import sys
import os
import threading
from datetime import datetime, date

# 必須在 QApplication 之前設定（避免 Qt 自動縮放與我們的 S() 函數雙重縮放）
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTabWidget,
    QMessageBox, QPushButton, QDialog, QInputDialog, QLineEdit
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QSize, QUrl
from PyQt6.QtGui import (
    QColor, QPalette, QKeySequence, QShortcut, QIcon, QDesktopServices
)

import wealthmatrix.theme as _theme_module
from wealthmatrix.theme import CP, STYLESHEET, DIALOG_STYLE, S
from wealthmatrix.core.data_manager import (
    DataFetcher, load_data, save_data, pop_undo, push_undo, add_month_record,
    _save_local, register_push_warning_callback, set_cloud_sync_state,
    load_config, save_config,
    BACKUP_DIR, list_backups, load_backup, backup_now, count_records,
    cloud_password_needed, cloud_email, verify_cloud_login, set_cloud_password,
)
from wealthmatrix.core.calc import bank_total, stocks_total, net_worth
from wealthmatrix.core.recurring import apply_recurring
from wealthmatrix.ui.dashboard import DashboardWidget
from wealthmatrix.ui.cashflow import CashflowWidget
from wealthmatrix.ui.charts import ChartsWidget
from wealthmatrix.ui.holdings import HoldingsWidget


# ── Toast 通知（右下角淡出）─────────────────────────────────────────
class Toast(QLabel):
    def __init__(self, msg, parent):
        super().__init__(msg, parent)
        self.setWordWrap(True)
        self.setStyleSheet(
            f"background:#1b2430;border:1px solid {CP['orange']};"
            f"color:{CP['orange']};font-family:'Segoe UI','Microsoft JhengHei',sans-serif;"
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
            f"background:#1b2430;border:1px solid {CP['orange']};"
            f"color:rgba(224,164,88,{max(0,self._opacity):.2f});"
            f"font-family:'Segoe UI','Microsoft JhengHei',sans-serif;"
            f"font-size:{S(11)}px;padding:{S(10)}px {S(14)}px;border-radius:6px;"
        )
        if self._opacity <= 0:
            self._timer.stop()
            self.deleteLater()


class WealthMatrix(QMainWindow):
    def __init__(self):
        super().__init__()
        self.data, self._startup_conflict = load_data()
        self.stock_prices = {}
        self.usd_rate     = self.data.get("usd_rate", 31.5)

        self.fetcher = DataFetcher()
        self.fetcher.prices_ready.connect(self._on_prices)
        self.fetcher.fx_ready.connect(self._on_fx)
        self.fetcher.fetch_error.connect(self._on_fetch_error)

        self.setWindowTitle("WealthMatrix")
        self.setMinimumSize(S(900), S(780))
        self.setStyleSheet(str(STYLESHEET))
        self._set_window_icon()

        self._build_ui()
        self._restore_geometry()

        if not self.data["goals_visible"]:
            self.dashboard.goals_scroll.hide()
            self.dashboard.toggle_goal_btn.setText("展開")

        self.clock_timer = QTimer()
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)

        self.price_timer = QTimer()
        self.price_timer.timeout.connect(self.refresh_prices)
        self.price_timer.start(60_000)

        self.sync_timer = QTimer()
        self.sync_timer.timeout.connect(self._background_sync)
        self.sync_timer.start(5 * 60 * 1000)

        undo_sc = QShortcut(QKeySequence("Ctrl+Z"), self)
        undo_sc.activated.connect(self._undo)

        self._render_all()
        self.refresh_prices()

        register_push_warning_callback(lambda msg: Toast(msg, self))

        QTimer.singleShot(500, self._maybe_record_history)
        QTimer.singleShot(800, self.dashboard.check_dca_reminder)
        if self._startup_conflict:
            QTimer.singleShot(400, self._handle_startup_conflict)

    # ──────────────────────────────────────────────────────────────
    # 視窗 Icon
    # ──────────────────────────────────────────────────────────────
    def _set_window_icon(self):
        # PyInstaller onefile 模式下，_MEIPASS 是解壓暫存目錄；開發時用專案根目錄
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        # app.py 在 wealthmatrix/ 下，往上一層才是專案根目錄
        root = os.path.dirname(base) if not getattr(sys, '_MEIPASS', None) else base
        ico  = os.path.join(root, "icon.ico")
        if os.path.exists(ico):
            self.setWindowIcon(QIcon(ico))

    # ──────────────────────────────────────────────────────────────
    # 視窗幾何
    # ──────────────────────────────────────────────────────────────
    def _restore_geometry(self):
        geo   = self.data.get("window_geometry")
        avail = QApplication.primaryScreen().availableGeometry()

        if geo and len(geo) == 4:
            _, _, w, h = geo
            w = min(w, avail.width())
            h = min(h, avail.height())
        else:
            w, h = S(980), S(900)

        self.resize(QSize(w, h))

        x = avail.left() + (avail.width()  - w) // 2
        y = avail.top()  + (avail.height() - h) // 2
        self.move(QPoint(x, y))

    def closeEvent(self, event):
        pos = self.pos()
        sz  = self.size()
        self.data["window_geometry"] = [pos.x(), pos.y(), sz.width(), sz.height()]
        # 視窗座標只存本地，不推送雲端（避免不同螢幕互相污染位置）
        _save_local(self.data)
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
        title = QLabel("WealthMatrix")
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
        header.addSpacing(S(12))
        settings_btn = QPushButton("⚙")
        settings_btn.setFixedSize(S(28), S(28))
        settings_btn.setStyleSheet(
            f"QPushButton {{ border: 1px solid {CP['border']}; color: {CP['muted']};"
            f" border-radius: {S(4)}px; padding: 0; font-size: {S(13)}px; }}"
            f"QPushButton:hover {{ color: {CP['cyan']}; border-color: {CP['cyan_dim']};"
            f" background: rgba(90,176,232,0.08); }}"
        )
        settings_btn.clicked.connect(self._show_settings)
        header.addWidget(settings_btn)
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
        self.tabs.addTab(self.dashboard, "總覽")

        self.cashflow_w = CashflowWidget(
            data=self.data,
            on_data_changed=self._render_all,
        )
        self.tabs.addTab(self.cashflow_w, "收支")

        self.charts_w = ChartsWidget()
        self.charts_w.clear_hist_btn.clicked.connect(self._clear_history)
        self.tabs.addTab(self.charts_w, "圖表")

        self.holdings_w = HoldingsWidget(
            data=self.data,
            get_fx_rate_fn=lambda: self.usd_rate,
            get_stock_prices_fn=lambda: self.stock_prices,
        )
        self.tabs.addTab(self.holdings_w, "持股")

    # ──────────────────────────────────────────────────────────────
    # 資料替換
    # ──────────────────────────────────────────────────────────────
    def _replace_data(self, new_data):
        """就地替換 self.data 的內容。

        各分頁 widget 在建構時拿到的是同一個 dict 物件，若直接 `self.data = new`
        會讓它們繼續讀寫舊 dict，之後操作會把舊資料存回去覆蓋剛選的資料。
        """
        self.data.clear()
        self.data.update(new_data)
        self.usd_rate = self.data.get("usd_rate", 31.5)
        self.fx_lbl.setText(f"USD/TWD  {self.usd_rate:.2f}")
        self.dashboard.cash_input.setValue(self.data["cash"])

    # ──────────────────────────────────────────────────────────────
    # 計算
    # ──────────────────────────────────────────────────────────────
    def _bank_total(self):
        return bank_total(self.data)

    def _stocks_total(self):
        return stocks_total(self.data, self.stock_prices)

    def _grand_total(self):
        """淨值（銀行 + 現金 + 股票 − 負債）。"""
        return net_worth(self.data, self.stock_prices)

    # ──────────────────────────────────────────────────────────────
    # 渲染
    # ──────────────────────────────────────────────────────────────
    def _render_all(self):
        self.cashflow_w.refresh()
        self.dashboard.render_all(self._grand_total())
        self.holdings_w.refresh_stocks()
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
    def _apply_recurring_now(self):
        """到期的固定收支自動入帳；有新增就存檔並刷新現金流分頁。"""
        added = apply_recurring(self.data)
        if added:
            save_data(self.data)
            self.cashflow_w.refresh()
            Toast(f"已自動入帳 {added} 筆固定收支", self)
        return added

    def _maybe_record_history(self):
        self._apply_recurring_now()
        today = date.today().isoformat()
        total = self._grand_total()
        bank  = self._bank_total()
        cash  = self.data["cash"]
        stock = self._stocks_total()

        history = self.data.setdefault("history", [])
        existing = [h for h in history if h["date"] == today]
        if existing:
            existing[0]["total"] = total
        else:
            history.append({"date": today, "total": total})
        self.data["history"] = sorted(history, key=lambda x: x["date"])[-365:]

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
    # 價格刷新
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
        self.data["usd_rate_date"] = date.today().isoformat()
        self.fx_lbl.setText(f"USD/TWD  {rate:.2f}")

    def _on_prices(self, prices):
        self.stock_prices.update(prices)
        today_str = date.today().isoformat()
        for stock in self.data["stocks"]:
            p = prices.get(stock["ticker"])
            if p is not None:
                stock["last_price"]   = round(p, 2)
                stock["last_updated"] = today_str
        self.dashboard.refresh_lbl.setText(datetime.now().strftime("更新 %H:%M"))
        self._render_all()
        self._maybe_record_history()

    def _on_fetch_error(self, msg):
        Toast(msg, self)

    # ──────────────────────────────────────────────────────────────
    # 設定視窗
    # ──────────────────────────────────────────────────────────────
    def _show_settings(self):
        cfg           = load_config()
        current_scale = cfg.get("ui_scale", None)

        dlg = QDialog(self)
        dlg.setWindowTitle("設定")
        dlg.setStyleSheet(str(DIALOG_STYLE))
        dlg.setFixedWidth(S(360))

        layout = QVBoxLayout(dlg)
        layout.setSpacing(S(14))
        layout.setContentsMargins(S(24), S(20), S(24), S(24))

        lbl = QLabel("介面縮放")
        lbl.setObjectName("section_title")
        layout.addWidget(lbl)

        note = QLabel("重新啟動後生效")
        note.setObjectName("muted")
        layout.addWidget(note)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(S(6))

        scales = [0.8, 1.0, 1.25, 1.5, 1.75]
        labels = ["80%", "100%", "125%", "150%", "175%"]

        def _make_handler(sv, label):
            def handler():
                save_config({"ui_scale": sv})
                Toast(f"已儲存（{label}），重新啟動後生效", self)
                dlg.accept()
            return handler

        for val, label in zip(scales, labels):
            btn = QPushButton(label)
            is_current = (
                current_scale is not None
                and abs(float(current_scale) - val) < 0.01
            )
            if is_current:
                btn.setStyleSheet(
                    f"border: 1px solid {CP['cyan']}; color: {CP['cyan']};"
                    f" background: rgba(90,176,232,0.12);"
                    f" border-radius: {S(4)}px; padding: {S(5)}px {S(8)}px;"
                    f" font-family: 'Segoe UI','Microsoft JhengHei',sans-serif; font-size: {S(11)}px;"
                )
            btn.clicked.connect(_make_handler(val, label))
            btn_row.addWidget(btn)

        layout.addLayout(btn_row)

        bk_title = QLabel("資料備份")
        bk_title.setObjectName("section_title")
        layout.addWidget(bk_title)

        bk_note = QLabel(
            f"每天自動備份一份，保留最近 30 天（目前 {len(list_backups())} 份）"
        )
        bk_note.setObjectName("muted")
        bk_note.setWordWrap(True)
        layout.addWidget(bk_note)

        bk_row = QHBoxLayout()
        bk_row.setSpacing(S(6))
        open_btn = QPushButton("開啟備份資料夾")
        open_btn.clicked.connect(self._open_backup_folder)
        restore_btn = QPushButton("從備份還原…")

        def _restore():
            dlg.accept()
            QTimer.singleShot(0, self._restore_backup)

        restore_btn.clicked.connect(_restore)
        bk_row.addWidget(open_btn)
        bk_row.addWidget(restore_btn)
        layout.addLayout(bk_row)
        dlg.exec()

    def _open_backup_folder(self):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(BACKUP_DIR))

    def _restore_backup(self):
        from wealthmatrix.core.data_manager import _apply_migrations, _default_data
        entries = []
        for label, path in list_backups():
            raw = load_backup(path)
            if raw:
                entries.append((f"{label}　（{count_records(raw)} 筆）", raw))
        if not entries:
            Toast("目前沒有可用的備份。", self)
            return

        item, ok = QInputDialog.getItem(
            self, "從備份還原", "選擇要還原的備份：",
            [text for text, _ in entries], 0, False,
        )
        if not ok:
            return
        raw = dict(entries[[text for text, _ in entries].index(item)][1])

        if QMessageBox.question(
            self, "確認還原",
            f"將用「{item}」覆蓋目前資料，並同步到雲端。\n"
            "目前的資料會先另存一份（pre-restore），之後仍可還原回來。\n\n確定還原？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        backup_now("pre-restore")
        raw.pop("undo_stack", None)
        raw["window_geometry"] = self.data.get("window_geometry")
        self._replace_data(_apply_migrations(raw, _default_data()))
        # 明確選擇還原：解除筆數鎖定，允許推送；save_data 會蓋上新時間戳，雲端與其他裝置會跟進
        set_cloud_sync_state(True, 0)
        save_data(self.data)
        self._render_all()
        self.cashflow_w.refresh()
        Toast(f"已還原備份：{item}", self)

    # ──────────────────────────────────────────────────────────────
    # 啟動時資料衝突處理
    # ──────────────────────────────────────────────────────────────
    def _handle_startup_conflict(self):
        info = self._startup_conflict
        if not info:
            return

        local_ts  = info["local_ts"][:19].replace("T", " ")
        cloud_ts  = info["cloud_ts"][:19].replace("T", " ")
        local_cnt = info["local_count"]
        cloud_cnt = info["cloud_count"]

        msg = (
            "偵測到資料衝突：\n\n"
            f"  本地：{local_cnt} 筆記錄，最後更新 {local_ts}\n"
            f"  雲端：{cloud_cnt} 筆記錄，最後更新 {cloud_ts}\n\n"
            "本地資料的時間戳較新，但筆數明顯少於雲端，\n"
            "可能是從其他裝置同步後又在舊電腦離線操作所致。\n\n"
            "目前已載入雲端資料（較安全）。\n"
            "是否改用本地資料？（將覆蓋雲端）"
        )

        ret = QMessageBox.warning(
            self, "資料同步衝突",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,   # 預設保留雲端
        )

        if ret == QMessageBox.StandardButton.Yes:
            from wealthmatrix.core.data_manager import _apply_migrations, _default_data
            self._replace_data(
                _apply_migrations(dict(info["local_data"]), _default_data())
            )
            # 明確選擇本地：解除筆數鎖定，允許推送
            set_cloud_sync_state(True, 0)
            save_data(self.data)
            self._render_all()
            Toast("已切換至本地資料並同步至雲端", self)
        else:
            Toast("已使用雲端資料", self)

    # ──────────────────────────────────────────────────────────────
    # 背景雲端同步（每 5 分鐘）
    # ──────────────────────────────────────────────────────────────
    def _background_sync(self):
        from wealthmatrix.core.data_manager import _load_cloud_cfg, _cloud_pull
        def _pull():
            sb_url, sb_key, sb_email, sb_pwd = _load_cloud_cfg()
            if not sb_url:
                return
            cloud_raw = _cloud_pull(sb_url, sb_key, sb_email, sb_pwd)
            if not cloud_raw:
                return
            cloud_ts = cloud_raw.get("_updated", "")
            local_ts = self.data.get("_updated", "")
            if cloud_ts <= local_ts:
                return
            cloud_raw["window_geometry"] = self.data.get("window_geometry")
            self._sync_pending = cloud_raw
            QTimer.singleShot(0, self._apply_sync)
        threading.Thread(target=_pull, daemon=True).start()

    def _apply_sync(self):
        from wealthmatrix.core.data_manager import _apply_migrations, _default_data
        cloud_raw = getattr(self, "_sync_pending", None)
        if not cloud_raw:
            return
        self._sync_pending = None
        self._replace_data(_apply_migrations(cloud_raw, _default_data()))
        self._render_all()
        self.cashflow_w.refresh()
        Toast("已從雲端同步最新資料", self)

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

        elif action == "del_liability":
            item = payload["item"]
            idx  = payload.get("idx", len(self.data["liabilities"]))
            self.data["liabilities"].insert(min(idx, len(self.data["liabilities"])), item)
            if payload.get("rule"):
                self.data.setdefault("recurring", []).append(payload["rule"])
            save_data(self.data)
            self._render_all()
            Toast(f"已復原：負債「{item['name']}」", self)

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


def run() -> int:
    """建立 QApplication、設定縮放、啟動主視窗，回傳 exit code"""
    app = QApplication.instance() or QApplication(sys.argv)

    # DPI 縮放（96 DPI = 1.0x 基準，Windows 標準 100%）
    dpi        = app.primaryScreen().logicalDotsPerInch()
    auto_scale = float(os.environ.get("FORCE_SCALE", round(dpi / 96.0, 2)))
    _cfg = load_config()
    if "ui_scale" in _cfg:
        auto_scale = max(0.8, min(2.5, float(_cfg["ui_scale"])))
    _theme_module.set_scale(auto_scale)

    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "WealthMatrix.App.1.1"
        )

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

    _ask_cloud_password_if_needed()

    win = WealthMatrix()
    win.show()
    return app.exec()


def _ask_cloud_password_if_needed():
    """wm_cloud.json 是從別台電腦複製來的（加密的密碼在這台解不開）→ 問一次密碼，存成這台電腦的加密版。

    取消或連續輸入錯誤就略過：程式照常啟動，只是雲端同步暫停（不會用空資料覆蓋雲端）。
    """
    if not cloud_password_needed():
        return
    email = cloud_email()
    prompt = f"這台電腦第一次使用雲端同步。\n請輸入帳號 {email} 的密碼："
    for _ in range(3):
        pw, ok = QInputDialog.getText(
            None, "雲端同步登入", prompt, QLineEdit.EchoMode.Password
        )
        if not ok:
            return
        if not pw:
            continue
        result = verify_cloud_login(pw)
        if result == "bad":
            prompt = f"密碼不正確，請再試一次。\n帳號 {email}："
            continue
        set_cloud_password(pw)        # 'ok' 或連不上（無法驗證）都先存起來
        return
    QMessageBox.warning(
        None, "雲端同步", "密碼連續輸入錯誤，這次先不啟用雲端同步（資料仍會存在本機）。"
    )
