import React, { useEffect, useState } from 'react';
import { Area, CartesianGrid, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api, arr, longDate, shortDate, timeAgo, useApi, useApp } from './api.js';
import { Badge, Empty, Field, Icon, Loading, Note, PageHead, Panel, Seg, Select, Stat, TableWrap, useDebounced, useToast } from './ui.jsx';
import { ErrorLine, PeriodPicker } from './pagesA.jsx';

const tick = { fontSize: 13, fill: 'var(--muted)' };
const tipStyle = { background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 10, fontSize: 14, color: 'var(--ink)' };

// ───────────────────────── Forecast ─────────────────────────
export function Forecast() {
  const { st, fmt, go } = useApp();
  const [metric, setMetric] = useState('revenue');
  const [horizon, setHorizon] = useState(0);
  const { data: f, error, loading, reload } = useApi(`/forecast?metric=${metric}&horizon=${horizon}`, [st?.dataset?.id, st?.dataset?.rows]);
  if (loading && !f) return <Loading text="Testing forecasting models on your history…" />;
  if (error) return <><PageHead title="Forecast" /><ErrorLine error={error} retry={reload} /></>;
  if (!f?.available) return <><PageHead title="Forecast" sub="What your sales are likely to do next." /><Empty title="A forecast is not possible yet" text={f?.reason} icon="trend"><button className="btn primary" onClick={() => go('data')}>Open column mapping</button></Empty></>;
  const hist = arr(f.history).map(p => ({ date: p.date, actual: p.value }));
  const last = hist[hist.length - 1];
  const fut = arr(f.forecast).map(p => ({ date: p.date, predicted: p.value, band: [p.lower, p.upper] }));
  const series = [...hist.map((h, i) => i === hist.length - 1 ? { ...h, predicted: h.actual } : h), ...fut];
  const unit = f.unit;
  const horizons = f.freq === 'D' ? [7, 14, 30, 60] : f.freq === 'W' ? [4, 8, 12, 26] : [3, 6, 12];
  const s = f.summary;
  const rel = { good: ['good', 'Good'], fair: ['warn', 'Fair'], low: ['bad', 'Low'] }[f.reliability] || ['neutral', '—'];
  const isMoney = f.metric === 'revenue' || f.metric === 'profit';
  const show = v => isMoney ? fmt.money(v) : fmt.num(v);
  return (
    <>
      <PageHead title="Forecast" sub={`DataPilot tested ${arr(f.backtest).length} methods on your own history and picked the most accurate one.`}>
        <Select label="Measure" value={metric} onChange={setMetric} options={arr(f.metrics).map(m => ({ value: m.key, label: m.label }))} />
        <Select label="Look ahead" value={String(f.horizon)} onChange={v => setHorizon(Number(v))} options={horizons.map(h => ({ value: String(h), label: `${h} ${unit}s` }))} />
      </PageHead>
      <div className="stats">
        <Stat label={`Expected ${f.metric_label.toLowerCase()}`} value={show(s.total)} delta={s.change} sub={`next ${f.horizon} ${unit}s`} />
        <Stat label={`Average per ${unit}`} value={show(s.average)} />
        <Stat label="Strongest" value={shortDate(s.peak)} sub="expected best" />
        <Stat label="Forecast reliability" value={<Badge tone={rel[0]}>{rel[1]}</Badge>} sub={`${f.accuracy.toFixed(0)}% accurate on past data`} />
      </div>
      <Panel title={`${f.metric_label} forecast`} sub="The shaded area is the likely range. Real results will usually land inside it.">
        <div className="chart"><ResponsiveContainer width="100%" height={380}>
          <ComposedChart data={series} margin={{ left: 0, right: 8, top: 8 }}>
            <CartesianGrid stroke="var(--line)" vertical={false} />
            <XAxis dataKey="date" tick={tick} tickFormatter={shortDate} minTickGap={28} />
            <YAxis tick={tick} tickFormatter={isMoney ? fmt.axis : undefined} width={52} />
            <Tooltip contentStyle={tipStyle} labelFormatter={longDate} formatter={(v, n) => Array.isArray(v) ? [`${show(v[0])} to ${show(v[1])}`, 'Likely range'] : [show(v), n]} />
            <Legend wrapperStyle={{ fontSize: 14 }} />
            <Area dataKey="band" name="Likely range" stroke="none" fill="var(--accent)" fillOpacity={0.16} />
            <Line dataKey="actual" name="Actual" stroke="var(--ink)" strokeWidth={2.5} dot={false} />
            <Line dataKey="predicted" name="Forecast" stroke="var(--accent)" strokeWidth={3} strokeDasharray="6 4" dot={false} />
            {last && <ReferenceLine x={last.date} stroke="var(--muted)" strokeDasharray="3 3" label={{ value: 'Today', fill: 'var(--muted)', fontSize: 13 }} />}
          </ComposedChart>
        </ResponsiveContainer></div>
      </Panel>
      <div className="grid two">
        <Panel title="How accurate is it?" sub={`Each method predicted the last ${f.holdout_periods} ${unit}s using only older data. Lower error is better.`}>
          <TableWrap><table><thead><tr><th>Method</th><th className="r">Accuracy</th><th></th></tr></thead>
            <tbody>{arr(f.backtest).map(b => <tr key={b.id}><td>{b.name}</td><td className="r">{b.accuracy.toFixed(0)}%</td><td>{b.id === f.model.id && <Badge tone="good">Used</Badge>}</td></tr>)}</tbody></table></TableWrap>
        </Panel>
        <Panel title="Day by day">
          <TableWrap><table><thead><tr><th>Date</th><th className="r">Expected</th><th className="r">Range</th></tr></thead>
            <tbody>{arr(f.forecast).slice(0, 14).map(p => <tr key={p.date}><td>{longDate(p.date)}</td><td className="r">{show(p.value)}</td><td className="r muted">{show(p.lower)} – {show(p.upper)}</td></tr>)}</tbody></table></TableWrap>
        </Panel>
      </div>
      <Note kind="info">A forecast is a planning guide, not a promise. It assumes the future behaves like the past. Festivals, price changes or stock-outs can move real sales away from it.</Note>
    </>
  );
}

// ───────────────────────── Signals ─────────────────────────
export function Signals() {
  const { st, period, go, refresh } = useApp();
  const toast = useToast();
  const { data, error, loading, reload } = useApi('/signals?period=' + period, [st?.dataset?.id, st?.dataset?.rows]);
  const [sev, setSev] = useState('all');
  async function addAction(a) { try { await api('/actions', { method: 'POST', body: { ...a, source: 'signal' } }); toast('Added to your Actions'); refresh(); } catch (e) { toast(e.message, 'bad'); } }
  if (loading) return <Loading />;
  if (error) return <><PageHead title="Signals" /><ErrorLine error={error} retry={reload} /></>;
  const list = arr(data?.signals).filter(s => sev === 'all' || s.severity === sev);
  const sm = data?.summary || {};
  return (
    <>
      <PageHead title="Signals" sub="Early warnings found by watching your sales, stock and margins."><PeriodPicker /></PageHead>
      <div className="stats">
        <Stat label="Total" value={sm.total || 0} /><Stat label="High priority" value={sm.high || 0} tone={sm.high ? 'bad' : ''} /><Stat label="Medium" value={sm.medium || 0} /><Stat label="Low" value={sm.low || 0} />
      </div>
      <Seg label="Severity" value={sev} onChange={setSev} options={[{ value: 'all', label: 'All' }, { value: 'high', label: 'High' }, { value: 'medium', label: 'Medium' }, { value: 'low', label: 'Low' }]} />
      {list.length ? (
        <ul className="feed big">{list.map(s => (
          <li key={s.id} className={'feed-item ' + s.tone}>
            <div><div className="row tight"><Badge tone={s.severity === 'high' ? 'bad' : s.severity === 'medium' ? 'warn' : 'neutral'}>{s.type}</Badge>{s.date && <span className="muted small">{longDate(s.date)}</span>}</div>
              <strong>{s.title}</strong><p>{s.detail}</p>
              <div className="row">{s.action && <button className="btn small" onClick={() => addAction(s.action)}><Icon n="plus" size={15} />Add to my actions</button>}{s.page && <button className="btn small ghost" onClick={() => go(s.page)}>Open</button>}</div></div>
          </li>))}</ul>
      ) : <Empty title="No signals here" text="Everything looks normal for this view." icon="check" />}
    </>
  );
}

// ───────────────────────── Scenarios ─────────────────────────
function Slider({ label, value, onChange, min, max, step = 1, unit = '%', hint }) {
  return (
    <div className="slider">
      <div className="slider-top"><label htmlFor={'s-' + label}>{label}</label><strong>{value > 0 ? '+' : ''}{value}{unit}</strong></div>
      <input id={'s-' + label} type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(Number(e.target.value))} />
      {hint && <small className="muted">{hint}</small>}
    </div>
  );
}
export function ScenarioResult({ res, fmt, name, setName, save }) {
  return (
    <Panel title="What could happen" sub={`Compared with ${res.baseline_label}`}>
              <p className="verdict">{res.verdict}</p>
              <TableWrap><table><thead><tr><th></th><th className="r">Now</th><th className="r">With your idea</th><th className="r">Change</th></tr></thead>
                <tbody>{arr(res.rows).map(r => <tr key={r.label}><td><strong>{r.label}</strong></td><td className="r">{r.money ? fmt.money(r.baseline) : fmt.num(r.baseline)}</td><td className="r">{r.money ? fmt.money(r.scenario) : fmt.num(r.scenario)}</td>
                  <td className={'r ' + (r.delta >= 0 ? 'pos' : 'neg')}>{r.change === null ? '—' : fmt.pct(r.change)}</td></tr>)}</tbody></table></TableWrap>
              <h3 className="mt">Which price works best?</h3>
              <div className="chart"><ResponsiveContainer width="100%" height={240}><LineChart data={res.curve} margin={{ left: 0, right: 8 }}>
                <CartesianGrid stroke="var(--line)" vertical={false} /><XAxis dataKey="price_change" tick={tick} tickFormatter={v => (v > 0 ? '+' : '') + v + '%'} /><YAxis tick={tick} tickFormatter={fmt.axis} width={52} />
                <Tooltip contentStyle={tipStyle} formatter={v => fmt.money(v, false)} labelFormatter={v => `Price ${v > 0 ? '+' : ''}${v}%`} />
                <Line dataKey={res.curve?.[0]?.profit === null ? 'revenue' : 'profit'} name={res.curve?.[0]?.profit === null ? 'Sales' : 'Profit'} stroke="var(--accent)" strokeWidth={3} dot />
                <ReferenceLine x={res.best_price_change} stroke="var(--good)" strokeDasharray="4 4" /></LineChart></ResponsiveContainer></div>
              <p className="muted small">Best price change on this curve: {res.best_price_change > 0 ? '+' : ''}{res.best_price_change}%. Sensitivity used: {res.elasticity}.</p>
              {arr(res.notes).map((n, i) => <p key={i} className="muted small">ⓘ {n}</p>)}
              <div className="row"><input className="grow" placeholder="Name this scenario" value={name} onChange={e => setName(e.target.value)} aria-label="Scenario name" /><button className="btn" onClick={save}>Save scenario</button></div>
            </Panel>
  );
}

export function Scenarios() {
  const { st, fmt } = useApp();
  const toast = useToast();
  const [inp, setInp] = useState({ price_change: 5, demand_change: 0, cost_change: 0, discount: 0, extra_spend: 0 });
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [name, setName] = useState('');
  const d = useDebounced(inp, 300);
  const saved = useApi('/scenarios');
  useEffect(() => {
    let live = true;
    api('/scenario', { method: 'POST', body: d }).then(r => { if (live) { setRes(r); setErr(null); } }).catch(e => { if (live) setErr(e); });
    return () => { live = false; };
  }, [d, st?.dataset?.id]);
  const set = k => v => setInp(x => ({ ...x, [k]: v }));
  async function save() {
    try { await api('/scenarios', { method: 'POST', body: { name: name || 'My scenario', inputs: inp, result: res } }); toast('Scenario saved'); setName(''); saved.reload(); } catch (e) { toast(e.message, 'bad'); }
  }
  async function del(id) { try { await api('/scenarios/' + id, { method: 'DELETE' }); saved.reload(); } catch (e) { toast(e.message, 'bad'); } }
  return (
    <>
      <PageHead title="What if…?" sub="Try a decision on paper before you make it. Move the sliders and see the effect on sales and profit." />
      <div className="grid two wide-left">
        <Panel title="Your idea">
          <Slider label="Change prices" value={inp.price_change} onChange={set('price_change')} min={-30} max={30} />
          <Slider label="Give a discount" value={inp.discount} onChange={set('discount')} min={0} max={40} hint="Applied on top of the price change" />
          <Slider label="Customers buying more or less" value={inp.demand_change} onChange={set('demand_change')} min={-40} max={60} hint="From marketing, season or competition" />
          <Slider label="Cost of goods" value={inp.cost_change} onChange={set('cost_change')} min={-30} max={40} hint="If your supplier changes prices" />
          <Field label="Extra spending (advertising etc.)"><input type="number" min="0" step="any" inputMode="decimal" value={inp.extra_spend || ''} placeholder="0" onChange={e => set('extra_spend')(Number(e.target.value) || 0)} /></Field>
          <Field label="Customer price sensitivity (optional)" hint="Leave empty to let DataPilot estimate it. −1 means a 10% price rise loses about 10% of buyers."><input type="number" step="0.1" max="0" min="-5" placeholder="Auto" onChange={e => setInp(x => ({ ...x, elasticity: e.target.value === '' ? null : Number(e.target.value) }))} /></Field>
        </Panel>
        <div className="stack">
          {err && <ErrorLine error={err} />}
          {res ? (
            <ScenarioResult res={res} fmt={fmt} name={name} setName={setName} save={save} />
          ) : !err && <Loading text="Calculating…" />}
          {arr(saved.data?.scenarios).length > 0 && (
            <Panel title="Saved scenarios"><ul className="dslist">{saved.data.scenarios.map(s => <li key={s.id}><div><strong>{s.name}</strong><p className="muted small">Price {s.inputs.price_change}% · demand {s.inputs.demand_change}% · discount {s.inputs.discount}% · {s.result?.verdict}</p></div>
              <div className="row"><button className="btn small" onClick={() => setInp({ price_change: 0, demand_change: 0, cost_change: 0, discount: 0, extra_spend: 0, ...s.inputs })}>Load</button><button className="btn small ghost" onClick={() => del(s.id)} aria-label="Delete"><Icon n="trash" size={16} /></button></div></li>)}</ul></Panel>
          )}
        </div>
      </div>
    </>
  );
}

// ───────────────────────── Actions ─────────────────────────
const PRI = { high: 'bad', medium: 'warn', low: 'neutral' };
export function Actions() {
  const { refresh } = useApp();
  const toast = useToast();
  const [filter, setFilter] = useState('pending');
  const { data, error, loading, reload } = useApi('/actions?status=all');
  const [form, setForm] = useState({ title: '', description: '', priority: 'medium' });
  const [open, setOpen] = useState(false);
  const counts = data?.counts || {};
  async function set(a, status) {
    try { await api(`/actions/${a.id}`, { method: 'PATCH', body: { status } }); toast(status === 'approved' ? 'Approved' : status === 'rejected' ? 'Rejected' : status === 'done' ? 'Marked as done' : 'Moved back to review'); reload(); refresh(); } catch (e) { toast(e.message, 'bad'); }
  }
  async function del(a) { if (!window.confirm('Delete this action?')) return; try { await api('/actions/' + a.id, { method: 'DELETE' }); reload(); refresh(); } catch (e) { toast(e.message, 'bad'); } }
  async function create(e) {
    e.preventDefault();
    try { await api('/actions', { method: 'POST', body: form }); setForm({ title: '', description: '', priority: 'medium' }); setOpen(false); toast('Action added'); reload(); refresh(); } catch (er) { toast(er.message, 'bad'); }
  }
  const list = arr(data?.actions).filter(a => filter === 'all' || a.status === filter);
  const tabs = [['pending', 'To review'], ['approved', 'Approved'], ['done', 'Done'], ['rejected', 'Rejected'], ['all', 'All']];
  return (
    <>
      <PageHead title="Actions" sub="DataPilot suggests, you decide. Nothing happens until you approve it."><button className="btn primary" onClick={() => setOpen(!open)}><Icon n="plus" size={17} />New action</button></PageHead>
      {open && <Panel title="Add your own action"><form onSubmit={create} className="stack">
        <Field label="What needs to be done?"><input required value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} placeholder="e.g. Call the rice supplier" /></Field>
        <Field label="Details (optional)"><textarea rows={2} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></Field>
        <Seg label="Priority" value={form.priority} onChange={v => setForm({ ...form, priority: v })} options={[{ value: 'high', label: 'High' }, { value: 'medium', label: 'Medium' }, { value: 'low', label: 'Low' }]} />
        <div className="row"><button className="btn primary">Add action</button><button type="button" className="btn ghost" onClick={() => setOpen(false)}>Cancel</button></div></form></Panel>}
      <div className="tabs" role="tablist">{tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={filter === k} className={filter === k ? 'on' : ''} onClick={() => setFilter(k)}>{l}<span className="count">{counts[k] ?? 0}</span></button>)}</div>
      {loading && !data ? <Loading /> : error ? <ErrorLine error={error} retry={reload} /> : list.length ? (
        <ul className="actions">{list.map(a => (
          <li key={a.id} className={'action ' + a.status}>
            <div className="action-main">
              <div className="row tight"><Badge tone={PRI[a.priority]}>{a.priority} priority</Badge><Badge tone="neutral">{a.source === 'agent' ? 'AI investigation' : a.source === 'automation' ? 'Automation' : a.source === 'manual' ? 'Added by you' : a.source}</Badge><span className="muted small">{timeAgo(a.created_at)}</span></div>
              <h3>{a.title}</h3>{a.description && <p>{a.description}</p>}{a.impact && <p className="impact">Why it matters: {a.impact}</p>}
            </div>
            <div className="action-btns">
              {a.status === 'pending' && <><button className="btn primary" onClick={() => set(a, 'approved')}><Icon n="check" size={17} />Approve</button><button className="btn" onClick={() => set(a, 'rejected')}>Reject</button></>}
              {a.status === 'approved' && <button className="btn primary" onClick={() => set(a, 'done')}><Icon n="check" size={17} />Mark done</button>}
              {(a.status === 'rejected' || a.status === 'done') && <button className="btn" onClick={() => set(a, 'pending')}>Reopen</button>}
              <button className="btn ghost icon" onClick={() => del(a)} aria-label="Delete action"><Icon n="trash" size={17} /></button>
            </div>
          </li>))}</ul>
      ) : <Empty title={filter === 'pending' ? 'Nothing to review' : 'Nothing here'} text="Run the AI investigation, turn on an automation, or add an action from Insights." icon="check" />}
    </>
  );
}

// ───────────────────────── Automations ─────────────────────────
export function Automations() {
  const { refresh } = useApp();
  const toast = useToast();
  const { data, error, loading, reload } = useApi('/automations');
  const [msg, setMsg] = useState({});
  const [busy, setBusy] = useState(null);
  const [showNew, setShowNew] = useState(false);
  const blank = { name: '', metric: 'sales', condition: 'drops_by_pct', value: 10, window_days: 7, schedule: 'daily' };
  const [nf, setNf] = useState(blank);
  async function patch(a, body) { try { await api('/automations/' + a.id, { method: 'POST', body }); reload(); } catch (e) { toast(e.message, 'bad'); } }
  async function run(a) {
    setBusy(a.id);
    try { const r = await api(`/automations/${a.id}/run`, { method: 'POST' }); setMsg(m => ({ ...m, [a.id]: r })); reload(); refresh(); if (r.created?.length) toast(`${r.created.length} new action${r.created.length > 1 ? 's' : ''} added`); }
    catch (e) { toast(e.message, 'bad'); } finally { setBusy(null); }
  }
  async function create(e) {
    e.preventDefault();
    try { await api('/automations', { method: 'POST', body: nf }); setShowNew(false); setNf(blank); toast('Alert created and turned on'); reload(); } catch (er) { toast(er.message, 'bad'); }
  }
  async function del(a) { if (!window.confirm('Delete this alert?')) return; try { await api('/automations/' + a.id, { method: 'DELETE' }); reload(); } catch (e) { toast(e.message, 'bad'); } }
  if (loading && !data) return <Loading />;
  if (error) return <><PageHead title="Automations" /><ErrorLine error={error} retry={reload} /></>;
  const list = arr(data?.automations);
  return (
    <>
      <PageHead title="Automations" sub="Let DataPilot watch your business for you. It only creates suggestions in Actions. You approve everything."><button className="btn primary" onClick={() => setShowNew(!showNew)}><Icon n="plus" size={17} />Custom alert</button></PageHead>
      <Note kind="info">Automations run while the DataPilot server is running. “Whenever I upload data” rules run right after each upload. Daily and weekly rules run in the background.</Note>
      {showNew && (
        <Panel title="Create your own alert" sub="Example: tell me when sales drop by 10% compared with the week before."><form onSubmit={create} className="formgrid">
          <Field label="Name"><input required value={nf.name} onChange={e => setNf({ ...nf, name: e.target.value })} placeholder="e.g. Weekly sales dip" /></Field>
          <Field label="Watch"><select value={nf.metric} onChange={e => setNf({ ...nf, metric: e.target.value })}>{Object.entries(data?.custom?.metrics || {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Alert when it"><select value={nf.condition} onChange={e => setNf({ ...nf, condition: e.target.value })}>{Object.entries(data?.custom?.conditions || {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Limit"><input type="number" step="any" required value={nf.value} onChange={e => setNf({ ...nf, value: e.target.value })} /></Field>
          <Field label="Over the last (days)"><input type="number" min="1" max="90" value={nf.window_days} onChange={e => setNf({ ...nf, window_days: e.target.value })} /></Field>
          <Field label="Check"><select value={nf.schedule} onChange={e => setNf({ ...nf, schedule: e.target.value })}>{Object.entries(data?.schedules || {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <div className="formgrid-end"><button className="btn primary">Create alert</button><button type="button" className="btn ghost" onClick={() => setShowNew(false)}>Cancel</button></div></form></Panel>
      )}
      <div className="grid auto">
        {list.map(a => (
          <article key={a.id} className={'auto' + (a.enabled ? ' on' : '')}>
            <div className="auto-top">
              <div><h3>{a.name}</h3><p className="muted">{a.description}</p></div>
              <button className={'switch' + (a.enabled ? ' on' : '')} role="switch" aria-checked={a.enabled} aria-label={`${a.name} ${a.enabled ? 'on' : 'off'}`} onClick={() => patch(a, { enabled: !a.enabled })}><i /></button>
            </div>
            <div className="auto-fields">
              <Select label="Runs" value={a.schedule} onChange={v => patch(a, { schedule: v })} options={Object.entries(data?.schedules || {}).map(([k, v]) => ({ value: k, label: v }))} />
              {arr(a.fields).map(f => <label key={f.key} className="field inline"><span>{f.label}</span><input type="number" min={f.min} max={f.max} defaultValue={a.params?.[f.key]} onBlur={e => e.target.value !== String(a.params?.[f.key]) && patch(a, { params: { [f.key]: e.target.value } })} /></label>)}
            </div>
            <div className="auto-foot">
              <button className="btn small" disabled={busy === a.id} onClick={() => run(a)}><Icon n="play" size={14} />{busy === a.id ? 'Running…' : 'Run now'}</button>
              {a.is_custom && <button className="btn small ghost" onClick={() => del(a)} aria-label="Delete"><Icon n="trash" size={16} /></button>}
              <span className="muted small">{a.last_run_at ? `Last run ${timeAgo(a.last_run_at)}` : 'Never run'}</span>
            </div>
            {(msg[a.id] || a.last_message) && <p className={'auto-msg' + (msg[a.id] && msg[a.id].status === 'failed' ? ' bad' : '')}>{msg[a.id]?.message || a.last_message}</p>}
            {msg[a.id]?.report && <p className="auto-report">{msg[a.id].report}</p>}
          </article>
        ))}
      </div>
      <Panel title="Recent activity" sub="Every automation run is recorded here.">
        {arr(data?.runs).length ? <TableWrap><table><thead><tr><th>When</th><th>Automation</th><th>Result</th><th className="r">New actions</th></tr></thead>
          <tbody>{data.runs.map(r => <tr key={r.id}><td>{timeAgo(r.ran_at)}</td><td>{r.name || '—'} <span className="muted small">({r.trigger})</span></td><td>{r.message}</td><td className="r">{r.created_count}</td></tr>)}</tbody></table></TableWrap> : <p className="muted">Nothing has run yet. Press “Run now” on any automation.</p>}
      </Panel>
    </>
  );
}
