import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AppCtx, api, arr, makeFmt, useApi } from './api.js';
import { Empty, ErrorBoundary, Icon, Loading, Note, ToastProvider, useToast } from './ui.jsx';
import { Customers, DataStudio, Home, Insights, Inventory } from './pagesA.jsx';
import { Actions, Automations, Forecast, Scenarios, Signals } from './pagesB.jsx';
import { Agents, Chat, Reports, Settings } from './pagesC.jsx';

const NAV = [
  { group: 'Overview', items: [['home', 'Home', 'home']] },
  { group: 'Understand', items: [['insights', 'Insights', 'insights'], ['inventory', 'Stock', 'box'], ['customers', 'Customers', 'users'], ['forecast', 'Forecast', 'trend'], ['signals', 'Signals', 'alert']] },
  { group: 'Decide', items: [['scenarios', 'What if…?', 'sliders'], ['actions', 'Actions', 'check'], ['automation', 'Automations', 'bolt']] },
  { group: 'Ask', items: [['chat', 'Ask DataPilot', 'chat'], ['agents', 'AI investigation', 'agents'], ['reports', 'Report', 'file']] },
  { group: 'Manage', items: [['data', 'Your data', 'db'], ['settings', 'Settings', 'gear']] },
];
const TITLES = Object.fromEntries(NAV.flatMap(g => g.items.map(i => [i[0], i[1]])));
const NEEDS_DATA = new Set(['home', 'insights', 'inventory', 'customers', 'forecast', 'signals', 'scenarios', 'chat', 'agents', 'reports']);
const MOBILE = [['home', 'Home', 'home'], ['insights', 'Insights', 'insights'], ['chat', 'Ask', 'chat'], ['actions', 'Actions', 'check'], ['more', 'More', 'menu']];
const pageFromHash = () => { const h = (window.location.hash || '').replace('#/', '').replace('#', ''); return TITLES[h] ? h : 'home'; };
const stored = (k, d) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
const store = (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };

function Welcome({ go }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <div className="welcome">
      <h1>Welcome to DataPilot</h1>
      <p className="lead">Add your sales and DataPilot will show what is making money, what is running out, and what to do next.</p>
      <div className="row center"><button className="btn primary big" onClick={() => go('data')}><Icon n="upload" size={20} />Add my sales file</button>
        <button className="btn big" disabled={busy} onClick={async () => { setBusy(true); try { await api('/sample', { method: 'POST' }); window.dispatchEvent(new Event('dp-refresh')); } catch (e) { toast(e.message, 'bad'); } finally { setBusy(false); } }}>{busy ? 'Loading…' : 'Explore a sample shop'}</button></div>
      <ul className="welcome-list"><li><strong>Any file works.</strong> CSV or Excel, with any column names. DataPilot recognises them and lets you correct it.</li><li><strong>Private.</strong> Your files stay on this computer.</li><li><strong>You stay in control.</strong> DataPilot suggests; you approve.</li></ul>
    </div>
  );
}

export default function App() {
  const [page, setPageState] = useState(pageFromHash());
  const [theme, setThemeS] = useState(stored('dpTheme', 'light'));
  const [scale, setScaleS] = useState(stored('dpScale', 'm'));
  const [period, setPeriodS] = useState(stored('dpPeriod', '30d'));
  const [menu, setMenu] = useState(false);
  const toastRef = useRef(null);
  const { data: st, error, loading, reload } = useApi('/state');

  const refresh = useCallback(() => reload(), [reload]);
  useEffect(() => { const f = () => reload(); window.addEventListener('dp-refresh', f); return () => window.removeEventListener('dp-refresh', f); }, [reload]);
  useEffect(() => { const f = () => setPageState(pageFromHash()); window.addEventListener('hashchange', f); return () => window.removeEventListener('hashchange', f); }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; store('dpTheme', theme); }, [theme]);
  useEffect(() => { document.documentElement.dataset.scale = scale; store('dpScale', scale); }, [scale]);
  useEffect(() => { setMenu(false); window.scrollTo(0, 0); document.title = `${TITLES[page] || 'DataPilot'} · DataPilot`; }, [page]);
  useEffect(() => { document.body.classList.toggle('noscroll', menu); }, [menu]);
  // Last-resort guard: an unexpected async error shows a message instead of silently breaking things.
  useEffect(() => {
    const f = e => toastRef.current?.(String(e.reason?.message || 'Something went wrong. Please try again.'), 'bad');
    window.addEventListener('unhandledrejection', f); return () => window.removeEventListener('unhandledrejection', f);
  }, []);

  const go = useCallback(p => { window.location.hash = '#/' + p; setPageState(p); }, []);
  const setPeriod = v => { setPeriodS(v); store('dpPeriod', v); };
  const profile = st?.settings?.profile || {};
  const fmt = makeFmt(profile);
  const ctx = { st, profile, fmt, period, setPeriod, refresh, go };

  let body;
  if (loading && !st) body = <Loading text="Opening DataPilot…" />;
  else if (error && !st) body = <div className="welcome"><Note kind="bad">{error.message}</Note><button className="btn primary" onClick={reload}>Try again</button></div>;
  else if (!st?.has_data && NEEDS_DATA.has(page)) body = page === 'home' ? <Welcome go={go} /> : <Empty title="Add your data first" text={st?.error || 'This page needs your sales data.'} icon="db"><button className="btn primary" onClick={() => go('data')}>Add data</button></Empty>;
  else {
    const P = { home: Home, insights: Insights, inventory: Inventory, customers: Customers, forecast: Forecast, signals: Signals, scenarios: Scenarios, actions: Actions, automation: Automations, chat: Chat, agents: Agents, reports: Reports, data: DataStudio }[page];
    body = P ? <P /> : <Settings theme={theme} setTheme={setThemeS} scale={scale} setScale={setScaleS} />;
  }
  const pending = st?.counts?.pending || 0;

  return (
    <AppCtx.Provider value={ctx}>
      <ToastProvider bridge={toastRef}>
        <div className="app">
          <a className="skip" href="#main">Skip to content</a>
          <aside className={'side' + (menu ? ' open' : '')} aria-label="Main menu">
            <div className="brand"><span className="logo"><Icon n="trend" size={22} /></span><div><strong>{profile.business_name || 'DataPilot'}</strong><small>{profile.business_name ? 'DataPilot' : 'Know your business'}</small></div>
              <button className="x only-mobile" onClick={() => setMenu(false)} aria-label="Close menu"><Icon n="close" /></button></div>
            <nav>{NAV.map(g => <div key={g.group} className="navgroup"><span className="navlabel">{g.group}</span>
              {g.items.map(([k, label, ico]) => <button key={k} className={page === k ? 'on' : ''} aria-current={page === k ? 'page' : undefined} onClick={() => go(k)}><Icon n={ico} size={21} /><span>{label}</span>{k === 'actions' && pending > 0 && <em className="count hot">{pending}</em>}</button>)}</div>)}</nav>
            <div className="side-foot"><button onClick={() => setThemeS(theme === 'dark' ? 'light' : 'dark')}><Icon n={theme === 'dark' ? 'sun' : 'moon'} size={20} /><span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span></button></div>
          </aside>
          {menu && <div className="scrim" onClick={() => setMenu(false)} />}
          <div className="content">
            <div className="topbar">
              <button className="icon-btn only-mobile" onClick={() => setMenu(true)} aria-label="Open menu"><Icon n="menu" /></button>
              <strong className="topbar-title">{TITLES[page]}</strong>
              <div className="topbar-right">
                {st?.dataset && <button className="dschip" onClick={() => go('data')} title="Open your data"><Icon n="db" size={16} /><span>{st.dataset.name}</span>{st.dataset.is_sample && <em>sample</em>}</button>}
                <button className="icon-btn bell" onClick={() => go('actions')} aria-label={`${pending} actions to review`}><Icon n="bell" />{pending > 0 && <span className="dot">{pending > 9 ? '9+' : pending}</span>}</button>
              </div>
            </div>
            <main id="main" tabIndex={-1}><ErrorBoundary resetKey={page + (st?.dataset?.id || '')}>{body}</ErrorBoundary></main>
          </div>
          <nav className="tabbar" aria-label="Quick menu">{MOBILE.map(([k, l, ico]) => <button key={k} className={page === k ? 'on' : ''} onClick={() => k === 'more' ? setMenu(true) : go(k)}><Icon n={ico} size={22} /><span>{l}</span>{k === 'actions' && pending > 0 && <em className="dot">{pending > 9 ? '9+' : pending}</em>}</button>)}</nav>
        </div>
      </ToastProvider>
    </AppCtx.Provider>
  );
}
