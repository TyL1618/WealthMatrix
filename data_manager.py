"""
data_manager.py - 資料讀寫、網路抓取（股價/匯率）
新增：
  - AES 加密存檔（cryptography.fernet）
  - 匯率當天快取（避免重複抓取）
  - Yahoo Finance 失效 / 網路錯誤 signal
"""
import json
import os
import sys
import threading
import requests
from datetime import date

if getattr(sys, 'frozen', False):
    import certifi
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
    os.environ['SSL_CERT_FILE'] = certifi.where()

from PyQt6.QtCore import QObject, pyqtSignal


def _get_data_dir():
    if os.name == 'nt':
        app_data = os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        app_data = os.path.expanduser('~')
    data_dir = os.path.join(app_data, 'WealthMatrix')
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


DATA_DIR     = _get_data_dir()
DATA_FILE    = os.path.join(DATA_DIR, "wealth_matrix_data.enc")
KEY_FILE     = os.path.join(DATA_DIR, "wm.key")
_LEGACY_FILE = os.path.join(DATA_DIR, "wealth_matrix_data.json")


def _get_fernet():
    try:
        from cryptography.fernet import Fernet
        if os.path.exists(KEY_FILE):
            with open(KEY_FILE, "rb") as f:
                key = f.read()
        else:
            key = Fernet.generate_key()
            with open(KEY_FILE, "wb") as f:
                f.write(key)
        return Fernet(key)
    except ImportError:
        return None


def load_data():
    default = {
        "banks": [], "cash": 0, "stocks": [], "goals": [],
        "goals_visible": True,
        "cashflow_monthly": {},
        "cashflow": [],
        "history": [],
        "dca_reminder": {"enabled": False, "day": 5, "last_reminded": ""},
        "usd_rate": 31.5,
        "usd_rate_date": "",
        "window_geometry": None,
        "undo_stack": [],
    }

    raw = None
    fernet = _get_fernet()
    if fernet and os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "rb") as f:
                raw = fernet.decrypt(f.read()).decode("utf-8")
        except Exception:
            raw = None

    if raw is None and os.path.exists(_LEGACY_FILE):
        try:
            with open(_LEGACY_FILE, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception:
            pass

    if raw:
        try:
            d = json.loads(raw)
            if "dca_reminder" in d and isinstance(d["dca_reminder"], dict):
                default["dca_reminder"].update(d["dca_reminder"])
                d.pop("dca_reminder")
            default.update(d)
            if default["cashflow"] and not default["cashflow_monthly"]:
                for rec in default["cashflow"]:
                    ym = rec["date"][:7]
                    default["cashflow_monthly"].setdefault(ym, []).append(rec)
                default["cashflow"] = []
        except Exception:
            pass

    return default


def save_data(data):
    if "undo_stack" in data and len(data["undo_stack"]) > 20:
        data["undo_stack"] = data["undo_stack"][-20:]

    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    fernet  = _get_fernet()
    try:
        if fernet:
            with open(DATA_FILE, "wb") as f:
                f.write(fernet.encrypt(payload))
        else:
            with open(_LEGACY_FILE, "w", encoding="utf-8") as f:
                f.write(payload.decode("utf-8"))
    except Exception as e:
        print(f"Save error: {e}")


def get_month_key(year, month):
    return f"{year:04d}-{month:02d}"


def get_month_records(data, year, month):
    key = get_month_key(year, month)
    return data["cashflow_monthly"].get(key, [])


def add_month_record(data, year, month, record):
    key = get_month_key(year, month)
    data["cashflow_monthly"].setdefault(key, []).append(record)


def delete_month_record(data, year, month, idx):
    key = get_month_key(year, month)
    if key in data["cashflow_monthly"] and 0 <= idx < len(data["cashflow_monthly"][key]):
        return data["cashflow_monthly"][key].pop(idx)
    return None


def update_month_record(data, year, month, idx, new_rec):
    key = get_month_key(year, month)
    if key in data["cashflow_monthly"] and 0 <= idx < len(data["cashflow_monthly"][key]):
        data["cashflow_monthly"][key][idx] = new_rec


def get_year_summary(data, year):
    summary = {}
    for month in range(1, 13):
        key = get_month_key(year, month)
        records = data["cashflow_monthly"].get(key, [])
        income  = sum(r["amount"] for r in records if r["type"] == "收入")
        expense = sum(r["amount"] for r in records if r["type"] == "支出")
        summary[month] = {"income": income, "expense": expense, "net": income - expense}
    return summary


def get_available_years(data):
    return list(range(2100, 1999, -1))


def push_undo(data, action_type, payload):
    stack = data.setdefault("undo_stack", [])
    stack.append({"type": action_type, "payload": payload})
    if len(stack) > 20:
        data["undo_stack"] = stack[-20:]


def pop_undo(data):
    stack = data.get("undo_stack", [])
    if not stack:
        return None
    entry = stack.pop()
    return entry["type"], entry["payload"]


class DataFetcher(QObject):
    prices_ready = pyqtSignal(dict)
    fx_ready     = pyqtSignal(float)
    fetch_error  = pyqtSignal(str)

    def fetch_all(self, tickers, fetch_fx=True, cached_rate=None, cached_date=""):
        def run():
            TIMEOUT   = 6
            HEADERS   = {"User-Agent": "Mozilla/5.0"}
            today_str = date.today().isoformat()

            usd_rate = None
            if fetch_fx:
                if cached_date == today_str and cached_rate:
                    usd_rate = cached_rate
                else:
                    try:
                        url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
                               "USDTWD=X?interval=1d&range=1d")
                        r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
                        r.raise_for_status()
                        d = r.json()
                        usd_rate = d["chart"]["result"][0]["meta"]["regularMarketPrice"]
                        self.fx_ready.emit(usd_rate)
                    except requests.exceptions.ConnectionError:
                        self.fetch_error.emit("網路無法連線，匯率使用上次快取值。")
                    except requests.exceptions.Timeout:
                        self.fetch_error.emit("匯率請求逾時（Yahoo Finance），使用上次快取值。")
                    except Exception as e:
                        self.fetch_error.emit(f"匯率抓取失敗：{e}")

            if not tickers:
                self.prices_ready.emit({})
                return

            result   = {}
            failures = []
            for ticker in tickers:
                try:
                    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
                           f"{ticker}?interval=1d&range=1d")
                    r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
                    r.raise_for_status()
                    d    = r.json()
                    meta = d["chart"]["result"][0]["meta"]
                    price    = meta["regularMarketPrice"]
                    currency = meta.get("currency", "TWD")
                    if currency == "USD" and usd_rate:
                        price = price * usd_rate
                    result[ticker] = price
                except requests.exceptions.ConnectionError:
                    failures.append(ticker)
                except requests.exceptions.Timeout:
                    failures.append(ticker)
                except Exception:
                    failures.append(ticker)

            if failures:
                self.fetch_error.emit(
                    f"以下股票代號無法取得即時報價：{', '.join(failures)}\n"
                    f"（可能原因：代號錯誤、Yahoo Finance 暫時無法存取、或無網路連線）"
                )

            self.prices_ready.emit(result)

        threading.Thread(target=run, daemon=True).start()