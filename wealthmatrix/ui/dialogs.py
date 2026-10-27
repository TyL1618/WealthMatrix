"""
dialogs.py - 所有 QDialog 對話框
"""
import math
import calendar
from datetime import date as _date

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QLineEdit, QDoubleSpinBox,
    QSpinBox, QComboBox, QCheckBox, QListWidget
)
from wealthmatrix.core.calc import rec_type, normalize_ticker
from wealthmatrix.theme import CP, get_dialog_style, S


class CpDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(S(340))
        self.setStyleSheet(get_dialog_style())
        main = QVBoxLayout(self)
        main.setSpacing(S(12))
        main.setContentsMargins(S(20), S(20), S(20), S(20))
        title_lbl = QLabel(title.upper())
        title_lbl.setStyleSheet(
            f"color:{CP['cyan']};font-family:'Courier New',monospace;"
            f"font-size:{S(13)}px;letter-spacing:2px;font-weight:bold;"
        )
        main.addWidget(title_lbl)
        self.form = QFormLayout()
        self.form.setSpacing(S(8))
        main.addLayout(self.form)
        btn_row = QHBoxLayout()
        self.btn_ok     = QPushButton("CONFIRM")
        self.btn_cancel = QPushButton("CANCEL")
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_ok)
        btn_row.addWidget(self.btn_cancel)
        main.addLayout(btn_row)


# ── 銀行 ─────────────────────────────────────────────────────────────
class AddBankDialog(CpDialog):
    def __init__(self, parent=None):
        super().__init__("Add Bank Account", parent)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("銀行名稱 (e.g. 台新銀行)")
        self.amt_input = QDoubleSpinBox()
        self.amt_input.setRange(0, 999_999_999)
        self.amt_input.setDecimals(0)
        self.amt_input.setSingleStep(1000)
        self.amt_input.setPrefix("NT$ ")
        self.form.addRow("銀行名稱", self.name_input)
        self.form.addRow("帳戶餘額", self.amt_input)

    def get_data(self):
        return {"name": self.name_input.text().strip(), "amount": self.amt_input.value()}


class EditBankDialog(CpDialog):
    def __init__(self, bank, parent=None):
        super().__init__(f"Edit: {bank['name']}", parent)
        self.amt_input = QDoubleSpinBox()
        self.amt_input.setRange(0, 999_999_999)
        self.amt_input.setDecimals(0)
        self.amt_input.setSingleStep(1000)
        self.amt_input.setPrefix("NT$ ")
        self.amt_input.setValue(bank["amount"])
        self.form.addRow("帳戶餘額", self.amt_input)

    def get_amount(self):
        return self.amt_input.value()


# ── 股票 ─────────────────────────────────────────────────────────────
class AddStockDialog(CpDialog):
    def __init__(self, parent=None):
        super().__init__("Add Stock / ETF", parent)
        self.ticker_input = QLineEdit()
        self.ticker_input.setPlaceholderText("代號 (e.g. 0050 / 2330 / AAPL)")
        self.shares_input = QDoubleSpinBox()
        self.shares_input.setRange(0, 99_999_999)
        self.shares_input.setDecimals(0)
        self.shares_input.setSingleStep(1)
        self.cost_input = QDoubleSpinBox()
        self.cost_input.setRange(0, 999_999)
        self.cost_input.setDecimals(2)
        self.cost_input.setSingleStep(0.5)
        self.cost_input.setPrefix("NT$ ")
        note = QLabel("台股輸入數字代號即可（自動補 .TW，上櫃請輸入 .TWO）；美股會自動以即時匯率換算成台幣")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{CP['muted']};font-size:{S(11)}px;")
        self.form.addRow("股票代號", self.ticker_input)
        self.form.addRow("持有股數（股）", self.shares_input)
        self.form.addRow("每股成本（NT$）", self.cost_input)
        self.form.addRow("", note)

    def get_data(self):
        shares = self.shares_input.value()
        price  = self.cost_input.value()
        holding_cost = round(shares * price, 2)
        cost = price
        return {
            "ticker":       normalize_ticker(self.ticker_input.text()),
            "shares":       shares,
            "cost":         cost,
            "holding_cost": holding_cost,
        }


class EditStockDialog(CpDialog):
    def __init__(self, stock, parent=None):
        super().__init__(f"Edit: {stock['ticker']}", parent)
        self.shares_input = QDoubleSpinBox()
        self.shares_input.setRange(0, 99_999_999)
        self.shares_input.setDecimals(0)
        self.shares_input.setSingleStep(1)
        self.shares_input.setValue(stock["shares"])
        self.form.addRow("持有股數", self.shares_input)

    def get_data(self):
        return {"shares": self.shares_input.value()}


class AddPositionDialog(CpDialog):
    def __init__(self, stock, parent=None):
        super().__init__(f"加倉: {stock['ticker']}", parent)
        cur_shares = stock["shares"]
        cur_cost   = stock.get("cost", 0)
        info_txt = f"目前  {int(cur_shares):,} 股"
        if cur_cost > 0:
            info_txt += f"  ×  NT${cur_cost:.2f}"
        info = QLabel(info_txt)
        info.setStyleSheet(f"color:{CP['cyan']};font-family:'Courier New',monospace;font-size:{S(12)}px;")
        self.form.addRow("現況", info)
        self.add_shares_input = QDoubleSpinBox()
        self.add_shares_input.setRange(1, 99_999_999)
        self.add_shares_input.setDecimals(0)
        self.add_shares_input.setSingleStep(1)
        self.form.addRow("這次買幾股", self.add_shares_input)
        self.add_price_input = QDoubleSpinBox()
        self.add_price_input.setRange(0, 999_999)
        self.add_price_input.setDecimals(2)
        self.add_price_input.setSingleStep(0.5)
        self.add_price_input.setPrefix("NT$ ")
        self.form.addRow("這次買價（每股）", self.add_price_input)
        self._result_lbl = QLabel("")
        self._result_lbl.setStyleSheet(f"color:{CP['green']};font-family:'Courier New',monospace;font-size:{S(12)}px;")
        self.form.addRow("新均價預覽", self._result_lbl)
        self._cur_shares       = cur_shares
        self._cur_cost         = cur_cost
        self._cur_holding_cost = stock.get("holding_cost", round(cur_cost * cur_shares))
        self.add_shares_input.valueChanged.connect(self._preview)
        self.add_price_input.valueChanged.connect(self._preview)

    def _preview(self):
        add_s = self.add_shares_input.value()
        add_p = self.add_price_input.value()
        if add_s <= 0 or add_p <= 0:
            self._result_lbl.setText("")
            return
        this_cost   = round(add_s * add_p, 2)
        new_holding = self._cur_holding_cost + this_cost
        new_shares  = self._cur_shares + add_s
        new_cost    = new_holding / new_shares
        self._result_lbl.setText(
            f"NT${new_cost:.2f}  （{int(new_shares):,} 股  總成本 {int(new_holding):,}）"
        )

    def get_data(self):
        add_s       = self.add_shares_input.value()
        add_p       = self.add_price_input.value()
        this_cost   = round(add_s * add_p, 2)
        new_holding = self._cur_holding_cost + this_cost
        new_shares  = self._cur_shares + add_s
        new_cost    = round(new_holding / new_shares, 2) if new_shares > 0 else add_p
        return {
            "shares":       new_shares,
            "cost":         new_cost,
            "holding_cost": new_holding,
        }


# ── 目標 ─────────────────────────────────────────────────────────────
class AddGoalDialog(CpDialog):
    def __init__(self, parent=None, goal=None):
        super().__init__("Edit Target Goal" if goal else "Add Target Goal", parent)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("目標名稱 (e.g. 買車)")
        self.target_input = QDoubleSpinBox()
        self.target_input.setRange(1, 999_999_999)
        self.target_input.setDecimals(0)
        self.target_input.setSingleStep(10000)
        self.target_input.setPrefix("NT$ ")

        self.deadline_cb = QCheckBox("設定期限")
        self.year_spin = QSpinBox()
        self.year_spin.setRange(_date.today().year, _date.today().year + 40)
        self.year_spin.setSuffix(" 年")
        self.month_spin = QSpinBox()
        self.month_spin.setRange(1, 12)
        self.month_spin.setSuffix(" 月")
        dl_row = QHBoxLayout()
        dl_row.addWidget(self.deadline_cb)
        dl_row.addWidget(self.year_spin)
        dl_row.addWidget(self.month_spin)
        self.deadline_cb.toggled.connect(self._sync_deadline)

        self.form.addRow("目標名稱", self.name_input)
        self.form.addRow("目標金額", self.target_input)
        self.form.addRow("期限", dl_row)

        nxt = _date.today().year + 1
        self.year_spin.setValue(nxt)
        self.month_spin.setValue(12)
        if goal:
            self.name_input.setText(goal.get("name", ""))
            self.target_input.setValue(goal.get("target", 1))
            dl = goal.get("deadline") or ""
            if len(dl) >= 7 and dl[:4].isdigit() and dl[5:7].isdigit() and 1 <= int(dl[5:7]) <= 12:
                self.year_spin.setRange(min(int(dl[:4]), _date.today().year), max(int(dl[:4]), nxt) + 40)
                self.year_spin.setValue(int(dl[:4]))
                self.month_spin.setValue(int(dl[5:7]))
                self.deadline_cb.setChecked(True)
        self._sync_deadline()

    def _sync_deadline(self):
        on = self.deadline_cb.isChecked()
        self.year_spin.setEnabled(on)
        self.month_spin.setEnabled(on)

    def get_data(self):
        d = {"name": self.name_input.text().strip(), "target": self.target_input.value()}
        if self.deadline_cb.isChecked():
            d["deadline"] = f"{self.year_spin.value():04d}-{self.month_spin.value():02d}"
        return d


# ── 預算 ─────────────────────────────────────────────────────────────
class BudgetDialog(CpDialog):
    """每個支出分類的每月預算。0 = 不設預算。"""

    def __init__(self, budgets, categories, parent=None):
        super().__init__("Monthly Budget", parent)
        self.setMinimumWidth(S(380))
        self._spins = {}
        for cat in categories:
            sp = QDoubleSpinBox()
            sp.setRange(0, 99_999_999)
            sp.setDecimals(0)
            sp.setSingleStep(500)
            sp.setPrefix("NT$ ")
            sp.setSpecialValueText("不設預算")
            sp.setValue(float((budgets or {}).get(cat, 0) or 0))
            self._spins[cat] = sp
            self.form.addRow(cat, sp)

    def get_data(self):
        return {c: sp.value() for c, sp in self._spins.items() if sp.value() > 0}


# ── 現金流：新增 ─────────────────────────────────────────────────────
INCOME_CATS  = ["薪資", "年終獎金", "家教收入", "投資獲利", "其他收入"]
EXPENSE_CATS = ["生活費", "餐飲", "交通", "娛樂", "購物", "投資買入", "其他支出"]


class AddCashflowDialog(CpDialog):
    def __init__(self, year, month, parent=None):
        super().__init__("Add Cashflow Record", parent)
        self._year  = year
        self._month = month

        month_lbl = QLabel(f"{year} 年 {month:02d} 月")
        month_lbl.setStyleSheet(
            f"color:{CP['cyan']};font-family:'Courier New',monospace;font-size:{S(12)}px;"
        )
        self.form.addRow("記帳月份", month_lbl)

        self.day_spin = QSpinBox()
        days_in_month = calendar.monthrange(year, month)[1]
        self.day_spin.setRange(1, days_in_month)
        if _date.today().year == year and _date.today().month == month:
            self.day_spin.setValue(_date.today().day)
        else:
            self.day_spin.setValue(1)
        self.day_spin.setSuffix(" 日")
        self.form.addRow("日期", self.day_spin)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["收入", "支出"])
        self.type_combo.currentTextChanged.connect(self._update_cats)

        self.cat_combo = QComboBox()

        self.amt_input = QDoubleSpinBox()
        self.amt_input.setRange(0, 99_999_999)
        self.amt_input.setDecimals(0)
        self.amt_input.setSingleStep(100)
        self.amt_input.setPrefix("NT$ ")

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("備註（選填）")

        self.form.addRow("類型", self.type_combo)
        self.form.addRow("分類", self.cat_combo)
        self.form.addRow("金額", self.amt_input)
        self.form.addRow("備註", self.note_input)
        self._update_cats("收入")

    def _update_cats(self, t):
        self.cat_combo.clear()
        self.cat_combo.addItems(INCOME_CATS if t == "收入" else EXPENSE_CATS)

    def get_data(self):
        day = self.day_spin.value()
        rec_date = f"{self._year:04d}-{self._month:02d}-{day:02d}"
        return {
            "date":     rec_date,
            "type":     self.type_combo.currentText(),
            "category": self.cat_combo.currentText(),
            "amount":   self.amt_input.value(),
            "note":     self.note_input.text().strip()
        }


# ── 現金流：編輯 ─────────────────────────────────────────────────────
class EditCashflowDialog(CpDialog):
    def __init__(self, rec, parent=None):
        super().__init__("Edit Cashflow Record", parent)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["收入", "支出"])
        self.type_combo.setCurrentText(rec_type(rec))
        self.type_combo.currentTextChanged.connect(self._update_cats)

        self.cat_combo = QComboBox()
        self._orig_cat = rec.get("category", "")

        self.amt_input = QDoubleSpinBox()
        self.amt_input.setRange(0, 99_999_999)
        self.amt_input.setDecimals(0)
        self.amt_input.setSingleStep(100)
        self.amt_input.setPrefix("NT$ ")
        self.amt_input.setValue(abs(rec.get("amount", 0)))

        self.note_input = QLineEdit()
        self.note_input.setText(rec.get("note", ""))

        self.form.addRow("類型", self.type_combo)
        self.form.addRow("分類", self.cat_combo)
        self.form.addRow("金額", self.amt_input)
        self.form.addRow("備註", self.note_input)

        self._update_cats(rec_type(rec))
        idx = self.cat_combo.findText(self._orig_cat)
        if idx < 0 and self._orig_cat:
            # 手機端可自由輸入分類；不在清單內時保留原分類，避免編輯時被悄悄改掉
            self.cat_combo.addItem(self._orig_cat)
            idx = self.cat_combo.count() - 1
        if idx >= 0:
            self.cat_combo.setCurrentIndex(idx)

        self._rec = rec

    def _update_cats(self, t):
        self.cat_combo.clear()
        self.cat_combo.addItems(INCOME_CATS if t == "收入" else EXPENSE_CATS)

    def get_data(self):
        return {
            "date":     self._rec["date"],
            "type":     self.type_combo.currentText(),
            "category": self.cat_combo.currentText(),
            "amount":   self.amt_input.value(),
            "note":     self.note_input.text().strip()
        }


# ── 負債 ─────────────────────────────────────────────────────────────
class AddLiabilityDialog(CpDialog):
    def __init__(self, parent=None):
        super().__init__("Add Liability", parent)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("名稱 (e.g. 信用卡 / 學貸 / 房貸)")
        self.amt_input = QDoubleSpinBox()
        self.amt_input.setRange(0, 999_999_999)
        self.amt_input.setDecimals(0)
        self.amt_input.setSingleStep(1000)
        self.amt_input.setPrefix("NT$ ")
        self.form.addRow("負債名稱", self.name_input)
        self.form.addRow("目前欠款", self.amt_input)

    def get_data(self):
        return {"name": self.name_input.text().strip(), "amount": self.amt_input.value()}


class EditLiabilityDialog(CpDialog):
    def __init__(self, item, parent=None):
        super().__init__(f"Edit: {item['name']}", parent)
        self.amt_input = QDoubleSpinBox()
        self.amt_input.setRange(0, 999_999_999)
        self.amt_input.setDecimals(0)
        self.amt_input.setSingleStep(1000)
        self.amt_input.setPrefix("NT$ ")
        self.amt_input.setValue(item["amount"])
        self.form.addRow("目前欠款", self.amt_input)

    def get_amount(self):
        return self.amt_input.value()


# ── 固定收支 ─────────────────────────────────────────────────────────
class RecurringRuleDialog(CpDialog):
    def __init__(self, parent=None):
        super().__init__("Add Recurring", parent)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["支出", "收入"])
        self.type_combo.currentTextChanged.connect(self._update_cats)
        self.cat_combo = QComboBox()
        self.cat_combo.setEditable(True)     # 允許自訂分類（例如「房租」「訂閱」）
        self.amt_input = QDoubleSpinBox()
        self.amt_input.setRange(0, 99_999_999)
        self.amt_input.setDecimals(0)
        self.amt_input.setSingleStep(100)
        self.amt_input.setPrefix("NT$ ")
        self.day_spin = QSpinBox()
        self.day_spin.setRange(1, 31)
        self.day_spin.setValue(1)
        self.day_spin.setPrefix("每月 ")
        self.day_spin.setSuffix(" 日")
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("備註（選填）")
        note = QLabel("31 日在小月會自動落在月底；到期時開啟程式（或手機）就會自動入帳")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{CP['muted']};font-size:{S(11)}px;")
        self.form.addRow("類型", self.type_combo)
        self.form.addRow("分類", self.cat_combo)
        self.form.addRow("金額", self.amt_input)
        self.form.addRow("日期", self.day_spin)
        self.form.addRow("備註", self.note_input)
        self.form.addRow("", note)
        self._update_cats("支出")

    def _update_cats(self, t):
        self.cat_combo.clear()
        self.cat_combo.addItems(INCOME_CATS if t == "收入" else EXPENSE_CATS)

    def get_data(self):
        return {
            "type":     self.type_combo.currentText(),
            "category": self.cat_combo.currentText().strip(),
            "amount":   self.amt_input.value(),
            "day":      self.day_spin.value(),
            "note":     self.note_input.text().strip(),
        }


class RecurringListDialog(CpDialog):
    """管理固定收支規則。直接修改傳入的 rules list；呼叫端在 exec() 後檢查 .changed。"""

    def __init__(self, rules, parent=None):
        super().__init__("固定收支", parent)
        self.setMinimumWidth(S(480))
        self.rules   = rules
        self.changed = False
        self.btn_ok.setText("CLOSE")
        self.btn_cancel.hide()

        self.list = QListWidget()
        self.list.setMinimumHeight(S(180))
        self.form.addRow(self.list)

        row = QHBoxLayout()
        add_btn = QPushButton("+ 新增")
        add_btn.clicked.connect(self._add)
        toggle_btn = QPushButton("啟用 / 停用")
        toggle_btn.clicked.connect(self._toggle)
        del_btn = QPushButton("刪除")
        del_btn.setObjectName("btn_pink")
        del_btn.clicked.connect(self._delete)
        for b in (add_btn, toggle_btn, del_btn):
            row.addWidget(b)
        self.form.addRow(row)
        self._refresh()

    def _refresh(self, select=None):
        self.list.clear()
        for r in self.rules:
            state = "✓" if r.get("active", True) else "✗"
            sign  = "+" if r.get("type") == "收入" else "-"
            self.list.addItem(
                f"{state}  每月 {int(r.get('day', 1)):>2} 日   {r.get('type', '')}  "
                f"{r.get('category', '')}   {sign}NT${float(r.get('amount', 0)):,.0f}"
                + ("" if r.get("active", True) else "   （已停用）")
            )
        if select is not None and 0 <= select < self.list.count():
            self.list.setCurrentRow(select)

    def _add(self):
        dlg = RecurringRuleDialog(self)
        if not dlg.exec():
            return
        d = dlg.get_data()
        if d["amount"] <= 0 or not d["category"]:
            return
        from wealthmatrix.core.recurring import new_rule_id
        self.rules.append({
            **d, "id": new_rule_id(), "active": True,
            "start": _date.today().strftime("%Y-%m"), "generated": [],
        })
        self.changed = True
        self._refresh(len(self.rules) - 1)

    def _toggle(self):
        i = self.list.currentRow()
        if i < 0:
            return
        rule = self.rules[i]
        rule["active"] = not rule.get("active", True)
        if rule["active"]:
            # 重新啟用時從本月重新開始，不回補停用期間的月份
            rule["start"] = _date.today().strftime("%Y-%m")
        self.changed = True
        self._refresh(i)

    def _delete(self):
        i = self.list.currentRow()
        if i < 0:
            return
        self.rules.pop(i)     # 已產生的記錄保留，只是不再繼續產生
        self.changed = True
        self._refresh(min(i, len(self.rules) - 1))


# ── DCA ──────────────────────────────────────────────────────────────
class DCASettingsDialog(CpDialog):
    def __init__(self, dca, parent=None):
        super().__init__("DCA Reminder Settings", parent)
        self.enabled_cb = QCheckBox("啟用每月定期定額提醒")
        self.enabled_cb.setChecked(dca.get("enabled", False))
        self.day_spin = QSpinBox()
        self.day_spin.setRange(1, 28)
        self.day_spin.setValue(dca.get("day", 5))
        self.day_spin.setSuffix("  日")
        self.form.addRow("", self.enabled_cb)
        self.form.addRow("每月提醒日", self.day_spin)

    def get_data(self):
        return {"enabled": self.enabled_cb.isChecked(), "day": self.day_spin.value()}


class DcaReminderPopup(QDialog):
    def __init__(self, day, parent=None):
        super().__init__(parent)
        self.setWindowTitle("定期定額提醒")
        self.setModal(True)
        self.setMinimumWidth(S(320))
        self.setStyleSheet(f"""
            QDialog {{ background-color: #0a1525; border: 1px solid {CP['gold']}; }}
            QLabel  {{ color: {CP['text']}; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S(24), S(24), S(24), S(20))
        lay.setSpacing(S(14))
        icon = QLabel("⚡  DCA 提醒")
        icon.setStyleSheet(
            f"color:{CP['gold']};font-family:'Courier New',monospace;"
            f"font-size:{S(14)}px;font-weight:bold;letter-spacing:3px;"
        )
        lay.addWidget(icon)
        msg = QLabel(f"今天是每月第 {day} 號。\n是否記得執行定期定額買入？")
        msg.setStyleSheet(f"color:{CP['text']};font-size:{S(13)}px;line-height:1.6;")
        msg.setWordWrap(True)
        lay.addWidget(msg)
        btn = QPushButton("已知悉  ✓")
        btn.setStyleSheet(
            f"background:transparent;border:1px solid {CP['gold']};color:{CP['gold']};"
            f"border-radius:4px;padding:{S(8)}px;font-family:'Courier New',monospace;font-size:{S(12)}px;"
        )
        btn.clicked.connect(self.accept)
        lay.addWidget(btn)
