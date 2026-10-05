import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

const BASE = (typeof window !== 'undefined' && window.DP_API) || '';

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

/** Every call returns data or throws an ApiError with a message that is safe to show to the owner. */
export async function api(path, { method = 'GET', body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(BASE + '/api' + path, opts); }
  catch { throw new ApiError('Cannot reach the DataPilot server. Start the backend first (see RUN.md), then try again.', 0); }
  let data = null;
  try { data = await r.json(); } catch { /* non-JSON body */ }
  if (!r.ok) {
    const d = data && data.detail;
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map(x => x.msg).join(' ') : 'Something went wrong. Please try again.';
    throw new ApiError(msg, r.status);
  }
  return data;
}

/** Loads data from the API and keeps loading/error state, so a failed request can never blank the screen. */
export function useApi(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: !!path });
  const tick = useRef(0);
  const load = useCallback(async (silent = false) => {
    if (!path) { setState({ data: null, error: null, loading: false }); return; }
    const id = ++tick.current;
    if (!silent) setState(s => ({ ...s, loading: true, error: null }));
    try {
      const data = await api(path);
      if (id === tick.current) setState({ data, error: null, loading: false });
    } catch (e) {
      if (id === tick.current) setState(s => ({ data: silent ? s.data : null, error: e, loading: false }));
    }
  }, [path]); // eslint-disable-line
  useEffect(() => { load(); return () => { tick.current++; }; }, [load, ...deps]); // eslint-disable-line
  return { ...state, reload: () => load(true), refetch: () => load(false) };
}

export const AppCtx = createContext({ st: null, profile: {}, fmt: null, period: '30d', refresh: () => {}, go: () => {}, toast: () => {} });
export const useApp = () => useContext(AppCtx);

// ───────── number formatting (mirrors the server so charts and cards agree) ─────────
function indianGroup(n) {
  const s = String(Math.round(Math.abs(n)));
  if (s.length <= 3) return s;
  let head = s.slice(0, -3); const tail = s.slice(-3); const parts = [];
  while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
  if (head) parts.unshift(head);
  return [...parts, tail].join(',');
}

export function makeFmt(p = {}) {
  const sym = p.currency ?? '₹';
  const indian = (p.number_style || 'indian') === 'indian';
  const money = (v, compact = true) => {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
    v = Number(v);
    const a = Math.abs(v), sign = v < 0 ? '-' : '';
    if (indian) {
      if (compact && a >= 1e7) return `${sign}${sym}${(a / 1e7).toFixed(2)} Cr`;
      if (compact && a >= 1e5) return `${sign}${sym}${(a / 1e5).toFixed(2)} L`;
      return `${sign}${sym}${indianGroup(a)}`;
    }
    if (compact && a >= 1e9) return `${sign}${sym}${(a / 1e9).toFixed(2)}B`;
    if (compact && a >= 1e6) return `${sign}${sym}${(a / 1e6).toFixed(2)}M`;
    if (compact && a >= 1e4) return `${sign}${sym}${(a / 1e3).toFixed(1)}K`;
    return `${sign}${sym}${Math.round(a).toLocaleString('en-US')}`;
  };
  const num = v => (v === null || v === undefined || Number.isNaN(Number(v))) ? '—' : Number(v).toLocaleString(indian ? 'en-IN' : 'en-US', { maximumFractionDigits: Math.abs(v) >= 100 ? 0 : 1 });
  const pct = (v, signed = true) => (v === null || v === undefined || Number.isNaN(Number(v))) ? '—' : `${signed && v > 0 ? '+' : ''}${Number(v).toFixed(1)}%`;
  const axis = v => { const a = Math.abs(v); return indian ? (a >= 1e7 ? (v / 1e7).toFixed(1) + 'Cr' : a >= 1e5 ? (v / 1e5).toFixed(1) + 'L' : a >= 1e3 ? Math.round(v / 1e3) + 'k' : v) : (a >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : a >= 1e3 ? Math.round(v / 1e3) + 'k' : v); };
  return { money, num, pct, axis, sym };
}

export const shortDate = d => {
  if (!d) return '';
  const t = new Date(String(d).slice(0, 10) + 'T00:00:00');
  return Number.isNaN(t.getTime()) ? String(d) : t.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
};
export const longDate = d => {
  if (!d) return '';
  const t = new Date(String(d).slice(0, 10) + 'T00:00:00');
  return Number.isNaN(t.getTime()) ? String(d) : t.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
};
export const timeAgo = iso => {
  if (!iso) return '';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (Number.isNaN(s)) return '';
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
};
export const arr = x => (Array.isArray(x) ? x : []);
