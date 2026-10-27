/*
 * logic.js — WealthMatrix PWA 的純邏輯（不碰 DOM、不用全域 _data，全部以參數傳入）
 *
 * 與桌面版 wealthmatrix/core/calc.py、core/recurring.py 是「同一套規則的兩份實作」。
 * 兩邊共用 tests/vectors.json（由 tests/gen_vectors.py 以 Python 產生）：
 *   python -m unittest discover tests          → 驗證 Python 仍符合向量
 *   node --test tests/js                        → 驗證這個檔案符合同一份向量
 * 修改任何一邊的規則：先改 Python → 重新產生向量 → 讓 JS 測試通過。
 *
 * 瀏覽器：<script src="logic.js"> 之後使用全域 WMLogic；Node：require('./logic.js')。
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.WMLogic = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ════════════ 通用 ════════════
  const pad2 = n => String(n).padStart(2, '0');
  const rndInt = x => Math.floor(x + 0.5);                 // 與 Python _rnd 一致（正數四捨五入）
  const round2 = x => Math.round(x * 100) / 100;
  const round4 = x => Math.round(x * 10000) / 10000;
  const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

  function randHex(n) {
    const a = new Uint8Array(n);
    (globalThis.crypto || require('node:crypto').webcrypto).getRandomValues(a);
    return [...a].map(b => b.toString(16).padStart(2, '0')).join('');
  }

  const isoDate = d => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  function localDate(offsetDays = 0, now = new Date()) {
    const d = new Date(now.getTime());
    d.setDate(d.getDate() + offsetDays);
    return isoDate(d);
  }
  function monthKeyAt(offset, now = new Date()) {
    const d = new Date(now.getTime());
    d.setDate(1);
    d.setMonth(d.getMonth() + offset);
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
  }
  const monthIdx = (y, m1) => y * 12 + (m1 - 1);                        // m1 = 1..12
  const idxToYm = idx => `${Math.floor(idx / 12)}-${pad2(idx % 12 + 1)}`;

  // 桌面版寫的時間戳沒有時區且是微秒，PWA 寫的是 ISO Z 毫秒；統一轉成毫秒再比較
  function tsMs(s) {
    if (!s) return 0;
    let t = String(s).replace(/(\.\d{3})\d+/, '$1');
    if (!/(Z|[+-]\d\d:?\d\d)$/i.test(t)) t += 'Z';
    const ms = Date.parse(t);
    return isNaN(ms) ? 0 : ms;
  }

  // ════════════ 股票代號 / 記帳類型 ════════════
  function normalizeTicker(t) {
    t = String(t || '').trim().toUpperCase();
    return /^\d{4,6}[A-Z]?$/.test(t) ? t + '.TW' : t;
  }

  // 有 type 看 type；舊資料沒有 type 時看金額正負
  const isIncomeRec = r => r.type === '收入' ? true : r.type === '支出' ? false : (r.amount || 0) >= 0;

  // ════════════ 分期貸款 ════════════
  function parseYmd(str) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(str || '');
    if (!m) return null;
    const y = +m[1], mo = +m[2], d = +m[3];
    const dt = new Date(y, mo - 1, d);
    return dt.getFullYear() === y && dt.getMonth() === mo - 1 && dt.getDate() === d ? { y, mo, d } : null;
  }

  function addMonthsYmd(p, k) {
    const idx = p.y * 12 + (p.mo - 1) + k;
    const y = Math.floor(idx / 12), m = idx % 12;
    return `${y}-${pad2(m + 1)}-${pad2(Math.min(p.d, new Date(y, m + 1, 0).getDate()))}`;
  }

  function validateLoan(l) {
    const blank = v => v === undefined || v === null || v === '';
    if (blank(l.principal)) return '請輸入貸款總額';
    if (blank(l.rate)) return '請輸入年利率';
    if (blank(l.term)) return '請輸入總期數';
    const principal = Number(l.principal), rate = Number(l.rate), term = parseInt(l.term), grace = parseInt(l.grace || 0);
    if ([principal, rate, term, grace].some(Number.isNaN)) return '數字格式錯誤';
    if (!(principal > 0)) return '貸款總額必須大於 0';
    if (!(rate >= 0 && rate <= 100)) return '年利率必須在 0～100 之間';
    if (!(term >= 1 && term <= 600)) return '期數必須在 1～600 之間';
    if (!(grace >= 0 && grace < term)) return '寬限期必須小於總期數';
    if (!['annuity', 'equal_principal'].includes(l.method || 'annuity')) return '攤還方式不正確';
    if (!parseYmd(l.start)) return '首期繳款日格式必須是 YYYY-MM-DD';
    if (l.paid_override !== null && l.paid_override !== undefined && l.paid_override !== '') {
      const po = parseInt(l.paid_override);
      if (Number.isNaN(po)) return '已繳期數格式錯誤';
      if (!(po >= 0 && po <= term)) return '已繳期數必須在 0～總期數 之間';
    }
    return null;
  }

  function loanSchedule(l) {
    if (validateLoan(l)) return [];
    const P = Number(l.principal), r = Number(l.rate) / 1200;
    const n = parseInt(l.term), g = parseInt(l.grace || 0), m = n - g;
    const method = l.method || 'annuity';
    const start = parseYmd(l.start);
    let pmt = 0, base = 0;
    if (method === 'annuity') pmt = r === 0 ? rndInt(P / m) : rndInt(P * r * Math.pow(1 + r, m) / (Math.pow(1 + r, m) - 1));
    else base = rndInt(P / m);
    const rows = [];
    let bal = rndInt(P);
    for (let i = 1; i <= n; i++) {
      const interest = rndInt(bal * r);
      let prin;
      if (i <= g) prin = 0;
      else {
        const k = i - g;
        if (k === m) prin = bal;                                   // 最後一期把尾數補齊
        else if (method === 'annuity') prin = Math.min(bal, Math.max(0, pmt - interest));
        else prin = Math.min(bal, base);
      }
      bal -= prin;
      rows.push({ n: i, date: addMonthsYmd(start, i - 1), payment: interest + prin, interest, principal: prin, balance: bal });
    }
    return rows;
  }

  function loanStatus(l, now = new Date()) {
    const rows = loanSchedule(l);
    if (!rows.length) return null;
    const n = rows.length, P = rndInt(Number(l.principal));
    const todayIso = isoDate(now);
    const hasOverride = l.paid_override !== null && l.paid_override !== undefined && l.paid_override !== '';
    const paid = hasOverride ? parseInt(l.paid_override) : rows.filter(x => x.date <= todayIso).length;
    const balance = paid > 0 ? rows[paid - 1].balance : P;
    const nxt = paid < n ? rows[paid] : null;
    return {
      paid, term: n, remainingTerms: n - paid, done: paid >= n,
      balance, principalPaid: P - balance, progress: P ? (P - balance) / P : 0,
      nextDate: nxt ? nxt.date : null, nextPayment: nxt ? nxt.payment : 0,
      monthlyPayment: (nxt || rows[n - 1]).payment,
      totalInterest: rows.reduce((a, x) => a + x.interest, 0),
      interestPaid: rows.slice(0, paid).reduce((a, x) => a + x.interest, 0),
      endDate: rows[n - 1].date,
    };
  }

  function liabBalance(x, now = new Date()) {
    if (x.type === 'loan') { const st = loanStatus(x, now); if (st) return st.balance; }
    return x.amount || 0;
  }

  function refreshLoanAmounts(data, now = new Date()) {
    for (const x of data.liabilities || []) {
      if (x.type === 'loan') { const st = loanStatus(x, now); if (st) x.amount = st.balance; }
    }
  }

  const LOAN_CATEGORY = '貸款還款';
  const loanRuleEligible = l => (l.method || 'annuity') === 'annuity' && parseInt(l.grace || 0) === 0;

  // 建立 / 更新 / 移除與貸款綁定的固定收支規則（沿用舊規則的 generated，避免已入帳月份重複入帳）
  function setLoanRule(data, loan, enabled) {
    if (!data.recurring) data.recurring = [];
    const old = data.recurring.find(r => r.loan === loan.id);
    if (old) data.recurring.splice(data.recurring.indexOf(old), 1);
    const rows = loanSchedule(loan);
    if (!(enabled && rows.length && loanRuleEligible(loan))) return null;
    const rule = {
      id: (old && old.id) || 'r_' + randHex(4), type: '支出', category: LOAN_CATEGORY, amount: rows[0].payment,
      day: parseInt(loan.start.slice(8, 10)), note: loan.name || '', active: true,
      start: loan.start.slice(0, 7), end: rows[rows.length - 1].date.slice(0, 7),
      generated: old ? [...(old.generated || [])] : [], loan: loan.id,
    };
    data.recurring.push(rule);
    return rule;
  }

  // ════════════ 固定收支 ════════════
  const REC_MAX_BACKFILL = 12;

  function applyRecurring(data, now = new Date()) {
    const nowIdx = now.getFullYear() * 12 + now.getMonth();
    const todayDay = now.getDate();
    let added = 0;
    for (const rule of data.recurring || []) {
      if (rule.active === false) continue;
      const amt = Number(rule.amount), day = parseInt(rule.day);
      if (!rule.id || !(rule.type === '收入' || rule.type === '支出') ||
          !(amt > 0) || !(day >= 1 && day <= 31)) continue;

      let startIdx = nowIdx;
      if (/^\d{4}-\d{2}/.test(rule.start || '')) {
        startIdx = parseInt(rule.start.slice(0, 4)) * 12 + parseInt(rule.start.slice(5, 7)) - 1;
      }
      let lastIdx = nowIdx;                                          // 選填 end（YYYY-MM）：最後一個要產生的月份
      const em = /^(\d{4})-(\d{2})/.exec(rule.end || '');
      if (em) lastIdx = Math.min(lastIdx, parseInt(em[1]) * 12 + parseInt(em[2]) - 1);
      const gen = rule.generated = rule.generated || [];
      for (let idx = Math.max(startIdx, nowIdx - (REC_MAX_BACKFILL - 1)); idx <= lastIdx; idx++) {
        const y = Math.floor(idx / 12), m = idx % 12;
        const key = `${y}-${pad2(m + 1)}`;
        const d = Math.min(day, new Date(y, m + 1, 0).getDate());
        if (idx === nowIdx && d > todayDay) continue;                // 本月還沒到期
        if (gen.includes(key)) continue;
        if (!data.cashflow_monthly) data.cashflow_monthly = {};
        (data.cashflow_monthly[key] = data.cashflow_monthly[key] || []).push({
          date: `${key}-${pad2(d)}`,
          type: rule.type, category: rule.category || '', amount: amt,
          note: rule.note || '', rec: rule.id,
        });
        gen.push(key);
        added++;
      }
    }
    return added;
  }

  // ════════════ 交易 / 股利 / 損益 ════════════
  function findStock(data, ticker) {
    const t = normalizeTicker(ticker);
    return (data.stocks || []).find(s => normalizeTicker(s.ticker) === t) || null;
  }

  // 成功回傳 null，失敗回傳錯誤訊息（資料不變）
  function applyTrade(data, trade) {
    const ticker = normalizeTicker(trade.ticker);
    const side = trade.side;
    const shares = Number(trade.shares), price = Number(trade.price), fee = Number(trade.fee || 0);
    if (!ticker) return '請輸入股票代號';
    if (side !== 'buy' && side !== 'sell') return '類型必須是買進或賣出';
    if (!DATE_RE.test(trade.date || '')) return '日期格式必須是 YYYY-MM-DD';
    if ([shares, price, fee].some(Number.isNaN)) return '數字格式錯誤';
    if (!(shares > 0)) return '股數必須大於 0';
    if (price < 0 || fee < 0) return '價格與費用不可為負';

    if (!data.stocks) data.stocks = [];
    let stock = findStock(data, ticker);
    const rec = { id: trade.id || 't_' + randHex(4), date: trade.date, ticker, side, shares, price, fee, note: (trade.note || '').trim() };
    const holdingOf = s => s.holding_cost != null ? s.holding_cost : (s.cost || 0) * (s.shares || 0);

    if (side === 'buy') {
      if (!stock) { stock = { ticker, shares: 0, cost: 0, holding_cost: 0 }; data.stocks.push(stock); }
      const newShares = (stock.shares || 0) + shares;
      const newHolding = holdingOf(stock) + shares * price + fee;
      stock.shares = newShares;
      stock.holding_cost = round2(newHolding);
      stock.cost = round4(newHolding / newShares);
    } else {
      if (!stock || (stock.shares || 0) + 1e-9 < shares) {
        return `持股不足：${ticker} 目前只有 ${stock ? stock.shares : 0} 股`;
      }
      const holding = holdingOf(stock);
      const avg = stock.shares ? holding / stock.shares : 0;
      rec.realized = round2(shares * price - fee - avg * shares);
      const remain = stock.shares - shares;
      if (remain <= 1e-9) {
        data.stocks.splice(data.stocks.indexOf(stock), 1);        // 全部賣光：移除持股，損益留在交易記錄
      } else {
        stock.shares = remain;
        stock.holding_cost = round2(holding - avg * shares);
        stock.cost = round4(avg);                                   // 賣出不改變均價
      }
    }
    if (!data.transactions) data.transactions = [];
    data.transactions.push(rec);
    return null;
  }

  function addDividend(data, div) {
    const ticker = normalizeTicker(div.ticker);
    const amount = Number(div.amount);
    if (!ticker) return '請輸入股票代號';
    if (!DATE_RE.test(div.date || '')) return '日期格式必須是 YYYY-MM-DD';
    if (Number.isNaN(amount)) return '金額格式錯誤';
    if (!(amount > 0)) return '股利金額必須大於 0';
    if (!data.dividends) data.dividends = [];
    data.dividends.push({ id: div.id || 'd_' + randHex(4), date: div.date, ticker, amount, note: (div.note || '').trim() });
    return null;
  }

  // priceOf(stock) → 目前價格或 null/undefined；預設用 last_price（PWA 沒有報價來源時）
  const defaultPriceOf = s => s.last_price;

  function portfolioSummary(data, year, priceOf = defaultPriceOf) {
    let unrealized = 0, priced = 0;
    for (const s of data.stocks || []) {
      const price = priceOf(s);
      if (price == null) continue;
      const holding = s.holding_cost != null ? s.holding_cost : (s.cost || 0) * (s.shares || 0);
      unrealized += price * (s.shares || 0) - holding;
      priced++;
    }
    const y = String(year);
    const sells = (data.transactions || []).filter(t => t.side === 'sell');
    const rTotal = sells.reduce((a, t) => a + (t.realized || 0), 0);
    const rYear = sells.filter(t => (t.date || '').startsWith(y)).reduce((a, t) => a + (t.realized || 0), 0);
    const divs = data.dividends || [];
    const dTotal = divs.reduce((a, d) => a + (d.amount || 0), 0);
    const dYear = divs.filter(d => (d.date || '').startsWith(y)).reduce((a, d) => a + (d.amount || 0), 0);
    return { unrealized, priced, realizedTotal: rTotal, realizedYear: rYear, dividendsTotal: dTotal, dividendsYear: dYear,
             totalReturn: unrealized + rTotal + dTotal };
  }

  // ── 年化報酬（XIRR）──────────────────────────────────────
  // flows: [{date:'YYYY-MM-DD', amount}]，投入為負、收回為正。無解或資料不足回傳 null。
  function xirr(flows) {
    const fl = flows.filter(f => f.amount !== 0 && DATE_RE.test(f.date || ''));
    if (!fl.some(f => f.amount < 0) || !fl.some(f => f.amount > 0)) return null;
    const t0 = Date.parse(fl.reduce((a, f) => (f.date < a ? f.date : a), fl[0].date) + 'T00:00:00Z');
    const yrs = fl.map(f => (Date.parse(f.date + 'T00:00:00Z') - t0) / 86400000 / 365);
    const npv = r => fl.reduce((a, f, i) => a + f.amount / Math.pow(1 + r, yrs[i]), 0);
    let lo = -0.9999, hi = 100;
    let flo = npv(lo), fhi = npv(hi);
    if (!isFinite(flo) || !isFinite(fhi) || flo * fhi > 0) return null;
    for (let i = 0; i < 200; i++) {
      const mid = (lo + hi) / 2, fm = npv(mid);
      if (flo * fm <= 0) { hi = mid; fhi = fm; } else { lo = mid; flo = fm; }
    }
    return (lo + hi) / 2;
  }

  // 只計入「帳本能完整解釋目前持股」的股票（買進 − 賣出 = 目前股數）；其餘列為 excluded
  function portfolioXirr(data, today, priceOf = defaultPriceOf, minDays = 30) {
    const net = {};
    for (const t of data.transactions || []) {
      net[t.ticker] = (net[t.ticker] || 0) + (t.side === 'buy' ? t.shares : -t.shares);
    }
    const holding = {};
    for (const s of data.stocks || []) holding[normalizeTicker(s.ticker)] = s;
    const included = [], excluded = [];
    const tickers = new Set([...Object.keys(net), ...Object.keys(holding)]);
    for (const tk of [...tickers].sort()) {
      const s = holding[tk];
      const have = s ? (s.shares || 0) : 0;
      const ledger = net[tk] || 0;
      if (Math.abs(have - ledger) > 1e-6) { excluded.push({ ticker: tk, reason: '缺少完整買進紀錄' }); continue; }
      if (s && have > 0 && priceOf(s) == null) { excluded.push({ ticker: tk, reason: '沒有報價' }); continue; }
      included.push(tk);
    }
    const inc = new Set(included);
    const flows = [];
    for (const t of data.transactions || []) {
      if (!inc.has(t.ticker)) continue;
      flows.push({ date: t.date, amount: t.side === 'buy' ? -(t.shares * t.price + (t.fee || 0)) : t.shares * t.price - (t.fee || 0) });
    }
    for (const d of data.dividends || []) if (inc.has(normalizeTicker(d.ticker))) flows.push({ date: d.date, amount: d.amount });
    let terminal = 0;
    for (const tk of included) { const s = holding[tk]; if (s && s.shares > 0) terminal += priceOf(s) * s.shares; }
    if (terminal > 0) flows.push({ date: today, amount: terminal });
    flows.sort((a, b) => a.date.localeCompare(b.date));
    const start = flows.length ? flows[0].date : null;
    const days = start ? (Date.parse(today + 'T00:00:00Z') - Date.parse(start + 'T00:00:00Z')) / 86400000 : 0;
    const rate = days >= minDays ? xirr(flows) : null;
    return { rate, included, excluded, start, days: Math.round(days), flows: flows.length };
  }

  // ════════════ 預算 ════════════
  const SAVING_CATS = ['投資買入'];            // 轉成資產，不算花掉

  function expenseByCategory(data, key) {
    const sums = {};
    for (const r of (data.cashflow_monthly || {})[key] || []) {
      if (isIncomeRec(r)) continue;
      const c = r.category || '其他';
      sums[c] = (sums[c] || 0) + Math.abs(r.amount);
    }
    return sums;
  }

  // 某月實際生效的預算：基本預算 + 該月覆寫（budgets_by_month[key]；覆寫值 <= 0 代表該月不設預算）
  function budgetLimits(data, key) {
    const out = {};
    for (const [c, v] of Object.entries(data.budgets || {})) out[c] = v;
    for (const [c, v] of Object.entries((data.budgets_by_month || {})[key] || {})) {
      if (Number(v) > 0) out[c] = v; else delete out[c];
    }
    return out;
  }

  // 「只有這個月」模式：把輸入值換算成要存進 budgets_by_month[月份] 的差異（與 calc.py 的 month_budget_override 相同）
  function monthBudgetOverride(base, values) {
    base = base || {};
    const out = {};
    for (const [cat, raw] of Object.entries(values || {})) {
      const v = Number(raw || 0) || 0, b = Number(base[cat] || 0) || 0;
      if (v > 0 && v !== b) out[cat] = v;
      else if (!(v > 0) && b > 0) out[cat] = 0;
    }
    return out;
  }

  function budgetStatus(data, key) {
    const spent = expenseByCategory(data, key);
    return Object.entries(budgetLimits(data, key))
      .map(([category, lim]) => ({ category, limit: Number(lim), spent: spent[category] || 0 }))
      .filter(x => x.limit > 0)
      .map(x => ({ ...x, ratio: x.spent / x.limit }))
      .sort((a, b) => (b.ratio - a.ratio) || (a.category < b.category ? -1 : a.category > b.category ? 1 : 0));   // 平手時依分類名稱，兩端順序一致
  }

  // ════════════ 存錢速度 / 目標 ════════════
  function monthlySaving(data, now = new Date()) {
    const cur = monthIdx(now.getFullYear(), now.getMonth() + 1);
    const vals = [];
    for (let off = 1; off <= 3; off++) {
      const recs = (data.cashflow_monthly || {})[idxToYm(cur - off)] || [];
      if (!recs.length) continue;
      let inc = 0, exp = 0;
      for (const r of recs) {
        if (isIncomeRec(r)) inc += Math.abs(r.amount);
        else if (!SAVING_CATS.includes(r.category)) exp += Math.abs(r.amount);
      }
      vals.push(inc - exp);
    }
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  }

  function goalProjection(goal, nw, saving, now = new Date()) {
    const remaining = Math.max(0, Number(goal.target || 0) - nw);
    const out = { remaining, done: remaining <= 0, monthsLeft: null, needPerMonth: null, etaMonths: null, eta: null, late: false };
    if (out.done) return out;
    const cur = monthIdx(now.getFullYear(), now.getMonth() + 1);
    let dl = null;
    const mm = /^(\d{4})-(\d{2})/.exec(goal.deadline || '');
    if (mm && +mm[2] >= 1 && +mm[2] <= 12) dl = monthIdx(+mm[1], +mm[2]);
    if (dl !== null) {
      out.monthsLeft = Math.max(0, dl - cur);
      out.needPerMonth = remaining / Math.max(1, out.monthsLeft);
    }
    if (saving !== null && saving > 0) {
      out.etaMonths = Math.ceil(remaining / saving);
      out.eta = idxToYm(cur + out.etaMonths);
    }
    if (dl !== null) out.late = out.etaMonths === null || cur + out.etaMonths > dl;
    return out;
  }

  // ════════════ 淨值歷史 ════════════
  const historySorted = data => (data.history || [])
    .filter(h => h && h.date && typeof h.total === 'number')
    .sort((a, b) => a.date.localeCompare(b.date));

  // 每天第一次補一筆當日資產；當天已有就不動。回傳是否有新增。
  function recordHistoryToday(data, totals, now = new Date()) {
    const t = localDate(0, now);
    let changed = false;
    const rows = [['history', 'total', totals.total], ['history_bank', 'bank', totals.bank],
                  ['history_cash', 'cash', totals.cash], ['history_stock', 'stock', totals.stock]];
    for (const [key, field, val] of rows) {
      const arr = data[key] = data[key] || [];
      if (arr.some(e => e.date === t)) continue;
      arr.push({ date: t, [field]: val });
      arr.sort((a, b) => a.date.localeCompare(b.date));
      if (arr.length > 365) data[key] = arr.slice(-365);
      changed = true;
    }
    return changed;
  }

  // ════════════ 舊資料補齊 ════════════
  function normalizeLegacy(d) {
    for (const recs of Object.values(d.cashflow_monthly || {})) {
      for (const r of recs) {
        if (r && r.type !== '收入' && r.type !== '支出') {
          const amt = Number(r.amount) || 0;
          r.type = amt >= 0 ? '收入' : '支出';
          r.amount = Math.abs(amt);
        }
      }
    }
    for (const s of d.stocks || []) if (s && s.ticker) s.ticker = normalizeTicker(s.ticker);
  }

  // ════════════ 搜尋記帳 ════════════
  // opts: {type: '收入'|'支出'|null}；query 空白 = 不依文字篩選。回傳新到舊排序。
  function searchRecords(data, query, opts = {}) {
    const q = String(query || '').trim().toLowerCase();
    const out = [];
    for (const [key, recs] of Object.entries(data.cashflow_monthly || {})) {
      recs.forEach((r, idx) => {
        const inc = isIncomeRec(r);
        if (opts.type && (opts.type === '收入') !== inc) return;
        if (q) {
          const hay = [r.category, r.note, r.date, String(Math.abs(r.amount))].join(' ').toLowerCase();
          if (!q.split(/\s+/).every(tok => hay.includes(tok))) return;
        }
        out.push({ key, idx, rec: r, income: inc });
      });
    }
    return out.sort((a, b) => (b.rec.date || '').localeCompare(a.rec.date || ''));
  }

  // ════════════ 股價 ════════════
  // quotes: {fx?: number, quotes: {TICKER: {price, prevClose, currency, state, time}}}
  function quoteTWD(q, fx) {
    if (!q || q.price == null) return null;
    return q.currency === 'USD' ? (fx ? q.price * fx : null) : q.price;
  }

  // 把報價寫進 stocks 的 last_price / last_updated；回傳更新了幾檔
  function applyQuotesToStocks(data, quotePack, now = new Date()) {
    if (!quotePack || !quotePack.quotes) return 0;
    let n = 0;
    for (const s of data.stocks || []) {
      const p = quoteTWD(quotePack.quotes[s.ticker], quotePack.fx);
      if (p == null) continue;
      s.last_price = round2(p);
      s.last_updated = localDate(0, now);
      n++;
    }
    if (quotePack.fx) { data.usd_rate = quotePack.fx; data.usd_rate_date = localDate(0, now); }
    return n;
  }


  // ════════════ 定期定額提醒 ════════════
  // 每月從提醒日起，本月還沒提醒過就該提醒（比桌面版「只有提醒日當天」更不容易漏掉；桌面版提醒後會寫 last_reminded，兩邊不會重複提醒）
  function dcaDue(dca, now = new Date()) {
    if (!dca || !dca.enabled) return false;
    const day = parseInt(dca.day);
    if (!(day >= 1 && day <= 28)) return false;
    if (now.getDate() < day) return false;
    return String(dca.last_reminded || '').slice(0, 7) !== `${now.getFullYear()}-${pad2(now.getMonth() + 1)}`;
  }

  // ════════════ 股價代理（Cloudflare Worker）════════════
  // 回傳要呼叫的網址；代理網址不是 https（本機測試的 localhost 除外）或沒有股票時回傳 null
  function quoteUrl(proxy, tickers) {
    const base = String(proxy || '').trim().replace(/\/+$/, '');
    if (!/^https:\/\/[^\s/]+/i.test(base) && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(base)) return null;
    const syms = [...new Set((tickers || []).map(t => String(t).trim()).filter(Boolean))];
    if (!syms.length) return null;
    return `${base}/quote?symbols=${syms.map(encodeURIComponent).join(',')}`;
  }

  // 驗證代理回傳的格式；不合法回傳 null
  function parseQuoteResponse(json) {
    if (!json || typeof json !== 'object' || !json.quotes || typeof json.quotes !== 'object') return null;
    const quotes = {};
    for (const [sym, q] of Object.entries(json.quotes)) {
      if (!q || !Number.isFinite(Number(q.price))) continue;
      quotes[sym] = {
        price: Number(q.price),
        prevClose: Number.isFinite(Number(q.prevClose)) ? Number(q.prevClose) : null,
        currency: q.currency === 'USD' ? 'USD' : 'TWD',
        state: q.state || '', time: q.time || null,
      };
    }
    const fx = Number.isFinite(Number(json.fx)) && Number(json.fx) > 0 ? Number(json.fx) : null;
    return { fx, quotes };
  }

  // ════════════ 三方合併（PWA 與電腦同時修改時，自動合併而不是二選一）════════════
  const deepEqual = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const isPlainObj = v => v && typeof v === 'object' && !Array.isArray(v);
  const IGNORE_KEYS = new Set(['undo_stack', 'window_geometry', '_updated']);
  const HISTORY_KEYS = new Set(['history', 'history_bank', 'history_cash', 'history_stock']);

  // 有 id 或 rec（自動產生）標記的項目視為「集合」（同 key 只留一筆）；其餘視為多重集合（可有完全相同的兩筆）
  const itemKey = r => r && r.id ? 'id:' + r.id : r && r.rec ? 'rec:' + r.rec + '|' + r.date : null;
  const canon = r => JSON.stringify(r, Object.keys(r || {}).sort());

  function mergeRecordArrays(base, local, remote) {
    const count = arr => { const m = new Map(); for (const r of arr) m.set(canon(r), (m.get(canon(r)) || 0) + 1); return m; };
    const cb = count(base), cl = count(local), cr = count(remote);
    // 先把 remote 的刪除（base 有、local 沒有）套用，再把 local 新增（local 有、base 沒有）接在後面
    const removedByLocal = new Map(), addedByLocal = new Map();
    for (const [k, n] of cb) { const d = n - (cl.get(k) || 0); if (d > 0) removedByLocal.set(k, d); }
    for (const [k, n] of cl) { const d = n - (cb.get(k) || 0); if (d > 0) addedByLocal.set(k, d); }
    const out = [], seenSet = new Set();
    const pushItem = r => {
      const sk = itemKey(r);
      if (sk) { if (seenSet.has(sk)) return; seenSet.add(sk); }
      out.push(r);
    };
    for (const r of remote) {
      const k = canon(r), rm = removedByLocal.get(k) || 0;
      if (rm > 0) { removedByLocal.set(k, rm - 1); continue; }
      pushItem(r);
    }
    const addLeft = new Map(addedByLocal);
    for (const r of local) {
      const k = canon(r), n = addLeft.get(k) || 0;
      if (n > 0) { addLeft.set(k, n - 1); pushItem(r); }
    }
    return out;
  }

  function mergeHistory(local, remote) {
    const m = new Map();
    for (const e of remote || []) m.set(e.date, e);
    for (const e of local || []) if (!m.has(e.date)) m.set(e.date, e);
    return [...m.values()].sort((a, b) => a.date.localeCompare(b.date)).slice(-365);
  }

  // 固定收支規則：依 id 合併；同一條規則兩邊都改時，generated 取聯集、其餘欄位三方比較
  function mergeRules(base, local, remote, path, conflicts) {
    const byId = arr => new Map((arr || []).map(r => [r.id, r]));
    const mb = byId(base), ml = byId(local), mr = byId(remote);
    const ids = [...new Set([...mr.keys(), ...ml.keys()])];
    const out = [];
    for (const id of ids) {
      const b = mb.get(id), l = ml.get(id), r = mr.get(id);
      if (l && !r) { if (b) { if (!deepEqual(l, b)) conflicts.push(`${path}[${id}]`); continue; } out.push(l); continue; }   // remote 刪了
      if (r && !l) { if (b) { if (!deepEqual(r, b)) conflicts.push(`${path}[${id}]`); continue; } out.push(r); continue; }   // local 刪了
      if (deepEqual(l, r)) { out.push(l); continue; }
      const merged = merge3(b || {}, l, r, `${path}[${id}]`, conflicts, { generated: (bb, ll, rr) =>
        [...new Set([...(rr || []), ...(ll || [])])] });
      out.push(merged);
    }
    return out;
  }

  // 記帳按月份合併。不走「兩邊相同就直接採用」的捷徑：兩邊各自新增了一筆內容完全相同的記錄時，兩筆都要留
  function mergeMonths(base, local, remote) {
    const out = {};
    for (const k of new Set([...Object.keys(remote || {}), ...Object.keys(local || {})])) {
      const arr = mergeRecordArrays((base || {})[k] || [], (local || {})[k] || [], (remote || {})[k] || []);
      if (arr.length || (remote || {})[k] || (local || {})[k]) out[k] = arr;
    }
    return out;
  }

  function merge3(base, local, remote, path, conflicts, special = {}) {
    const key = path.split('.').pop().replace(/\[.*$/, '');
    if (path === 'cashflow_monthly') return mergeMonths(base, local, remote);
    if (path !== '') {                                  // 根物件一律逐欄位處理（見上方 mergeMonths 的原因）
      if (deepEqual(local, remote)) return local;
      if (deepEqual(local, base)) return remote;
      if (deepEqual(remote, base)) return local;
    }
    if (isPlainObj(local) && isPlainObj(remote)) {
      const out = {};
      const keys = new Set([...Object.keys(local), ...Object.keys(remote)]);
      for (const k of keys) {
        if (IGNORE_KEYS.has(k)) { out[k] = remote[k] !== undefined ? remote[k] : local[k]; continue; }
        const p = path ? path + '.' + k : k;
        const sp = special[k];
        let v;
        if (sp) v = sp(base ? base[k] : undefined, local[k], remote[k]);
        else if (path === '' && HISTORY_KEYS.has(k)) v = mergeHistory(local[k], remote[k]);
        else if (path === '' && (k === 'transactions' || k === 'dividends')) v = mergeRecordArrays((base || {})[k] || [], local[k] || [], remote[k] || []);
        else if (path === '' && k === 'recurring') v = mergeRules((base || {})[k] || [], local[k] || [], remote[k] || [], 'recurring', conflicts);
        else v = merge3(base ? base[k] : undefined, local[k], remote[k], p, conflicts);
        if (v !== undefined) out[k] = v;
      }
      return out;
    }
    conflicts.push(path || key);
    return remote;
  }

  // 回傳 { merged, conflicts }：conflicts 為空代表可自動合併；否則呼叫端應改問使用者
  function threeWayMerge(base, local, remote) {
    const conflicts = [];
    const merged = merge3(base || {}, local, remote, '', conflicts);
    return { merged, conflicts };
  }

  return {
    pad2, rndInt, round2, round4, randHex, isoDate, localDate, monthKeyAt, monthIdx, idxToYm, tsMs,
    normalizeTicker, isIncomeRec, normalizeLegacy,
    parseYmd, addMonthsYmd, validateLoan, loanSchedule, loanStatus, liabBalance, refreshLoanAmounts,
    LOAN_CATEGORY, loanRuleEligible, setLoanRule, REC_MAX_BACKFILL, applyRecurring,
    findStock, applyTrade, addDividend, portfolioSummary, xirr, portfolioXirr,
    SAVING_CATS, expenseByCategory, budgetLimits, monthBudgetOverride, budgetStatus, monthlySaving, goalProjection,
    historySorted, recordHistoryToday, searchRecords, quoteTWD, applyQuotesToStocks, threeWayMerge,
    dcaDue, quoteUrl, parseQuoteResponse,
  };
});
