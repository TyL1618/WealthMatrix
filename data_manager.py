"""
data_manager.py - 資料讀寫、網路抓取（股價/匯率）
v5.0 新增：
  - Supabase 雲端同步（讀取優先雲端，斷線自動 fallback 本地）
  - 每次 save_data() 同時寫本地 + 推送雲端
  - 本地 .enc 永遠保留一份最新備份
  - 設定檔 wm_cloud.json 存放 Supabase 憑證（不寫死在程式碼中）

【首次設定】
  1. 前往 https://supabase.com 建立免費專案
  2. 在 Supabase 後台 > Table Editor > 建立資料表：
       Table name: wealthmatrix
       Columns:
         id       text  PRIMARY KEY  (固定值 "singleton")
         payload  text  (存放加密後的 JSON 字串)
         updated  text  (ISO 日期字串)
  3. 在 Supabase 後台 > Settings > API 取得：
       - Project URL（例如 https://xxxx.supabase.co）
       - anon/public key
  4. 在 WealthMatrix 資料夾建立 wm_cloud.json：
       {
         "supabase_url": "https://xxxx.supabase.co",
         "supabase_key": "eyJ..."
       }
  5. 把同一份 wm_cloud.json 複製到另一台電腦的 WealthMatrix 資料夾
  6. 同時也把 wm.key 複製過去（加密金鑰，兩台電腦必須相同）

【資料夾位置】
  Windows: %APPDATA%\\WealthMatrix\\
  macOS/Linux: ~/WealthMatrix/
"""

import json
import os
import sys
import threading
import requests
from datetime import date, datetime

if getattr(sys, 'frozen', False):
    import certifi
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
    os.environ['SSL_CERT_FILE'] = certifi.where()

from PyQt6.QtCore import QObject, pyqtSignal


# ── 路徑設定 ──────────────────────────────────────────────────────────
def _get_data_dir():
    if os.name == 'nt':
        app_data = os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        app_data = os.path.expanduser('~')
    data_dir = os.path.join(app_data, 'WealthMatrix')
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


DATA_DIR      = _get_data_dir()
DATA_FILE     = os.path.join(DATA_DIR, "wealth_matrix_data.enc")
KEY_FILE      = os.path.join(DATA_DIR, "wm.key")
CLOUD_CFG     = os.path.join(DATA_DIR, "wm_cloud.json")
_LEGACY_FILE  = os.path.join(DATA_DIR, "wealth_matrix_data.json")

_CLOUD_TIMEOUT = 6   # 秒，雲端操作逾時


# ── 加密 ─────────────────────────────────────────────────────────────
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


# ── Supabase 設定讀取 ─────────────────────────────────────────────────
def _load_cloud_cfg():
    """讀取 wm_cloud.json，回傳 (url, key) 或 (None, None)"""
    if not os.path.exists(CLOUD_CFG):
        return None, None
    try:
        with open(CLOUD_CFG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        url = cfg.get("supabase_url", "").rstrip("/")
        key = cfg.get("supabase_key", "")
        if url and key:
            return url, key
    except Exception:
        pass
    return None, None


# ── Supabase 雲端讀寫 ─────────────────────────────────────────────────
_SUPABASE_TABLE = "wealthmatrix"
_SUPABASE_ROW   = "singleton"   # 整份資料只存一列


def _cloud_headers(key):
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def _cloud_pull(url, key):
    """
    從 Supabase 拉取資料。
    回傳解密後的 dict，或 None（失敗 / 雲端無資料）。
    """
    fernet = _get_fernet()
    endpoint = f"{url}/rest/v1/{_SUPABASE_TABLE}?id=eq.{_SUPABASE_ROW}&select=payload,updated"
    try:
        r = requests.get(endpoint, headers=_cloud_headers(key), timeout=_CLOUD_TIMEOUT)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return None   # 雲端還沒有資料（首次使用）
        payload_str = rows[0].get("payload", "")
        if not payload_str:
            return None

        # 解密
        raw_bytes = payload_str.encode("utf-8")
        if fernet:
            try:
                raw_str = fernet.decrypt(raw_bytes).decode("utf-8")
            except Exception:
                # 可能是舊版明文 JSON（相容）
                raw_str = payload_str
        else:
            raw_str = payload_str

        return json.loads(raw_str)
    except Exception:
        return None


def _cloud_push(url, key, encrypted_payload: bytes):
    """
    將加密後的 payload 推送到 Supabase（upsert）。
    encrypted_payload 是 Fernet 加密後的 bytes。
    回傳 True / False。
    """
    endpoint = f"{url}/rest/v1/{_SUPABASE_TABLE}"
    body = {
        "id":      _SUPABASE_ROW,
        "payload": encrypted_payload.decode("utf-8"),
        "updated": datetime.utcnow().isoformat(),
    }
    headers = _cloud_headers(key)
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    try:
        r = requests.post(endpoint, headers=headers, json=body, timeout=_CLOUD_TIMEOUT)
        r.raise_for_status()
        return True
    except Exception:
        return False


def _cloud_push_raw(url, key, json_str: str):
    """當 Fernet 不可用時，用明文 JSON 推送（fallback）"""
    endpoint = f"{url}/rest/v1/{_SUPABASE_TABLE}"
    body = {
        "id":      _SUPABASE_ROW,
        "payload": json_str,
        "updated": datetime.utcnow().isoformat(),
    }
    headers = _cloud_headers(key)
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    try:
        r = requests.post(endpoint, headers=headers, json=body, timeout=_CLOUD_TIMEOUT)
        r.raise_for_status()
        return True
    except Exception:
        return False


# ── 雲端 vs 本地：選較新的 ────────────────────────────────────────────
def _pick_newer(local_data, cloud_data):
    """
    比較兩份資料的 _updated 時間戳，回傳較新的那份。
    若任一份沒有時間戳，優先雲端。
    """
    if cloud_data is None:
        return local_data
    if local_data is None:
        return cloud_data

    local_ts = local_data.get("_updated", "")
    cloud_ts = cloud_data.get("_updated", "")

    if not local_ts:
        return cloud_data
    if not cloud_ts:
        return local_data

    return cloud_data if cloud_ts >= local_ts else local_data


# ── 本地讀取（原有邏輯）──────────────────────────────────────────────
def _load_local():
    """只讀本地檔，回傳 dict 或 None"""
    fernet = _get_fernet()
    raw = None

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
            return json.loads(raw)
        except Exception:
            pass
    return None


# ── 預設資料結構 ──────────────────────────────────────────────────────
def _default_data():
    return {
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
        "_updated": "",   # ★ 同步用時間戳
    }


def _apply_migrations(d: dict, default: dict) -> dict:
    """把舊格式的欄位整理成新格式（原有 migration 邏輯）"""
    if "dca_reminder" in d and isinstance(d["dca_reminder"], dict):
        default["dca_reminder"].update(d["dca_reminder"])
        d.pop("dca_reminder")
    default.update(d)
    # cashflow 舊格式升級
    if default["cashflow"] and not default["cashflow_monthly"]:
        for rec in default["cashflow"]:
            ym = rec["date"][:7]
            default["cashflow_monthly"].setdefault(ym, []).append(rec)
        default["cashflow"] = []
    return default


# ── 公開 API：load_data ───────────────────────────────────────────────
def load_data():
    """
    載入資料。優先從雲端拉取，若雲端不可用則使用本地備份。
    兩者都有時，取較新的那份（依 _updated 時間戳比較）。
    """
    default = _default_data()

    # 1. 讀本地
    local_raw = _load_local()

    # 2. 嘗試讀雲端
    sb_url, sb_key = _load_cloud_cfg()
    cloud_raw = None
    if sb_url and sb_key:
        cloud_raw = _cloud_pull(sb_url, sb_key)

    # 3. 選較新的
    best_raw = _pick_newer(local_raw, cloud_raw)

    # 4. 套用 migrations
    if best_raw:
        result = _apply_migrations(best_raw, default)
    else:
        result = default

    # 5. 若雲端拉到的比本地新，順便更新本地備份
    if cloud_raw and local_raw:
        cloud_ts = cloud_raw.get("_updated", "")
        local_ts = local_raw.get("_updated", "")
        if cloud_ts > local_ts:
            _save_local(result)

    return result


# ── 公開 API：save_data ───────────────────────────────────────────────
def save_data(data):
    """
    儲存資料：
    1. 寫本地備份（.enc 加密檔）
    2. 非同步推送到雲端（不阻塞 UI）
    """
    # 注入時間戳（用於多端同步比較）
    data["_updated"] = datetime.utcnow().isoformat()

    if "undo_stack" in data and len(data["undo_stack"]) > 20:
        data["undo_stack"] = data["undo_stack"][-20:]

    payload_str   = json.dumps(data, ensure_ascii=False, indent=2)
    payload_bytes = payload_str.encode("utf-8")
    fernet        = _get_fernet()

    # 1. 本地寫入
    _save_local_raw(fernet, payload_bytes, payload_str)

    # 2. 雲端推送（背景執行，不卡 UI）
    sb_url, sb_key = _load_cloud_cfg()
    if sb_url and sb_key:
        def _push():
            if fernet:
                encrypted = fernet.encrypt(payload_bytes)
                _cloud_push(sb_url, sb_key, encrypted)
            else:
                _cloud_push_raw(sb_url, sb_key, payload_str)

        threading.Thread(target=_push, daemon=True).start()


def _save_local(data):
    """只寫本地（雲端同步時更新本地備份用）"""
    payload_str   = json.dumps(data, ensure_ascii=False, indent=2)
    payload_bytes = payload_str.encode("utf-8")
    fernet        = _get_fernet()
    _save_local_raw(fernet, payload_bytes, payload_str)


def _save_local_raw(fernet, payload_bytes: bytes, payload_str: str):
    try:
        if fernet:
            with open(DATA_FILE, "wb") as f:
                f.write(fernet.encrypt(payload_bytes))
        else:
            with open(_LEGACY_FILE, "w", encoding="utf-8") as f:
                f.write(payload_str)
    except Exception as e:
        print(f"Save error: {e}")


# ── 以下維持原有函數，完全不變 ────────────────────────────────────────
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


# ── DataFetcher（原有，完全不變）─────────────────────────────────────
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