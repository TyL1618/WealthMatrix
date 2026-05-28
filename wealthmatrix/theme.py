"""
theme.py - 色盤、樣式表、共用 UI 元件
SCALE = 全局縮放係數，調這一個數字即可放大/縮小整個 GUI
"""
from PyQt6.QtWidgets import QFrame, QLabel
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtCore import Qt

# ════════════════════════════════════════════════════════════════
#  ★ 全局縮放係數 — 由 app.py 啟動時根據螢幕 DPI 自動設定
#    不需要手動修改，程式會依照每台電腦的螢幕自動縮放
#    若需強制指定大小，可在執行時設 FORCE_SCALE 環境變數
# ════════════════════════════════════════════════════════════════
SCALE = 1.0   # 預設值，run() 會在 QApplication 建立後覆蓋

def set_scale(s: float):
    """由 app.py 在 QApplication 建立後、任何 Widget 建立前呼叫"""
    global SCALE
    SCALE = max(0.5, min(3.0, s))   # 限制在合理範圍內

def S(n):
    """將數值乘上縮放係數，回傳 int（用於 px / widget size）"""
    return int(round(n * SCALE))

def Sf(n):
    """將數值乘上縮放係數，回傳 float（用於 QFont pt）"""
    return n * SCALE

# ── 色盤 ─────────────────────────────────────────────────────────────
CP = {
    "bg":        "#05080f",
    "panel":     "#090f1a",
    "border":    "#1a3a55",
    "cyan":      "#00f5ff",
    "cyan_dim":  "#00a8b0",
    "green":     "#00ff88",
    "green_dim": "#00aa55",
    "pink":      "#ff2d78",
    "red":       "#ff4444",
    "blue":      "#1a6fff",
    "text":      "#c8e0f0",
    "muted":     "#7aaabb",
    "gold":      "#ffd700",
    "panel2":    "#0b1422",
    "orange":    "#ff9500",
}

def get_stylesheet():
    """延遲生成樣式表，確保使用 set_scale() 之後的 SCALE 值"""
    return _build_stylesheet()

def _build_stylesheet():
    return f"""
QMainWindow, QWidget {{
    background-color: {CP['bg']};
    color: {CP['text']};
    font-family: 'Rajdhani', 'Consolas', 'Courier New', monospace;
    font-size: {S(13)}px;
}}
QLabel {{
    color: {CP['text']};
    background: transparent;
}}
QLabel#title {{
    color: {CP['cyan']};
    font-size: {S(20)}px;
    font-weight: bold;
    letter-spacing: {S(4)}px;
}}
QLabel#section_title {{
    color: {CP['cyan_dim']};
    font-size: {S(11)}px;
    letter-spacing: {S(3)}px;
    font-weight: bold;
}}
QLabel#total_val {{
    color: {CP['cyan']};
    font-size: {S(28)}px;
    font-weight: bold;
    font-family: 'Courier New', monospace;
}}
QLabel#bank_total, QLabel#cash_val, QLabel#stock_total {{
    font-family: 'Courier New', monospace;
    font-size: {S(18)}px;
    font-weight: bold;
}}
QLabel#bank_total {{ color: {CP['cyan']}; }}
QLabel#cash_val   {{ color: {CP['green']}; }}
QLabel#stock_total {{ color: {CP['pink']}; }}
QLabel#muted {{
    color: {CP['muted']};
    font-size: {S(13)}px;
}}
QLabel#clock {{
    color: {CP['muted']};
    font-family: 'Courier New', monospace;
    font-size: {S(12)}px;
}}
QLabel#fx_rate {{
    color: {CP['gold']};
    font-family: 'Courier New', monospace;
    font-size: {S(11)}px;
}}

QPushButton {{
    background-color: transparent;
    border: 1px solid {CP['cyan_dim']};
    color: {CP['cyan']};
    border-radius: {S(4)}px;
    padding: {S(5)}px {S(14)}px;
    font-family: 'Courier New', monospace;
    font-size: {S(11)}px;
    letter-spacing: 1px;
}}
QPushButton:hover {{
    background-color: rgba(0,245,255,0.1);
}}
QPushButton:pressed {{
    background-color: rgba(0,245,255,0.2);
}}
QPushButton#btn_green {{
    border-color: rgba(0,255,136,0.4);
    color: {CP['green']};
}}
QPushButton#btn_green:hover {{ background-color: rgba(0,255,136,0.1); }}
QPushButton#btn_pink {{
    border-color: rgba(255,45,120,0.4);
    color: {CP['pink']};
    border-radius: {S(3)}px;
    padding: {S(2)}px {S(8)}px;
    font-size: {S(14)}px;
}}
QPushButton#btn_pink:hover {{ background-color: rgba(255,45,120,0.1); }}
QPushButton#btn_blue {{
    border-color: rgba(26,111,255,0.4);
    color: {CP['blue']};
}}
QPushButton#btn_blue:hover {{ background-color: rgba(26,111,255,0.1); }}
QPushButton#btn_gold {{
    border-color: rgba(255,215,0,0.4);
    color: {CP['gold']};
}}
QPushButton#btn_gold:hover {{ background-color: rgba(255,215,0,0.1); }}

QLineEdit, QDoubleSpinBox, QSpinBox {{
    background-color: rgba(0,245,255,0.04);
    border: 1px solid #1a3a55;
    border-radius: {S(4)}px;
    color: {CP['text']};
    font-family: 'Courier New', monospace;
    font-size: {S(13)}px;
    padding: {S(6)}px {S(10)}px;
    selection-background-color: {CP['cyan_dim']};
    min-height: {S(28)}px;
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
    border-color: {CP['cyan_dim']};
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button, QSpinBox::down-button {{
    background: {CP['panel']};
    border: none;
    width: {S(22)}px;
}}

QComboBox {{
    background-color: rgba(0,245,255,0.04);
    border: 1px solid #1a3a55;
    border-radius: {S(4)}px;
    color: {CP['text']};
    font-family: 'Courier New', monospace;
    font-size: {S(13)}px;
    padding: {S(4)}px {S(10)}px;
    min-height: {S(28)}px;
}}
QComboBox::drop-down {{
    border: none;
    width: {S(24)}px;
}}
QComboBox QAbstractItemView {{
    background-color: {CP['panel2']};
    border: 1px solid {CP['border']};
    color: {CP['text']};
    font-size: {S(13)}px;
    selection-background-color: {CP['cyan_dim']};
}}

QTabWidget::pane {{
    border: 1px solid {CP['border']};
    border-radius: {S(4)}px;
    background: {CP['panel']};
}}
QTabBar::tab {{
    background: {CP['panel2']};
    color: {CP['muted']};
    border: 1px solid {CP['border']};
    border-bottom: none;
    padding: {S(6)}px {S(20)}px;
    font-family: 'Courier New', monospace;
    font-size: {S(11)}px;
    letter-spacing: 2px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {CP['panel']};
    color: {CP['cyan']};
    border-top: 2px solid {CP['cyan']};
}}
QTabBar::tab:hover {{
    color: {CP['cyan_dim']};
}}

QScrollArea {{ border: none; background: transparent; }}

/* ── Vertical Scrollbar — cyberpunk neon ── */
QScrollBar:vertical {{
    background: {CP['panel']};
    width: {S(10)}px;
    border-radius: {S(5)}px;
    border: 1px solid rgba(0,245,255,0.10);
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {CP['pink']}, stop:1 {CP['cyan']});
    border-radius: {S(4)}px;
    min-height: {S(28)}px;
    border: 1px solid rgba(0,245,255,0.55);
}}
QScrollBar::handle:vertical:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #ff6ba0, stop:1 #40faff);
    border: 1px solid {CP['cyan']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0; border: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

/* ── Horizontal Scrollbar — cyberpunk neon ── */
QScrollBar:horizontal {{
    background: {CP['panel']};
    height: {S(10)}px;
    border-radius: {S(5)}px;
    border: 1px solid rgba(255,45,120,0.10);
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {CP['cyan']}, stop:1 {CP['pink']});
    border-radius: {S(4)}px;
    min-width: {S(28)}px;
    border: 1px solid rgba(255,45,120,0.55);
}}
QScrollBar::handle:horizontal:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #40faff, stop:1 #ff6ba0);
    border: 1px solid {CP['pink']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0; border: none;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

QProgressBar {{
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: {S(8)}px;
    background-color: rgba(255,255,255,0.06);
    height: {S(18)}px;
    text-align: center;
    font-family: 'Courier New', monospace;
    font-size: {S(10)}px;
    color: {CP['text']};
}}

QDialog {{
    background-color: #0a1525;
    border: 1px solid {CP['cyan_dim']};
    border-radius: {S(8)}px;
}}
QFormLayout QLabel {{
    color: {CP['muted']};
    font-size: {S(12)}px;
    letter-spacing: 1px;
}}

QCheckBox {{
    color: {CP['text']};
    font-size: {S(13)}px;
}}
QCheckBox::indicator {{
    width: {S(16)}px; height: {S(16)}px;
    border: 1px solid {CP['border']};
    border-radius: {S(3)}px;
    background: transparent;
}}
QCheckBox::indicator:checked {{
    background: {CP['cyan_dim']};
    border-color: {CP['cyan']};
}}
"""

# 保留向後相容的模組層級名稱（部分模組直接 import STYLESHEET）
class _LazyStyle:
    """讓 'from theme import STYLESHEET' 仍能運作，但每次讀取都用當下的 SCALE"""
    def __init__(self, fn):
        self._fn = fn
    def __str__(self):
        return self._fn()
    def __format__(self, spec):
        return format(str(self), spec)

STYLESHEET   = _LazyStyle(get_stylesheet)

def get_dialog_style():
    return f"""
    QDialog {{
        background-color: #0a1525;
        border: 1px solid {CP['cyan_dim']};
    }}
    QLabel {{ color: {CP['muted']}; font-size: {S(12)}px; }}
    QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
        background: rgba(0,245,255,0.04);
        border: 1px solid #1a3a55;
        border-radius: {S(4)}px;
        color: {CP['text']};
        font-family: 'Courier New', monospace;
        font-size: {S(13)}px;
        padding: {S(6)}px {S(10)}px;
        min-height: {S(28)}px;
    }}
    QLineEdit:focus, QDoubleSpinBox:focus {{
        border-color: {CP['cyan_dim']};
    }}
    QPushButton {{
        background: transparent;
        border: 1px solid {CP['cyan_dim']};
        color: {CP['cyan']};
        border-radius: {S(4)}px;
        padding: {S(8)}px 0;
        font-family: 'Courier New', monospace;
        font-size: {S(12)}px;
        letter-spacing: 1px;
    }}
    QPushButton:hover {{ background: rgba(0,245,255,0.12); }}
    QPushButton#btn_cancel {{
        border-color: {CP['border']};
        color: {CP['muted']};
    }}
    QPushButton#btn_cancel:hover {{ background: rgba(255,255,255,0.04); }}
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
    QSpinBox::up-button, QSpinBox::down-button {{
        background: {CP['panel']}; border: none; width: {S(22)}px;
    }}
    QCheckBox {{ color: {CP['text']}; font-size: {S(13)}px; }}
    QCheckBox::indicator {{
        width: {S(16)}px; height: {S(16)}px;
        border: 1px solid {CP['border']};
        border-radius: {S(3)}px; background: transparent;
    }}
    QCheckBox::indicator:checked {{
        background: {CP['cyan_dim']};
        border-color: {CP['cyan']};
    }}
"""

DIALOG_STYLE = _LazyStyle(get_dialog_style)


# ── 面板基底 ────────────────────────────────────────────────────────
class CpPanel(QFrame):
    def __init__(self, accent=None, parent=None):
        super().__init__(parent)
        if accent is None:
            accent = CP["cyan"]
        self.accent = QColor(accent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {CP['panel']};
                border: 1px solid #1a3a55;
                border-radius: {S(6)}px;
            }}
        """)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.accent)
        painter.drawRoundedRect(0, 0, self.width(), S(3), 2, 2)


def section_label(text):
    lbl = QLabel(text)
    lbl.setObjectName("section_title")
    return lbl


def muted_label(text):
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    return lbl


def fmt_ntd(n):
    return f"NT${int(round(n)):,}"


def fmt_pnl(n):
    sign = "+" if n >= 0 else ""
    return f"{sign}NT${int(round(n)):,}"


def fmt_pct(n):
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:.2f}%"


def pnl_color(n):
    if n > 0:
        return CP["green"]
    elif n < 0:
        return CP["pink"]
    return CP["muted"]


def goal_color(pct):
    t = min(pct / 100, 1.0)
    r = int(0   + (26  - 0)   * t)
    g = int(255 + (111 - 255) * t)
    b = int(136 + (255 - 136) * t)
    return f"rgb({r},{g},{b})"
