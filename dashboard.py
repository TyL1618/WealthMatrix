"""
dashboard.py - 儀表板分頁 Widget
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QProgressBar,
    QDoubleSpinBox, QSizePolicy, QMessageBox
)
from PyQt6.QtCore import Qt

from styles import (
    CP, CpPanel, section_label, muted_label,
    fmt_ntd, fmt_pnl, fmt_pct, pnl_color, goal_color, S
)
from data_manager import save_data, push_undo
from dialogs import (
    AddBankDialog, EditBankDialog, AddStockDialog,
    EditStockDialog, AddPositionDialog, AddGoalDialog,
    DCASettingsDialog, DcaReminderPopup
)


class DashboardWidget(QWidget):
    # ★ 修正二：新增 on_data_changed 參數
    def __init__(self, data, get_stock_prices_fn, refresh_prices_fn,
                 on_data_changed=None, parent=None):
        super().__init__(parent)
        self.data = data
        self.get_stock_prices  = get_stock_prices_fn
        self.refresh_prices    = refresh_prices_fn
        # 任何金錢異動後呼叫此 callback，讓 main 重新計算並渲染總資產
        self._on_data_changed  = on_data_changed or (lambda: None)
        self._build_ui()

    # ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S(10), S(10), S(10), S(10))
        lay.setSpacing(S(10))

        # Total bar
        total_panel = CpPanel(accent=CP["cyan"])
        total_layout = QHBoxLayout(total_panel)
        total_layout.setContentsMargins(S(16), S(10), S(16), S(10))
        left_col = QVBoxLayout()
        left_col.addWidget(section_label("TOTAL ASSET VALUE"))
        left_col.addWidget(muted_label("銀行 + 現金 + 投資"))
        self.total_lbl = QLabel("NT$0")
        self.total_lbl.setObjectName("total_val")
        right_col = QVBoxLayout()
        right_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right_col.addWidget(self.total_lbl)
        total_layout.addLayout(left_col)
        total_layout.addStretch()
        total_layout.addLayout(right_col)
        lay.addWidget(total_panel)

        # 中間兩格
        mid_row = QHBoxLayout()
        mid_row.setSpacing(S(10))
        mid_row.setContentsMargins(0, 0, 0, 0)

        # 銀行面板
        bank_panel = CpPanel(accent=CP["cyan"])
        bank_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        bank_vbox = QVBoxLayout(bank_panel)
        bank_vbox.setContentsMargins(S(12), S(10), S(12), S(10))
        bank_vbox.setSpacing(S(0))
        bank_header = QHBoxLayout()
        bank_header.addWidget(section_label("BANK ACCOUNTS"))
        bank_header.addStretch()
        add_bank_btn = QPushButton("+ ADD")
        add_bank_btn.clicked.connect(self.add_bank)
        bank_header.addWidget(add_bank_btn)
        bank_vbox.addLayout(bank_header)
        bank_vbox.addSpacing(S(6))
        self.bank_scroll = QScrollArea()
        self.bank_scroll.setWidgetResizable(True)
        self.bank_scroll.setFixedHeight(S(90))   # 約顯示 2~3 行，多的滾輪捲
        self.bank_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.bank_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.bank_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.bank_list_widget = QWidget()
        self.bank_list_layout = QVBoxLayout(self.bank_list_widget)
        self.bank_list_layout.setSpacing(S(2))
        self.bank_list_layout.setContentsMargins(0, 0, 0, 0)
        self.bank_list_layout.addStretch()
        self.bank_scroll.setWidget(self.bank_list_widget)
        bank_vbox.addWidget(self.bank_scroll)
        bank_vbox.addSpacing(S(6))
        # 分隔線（用 stylesheet 畫，不用獨立 QFrame 避免位置偏移）
        bank_footer_widget = QWidget()
        bank_footer_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bank_footer_widget.setFixedHeight(S(36))
        bank_footer_widget.setStyleSheet(
            f"background:{CP['panel']}; border:none;"
            f"border-top: 1px solid {CP['border']};"
        )
        bank_footer = QHBoxLayout(bank_footer_widget)
        bank_footer.setContentsMargins(0, S(4), 0, S(4))
        bank_footer.setSpacing(S(8))
        self._bank_cnt_lbl = muted_label(f"TOTAL  ({len(self.data['banks'])} accts)")
        bank_footer.addWidget(self._bank_cnt_lbl)
        bank_footer.addStretch()
        self.bank_total_lbl = QLabel("NT$0")
        self.bank_total_lbl.setObjectName("bank_total")
        self.bank_total_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        bank_footer.addWidget(self.bank_total_lbl)
        bank_vbox.addWidget(bank_footer_widget)
        mid_row.addWidget(bank_panel, 3)

        # 現金面板
        cash_panel = CpPanel(accent=CP["green"])
        cash_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        cash_vbox = QVBoxLayout(cash_panel)
        cash_vbox.setContentsMargins(S(12), S(10), S(12), S(10))
        cash_vbox.setSpacing(S(6))
        cash_vbox.addWidget(section_label("現金"))
        self.cash_lbl = QLabel("NT$0")
        self.cash_lbl.setObjectName("cash_val")
        cash_vbox.addWidget(self.cash_lbl)
        cash_input_row = QHBoxLayout()
        self.cash_input = QDoubleSpinBox()
        self.cash_input.setRange(0, 99_999_999)
        self.cash_input.setDecimals(0)
        self.cash_input.setSingleStep(100)
        self.cash_input.setPrefix("NT$ ")
        self.cash_input.setValue(self.data["cash"])
        set_cash_btn = QPushButton("SET")
        set_cash_btn.setObjectName("btn_green")
        set_cash_btn.clicked.connect(self.set_cash)
        cash_input_row.addWidget(self.cash_input)
        cash_input_row.addWidget(set_cash_btn)
        cash_vbox.addLayout(cash_input_row)
        mid_row.addWidget(cash_panel, 2)
        lay.addLayout(mid_row)

        # 股票面板（全寬）
        stock_panel = CpPanel(accent=CP["pink"])
        stock_vbox = QVBoxLayout(stock_panel)
        stock_vbox.setContentsMargins(S(12), S(10), S(12), S(10))
        stock_vbox.setSpacing(S(4))
        stock_header = QHBoxLayout()
        stock_header.addWidget(section_label("ETF / STOCKS PORTFOLIO"))
        stock_header.addStretch()
        self.stock_total_lbl = QLabel("NT$0")
        self.stock_total_lbl.setObjectName("stock_total")
        self.refresh_lbl = QLabel("")
        self.refresh_lbl.setObjectName("muted")
        stock_header.addWidget(self.refresh_lbl)
        stock_header.addWidget(self.stock_total_lbl)
        refresh_btn = QPushButton("↻ REFRESH")
        refresh_btn.clicked.connect(self.refresh_prices)
        add_stock_btn = QPushButton("+ ADD")
        add_stock_btn.clicked.connect(self.add_stock)
        stock_header.addWidget(refresh_btn)
        stock_header.addWidget(add_stock_btn)
        stock_vbox.addLayout(stock_header)
        self.stock_scroll = QScrollArea()
        self.stock_scroll.setWidgetResizable(True)
        self.stock_scroll.setFixedHeight(S(110))
        self.stock_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.stock_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.stock_list_widget = QWidget()
        self.stock_list_layout = QVBoxLayout(self.stock_list_widget)
        self.stock_list_layout.setSpacing(S(2))
        self.stock_list_layout.setContentsMargins(0, 0, 0, 0)
        self.stock_list_layout.addStretch()
        self.stock_scroll.setWidget(self.stock_list_widget)
        stock_vbox.addWidget(self.stock_scroll)
        note = muted_label(
            "* 股價透過 Yahoo Finance 即時取得；台股格式 0050.TW，美股直接輸入 AAPL（自動換算台幣）"
        )
        stock_vbox.addWidget(note)
        lay.addWidget(stock_panel)

        # 目標進度條面板
        self.goal_panel = CpPanel(accent=CP["blue"])
        goal_vbox = QVBoxLayout(self.goal_panel)
        goal_vbox.setContentsMargins(S(12), S(10), S(12), S(10))
        goal_vbox.setSpacing(S(6))
        goal_header = QHBoxLayout()
        goal_header.addWidget(section_label("TARGET PROGRESS"))
        goal_header.addStretch()
        add_goal_btn = QPushButton("+ ADD GOAL")
        add_goal_btn.setObjectName("btn_blue")
        add_goal_btn.clicked.connect(self.add_goal)
        self.toggle_goal_btn = QPushButton("HIDE")
        self.toggle_goal_btn.setObjectName("btn_blue")
        self.toggle_goal_btn.clicked.connect(self.toggle_goals)
        dca_btn = QPushButton("⚡ DCA 提醒")
        dca_btn.setObjectName("btn_gold")
        dca_btn.clicked.connect(self.open_dca_settings)
        goal_header.addWidget(dca_btn)
        goal_header.addWidget(add_goal_btn)
        goal_header.addWidget(self.toggle_goal_btn)
        goal_vbox.addLayout(goal_header)
        self.goals_scroll = QScrollArea()
        self.goals_scroll.setWidgetResizable(True)
        self.goals_scroll.setFixedHeight(S(200))
        self.goals_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.goals_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.goals_container = QWidget()
        self.goals_vbox = QVBoxLayout(self.goals_container)
        self.goals_vbox.setSpacing(S(12))
        self.goals_vbox.setContentsMargins(0, S(4), S(4), S(4))
        self.goals_vbox.addStretch()
        self.goals_scroll.setWidget(self.goals_container)
        goal_vbox.addWidget(self.goals_scroll)
        lay.addWidget(self.goal_panel)

    # ──────────────────────────────────────────────────────────────
    # 渲染
    # ──────────────────────────────────────────────────────────────
    def render_banks(self):
        while self.bank_list_layout.count() > 1:
            item = self.bank_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, bank in enumerate(self.data["banks"]):
            row = QHBoxLayout()
            name_lbl = QLabel(bank["name"])
            name_lbl.setStyleSheet(f"color:{CP['text']};font-size:{S(13)}px;")
            amt_lbl = QLabel(fmt_ntd(bank["amount"]))
            amt_lbl.setStyleSheet(
                f"color:{CP['cyan']};font-family:'Courier New',monospace;font-size:{S(13)}px;"
            )
            edit_btn = QPushButton("✎")
            edit_btn.setObjectName("btn_pink")
            edit_btn.setFixedWidth(S(28))
            edit_btn.setStyleSheet(
                f"color:{CP['cyan_dim']};border-color:{CP['border']};"
                f"font-size:{S(13)}px;padding:{S(2)}px {S(4)}px;"
            )
            edit_btn.clicked.connect(lambda _, idx=i: self.edit_bank(idx))
            del_btn = QPushButton("×")
            del_btn.setObjectName("btn_pink")
            del_btn.setFixedWidth(S(28))
            del_btn.clicked.connect(lambda _, idx=i: self.del_bank(idx))
            row.addWidget(name_lbl)
            row.addStretch()
            row.addWidget(amt_lbl)
            row.addWidget(edit_btn)
            row.addWidget(del_btn)
            container = QWidget()
            container.setLayout(row)
            container.setStyleSheet(
                f"border-bottom:1px solid {CP['border']}; background:transparent;"
            )
            self.bank_list_layout.insertWidget(self.bank_list_layout.count() - 1, container)

        bank_total = sum(b["amount"] for b in self.data["banks"])
        self.bank_total_lbl.setText(fmt_ntd(bank_total))
        self._bank_cnt_lbl.setText(f"TOTAL  ({len(self.data['banks'])} accts)")

    def render_stocks(self):
        prices = self.get_stock_prices()
        while self.stock_list_layout.count() > 1:
            item = self.stock_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for i, s in enumerate(self.data["stocks"]):
            price  = prices.get(s["ticker"])
            cost   = s.get("cost", 0)
            shares = s["shares"]

            # ── 持有成本：優先用存好的 holding_cost，否則回退舊資料 ──
            holding_cost = s.get("holding_cost", round(cost * shares))

            # ── 均價（買入均價，含手續費）────────────────────────────
            holding_cost = s.get("holding_cost", round(cost * shares))
            avg_cost = holding_cost / shares if shares > 0 else 0

            if price is not None:
                val = price * shares
                if cost > 0:
                    # 損益 = 現值 - 持有成本（含手續費）
                    pnl = val - holding_cost
                    pct = pnl / holding_cost * 100 if holding_cost else 0
                else:
                    pnl = pct = None
                detail_txt = f"{int(shares):,} 股  ×  NT${price:,.2f}"
                val_txt    = fmt_ntd(val)
                val_color  = CP["green"]
            else:
                pnl = pct = None
                detail_txt = f"{int(shares):,} 股  ×  取得中..."
                val_txt    = "---"
                val_color  = CP["muted"]

            wrapper = QWidget()
            wrapper.setStyleSheet(
                f"border-bottom:1px solid {CP['border']}; background:transparent;"
            )
            # ── 單行佈局：ticker | 股數×價 | 損益 | 持有成本 | 均價 ‖ 現值 | 按鈕群 ──
            row = QHBoxLayout(wrapper)
            row.setSpacing(S(10))
            row.setContentsMargins(0, S(5), 0, S(5))

            # 代號
            ticker_lbl = QLabel(s["ticker"])
            ticker_lbl.setStyleSheet(
                f"color:{CP['cyan']};font-family:'Courier New',monospace;"
                f"font-size:{S(13)}px;min-width:{S(80)}px;font-weight:bold;"
            )
            row.addWidget(ticker_lbl)

            # 股數 × 現價
            detail_lbl = QLabel(detail_txt)
            detail_lbl.setStyleSheet(
                f"color:{CP['muted']};font-size:{S(12)}px;font-family:'Courier New',monospace;"
            )
            row.addWidget(detail_lbl)

            # 分隔
            sep1 = QLabel("│")
            sep1.setStyleSheet(f"color:{CP['border']};font-size:{S(12)}px;")
            row.addWidget(sep1)

            # 損益（有成本才顯示）
            if pnl is not None and cost > 0:
                pnl_lbl = QLabel(f"損益 {fmt_pnl(pnl)} ({fmt_pct(pct)})")
                pnl_lbl.setStyleSheet(
                    f"color:{pnl_color(pnl)};font-size:{S(12)}px;"
                    f"font-family:'Courier New',monospace;"
                )
                row.addWidget(pnl_lbl)

                sep2 = QLabel("│")
                sep2.setStyleSheet(f"color:{CP['border']};font-size:{S(12)}px;")
                row.addWidget(sep2)

                # 持有成本 + 均價合併一欄
                cost_info = QLabel(f"成本 NT${int(holding_cost):,}  均價 {avg_cost:,.2f}")
                cost_info.setStyleSheet(
                    f"color:{CP['muted']};font-size:{S(11)}px;"
                    f"font-family:'Courier New',monospace;"
                )
                row.addWidget(cost_info)

            row.addStretch()

            # 現值
            val_lbl = QLabel(val_txt)
            val_lbl.setStyleSheet(
                f"color:{val_color};font-family:'Courier New',monospace;"
                f"font-size:{S(13)}px;font-weight:bold;"
            )
            row.addWidget(val_lbl)

            # 按鈕群
            pos_btn = QPushButton("+倉")
            pos_btn.setObjectName("btn_green")
            pos_btn.setFixedWidth(S(38))
            pos_btn.setStyleSheet(
                f"color:{CP['green']};border-color:rgba(0,255,136,0.4);"
                f"font-size:{S(11)}px;padding:{S(2)}px {S(4)}px;border-radius:3px;"
            )
            pos_btn.clicked.connect(lambda _, idx=i: self.add_position(idx))
            edit_btn = QPushButton("✎")
            edit_btn.setObjectName("btn_pink")
            edit_btn.setFixedWidth(S(28))
            edit_btn.setStyleSheet(
                f"color:{CP['cyan_dim']};border-color:{CP['border']};"
                f"font-size:{S(13)}px;padding:{S(2)}px {S(4)}px;"
            )
            edit_btn.clicked.connect(lambda _, idx=i: self.edit_stock(idx))
            del_btn = QPushButton("×")
            del_btn.setObjectName("btn_pink")
            del_btn.setFixedWidth(S(28))
            del_btn.clicked.connect(lambda _, idx=i: self.del_stock(idx))

            row.addWidget(pos_btn)
            row.addWidget(edit_btn)
            row.addWidget(del_btn)

            self.stock_list_layout.insertWidget(
                self.stock_list_layout.count() - 1, wrapper
            )

        prices_copy = self.get_stock_prices()
        stock_total = sum(
            prices_copy.get(s["ticker"], s.get("cost", 0)) * s["shares"]
            for s in self.data["stocks"]
        )
        self.stock_total_lbl.setText(fmt_ntd(stock_total))

    def render_goals(self):
        while self.goals_vbox.count() > 1:
            item = self.goals_vbox.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        base = sum(b["amount"] for b in self.data["banks"]) + self.data["cash"]

        if not self.data["goals"]:
            lbl = QLabel("— NO TARGETS SET —")
            lbl.setStyleSheet(
                f"color:{CP['muted']};font-family:'Courier New',monospace;font-size:{S(13)}px;"
            )
            self.goals_vbox.insertWidget(0, lbl)
            return

        for i, goal in enumerate(self.data["goals"]):
            pct = min(100.0, (base / goal["target"]) * 100) if goal["target"] > 0 else 0
            col = goal_color(pct)

            wrapper = QWidget()
            wrapper.setStyleSheet("background:transparent;")
            vbox = QVBoxLayout(wrapper)
            vbox.setSpacing(S(4)); vbox.setContentsMargins(0, 0, 0, 0)

            top_row = QHBoxLayout()
            name_lbl = QLabel(goal["name"])
            name_lbl.setStyleSheet(f"color:{CP['text']};font-size:{S(14)}px;font-weight:bold;")
            pct_lbl = QLabel(f"{pct:.1f}%")
            pct_lbl.setStyleSheet(
                f"color:{col};font-family:'Courier New',monospace;"
                f"font-size:{S(13)}px;font-weight:bold;"
            )
            del_btn = QPushButton("×")
            del_btn.setObjectName("btn_pink")
            del_btn.setFixedWidth(S(24))
            del_btn.clicked.connect(lambda _, idx=i: self.del_goal(idx))
            top_row.addWidget(name_lbl)
            top_row.addStretch()
            top_row.addWidget(pct_lbl)
            top_row.addWidget(del_btn)
            vbox.addLayout(top_row)

            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(pct * 10))
            bar.setTextVisible(False)
            bar.setFixedHeight(S(18))
            bar.setStyleSheet(f"""
                QProgressBar {{
                    background: rgba(255,255,255,0.06);
                    border: 1px solid rgba(255,255,255,0.15);
                    border-radius: 8px;
                }}
                QProgressBar::chunk {{
                    background-color: {col};
                    border-radius: 8px;
                }}
            """)
            vbox.addWidget(bar)

            nums_row = QHBoxLayout()
            cur_lbl = QLabel(fmt_ntd(base))
            cur_lbl.setStyleSheet(
                f"color:{CP['muted']};font-size:{S(12)}px;font-family:'Courier New',monospace;"
            )
            tgt_lbl = QLabel(f"目標 {fmt_ntd(goal['target'])}")
            tgt_lbl.setStyleSheet(
                f"color:{CP['muted']};font-size:{S(12)}px;font-family:'Courier New',monospace;"
            )
            nums_row.addWidget(cur_lbl)
            nums_row.addStretch()
            nums_row.addWidget(tgt_lbl)
            vbox.addLayout(nums_row)

            self.goals_vbox.insertWidget(self.goals_vbox.count() - 1, wrapper)

    def render_all(self, grand_total):
        self.render_banks()
        self.cash_lbl.setText(fmt_ntd(self.data["cash"]))
        self.render_stocks()
        self.total_lbl.setText(fmt_ntd(grand_total))
        self.render_goals()

    # ──────────────────────────────────────────────────────────────
    # 操作：銀行
    # ──────────────────────────────────────────────────────────────
    def add_bank(self):
        dlg = AddBankDialog(self)
        if dlg.exec():
            d = dlg.get_data()
            if d["name"]:
                self.data["banks"].append(d)
                save_data(self.data)
                self._on_data_changed()   # ★ 即時更新總資產

    def edit_bank(self, idx):
        dlg = EditBankDialog(self.data["banks"][idx], self)
        if dlg.exec():
            self.data["banks"][idx]["amount"] = dlg.get_amount()
            save_data(self.data)
            self._on_data_changed()       # ★ 即時更新總資產

    def del_bank(self, idx):
        name = self.data["banks"][idx]["name"]
        if QMessageBox.question(
            self, "確認", f"刪除 {name}？（可按 Ctrl+Z 復原）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            push_undo(self.data, "del_bank", {"bank": self.data["banks"][idx], "idx": idx})
            self.data["banks"].pop(idx)
            save_data(self.data)
            self._on_data_changed()

    def set_cash(self):
        self.data["cash"] = self.cash_input.value()
        save_data(self.data)
        self._on_data_changed()           # ★ 即時更新總資產

    # ──────────────────────────────────────────────────────────────
    # 操作：股票
    # ──────────────────────────────────────────────────────────────
    def add_stock(self):
        dlg = AddStockDialog(self)
        if dlg.exec():
            d = dlg.get_data()
            if d["ticker"] and d["shares"] > 0:
                self.data["stocks"].append(d)
                save_data(self.data)
                self.refresh_prices()     # 新增股票仍觸發價格抓取（內部會呼叫 _render_all）

    def edit_stock(self, idx):
        dlg = EditStockDialog(self.data["stocks"][idx], self)
        if dlg.exec():
            self.data["stocks"][idx]["shares"] = dlg.get_data()["shares"]
            save_data(self.data)
            self._on_data_changed()       # ★ 即時更新總資產

    def add_position(self, idx):
        dlg = AddPositionDialog(self.data["stocks"][idx], self)
        if dlg.exec():
            d = dlg.get_data()
            self.data["stocks"][idx]["shares"]       = d["shares"]
            self.data["stocks"][idx]["cost"]         = d["cost"]
            self.data["stocks"][idx]["holding_cost"] = d["holding_cost"]   # ★ 累計總持有成本
            save_data(self.data)
            self._on_data_changed()

    def del_stock(self, idx):
        ticker = self.data["stocks"][idx]["ticker"]
        if QMessageBox.question(
            self, "確認", f"刪除 {ticker}？（可按 Ctrl+Z 復原）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            push_undo(self.data, "del_stock", {"stock": self.data["stocks"][idx], "idx": idx})
            self.data["stocks"].pop(idx)
            save_data(self.data)
            self._on_data_changed()

    # ──────────────────────────────────────────────────────────────
    # 操作：目標
    # ──────────────────────────────────────────────────────────────
    def add_goal(self):
        dlg = AddGoalDialog(self)
        if dlg.exec():
            d = dlg.get_data()
            if d["name"] and d["target"] > 0:
                self.data["goals"].append(d)
                save_data(self.data)
                self.render_goals()

    def del_goal(self, idx):
        push_undo(self.data, "del_goal", {"goal": self.data["goals"][idx], "idx": idx})
        self.data["goals"].pop(idx)
        save_data(self.data)
        self.render_goals()

    def toggle_goals(self):
        self.data["goals_visible"] = not self.data["goals_visible"]
        if self.data["goals_visible"]:
            self.goals_scroll.show()
            self.toggle_goal_btn.setText("HIDE")
        else:
            self.goals_scroll.hide()
            self.toggle_goal_btn.setText("SHOW")
        save_data(self.data)

    def open_dca_settings(self):
        dlg = DCASettingsDialog(self.data["dca_reminder"], self)
        if dlg.exec():
            self.data["dca_reminder"].update(dlg.get_data())
            save_data(self.data)

    def check_dca_reminder(self):
        from datetime import date
        dca = self.data["dca_reminder"]
        if not dca.get("enabled"):
            return
        today = date.today()
        if today.day != dca.get("day"):
            return
        if dca.get("last_reminded") == today.isoformat():
            return
        dlg = DcaReminderPopup(dca["day"], self)
        dlg.exec()
        self.data["dca_reminder"]["last_reminded"] = today.isoformat()
        save_data(self.data)