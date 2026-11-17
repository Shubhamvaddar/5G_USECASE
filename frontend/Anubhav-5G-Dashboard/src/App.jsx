import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import { fetchDashboardData, getInitialApiBase, isRecordStale, pollIntervalMs, staleAfterMs } from './services/api';

const NAV = [
  ['overview', 'Overview', '◫'], ['live', 'Live Monitoring', '⌁'],
  ['twin', 'Digital Twin', '◇'], ['analytics', 'Analytics', '▥'], ['network', 'Network Status', '⌘'],
];
const VARIABLES = {
  powerW: { label: 'Power', unit: 'W', color: '#1678e8' },
  voltageV: { label: 'Voltage', unit: 'V', color: '#8b5cf6' },
  currentA: { label: 'Current', unit: 'A', color: '#11a579' },
  temperatureC: { label: 'Temperature', unit: '°C', color: '#e08b32' },
  lightLux: { label: 'Light intensity', unit: 'lx', color: '#d6a51a' },
};
const fmt = (value, digits = 1) => Number.isFinite(value) ? new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(value) : '—';
const validValue = value => Number.isFinite(value) ? value : null;
const parseUtc = ts => {
  if (!ts) return NaN;
  if (typeof ts === 'string' && !ts.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(ts)) {
    return Date.parse(ts + 'Z');
  }
  return Date.parse(ts);
};
const validTimestamp = record => record?.timestamp && Number.isFinite(parseUtc(record.timestamp));
const sortRecords = rows => [...rows].filter(validTimestamp).sort((a,b) => parseUtc(a.timestamp)-parseUtc(b.timestamp));
const latestOf = rows => sortRecords(rows).filter(record => Object.values(record.measurements || {}).some(Number.isFinite)).at(-1) || null;
const valueText = (record, key) => fmt(record?.measurements?.[key], key === 'lightLux' ? 0 : 2);
const timestampText = value => {
  if (!value) return 'No valid record yet';
  const ts = (typeof value === 'string' && !value.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(value)) ? value + 'Z' : value;
  return new Date(ts).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
};
const relativeTime = value => {
  if (!value) return 'No valid record';
  const seconds = Math.max(0, Math.floor((Date.now() - parseUtc(value)) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
};
const healthState = health => {
  if (!health) return 'Unknown';
  const raw = String(health.status || health.health || '').toLowerCase();
  if (health.ok === true || ['ok', 'healthy', 'up', 'ready'].includes(raw)) return 'Healthy';
  if (health.ok === false || ['error', 'unhealthy', 'down', 'not_ready'].includes(raw)) return 'Unhealthy';
  return 'Reachable · health unconfirmed';
};
const remoteFlag = value => value === true ? 'Connected' : value === false ? 'Disconnected' : 'Not reported';

function Icon({ children, tone = '' }) { return <span className={`icon ${tone}`}>{children}</span>; }
function StatusPill({ children, tone = 'neutral' }) { return <span className={`status-pill ${tone}`}><i />{children}</span>; }
function Panel({ title, subtitle, extra, children, className = '' }) {
  return <section className={`panel ${className}`}><header className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{extra}</header>{children}</section>;
}
function Empty({ title, detail, action }) { return <div className="empty-state"><div className="empty-icon">⌁</div><strong>{title}</strong><p>{detail}</p>{action}</div>; }
function MetricCard({ metric, record, updated, demo, predicted = false }) {
  const config = VARIABLES[metric];
  return <article className="metric-card">
    <div className="metric-top"><span>{config.label}</span><Icon tone={metric}>{metric==='powerW'?'ϟ':metric==='voltageV'?'↗':metric==='currentA'?'⟲':metric==='temperatureC'?'◉':'☼'}</Icon></div>
    <div className="metric-number">{valueText(record, metric)} <small>{config.unit}</small></div>
    <div className="metric-foot"><span>{predicted ? 'Predicted · twin model' : demo ? 'Demo sample · not measured' : 'Latest valid record'}</span><time title={timestampText(updated)}>{relativeTime(updated)}</time></div>
  </article>;
}
function MetricGrid({ record, demo, predicted = false }) {
  const updated = record?.timestamp || null;
  return <div className="metric-grid">{Object.keys(VARIABLES).map(key => <MetricCard key={key} metric={key} record={record} updated={updated} demo={demo} predicted={predicted} />)}</div>;
}
function TrendChart({ real, simulated, variable = 'powerW', compare = true, demo = false, height = 290 }) {
  const config = VARIABLES[variable];
  const points = useMemo(() => {
    const realMap = new Map(sortRecords(real).map(r => [new Date(r.timestamp).toISOString(), r]));
    const twinMap = new Map(sortRecords(simulated).map(r => [new Date(r.timestamp).toISOString(), r]));
    const times = [...new Set([...realMap.keys(), ...twinMap.keys()])].sort().slice(-48);
    return times.map((timestamp, index) => ({
      time: new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      fullTime: timestamp,
      real: validValue(realMap.get(timestamp)?.measurements?.[variable]),
      twin: validValue(twinMap.get(timestamp)?.measurements?.[variable]),
      index,
    }));
  }, [real, simulated, variable]);
  const singleKey = real.length ? 'real' : 'twin';
  const hasSeries = point => compare ? point.real !== null || point.twin !== null : point[singleKey] !== null;
  if (!points.length || points.every(point => !hasSeries(point))) {
    return <Empty title="No trend records" detail="Valid, timestamped records will appear here when data arrives." />;
  }
  return <div className="chart-wrap" style={{ height }}>
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={points} margin={{ top: 8, right: 12, left: 2, bottom: 2 }}>
        <CartesianGrid stroke="#edf1f5" vertical={false} />
        <XAxis dataKey="time" tick={{ fill:'#8792a0',fontSize:11 }} axisLine={false} tickLine={false} minTickGap={26} />
        <YAxis width={50} tick={{ fill:'#8792a0',fontSize:11 }} axisLine={false} tickLine={false} tickFormatter={v=>fmt(v,0)} />
        <Tooltip content={<ChartTooltip config={config} demo={demo} />} />
        <Legend wrapperStyle={{fontSize:11,paddingTop:8}} />
        {compare ? <><Line type="monotone" dataKey="real" name={demo?'Demo real-source fixture':'Real'} stroke={config.color} strokeWidth={2.5} dot={false} connectNulls={false} activeDot={{r:4}} /><Line type="monotone" dataKey="twin" name="Twin predicted" stroke="#a9b4c1" strokeDasharray="5 5" strokeWidth={2} dot={false} connectNulls={false} activeDot={{r:4}} /></> : <Line type="monotone" dataKey={singleKey} name={singleKey==='twin'?'Twin predicted':demo?'Demo fixture':'Real'} stroke={singleKey==='twin'?'#8c86a5':config.color} strokeWidth={2.5} dot={false} connectNulls={false} activeDot={{r:4}} />}
      </LineChart>
    </ResponsiveContainer>
  </div>;
}
function ChartTooltip({ active, payload, label, config, demo }) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload;
  return <div className="chart-tooltip"><b>{point?.fullTime ? timestampText(point.fullTime) : label}</b>
    {payload.map(item => item.value !== null && item.value !== undefined && <div key={item.dataKey} style={{color:item.color}}>{item.name}: {fmt(item.value,2)} {config.unit}{demo&&item.dataKey==='real'?' · demo':''}</div>)}
  </div>;
}
function PowerArea({ real, demo }) {
  const data = sortRecords(real).slice(-36).map(record => ({
    time: new Date(record.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}),
    fullTime: record.timestamp, value: record.measurements.powerW,
  }));
  if (!data.length || data.every(d=>d.value===null)) return <Empty title="Waiting for power samples" detail="Power is shown from a supplied value or calculated as voltage × current." />;
  return <div className="chart-wrap" style={{height:250}}><ResponsiveContainer width="100%" height="100%"><AreaChart data={data} margin={{top:8,right:10,left:0,bottom:0}}>
    <defs><linearGradient id="powerFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#1678e8" stopOpacity={.22}/><stop offset="100%" stopColor="#1678e8" stopOpacity={0}/></linearGradient></defs>
    <CartesianGrid stroke="#edf1f5" vertical={false}/><XAxis dataKey="time" tick={{fill:'#8792a0',fontSize:11}} axisLine={false} tickLine={false} minTickGap={26}/><YAxis width={45} tick={{fill:'#8792a0',fontSize:11}} axisLine={false} tickLine={false}/><Tooltip content={<ChartTooltip config={VARIABLES.powerW} demo={demo}/>}/><Area type="monotone" dataKey="value" name={demo?'Demo power':'Real power'} stroke="#1678e8" strokeWidth={2.5} fill="url(#powerFill)" connectNulls={false}/>
  </AreaChart></ResponsiveContainer></div>;
}
function PanelStatus({ title, record, demo, error, source }) {
  const stale = !demo && isRecordStale(record);
  let status = error ? 'error' : demo ? 'demo' : !record ? 'empty' : stale ? 'stale' : 'ok';
  let label = error ? 'API error' : !record ? 'No data' : stale ? 'Stale' : demo ? 'Demo Data' : 'Receiving';
  return <div className="panel-status"><div><strong>{title}</strong><p>{source}</p></div><StatusPill tone={status}>{label}</StatusPill></div>;
}
function RecordTable({ records, demo, predicted = false }) {
  const rows = sortRecords(records).slice(-8).reverse();
  if (!rows.length) return <div className="table-empty">No records available for this panel.</div>;
  return <div className="table-scroll"><table><thead><tr><th>Timestamp</th><th>Source</th><th>Light</th><th>Temp</th><th>V</th><th>A</th><th>Power</th></tr></thead><tbody>{rows.map(row=><tr key={row.id}><td>{timestampText(row.timestamp)}</td><td><span className={`source-tag ${predicted?'simulated':'real'}`}>{predicted?'SIMULATED / PREDICTED':demo?'DEMO / NOT MEASURED':'REAL'}</span></td><td>{valueText(row,'lightLux')} lx</td><td>{valueText(row,'temperatureC')} °C</td><td>{valueText(row,'voltageV')} V</td><td>{valueText(row,'currentA')} A</td><td>{valueText(row,'powerW')} W</td></tr>)}</tbody></table></div>;
}
function Header({ page, demo, refreshing, onRefresh }) {
  const title = NAV.find(item=>item[0]===page)?.[1] || 'Overview';
  return <header className="topbar"><div><div className="breadcrumb">ANUBHAV LAB <span>/</span> <b>{title}</b></div><div className="top-title">Coral Anubhav · Panel monitor</div></div><div className="top-actions"><StatusPill tone={demo?'demo':'live'}>{demo?'Demo Data':'Live API'}</StatusPill><button className="button ghost" onClick={onRefresh} disabled={refreshing}>{refreshing?'Updating…':'↻ Refresh'}</button></div></header>;
}

export default function App() {
  const [page,setPage]=useState('overview');
  const [apiBase,setApiBase]=useState(()=>localStorage.getItem('anubhav-api-base') ?? getInitialApiBase());
  const [draftBase,setDraftBase]=useState(apiBase);
  const [data,setData]=useState({demo:!apiBase,real:[],simulated:[],errors:{},health:null,network:null,reachability:'demo'});
  const [loading,setLoading]=useState(true);
  const [refreshing,setRefreshing]=useState(false);
  const [lastSuccess,setLastSuccess]=useState(null);
  const [variable,setVariable]=useState('powerW');
  const [uiError,setUiError]=useState('');
  const real=useMemo(()=>sortRecords(data.real.filter(r=>r.source==='real')),[data.real]);
  const simulated=useMemo(()=>sortRecords(data.simulated.filter(r=>r.source==='simulated')),[data.simulated]);
  const latestReal=latestOf(real),latestTwin=latestOf(simulated);
  const noRecords=!data.demo&&!real.length&&!data.errors.real;
  const stale=!data.demo&&Boolean(latestReal&&isRecordStale(latestReal));

  const refresh=useCallback(async({quiet=false}={})=>{
    if(!quiet)setRefreshing(true);
    try{
      const result=await fetchDashboardData(apiBase);
      setData(result);setUiError('');
      if(result.real?.length)setLastSuccess(latestOf(result.real)?.timestamp || new Date().toISOString());
      if(result.errors.real)setUiError(`Real panel API: ${result.errors.real}`);
      else if(result.errors.health)setUiError(`Health endpoint: ${result.errors.health}`);
    } catch(error) { setUiError(error.message||'Could not load dashboard data'); }
    finally {setLoading(false);setRefreshing(false)}
  },[apiBase]);
  useEffect(()=>{setLoading(true);refresh();const timer=setInterval(()=>refresh({quiet:true}),Math.max(3000,pollIntervalMs));return()=>clearInterval(timer)},[refresh]);

  const saveBase=event=>{event.preventDefault();const clean=draftBase.trim().replace(/\/+$/,'');setApiBase(clean);localStorage.setItem('anubhav-api-base',clean);setPage('network')};
  const resetDemo=()=>{setDraftBase('');setApiBase('');localStorage.removeItem('anubhav-api-base');};

  const pageTitle= NAV.find(item=>item[0]===page)?.[1] || 'Overview';
  const failedEndpoint=uiError||Object.values(data.errors||{}).length>0;

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">A<span>5</span></div><div><b>ANUBHAV</b><small>5G PANEL LAB</small></div></div>
      <div className="side-label">MONITORING</div>
      <nav>{NAV.map(([key,label,icon])=><button key={key} className={`nav-item ${page===key?'selected':''}`} onClick={()=>setPage(key)}><span className="nav-icon">{icon}</span>{label}{key==='twin'&&<span className="nav-tag">MODEL</span>}</button>)}</nav>
      <div className="side-device"><div className="side-device-top"><span className={`pulse ${data.demo?'demo-pulse':data.reachability==='reachable'?'online':'offline'}`}/><span>{data.demo?'DEMO SOURCE':data.reachability==='reachable'?'API REACHABLE':'API STATUS'}</span></div><b>Coral Anubhav</b><small>Evaluation board · Solar panel twin</small></div>
      <div className="side-footer">Telemetry console <span>v1.0</span></div>
    </aside>
    <main className="main-area">
      <Header page={page} demo={data.demo} refreshing={refreshing} onRefresh={()=>refresh()} />
      <div className="page-content">
        <div className="page-intro"><div><div className="eyebrow">5G · SOLAR PANEL USE CASE</div><h1>{pageTitle}</h1><p>Live panel telemetry and a separately labeled digital twin prediction.</p></div><div className="update-stamp"><span className="tiny-dot"/>Latest valid record <b>{relativeTime(latestReal?.timestamp)}</b></div></div>
        {data.demo&&<div className="demo-banner"><span className="demo-ico">D</span><div><b>DEMO DATA · NO HARDWARE MEASUREMENTS</b><span>Sample records are used to shape the interface. Twin values are model predictions. Configure the API base URL in Network Status to load backend data.</span></div><button onClick={()=>setPage('network')}>Configure API <span>→</span></button></div>}
        {!data.demo&&uiError&&<div className="notice error"><b>Data source issue</b><span>{uiError} · Last successful update: {timestampText(lastSuccess)}</span><button onClick={()=>refresh()}>Retry</button></div>}
        {loading&&<div className="notice loading"><span className="spinner"/>Loading panel records…</div>}
        {noRecords&&!loading&&<div className="notice empty-notice"><b>No real panel records yet</b><span>The API is reachable, but it returned no records tagged <code>source: "real"</code>.</span></div>}
        {page==='overview'&&<Overview real={real} simulated={simulated} latestReal={latestReal} latestTwin={latestTwin} demo={data.demo} errors={data.errors} stale={stale} loading={loading} onNavigate={setPage} />}
        {page==='live'&&<LiveMonitoring real={real} latest={latestReal} demo={data.demo} error={data.errors.real} stale={stale} loading={loading} />}
        {page==='twin'&&<DigitalTwin records={simulated} latest={latestTwin} realLatest={latestReal} demo={data.demo} loading={loading} />}
        {page==='analytics'&&<Analytics real={real} simulated={simulated} variable={variable} setVariable={setVariable} demo={data.demo} />}
        {page==='network'&&<NetworkStatus data={data} apiBase={apiBase} draftBase={draftBase} setDraftBase={setDraftBase} saveBase={saveBase} resetDemo={resetDemo} lastSuccess={lastSuccess} />}
        <footer className="page-footer">Dashboard refreshes every {Math.round(pollIntervalMs/1000)} seconds · {data.demo?'Demo fixture':'Backend API'} · Lab/MEC state is shown only when returned by the backend.</footer>
      </div>
    </main>
  </div>;
}

function Overview({real,simulated,latestReal,latestTwin,demo,errors,stale,loading,onNavigate}) {
  const sourceLabel=demo?'Demo fixture · not hardware':'source: real';
  return <>
    <PanelStatus title="REAL PANEL" record={latestReal} demo={demo} error={errors.real} source={sourceLabel} />
    {stale&&<div className="notice stale"><b>Real panel data is stale</b><span>Latest valid record is older than the configured threshold. Check the sensor or backend stream.</span></div>}
    {!loading&&!latestReal&&!errors.real&&<Empty title="No real sensor values" detail="The real panel is empty until a valid source=real record arrives." />}
    {latestReal&&<MetricGrid record={latestReal} demo={demo}/>}
    <div className="content-grid overview-grid">
      <Panel title="Live power trend" subtitle="Real panel power · derived from voltage × current when omitted" extra={<button className="link-button" onClick={()=>onNavigate('live')}>Open monitoring →</button>}><div className="panel-body"><PowerArea real={real} demo={demo}/></div></Panel>
      <Panel title="Digital twin snapshot" subtitle="Predicted values · independent model output" extra={<button className="link-button" onClick={()=>onNavigate('twin')}>Open twin →</button>}><div className="twin-summary">
        <div className="twin-big">{valueText(latestTwin,'powerW')} <small>W</small></div><div className="predicted-label"><span>SIMULATED / PREDICTED</span><time>{timestampText(latestTwin?.timestamp)}</time></div>
        <div className="twin-stats"><span>Voltage <b>{valueText(latestTwin,'voltageV')} V</b></span><span>Current <b>{valueText(latestTwin,'currentA')} A</b></span><span>Temperature <b>{valueText(latestTwin,'temperatureC')} °C</b></span></div>
        <div className="model-callout">Model assumes power scales with light intensity and applies a temperature derate. Not calibrated to the physical panel.</div>
      </div></Panel>
    </div>
    <Panel title="Recent records" subtitle="Latest real-panel stream records" extra={<span className={`source-tag ${demo?'demo':'real'}`}>{demo?'DEMO · NOT MEASURED':'REAL SOURCE'}</span>}><RecordTable records={real} demo={demo}/></Panel>
  </>;
}
function LiveMonitoring({real,latest,demo,error,stale,loading}) {
  return <>
    <PanelStatus title="REAL PANEL · LIVE STREAM" record={latest} demo={demo} error={error} source={demo?'Sample real-source fixture · not measured':'Backend records filtered to source=real'} />
    {error&&<div className="notice error"><b>Live data unavailable</b><span>{error}</span></div>}
    {stale&&<div className="notice stale"><b>Data is stale</b><span>The latest record is older than {Math.round(staleAfterMs/1000)} seconds.</span></div>}
    {loading&&!latest?<Empty title="Loading live telemetry" detail="Waiting for the first valid record…"/>:latest?<><MetricGrid record={latest} demo={demo}/><div className="trend-panel-grid">{Object.entries(VARIABLES).map(([key,config])=><Panel key={key} title={`${config.label} trend`} subtitle={`Real panel · ${config.unit}`}><div className="panel-body"><TrendChart real={real} simulated={[]} compare={false} variable={key} demo={demo} height={210}/></div></Panel>)}</div></>:<Empty title="No live measurements" detail="The API must return valid records tagged source=real."/>}
    <Panel title="Live record stream" subtitle="Timestamp and source are preserved from each backend record"><RecordTable records={real} demo={demo}/></Panel>
  </>;
}
function SolarPanel2D({ latest, realLatest }) {
  const [mode, setMode] = useState('pv');
  const [hoverCell, setHoverCell] = useState(null);

  const m = latest?.measurements || {};
  const rm = realLatest?.measurements || {};
  const pwr = Number(m.powerW ?? 0);
  const volt = Number(m.voltageV ?? 0);
  const cur = Number(m.currentA ?? 0);
  const temp = Number(m.temperatureC ?? rm.temperatureC ?? 25.0);
  const lux = Number(m.lightLux ?? rm.lightLux ?? 0);

  const deltaTemp = Math.max(0, temp - 25);
  const deratePercent = (deltaTemp * 0.4).toFixed(1);
  const irradianceEst = Math.round(lux / 95);
  const isGenerating = pwr > 0.5;

  const cells = [];
  for (let r = 0; r < 6; r++) {
    for (let c = 0; c < 10; c++) {
      const x = 38 + c * 76;
      const y = 38 + r * 61;
      const id = r * 10 + c + 1;
      const stringId = c < 3 ? 'A' : c < 7 ? 'B' : 'C';
      const dist = Math.hypot(c - 4.5, r - 2.5);
      const cellTemp = (temp - 0.7 + (3.5 - dist) * 0.4).toFixed(1);

      let fill;
      if (mode === 'thermal') {
        const ct = Number(cellTemp);
        fill = ct <= 25 ? '#0e5066' : ct <= 29 ? '#166534' : ct <= 35 ? '#b45309' : ct <= 42 ? '#c2410c' : '#b91c1c';
      } else {
        fill = `rgb(13, 34, ${42 + ((r * 10 + c) % 5) * 3})`;
      }

      cells.push({ id, r: r + 1, c: c + 1, x, y, stringId, cellTemp, fill });
    }
  }

  return (
    <div className="panel-2d-twin-container">
      <div className="panel-2d-topbar">
        <div className="panel-2d-buttons">
          <button
            className={`button ${mode === 'pv' ? 'primary' : 'ghost'}`}
            onClick={() => setMode('pv')}
          >
            ☀️ Photovoltaic View
          </button>
          <button
            className={`button ${mode === 'thermal' ? 'primary' : 'ghost'}`}
            onClick={() => setMode('thermal')}
          >
            🌡️ Thermal Heatmap
          </button>
        </div>
        <div className="panel-2d-hud">
          <span className="hud-pill hud-pwr">⚡ {pwr.toFixed(1)} W</span>
          <span className="hud-pill hud-vi">{volt.toFixed(1)} V · {cur.toFixed(2)} A</span>
          <span className="hud-pill hud-temp">🌡️ {temp.toFixed(1)} °C ({deratePercent}% derate)</span>
          <span className="hud-pill hud-irr">☀️ {lux.toLocaleString()} lx (≈{irradianceEst} W/m²)</span>
        </div>
      </div>

      <div className="panel-svg-wrap">
        <svg viewBox="0 0 832 436" className="panel-svg-elem">
          <defs>
            <linearGradient id="frameGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#94a3b8" />
              <stop offset="50%" stopColor="#475569" />
              <stop offset="100%" stopColor="#64748b" />
            </linearGradient>
            <linearGradient id="sunGleam" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#ffffff" stopOpacity="0.32" />
              <stop offset="30%" stopColor="#60a5fa" stopOpacity="0.12" />
              <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
            </linearGradient>
          </defs>

          {/* Frame & Mounting */}
          <rect x="8" y="8" width="816" height="420" rx="10" fill="url(#frameGrad)" stroke="#334155" strokeWidth="2" />
          <rect x="18" y="18" width="796" height="400" rx="6" fill="#09111e" stroke="#1e293b" strokeWidth="2" />
          <circle cx="13" cy="13" r="3" fill="#cbd5e1" />
          <circle cx="819" cy="13" r="3" fill="#cbd5e1" />
          <circle cx="13" cy="423" r="3" fill="#cbd5e1" />
          <circle cx="819" cy="423" r="3" fill="#cbd5e1" />

          {/* Top Bus Ribbon & Junction Box */}
          <rect x="38" y="24" width="756" height="8" rx="2" fill="#334155" />
          <rect x="376" y="10" width="80" height="12" rx="3" fill="#1e293b" stroke="#475569" />
          <text x="416" y="19" fontSize="8" fill="#94a3b8" textAnchor="middle" fontFamily="monospace">5G MEC JUNCTION</text>

          {/* Cells */}
          <g>
            {cells.map(cell => (
              <g
                key={cell.id}
                onMouseEnter={() => setHoverCell(cell)}
                onMouseLeave={() => setHoverCell(null)}
              >
                <rect
                  x={cell.x}
                  y={cell.y}
                  width="72"
                  height="56"
                  rx="4"
                  fill={cell.fill}
                  stroke="#1e293b"
                  strokeWidth="1"
                  className="cell-rect"
                />
                {/* Finger lines */}
                {[1, 2, 3, 4, 5].map(f => (
                  <line
                    key={f}
                    x1={cell.x + 1}
                    y1={cell.y + f * 9.3}
                    x2={cell.x + 71}
                    y2={cell.y + f * 9.3}
                    stroke="rgba(255,255,255,0.12)"
                    strokeWidth="0.6"
                    pointerEvents="none"
                  />
                ))}
                {/* 3 Busbars + dynamic energy stream */}
                {[18, 36, 54].map(bx => (
                  <g key={bx}>
                    <line
                      x1={cell.x + bx}
                      y1={cell.y}
                      x2={cell.x + bx}
                      y2={cell.y + 56}
                      stroke="#cbd5e1"
                      strokeWidth="1.5"
                      pointerEvents="none"
                    />
                    {isGenerating && (
                      <line
                        x1={cell.x + bx}
                        y1={cell.y}
                        x2={cell.x + bx}
                        y2={cell.y + 56}
                        stroke="#38bdf8"
                        strokeWidth="1.8"
                        className="pv-energy-stream"
                        pointerEvents="none"
                      />
                    )}
                  </g>
                ))}
              </g>
            ))}
          </g>

          {/* Sunlight Sheen */}
          {mode === 'pv' && lux > 0 && (
            <polygon points="18,18 450,18 200,418 18,418" fill="url(#sunGleam)" pointerEvents="none" />
          )}

          {/* Bottom Bus Ribbon */}
          <rect x="38" y="404" width="756" height="8" rx="2" fill="#334155" />
        </svg>
      </div>

      <div className="panel-2d-footer">
        {hoverCell ? (
          <span>
            <b>Cell #{hoverCell.id}</b> (Row {hoverCell.r}, Col {hoverCell.c}) · String {hoverCell.stringId} · Model Temp: <b>{hoverCell.cellTemp} °C</b> · V_cell: ~0.57 V
          </span>
        ) : (
          <span>Hover over any of the 60 photovoltaic cells to inspect cell telemetry.</span>
        )}
        <span className={isGenerating ? 'status-generating' : 'status-standby'}>
          {isGenerating ? '● Generating · 5G Ultra-Low Latency' : '○ Standby (Low Light) · 5G Connected'}
        </span>
      </div>
    </div>
  );
}

function DigitalTwin({records,latest,realLatest,demo,loading}) {
  return <>
    <PanelStatus title="DIGITAL TWIN" record={latest} demo={demo} source={demo?'Generated demo predictions':'Simulated records or client-side model'} />
    <div className="model-banner"><span className="model-glyph">◇</span><div><b>SIMULATED / PREDICTED VALUES</b><p>These outputs are model estimates. They are not sensor measurements and must not be treated as real-panel readings.</p></div></div>
    {loading&&!latest?<Empty title="Generating twin data" detail="Waiting for real-panel input or the simulation endpoint."/>:latest?<><MetricGrid record={latest} demo={false} predicted/><Panel title="2D Solar Photovoltaic Twin" subtitle="Interactive physical simulation · Multi-busbar PV cell matrix with dynamic thermal derating and energy flux"><SolarPanel2D latest={latest} realLatest={realLatest}/></Panel><div className="content-grid twin-grid"><Panel title="Predicted power trend" subtitle="Model output · input sourced from real panel variables"><div className="panel-body"><TrendChart real={[]} simulated={records} compare={false} variable="powerW" demo={false} height={300}/></div></Panel><Panel title="Model inputs and assumptions" subtitle="Current twin model · version 1"><div className="assumption-list"><div><b>Light intensity</b><span>Acts as a linear irradiance proxy, capped at 1.2 × reference.</span></div><div><b>Reference conditions</b><span>95,000 lx maps to 100 W modeled output at 25 °C.</span></div><div><b>Temperature effect</b><span>Power derates 0.4% per °C above 25 °C; voltage derates 0.025 V/°C.</span></div><div><b>Current</b><span>Calculated as predicted power ÷ predicted voltage.</span></div><div><b>Limit</b><span>Illustrative only: lux is not calibrated irradiance and the model is not panel-specific.</span></div></div><div className="twin-input">Latest input {demo?'(demo sample)':'(real source)'}: {valueText(realLatest,'lightLux')} lx · {valueText(realLatest,'temperatureC')} °C</div></Panel></div></>:<Empty title="Twin has no input" detail="The twin needs a valid real-panel record or a simulated-record response from the backend."/>}
    <Panel title="Predicted records" subtitle="Every row in this panel is explicitly labeled simulated / predicted"><RecordTable records={records} demo={false} predicted/></Panel>
  </>;
}
function Analytics({real,simulated,variable,setVariable,demo}) {
  const config=VARIABLES[variable];
  return <>
    <div className="analytics-controls"><div><b>Compare real and twin</b><span>Use matching timestamps to compare measured and predicted values.</span></div><label>Variable<select value={variable} onChange={e=>setVariable(e.target.value)}>{Object.entries(VARIABLES).map(([key,item])=><option key={key} value={key}>{item.label}</option>)}</select></label></div>
    <Panel title={`${config.label} comparison`} subtitle={`Real panel ${demo?'demo fixture (not measured)':'source=real'} versus twin predicted` } extra={<span className="source-tag simulated">TWIN PREDICTED</span>}><div className="panel-body"><TrendChart real={real} simulated={simulated} variable={variable} demo={demo} height={360}/></div></Panel>
    <div className="content-grid analytics-bottom"><Panel title="Series summary" subtitle="Latest available record for selected variable"><div className="summary-columns"><div><span>{demo?'REAL-SOURCE DEMO FIXTURE':'REAL PANEL'}</span><strong>{valueText(latestOf(real),variable)} <small>{config.unit}</small></strong><time>{timestampText(latestOf(real)?.timestamp)}</time></div><div className="sim-summary"><span>SIMULATED / PREDICTED</span><strong>{valueText(latestOf(simulated),variable)} <small>{config.unit}</small></strong><time>{timestampText(latestOf(simulated)?.timestamp)}</time></div></div></Panel><Panel title="Interpretation" subtitle="Keep provenance visible"><div className="interpret-note"><b>Separate sources</b><p>Real-source records and model predictions are shown as separate series. Demo fixtures are labeled and are not physical measurements. Missing values are left as gaps instead of being interpolated.</p></div></Panel></div>
  </>;
}
function NetworkStatus({data,apiBase,draftBase,setDraftBase,saveBase,resetDemo,lastSuccess}) {
  const health=healthState(data.health);
  const network=data.network||{};
  const reachTone=data.demo?'demo':data.reachability==='reachable'?'live':'error';
  const backendFields=Object.keys(data.health||{}).length>0;
  const lastBackend=network.lastSuccessfulUpdate||network.last_successful_update||null;
  const endpointErrors=Object.entries(data.errors||{});
  return <>
    {endpointErrors.length>0&&<div className="notice error"><b>Endpoint errors</b><span>{endpointErrors.map(([name,message])=>`${name}: ${message}`).join(' · ')}</span></div>}
    <div className="network-grid">
      <Panel title="API reachability" subtitle="Based on a real fetch to the configured health endpoint" extra={<StatusPill tone={reachTone}>{data.demo?'Demo mode':data.reachability==='reachable'?'Reachable':'Unreachable'}</StatusPill>}><div className="network-detail-list"><div><span>API base URL</span><b>{apiBase||'Not configured · mock mode active'}</b></div><div><span>Backend health</span><b className={health==='Healthy'?'text-green':health==='Unhealthy'?'text-red':''}>{data.demo?'Not verified in demo mode':data.errors.health?'Unreachable':health}</b></div><div><span>Last successful data update</span><b>{data.demo?'Not verified':timestampText(lastBackend||lastSuccess)}</b></div><div><span>Health response</span><b>{data.demo?'Demo mode':data.errors.health||(!backendFields?'No health payload':'Received')}</b></div></div></Panel>
      <Panel title="Lab and MEC connection" subtitle="Displayed only from backend network checks"><div className="network-detail-list"><div><span>Lab network</span><b>{data.demo?'Not verified':remoteFlag(network.labConnected??network.lab_connected)}</b></div><div><span>MEC connection</span><b>{data.demo?'Not verified':remoteFlag(network.mecConnected??network.mec_connected)}</b></div><div><span>API online status</span><b>{data.demo?'Not verified':navigator.onLine?'Browser online · API check required':'Browser offline'}</b></div><div><span>Last status check</span><b>{data.demo?'—':new Date().toLocaleString([], {dateStyle:'medium',timeStyle:'short'})}</b></div></div></Panel>
    </div>
    <Panel title="Backend configuration" subtitle="Set Member 2's API base URL without rebuilding the frontend"><form className="api-form" onSubmit={saveBase}><label htmlFor="apiBase">API base URL</label><div className="api-input-row"><input id="apiBase" type="url" placeholder="https://your-mec-host.example" value={draftBase} onChange={e=>setDraftBase(e.target.value)}/><button className="button primary" type="submit">Save and connect</button><button className="button ghost" type="button" onClick={resetDemo}>Use demo data</button></div><small>Endpoints are configured in the project environment file. Saved URL is kept in this browser only.</small></form></Panel>
    <Panel title="Expected network payload" subtitle="The dashboard does not infer lab/MEC status from browser connectivity"><pre className="code-block">{`GET /api/network/status\n{\n  "labConnected": true,\n  "mecConnected": true,\n  "lastSuccessfulUpdate": "2026-11-06T08:15:30Z"\n}`}</pre></Panel>
  </>;
}
