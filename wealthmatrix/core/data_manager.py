"""
data_manager.py - 資料讀寫、網路抓取（股價/匯率）

【Supabase 雲端同步設定】
  1. 前往 https://supabase.com 建立免費專案
  2. 在 Table Editor 建立資料表：
       Table name: wealthmatrix
       Columns: id(text, PK), payload(text), updated(text)
  3. 在 Settings > API 取得 Project URL 與 anon/public key
  4. Authentication > Sign In with Email 確認已啟用
  5. 建立一個帳號（Authentication > Users > Invite）
  6. 在 SQL Editor 執行以下 RLS 設定：
       ALTER TABLE wealthmatrix ENABLE ROW LEVEL SECURITY;
       CREATE POLICY "Own data only" ON wealthmatrix
         FOR ALL USING (auth.uid()::text = id);
  7. 在 WealthMatrix 資料夾建立 wm_cloud.json：
       {
         "supabase_url": "https://xxxx.supabase.co",
         "supabase_key": "eyJ...",
         "email": "your@email.com",
         "password": "yourpassword"
       }
  8. 複製同一份 wm_cloud.json 到其他裝置即可（不再需要 wm.key）

【資料夾位置】
  Windows: %APPDATA%\\WealthMatrix\\
  macOS/Linux: ~/WealthMatrix/

【舊版加密資料升級】
  若之前有舊版 .enc 加密檔，程式啟動時會自動嘗試解密並存為明文 .json。
  需要 cryptography 套件；若未安裝則嘗試直接讀取（舊版 fallback 路徑）。
"""

import json
import os
import sys
import time
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


DATA_DIR  = _get_data_dir()
DATA_FILE = os.path.join(DATA_DIR, "wealth_matrix_data.json")   # 明文 JSON（主要本地檔）
_ENC_FILE = os.path.join(DATA_DIR, "wealth_matrix_data.enc")    # 舊加密檔（僅用於一次性遷移）
CLOUD_CFG   = os.path.join(DATA_DIR, "wm_cloud.json")
CONFIG_FILE = os.path.join(DATA_DIR, "wm_config.json")

_CLOUD_TIMEOUT   = 6
_SUPABASE_TABLE  = "wealthmatrix"
_SUPABASE_LEGACY_ROW = "singleton"   # 舊版單列 ID，用於 migration

# ── Auth 快取（記憶登入 token，避免每次操作都重新登入）─────────────────
_auth_cache: dict = {"token": None, "user_id": None, "expires_at": 0.0}

# ── 雲端推送安全旗標 ──────────────────────────────────────────────────
# True  = 資料來自 cloud / local，可安全推送
# False = fallback 空資料（斷線啟動），禁止推送防止蓋掉雲端真實資料
_cloud_push_allowed = False
_cloud_record_count = 0       # 上次 load_data 時雲端的筆數，推送前用來比對
_push_warning_callback = None  # save_data 被筆數保護攔截時呼叫 fn(msg: str)


def register_push_warning_callback(fn):
    """註冊推送攔截警告 callback：fn(msg: str)，在 save_data 推送被筆數保護停止時呼叫。"""
    global _push_warning_callback
    _push_warning_callback = fn


def set_cloud_sync_state(push_allowed: bool, record_count: int = 0):
    """讓 app 在用戶明確選擇本地資料後覆寫同步狀態，解除筆數鎖定。"""
    global _cloud_push_allowed, _cloud_record_count
    _cloud_push_allowed = push_allowed
    _cloud_record_count = record_count


# ── 舊版 .enc 遷移（try/import，cryptography 未安裝時跳過）─────────────
def _try_migrate_enc():
    """將舊 .enc 加密檔解密並存為明文 .json（一次性遷移）。回傳解密後的 dict 或 None。"""
    if not os.path.exists(_ENC_FILE):
        return None
    try:
        from cryptography.fernet import Fernet
        key_file = os.path.join(DATA_DIR, "wm.key")
        if not os.path.exists(key_file):
            raise FileNotFoundError("wm.key not found")
        with open(key_file, "rb") as f:
            key = f.read()
        fernet = Fernet(key)
        with open(_ENC_FILE, "rb") as f:
            raw = fernet.decrypt(f.read()).decode("utf-8")
        data = json.loads(raw)
        with open(DATA_FILE, "w", encoding="utf-8") as wf:
            json.dump(data, wf, ensure_ascii=False, indent=2)
        return data
    except ImportError:
        pass
    except Exception:
        pass
    # Fallback：舊版未安裝 cryptography 時 .enc 其實存的是明文 JSON
    try:
        with open(_ENC_FILE, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
        with open(DATA_FILE, "w", encoding="utf-8") as wf:
            json.dump(data, wf, ensure_ascii=False, indent=2)
        return data
    except Exception:
        return None


def _decrypt_fernet(payload_str: str):
    """解密 Fernet 密文（雲端 legacy 模式用，try/import）。"""
    try:
        from cryptography.fernet import Fernet
        key_file = os.path.join(DATA_DIR, "wm.key")
        if os.path.exists(key_file):
            with open(key_file, "rb") as f:
                key = f.read()
            fernet = Fernet(key)
            try:
                return json.loads(fernet.decrypt(payload_str.encode()).decode())
            except Exception:
                pass
    except ImportError:
        pass
    try:
        return json.loads(payload_str)  # fallback：明文
    except Exception:
        return None


# ── Supabase 設定讀取 ─────────────────────────────────────────────────
def _load_cloud_cfg():
    """讀取 wm_cloud.json，回傳 (url, anon_key, email, password)，
    任一必要欄位缺失則回傳 (None, None, None, None)。"""
    if not os.path.exists(CLOUD_CFG):
        return None, None, None, None
    try:
        with open(CLOUD_CFG, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        url   = cfg.get("supabase_url", "").rstrip("/")
        key   = cfg.get("supabase_key", "")
        email = cfg.get("email", "")
        pwd   = cfg.get("password", "")
        if url and key:
            return url, key, email, pwd
    except Exception:
        pass
    return None, None, None, None


# ── Supabase Auth 登入 ────────────────────────────────────────────────
def _sign_in(url: str, anon_key: str, email: str, password: str):
    """以 email/password 登入，回傳 (access_token, user_id, expires_in)。"""
    endpoint = f"{url}/auth/v1/token?grant_type=password"
    r = requests.post(
        endpoint,
        headers={"apikey": anon_key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=_CLOUD_TIMEOUT,
    )
    r.raise_for_status()
    d = r.json()
    return d["access_token"], d["user"]["id"], d.get("expires_in", 3600)


def _get_auth_context(url: str, anon_key: str, email: str, password: str):
    """
    回傳 (headers, row_id, is_auth_mode)。
    - is_auth_mode=True  : 使用 Supabase Auth，row_id = user UUID
    - is_auth_mode=False : legacy 模式，row_id = "singleton"
    auth 失敗時回傳 (None, None, False)。
    """
    global _auth_cache

    if not email or not password:
        return _make_headers(anon_key), _SUPABASE_LEGACY_ROW, False

    now = time.time()
    if _auth_cache["token"] and _auth_cache["expires_at"] > now + 60:
        headers = _make_headers(anon_key, _auth_cache["token"])
        return headers, _auth_cache["user_id"], True

    try:
        token, user_id, expires_in = _sign_in(url, anon_key, email, password)
        _auth_cache = {
            "token": token,
            "user_id": user_id,
            "expires_at": now + expires_in,
        }
        return _make_headers(anon_key, token), user_id, True
    except Exception:
        return None, None, False


def _make_headers(anon_key: str, token: str = None) -> dict:
    bearer = token or anon_key
    return {
        "apikey": anon_key,
        "Authorization": f"Bearer {bearer}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


# ── 雲端讀取 ─────────────────────────────────────────────────────────
def _cloud_pull(url: str, anon_key: str, email: str = "", password: str = ""):
    """
    從 Supabase 拉取資料，回傳解密後的 dict，或 None。

    Auth 模式：payload 為明文 JSON。
    Legacy 模式：payload 為 Fernet 密文。
    Migration：Auth 模式但 user UUID 列不存在時，嘗試讀 "singleton" 列（Fernet 解密）。
    """
    headers, row_id, is_auth = _get_auth_context(url, anon_key, email, password)
    if headers is None:
        return None

    def _fetch_row(rid, hdrs):
        ep = (f"{url}/rest/v1/{_SUPABASE_TABLE}"
              f"?id=eq.{rid}&select=payload,updated")
        r = requests.get(ep, headers=hdrs, timeout=_CLOUD_TIMEOUT)
        r.raise_for_status()
        return r.json()

    try:
        rows = _fetch_row(row_id, headers)

        # Migration：Auth 模式但 user UUID 列空，嘗試舊 singleton 列
        if is_auth and not rows:
            try:
                legacy_hdrs = _make_headers(anon_key)
                rows = _fetch_row(_SUPABASE_LEGACY_ROW, legacy_hdrs)
                if rows:
                    payload_str = rows[0].get("payload", "")
                    return _decrypt_fernet(payload_str)
            except Exception:
                pass
            return None

        if not rows:
            return None

        payload_str = rows[0].get("payload", "")
        if not payload_str:
            return None

        if is_auth:
            return json.loads(payload_str)          # 明文 JSON
        else:
            return _decrypt_fernet(payload_str)     # legacy Fernet 解密

    except Exception:
        return None


# ── 雲端寫入 ─────────────────────────────────────────────────────────
def _cloud_push(url: str, anon_key: str, email: str, password: str,
                payload_str: str) -> bool:
    """推送明文 JSON 到 Supabase（upsert）。"""
    headers, row_id, _ = _get_auth_context(url, anon_key, email, password)
    if headers is None:
        return False

    body = {
        "id":      row_id,
        "payload": payload_str,
        "updated": datetime.utcnow().isoformat(),
    }
    h = dict(headers)
    h["Prefer"] = "resolution=merge-duplicates,return=minimal"
    try:
        r = requests.post(
            f"{url}/rest/v1/{_SUPABASE_TABLE}",
            headers=h, json=body, timeout=_CLOUD_TIMEOUT,
        )
        r.raise_for_status()
        return True
    except Exception:
        return False


# ── 雲端 vs 本地：選較新的 ───────────────────────────────────────────
def _pick_newer(local_data, cloud_data):
    if cloud_data is None:
        return local_data
    if local_data is None:
        return cloud_data
    local_ts = local_data.get("_updated", "")
    cloud_ts = cloud_data.get("_updated", "")
    if not local_ts and not cloud_ts:
        return local_data   # 都沒時間戳，優先本地
    if not local_ts:
        return cloud_data
    if not cloud_ts:
        return local_data
    return cloud_data if cloud_ts >= local_ts else local_data


# ── 筆數統計（用於衝突保護）─────────────────────────────────────────
def _count_records(d: dict) -> int:
    """計算 banks + stocks + goals 總筆數，作為資料完整性指標。"""
    if not d:
        return 0
    return (len(d.get("banks", [])) +
            len(d.get("stocks", [])) +
            len(d.get("goals", [])))


# ── 本地讀取 ─────────────────────────────────────────────────────────
def _load_local():
    """讀取本地 JSON；若不存在則嘗試從舊 .enc 遷移。"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except Exception:
            pass
    return _try_migrate_enc()


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
        "_updated": "",
    }


def _apply_migrations(d: dict, default: dict) -> dict:
    if "dca_reminder" in d and isinstance(d["dca_reminder"], dict):
        default["dca_reminder"].update(d["dca_reminder"])
        d.pop("dca_reminder")
    default.update(d)
    if default["cashflow"] and not default["cashflow_monthly"]:
        for rec in default["cashflow"]:
            ym = rec["date"][:7]
            default["cashflow_monthly"].setdefault(ym, []).append(rec)
        default["cashflow"] = []
    return default


# ── 公開 API：load_data ───────────────────────────────────────────────
def load_data():
    """
    載入資料，回傳 (data, conflict_info)。

    - data        : 已套用 migration 的最終資料 dict
    - conflict_info: 偵測到可疑衝突時為 dict，否則為 None
        {
          "local_ts":    str,   # 本地 _updated 時間戳
          "cloud_ts":    str,   # 雲端 _updated 時間戳
          "local_count": int,   # 本地 banks+stocks+goals 筆數
          "cloud_count": int,   # 雲端 banks+stocks+goals 筆數
          "local_data":  dict,  # 未 migrate 的本地原始資料
          "cloud_data":  dict,  # 未 migrate 的雲端原始資料（dca_reminder 已 pop）
        }
      衝突時預設已載入雲端資料（較安全），app 可讓用戶選擇改用本地。

    衝突觸發條件：雲端可達 + 本地時間戳比雲端新 + 本地筆數 < 雲端筆數 70%
    （典型情境：舊電腦斷線期間曾儲存過，導致時間戳偏新但資料是舊版）
    """
    global _cloud_push_allowed, _cloud_record_count
    default = _default_data()

    local_raw = _load_local()

    sb_url, sb_key, sb_email, sb_pwd = _load_cloud_cfg()
    cloud_configured = bool(sb_url and sb_key)
    cloud_raw = None
    cloud_reachable = False
    conflict_info = None

    if cloud_configured:
        cloud_raw = _cloud_pull(sb_url, sb_key, sb_email, sb_pwd)
        cloud_reachable = cloud_raw is not None
        _cloud_record_count = _count_records(cloud_raw) if cloud_raw else 0
    else:
        _cloud_record_count = 0

    # 偵測可疑衝突：本地時間戳較新但筆數明顯較少（舊電腦場景）
    if cloud_reachable and local_raw is not None and cloud_raw is not None:
        local_ts = local_raw.get("_updated", "")
        cloud_ts = cloud_raw.get("_updated", "")
        if local_ts and cloud_ts and local_ts > cloud_ts:
            local_count = _count_records(local_raw)
            cloud_count = _count_records(cloud_raw)
            if cloud_count > 0 and local_count < cloud_count * 0.70:
                conflict_info = {
                    "local_ts":    local_ts,
                    "cloud_ts":    cloud_ts,
                    "local_count": local_count,
                    "cloud_count": cloud_count,
                    "local_data":  local_raw,   # 原始 dict，app 需自行 _apply_migrations
                    "cloud_data":  cloud_raw,
                }

    # 有衝突時預設用雲端（較安全），app.py 會彈出 dialog 讓用戶確認
    if conflict_info is not None:
        best_raw = cloud_raw
    else:
        best_raw = _pick_newer(local_raw, cloud_raw)

    if best_raw:
        result = _apply_migrations(best_raw, default)
        if cloud_configured and not cloud_reachable:
            _cloud_push_allowed = False
        else:
            _cloud_push_allowed = True
    else:
        result = default
        _cloud_push_allowed = False

    # 若雲端比本地新，同步更新本地備份
    if cloud_raw:
        cloud_ts = cloud_raw.get("_updated", "")
        local_ts = (local_raw or {}).get("_updated", "")
        if cloud_ts > local_ts:
            _save_local(result)

    return result, conflict_info


# ── 公開 API：save_data ───────────────────────────────────────────────
def save_data(data):
    """
    儲存資料：
    1. 立刻寫本地 JSON
    2. 非同步推送雲端（不阻塞 UI）
       ※ _cloud_push_allowed=False 時只存本地，防止蓋掉雲端真實資料。
       ※ 若本地筆數 < 雲端筆數 50%，停止推送並觸發 push_warning_callback。
    """
    global _cloud_push_allowed

    data["_updated"] = datetime.utcnow().isoformat()

    if "undo_stack" in data and len(data["undo_stack"]) > 20:
        data["undo_stack"] = data["undo_stack"][-20:]

    payload_str = json.dumps(data, ensure_ascii=False, indent=2)
    _save_local_raw(payload_str)

    if not _cloud_push_allowed:
        return

    sb_url, sb_key, sb_email, sb_pwd = _load_cloud_cfg()
    if not (sb_url and sb_key):
        return

    # 推送前筆數安全檢查：本地遠少於雲端 → 停止推送
    if _cloud_record_count > 0:
        local_count = _count_records(data)
        if local_count < _cloud_record_count * 0.50:
            _cloud_push_allowed = False
            if _push_warning_callback:
                _push_warning_callback(
                    f"雲端同步暫停：本地資料（{local_count} 筆）遠少於雲端"
                    f"（{_cloud_record_count} 筆），已停止推送以保護雲端資料。"
                    "請重新啟動程式確認資料完整性。"
                )
            return

    def _push():
        _cloud_push(sb_url, sb_key, sb_email, sb_pwd, payload_str)
    threading.Thread(target=_push, daemon=True).start()


def _save_local(data):
    payload_str = json.dumps(data, ensure_ascii=False, indent=2)
    _save_local_raw(payload_str)


def _save_local_raw(payload_str: str):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            f.write(payload_str)
    except Exception as e:
        print(f"Save error: {e}")


def is_cloud_push_allowed() -> bool:
    """回傳目前是否允許推送雲端（供 UI 顯示同步狀態用）"""
    return _cloud_push_allowed


# ── 現金流工具函數 ────────────────────────────────────────────────────
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
    current_year = date.today().year
    years_with_data = {
        int(k[:4]) for k in data.get("cashflow_monthly", {})
        if k and len(k) >= 4 and k[:4].isdigit()
    }
    base_range = set(range(current_year - 5, current_year + 2))
    return sorted(years_with_data | base_range, reverse=True)


# ── Undo Stack ────────────────────────────────────────────────────────
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


# ── DataFetcher（背景執行緒抓股價 / 匯率）────────────────────────────
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


# ── 本機設定（不同步雲端）────────────────────────────────────────────
def load_config() -> dict:
    """讀取 wm_config.json（本機設定，不上雲端）。失敗回傳空 dict。"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_config(cfg: dict):
    """寫入 wm_config.json。"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
