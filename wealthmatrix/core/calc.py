"""
calc.py - 資產 / 負債 / 淨值計算（純函式，不依賴 Qt，桌面各處共用）

淨值 = 銀行 + 現金 + 股票市值 - 負債
股票沒有即時報價時以成本價估算（與 PWA 的 stockTotal 行為一致）。
"""


def bank_total(data: dict) -> float:
    return sum(b.get("amount", 0) for b in data.get("banks", []))


def liabilities_total(data: dict) -> float:
    return sum(x.get("amount", 0) for x in data.get("liabilities", []))


def stocks_total(data: dict, prices: dict) -> float:
    return sum(
        prices.get(s["ticker"], s.get("cost", 0)) * s["shares"]
        for s in data.get("stocks", [])
    )


def assets_total(data: dict, prices: dict) -> float:
    return bank_total(data) + data.get("cash", 0) + stocks_total(data, prices)


def net_worth(data: dict, prices: dict) -> float:
    return assets_total(data, prices) - liabilities_total(data)
