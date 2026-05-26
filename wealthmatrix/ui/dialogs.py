"""
dialogs.py - 所有 QDialog 對話框
"""
import math
import calendar
from datetime import date as _date

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QLineEdit, QDoubleSpinBox,
    QSpinBox, QComboBox, QCheckBox
)
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
        self.ticker_input.setPlaceholderText("代號 (e.g. 0050.TW / AAPL)")
        self.shares_input = QDoubleSpinBox()
        self.shares_input.setRange(0, 99_999_999)
        self.shares_input.setDecimals(0)
        self.shares_input.setSingleStep(1)
        self.cost_input = QDoubleSpinBox()
        self.cost_input.setRange(0, 999_999)
        self.cost_input.setDecimals(2)
        self.cost_input.setSingleStep(0.5)
        self.cost_input.setPrefix("NT$ ")
        note = QLabel("美股會自動以即時匯率換算成台幣")
        note.setStyleSheet(f"color:{CP['muted']};font-size:{S(11)}px;")
        self.fee_input = QDoubleSpinBox()
        self.fee_input.setRange(0, 9999)
        self.fee_input.setDecimals(0)
        self.fee_input.setSingleStep(1)
        self.fee_input.setPrefix("NT$ ")
        self.fee_input.setValue(1)
        self.form.addRow("股票代號", self.ticker_input)
        self.form.addRow("持有股數（股）", self.shares_input)
        self.form.addRow("每股成本（NT$）", self.cost_input)
        self.form.addRow("買入手續費（元）", self.fee_input)
        self.form.addRow("", note)

    def get_data(self):
        shares = self.shares_input.value()
        price  = self.cost_input.value()
        fee    = self.fee_input.value()
        # 元大算法：每筆成交金額無條件捨去後加手續費
        holding_cost = math.floor(shares * price) + fee
        cost = round(holding_cost / shares, 2) if shares > 0 else price
        return {
            "ticker":       self.ticker_input.text().strip().upper(),
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

        self.add_fee_input = QDoubleSpinBox()
        self.add_fee_input.setRange(0, 9999)
        self.add_fee_input.setDecimals(0)
        self.add_fee_input.setSingleStep(1)
        self.add_fee_input.setPrefix("NT$ ")
        self.add_fee_input.setValue(1)
        self.add_fee_input.valueChanged.connect(self._preview)
        self.form.addRow("這次手續費（元）", self.add_fee_input)

    def _preview(self):
        add_s   = self.add_shares_input.value()
        add_p   = self.add_price_input.value()
        add_fee = self.add_fee_input.value()
        if add_s <= 0 or add_p <= 0:
            self._result_lbl.setText("")
            return
        this_cost    = math.floor(add_s * add_p) + add_fee
        new_holding  = self._cur_holding_cost + this_cost
        new_shares   = self._cur_shares + add_s
        new_cost     = new_holding / new_shares
        self._result_lbl.setText(
            f"NT${new_cost:.2f}  （{int(new_shares):,} 股  總成本 {int(new_holding):,}）"
        )

    def get_data(self):
        add_s        = self.add_shares_input.value()
        add_p        = self.add_price_input.value()
        add_fee      = self.add_fee_input.value()
        this_cost    = math.floor(add_s * add_p) + add_fee
        new_holding  = self._cur_holding_cost + this_cost
        new_shares   = self._cur_shares + add_s
        new_cost     = round(new_holding / new_shares, 2) if new_shares > 0 else add_p
        return {
            "shares":       new_shares,
            "cost":         new_cost,
            "holding_cost": new_holding,
        }


# ── 目標 ─────────────────────────────────────────────────────────────
class AddGoalDialog(CpDialog):
    def __init__(self, parent=None):
        super().__init__("Add Target Goal", parent)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("目標名稱 (e.g. 買車)")
        self.target_input = QDoubleSpinBox()
        self.target_input.setRange(1, 999_999_999)
        self.target_input.setDecimals(0)
        self.target_input.setSingleStep(10000)
        self.target_input.setPrefix("NT$ ")
        self.form.addRow("目標名稱", self.name_input)
        self.form.addRow("目標金額", self.target_input)

    def get_data(self):
        return {"name": self.name_input.text().strip(), "target": self.target_input.value()}


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
        self.type_combo.setCurrentText(rec.get("type", "支出"))
        self.type_combo.currentTextChanged.connect(self._update_cats)

        self.cat_combo = QComboBox()
        self._orig_cat = rec.get("category", "")

        self.amt_input = QDoubleSpinBox()
        self.amt_input.setRange(0, 99_999_999)
        self.amt_input.setDecimals(0)
        self.amt_input.setSingleStep(100)
        self.amt_input.setPrefix("NT$ ")
        self.amt_input.setValue(rec.get("amount", 0))

        self.note_input = QLineEdit()
        self.note_input.setText(rec.get("note", ""))

        self.form.addRow("類型", self.type_combo)
        self.form.addRow("分類", self.cat_combo)
        self.form.addRow("金額", self.amt_input)
        self.form.addRow("備註", self.note_input)

        self._update_cats(rec.get("type", "支出"))
        idx = self.cat_combo.findText(self._orig_cat)
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
