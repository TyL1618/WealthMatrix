"""
cashflow.py - 現金流分頁 Widget
"""
from datetime import date

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QComboBox, QMessageBox
)
from PyQt6.QtCore import Qt

from wealthmatrix.theme import CP, CpPanel, section_label, muted_label, fmt_ntd, pnl_color, S
from wealthmatrix.core.data_manager import (
    save_data, get_month_records, add_month_record,
    delete_month_record, update_month_record,
    get_year_summary, get_available_years, push_undo
)
from wealthmatrix.ui.dialogs import AddCashflowDialog, EditCashflowDialog


class CashflowWidget(QWidget):
    def __init__(self, data, on_data_changed=None, parent=None):
        super().__init__(parent)
        self.data = data
        self._on_data_changed = on_data_changed or (lambda: None)

        today = date.today()
        self._sel_year  = today.year
        self._sel_month = today.month
        self._view_mode = "month"

        self._build_ui()
        self.refresh()

    # ──────────────────────────────────────────────────────────────
    # UI 建構
    # ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(S(10), S(10), S(10), S(10))
        root.setSpacing(S(10))

        # ── 選單列 ──────────────────────────────────────────────
        ctrl_panel = CpPanel(accent=CP["cyan"])
        ctrl_lay = QHBoxLayout(ctrl_panel)
        ctrl_lay.setContentsMargins(S(14), S(8), S(14), S(8))
        ctrl_lay.setSpacing(S(10))

        ctrl_lay.addWidget(section_label("PERIOD"))

        self.year_combo = QComboBox()
        self.year_combo.setFixedWidth(S(90))
        self.year_combo.currentTextChanged.connect(self._on_year_changed)
        ctrl_lay.addWidget(self.year_combo)

        self.month_combo = QComboBox()
        self.month_combo.setMinimumWidth(S(85))
        self.month_combo.setMaximumWidth(S(110))   # fix: was missing S()
        for m in range(1, 13):
            self.month_combo.addItem(f"{m:02d} 月", m)
        self.month_combo.currentIndexChanged.connect(self._on_month_changed)
        ctrl_lay.addWidget(self.month_combo)

        ctrl_lay.addStretch()

        self.month_btn = QPushButton("月收支")
        self.month_btn.setCheckable(True)
        self.month_btn.setChecked(True)
        self.month_btn.clicked.connect(lambda: self._set_view("month"))

        self.year_btn = QPushButton("年總覽")
        self.year_btn.setCheckable(True)
        self.year_btn.clicked.connect(lambda: self._set_view("year"))

        for btn in [self.month_btn, self.year_btn]:
            btn.setFixedWidth(S(76))
            ctrl_lay.addWidget(btn)

        root.addWidget(ctrl_panel)

        # ── 摘要列 ──────────────────────────────────────────────
        summary_panel = CpPanel(accent=CP["green"])
        sum_lay = QHBoxLayout(summary_panel)
        sum_lay.setContentsMargins(S(16), S(10), S(16), S(10))

        self.cf_income_lbl  = QLabel("NT$0")
        self.cf_expense_lbl = QLabel("NT$0")
        self.cf_net_lbl     = QLabel("NT$0")
        self.sum_period_lbl = muted_label("")

        for lbl in [self.cf_income_lbl, self.cf_expense_lbl, self.cf_net_lbl]:
            lbl.setStyleSheet(
                f"font-family:'Courier New',monospace;font-size:{S(18)}px;"
                f"font-weight:bold;color:{CP['text']};"
            )

        def col_block(label_txt, val_lbl):
            b = QVBoxLayout()
            b.addWidget(section_label(label_txt))
            b.addWidget(val_lbl)
            return b

        sum_lay.addLayout(col_block("收入", self.cf_income_lbl))
        sum_lay.addStretch()
        _sep = QFrame(); _sep.setFrameShape(QFrame.Shape.VLine)
        _sep.setStyleSheet(f"color:{CP['border']};")
        sum_lay.addWidget(_sep)
        sum_lay.addStretch()
        sum_lay.addLayout(col_block("支出", self.cf_expense_lbl))
        sum_lay.addStretch()
        _sep2 = QFrame(); _sep2.setFrameShape(QFrame.Shape.VLine)
        _sep2.setStyleSheet(f"color:{CP['border']};")
        sum_lay.addWidget(_sep2)
        sum_lay.addStretch()
        sum_lay.addLayout(col_block("淨現金流", self.cf_net_lbl))
        root.addWidget(summary_panel)

        # ── 工具列 ──────────────────────────────────────────────
        self.tool_row_widget = QWidget()
        tool_row = QHBoxLayout(self.tool_row_widget)
        tool_row.setContentsMargins(0, 0, 0, 0)
        self.period_title_lbl = section_label("")
        tool_row.addWidget(self.period_title_lbl)
        tool_row.addStretch()
        self.add_cf_btn = QPushButton("+ ADD RECORD")
        self.add_cf_btn.setObjectName("btn_green")
        self.add_cf_btn.clicked.connect(self.add_cashflow)
        tool_row.addWidget(self.add_cf_btn)
        root.addWidget(self.tool_row_widget)

        # ── 月記錄清單 ──────────────────────────────────────────
        self.cf_scroll = QScrollArea()
        self.cf_scroll.setWidgetResizable(True)
        self.cf_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.cf_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cf_list_widget = QWidget()
        self.cf_list_layout = QVBoxLayout(self.cf_list_widget)
        self.cf_list_layout.setSpacing(S(2))
        self.cf_list_layout.setContentsMargins(0, 0, 0, 0)
        self.cf_list_layout.addStretch()
        self.cf_scroll.setWidget(self.cf_list_widget)
        root.addWidget(self.cf_scroll)

        # ── 年總覽表格 ──────────────────────────────────────────
        self.year_scroll = QScrollArea()
        self.year_scroll.setWidgetResizable(True)
        self.year_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.year_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.year_content = QWidget()
        self.year_layout  = QVBoxLayout(self.year_content)
        self.year_layout.setSpacing(S(4))
        self.year_layout.setContentsMargins(S(4), S(4), S(4), S(4))
        self.year_layout.addStretch()
        self.year_scroll.setWidget(self.year_content)
        root.addWidget(self.year_scroll)

        self._populate_year_combo()
        self._sync_month_combo()

    # ──────────────────────────────────────────────────────────────
    # 年份 / 月份選單同步
    # ──────────────────────────────────────────────────────────────
    def _populate_year_combo(self):
        self.year_combo.blockSignals(True)
        self.year_combo.clear()
        for y in get_available_years(self.data):
            self.year_combo.addItem(str(y), y)
        idx = self.year_combo.findData(self._sel_year)
        if idx >= 0:
            self.year_combo.setCurrentIndex(idx)
        self.year_combo.blockSignals(False)

    def _sync_month_combo(self):
        self.month_combo.blockSignals(True)
        idx = self.month_combo.findData(self._sel_month)
        if idx >= 0:
            self.month_combo.setCurrentIndex(idx)
        self.month_combo.blockSignals(False)

    def _on_year_changed(self, text):
        idx = self.year_combo.currentIndex()
        data = self.year_combo.itemData(idx)
        if data is not None:
            self._sel_year = data
        else:
            try:
                self._sel_year = int(text)
            except ValueError:
                return
        self.refresh()

    def _on_month_changed(self, idx):
        self._sel_month = self.month_combo.itemData(idx)
        self.refresh()

    # ──────────────────────────────────────────────────────────────
    # 切換檢視模式
    # ──────────────────────────────────────────────────────────────
    def _set_view(self, mode):
        self._view_mode = mode
        self.month_btn.setChecked(mode == "month")
        self.year_btn.setChecked(mode == "year")
        self.month_combo.setEnabled(mode == "month")
        self.tool_row_widget.setVisible(mode == "month")
        self.cf_scroll.setVisible(mode == "month")
        self.year_scroll.setVisible(mode == "year")
        self.refresh()

    # ──────────────────────────────────────────────────────────────
    # 主刷新
    # ──────────────────────────────────────────────────────────────
    def refresh(self):
        if self._view_mode == "month":
            self._render_month()
        else:
            self._render_year()

    def _render_month(self):
        records = get_month_records(self.data, self._sel_year, self._sel_month)

        # 保留原始 index，排序後仍能找到正確位置
        indexed_sorted = sorted(enumerate(records), key=lambda x: x[1]["date"], reverse=True)

        income  = sum(r["amount"] for r in records if r["type"] == "收入")
        expense = sum(r["amount"] for r in records if r["type"] == "支出")
        net     = income - expense

        self._update_summary(income, expense, net,
                             f"{self._sel_year} 年 {self._sel_month:02d} 月")
        self.period_title_lbl.setText(
            f"RECORDS  ·  {self._sel_year}-{self._sel_month:02d}  ({len(records)} 筆)"
        )

        while self.cf_list_layout.count() > 1:
            item = self.cf_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not indexed_sorted:
            empty = QLabel("— 本月尚無記錄 —")
            empty.setStyleSheet(f"color:{CP['muted']};font-family:'Courier New',monospace;"
                                f"font-size:{S(13)}px;padding:{S(20)}px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cf_list_layout.insertWidget(0, empty)
            return

        for real_idx, rec in indexed_sorted:
            self.cf_list_layout.insertWidget(
                self.cf_list_layout.count() - 1,
                self._make_record_row(real_idx, rec)
            )

    def _make_record_row(self, real_idx, rec):
        """建立單筆記錄的 row widget，real_idx 為在原始 list 中的真實位置"""
        row_w = QWidget()
        row_w.setStyleSheet(f"border-bottom:1px solid {CP['border']}; background:transparent;")
        row_lay = QHBoxLayout(row_w)
        row_lay.setContentsMargins(S(4), S(5), S(4), S(5))

        color = CP["green"] if rec["type"] == "收入" else CP["pink"]
        sign  = "+" if rec["type"] == "收入" else "-"

        date_lbl = QLabel(rec["date"])
        date_lbl.setStyleSheet(
            f"color:{CP['muted']};font-size:{S(12)}px;"
            f"font-family:'Courier New',monospace;min-width:{S(86)}px;"
        )
        type_lbl = QLabel(rec["type"])
        type_lbl.setStyleSheet(f"color:{color};font-size:{S(12)}px;min-width:{S(36)}px;font-weight:bold;")

        cat_lbl = QLabel(f"[{rec['category']}]")
        cat_lbl.setStyleSheet(f"color:{CP['muted']};font-size:{S(12)}px;min-width:{S(90)}px;")

        note_lbl = QLabel(rec.get("note", ""))
        note_lbl.setStyleSheet(f"color:{CP['text']};font-size:{S(13)}px;")

        amt_lbl = QLabel(f"{sign}NT${int(rec['amount']):,}")
        amt_lbl.setStyleSheet(
            f"color:{color};font-family:'Courier New',monospace;"
            f"font-size:{S(13)}px;font-weight:bold;"
        )

        edit_btn = QPushButton("✎")
        edit_btn.setObjectName("btn_pink")
        edit_btn.setFixedWidth(S(28))
        edit_btn.setStyleSheet(
            f"color:{CP['cyan_dim']};border-color:{CP['border']};"
            f"font-size:{S(13)}px;padding:{S(2)}px {S(4)}px;"
        )
        edit_btn.clicked.connect(
            lambda _, idx=real_idx, r=rec: self.edit_cashflow(idx, r)
        )

        del_btn = QPushButton("×")
        del_btn.setObjectName("btn_pink")
        del_btn.setFixedWidth(S(24))
        del_btn.clicked.connect(lambda _, idx=real_idx: self.del_cashflow(idx))

        row_lay.addWidget(date_lbl)
        row_lay.addWidget(type_lbl)
        row_lay.addWidget(cat_lbl)
        row_lay.addWidget(note_lbl)
        row_lay.addStretch()
        row_lay.addWidget(amt_lbl)
        row_lay.addWidget(edit_btn)
        row_lay.addWidget(del_btn)
        return row_w

    def _render_year(self):
        summary = get_year_summary(self.data, self._sel_year)
        total_income  = sum(v["income"]  for v in summary.values())
        total_expense = sum(v["expense"] for v in summary.values())
        total_net     = total_income - total_expense

        self._update_summary(total_income, total_expense, total_net,
                             f"{self._sel_year} 年度")

        while self.year_layout.count() > 1:
            item = self.year_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 表頭
        header_w = QWidget()
        header_w.setStyleSheet(f"background:{CP['panel2']};border-radius:4px;")
        hlay = QHBoxLayout(header_w)
        hlay.setContentsMargins(S(8), S(6), S(8), S(6))
        for txt, w in [("月份", 60), ("收入", 120), ("支出", 120), ("淨現金流", 120)]:
            lbl = QLabel(txt)
            lbl.setFixedWidth(w)
            lbl.setStyleSheet(
                f"color:{CP['cyan_dim']};font-size:{S(11)}px;"
                f"letter-spacing:2px;font-weight:bold;"
            )
            hlay.addWidget(lbl)
        hlay.addStretch()
        self.year_layout.insertWidget(0, header_w)

        # 12 個月
        for month in range(1, 13):
            v = summary[month]
            has_data = (v["income"] > 0 or v["expense"] > 0)

            row_w = QWidget()
            row_w.setStyleSheet(
                f"border-bottom:1px solid {CP['border']}; background:transparent;"
            )
            rlay = QHBoxLayout(row_w)
            rlay.setContentsMargins(S(8), S(5), S(8), S(5))

            month_lbl = QLabel(f"{month:02d} 月")
            month_lbl.setFixedWidth(S(60))
            month_lbl.setStyleSheet(
                f"color:{CP['text']};font-family:'Courier New',monospace;font-size:{S(13)}px;"
            )

            inc_lbl = QLabel(fmt_ntd(v["income"]) if has_data else "—")
            inc_lbl.setFixedWidth(S(120))
            inc_lbl.setStyleSheet(
                f"color:{CP['green'] if has_data else CP['muted']};"
                f"font-family:'Courier New',monospace;font-size:{S(13)}px;"
            )

            exp_lbl = QLabel(fmt_ntd(v["expense"]) if has_data else "—")
            exp_lbl.setFixedWidth(S(120))
            exp_lbl.setStyleSheet(
                f"color:{CP['pink'] if has_data else CP['muted']};"
                f"font-family:'Courier New',monospace;font-size:{S(13)}px;"
            )

            net_color = pnl_color(v["net"]) if has_data else CP["muted"]
            net_txt   = fmt_ntd(v["net"]) if has_data else "—"
            net_lbl = QLabel(net_txt)
            net_lbl.setFixedWidth(S(120))
            net_lbl.setStyleSheet(
                f"color:{net_color};font-family:'Courier New',monospace;"
                f"font-size:{S(13)}px;font-weight:{'bold' if has_data else 'normal'};"
            )

            go_btn = QPushButton(f"查看")
            go_btn.setFixedWidth(S(48))
            go_btn.setStyleSheet(
                f"font-size:{S(11)}px;padding:{S(2)}px {S(4)}px;"
                f"color:{CP['cyan_dim']};border-color:{CP['border']};"
            )
            go_btn.clicked.connect(
                lambda _, m=month: self._jump_to_month(m)
            )

            rlay.addWidget(month_lbl)
            rlay.addWidget(inc_lbl)
            rlay.addWidget(exp_lbl)
            rlay.addWidget(net_lbl)
            rlay.addStretch()
            rlay.addWidget(go_btn)
            self.year_layout.insertWidget(
                self.year_layout.count() - 1, row_w
            )

        # 合計列
        total_w = QWidget()
        total_w.setStyleSheet(f"background:{CP['panel2']};border-radius:4px;margin-top:4px;")
        tlay = QHBoxLayout(total_w)
        tlay.setContentsMargins(S(8), S(8), S(8), S(8))

        for txt, val, color in [
            ("全年合計", None, CP["cyan"]),
            (fmt_ntd(total_income),  None, CP["green"]),
            (fmt_ntd(total_expense), None, CP["pink"]),
            (fmt_ntd(total_net),     None, pnl_color(total_net)),
        ]:
            lbl = QLabel(txt)
            lbl.setFixedWidth(S(120))
            lbl.setStyleSheet(
                f"color:{color};font-family:'Courier New',monospace;"
                f"font-size:{S(13)}px;font-weight:bold;"
            )
            tlay.addWidget(lbl)
        tlay.addStretch()
        self.year_layout.insertWidget(self.year_layout.count() - 1, total_w)

    def _update_summary(self, income, expense, net, period_str):
        self.cf_income_lbl.setText(fmt_ntd(income))
        self.cf_income_lbl.setStyleSheet(
            f"font-family:'Courier New',monospace;font-size:{S(18)}px;"
            f"font-weight:bold;color:{CP['green']};"
        )
        self.cf_expense_lbl.setText(fmt_ntd(expense))
        self.cf_expense_lbl.setStyleSheet(
            f"font-family:'Courier New',monospace;font-size:{S(18)}px;"
            f"font-weight:bold;color:{CP['pink']};"
        )
        self.cf_net_lbl.setText(fmt_ntd(net))
        self.cf_net_lbl.setStyleSheet(
            f"font-family:'Courier New',monospace;font-size:{S(18)}px;"
            f"font-weight:bold;color:{pnl_color(net)};"
        )

    def _jump_to_month(self, month):
        self._sel_month = month
        self._sync_month_combo()
        self._set_view("month")

    # ──────────────────────────────────────────────────────────────
    # 操作
    # ──────────────────────────────────────────────────────────────
    def add_cashflow(self):
        dlg = AddCashflowDialog(self._sel_year, self._sel_month, self)
        if dlg.exec():
            d = dlg.get_data()
            if d["amount"] > 0:
                add_month_record(self.data, self._sel_year, self._sel_month, d)
                save_data(self.data)
                self.refresh()

    def edit_cashflow(self, idx, rec):
        dlg = EditCashflowDialog(rec, self)
        if dlg.exec():
            new_rec = dlg.get_data()
            update_month_record(self.data, self._sel_year, self._sel_month, idx, new_rec)
            save_data(self.data)
            self.refresh()

    def del_cashflow(self, idx):
        if QMessageBox.question(
            self, "確認", "刪除這筆記錄？（可按 Ctrl+Z 復原）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            push_undo(self.data, "del_cashflow", {
                "year": self._sel_year, "month": self._sel_month,
                "idx": idx,
                "record": get_month_records(self.data, self._sel_year, self._sel_month)[idx]
            })
            delete_month_record(self.data, self._sel_year, self._sel_month, idx)
            save_data(self.data)
            self.refresh()
