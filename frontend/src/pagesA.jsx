import React, { useEffect, useRef, useState } from 'react';
import { Area, AreaChart, Bar as RBar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api, arr, shortDate, useApi, useApp } from './api.js';
import { Badge, Bar, Empty, Field, Icon, Loading, Note, PageHead, Panel, Select, Seg, Stat, TableWrap, download, useToast } from './ui.jsx';

const tick = { fontSize: 13, fill: 'var(--muted)' };
const tipStyle = { background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 10, fontSize: 14, color: 'var(--ink)' };

export function ErrorLine({ error, retry }) {
  if (!error) return null;
  return <Note kind={error.status === 409 ? 'info' : 'bad'}>{error.message}{retry && <> <button className="link" onClick={retry}>Try again</button></>}</Note>;
}

export function PeriodPicker() {
  const { st, period, setPeriod } = useApp();
  return <Select label="Period" value={period} onChange={setPeriod} options={arr(st?.periods).map(p => ({ value: p.key, label: p.label }))} />;
}

// ───────────────────────── Home ─────────────────────────
export function Home() {
  const { fmt, period, go, profile, st, refresh } = useApp();
  const toast = useToast();
  const { data: d, error, loading, reload } = useApi('/dashboard?period=' + period, [st?.dataset?.id]);
  async function addAction(a) {
    try { await api('/actions', { method: 'POST', body: { ...a, source: 'insight' } }); toast('Added to your Actions'); refresh(); }
    catch (e) { toast(e.message, 'bad'); }
  }
  if (loading) return <Loading />;
  if (error) return <ErrorLine error={error} retry={reload} />;
  if (!d) return <Empty title="Nothing to show yet" text="DataPilot did not receive any numbers. Check that the server is running, then try again." icon="info"><button className="btn primary" onClick={reload}>Try again</button></Empty>;
  const trend = arr(d.trend?.current).map((p, i) => ({ date: p.date, now: p.value, before: d.trend?.previous?.[i]?.value ?? null }));
  const name = profile?.owner_name ? `, ${profile.owner_name.split(' ')[0]}` : '';
  return (
    <>
      <PageHead title={`Here is how your business is doing${name}`} sub={`${d.period?.label || ''}${d.period?.text ? ' · ' + d.period.text : ''}`}><PeriodPicker /></PageHead>
      {d.dataset?.is_sample && <Note kind="info">You are looking at sample data. <button className="link" onClick={() => go('data')}>Add your own sales</button> to see your real numbers.</Note>}
      <Panel className="hero">
        {arr(d.headline).map((l, i) => <p key={i} className={i === 0 ? 'hero-line' : 'hero-sub'}>{l}</p>)}
      </Panel>
      <div className="stats">
        {arr(d.kpis).map(k => (
          <Stat key={k.key} label={k.label} value={k.display} delta={k.change} sub={k.sub || (k.change === null || k.change === undefined ? (d.period?.has_prev ? '' : 'no earlier period to compare') : 'vs previous')}
            tone={k.tone === 'missing' ? 'dim' : ''} onClick={k.missing ? () => go('settings') : undefined} />
        ))}
      </div>
      <div className="grid two">
        <Panel title="Sales over time" sub={d.trend?.previous ? 'Solid line is now, dashed line is the previous period.' : 'Sales for the selected period.'}>
          {trend.length ? (
            <div className="chart"><ResponsiveContainer width="100%" height={300}>
              <AreaChart data={trend} margin={{ left: 0, right: 8, top: 8 }}>
                <defs><linearGradient id="g1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--accent)" stopOpacity=".28" /><stop offset="1" stopColor="var(--accent)" stopOpacity="0" /></linearGradient></defs>
                <CartesianGrid stroke="var(--line)" vertical={false} />
                <XAxis dataKey="date" tick={tick} tickFormatter={shortDate} minTickGap={28} />
                <YAxis tick={tick} tickFormatter={fmt.axis} width={52} />
                <Tooltip contentStyle={tipStyle} formatter={v => fmt.money(v, false)} labelFormatter={shortDate} />
                {d.trend?.previous && <Area type="monotone" dataKey="before" name="Previous" stroke="var(--muted)" strokeDasharray="5 4" fill="none" strokeWidth={2} dot={false} />}
                <Area type="monotone" dataKey="now" name="Now" stroke="var(--accent)" fill="url(#g1)" strokeWidth={3} dot={false} />
              </AreaChart>
            </ResponsiveContainer></div>
          ) : <Empty title="No dates in your data" text="Add a date column to see how sales move over time." icon="trend"><button className="btn" onClick={() => go('data')}>Open column mapping</button></Empty>}
        </Panel>
        <Panel title="What needs your attention" sub="Plain-English findings from your data.">
          <ul className="feed">
            {arr(d.insights).slice(0, 4).map(i => (
              <li key={i.id} className={'feed-item ' + i.tone}>
                <div><strong>{i.title}</strong><p>{i.detail}</p>
                  <div className="row">{i.action && <button className="btn small" onClick={() => addAction(i.action)}><Icon n="plus" size={15} />Add to my actions</button>}{i.page && <button className="btn small ghost" onClick={() => go(i.page)}>Open</button>}</div>
                </div>
              </li>
            ))}
            {!arr(d.insights).length && <li className="muted">Nothing needs attention right now.</li>}
          </ul>
        </Panel>
      </div>
      <div className="grid two">
        <Panel title="Best categories" sub="Share of sales">
          <RankList rows={arr(d.categories)} fmt={fmt} empty="No category column in your data." />
        </Panel>
        <Panel title="Best products" sub="Share of sales">
          <RankList rows={arr(d.products)} fmt={fmt} empty="No product column in your data." />
        </Panel>
      </div>
      {arr(d.setup).length > 0 && (
        <Panel title="Get more from DataPilot" sub="A few quick additions unlock more features.">
          <div className="grid three">{d.setup.map(t => <div className="tip" key={t.id}><strong>{t.title}</strong><p>{t.text}</p><button className="btn small" onClick={() => go(t.page)}>{t.cta}</button></div>)}</div>
        </Panel>
      )}
      <Panel title="Signals" sub={`${d.signal_counts?.total || 0} found, ${d.signal_counts?.high || 0} high priority`} actions={<button className="btn small ghost" onClick={() => go('signals')}>See all</button>}>
        <ul className="feed compact">{arr(d.signals).slice(0, 3).map(s => <li key={s.id} className={'feed-item ' + s.tone}><div><strong>{s.title}</strong><p>{s.detail}</p></div></li>)}
          {!arr(d.signals).length && <li className="muted">No signals. Everything is within normal range.</li>}</ul>
      </Panel>
    </>
  );
}

function RankList({ rows, fmt, empty }) {
  if (!rows.length) return <p className="muted">{empty}</p>;
  const max = Math.max(...rows.map(r => r.revenue || 0), 1);
  return (
    <ol className="rank">
      {rows.map(r => (
        <li key={r.name}>
          <div className="rank-top"><span className="rank-name">{r.name}</span><strong>{fmt.money(r.revenue)}</strong></div>
          <Bar value={r.revenue} max={max} />
          <div className="rank-foot muted">{fmt.pct(r.share, false)} of sales{r.change !== null && r.change !== undefined && <> · <span className={r.change >= 0 ? 'pos' : 'neg'}>{fmt.pct(r.change)}</span> vs before</>}</div>
        </li>
      ))}
    </ol>
  );
}

// ───────────────────────── Data Studio ─────────────────────────
export function DataStudio() {
  const { st, refresh, go } = useApp();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState('replace');
  const [result, setResult] = useState(null);
  const [drag, setDrag] = useState(false);
  const input = useRef(null);
  const has = st?.has_data;
  const ds = st?.dataset;

  async function send(files) {
    files = Array.from(files || []);
    if (!files.length) return;
    setBusy(true); setResult(null);
    try {
      const form = new FormData();
      files.forEach(f => form.append('files', f));
      const r = await api(`/upload?mode=${has ? mode : 'replace'}`, { method: 'POST', form });
      setResult(r);
      toast(`${r.files.length} file${r.files.length > 1 ? 's' : ''} loaded`);
      await refresh();
    } catch (e) { toast(e.message, 'bad'); setResult({ error: e.message }); }
    finally { setBusy(false); if (input.current) input.current.value = ''; }
  }
  async function useSample() {
    setBusy(true);
    try { await api('/sample', { method: 'POST' }); toast('Sample shop loaded'); await refresh(); } catch (e) { toast(e.message, 'bad'); } finally { setBusy(false); }
  }
  return (
    <>
      <PageHead title="Your data" sub="Add your sales from a CSV or Excel file. DataPilot works out which column is which, and you can correct it." />
      <Panel title={has ? 'Add or replace data' : 'Start with your sales file'} sub="CSV or Excel (.xlsx). You can select several files at once.">
        <div className={'drop' + (drag ? ' on' : '')} onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
          onDrop={e => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}>
          <Icon n="upload" size={34} />
          <h3>{busy ? 'Reading your files…' : 'Drop files here'}</h3>
          <p className="muted">Sales, bills, orders, stock, expenses. Any column names are fine.</p>
          {has && <Seg label="What to do with the new files" value={mode} onChange={setMode} options={[{ value: 'replace', label: 'Replace current data' }, { value: 'append', label: 'Add to current data' }]} />}
          <div className="row center">
            <button className="btn primary big" disabled={busy} onClick={() => input.current?.click()}>Choose files</button>
            {!has && <button className="btn big" disabled={busy} onClick={useSample}>Try a sample shop</button>}
            <a className="btn big ghost" href="/api/template.csv">Download a template</a>
          </div>
          <input ref={input} type="file" hidden multiple accept=".csv,.tsv,.txt,.xlsx,.xlsm" onChange={e => send(e.target.files)} />
        </div>
        {result?.error && <Note kind="bad">{result.error}</Note>}
        {result && !result.error && (
          <div className="stack">
            <Note kind="ok">Loaded {result.files.join(', ')}. Data quality {result.quality}/100.</Note>
            {result.needs_mapping && <Note kind="warn">No sales amount column was found. Choose it in <strong>Column mapping</strong> below.</Note>}
            {arr(result.warnings).map((w, i) => <Note key={i} kind="warn">{w}</Note>)}
            {arr(result.notes).map((w, i) => <Note key={i} kind="info">{w}</Note>)}
            {arr(result.automations_run).filter(a => a.created).map((a, i) => <Note key={i} kind="info">Automation: {a.message}</Note>)}
          </div>
        )}
      </Panel>
      {has && <>
        <Datasets />
        <Mapping />
        <Preview />
        <QuickEntry />
      </>}
    </>
  );
}

function Datasets() {
  const { st, refresh } = useApp();
  const toast = useToast();
  const list = arr(st?.datasets);
  async function activate(id) { try { await api(`/datasets/${id}/activate`, { method: 'POST' }); await refresh(); } catch (e) { toast(e.message, 'bad'); } }
  async function remove(d) {
    if (!window.confirm(`Delete “${d.name}”? Your original files in this dataset will be removed.`)) return;
    try { await api(`/datasets/${d.id}`, { method: 'DELETE' }); toast('Dataset deleted'); await refresh(); } catch (e) { toast(e.message, 'bad'); }
  }
  return (
    <Panel title="Datasets" sub="Switch between files you uploaded earlier. Everything in DataPilot follows the active one."
      actions={<a className="btn small" href="/api/export/cleaned.csv"><Icon n="download" size={15} />Download cleaned data</a>}>
      <ul className="dslist">
        {list.map(d => (
          <li key={d.id} className={d.id === st.dataset?.id ? 'active' : ''}>
            <div><strong>{d.name}</strong> {d.is_sample && <Badge tone="info">Sample</Badge>} {d.id === st.dataset?.id && <Badge tone="good">Active</Badge>}
              <p className="muted small">{(d.rows || 0).toLocaleString()} rows · {arr(d.files).join(', ')}</p></div>
            <div className="row">{d.id !== st.dataset?.id && <button className="btn small" onClick={() => activate(d.id)}>Use this</button>}<button className="btn small ghost" onClick={() => remove(d)} aria-label={`Delete ${d.name}`}><Icon n="trash" size={16} /></button></div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function Mapping() {
  const { st, refresh } = useApp();
  const toast = useToast();
  const { data: m, error, loading, reload } = useApi('/mapping', [st?.dataset?.id, st?.dataset?.rows]);
  const [draft, setDraft] = useState({});
  const [opts, setOpts] = useState({});
  const [busy, setBusy] = useState(false);
  if (loading) return <Panel title="Column mapping"><Loading /></Panel>;
  if (error) return <Panel title="Column mapping"><ErrorLine error={error} retry={reload} /></Panel>;
  if (!m) return <Panel title="Column mapping"><Empty title="Could not load your columns" icon="info"><button className="btn" onClick={reload}>Try again</button></Empty></Panel>;
  const val = r => (r.role in draft ? draft[r.role] : (r.column || ''));
  const dateMode = opts.date_mode ?? m.date_mode;
  const dirty = Object.keys(draft).length > 0 || Object.keys(opts).length > 0;
  async function save() {
    setBusy(true);
    try {
      await api('/mapping', { method: 'POST', body: { mapping: draft, ...opts } });
      setDraft({}); setOpts({}); toast('Column mapping saved'); await refresh(); reload();
    } catch (e) { toast(e.message, 'bad'); } finally { setBusy(false); }
  }
  const tone = { high: 'good', medium: 'neutral', low: 'warn', 'you chose': 'info' };
  return (
    <Panel title="Column mapping" sub="Check that DataPilot understood your columns. Change any that look wrong, then save." actions={<Badge tone={m.quality.score >= 80 ? 'good' : m.quality.score >= 60 ? 'warn' : 'bad'}>Data quality {m.quality.score}/100</Badge>}>
      <div className="maprows">
        {arr(m.roles).map(r => (
          <div className="maprow" key={r.role}>
            <div><strong>{r.label}</strong><p className="muted small">{r.help}</p></div>
            <div className="row nowrap">
              <select aria-label={r.label} value={val(r)} onChange={e => setDraft({ ...draft, [r.role]: e.target.value })}>
                <option value="">— not in my data —</option>
                {arr(m.columns).map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              {r.confidence && val(r) === r.column && <Badge tone={tone[r.confidence] || 'neutral'}>{r.confidence === 'you chose' ? 'you chose' : r.confidence + ' match'}</Badge>}
            </div>
          </div>
        ))}
      </div>
      {(!arr(m.roles).find(r => r.role === 'date')?.column || dateMode !== 'column') && (
        <div className="subpanel">
          <h3>No date column?</h3>
          <p className="muted">Trends and forecasts need dates. If your file has none you can still compare products and groups, or create dates from row order (only do this if rows are in time order).</p>
          <Seg label="Date handling" value={dateMode} onChange={v => setOpts({ ...opts, date_mode: v })} options={[{ value: 'column', label: 'Use the date column' }, { value: 'none', label: 'No dates' }, { value: 'sequence', label: 'Create dates from row order' }]} />
          {dateMode === 'sequence' && <div className="grid two"><Field label="Rows per day"><input type="number" min="1" defaultValue={m.rows_per_period} onChange={e => setOpts({ ...opts, date_mode: 'sequence', rows_per_period: Number(e.target.value) || 1 })} /></Field>
            <Field label="First day"><input type="date" defaultValue={m.sequence_start} onChange={e => setOpts({ ...opts, date_mode: 'sequence', sequence_start: e.target.value })} /></Field></div>}
        </div>
      )}
      <label className="check"><input type="checkbox" checked={opts.drop_duplicates ?? m.drop_duplicates} onChange={e => setOpts({ ...opts, drop_duplicates: e.target.checked })} /> Remove exact duplicate rows</label>
      <div className="row"><button className="btn primary" disabled={!dirty || busy} onClick={save}>{busy ? 'Saving…' : 'Save mapping'}</button>{dirty && <button className="btn ghost" onClick={() => { setDraft({}); setOpts({}); }}>Undo changes</button>}</div>
      <h3 className="mt">Data checks</h3>
      <ul className="checks">{arr(m.quality.checks).map((c, i) => <li key={i} className={c.status}><Icon n={c.status === 'ok' ? 'check' : c.status === 'info' ? 'info' : 'alert'} size={18} /><div><strong>{c.label}</strong><span> {c.detail}</span></div></li>)}</ul>
      {arr(m.notes).map((n, i) => <p key={i} className="muted small">ⓘ {n}</p>)}
    </Panel>
  );
}

function Preview() {
  const { st } = useApp();
  const [q, setQ] = useState('');
  const [page, setPage] = useState(0);
  const size = 25;
  const { data, error, loading } = useApi(`/data?limit=${size}&offset=${page * size}&q=${encodeURIComponent(q)}`, [st?.dataset?.id, st?.dataset?.rows]);
  const pages = Math.max(1, Math.ceil((data?.total_rows || 0) / size));
  return (
    <Panel title="Your rows" sub="The data after cleaning. This is exactly what the analysis uses." actions={<input className="search" type="search" placeholder="Search product, category, customer…" value={q} onChange={e => { setQ(e.target.value); setPage(0); }} aria-label="Search rows" />}>
      {error && <ErrorLine error={error} />}
      {loading && !data ? <Loading /> : data && (
        <>
          <TableWrap><table><thead><tr>{arr(data.columns).map(c => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>{arr(data.rows).map((r, i) => <tr key={i}>{data.columns.map(c => <td key={c}>{String(r[c] ?? '')}</td>)}</tr>)}</tbody></table></TableWrap>
          <div className="pager"><span className="muted">{(data.total_rows || 0).toLocaleString()} rows</span>
            <div className="row"><button className="btn small" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page + 1} of {pages}</span><button className="btn small" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</button></div></div>
        </>
      )}
    </Panel>
  );
}

function QuickEntry() {
  const { refresh } = useApp();
  const toast = useToast();
  const blank = { date: new Date().toISOString().slice(0, 10), product: '', category: '', quantity: '1', unit_price: '', amount: '', cost: '', customer: '' };
  const [f, setF] = useState(blank);
  const [busy, setBusy] = useState(false);
  const set = k => e => setF({ ...f, [k]: e.target.value });
  async function save(e) {
    e.preventDefault(); setBusy(true);
    try { await api('/rows', { method: 'POST', body: { rows: [f] } }); toast('Sale added'); setF({ ...blank, date: f.date }); await refresh(); }
    catch (err) { toast(err.message, 'bad'); } finally { setBusy(false); }
  }
  return (
    <Panel title="Add a sale by hand" sub="No spreadsheet today? Type a sale here and it joins your data straight away.">
      <form onSubmit={save} className="formgrid">
        <Field label="Date"><input type="date" value={f.date} onChange={set('date')} required /></Field>
        <Field label="Product"><input value={f.product} onChange={set('product')} placeholder="e.g. Atta 5kg" /></Field>
        <Field label="Category"><input value={f.category} onChange={set('category')} placeholder="e.g. Grocery" /></Field>
        <Field label="Quantity"><input type="number" min="0" step="any" value={f.quantity} onChange={set('quantity')} inputMode="decimal" /></Field>
        <Field label="Price per unit"><input type="number" min="0" step="any" value={f.unit_price} onChange={set('unit_price')} inputMode="decimal" /></Field>
        <Field label="Total amount" hint="Leave empty to use quantity × price"><input type="number" min="0" step="any" value={f.amount} onChange={set('amount')} inputMode="decimal" /></Field>
        <Field label="Cost (optional)"><input type="number" min="0" step="any" value={f.cost} onChange={set('cost')} inputMode="decimal" /></Field>
        <Field label="Customer (optional)"><input value={f.customer} onChange={set('customer')} /></Field>
        <div className="formgrid-end"><button className="btn primary" disabled={busy}>{busy ? 'Adding…' : 'Add sale'}</button></div>
      </form>
    </Panel>
  );
}

// ───────────────────────── Insights ─────────────────────────
export function Insights() {
  const { go } = useApp();
  const [tab, setTab] = useState('findings');
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    const onTab = e => {
      if (e.detail === 'patterns' || e.detail === 'breakdown' || e.detail === 'findings') setTab(e.detail);
    };
    window.addEventListener('dp-insights-tab', onTab);
    return () => window.removeEventListener('dp-insights-tab', onTab);
  }, []);

  function openInsight(insight) {
    if (!insight?.page) return;
    // A number of insight cards intentionally point back to Insights.
    // Navigating to the same page used to look like a dead button.
    // Show the actual insight details instead, while preserving normal navigation for other pages.
    if (insight.page === 'insights') setSelected(insight);
    else go(insight.page);
  }

  return (
    <>
      <PageHead title="Insights" sub="What your data says about where you make money and where you lose it."><PeriodPicker /></PageHead>
      <Seg label="Insight views" value={tab} onChange={setTab} options={[{ value: 'findings', label: 'Findings' }, { value: 'breakdown', label: 'Breakdowns' }, { value: 'patterns', label: 'Patterns' }]} />
      {tab === 'findings' && <Findings onOpen={openInsight} />}
      {tab === 'breakdown' && <Breakdown />}
      {tab === 'patterns' && <Patterns />}
      {selected && <InsightDetails insight={selected} onClose={() => setSelected(null)} onBreakdown={() => { setSelected(null); setTab('breakdown'); }} />}
    </>
  );
}

function Findings({ onOpen }) {
  const { period, refresh, st } = useApp();
  const toast = useToast();
  const { data, error, loading, reload } = useApi('/insights?period=' + period, [st?.dataset?.id, st?.dataset?.rows]);
  async function addAction(a) { try { await api('/actions', { method: 'POST', body: { ...a, source: 'insight' } }); toast('Added to your Actions'); refresh(); } catch (e) { toast(e.message, 'bad'); } }
  if (loading) return <Loading />;
  if (error) return <ErrorLine error={error} retry={reload} />;
  const list = arr(data?.insights);
  return list.length ? (
    <ul className="feed big">{list.map(i => (
      <li key={i.id} className={'feed-item ' + i.tone}><div><strong>{i.title}</strong><p>{i.detail}</p>
        <div className="row">{i.action && <button className="btn small" onClick={() => addAction(i.action)}><Icon n="plus" size={15} />Add to my actions</button>}{i.page && <button className="btn small ghost" onClick={() => onOpen(i)}>View details</button>}</div></div></li>))}</ul>
  ) : <Empty title="No findings yet" text="Add more data to see insights." icon="insights" />;
}

function InsightDetails({ insight, onClose, onBreakdown }) {
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const canBreakdown = /^(fall_|rise_|concentration|loss_products|thin_margin|margin)/.test(String(insight?.id || ''));
  const canPatterns = insight?.id === 'weekday' || insight?.id === 'best_day';

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <section className="modal panel" role="dialog" aria-modal="true" aria-labelledby="insight-detail-title">
        <div className="modal-head"><div><span className="eyebrow">INSIGHT DETAILS</span><h2 id="insight-detail-title">{insight.title}</h2></div><button className="btn ghost icon" onClick={onClose} aria-label="Close"><Icon n="close" size={18} /></button></div>
        <p className="verdict">{insight.detail}</p>
        {insight.evidence && Object.keys(insight.evidence).length > 0 && <div className="subpanel"><strong>What DataPilot used</strong><p className="muted small">This finding is based on the calculations shown above and the evidence stored with this insight.</p><ul className="bullets">{Object.entries(insight.evidence).map(([k, v]) => <li key={k}><strong>{k.replaceAll('_', ' ')}:</strong> {String(v)}</li>)}</ul></div>}
        <div className="row">
          {canBreakdown && <button className="btn primary" onClick={onBreakdown}>Open breakdown</button>}
          {canPatterns && <button className="btn primary" onClick={() => { onClose(); window.dispatchEvent(new CustomEvent('dp-insights-tab', { detail: 'patterns' })); }}>Open patterns</button>}
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </section>
    </div>
  );
}

function Breakdown() {
  const { st, fmt, period } = useApp();
  const dims = arr(st?.dataset?.dims);
  const [dim, setDim] = useState(dims.includes('category') ? 'category' : dims[0] || 'product');
  const [metric, setMetric] = useState('revenue');
  const { data, error, loading } = useApi(`/explore?dim=${encodeURIComponent(dim)}&metric=${metric}&period=${period}`, [st?.dataset?.id]);
  const metrics = [{ value: 'revenue', label: 'Sales' }, { value: 'units', label: 'Items sold' }, { value: 'orders', label: 'Orders' }, { value: 'aov', label: 'Average bill' }];
  if (st?.dataset?.cost_mode) metrics.push({ value: 'profit', label: 'Profit' }, { value: 'margin', label: 'Margin %' });
  const rows = arr(data?.rows).slice(0, 15);
  const f = v => (data?.metric === 'units' || data?.metric === 'orders') ? fmt.num(v) : data?.metric === 'margin' ? fmt.pct(v, false) : fmt.money(v);
  if (!dims.length) return <Empty title="Nothing to break down" text="Your data has no category, product or other grouping columns." icon="insights" />;
  return (
    <Panel title="Compare groups" sub="Pick any column in your data to see how each group performs."
      actions={<><Select label="Group by" value={dim} onChange={setDim} options={dims.map(d => ({ value: d, label: d }))} /><Select label="Measure" value={metric} onChange={setMetric} options={metrics} /></>}>
      {error && <ErrorLine error={error} />}
      {loading && !data ? <Loading /> : rows.length > 0 && (
        <>
          <div className="chart"><ResponsiveContainer width="100%" height={Math.max(260, rows.length * 34)}>
            <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 16 }}>
              <CartesianGrid stroke="var(--line)" horizontal={false} />
              <XAxis type="number" tick={tick} tickFormatter={v => (data.metric === 'revenue' || data.metric === 'profit' || data.metric === 'aov') ? fmt.axis(v) : v} />
              <YAxis type="category" dataKey="name" tick={tick} width={110} />
              <Tooltip contentStyle={tipStyle} formatter={v => f(v)} />
              <RBar dataKey={data.metric} radius={[0, 6, 6, 0]}>{rows.map((r, i) => <Cell key={i} fill={(r[data.metric] ?? 0) < 0 ? 'var(--bad)' : 'var(--accent)'} />)}</RBar>
            </BarChart>
          </ResponsiveContainer></div>
          <TableWrap><table><thead><tr><th>{dim}</th><th className="r">Sales</th><th className="r">Share</th><th className="r">Orders</th><th className="r">Avg bill</th>{data.can_profit && <th className="r">Profit</th>}{data.can_profit && <th className="r">Margin</th>}<th className="r">Change</th><th>Class</th></tr></thead>
            <tbody>{rows.map(r => <tr key={r.name}><td><strong>{r.name}</strong></td><td className="r">{fmt.money(r.revenue)}</td><td className="r">{fmt.pct(r.share, false)}</td><td className="r">{fmt.num(r.orders)}</td><td className="r">{fmt.money(r.aov)}</td>
              {data.can_profit && <td className={'r ' + ((r.profit ?? 0) < 0 ? 'neg' : '')}>{fmt.money(r.profit)}</td>}{data.can_profit && <td className="r">{r.margin === null ? '—' : fmt.pct(r.margin, false)}</td>}
              <td className={'r ' + ((r.change ?? 0) < 0 ? 'neg' : 'pos')}>{r.change === null ? '—' : fmt.pct(r.change)}</td><td><Badge tone={r.abc === 'A' ? 'good' : r.abc === 'B' ? 'neutral' : 'warn'}>{r.abc}</Badge></td></tr>)}</tbody></table></TableWrap>
          <p className="muted small">Class A groups make up the first 80% of sales, B the next 15%, C the last 5%. {data.total_groups > 15 && `Showing 15 of ${data.total_groups}.`}</p>
        </>
      )}
    </Panel>
  );
}

function Patterns() {
  const { st, fmt } = useApp();
  const { data, error, loading } = useApi('/patterns', [st?.dataset?.id, st?.dataset?.rows]);
  if (loading) return <Loading />;
  if (error) return <ErrorLine error={error} />;
  if (!data?.available) return <Empty title="Patterns need dates" text={data?.reason || 'Add a date column to see which days and months are strongest.'} icon="trend" />;
  const best = [...arr(data.weekday)].sort((a, b) => b.avg_revenue - a.avg_revenue);
  return (
    <div className="grid two">
      <Panel title="Best days of the week" sub={best.length ? `${best[0].day} is strongest, ${best[best.length - 1].day} is weakest.` : ''}>
        <div className="chart"><ResponsiveContainer width="100%" height={280}><BarChart data={data.weekday}><CartesianGrid stroke="var(--line)" vertical={false} /><XAxis dataKey="day" tick={tick} /><YAxis tick={tick} tickFormatter={fmt.axis} width={52} /><Tooltip contentStyle={tipStyle} formatter={v => fmt.money(v, false)} />
          <RBar dataKey="avg_revenue" name="Average sales" radius={[6, 6, 0, 0]}>{arr(data.weekday).map((r, i) => <Cell key={i} fill={r.day === best[0]?.day ? 'var(--accent)' : 'var(--accent-soft)'} />)}</RBar></BarChart></ResponsiveContainer></div>
      </Panel>
      <Panel title="Month by month" sub={data.last_month_partial ? 'The latest month is not finished yet.' : ''}>
        <div className="chart"><ResponsiveContainer width="100%" height={280}><BarChart data={data.monthly}><CartesianGrid stroke="var(--line)" vertical={false} /><XAxis dataKey="month" tick={tick} minTickGap={16} /><YAxis tick={tick} tickFormatter={fmt.axis} width={52} /><Tooltip contentStyle={tipStyle} formatter={v => fmt.money(v, false)} />
          <RBar dataKey="revenue" name="Sales" fill="var(--accent)" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer></div>
      </Panel>
    </div>
  );
}

// ───────────────────────── Inventory ─────────────────────────
const STATUS = { out: ['bad', 'Out of stock'], critical: ['bad', 'Very low'], low: ['warn', 'Low'], watch: ['info', 'Watch'], dead: ['neutral', 'Not selling'], over: ['neutral', 'Too much'], ok: ['good', 'Healthy'] };
export function Inventory() {
  const { st, fmt, go, refresh } = useApp();
  const toast = useToast();
  const { data, error, loading, reload } = useApi('/inventory', [st?.dataset?.id, st?.dataset?.rows]);
  const [filter, setFilter] = useState('attention');
  async function reorder(i) {
    try { await api('/actions', { method: 'POST', body: { title: `Reorder ${i.product}`, description: `Stock ${fmt.num(i.stock)}, selling ${i.per_day}/day. Suggested order: ${i.reorder_qty} units.`, priority: i.status === 'low' ? 'medium' : 'high', source: 'inventory', dedupe_key: `stock:${i.product}` } }); toast('Added to your Actions'); refresh(); }
    catch (e) { toast(e.message, 'bad'); }
  }
  if (loading) return <Loading />;
  if (error) return <><PageHead title="Stock" /><ErrorLine error={error} retry={reload} /></>;
  if (!data?.available) return <><PageHead title="Stock" sub="Know what to reorder before you run out." /><Empty title="No stock data yet" text={data?.reason} icon="box"><button className="btn primary" onClick={() => go('data')}>Open Data Studio</button></Empty></>;
  const s = data.summary;
  const rows = arr(data.items).filter(i => filter === 'all' || (filter === 'attention' ? ['out', 'critical', 'low'].includes(i.status) : i.status === filter));
  return (
    <>
      <PageHead title="Stock" sub={`Based on the last 30 days of sales. Lead time ${data.settings.lead_time_days} days, safety stock ${data.settings.safety_days} days.`} />
      <div className="stats">
        <Stat label="Need action" value={s.needs_action} tone={s.needs_action ? 'bad' : 'good'} sub="out or running low" />
        <Stat label="Sales at risk" value={fmt.money(s.revenue_at_risk)} sub="before new stock arrives" />
        <Stat label="Not selling" value={s.dead} sub="stock with no sales in 30 days" />
        <Stat label="Products tracked" value={s.total} sub="with stock levels" />
      </div>
      <Panel title="Products" actions={<Seg label="Filter" value={filter} onChange={setFilter} options={[{ value: 'attention', label: 'Needs action' }, { value: 'watch', label: 'Watch' }, { value: 'dead', label: 'Not selling' }, { value: 'all', label: 'All' }]} />}>
        {rows.length ? (
          <TableWrap><table><thead><tr><th>Product</th><th>Status</th><th className="r">In stock</th><th className="r">Sold per day</th><th className="r">Days left</th><th className="r">Order</th><th></th></tr></thead>
            <tbody>{rows.map(i => <tr key={i.product}><td><strong>{i.product}</strong></td><td><Badge tone={STATUS[i.status][0]}>{STATUS[i.status][1]}</Badge></td><td className="r">{fmt.num(i.stock)}</td><td className="r">{i.per_day ?? '—'}</td>
              <td className="r">{i.days_left === null || i.days_left === undefined ? '—' : i.days_left.toFixed(1)}</td><td className="r">{i.reorder_qty ? i.reorder_qty.toLocaleString() : '—'}</td>
              <td className="r">{i.reorder_qty > 0 && ['out', 'critical', 'low', 'watch'].includes(i.status) && <button className="btn small" onClick={() => reorder(i)}>Add to actions</button>}</td></tr>)}</tbody></table></TableWrap>
        ) : <Empty title="Nothing here" text="No products match this filter." icon="check" />}
        <p className="muted small">Order quantity covers your supplier lead time, safety stock and 14 days of sales. Change these in Settings.</p>
      </Panel>
    </>
  );
}

// ───────────────────────── Customers ─────────────────────────
export function Customers() {
  const { st, fmt, go } = useApp();
  const { data, error, loading } = useApi('/customers?period=all', [st?.dataset?.id, st?.dataset?.rows]);
  if (loading) return <Loading />;
  if (error) return <ErrorLine error={error} />;
  if (!data?.available) return <><PageHead title="Customers" sub="Who buys from you and who is slipping away." /><Empty title="Customer analysis is not available" text={data?.reason} icon="users"><button className="btn" onClick={() => go('data')}>Open column mapping</button></Empty></>;
  const segDesc = { Champions: 'Buy often and recently', Loyal: 'Come back regularly', 'At risk': 'Used to buy, now quiet', New: 'Recent first purchase', 'One-time': 'Bought once, a while ago' };
  return (
    <>
      <PageHead title="Customers" sub="Who buys from you and who is slipping away." />
      <div className="stats">
        <Stat label="Customers" value={data.total.toLocaleString()} />
        <Stat label="Came back" value={fmt.pct(data.repeat_rate, false)} sub="bought more than once" />
        <Stat label="Average spend" value={fmt.money(data.avg_spend)} sub="per customer" />
        <Stat label="Top 10% bring" value={fmt.pct(data.top10_share, false)} sub="of all sales" />
      </div>
      <div className="grid two">
        <Panel title="Customer groups" sub="Based on how often and how recently they bought.">
          <ul className="seglist">{Object.entries(data.segments || {}).map(([k, v]) => <li key={k}><div><strong>{k}</strong><p className="muted small">{segDesc[k]}</p></div><span className="big-num">{v}</span></li>)}</ul>
        </Panel>
        <Panel title="Your best customers">
          <TableWrap><table><thead><tr><th>Customer</th><th className="r">Spent</th><th className="r">Orders</th><th>Last seen</th><th>Group</th></tr></thead>
            <tbody>{arr(data.top).map(c => <tr key={c.customer}><td><strong>{c.customer}</strong></td><td className="r">{fmt.money(c.revenue)}</td><td className="r">{c.orders}</td><td>{c.last_seen || '—'}</td><td>{c.segment && <Badge tone={c.segment === 'At risk' ? 'warn' : c.segment === 'Champions' ? 'good' : 'neutral'}>{c.segment}</Badge>}</td></tr>)}</tbody></table></TableWrap>
        </Panel>
      </div>
    </>
  );
}
