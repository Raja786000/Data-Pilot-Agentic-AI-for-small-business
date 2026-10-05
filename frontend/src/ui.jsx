import React, { Component, createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

// ───────── icons (inline, no dependency) ─────────
const P = {
  home: 'M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z',
  insights: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  box: 'M21 8l-9-5-9 5v8l9 5 9-5zM3 8l9 5 9-5M12 13v8',
  users: 'M17 20v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM21 20v-1a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8',
  trend: 'M3 17l6-6 4 4 8-8M15 7h6v6',
  alert: 'M12 3l10 18H2zM12 10v5M12 18h.01',
  sliders: 'M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4',
  check: 'M5 12l5 5 9-10',
  bolt: 'M13 2L4 14h7l-1 8 9-12h-7z',
  chat: 'M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-5.4A8 8 0 1 1 21 12z',
  agents: 'M12 2l2.4 5.6L20 10l-5.6 2.4L12 18l-2.4-5.6L4 10l5.6-2.4zM19 16l.9 2.1L22 19l-2.1.9L19 22l-.9-2.1L16 19l2.1-.9z',
  file: 'M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5M9 13h6M9 17h6',
  db: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
  menu: 'M4 6h16M4 12h16M4 18h16',
  close: 'M6 6l12 12M18 6L6 18',
  moon: 'M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10z',
  sun: 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5',
  upload: 'M12 16V4M7 9l5-5 5 5M4 20h16',
  download: 'M12 4v12M7 11l5 5 5-5M4 20h16',
  plus: 'M12 5v14M5 12h14',
  up: 'M12 19V5M6 11l6-6 6 6',
  down: 'M12 5v14M6 13l6 6 6-6',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  print: 'M7 9V3h10v6M7 17H4v-6h16v6h-3M7 14h10v7H7z',
  trash: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13',
  send: 'M22 2L11 13M22 2l-7 20-4-9-9-4z',
  bell: 'M18 8a6 6 0 1 0-12 0c0 7-3 8-3 8h18s-3-1-3-8M10 21a2 2 0 0 0 4 0',
  play: 'M6 4l14 8-14 8z',
  info: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01',
  arrow: 'M5 12h14M13 6l6 6-6 6',
};
export function Icon({ n, size = 20 }) {
  return <svg className="ico" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={P[n] || P.info} /></svg>;
}

// ───────── error boundary: a crash in one page can no longer blank the whole site ─────────
export class ErrorBoundary extends Component {
  constructor(p) { super(p); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err }; }
  componentDidCatch(err, info) { console.error('DataPilot UI error:', err, info?.componentStack); }
  componentDidUpdate(prev) { if (prev.resetKey !== this.props.resetKey && this.state.err) this.setState({ err: null }); }
  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className={this.props.full ? 'crash full' : 'crash'} role="alert">
        <h2>This part of the page hit a problem</h2>
        <p>Your data is safe. Nothing was lost or changed.</p>
        <p className="muted small">{String(this.state.err?.message || this.state.err)}</p>
        <div className="row">
          <button className="btn primary" onClick={() => this.setState({ err: null })}>Try again</button>
          <button className="btn" onClick={() => { window.location.hash = ''; window.location.reload(); }}>Reload DataPilot</button>
        </div>
      </div>
    );
  }
}

// ───────── toasts ─────────
const ToastCtx = createContext(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children, bridge }) {
  const [items, setItems] = useState([]);
  const push = useCallback((text, kind = 'ok') => {
    const id = Math.random().toString(36).slice(2);
    setItems(x => [...x.slice(-3), { id, text, kind }]);
    setTimeout(() => setItems(x => x.filter(i => i.id !== id)), kind === 'bad' ? 7000 : 4200);
  }, []);
  useEffect(() => { if (bridge) bridge.current = push; }, [bridge, push]);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">{items.map(i => <div key={i.id} className={'toast ' + i.kind}>{i.text}</div>)}</div>
    </ToastCtx.Provider>
  );
}

// ───────── building blocks ─────────
export function PageHead({ title, sub, children }) {
  return (
    <header className="pagehead">
      <div><h1>{title}</h1>{sub && <p className="lead">{sub}</p>}</div>
      {children && <div className="pagehead-actions">{children}</div>}
    </header>
  );
}
export const Panel = ({ title, sub, actions, children, className = '' }) => (
  <section className={'panel ' + className}>
    {(title || actions) && <div className="panel-head"><div>{title && <h2>{title}</h2>}{sub && <p className="muted">{sub}</p>}</div>{actions && <div className="row">{actions}</div>}</div>}
    {children}
  </section>
);
export const Loading = ({ text = 'Loading…' }) => <div className="loading" role="status"><span className="spin" />{text}</div>;
export const Empty = ({ title, text, children, icon = 'info' }) => (
  <div className="empty"><div className="empty-ico"><Icon n={icon} size={26} /></div><h3>{title}</h3>{text && <p>{text}</p>}{children && <div className="row center">{children}</div>}</div>
);
export const Note = ({ kind = 'info', children, onClose }) => (
  <div className={'note ' + kind} role={kind === 'bad' ? 'alert' : 'status'}><Icon n={kind === 'ok' ? 'check' : kind === 'info' ? 'info' : 'alert'} size={20} /><div>{children}</div>{onClose && <button className="x" onClick={onClose} aria-label="Dismiss"><Icon n="close" size={16} /></button>}</div>
);
export const Badge = ({ tone = 'neutral', children }) => <span className={'badge ' + tone}>{children}</span>;
export function Seg({ value, onChange, options, label }) {
  return <div className="seg" role="group" aria-label={label}>{options.map(o => <button key={o.value} type="button" className={value === o.value ? 'on' : ''} onClick={() => onChange(o.value)} aria-pressed={value === o.value}>{o.label}</button>)}</div>;
}
export function Select({ value, onChange, options, label, className = '' }) {
  return (
    <label className={'field inline ' + className}>
      {label && <span>{label}</span>}
      <select value={value ?? ''} onChange={e => onChange(e.target.value)}>{options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
    </label>
  );
}
export function Field({ label, hint, children }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small className="muted">{hint}</small>}</label>;
}
export function Delta({ v, fmt, invert }) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return null;
  const good = invert ? v <= 0 : v >= 0;
  return <span className={'delta ' + (Math.abs(v) < 0.05 ? 'flat' : good ? 'up' : 'down')}><Icon n={v >= 0 ? 'up' : 'down'} size={14} />{fmt ? fmt(v) : `${Math.abs(v).toFixed(1)}%`}</span>;
}
export function Stat({ label, value, sub, delta, fmt, tone, onClick }) {
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag className={'stat ' + (tone || '') + (onClick ? ' click' : '')} onClick={onClick}>
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      <span className="stat-foot">{delta !== undefined && delta !== null && <Delta v={delta} fmt={fmt} />}{sub && <span className="muted">{sub}</span>}</span>
    </Tag>
  );
}
export const TableWrap = ({ children }) => <div className="tablewrap" tabIndex={0}>{children}</div>;
export const Bar = ({ value, max = 100, tone = '' }) => <div className="bar" aria-hidden="true"><i className={tone} style={{ width: `${Math.max(0, Math.min(100, (value / (max || 1)) * 100))}%` }} /></div>;
export function download(name, text, type = 'text/csv') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url);
}
export function useDebounced(value, ms = 350) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}
