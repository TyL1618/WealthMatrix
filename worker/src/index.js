/**
 * WealthMatrix 股價代理（Cloudflare Worker）
 *
 * 為什麼需要：手機瀏覽器直接抓 Yahoo Finance 會被 CORS 擋下。這個 Worker 在伺服器端幫你抓，
 * 再加上 CORS 標頭回給你的 PWA。它只處理公開的股價，完全不碰你的財務資料。
 *
 * API
 *   GET /quote?symbols=0050.TW,2330.TW,AAPL
 *   → { fx: 31.5, quotes: { "0050.TW": { price, prevClose, currency, state, time }, ... }, at: <ms> }
 *   fx = USD/TWD（只在有美元計價的股票時才會抓）
 *
 * 安全
 *   - 只接受 ALLOWED_ORIGINS 裡的網頁來源（預設是你的 GitHub Pages），其他網站的 JS 叫不動它
 *   - 代號只允許英數與 . ^ = _ -，一次最多 30 檔；只轉發到 Yahoo Finance，不是開放代理
 *   - 結果快取 60 秒，避免被刷
 *
 * 環境變數（wrangler.jsonc 的 vars）
 *   ALLOWED_ORIGINS  逗號分隔的來源，例如 "https://tyl1618.github.io,http://localhost:7788"
 */

const DEFAULT_ORIGINS = ['https://tyl1618.github.io'];
const SYMBOL_RE = /^[A-Za-z0-9.^=_-]{1,15}$/;
const MAX_SYMBOLS = 30;
const CACHE_SECONDS = 60;
const YAHOO = 'https://query1.finance.yahoo.com/v8/finance/chart/';

export function allowedOrigins(env) {
  const raw = env && env.ALLOWED_ORIGINS;
  return raw ? String(raw).split(',').map(s => s.trim()).filter(Boolean) : DEFAULT_ORIGINS;
}

function corsHeaders(origin) {
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
    'Vary': 'Origin',
  };
}

function json(body, status, origin) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...(origin ? corsHeaders(origin) : {}) },
  });
}

export function parseSymbols(query) {
  const syms = [...new Set(String(query || '').split(',').map(s => s.trim()).filter(Boolean))];
  if (!syms.length) return { error: '缺少 symbols' };
  if (syms.length > MAX_SYMBOLS) return { error: `一次最多 ${MAX_SYMBOLS} 檔` };
  if (syms.some(s => !SYMBOL_RE.test(s))) return { error: '代號格式不正確' };
  return { symbols: syms };
}

// 從 Yahoo chart API 的回應取出報價；格式不對回傳 null
export function extractQuote(payload) {
  const meta = payload && payload.chart && payload.chart.result && payload.chart.result[0] && payload.chart.result[0].meta;
  if (!meta || !Number.isFinite(meta.regularMarketPrice)) return null;
  const prev = Number.isFinite(meta.chartPreviousClose) ? meta.chartPreviousClose
             : Number.isFinite(meta.previousClose) ? meta.previousClose : null;
  return {
    price: meta.regularMarketPrice,
    prevClose: prev,
    currency: meta.currency === 'USD' ? 'USD' : 'TWD',
    state: meta.marketState || '',
    time: meta.regularMarketTime || null,
  };
}

async function fetchOne(symbol) {
  try {
    const res = await fetch(`${YAHOO}${encodeURIComponent(symbol)}?interval=1d&range=5d`, {
      headers: { 'User-Agent': 'Mozilla/5.0 (WealthMatrix quote proxy)' },
    });
    if (!res.ok) return null;
    return extractQuote(await res.json());
  } catch {
    return null;
  }
}

export async function buildQuotes(symbols, fetcher = fetchOne) {
  const entries = await Promise.all(symbols.map(async s => [s, await fetcher(s)]));
  const quotes = {};
  for (const [s, q] of entries) if (q) quotes[s] = q;
  let fx = null;
  if (Object.values(quotes).some(q => q.currency === 'USD')) {
    const f = await fetcher('USDTWD=X');
    fx = f ? f.price : null;
  }
  return { fx, quotes, at: Date.now() };
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get('Origin') || '';
    const allowed = allowedOrigins(env);
    const originOk = !origin || allowed.includes(origin);        // 沒有 Origin（直接開網址 / curl）允許，方便你測試

    if (request.method === 'OPTIONS') {
      return originOk && origin ? new Response(null, { status: 204, headers: corsHeaders(origin) }) : new Response(null, { status: 403 });
    }
    if (!originOk) return json({ error: '來源不被允許' }, 403, null);
    if (request.method !== 'GET') return json({ error: '只支援 GET' }, 405, origin);
    if (url.pathname === '/' || url.pathname === '/health') return json({ ok: true, service: 'wealthmatrix-quotes' }, 200, origin);
    if (url.pathname !== '/quote') return json({ error: '找不到' }, 404, origin);

    const parsed = parseSymbols(url.searchParams.get('symbols'));
    if (parsed.error) return json({ error: parsed.error }, 400, origin);

    const cache = typeof caches !== 'undefined' ? caches.default : null;
    const cacheKey = new Request(`https://cache.local/quote?symbols=${[...parsed.symbols].sort().join(',')}`);
    if (cache) {
      const hit = await cache.match(cacheKey);
      if (hit) return json(await hit.json(), 200, origin);
    }
    const body = await buildQuotes(parsed.symbols);
    if (cache && ctx && ctx.waitUntil) {
      ctx.waitUntil(cache.put(cacheKey, new Response(JSON.stringify(body), {
        headers: { 'Content-Type': 'application/json', 'Cache-Control': `max-age=${CACHE_SECONDS}` },
      })));
    }
    return json(body, 200, origin);
  },
};
