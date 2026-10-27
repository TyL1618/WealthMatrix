"""
secret.py - 用 Windows DPAPI 保護本機密碼（不需要額外套件，PyInstaller onefile 也能用）

DPAPI 加密的資料只有「同一個 Windows 使用者帳號、同一台電腦」解得開，
所以 wm_cloud.json 裡的密碼就算被複製走（雲端硬碟、備份、不小心 commit）也沒有用。
代價：把 wm_cloud.json 複製到別台電腦時密碼解不開，第一次啟動會請你輸入一次密碼。

非 Windows 沒有 DPAPI：protect() 回傳 None，呼叫端應退回原本的明文存法。
"""
import base64
import sys

_ENTROPY = b"WealthMatrix.cloud.v1"   # 附加熵：別的程式即使同帳號也不會直接拿同一個 blob 去解

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32  = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    def _in_blob(data: bytes):
        buf = ctypes.create_string_buffer(data, len(data))
        return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _take(out: "_BLOB") -> bytes:
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def available() -> bool:
    return sys.platform == "win32"


def protect(text: str):
    """加密字串，回傳 base64 文字；失敗或不支援回傳 None。"""
    if not available():
        return None
    try:
        data, _keep1 = _in_blob(text.encode("utf-8"))
        ent, _keep2 = _in_blob(_ENTROPY)
        out = _BLOB()
        if not _crypt32.CryptProtectData(
            ctypes.byref(data), "WealthMatrix", ctypes.byref(ent), None, None, 0, ctypes.byref(out)
        ):
            return None
        return base64.b64encode(_take(out)).decode("ascii")
    except Exception:
        return None


def unprotect(token: str):
    """解密 protect() 的結果；不是這個使用者/電腦加密的、或資料毀損，回傳 None。"""
    if not available() or not token:
        return None
    try:
        raw = base64.b64decode(token.encode("ascii"), validate=True)
        data, _keep1 = _in_blob(raw)
        ent, _keep2 = _in_blob(_ENTROPY)
        out = _BLOB()
        if not _crypt32.CryptUnprotectData(
            ctypes.byref(data), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out)
        ):
            return None
        return _take(out).decode("utf-8")
    except Exception:
        return None
