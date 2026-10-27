// 只有 JS 端有的邏輯：三方合併、搜尋、報價、歷史快照、舊資料補齊
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const L = require('../../docs/logic.js');
const clone = o => JSON.parse(JSON.stringify(o));
const rec = (date, category, amount, type = '支出', extra = {}) => ({ date, type, category, amount, note: '', ...extra });
const base = () => ({
  banks: [{ name: '銀行', amount: 1000 }], cash: 50, goals: [], liabilities: [], stocks: [],
  cashflow_monthly: { '2026-10': [rec('2026-10-01', '薪資', 65000, '收入'), rec('2026-10-02', '餐飲', 100)] },
  transactions: [], dividends: [], recurring: [], budgets: { 餐飲: 5000 }, history: [{ date: '2026-10-01', total: 100 }],
  _updated: 'a',
});

test('merge: 兩邊各新增不同記帳 → 全部保留', () => {
  const b = base(), l = clone(b), r = clone(b);
  l.cashflow_monthly['2026-10'].push(rec('2026-10-05', '交通', 50));
  r.cashflow_monthly['2026-10'].push(rec('2026-10-06', '購物', 300));
  const { merged, conflicts } = L.threeWayMerge(b, l, r);
  assert.deepEqual(conflicts, []);
  const cats = merged.cashflow_monthly['2026-10'].map(x => x.category).sort();
  assert.deepEqual(cats, ['交通', '購物', '薪資', '餐飲'].sort());
});

test('merge: 一邊刪、一邊新增 → 刪除與新增都生效（不會復活）', () => {
  const b = base(), l = clone(b), r = clone(b);
  l.cashflow_monthly['2026-10'] = l.cashflow_monthly['2026-10'].filter(x => x.category !== '餐飲');     // local 刪餐飲
  r.cashflow_monthly['2026-10'].push(rec('2026-10-06', '購物', 300));                                  // remote 新增
  const { merged, conflicts } = L.threeWayMerge(b, l, r);
  assert.deepEqual(conflicts, []);
  assert.deepEqual(merged.cashflow_monthly['2026-10'].map(x => x.category).sort(), ['薪資', '購物'].sort());
});

test('merge: 兩邊各加一筆完全相同的記帳 → 保留兩筆（可能真的買了兩杯咖啡）', () => {
  const b = base(), l = clone(b), r = clone(b);
  l.cashflow_monthly['2026-10'].push(rec('2026-10-07', '餐飲', 80));
  r.cashflow_monthly['2026-10'].push(rec('2026-10-07', '餐飲', 80));
  const { merged } = L.threeWayMerge(b, l, r);
  assert.equal(merged.cashflow_monthly['2026-10'].filter(x => x.date === '2026-10-07').length, 2);
});

test('merge: 兩邊都自動產生同一筆固定收支 → 只留一筆，generated 取聯集', () => {
  const rule = { id: 'r_1', type: '支出', category: '房租', amount: 12000, day: 5, active: true, start: '2026-10', generated: [] };
  const b = { ...base(), recurring: [rule] };
  const mkSide = () => { const d = clone(b); L.applyRecurring(d, new Date(2026, 9, 10)); return d; };
  const { merged, conflicts } = L.threeWayMerge(b, mkSide(), mkSide());
  assert.deepEqual(conflicts, []);
  assert.equal(merged.cashflow_monthly['2026-10'].filter(x => x.rec === 'r_1').length, 1);
  assert.deepEqual(merged.recurring[0].generated, ['2026-10']);
});

test('merge: 兩邊各產生不同月份的固定收支 → generated 聯集、兩筆都在', () => {
  const rule = { id: 'r_1', type: '支出', category: '房租', amount: 12000, day: 5, active: true, start: '2026-09', generated: [] };
  const b = { ...base(), recurring: [rule] };
  const l = clone(b); L.applyRecurring(l, new Date(2026, 8, 10));       // 只到 9 月
  const r = clone(b); L.applyRecurring(r, new Date(2026, 9, 10));       // 到 10 月
  const { merged, conflicts } = L.threeWayMerge(b, l, r);
  assert.deepEqual(conflicts, []);
  assert.deepEqual([...merged.recurring[0].generated].sort(), ['2026-09', '2026-10']);
  assert.equal(merged.cashflow_monthly['2026-09'].filter(x => x.rec === 'r_1').length, 1);
  assert.equal(merged.cashflow_monthly['2026-10'].filter(x => x.rec === 'r_1').length, 1);
});

test('merge: 只有一邊改的欄位直接採用；不同欄位各改各的', () => {
  const b = base(), l = clone(b), r = clone(b);
  l.cash = 80;                                   // local 改現金
  r.banks[0].amount = 2000;                      // remote 改銀行
  r.budgets.交通 = 1500;                         // remote 加預算
  const { merged, conflicts } = L.threeWayMerge(b, l, r);
  assert.deepEqual(conflicts, []);
  assert.equal(merged.cash, 80);
  assert.equal(merged.banks[0].amount, 2000);
  assert.deepEqual(merged.budgets, { 餐飲: 5000, 交通: 1500 });
});

test('merge: 預算物件逐項合併（各改不同分類）', () => {
  const b = base(), l = clone(b), r = clone(b);
  l.budgets.餐飲 = 6000;
  r.budgets.娛樂 = 800;
  const { merged, conflicts } = L.threeWayMerge(b, l, r);
  assert.deepEqual(conflicts, []);
  assert.deepEqual(merged.budgets, { 餐飲: 6000, 娛樂: 800 });
});

test('merge: 兩邊改同一欄位成不同值 → 衝突，回報路徑', () => {
  const b = base(), l = clone(b), r = clone(b);
  l.cash = 80; r.cash = 90;
  l.banks[0].amount = 1; r.banks[0].amount = 2;
  const { conflicts } = L.threeWayMerge(b, l, r);
  assert.ok(conflicts.includes('cash'));
  assert.ok(conflicts.includes('banks'));
});

test('merge: 兩邊改成相同值不算衝突', () => {
  const b = base(), l = clone(b), r = clone(b);
  l.cash = 99; r.cash = 99;
  const { merged, conflicts } = L.threeWayMerge(b, l, r);
  assert.deepEqual(conflicts, []);
  assert.equal(merged.cash, 99);
});

test('merge: 交易與股利依 id 取聯集（不重複）', () => {
  const t1 = { id: 't1', date: '2026-10-01', ticker: '0050.TW', side: 'buy', shares: 1, price: 1, fee: 0 };
  const b = { ...base(), transactions: [t1] };
  const l = clone(b), r = clone(b);
  l.transactions.push({ id: 't2', date: '2026-10-02', ticker: '0050.TW', side: 'buy', shares: 1, price: 1, fee: 0 });
  r.transactions.push({ id: 't3', date: '2026-10-03', ticker: '0050.TW', side: 'buy', shares: 1, price: 1, fee: 0 });
  r.dividends.push({ id: 'd1', date: '2026-10-04', ticker: '0050.TW', amount: 5 });
  l.dividends.push({ id: 'd1', date: '2026-10-04', ticker: '0050.TW', amount: 5 });     // 同一筆兩邊都有
  const { merged } = L.threeWayMerge(b, l, r);
  assert.deepEqual(merged.transactions.map(t => t.id).sort(), ['t1', 't2', 't3']);
  assert.equal(merged.dividends.length, 1);
});

test('merge: 歷史走勢依日期聯集', () => {
  const b = base(), l = clone(b), r = clone(b);
  l.history.push({ date: '2026-10-02', total: 200 });
  r.history.push({ date: '2026-10-03', total: 300 });
  const { merged } = L.threeWayMerge(b, l, r);
  assert.deepEqual(merged.history.map(h => h.date), ['2026-10-01', '2026-10-02', '2026-10-03']);
});

test('merge: 規則被一邊刪、另一邊沒動 → 刪除；另一邊也改了 → 衝突', () => {
  const rule = { id: 'r_1', type: '支出', category: '房租', amount: 12000, day: 5, active: true, start: '2026-10', generated: [] };
  const b = { ...base(), recurring: [rule] };
  const l = clone(b), r = clone(b);
  l.recurring = [];
  assert.deepEqual(L.threeWayMerge(b, l, r).merged.recurring, []);
  r.recurring[0].amount = 13000;
  assert.ok(L.threeWayMerge(b, l, r).conflicts.some(c => c.startsWith('recurring')));
});

test('merge: 只有 remote 改 / 只有 local 改 / 都沒改', () => {
  const b = base();
  const r = clone(b); r.cash = 1;
  assert.equal(L.threeWayMerge(b, clone(b), r).merged.cash, 1);
  const l = clone(b); l.cash = 2;
  assert.equal(L.threeWayMerge(b, l, clone(b)).merged.cash, 2);
  const same = L.threeWayMerge(b, clone(b), clone(b));
  assert.deepEqual(same.conflicts, []);
});

test('merge: 不改輸入資料', () => {
  const b = base(), l = clone(b), r = clone(b);
  l.cashflow_monthly['2026-10'].push(rec('2026-10-05', '交通', 50));
  const lb = JSON.stringify(l), rb = JSON.stringify(r), bb = JSON.stringify(b);
  L.threeWayMerge(b, l, r);
  assert.equal(JSON.stringify(l), lb); assert.equal(JSON.stringify(r), rb); assert.equal(JSON.stringify(b), bb);
});

test('searchRecords', () => {
  const d = { cashflow_monthly: {
    '2026-10': [rec('2026-10-02', '餐飲', 100, '支出', { note: '早餐 咖啡' }), rec('2026-10-05', '薪資', 65000, '收入')],
    '2026-09': [rec('2026-09-20', '餐飲', 250, '支出', { note: '聚餐' }), { date: '2026-09-21', category: '舊資料', amount: -300 }] } };
  assert.deepEqual(L.searchRecords(d, '').map(x => x.rec.date), ['2026-10-05', '2026-10-02', '2026-09-21', '2026-09-20']);
  assert.deepEqual(L.searchRecords(d, '餐飲').map(x => x.rec.date), ['2026-10-02', '2026-09-20']);
  assert.deepEqual(L.searchRecords(d, '咖啡').map(x => x.rec.note), ['早餐 咖啡']);
  assert.equal(L.searchRecords(d, '早餐 咖啡').length, 1);                         // 多個關鍵字都要符合
  assert.deepEqual(L.searchRecords(d, '65000').map(x => x.rec.category), ['薪資']);
  assert.deepEqual(L.searchRecords(d, '300').map(x => x.rec.category), ['舊資料']);
  assert.equal(L.searchRecords(d, '', { type: '收入' }).length, 1);
  assert.equal(L.searchRecords(d, '', { type: '支出' }).length, 3);
  assert.equal(L.searchRecords(d, '2026-09').length, 2);
  assert.equal(L.searchRecords(d, 'zzz').length, 0);
  const hit = L.searchRecords(d, '聚餐')[0]; assert.deepEqual([hit.key, hit.idx, hit.income], ['2026-09', 0, false]);
});

test('quotes', () => {
  assert.equal(L.quoteTWD({ price: 185.2, currency: 'TWD' }, 31.5), 185.2);
  assert.equal(L.quoteTWD({ price: 200, currency: 'USD' }, 31.5), 6300);
  assert.equal(L.quoteTWD({ price: 200, currency: 'USD' }, 0), null);
  assert.equal(L.quoteTWD({ currency: 'TWD' }, 1), null);
  assert.equal(L.quoteTWD(undefined, 1), null);
  const d = { stocks: [{ ticker: '0050.TW', shares: 1 }, { ticker: 'AAPL', shares: 1 }, { ticker: 'NONE', shares: 1, last_price: 9 }] };
  const n = L.applyQuotesToStocks(d, { fx: 30, quotes: { '0050.TW': { price: 185.234, currency: 'TWD' }, AAPL: { price: 200, currency: 'USD' } } }, new Date(2026, 9, 27));
  assert.equal(n, 2);
  assert.deepEqual([d.stocks[0].last_price, d.stocks[1].last_price, d.stocks[2].last_price], [185.23, 6000, 9]);
  assert.equal(d.stocks[0].last_updated, '2026-10-27');
  assert.deepEqual([d.usd_rate, d.usd_rate_date], [30, '2026-10-27']);
  assert.equal(L.applyQuotesToStocks({ stocks: [] }, null), 0);
});

test('recordHistoryToday', () => {
  const d = {}; const now = new Date(2026, 9, 27);
  assert.equal(L.recordHistoryToday(d, { total: 1, bank: 2, cash: 3, stock: 4 }, now), true);
  assert.deepEqual([d.history, d.history_bank, d.history_cash, d.history_stock].map(a => Object.values(a[0]).join()),
    ['2026-10-27,1', '2026-10-27,2', '2026-10-27,3', '2026-10-27,4']);
  assert.equal(L.recordHistoryToday(d, { total: 9, bank: 9, cash: 9, stock: 9 }, now), false);        // 當天已有不動
  assert.equal(d.history[0].total, 1);
  d.history = Array.from({ length: 365 }, (_, i) => ({ date: L.localDate(-(400 - i), now), total: i }));
  L.recordHistoryToday(d, { total: 5, bank: 0, cash: 0, stock: 0 }, now);
  assert.equal(d.history.length, 365);
});

test('normalizeLegacy / tsMs / dates', () => {
  const d = { cashflow_monthly: { '2026-10': [{ date: 'x', category: 'a', amount: 50000 }, { date: 'y', category: 'b', amount: -300 }, { type: '支出', amount: 5 }] },
              stocks: [{ ticker: '2330' }, { ticker: 'aapl' }, { ticker: '0050.TW' }] };
  L.normalizeLegacy(d);
  assert.deepEqual(d.cashflow_monthly['2026-10'].map(r => [r.type, r.amount]), [['收入', 50000], ['支出', 300], ['支出', 5]]);
  assert.deepEqual(d.stocks.map(s => s.ticker), ['2330.TW', 'AAPL', '0050.TW']);
  assert.equal(L.tsMs('2026-10-27T06:00:00.123456'), L.tsMs('2026-10-27T06:00:00.123Z'));
  assert.ok(L.tsMs('2026-10-27T06:00:01.000Z') > L.tsMs('2026-10-27T06:00:00.999999'));
  assert.equal(L.tsMs(''), 0); assert.equal(L.tsMs(null), 0);
  assert.equal(L.localDate(-1, new Date(2026, 2, 1)), '2026-02-28');
  assert.equal(L.monthKeyAt(-1, new Date(2026, 0, 31)), '2025-12');
  assert.equal(L.monthKeyAt(1, new Date(2026, 11, 31)), '2027-01');
});

test('dcaDue', () => {
  const dca = { enabled: true, day: 5, last_reminded: '' };
  assert.equal(L.dcaDue(dca, new Date(2026, 9, 4)), false);                       // 還沒到提醒日
  assert.equal(L.dcaDue(dca, new Date(2026, 9, 5)), true);
  assert.equal(L.dcaDue(dca, new Date(2026, 9, 27)), true);                        // 提醒日之後第一次開也提醒
  assert.equal(L.dcaDue({ ...dca, last_reminded: '2026-10-05' }, new Date(2026, 9, 27)), false);   // 桌面版這個月已提醒過
  assert.equal(L.dcaDue({ ...dca, last_reminded: '2026-09-05' }, new Date(2026, 9, 27)), true);    // 上個月提醒的，本月還沒
  assert.equal(L.dcaDue({ ...dca, enabled: false }, new Date(2026, 9, 27)), false);
  assert.equal(L.dcaDue({ ...dca, day: 0 }, new Date(2026, 9, 27)), false);
  assert.equal(L.dcaDue({ ...dca, day: 29 }, new Date(2026, 9, 31)), false);
  assert.equal(L.dcaDue(null, new Date()), false);
});

test('quoteUrl / parseQuoteResponse', () => {
  assert.equal(L.quoteUrl('https://w.example.workers.dev/', ['0050.TW', 'AAPL', '0050.TW', ' ']), 'https://w.example.workers.dev/quote?symbols=0050.TW,AAPL');
  assert.equal(L.quoteUrl('http://localhost:8787', ['AAPL']), 'http://localhost:8787/quote?symbols=AAPL');
  assert.equal(L.quoteUrl('http://evil.example.com', ['AAPL']), null);               // 非 https 不接受
  assert.equal(L.quoteUrl('', ['AAPL']), null);
  assert.equal(L.quoteUrl('https://x.dev', []), null);
  assert.equal(L.quoteUrl('https://x.dev', ['BRK-B', 'USDTWD=X']), 'https://x.dev/quote?symbols=BRK-B,USDTWD%3DX');
  assert.equal(L.parseQuoteResponse(null), null);
  assert.equal(L.parseQuoteResponse({}), null);
  const ok = L.parseQuoteResponse({ fx: '31.5', quotes: { A: { price: '10.5', prevClose: 10, currency: 'USD', state: 'REGULAR' }, B: { price: 'x' }, C: null, D: { price: 5 } } });
  assert.deepEqual(Object.keys(ok.quotes).sort(), ['A', 'D']);
  assert.deepEqual([ok.fx, ok.quotes.A.price, ok.quotes.A.currency, ok.quotes.D.currency, ok.quotes.D.prevClose], [31.5, 10.5, 'USD', 'TWD', null]);
  assert.equal(L.parseQuoteResponse({ fx: -1, quotes: {} }).fx, null);
});
