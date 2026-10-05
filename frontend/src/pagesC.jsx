import React, { useEffect, useRef, useState } from 'react';
import { api, arr, makeFmt, timeAgo, useApi, useApp } from './api.js';
import { Badge, Empty, Field, Icon, Loading, Note, PageHead, Panel, Seg, Select, Stat, TableWrap, useToast } from './ui.jsx';
import { ErrorLine, PeriodPicker } from './pagesA.jsx';

// ───────────────────────── Ask AI (chat) ─────────────────────────
const STARTERS = ['How is my business doing?', 'Why did my sales change?', 'Which products need stock?', 'What are my top 5 products?', 'Which product is losing money?', 'What should I do this week?'];

export function Answer({ m, onAsk }) {
  const { go, refresh } = useApp();
  const toast = useToast();
  const meta = m.meta || {};
  async function add(a) { try { await api('/actions', { method: 'POST', body: { ...a, source: 'chat' } }); toast('Added to your Actions'); refresh(); } catch (e) { toast(e.message, 'bad'); } }
  return (
    <div className="msg bot">
      <div className="bubble">
        {String(m.text).split('\n\n').map((p, i) => <p key={i}>{p}</p>)}
        {arr(meta.facts).length > 0 && <div className="chips">{meta.facts.map((f, i) => <span key={i} className="chip"><small>{f.label}</small><strong>{String(f.value)}</strong></span>)}</div>}
        {meta.table && <TableWrap><table><thead><tr>{arr(meta.table.columns).map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>{arr(meta.table.rows).map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody></table></TableWrap>}
        {arr(meta.actions).length > 0 && <div className="row">{meta.actions.slice(0, 3).map((a, i) => <button key={i} className="btn small" onClick={() => add(a)}><Icon n="plus" size={15} />{a.title}</button>)}</div>}
        {meta.llm_error && <p className="muted small">AI could not be used ({meta.llm_error}) so this answer comes from DataPilot's own analysis.</p>}
        <div className="msg-foot"><span className="muted small">{meta.powered_by}</span>{meta.page && meta.page !== 'home' && <button className="link small" onClick={() => go(meta.page)}>See details</button>}</div>
      </div>
      {arr(meta.followups).length > 0 && onAsk && <div className="row suggest">{meta.followups.map(f => <button key={f} className="pill" onClick={() => onAsk(f)}>{f}</button>)}</div>}
    </div>
  );
}

export function Chat() {
  const { st } = useApp();
  const [msgs, setMsgs] = useState([]);
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const end = useRef(null);
  useEffect(() => { api('/chat/history').then(r => setMsgs(arr(r.messages))).catch(() => {}).finally(() => setLoaded(true)); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [msgs, busy]);
  async function send(text) {
    text = (text ?? q).trim();
    if (!text || busy) return;
    setQ(''); setError(null); setBusy(true);
    setMsgs(m => [...m, { id: 'u' + Date.now(), role: 'user', text }]);
    try {
      const r = await api('/chat', { method: 'POST', body: { question: text } });
      setMsgs(m => [...m, { id: 'a' + Date.now(), role: 'assistant', text: r.answer, meta: r }]);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function clear() { try { await api('/chat', { method: 'DELETE' }); setMsgs([]); } catch (e) { setError(e); } }
  const ai = st?.settings?.ai;
  return (
    <>
      <PageHead title="Ask DataPilot" sub="Ask in everyday words. Every number in the answer is calculated from your data."><button className="btn ghost" onClick={clear} disabled={!msgs.length}>Clear chat</button></PageHead>
      <div className="chatwrap">
        <section className="chat panel" aria-label="Conversation">
          <div className="chat-scroll">
            {!loaded ? <Loading /> : msgs.length === 0 ? (
              <div className="chat-empty"><Icon n="chat" size={30} /><h3>What would you like to know?</h3><p className="muted">Try one of these:</p>
                <div className="row center suggest">{STARTERS.map(s => <button key={s} className="pill" onClick={() => send(s)}>{s}</button>)}</div></div>
            ) : msgs.map((m, i) => m.role === 'user' ? <div key={m.id || i} className="msg me"><div className="bubble"><p>{m.text}</p></div></div> : <Answer key={m.id || i} m={m} onAsk={i === msgs.length - 1 ? send : null} />)}
            {busy && <div className="msg bot"><div className="bubble"><Loading text="Looking at your data…" /></div></div>}
            <div ref={end} />
          </div>
          {error && <ErrorLine error={error} />}
          <form className="composer" onSubmit={e => { e.preventDefault(); send(); }}>
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Ask about sales, profit, stock, customers…" aria-label="Your question" enterKeyHint="send" />
            <button className="btn primary" disabled={busy || !q.trim()} aria-label="Send"><Icon n="send" size={18} /><span className="hide-sm">Send</span></button>
          </form>
        </section>
        <aside className="chatside">
          <Panel title="Good to know">
            <p className="muted">{ai?.configured ? <>AI writing is <strong>on</strong> ({ai.model}). The AI only rephrases facts that DataPilot calculated first.</> : <>AI writing is <strong>off</strong>. You still get complete answers from DataPilot's own analysis. Add a key in Settings for more natural replies.</>}</p>
            <p className="muted">You can ask about a time period, like “last month” or “this month”.</p>
          </Panel>
        </aside>
      </div>
    </>
  );
}

// ───────────────────────── Agent Lab ─────────────────────────
const AGENTS = [['Data Profiler', 'Reads your file and recognises the columns.'], ['Quality Agent', 'Checks the numbers can be trusted.'], ['Signal Agent', 'Watches for unusual days, slowdowns and stock risks.'], ['Root-cause Agent', 'Finds what changed and which products or categories caused it.'], ['Forecast Agent', 'Looks ahead using the most accurate model on your history.'], ['Inventory Agent', 'Works out what to reorder and how much.'], ['Customer Agent', 'Finds loyal customers and those going quiet.'], ['Recommendation Agent', 'Ranks the next steps by urgency and impact.'], ['Approval Gate', 'Puts every suggestion in front of you. Nothing runs without a yes.']];

export function AgentOutput({ res, go }) {
  return (
    <>
          <Panel title="Summary" actions={<Badge tone="neutral">{res.powered_by}</Badge>}>
            {String(res.summary).split('\n\n').map((p, i) => <p key={i} className="verdict">{p}</p>)}
            {res.llm_error && <p className="muted small">AI could not be used ({res.llm_error}).</p>}
            {arr(res.findings).length > 0 && <ul className="bullets">{res.findings.map((f, i) => <li key={i}>{f}</li>)}</ul>}
          </Panel>
          <Panel title="What each agent did" sub={`Question: “${res.question}”`}>
            <ol className="steps">{arr(res.steps).map((s, i) => (
              <li key={i} className={s.status}><span className="step-dot">{s.status === 'done' ? <Icon n="check" size={16} /> : s.status === 'waiting' ? <Icon n="bell" size={16} /> : <Icon n="alert" size={16} />}</span>
                <div><strong>{s.name}</strong> <span className="muted small">· {s.role}{s.ms ? ` · ${s.ms} ms` : ''}</span><p>{s.detail}</p></div></li>))}</ol>
          </Panel>
          <Panel title="Suggested actions" sub="Waiting for your approval" actions={<button className="btn" onClick={() => go('actions')}>Review in Actions</button>}>
            {arr(res.recommendations).length ? <ul className="actions">{res.recommendations.map(a => <li key={a.id} className="action"><div className="action-main"><div className="row tight"><Badge tone={a.priority === 'high' ? 'bad' : a.priority === 'medium' ? 'warn' : 'neutral'}>{a.priority}</Badge></div><h3>{a.title}</h3><p>{a.description}</p></div></li>)}</ul> : <p className="muted">No actions needed right now.</p>}
          </Panel>
    </>
  );
}

export function Agents() {
  const { period, refresh, go } = useApp();
  const toast = useToast();
  const [q, setQ] = useState('What should I focus on this week?');
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const runs = useApi('/agent/runs');
  async function run() {
    setBusy(true); setErr(null);
    try { const r = await api('/agent/run', { method: 'POST', body: { question: q, period } }); setRes(r); refresh(); runs.reload(); }
    catch (e) { setErr(e); toast(e.message, 'bad'); } finally { setBusy(false); }
  }
  async function open(id) { try { setRes(await api('/agent/runs/' + id)); window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) { toast(e.message, 'bad'); } }
  return (
    <>
      <PageHead title="AI investigation" sub="A team of specialist agents checks your whole business, then hands you a short list of things to do."><PeriodPicker /></PageHead>
      <Panel>
        <Field label="What do you want investigated?"><textarea rows={2} value={q} onChange={e => setQ(e.target.value)} /></Field>
        <div className="row"><button className="btn primary big" disabled={busy || !q.trim()} onClick={run}>{busy ? 'Investigating…' : 'Run investigation'}</button>
          {['Why did sales drop?', 'What should I reorder?', 'Where am I losing money?'].map(s => <button key={s} className="pill" onClick={() => setQ(s)}>{s}</button>)}</div>
        {err && <ErrorLine error={err} />}
      </Panel>
      {busy && <Loading text="Agents are working on your data…" />}
      {res && !busy && <AgentOutput res={res} go={go} />}
      <div className="grid two">
        <Panel title="The team"><ul className="agentlist">{AGENTS.map(([n, d]) => <li key={n}><strong>{n}</strong><span className="muted">{d}</span></li>)}</ul></Panel>
        <Panel title="Past investigations">
          {arr(runs.data?.runs).length ? <ul className="dslist">{runs.data.runs.map(r => <li key={r.id}><div><strong>{r.question}</strong><p className="muted small">{timeAgo(r.created_at)}</p></div><button className="btn small" onClick={() => open(r.id)}>Open</button></li>)}</ul> : <p className="muted">Your investigations will be saved here.</p>}
        </Panel>
      </div>
    </>
  );
}

// ───────────────────────── Reports ─────────────────────────
export function Reports() {
  const { period, st } = useApp();
  const { data: r, error, loading, reload } = useApi('/report?period=' + period, [st?.dataset?.id, st?.dataset?.rows]);
  if (loading) return <Loading text="Preparing your report…" />;
  if (error) return <><PageHead title="Report" /><ErrorLine error={error} retry={reload} /></>;
  if (!r) return <><PageHead title="Business report" /><Empty title="The report is not ready" text="DataPilot did not receive any numbers. Try again in a moment." icon="file"><button className="btn primary" onClick={reload}>Try again</button></Empty></>;
  const f = makeFmt({ currency: r.currency, number_style: st?.settings?.profile?.number_style });
  return (
    <>
      <PageHead title="Business report" sub="A one-page summary you can print, save as PDF, or share with a partner, bank or accountant."><PeriodPicker /><button className="btn primary" onClick={() => window.print()}><Icon n="print" size={17} />Print or save as PDF</button></PageHead>
      <article className="report">
        <header><h2>{r.title}</h2><p className="muted">{r.period?.label} · {r.period?.text} · Data: {r.dataset} · Prepared {r.generated}</p></header>
        <section><h3>At a glance</h3>{arr(r.headline).map((l, i) => <p key={i}>{l}</p>)}
          <div className="stats">{arr(r.kpis).map(k => <Stat key={k.key} label={k.label} value={k.display} delta={k.change} />)}</div></section>
        {arr(r.insights).length > 0 && <section><h3>Key findings</h3><ul className="bullets">{r.insights.map(i => <li key={i.id}><strong>{i.title}.</strong> {i.detail}</li>)}</ul></section>}
        <div className="grid two">
          {arr(r.categories).length > 0 && <section><h3>Categories</h3><table><tbody>{r.categories.map(c => <tr key={c.name}><td>{c.name}</td><td className="r">{f.money(c.revenue)}</td><td className="r">{f.pct(c.share, false)}</td></tr>)}</tbody></table></section>}
          {arr(r.products).length > 0 && <section><h3>Products</h3><table><tbody>{r.products.map(c => <tr key={c.name}><td>{c.name}</td><td className="r">{f.money(c.revenue)}</td><td className="r">{f.pct(c.share, false)}</td></tr>)}</tbody></table></section>}
        </div>
        {arr(r.stock).length > 0 && <section><h3>Stock to reorder</h3><table><thead><tr><th>Product</th><th className="r">In stock</th><th className="r">Days left</th><th className="r">Order</th></tr></thead><tbody>{r.stock.map(i => <tr key={i.product}><td>{i.product}</td><td className="r">{f.num(i.stock)}</td><td className="r">{i.days_left === null ? '—' : i.days_left.toFixed(1)}</td><td className="r">{i.reorder_qty || '—'}</td></tr>)}</tbody></table></section>}
        <section><h3>Outlook</h3>{r.forecast?.available ? <p>Expected sales over the next {r.forecast.horizon} {r.forecast.unit}s: <strong>{f.money(r.forecast.summary?.total)}</strong> ({r.forecast.model}, about {Math.round(r.forecast.accuracy)}% accurate on past data).</p> : <p className="muted">{r.forecast?.reason || 'Not available.'}</p>}</section>
        {arr(r.signals).length > 0 && <section><h3>Warnings</h3><ul className="bullets">{r.signals.map(s => <li key={s.id}>{s.title}</li>)}</ul></section>}
        {arr(r.pending_actions).length > 0 && <section><h3>Decisions waiting</h3><ul className="bullets">{r.pending_actions.map(a => <li key={a.id}><strong>{a.title}</strong>{a.description ? ': ' + a.description : ''}</li>)}</ul></section>}
        <footer className="muted small">Data quality {r.quality}/100. {arr(r.notes).join(' ')} Forecasts and what-if results are estimates, not guarantees.</footer>
      </article>
    </>
  );
}

// ───────────────────────── Settings ─────────────────────────
export function Settings({ theme, setTheme, scale, setScale }) {
  const { data, error, loading, reload } = useApi('/settings');
  if (loading) return <Loading />;
  if (error) return <><PageHead title="Settings" /><ErrorLine error={error} retry={reload} /></>;
  if (!data) return <PageHead title="Settings" />;
  return <SettingsForm data={data} reload={reload} theme={theme} setTheme={setTheme} scale={scale} setScale={setScale} />;
}

export function SettingsForm({ data, reload, theme, setTheme, scale, setScale }) {
  const { refresh } = useApp();
  const toast = useToast();
  const [p, setP] = useState({ ...data.profile });
  const [ai, setAi] = useState({ ...data.ai });
  const [hook, setHook] = useState(data.webhook?.url || '');
  const [key, setKey] = useState('');
  const [test, setTest] = useState(null);
  const [busy, setBusy] = useState('');
  const [resetText, setResetText] = useState('');
  const presets = data.ai_presets || {};
  const sp = k => e => setP({ ...p, [k]: e.target.value });
  async function saveProfile() {
    setBusy('p');
    try { await api('/settings/profile', { method: 'POST', body: p }); toast('Business profile saved'); await refresh(); } catch (e) { toast(e.message, 'bad'); } finally { setBusy(''); }
  }
  function pickProvider(v) { const pr = presets[v] || {}; setAi({ ...ai, provider: v, base_url: v === 'custom' ? ai.base_url : '', model: pr.model || ai.model }); setTest(null); }
  async function saveAi(extra = {}) {
    setBusy('ai');
    try { const r = await api('/settings/ai', { method: 'POST', body: { provider: ai.provider, model: ai.model, base_url: ai.base_url, api_key: key, ...extra } }); setAi({ ...ai, ...r.ai }); setKey(''); toast(extra.remove_key ? 'Key removed' : 'AI settings saved'); await refresh(); reload(); return true; }
    catch (e) { toast(e.message, 'bad'); return false; } finally { setBusy(''); }
  }
  async function testAi() {
    setBusy('test'); setTest(null);
    if (key || ai.model) await saveAi();
    try { setTest(await api('/settings/ai/test', { method: 'POST' })); } catch (e) { setTest({ ok: false, error: e.message }); } finally { setBusy(''); }
  }
  async function saveHook() { try { await api('/settings/webhook', { method: 'POST', body: { url: hook } }); toast(hook ? 'Webhook saved' : 'Webhook removed'); } catch (e) { toast(e.message, 'bad'); } }
  async function reset() {
    try { await api('/settings/reset', { method: 'POST', body: { confirm: resetText } }); toast('Everything was cleared'); setResetText(''); await refresh(); } catch (e) { toast(e.message, 'bad'); }
  }
  const preset = presets[ai.provider] || {};
  return (
    <>
      <PageHead title="Settings" sub="Tell DataPilot about your business so the numbers and advice fit it." />
      <div className="grid two">
        <Panel title="Your business" actions={<button className="btn primary" disabled={busy === 'p'} onClick={saveProfile}>{busy === 'p' ? 'Saving…' : 'Save'}</button>}>
          <div className="formgrid one">
            <Field label="Business name"><input value={p.business_name || ''} onChange={sp('business_name')} placeholder="e.g. Sharma General Store" /></Field>
            <Field label="Your name"><input value={p.owner_name || ''} onChange={sp('owner_name')} /></Field>
            <Field label="Type of business"><select value={p.business_type} onChange={sp('business_type')}>{[['retail', 'Shop / retail'], ['restaurant', 'Restaurant / café'], ['wholesale', 'Wholesale / distribution'], ['online', 'Online store'], ['service', 'Services'], ['other', 'Other']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
            <div className="grid two"><Field label="Currency symbol"><input value={p.currency ?? ''} maxLength={4} onChange={sp('currency')} /></Field>
              <Field label="Number style"><select value={p.number_style} onChange={sp('number_style')}><option value="indian">Indian (1,00,000 · lakh, crore)</option><option value="international">International (100,000 · K, M)</option></select></Field></div>
            <Field label="Default period"><select value={p.default_period} onChange={sp('default_period')}>{arr(data.periods).map(x => <option key={x.key} value={x.key}>{x.label}</option>)}</select></Field>
            <Field label="Financial year starts in"><select value={p.fy_start_month} onChange={sp('fy_start_month')}>{['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'].map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</select></Field>
            <Field label="Typical cost of goods (% of sales)" hint="Only used when your data has no cost column. Profit will be marked as an estimate."><input type="number" min="0" max="99" step="any" inputMode="decimal" value={p.assumed_cost_pct ?? ''} placeholder="e.g. 75" onChange={sp('assumed_cost_pct')} /></Field>
          </div>
        </Panel>
        <div className="stack">
          <Panel title="Stock rules" actions={<button className="btn primary" disabled={busy === 'p'} onClick={saveProfile}>Save</button>}>
            <div className="formgrid one">
              <Field label="Warn when stock lasts fewer than (days)"><input type="number" min="1" value={p.low_stock_days} onChange={sp('low_stock_days')} /></Field>
              <Field label="Supplier delivery time (days)"><input type="number" min="1" value={p.lead_time_days} onChange={sp('lead_time_days')} /></Field>
              <Field label="Safety stock (days)" hint="Extra cover in case of delays."><input type="number" min="0" value={p.safety_days} onChange={sp('safety_days')} /></Field>
            </div>
          </Panel>
          <Panel title="How it looks">
            <Field label="Theme"><Seg label="Theme" value={theme} onChange={setTheme} options={[{ value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }]} /></Field>
            <Field label="Text size"><Seg label="Text size" value={scale} onChange={setScale} options={[{ value: 'm', label: 'Normal' }, { value: 'l', label: 'Large' }, { value: 'xl', label: 'Extra large' }]} /></Field>
          </Panel>
        </div>
      </div>
      <Panel title="AI assistant (optional)" sub="DataPilot works fully without it. Adding an AI service makes answers read more naturally. Numbers are always calculated by DataPilot, never by the AI."
        actions={<Badge tone={data.ai.configured ? 'good' : 'neutral'}>{data.ai.configured ? 'Connected' : 'Not connected'}</Badge>}>
        <div className="formgrid">
          <Field label="Service"><select value={ai.provider} onChange={e => pickProvider(e.target.value)}>{Object.entries(presets).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select></Field>
          <Field label="Model name" hint={preset.model ? `Suggested: ${preset.model}` : ''}><input value={ai.model || ''} onChange={e => setAi({ ...ai, model: e.target.value })} /></Field>
          {(ai.provider === 'custom' || ai.provider === 'ollama') && <Field label="Server address"><input value={ai.base_url || ''} placeholder={preset.base_url || 'https://…/v1'} onChange={e => setAi({ ...ai, base_url: e.target.value })} /></Field>}
          {preset.needs_key !== false && <Field label="API key" hint={data.ai.key_hint ? `A key ending ${data.ai.key_hint} is saved. Paste a new one to replace it.` : 'Stored only on this computer, by the DataPilot server.'}><input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} placeholder={data.ai.key_hint ? '••••••••' : 'sk-…'} /></Field>}
        </div>
        <div className="row"><button className="btn primary" disabled={!!busy} onClick={() => saveAi()}>{busy === 'ai' ? 'Saving…' : 'Save AI settings'}</button>
          <button className="btn" disabled={!!busy} onClick={testAi}>{busy === 'test' ? 'Testing…' : 'Test connection'}</button>
          {data.ai.key_hint && <button className="btn ghost danger" disabled={!!busy} onClick={() => saveAi({ remove_key: true })}>Remove key</button>}</div>
        {test && <Note kind={test.ok ? 'ok' : 'bad'}>{test.ok ? `Connected to ${test.provider} (${test.model}).` : test.error}</Note>}
      </Panel>
      <div className="grid two">
        <Panel title="Send approved actions elsewhere" sub="Optional. When you approve an action, DataPilot posts it to this link, so tools like Zapier, Make or n8n can send a WhatsApp, email or sheet row.">
          <Field label="Webhook link"><input type="url" value={hook} placeholder="https://hooks.example.com/…" onChange={e => setHook(e.target.value)} /></Field>
          <div className="row"><button className="btn primary" onClick={saveHook}>Save link</button>
            <button className="btn" disabled={!hook} onClick={async () => { try { const r = await api('/settings/webhook/test', { method: 'POST' }); toast(r.ok ? 'Test sent' : 'Failed: ' + r.error, r.ok ? 'ok' : 'bad'); } catch (e) { toast(e.message, 'bad'); } }}>Send a test</button></div>
        </Panel>
        <Panel title="Start over" sub="Deletes all datasets, actions, chats and saved scenarios from this computer. Your settings and AI key stay.">
          <Field label="Type RESET to confirm"><input value={resetText} onChange={e => setResetText(e.target.value)} /></Field>
          <button className="btn danger" disabled={resetText !== 'RESET'} onClick={reset}>Delete all my data</button>
        </Panel>
      </div>
    </>
  );
}
