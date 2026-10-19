#!/usr/bin/env python3
"""
bake_config.py — 把 Supabase 連線設定「烤進」PWA（docs/index.html）

用途
----
讀取本機 %APPDATA%\\WealthMatrix\\wm_cloud.json 裡的 supabase_url 與
supabase_key，替換 docs/index.html 中的以下兩個佔位字串：

    const BAKED_URL = '__SUPABASE_URL__';
    const BAKED_KEY = '__SUPABASE_ANON_KEY__';

替換後，手機端 PWA 不再需要手動輸入 URL / anon key（清快取也不會遺失，
因為值跟著 index.html 一起由 GitHub Pages 送出）。登入只需 email + 密碼
一次，之後用指紋 / PIN 解鎖。

安全性
------
URL 與 anon key 是「公開金鑰」，由 Supabase RLS 保護：沒有帳號密碼登入
就讀不到任何資料。email / 密碼永遠不會被寫入程式碼。
※ 前提：Supabase 必須維持 RLS 開啟，且關閉匿名註冊。

執行
----
    python scripts/bake_config.py

完成後 git add / commit / push，GitHub Pages 幾分鐘內生效。
重新產生（例如重寫 index.html 後）直接再跑一次即可。
"""
import json
import os
import re
import sys
from pathlib import Path


def main() -> int:
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    cfg_path = Path(appdata) / "WealthMatrix" / "wm_cloud.json"
    html_path = Path(__file__).resolve().parent.parent / "docs" / "index.html"

    if not cfg_path.exists():
        print(f"[X] 找不到設定檔：{cfg_path}")
        print("    請先用電腦版 WealthMatrix 設定好雲端連線（會產生 wm_cloud.json）。")
        return 1
    if not html_path.exists():
        print(f"[X] 找不到：{html_path}")
        return 1

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"[X] 讀取 wm_cloud.json 失敗：{e}")
        return 1

    url = (cfg.get("supabase_url") or "").rstrip("/")
    key = cfg.get("supabase_key") or ""
    if not url or not key:
        print("[X] wm_cloud.json 缺少 supabase_url 或 supabase_key。")
        return 1
    if "'" in url or "'" in key:
        print("[X] URL / key 含單引號，無法安全內嵌，請檢查設定。")
        return 1

    html = html_path.read_text(encoding="utf-8")

    new_html, n_url = re.subn(
        r"const BAKED_URL = '[^']*';",
        f"const BAKED_URL = '{url}';",
        html,
    )
    new_html, n_key = re.subn(
        r"const BAKED_KEY = '[^']*';",
        f"const BAKED_KEY = '{key}';",
        new_html,
    )

    if n_url != 1 or n_key != 1:
        print(f"[X] 替換目標數量異常（URL={n_url}, KEY={n_key}），"
              "請確認 index.html 內含 BAKED_URL / BAKED_KEY 定義。")
        return 1

    html_path.write_text(new_html, encoding="utf-8")
    print("[OK] 已烤入連線設定。")
    print(f"     URL 長度 {len(url)}；anon key 長度 {len(key)}。")
    print("     接著：git add docs/index.html && git commit && git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
