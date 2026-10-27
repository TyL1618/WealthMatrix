// JS 端對照共用向量：node --test tests/js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const L = require('../../docs/logic.js');
const here = path.dirname(fileURLToPath(import.meta.url));
const V = JSON.parse(readFileSync(path.join(here, '..', 'vectors.json'), 'utf8'));

const D = iso => { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d); };
const snake = s => s.replace(/[A-Z]/g, c => '_' + c.toLowerCase());
const snakeKeys = o => o && typeof o === 'object' && !Array.isArray(o) ? Object.fromEntries(Object.entries(o).map(([k, v]) => [snake(k), v])) : o;
const clone = o => JSON.parse(JSON.stringify(o));
// JSON 往返：把 undefined 欄位去掉，與 Python 產生的 JSON 一致
const norm = o => JSON.parse(JSON.stringify(o));
const approx = (a, b, eps = 1e-9) => (a === null || b === null) ? assert.equal(a, b) : assert.ok(Math.abs(a - b) <= eps, `${a} vs ${b}`);

test('normalizeTicker', () => { for (const c of V.normalize_ticker) assert.equal(L.normalizeTicker(c.in), c.out, String(c.in)); });
test('isIncomeRec', () => { for (const c of V.is_income) assert.equal(L.isIncomeRec(c.in), c.out, JSON.stringify(c.in)); });

test('loan schedule / status / balance', () => {
  for (const c of V.loans) {
    assert.deepEqual(norm(L.loanSchedule(c.loan)), c.schedule, JSON.stringify(c.loan));
    for (const [t, exp] of Object.entries(c.status)) {
      const got = snakeKeys(L.loanStatus(c.loan, D(t)));
      assert.deepEqual(norm(got), exp, `${JSON.stringify(c.loan)} @ ${t}`);
      assert.equal(L.liabBalance(c.loan, D(t)), c.balance[t]);
    }
  }
});
test('loan paid_override', () => {
  for (const c of V.loan_overrides) assert.deepEqual(norm(snakeKeys(L.loanStatus(c.loan, D(c.today)))), c.status);
});
test('validateLoan', () => { for (const c of V.loan_validation) assert.equal(L.validateLoan(c.loan), c.error, JSON.stringify(c.loan)); });

test('trades / dividends', () => {
  for (const sc of V.trades) {
    const data = clone(sc.start);
    const errors = sc.ops.map(op => op.kind === 'div' ? L.addDividend(data, op.div) : L.applyTrade(data, op.trade));
    assert.deepEqual(errors, sc.errors, sc.name);
    assert.deepEqual(norm(data), sc.final, sc.name);
  }
});

test('portfolioSummary', () => {
  for (const c of V.summary) {
    const priceOf = s => c.prices[s.ticker] !== undefined ? c.prices[s.ticker] : s.last_price;
    assert.deepEqual(norm(snakeKeys(L.portfolioSummary(c.data, c.year, priceOf))), c.out);
  }
});

test('xirr', () => { for (const c of V.xirr) approx(L.xirr(c.flows), c.out); });
test('portfolioXirr', () => {
  for (const c of V.portfolio_xirr) {
    const priceOf = s => c.prices[s.ticker] !== undefined ? c.prices[s.ticker] : s.last_price;
    const got = L.portfolioXirr(c.data, c.today, priceOf);
    assert.deepEqual(got.included, c.out.included, c.name);
    assert.deepEqual(got.excluded, c.out.excluded, c.name);
    assert.equal(got.start, c.out.start, c.name);
    assert.equal(got.days, c.out.days, c.name);
    assert.equal(got.flows, c.out.flows, c.name);
    approx(got.rate, c.out.rate);
  }
});

test('budgets (含按月覆寫)', () => {
  for (const c of V.budgets) {
    assert.deepEqual(norm(L.budgetLimits(c.data, c.key)), c.limits, c.key);
    const got = L.budgetStatus(c.data, c.key).map(r => ({ category: r.category, limit: r.limit, spent: r.spent, ratio: r.ratio }));
    assert.deepEqual(norm(got), c.status, c.key);
  }
});

test('monthBudgetOverride', () => { for (const c of V.budget_override) assert.deepEqual(norm(L.monthBudgetOverride(c.base, c.values)), c.out, JSON.stringify(c)); });

test('monthlySaving / goalProjection', () => {
  for (const c of V.saving) assert.equal(L.monthlySaving(c.data, D(c.today)), c.out);
  for (const c of V.goals) assert.deepEqual(norm(snakeKeys(L.goalProjection(c.goal, c.net_worth, c.saving, D(c.today)))), c.out, JSON.stringify(c.goal));
});

test('applyRecurring', () => {
  for (const c of V.recurring) {
    const data = clone(c.start);
    const counts = c.days.map(d => L.applyRecurring(data, D(d)));
    assert.deepEqual(counts, c.counts, c.name);
    assert.deepEqual(norm(data), c.final, c.name);
  }
});

test('setLoanRule', () => {
  for (const c of V.loan_rules) {
    const data = { liabilities: [clone(c.loan)], recurring: [], cashflow_monthly: {} };
    const log = [];
    for (const [op, arg] of c.steps) {
      if (op === 'set') { const r = L.setLoanRule(data, data.liabilities[0], arg); log.push(r === null ? null : (({ id, ...rest }) => rest)(r)); }
      else if (op === 'apply') log.push(L.applyRecurring(data, D(arg)));
      else if (op === 'edit') { Object.assign(data.liabilities[0], arg); log.push(null); }
    }
    data.recurring = data.recurring.map(({ id, ...rest }) => rest);
    for (const recs of Object.values(data.cashflow_monthly)) for (const r of recs) delete r.rec;
    assert.deepEqual(norm(log), c.log, c.name);
    assert.deepEqual(norm(data), c.final, c.name);
  }
});
