// 股價代理 Worker：用假的 fetch 測試（不會真的連網）
import { test } from 'node:test';
import assert from 'node:assert/strict';
import worker, { parseSymbols, extractQuote, buildQuotes, allowedOrigins } from '../../worker/src/index.js';

const yahoo = (price, extra = {}) => ({ chart: { result: [{ meta: { regularMarketPrice: price, chartPreviousClose: price - 1, currency: 'TWD', marketState: 'REGULAR', regularMarketTime: 1700000000, ...extra } }] } });

test('parseSymbols', () => {
  assert.deepEqual(parseSymbols('0050.TW, AAPL ,0050.TW'), { symbols: ['0050.TW', 'AAPL'] });
  assert.ok(parseSymbols('').error);
  assert.ok(parseSymbols(null).error);
  assert.ok(parseSymbols('a/b').error);
  assert.ok(parseSymbols('AAPL;rm').error);
  assert.ok(parseSymbols('x'.repeat(16)).error);
  assert.ok(parseSymbols(Array.from({ length: 31 }, (_, i) => 'S' + i).join(',')).error);
  assert.equal(parseSymbols(Array.from({ length: 30 }, (_, i) => 'S' + i).join(',')).symbols.length, 30);
  assert.deepEqual(parseSymbols('USDTWD=X,BRK-B,^TWII').symbols, ['USDTWD=X', 'BRK-B', '^TWII']);
});

test('extractQuote', () => {
  assert.deepEqual(extractQuote(yahoo(185.2)), { price: 185.2, prevClose: 184.2, currency: 'TWD', state: 'REGULAR', time: 1700000000 });
  assert.equal(extractQuote(yahoo(10, { currency: 'USD' })).currency, 'USD');
  assert.equal(extractQuote(yahoo(10, { currency: 'JPY' })).currency, 'TWD');
  assert.equal(extractQuote(yahoo(10, { chartPreviousClose: undefined, previousClose: 9 })).prevClose, 9);
  assert.equal(extractQuote(yahoo(10, { chartPreviousClose: undefined })).prevClose, null);
  assert.equal(extractQuote(null), null);
  assert.equal(extractQuote({}), null);
  assert.equal(extractQuote({ chart: { result: [] } }), null);
  assert.equal(extractQuote(yahoo(NaN)), null);
});

test('buildQuotes：失敗的代號略過；有美元股票才抓匯率', async () => {
  const calls = [];
  const fetcher = async s => { calls.push(s); return s === 'BAD' ? null : s === 'USDTWD=X' ? { price: 31.5, currency: 'TWD' } : { price: 100, currency: s === 'AAPL' ? 'USD' : 'TWD' }; };
  let r = await buildQuotes(['0050.TW', 'BAD'], fetcher);
  assert.deepEqual(Object.keys(r.quotes), ['0050.TW']); assert.equal(r.fx, null); assert.ok(!calls.includes('USDTWD=X'));
  calls.length = 0;
  r = await buildQuotes(['AAPL', '0050.TW'], fetcher);
  assert.equal(r.fx, 31.5); assert.ok(calls.includes('USDTWD=X'));
  r = await buildQuotes(['AAPL'], async s => s === 'USDTWD=X' ? null : { price: 1, currency: 'USD' });
  assert.equal(r.fx, null);                                           // 匯率抓不到：fx 為 null，由前端沿用舊匯率
});

test('allowedOrigins', () => {
  assert.deepEqual(allowedOrigins({}), ['https://tyl1618.github.io']);
  assert.deepEqual(allowedOrigins({ ALLOWED_ORIGINS: 'https://a.dev, http://localhost:7788 ' }), ['https://a.dev', 'http://localhost:7788']);
});

function withFetch(handler, fn) {
  const orig = globalThis.fetch; globalThis.fetch = handler;
  return Promise.resolve(fn()).finally(() => { globalThis.fetch = orig; });
}
const req = (path, headers = {}, method = 'GET') => new Request('https://w.dev' + path, { method, headers });

test('HTTP：CORS、來源限制、錯誤處理', async () => {
  const env = {};
  const good = { Origin: 'https://tyl1618.github.io' };
  await withFetch(async url => new Response(JSON.stringify(yahoo(185.2)), { status: 200 }), async () => {
    let res = await worker.fetch(req('/quote?symbols=0050.TW', good), env, {});
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('Access-Control-Allow-Origin'), 'https://tyl1618.github.io');
    const body = await res.json();
    assert.equal(body.quotes['0050.TW'].price, 185.2);
    assert.equal(body.fx, null);

    res = await worker.fetch(req('/quote?symbols=0050.TW', { Origin: 'https://evil.example.com' }), env, {});
    assert.equal(res.status, 403);                                    // 其他網站不能用
    assert.equal(res.headers.get('Access-Control-Allow-Origin'), null);

    res = await worker.fetch(req('/quote?symbols=0050.TW'), env, {});
    assert.equal(res.status, 200);                                    // 沒有 Origin（直接測試）允許

    res = await worker.fetch(req('/quote', good), env, {}); assert.equal(res.status, 400);
    res = await worker.fetch(req('/quote?symbols=a/b', good), env, {}); assert.equal(res.status, 400);
    res = await worker.fetch(req('/nope', good), env, {}); assert.equal(res.status, 404);
    res = await worker.fetch(req('/quote?symbols=A', good, 'POST'), env, {}); assert.equal(res.status, 405);
    res = await worker.fetch(req('/health', good), env, {}); assert.equal((await res.json()).ok, true);

    res = await worker.fetch(req('/quote', { ...good, 'Access-Control-Request-Method': 'GET' }, 'OPTIONS'), env, {});
    assert.equal(res.status, 204);
    assert.equal(res.headers.get('Access-Control-Allow-Origin'), 'https://tyl1618.github.io');
    res = await worker.fetch(req('/quote', { Origin: 'https://evil.example.com' }, 'OPTIONS'), env, {});
    assert.equal(res.status, 403);
  });
});

test('HTTP：Yahoo 失敗時回傳空的 quotes 而不是錯誤', async () => {
  await withFetch(async () => new Response('nope', { status: 429 }), async () => {
    const res = await worker.fetch(req('/quote?symbols=0050.TW', { Origin: 'https://tyl1618.github.io' }), {}, {});
    assert.equal(res.status, 200);
    assert.deepEqual((await res.json()).quotes, {});
  });
});

test('HTTP：自訂 ALLOWED_ORIGINS', async () => {
  await withFetch(async () => new Response(JSON.stringify(yahoo(1)), { status: 200 }), async () => {
    const env = { ALLOWED_ORIGINS: 'http://localhost:7788' };
    assert.equal((await worker.fetch(req('/quote?symbols=A', { Origin: 'http://localhost:7788' }), env, {})).status, 200);
    assert.equal((await worker.fetch(req('/quote?symbols=A', { Origin: 'https://tyl1618.github.io' }), env, {})).status, 403);
  });
});
