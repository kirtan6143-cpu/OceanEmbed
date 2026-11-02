import React, { useState, useEffect, useRef } from "react";
import OceanMap, { placeName } from "./OceanMap";
import Locator from "./Locator";

// Whole-column diagnostics have no depth dimension of their own -- see
// science.field_diagnostics()/api.py's PROFILE_DERIVED. Kept as a Set here so
// the dropdown, the depth-selector disable, and the panel title logic below
// all read the same source of truth instead of three separate string checks.
const DEPTH_INDEPENDENT = new Set(["tchp", "d26", "mld_t"]);
const VARIABLE_TITLE: Record<string, string> = {
  tchp: "Tropical Cyclone Heat Potential",
  d26: "D26 · 26°C isotherm depth",
  mld_t: "MLD-T · mixed-layer depth",
};
import Cutaway from "./Cutaway";
import { observationScatter } from "./validation.mjs";
import { depthOptionLabel, displayFieldFor, isDisplayEstimate } from "./depthSemantics.mjs";
import {
  Search,
  Layers,
  Flame,
  ShieldCheck,
  ShieldAlert,
  Download,
  ChevronRight,
  Play,
  Pause,
  Info,
  Activity,
  FileText,
  Box,
  SlidersHorizontal,
  Siren,
  Wind,
  Home,
  Hospital,
  Radio,
  Phone,
  Satellite,
} from "lucide-react";

type Obj = Record<string, any>;
let chartEngine: Promise<any> | undefined;
function loadChartEngine() {
  return chartEngine ??= import("plotly.js-cartesian-dist-min").then((m) => m.default).catch((e) => {
    chartEngine = undefined;
    throw e;
  });
}
const tabs = ["Explore", "Sections", "Heat events", "Validate", "Exports", "Readiness"];
const icons = [Search, Layers, Flame, ShieldCheck, Download, ShieldAlert];
const thermal = [
  [0, "#152451"],
  [0.22, "#245eb3"],
  [0.43, "#25b8cc"],
  [0.64, "#a9d68b"],
  [0.82, "#f4c25e"],
  [1, "#f4714c"],
];
const balance = [
  [0, "#23429b"],
  [0.25, "#42a3ce"],
  [0.5, "#e7f0e8"],
  [0.75, "#f39b5e"],
  [1, "#bc314b"],
];
async function api(path: string, params: Obj = {}, signal?: AbortSignal) {
  const r = await fetch("/api" + path + "?" + new URLSearchParams(params), {
    signal,
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw Error(e.detail || `Request failed (${r.status}). Check the local API.`);
  }
  return r.json();
}
// Some backends in this project expose /color-reference (stable, run-pooled
// percentile colouring); others don't. Read the API's own route list once
// instead of calling the endpoint blind, so a backend without it produces no
// failed requests and the map/cutaway simply use their linear colour scale.
// Resolves to null while unknown, then true/false.
let colorRefSupport: Promise<boolean> | undefined;
function useColorReferenceSupport() {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    colorRefSupport ??= fetch("/api/openapi.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((spec) => !!spec?.paths?.["/color-reference"])
      .catch(() => false);
    colorRefSupport.then((v) => live && setOk(v));
    return () => {
      live = false;
    };
  }, []);
  return ok;
}

function useData(path: string, params: Obj, enabled = true) {
  const [data, setData] = useState<any>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [resolvedKey, setResolvedKey] = useState("");
  const key = JSON.stringify(params);
  const requestKey = path + key;
  useEffect(() => {
    if (!enabled) {
      setData(null);
      return;
    }
    const c = new AbortController();
    const timer = setTimeout(() => {
      c.abort();
      setError("Request timed out. Check the API, then change the selection to retry.");
      setResolvedKey(requestKey);
      setLoading(false);
    }, 30000);
    setLoading(true);
    setError("");
    setData(null);
    api(path, params, c.signal)
      .then((value) => {
        if (!c.signal.aborted) {
          setData(value);
          setResolvedKey(requestKey);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) {
          setError(e.message);
          setResolvedKey(requestKey);
        }
      })
      .finally(() => {
        clearTimeout(timer);
        if (!c.signal.aborted) setLoading(false);
      });
    return () => { clearTimeout(timer); c.abort(); };
  }, [path, key, enabled]);
  const current = enabled && resolvedKey === requestKey;
  return { data: current ? data : null, error: current ? error : "", loading: enabled && (!current || loading) };
}
function Plot({
  data,
  layout = {},
  onClick,
  height = 380,
}: {
  data: any[];
  layout?: Obj;
  onClick?: any;
  height?: number;
}) {
  const ref = useRef<any>(null);
  const [Plotly, setPlotly] = useState<any>(null);
  const [chartError, setChartError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setChartError("");
    loadChartEngine().then((engine) => { if (active) setPlotly(engine); })
      .catch(() => { if (active) setChartError("Chart engine could not load. Check the local frontend server."); });
    return () => { active = false; };
  }, [attempt]);
  const handler = useRef(onClick);
  handler.current = onClick;
  // Parents recreate trace arrays for unrelated controls. Compare their content
  // so these renders don't repeatedly ask Plotly to rebuild identical charts.
  const dataKey = JSON.stringify(data);
  useEffect(() => {
    if (!Plotly) return;
    const node = ref.current;
    Plotly.react(
      node,
      data,
      {
        paper_bgcolor: "transparent",
        plot_bgcolor: "#091f2e",
        font: { color: "#a8bfcc", family: "Arial", size: 12 },
        margin: { l: 54, r: 25, t: 15, b: 48 },
        height,
        autosize: true,
        transition: { duration: 420, easing: "cubic-in-out" },
        hoverlabel: { bgcolor: "#071d2b", bordercolor: "#55d9ef", font: { color: "#e8f8fd" } },
        xaxis: { gridcolor: "#203b4d", zeroline: false },
        yaxis: { gridcolor: "#203b4d", zeroline: false },
        legend: { orientation: "h", y: -0.2 },
        ...layout,
      },
      {
        responsive: true,
        displaylogo: false,
        modeBarButtonsToRemove: ["lasso2d", "select2d"],
      },
    );
    node.removeAllListeners?.("plotly_click");
    node.on?.("plotly_click", (e) => handler.current?.(e));
  }, [Plotly, dataKey, JSON.stringify(layout), height]);
  useEffect(() => {
    if (!Plotly) return;
    const node = ref.current;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (node.isConnected && node.clientWidth) Plotly.Plots.resize(node);
      });
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      Plotly.purge(node);
    };
  }, [Plotly]);
  return (
    <>
      {chartError ? <div role="alert">{chartError} <button onClick={() => setAttempt((v) => v + 1)}>Retry chart</button></div>
        : !Plotly && <div role="status">Loading interactive chart…</div>}
      <div ref={ref} className="plot" style={{ minHeight: height }} aria-label="Interactive scientific chart" aria-busy={!Plotly} />
    </>
  );
}
function Panel({ title, sub, children, className = "" }: any) {
  return (
    <section className={"panel " + className}>
      <div className="panel-heading">
        <h3>{title}</h3>
        {sub && <span>{sub}</span>}
      </div>
      {children}
    </section>
  );
}
function Field({ label, children }: any) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
function Notice({ children }: any) {
  return (
    <div className="notice">
      <Info size={17} />
      <span>{children}</span>
    </div>
  );
}
function Load({ state }: any) {
  return state.error ? (
    <div role="alert" className="error">
      {state.error}
    </div>
  ) : state.loading ? (
    <div className="empty">Loading the selected run…</div>
  ) : null;
}
function fmt(v: any, d = 2) {
  return v == null ? "—" : Number(v).toFixed(d);
}
// Commonly cited TCHP research bands (e.g. Shay/Goni/Black-style thresholds
// used in tropical-cyclone heat-potential literature). Context only — never
// a forecast, never a danger level. Kept in one place so the gauge, the
// caption text and the legend zones can't drift apart.
const TCHP_BANDS = [
  { to: 50, label: "Low", color: "#2f83b8" },
  { to: 100, label: "Moderate", color: "#e8c25e" },
  { to: 150, label: "High", color: "#ec8a44" },
  { to: 180, label: "Very high", color: "#df4a3a" },
];
function tchpCategory(v: number | null | undefined) {
  if (v == null || !Number.isFinite(v)) return null;
  return TCHP_BANDS.find((b) => v < b.to) || TCHP_BANDS[TCHP_BANDS.length - 1];
}
function ArcGauge({
  value, min, max, unit, zones, title,
}: {
  value: number | null | undefined; min: number; max: number; unit: string;
  zones: { to: number; color: string; label: string }[]; title: string;
}) {
  const cx = 100, cy = 100, r = 78, rNeedle = 62, strokeW = 20;
  const angleFor = (v: number) => 180 - (Math.max(min, Math.min(max, v)) - min) / (max - min) * 180;
  const pt = (deg: number, radius: number): [number, number] => {
    const rad = (deg * Math.PI) / 180;
    return [cx + radius * Math.cos(rad), cy - radius * Math.sin(rad)];
  };
  let from = min;
  const arcs = zones.map((z) => {
    const a1 = angleFor(from), a2 = angleFor(z.to);
    const [x1, y1] = pt(a1, r), [x2, y2] = pt(a2, r);
    from = z.to;
    return (
      <path key={z.label}
        d={`M${x1.toFixed(1)} ${y1.toFixed(1)} A${r} ${r} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`}
        fill="none" stroke={z.color} strokeWidth={strokeW} />
    );
  });
  const known = value != null && Number.isFinite(value);
  const [nx, ny] = pt(known ? angleFor(value as number) : 180, rNeedle);
  return (
    <svg viewBox="0 0 200 128" style={{ width: "100%", height: "auto" }} role="img" aria-label={title}>
      {arcs}
      {known && (
        <>
          <line x1={cx} y1={cy} x2={nx.toFixed(1)} y2={ny.toFixed(1)} stroke="#eef6fb" strokeWidth="3" strokeLinecap="round" />
          <circle cx={cx} cy={cy} r="5" fill="#eef6fb" />
        </>
      )}
      <text x={cx} y={cy + 24} textAnchor="middle" fontSize="22" fontWeight="700" fill="#eef6fb">
        {known ? Math.round(value as number) : "—"}
        <tspan fontSize="11" fontWeight="400" fill="#9ab8c8" dx="4">{unit}</tspan>
      </text>
    </svg>
  );
}
function Donut({ counts }: { counts: Record<string, number> }) {
  const states = ["Supported", "Caution", "Abstain"] as const;
  const colors: Record<string, string> = { Supported: "#37c871", Caution: "#e8c25e", Abstain: "#e2596b" };
  const total = states.reduce((s, k) => s + (counts?.[k] || 0), 0) || 1;
  const r = 54, c = 2 * Math.PI * r;
  let offset = 0;
  const supportedPct = Math.round(((counts?.Supported || 0) / total) * 100);
  return (
    <svg viewBox="0 0 140 140" width="140" height="140" role="img" aria-label="Reliability breakdown">
      <circle cx="70" cy="70" r={r} fill="none" stroke="#132a38" strokeWidth="18" />
      {states.map((k) => {
        const frac = (counts?.[k] || 0) / total;
        const dash = frac * c;
        const el = (
          <circle key={k} cx="70" cy="70" r={r} fill="none" stroke={colors[k]} strokeWidth="18"
            strokeDasharray={`${dash} ${c - dash}`} strokeDashoffset={-offset}
            transform="rotate(-90 70 70)" />
        );
        offset += dash;
        return el;
      })}
      <text x="70" y="66" textAnchor="middle" fontSize="22" fontWeight="700" fill="#eef6fb">{supportedPct}%</text>
      <text x="70" y="84" textAnchor="middle" fontSize="10" fill="#9ab8c8">Supported</text>
    </svg>
  );
}
function SeverityLadder({ category }: { category: string | null | undefined }) {
  const steps = [
    { label: "Moderate", color: "#e8c25e" },
    { label: "Strong", color: "#e8a24f" },
    { label: "Severe", color: "#e2793f" },
    { label: "Extreme", color: "#dd4a3a" },
  ];
  return (
    <div className="severity-scale">
      {steps.map((s) => (
        <div key={s.label}
          className={"severity-seg" + (category === s.label ? " active" : "")}
          style={category === s.label ? { background: s.color, borderColor: s.color } : undefined}>
          <span>{s.label}</span>
        </div>
      ))}
    </div>
  );
}

function SectionPlot({s,seafloor,isotherm,height=460}:any) {
  // Matched to the backend's exact convention (science.py field_diagnostics),
  // not just the boundary comparison. Two real discrepancies found by
  // reading the backend line by line rather than assuming this port was
  // faithful:
  //   1. Backend: surface already <26 degC -> d26 = 0.0 (a real, valid
  //      answer: the thermocline crossing is at the surface). This code
  //      returned null instead -- treating a valid "0m" result as no data.
  //   2. Backend: crosses at the first depth where t[i] <= 26 (inclusive).
  //      This code used `b<26` (exclusive), so a profile hitting exactly
  //      26.000 degC never registered a crossing here while the backend
  //      would report one, for that same exact case.
  const d26=s.distance.map((_:number,j:number)=>{
    if(s.z[0]?.[j]==null)return null;
    if(s.z[0][j]<26)return 0;
    for(let i=1;i<s.depths.length;i++) {
      const a=s.z[i-1][j], b=s.z[i][j];
      if(b==null)return null;
      if(b<=26)return a===b ? s.depths[i-1] : s.depths[i-1]+(26-a)/(b-a)*(s.depths[i]-s.depths[i-1]);
    }return null;
  });
  return <Plot height={height} data={[
    {type:"heatmap",x:s.distance,y:s.depths,z:s.z,colorscale:thermal,zmin:0,zmax:32,connectgaps:false,hoverongaps:false,colorbar:{title:{text:"°C"},thickness:12},hovertemplate:"%{x:.0f} km · %{y} m<br>%{z:.2f} °C<extra></extra>"},
    ...(seafloor?[{type:"scatter",x:[...s.distance,...s.distance.slice().reverse()],y:[...s.bathymetry.map((v:number)=>Math.min(1000,v)),...s.distance.map(()=>1000)],fill:"toself",fillcolor:"#344a59",mode:"lines",line:{color:"#93adba",width:1},name:"Seafloor",hoverinfo:"skip"}]:[]),
    ...(isotherm?[{type:"scatter",x:s.distance,y:d26,mode:"lines",line:{color:"#fff4ca",dash:"dash",width:2},name:"26°C isotherm · D26",connectgaps:false}]:[])
  ]} layout={{xaxis:{title:{text:"Distance along transect (km)"},gridcolor:"#244050"},yaxis:{title:{text:"Depth (m)"},range:[1000,0],gridcolor:"#244050"},margin:{l:65,r:35,t:15,b:75}}}/>;
}

export default function App() {
  const meta = useData("/runs", {});
  const [contrast, setContrast] = useState(false);
  const [textSize, setTextSize] = useState(100);
  const [infoPage, setInfoPage] = useState("");
  useEffect(()=>{const close=(ev:KeyboardEvent)=>{if(ev.key==="Escape")setInfoPage("")};window.addEventListener("keydown",close);return()=>window.removeEventListener("keydown",close)},[]);
  useEffect(()=>{
    if(!infoPage)return;
    const previous=document.activeElement as HTMLElement;
    const trap=(ev:KeyboardEvent)=>{
      if(ev.key!=="Tab")return;
      const items=Array.from(document.querySelectorAll<HTMLElement>('.info-dialog button, .info-dialog a'));
      if(!items.length)return;
      if(ev.shiftKey&&document.activeElement===items[0]){ev.preventDefault();items.at(-1)?.focus();}
      else if(!ev.shiftKey&&document.activeElement===items.at(-1)){ev.preventDefault();items[0].focus();}
    };
    document.addEventListener('keydown',trap);
    return()=>{document.removeEventListener('keydown',trap);previous?.focus();};
  },[infoPage]);
  const [endpoint, setEndpoint] = useState(1);
  const [showSeafloor, setShowSeafloor] = useState(true);
  const [showIsotherm, setShowIsotherm] = useState(true);
  const [mapMessage, setMapMessage] = useState("");
  useEffect(() => { document.documentElement.style.fontSize = `${16*textSize/100}px`; }, [textSize]);
  const [tab, setTab] = useState("Explore");
  const [date, setDate] = useState("");
  const [depth, setDepth] = useState(100);
  const [variable, setVariable] = useState("temperature");
  const [region, setRegion] = useState("Full domain");
  const [pos, setPos] = useState({ lat: 14, lon: 88 });
  const [play, setPlay] = useState(false);
  const [three, setThree] = useState(false);
  const [source, setSource] = useState("Argo");
  const [format, setFormat] = useState("netcdf");
  const [busy, setBusy] = useState(false);
  const [exportError, setExportError] = useState("");
  const [jobs, setJobs] = useState<any[]>([]);
  const [transect, setTransect] = useState({
    lat1: 14,
    lon1: 82,
    lat2: 17,
    lon2: 96,
  });
  const [showPrior, setShowPrior] = useState(true);
  const [showManifest, setShowManifest] = useState(false);
  const [showReliability, setShowReliability] = useState(true);
  const [showObservations, setShowObservations] = useState(true);
  const [wakeDepth, setWakeDepth] = useState(50);
  useEffect(() => {
    if (meta.data) {
      setDate(meta.data.dates[0]);
      const b = meta.data.bounds;
      setPos({ lat: (b[1] + b[3]) / 2, lon: (b[0] + b[2]) / 2 });
      setTransect({
        lat1: b[1] + (b[3] - b[1]) * 0.4,
        lon1: b[0] + (b[2] - b[0]) * 0.2,
        lat2: b[1] + (b[3] - b[1]) * 0.6,
        lon2: b[0] + (b[2] - b[0]) * 0.8,
      });
    }
  }, [meta.data]);
  const fieldVariable = tab === "Heat events" ? "anomaly" : tab === "Readiness" ? "tchp" : variable;
  const field = useData(
    "/field",
    { date, depth, var: fieldVariable, region },
    !!date && ["Explore", "Sections", "Heat events", "Exports", "Readiness"].includes(tab),
  );
  // Deliberately keyed on {var, depth} only -- NOT date -- so this does not
  // refetch (and therefore cannot change) when the user steps through
  // dates. That stability is the entire point: an earlier attempt computed
  // a percentile reference from whatever single frame was on screen, and
  // reverted after finding the same physical value could then render as a
  // different colour on a different date. Pooling across every date on
  // the backend (see /color-reference's own docstring) fixes that at the
  // source -- this hook just has to avoid re-deriving it per date on top.
  const colorRefSupported = useColorReferenceSupport();
  const colorReference = useData(
    "/color-reference",
    { var: fieldVariable, ...(fieldVariable in { tchp:1, d26:1, mld_t:1 } ? {} : { depth }) },
    colorRefSupported === true && !!date && ["Explore", "Sections", "Heat events", "Exports", "Readiness"].includes(tab),
  );
  // A SEPARATE reference, specifically for the 3D cutaway: that view spans
  // the full 0-1000m water column, not one depth level. Reproduced
  // directly: reusing the map's own single-depth (100m) reference here
  // meant real surface values (warm) ranked ABOVE anything ever seen at
  // 100m collapsed into one "hottest" bucket instead of spreading out --
  // a reference has to span the same range as what it's colouring.
  // `depth` deliberately omitted so the backend pools every depth.
  const cutawayColorReference = useData(
    "/color-reference",
    { var: "temperature" },
    colorRefSupported === true && tab === "Sections",
  );
  const profile = useData(
    "/profile",
    { date, ...pos },
    !!date && ["Explore", "Heat events", "Readiness"].includes(tab),
  );
  const section = useData(
    "/section",
    { date, ...transect, var: "temperature" },
    !!date && tab === "Sections",
  );
  const events = useData(
    "/events",
    { ...pos, depth },
    !!date && ["Heat events", "Readiness"].includes(tab),
  );
  const validation = useData("/validation", { source }, tab === "Validate");
  const baselines = useData("/baselines", {}, tab === "Validate");
  const cyclone = useData("/cyclone/context", {}, ["Heat events", "Readiness"].includes(tab));
  const wake = useData("/cyclone/cold-wake", {}, tab === "Heat events");
  useEffect(() => {
    if (!play || !meta.data || tab !== "Explore" || field.loading || profile.loading || field.error || profile.error) return;
    const id = setTimeout(() => setDate((d) => meta.data.dates[(meta.data.dates.indexOf(d) + 1) % meta.data.dates.length]), 1100);
    return () => clearTimeout(id);
  }, [play, meta.data, tab, date, field.loading, profile.loading, field.error, profile.error]);
  const mode = meta.data?.source_mode;
  // The export endpoint accepts temperature and anomaly only, and has no
  // native values at 1000 m. Say so before the click instead of failing after.
  const exportBlock =
    variable === "tchp" || variable === "d26" || variable === "mld_t"
      ? "Downloads cover Temperature and Anomaly. Switch the variable above to export."
      : format === "png" && depth === 1000
        ? "1000 m has no native values, so this map would be empty. Choose 700 m or shallower for a PNG."
        : "";
  const synthetic = mode === "synthetic";
  const title =
    tab === "Explore"
      ? "Explore the ocean beneath"
      : tab === "Sections"
        ? "See beneath the surface"
        : tab === "Heat events"
          ? "Track persistent ocean warming"
          : tab === "Validate"
            ? "Evidence behind every estimate"
            : tab === "Readiness"
              ? "Disaster readiness & awareness"
              : "Take the science with you";
  const subtitle =
    tab === "Explore"
      ? "Inspect thermal structure, one profile at a time."
      : tab === "Sections"
        ? "Follow a transect through the water column."
        : tab === "Heat events"
          ? "Examine persistence and the baseline behind each event."
          : tab === "Validate"
            ? "Compare estimates with their declared reference."
            : tab === "Readiness"
              ? "Ocean heat context and public preparedness guidance — not a forecast."
              : "Export the selection with its scientific context.";
  const f = field.data,
    p = profile.data,
    s = section.data,
    e = events.data,
    v = validation.data;
  // Reproduced directly (this session): useData() calls setData(null) the
  // instant its params change, BEFORE the new request resolves -- so `f`
  // (field.data) goes null on every single date/variable/depth/region
  // change, and {f && <OceanMap/>} below fully unmounts the map each time.
  // Unmounting destroys all of OceanMap's own internal state (zoom, pan),
  // so panning in, then changing the date, silently snapped back to the
  // default view -- "an active map disappeared during loading, resetting
  // zoom". Fixed by keeping the last successfully loaded field around and
  // rendering THAT while a new request is in flight, so OceanMap stays
  // mounted continuously and its zoom/pan survive the reload. The
  // displayed data still updates the moment the new fetch resolves (this
  // ref is overwritten then); this only smooths over the null gap in
  // between, it does not show genuinely stale data once loading finishes.
  const lastGoodField = useRef<any>(null);
  if (f) lastGoodField.current = f;
  const mapField = displayFieldFor(f || lastGoodField.current);
  const estimatedActive = isDisplayEstimate(f || lastGoodField.current);
  // Clear the persisted field when the TAB itself changes, not just when
  // date/variable/depth/region change within one tab: without this, the
  // brief null gap after switching tabs (e.g. Explore -> Heat events)
  // would show the PREVIOUS tab's last map until the new tab's own data
  // arrives, which is a different and worse problem than the one this
  // persistence exists to fix.
  useEffect(() => { lastGoodField.current = null; }, [tab]);
  const latestEvent = e?.events?.length ? e.events[e.events.length - 1] : null;
  const cyclonePoints: any[] = cyclone.data?.points || [];
  const tchpAlongTrack = cyclonePoints
    .map((q) => q.tchp_kj_cm2)
    .filter((val) => val != null && Number.isFinite(val));
  const peakTrackTchp = tchpAlongTrack.length ? Math.max(...tchpAlongTrack) : null;
  const selectPoint = (q: {lat:number;lon:number}) => {
    const b=meta.data?.bounds;
    if(!b || q.lon<b[0] || q.lon>b[2] || q.lat<b[1] || q.lat>b[3]) {
      setMapMessage("Outside this run’s coverage. Select a point inside the coloured grid."); return;
    }
    setMapMessage(""); setPos(q);
  };
  const map = (height = 560) => <><Load state={field}/>{estimatedActive && <div className="estimate-banner" role="status"><strong>{mapField.estimate_badge}</strong><span>Not a native model reconstruction · reliability N/A</span></div>}{mapField && <OceanMap field={mapField} pos={pos} onSelect={selectPoint} reliability={showReliability && !estimatedActive} showObservations={showObservations} mode={fieldVariable} colorReference={colorReference.data?.reference} height={height} track={tab === "Heat events" ? cyclone.data?.points || [] : []}/>}{estimatedActive && <Notice>{mapField.estimated_note}</Notice>}<span className="map-message" role="status">{mapMessage}</span></>;
  const controls = (
    <>
      <Field label="Date">
        <select value={date} onChange={(ev) => setDate(ev.target.value)}>
          {meta.data?.dates.map((d) => <option key={d}>{d}</option>)}
        </select>
      </Field>
      <Field label="Variable">
        <select
          value={variable}
          onChange={(ev) => setVariable(ev.target.value)}
        >
          <option value="temperature">Temperature</option>
          <option value="anomaly">Temperature anomaly</option>
          <option value="tchp">TCHP (cyclone heat potential)</option>
          <option value="d26">D26 (26°C isotherm depth)</option>
          <option value="mld_t">MLD-T (mixed-layer depth)</option>
        </select>
      </Field>
      <Field label="Depth">
        <select
          value={depth}
          onChange={(ev) => setDepth(+ev.target.value)}
          disabled={DEPTH_INDEPENDENT.has(variable)}
        >
          {meta.data?.depths.map((z) => (
            <option key={z} value={z}>
              {depthOptionLabel(z)}
            </option>
          ))}
        </select>
        {DEPTH_INDEPENDENT.has(variable) && (
          <p className="muted small field-note">
            Whole-column diagnostic — the same at every depth on the slider.
          </p>
        )}
      </Field>
      <Field label="Region">
        <select value={region} onChange={(ev) => setRegion(ev.target.value)}>
          {["Full domain", "Bay of Bengal", "Arabian Sea"].map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
      </Field>
      <Field label="Layers">
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={showReliability}
            onChange={(ev) => setShowReliability(ev.target.checked)}
          />
          <span>Reliability overlay</span>
        </label>
        <label className="toggle-row" title={
          // Reproduced directly: /field never returns an `argo_floats` key
          // at all -- OceanMap.tsx's `argoFloats` is therefore always [],
          // so this toggle has been fully interactive with zero backing
          // data since it was added. Disabling it (rather than leaving a
          // toggle that silently does nothing, or inventing float
          // positions to make it "work") is the honest fix: fabricated
          // observation points would look like real ground-truth data on
          // a research tool, which is worse than an inert control. The
          // condition below re-enables it automatically the moment
          // /field genuinely starts returning float positions -- nothing
          // else needs to change when that happens.
          (f?.argo_floats?.length ?? 0) > 0 ? undefined : 'No Argo observation data available for this run'
        }>
          <input
            type="checkbox"
            checked={showObservations && (f?.argo_floats?.length ?? 0) > 0}
            disabled={(f?.argo_floats?.length ?? 0) === 0}
            onChange={(ev) => setShowObservations(ev.target.checked)}
          />
          <span>Observations (Argo){(f?.argo_floats?.length ?? 0) === 0 ? ' (none in this run)' : ''}</span>
        </label>
      </Field>
      {showReliability && estimatedActive && (
        <div className="reliability-key">
          <p className="reliability-key-note">
            Reliability: N/A. The 1000 m layer is a display estimate carried
            from 700 m, outside native source support (~902 m); the
            reliability gate does not apply to it.
          </p>
        </div>
      )}
      {showReliability && !estimatedActive && f?.reliability_summary && (
        <div className="reliability-key">
          {(["Supported", "Caution", "Abstain"] as const).map((state) => {
            const n = f.reliability_summary.counts?.[state] ?? 0;
            return (
              <div className="reliability-key-row" key={state}>
                <span
                  className={`reliability-swatch state-${state.toLowerCase()}`}
                  aria-hidden="true"
                />
                <span className="reliability-key-label">{state}</span>
                <span className="reliability-key-count">
                  {n.toLocaleString()}
                </span>
              </div>
            );
          })}
          <p className="reliability-key-note">
            Support for the estimate — not a danger level. Stale or
            edge-of-domain inputs read Caution; land, seabed and unsupported
            depths abstain.
          </p>
        </div>
      )}
    </>
  );
  async function download() {
    if (exportBlock) return;
    setBusy(true);
    setExportError("");
    try {
      const r = await fetch(
        "/api/export?" +
          new URLSearchParams({
            date,
            format,
            depth: String(depth),
            var: variable,
            lat: String(pos.lat),
            lon: String(pos.lon),
          }),
      );
      if (!r.ok) throw Error((await r.json()).detail);
      const blob = await r.blob();
      const u = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = u;
      a.download = `oceanembed-${date}.${format === "netcdf" ? "nc" : format}`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(u), 3000);
      setJobs((j) => [{ date, format, size: blob.size }, ...j].slice(0, 8));
    } catch (err: any) {
      setExportError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={"shell" + (contrast ? " high-contrast" : "")}>
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <div className="masthead"><span>SIH 2026 · Team DeepSindhu research prototype</span><span>Problem context: Ministry of Earth Sciences (MoES) · INCOIS</span><div className="access-tools"><button aria-label="Decrease text size" onClick={()=>setTextSize(v=>Math.max(100,v-10))}>A−</button><button aria-label="Reset text size" onClick={()=>setTextSize(100)}>A</button><button aria-label="Increase text size" onClick={()=>setTextSize(v=>Math.min(150,v+10))}>A+</button><button aria-pressed={contrast} onClick={()=>setContrast(v=>!v)}>High contrast</button></div></div>
      <header>
        <div className="brand">
          <img className="brand-mark" src="/oceanembed-mark.png" alt="" aria-hidden="true" />
          <div>
            OceanEmbed<small>for Team DeepSindhu</small>
          </div>
        </div>
        <nav aria-label="Main views">
          {tabs.map((name, i) => {
            const Icon = icons[i];
            return (
              <button
                key={name}
                aria-current={tab === name ? "page" : undefined}
                className={tab === name ? "active" : ""}
                onClick={() => {
                  setTab(name);
                  setPlay(false);
                }}
              >
                <Icon size={17} />
                {name}
              </button>
            );
          })}
        </nav>
        <span className={"badge data-mode-badge " + (synthetic ? "amber" : "")}>
          <span className="data-mode-label">
            {synthetic
              ? "DEMO · Synthetic data"
              : mode === "satellite_observation"
                ? "Strict satellite"
                : mode === "research_blended"
                  ? "Research-blended"
                  : "Research reconstruction"}
          </span>
          {meta.data?.freshness && (
            <span className="data-mode-freshness">
              Inputs as old as {Math.round(meta.data.freshness.oldest_input_hours)}h,
              as of {meta.data.freshness.as_of_date}
            </span>
          )}
        </span>
      </header>
      <main id="main-content" tabIndex={-1}>
        <div className="heading">
          <div>
            <p className="eyebrow">NORTH INDIAN OCEAN / THERMAL WORKSPACE</p>
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          <span className="run-chip">
            <Activity size={16} />
            15 depth levels · retrospective
          </span>
        </div>
        <Load state={meta} />
        {!meta.data && (
          <Notice>
            Start the Python backend and create the demo run using
            START_HERE.md.
          </Notice>
        )}
        {meta.data && (
          <>
            {tab === "Explore" && (
              <>
                <div className="explore-grid">
                  <aside className="panel filters">
                    <h3>
                      <SlidersHorizontal size={17} /> Selection
                    </h3>
                    {controls}
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={showPrior}
                        onChange={(ev) => setShowPrior(ev.target.checked)}
                      />
                      Show climatology
                    </label>
                    <Notice>
                      {synthetic
                        ? "Synthetic temperatures and bathymetry. Natural Earth basemap provides geographic context only."
                        : "Missing cells remain blank. Profiles are nearest-grid samples."}
                    </Notice>
                  </aside>
                  <Panel
                    title={
                      DEPTH_INDEPENDENT.has(variable)
                        ? VARIABLE_TITLE[variable]
                        : `${variable === "anomaly" ? "Temperature anomaly" : "Sea temperature"} · ${depth} m`
                    }
                    sub={date}
                  >
                    {map()}
                  </Panel>
                  <aside className="profile-stack">
                    <Panel
                      title="Selected profile"
                      sub={`${placeName(pos)} · ${fmt(pos.lat)}° N, ${fmt(pos.lon)}° E`}
                    >
                      <div className="coordinate-pair"><Field label="Latitude °N"><input type="number" step="0.25" value={Number(pos.lat.toFixed(3))} onChange={ev=>selectPoint({...pos,lat:+ev.target.value})}/></Field><Field label="Longitude °E"><input type="number" step="0.25" value={Number(pos.lon.toFixed(3))} onChange={ev=>selectPoint({...pos,lon:+ev.target.value})}/></Field></div>
                      <Load state={profile} />
                      {p && (
                        <>
                          <Plot
                            height={390}
                            data={[
                              ...(p.lower && p.upper
                                ? [
                                    {
                                      x: p.lower,
                                      y: p.depths,
                                      type: "scatter",
                                      mode: "lines",
                                      line: { width: 0 },
                                      showlegend: false,
                                      hoverinfo: "skip",
                                    },
                                    {
                                      x: p.upper,
                                      y: p.depths,
                                      type: "scatter",
                                      mode: "lines",
                                      line: { width: 0 },
                                      fill: "tonextx",
                                      fillcolor: "rgba(82,217,240,0.18)",
                                      name: "Empirical interval",
                                    },
                                  ]
                                : []),
                              {
                                x: p.temperature,
                                y: p.depths,
                                type: "scatter",
                                mode: "lines+markers",
                                line: { color: "#52d9f0", width: 3 },
                                marker: { size: 4 },
                                name: synthetic
                                  ? "Synthetic estimate"
                                  : "Model estimate",
                              },
                              ...(showPrior
                                ? [
                                    {
                                      x: p.prior,
                                      y: p.depths,
                                      type: "scatter",
                                      line: { color: "#97a7b8", dash: "dot" },
                                      name: "Climatology",
                                    },
                                  ]
                                : []),
                            ]}
                            layout={{
                              xaxis: {
                                title: { text: "Temperature (°C)" },
                                gridcolor: "#203b4d",
                              },
                              yaxis: {
                                title: { text: "Depth (m)" },
                                range: [1000, 0],
                                gridcolor: "#203b4d",
                              },
                            }}
                          />
                          <div className="mini-stats">
                            <span>
                              D26
                              <strong>{fmt(p.diagnostics.d26_m, 1)} m</strong>
                            </span>
                            <span>
                              MLD-T
                              <strong>{fmt(p.diagnostics.mld_t_m, 1)} m</strong>
                            </span>
                          </div>
                          {p.reliability && (
                            <div className="reliability-readout">
                              <div className="reliability-headline">
                                <span
                                  className={`reliability-swatch state-${p.reliability.overall.toLowerCase()}`}
                                  aria-hidden="true"
                                />
                                <strong>{p.reliability.overall}</strong>
                                <span className="muted">
                                  {p.reliability.depths_reporting}/
                                  {p.reliability.depths_total} depths reporting
                                </span>
                              </div>
                              <p className="muted small">
                                {p.reliability.calibration_applies
                                  ? "Calibrated interval applies at reporting depths."
                                  : "No calibrated interval on this run — the state describes input support only."}
                              </p>
                              {p.reliability.per_depth?.some(
                                (d: any) => d.state !== "Supported",
                              ) && (
                                <ul className="reliability-reasons">
                                  {Array.from(
                                    new Map(
                                      p.reliability.per_depth
                                        .filter((d: any) => d.state !== "Supported")
                                        .map((d: any) => [d.reason_code, d]),
                                    ).values(),
                                  ).map((d: any) => (
                                    <li key={d.reason_code}>
                                      <span
                                        className={`reliability-swatch state-${d.state.toLowerCase()}`}
                                        aria-hidden="true"
                                      />
                                      {d.reason}
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </div>
                          )}
                        </>
                      )}
                    </Panel>
                    <Panel title="Source coverage">
                      <p className="muted">{synthetic ? "Demonstration run · satellite and Argo observations are not loaded." : p?.status || "Inspect the source manifest for coverage and freshness."}</p>
                      <button
                        className="text-button"
                        onClick={() => setShowManifest(!showManifest)}
                      >
                        View sources <ChevronRight size={16} />
                      </button>
                      {showManifest && (
                        <pre>{JSON.stringify(meta.data.manifest, null, 2)}</pre>
                      )}
                    </Panel>
                  </aside>
                </div>
                <div className="timeline panel">
                  <button
                    className="round"
                    onClick={() => setPlay(!play)}
                    aria-label={play ? "Pause playback" : "Play dates"}
                  >
                    {play ? <Pause /> : <Play />}
                  </button>
                  <span>{meta.data.dates[0]}</span>
                  <input
                    aria-label="Date timeline"
                    type="range"
                    min="0"
                    max={meta.data.dates.length - 1}
                    value={meta.data.dates.indexOf(date)}
                    onChange={(ev) =>
                      setDate(meta.data.dates[+ev.target.value])
                    }
                  />
                  <strong>{date}</strong>
                  <span>{meta.data.dates.at(-1)}</span>
                </div>
              </>
            )}
            {tab === "Sections" && (
              <>
                <div className="toolbar panel">
                  <Field label="Date">
                    <select
                      value={date}
                      onChange={(ev) => setDate(ev.target.value)}
                    >
                      {meta.data.dates.map((d) => (
                        <option key={d}>{d}</option>
                      ))}
                    </select>
                  </Field>
                  {Object.keys(transect).map((k) => (
                    <Field
                      key={k}
                      label={k.replace("1", " A").replace("2", " B")}
                    >
                      <input
                        type="number"
                        step="0.25"
                        value={transect[k]}
                        onChange={(ev) =>
                          setTransect({ ...transect, [k]: +ev.target.value })
                        }
                      />
                    </Field>
                  ))}
                  <button
                    className={!three ? "selected" : ""}
                    onClick={() => setThree(false)}
                  >
                    <Layers size={17} />
                    Cross-section
                  </button>
                  <button
                    className={three ? "selected" : ""}
                    onClick={() => setThree(true)}
                  >
                    <Box size={17} />
                    3D cutaway
                  </button>
                </div>
                <div className="section-hero">
                  <Panel title="Draw your transect" sub="Select endpoints on the map">
                    <Locator transect={transect} />
                    <div className="transect-facts">
                      <span>From<strong>{fmt(transect.lat1)}°N, {fmt(transect.lon1)}°E</strong></span>
                      <span>To<strong>{fmt(transect.lat2)}°N, {fmt(transect.lon2)}°E</strong></span>
                      <span>Length<strong>{s?fmt(s.distance.at(-1),0):"—"} km</strong></span>
                    </div>
                    <div className="endpoint-controls">{[1,2].map(n=><button key={n} className={endpoint===n?"selected":""} onClick={()=>setEndpoint(n)}>Set {n===1?"A":"B"}</button>)}</div>
                    <OceanMap height={300} transect={transect} onSelect={q=>{
                      const b=meta.data.bounds;
                      if(q.lon<b[0]||q.lon>b[2]||q.lat<b[1]||q.lat>b[3]){setMapMessage("Choose an endpoint within the run domain.");return;}
                      setMapMessage("");setTransect({...transect,[`lat${endpoint}`]:+q.lat.toFixed(3),[`lon${endpoint}`]:+q.lon.toFixed(3)});setEndpoint(endpoint===1?2:1);
                    }}/><p role="status" className="muted">{mapMessage || `Click the map to place ${endpoint===1?"A":"B"}. Coordinates can also be edited above.`}</p>
                    <label className="toggle-row"><input type="checkbox" checked={showSeafloor} onChange={ev=>setShowSeafloor(ev.target.checked)}/>Seafloor mask</label>
                    <label className="toggle-row"><input type="checkbox" checked={showIsotherm} onChange={ev=>setShowIsotherm(ev.target.checked)}/>26°C isotherm</label>
                  </Panel>
                  <Panel title={three?"Ocean cutaway · Transect A–B":"Temperature along transect"} sub={synthetic?"Illustrative data · not measured ocean conditions":"Research reconstruction"}>
                    <Load state={section}/>
                    {/* Reproduced directly: `section` (the transect data itself)
                        and `cutawayColorReference` (the percentile colour table
                        the 3D cutaway needs for its rich full-column look) are
                        two independent fetches with no ordering guarantee.
                        `s` used to gate on `section` alone, so whenever
                        `section` resolved first, Cutaway rendered immediately
                        with whatever colorReference had -- usually still null
                        -- falling back to a flat, skewed linear scale that
                        reads as "mostly blue" on real data (deep water's real
                        variance is tiny, so it needs percentile ranking to
                        look rich). Gating the 3D view on both requests having
                        settled removes that flash; the 2D SectionPlot doesn't
                        use colorReference at all, so it isn't held back. */}
                    {s && (three
                      ? (colorRefSupported === null || cutawayColorReference.loading
                          ? <div className="empty">Loading colour reference…</div>
                          : <Cutaway section={s} seafloor={showSeafloor} colorReference={cutawayColorReference.data?.reference}/>)
                      : <SectionPlot s={s} seafloor={showSeafloor} isotherm={showIsotherm}/>)}
                  </Panel>
                </div>
                {three && s && <Panel title="Temperature along transect" sub="Distance × depth · quantitative cross-section"><SectionPlot s={s} seafloor={showSeafloor} isotherm={showIsotherm} height={340}/></Panel>}
                <Notice>Native depth samples; no interpolation across missing layers or land. D26 is shown only where a valid surface-connected 26°C crossing can be identified. Seafloor deeper than 1000 m lies outside this view.</Notice>
              </>
            )}
            {tab === "Heat events" && (
              <>
                <div className="events-grid">
                  <aside className="panel filters">
                    {controls}
                    <Notice>
                      Events require at least five consecutive daily exceedances
                      of the supplied seasonal threshold.
                    </Notice>
                  </aside>
                  <Panel
                    title={`Temperature anomaly context · ${depth} m`}
                    sub="Click to inspect a location"
                  >
                    {map(400)}
                  </Panel>
                  <Panel
                    title="Selected location"
                    sub={`${placeName(pos)} · ${fmt(pos.lat)}° N, ${fmt(pos.lon)}° E`}
                  >
                    <Load state={events} />
                    <p className="muted">{e?.status}</p>
                    {e?.events.map((ev, i) => (
                      <div className="event-card" key={i}>
                        <Flame color="#ef9674" />
                        <h3>{ev.category}</h3>
                        <p>
                          {ev.start} – {ev.end}
                        </p>
                        <div className="mini-stats">
                          <span>
                            Duration<strong>{ev.duration_days} days</strong>
                          </span>
                          <span>
                            Peak anomaly
                            <strong>+{fmt(ev.peak_anomaly)} °C</strong>
                          </span>
                        </div>
                      </div>
                    ))}
                    {e && !e.events.length && (
                      <p className="empty">
                        No qualifying events in the available series.
                      </p>
                    )}
                    <button
                      className="primary"
                      onClick={() => setTab("Explore")}
                    >
                      Inspect profile <ChevronRight size={17} />
                    </button>
                    <Notice>
                      Ocean thermal context only. No cyclone intensification
                      forecast is produced.
                    </Notice>
                  </Panel>
                </div>
                {e && (
                  <Panel
                    title="Temperature at selected location"
                    sub={`${depth} m`}
                  >
                    <Plot
                      height={290}
                      data={[
                        {
                          x: e.dates,
                          y: e.temperature,
                          type: "scatter",
                          name: "Temperature",
                          line: { color: "#49d9eb" },
                        },
                        ...(e.threshold
                          ? [
                              {
                                x: e.dates,
                                y: e.threshold,
                                type: "scatter",
                                name: "90th-percentile threshold",
                                line: { color: "#f2c77b", dash: "dash" },
                              },
                            ]
                          : []),
                      ]}
                      layout={{
                        yaxis: {
                          title: { text: "Temperature (°C)" },
                          gridcolor: "#203b4d",
                        },
                      }}
                    />
                  </Panel>
                )}
                <Panel
                  title="Cyclone thermal context"
                  sub="Retrospective best track over reconstructed upper-ocean heat"
                >
                  <Load state={cyclone} />
                  {cyclone.data?.available ? (
                    <>
                      <div className="cyclone-headline">
                        <strong>{cyclone.data.name}</strong>
                        <span className="muted">
                          {cyclone.data.points_with_thermal_context} of{" "}
                          {cyclone.data.points_total} track points have thermal
                          context
                        </span>
                        {cyclone.data.category_scheme && (
                          <span className="pill">
                            {cyclone.data.category_scheme} categories
                          </span>
                        )}
                      </div>
                      <Plot
                        height={330}
                        data={[
                          {
                            x: cyclone.data.points.map((q: any) => q.datetime),
                            y: cyclone.data.points.map((q: any) => q.tchp_kj_cm2),
                            type: "scatter",
                            mode: "lines+markers",
                            name: "TCHP (kJ/cm²)",
                            line: { color: "#f2854c", width: 2 },
                            connectgaps: false,
                          },
                          {
                            x: cyclone.data.points.map((q: any) => q.datetime),
                            y: cyclone.data.points.map((q: any) => q.d26_m),
                            type: "scatter",
                            mode: "lines+markers",
                            name: "D26 (m)",
                            yaxis: "y2",
                            line: { color: "#52d9f0", width: 2 },
                            connectgaps: false,
                          },
                        ]}
                        layout={{
                          xaxis: { title: { text: "Track time (UTC)" }, gridcolor: "#203b4d" },
                          yaxis: {
                            title: { text: "TCHP (kJ/cm²)" },
                            gridcolor: "#203b4d",
                          },
                          yaxis2: {
                            title: { text: "D26 (m)" },
                            overlaying: "y",
                            side: "right",
                            autorange: "reversed",
                          },
                        }}
                      />
                      <Notice>{cyclone.data.limits}</Notice>
                    </>
                  ) : (
                    <div className="empty tall">
                      <Activity size={36} />
                      <p>
                        {cyclone.data?.note || "No cyclone context loaded."}
                      </p>
                      <span>
                        Build one with the cyclone-context CLI command from an
                        official IMD/RSMC best track, then set OCEAN_CYCLONE.
                      </span>
                    </div>
                  )}
                </Panel>
                <Panel
                  title="Pre/post-passage change"
                  sub="Matched windows either side of passage"
                >
                  <Load state={wake} />
                  {wake.data?.available ? (
                    <>
                      <div className="cyclone-headline">
                        <strong>
                          {wake.data.mean_change_degC === null
                            ? "No complete windows"
                            : `${fmt(wake.data.mean_change_degC, 2)} °C mean change`}
                        </strong>
                        <span className="muted">
                          {wake.data.locations_with_complete_windows} of{" "}
                          {wake.data.locations_total} locations, {wake.data.depth} m,
                          ±{wake.data.window_days}-day windows
                        </span>
                      </div>
                      <Plot
                        height={300}
                        data={[
                          {
                            x: wake.data.records.map((r: any) => r.passage_date),
                            y: wake.data.records.map((r: any) => r.change_degC),
                            type: "bar",
                            name: "Change (°C)",
                            marker: {
                              color: wake.data.records.map((r: any) =>
                                r.change_degC === null
                                  ? "#44566a"
                                  : r.change_degC < 0
                                    ? "#52a8f0"
                                    : "#f2854c",
                              ),
                            },
                          },
                        ]}
                        layout={{
                          xaxis: { title: { text: "Passage date" }, gridcolor: "#203b4d" },
                          yaxis: {
                            title: { text: "After − before (°C)" },
                            gridcolor: "#203b4d",
                            zerolinecolor: "#4a6076",
                          },
                        }}
                      />
                      <Notice>{wake.data.limits}</Notice>
                    </>
                  ) : (
                    <div className="empty tall">
                      <Activity size={36} />
                      <p>{wake.data?.note || "No cold-wake diagnostic loaded."}</p>
                      <span>
                        Build one with the cold-wake CLI command, then set
                        OCEAN_COLD_WAKE.
                      </span>
                    </div>
                  )}
                </Panel>
              </>
            )}
            {tab === "Validate" && (
              <>
                <div className="toolbar panel">
                  <span>Observation source</span>
                  {["Argo", "RAMA", "Reanalysis"].map((x) => (
                    <button
                      key={x}
                      className={source === x ? "selected" : ""}
                      onClick={() => setSource(x)}
                    >
                      {x}
                    </button>
                  ))}
                  <span className="push muted">
                    {v?.partition || "No evaluation loaded"}
                  </span>
                </div>
                <Load state={validation} />
                <Notice>{v?.note || "No validation result loaded."}</Notice>
                {v?.metrics?.length > 0 ? (
                  <div className="validation-grid">
                    <Panel title="Error by depth" sub={`${v.source} · RMSE`}>
                      <Plot
                        height={390}
                        data={["climatology", "model"]
                          // Only draw a series the evaluation actually contains, so
                          // the legend never promises a comparison that isn't there.
                          .filter((k) => v.metrics.some((r: any) => Number.isFinite(r[k]?.rmse)))
                          .map((k) => ({
                          x: v.metrics.map((r) => r[k]?.rmse),
                          y: v.metrics.map((r) => r.depth),
                          type: "scatter",
                          mode: "lines+markers",
                          name:
                            k === "model"
                              ? synthetic
                                ? "Synthetic estimate"
                                : "OceanEmbed"
                              : "Climatology",
                          line: { color: k === "model" ? "#51d8eb" : "#b8c3d0", width: 2 },
                        }))}
                        layout={{
                          xaxis: { title: { text: "RMSE (°C)" }, gridcolor: "#203b4d" },
                          yaxis: {
                            title: { text: "Depth (m)" },
                            range: [1000, 0],
                            gridcolor: "#203b4d",
                          },
                        }}
                      />
                    </Panel>
                    <Panel
                      title="Baseline comparison"
                      sub="Reanalysis target · not observational skill"
                    >
                      <Load state={baselines} />
                      {baselines.data?.available ? (
                        <>
                          <Plot
                            height={390}
                            data={[
                              ["climatology", "Climatology", "#b8c3d0"],
                              ["persistence", "Persistence", "#f0a868"],
                              ["ridge", "Ridge regression", "#9b8cf0"],
                            ].map(([k, label, color]) => ({
                              x: baselines.data.metrics.map(
                                (r: any) => r[k as string]?.rmse,
                              ),
                              y: baselines.data.metrics.map((r: any) => r.depth),
                              type: "scatter",
                              mode: "lines+markers",
                              name: label,
                              line: { color, width: 2 },
                              connectgaps: false,
                            }))}
                            layout={{
                              xaxis: { title: { text: "RMSE (°C)" }, gridcolor: "#203b4d" },
                              yaxis: {
                                title: { text: "Depth (m)" },
                                range: [1000, 0],
                                gridcolor: "#203b4d",
                              },
                            }}
                          />
                          <p className="muted small">{baselines.data.note}</p>
                        </>
                      ) : (
                        <div className="empty tall">
                          <Activity size={36} />
                          <p>
                            "No baseline evaluation is available for this workspace."
                          </p>
                          <span>
                            Load an evaluated baseline artifact to compare the three reference methods.
                          </span>
                        </div>
                      )}
                    </Panel>
                    <Panel
                      title="Predicted vs observed"
                      sub="Matched observational records"
                    >
                      {v.matchups?.length ? (
                        <Plot
                          height={390}
                          data={[
                            {
                              x: observationScatter(v).x,
                              y: observationScatter(v).y,
                              type: "scatter",
                              mode: "markers",
                              marker: { size: 4, color: "#53d7ed" },
                              name: observationScatter(v).name,
                            },
                            {
                              x: [0, 32],
                              y: [0, 32],
                              type: "scatter",
                              mode: "lines",
                              line: { dash: "dash", color: "#b1bdcb" },
                              name: "1:1",
                            },
                          ]}
                          layout={{
                            xaxis: { title: { text: "Observed (°C)" } },
                            yaxis: { title: { text: "Predicted (°C)" } },
                          }}
                        />
                      ) : (
                        <div className="empty tall">
                          <ShieldCheck size={36} />
                          <p>No observational matchups loaded.</p>
                          <span>
                            Synthetic reference scores appear only in the
                            labelled reference view.
                          </span>
                        </div>
                      )}
                    </Panel>
                    <Panel title="Per-depth scorecard">
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Depth</th>
                              <th>RMSE</th>
                              <th>Bias</th>
                              <th>Matched values</th>
                            </tr>
                          </thead>
                          <tbody>
                            {v.metrics.map((r) => (
                              <tr key={r.depth}>
                                <td>{r.depth} m</td>
                                <td>{fmt(r.model.rmse)}</td>
                                <td>{fmt(r.model.bias)}</td>
                                <td>{r.model.n}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </Panel>
                    <Panel title="Evaluation provenance">
                      <pre>
                        {JSON.stringify(
                          {
                            source: v.source,
                            partition: v.partition,
                            group: v.group,
                            float_ids: v.float_ids || [],
                            mooring_ids: v.mooring_ids || [],
                            run_sha256: v.run_sha256,
                            note: v.note,
                          },
                          null,
                          2,
                        )}
                      </pre>
                    </Panel>
                  </div>
                ) : (
                  <>
                    <div className="evidence-summary panel"><ShieldCheck size={32}/><div><h3>Ready for evidence. No measured result loaded.</h3><p className="muted">The selected run has no {source} evaluation. Results appear here after observational matching and holdout evaluation.</p></div><span className="badge amber">Not yet validated</span></div>
                    <div className="validation-grid evidence-grid">
                      <Panel title="Error by depth" sub="RMSE · 15 output depths"><div className="evidence-placeholder"><Activity size={38}/><strong>Depth-resolved accuracy</strong><p>RMSE and bias will be computed from the selected evaluation. No placeholder accuracy is displayed.</p></div></Panel>
                      <Panel title="Predicted vs observed" sub={`${source} · held-out matchups`}><div className="evidence-placeholder"><ShieldCheck size={38}/><strong>Independent observations required</strong><p>Pair supported reconstructions with quality-controlled profiles, then evaluate unseen floats or moorings.</p></div></Panel>
                      <Panel title="Baseline comparison" sub="Climatology · persistence · ridge"><div className="baseline-status">{["Climatology","Persistence","Ridge regression","OceanEmbed-NIO"].map((name,i)=><div key={name}><span className={`baseline-dot dot-${i}`}/><strong>{name}</strong><span>Awaiting evaluation</span></div>)}</div><p className="muted">Compare the same reference and held-out partition. Persistence may have fewer samples; inspect counts before comparing scores.</p></Panel>
                      <Panel title="Evaluation provenance" sub="Reproducibility comes first"><div className="provenance-cards"><span>Observation source<strong>{source}</strong></span><span>Partition<strong>Not loaded</strong></span><span>Measured matchups<strong>—</strong></span><span>Model accuracy<strong>Not established</strong></span></div><button className="text-button" onClick={()=>setInfoPage("Data sources")}>About the data <ChevronRight size={16}/></button></Panel>
                    </div>
                  </>
                )}
              </>
            )}
            {tab === "Exports" && (
              <>
                <div className="export-grid">
                  <Panel
                    title="Build an export"
                    sub="The selected run remains attached to every result."
                  >
                    <div className="step-title">
                      <b>1</b>
                      <h3>Select data</h3>
                    </div>
                    <div className="export-controls">{controls}</div>
                    <div className="step-title">
                      <b>2</b>
                      <h3>Choose format</h3>
                    </div>
                    <div className="format-grid">
                      {[
                        ["netcdf", "NetCDF", "All 15 depths for this date"],
                        ["csv", "CSV", "Temperature profile at the selected point"],
                        ["png", "PNG", "Selected depth map"],
                      ].map(([k, t, d]) => (
                        <button
                          key={k}
                          className={
                            "format " + (format === k ? "selected" : "")
                          }
                          onClick={() => setFormat(k)}
                        >
                          <FileText size={26} />
                          <strong>{t}</strong>
                          <small>{d}</small>
                        </button>
                      ))}
                    </div>
                    <p className="muted">
                      NetCDF contains the full run domain for the selected date.
                      CSV uses {fmt(pos.lat)}° N, {fmt(pos.lon)}° E. PNG uses{" "}
                      {depth} m. Exports include synthetic labels when
                      applicable.
                    </p>
                    <button
                      className="primary"
                      disabled={busy || !date || !!exportBlock}
                      onClick={download}
                    >
                      <Download size={18} />
                      {busy ? "Preparing…" : "Download export"}
                    </button>
                    {exportBlock && (
                      <p className="muted" role="status">{exportBlock}</p>
                    )}
                    {exportError && (
                      <div role="alert" className="error">
                        {exportError}
                      </div>
                    )}
                  </Panel>
                  <Panel title="Your selection" sub={`${date} · ${mode}`}>
                    <div className="pill-row">
                      <span>15 depth levels</span>
                      <span>Daily fields</span>
                      <span>
                        {synthetic ? "Synthetic grid" : "Native run grid"}
                      </span>
                    </div>
                    {map(330)}
                    <button
                      className="text-button"
                      onClick={() => setShowManifest(!showManifest)}
                    >
                      Inspect run manifest <ChevronRight size={17} />
                    </button>
                    {showManifest && (
                      <pre>{JSON.stringify(meta.data.manifest, null, 2)}</pre>
                    )}
                  </Panel>
                </div>
                <Panel title="Recent downloads" sub="This browser session">
                  <table>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Format</th>
                        <th>Size</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {jobs.map((j, i) => (
                        <tr key={i}>
                          <td>{j.date}</td>
                          <td>{j.format.toUpperCase()}</td>
                          <td>{fmt(j.size / 1024, 1)} KB</td>
                          <td>Prepared and download started</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!jobs.length && (
                    <p className="empty">
                      No exports prepared in this session.
                    </p>
                  )}
                </Panel>
              </>
            )}
            {tab === "Readiness" && (
              <>
                <div className="disaster-banner" role="note">
                  <Siren size={22} />
                  <div>
                    <strong>Ocean thermal context only — this is not a cyclone forecast.</strong>
                    <span>
                      This screen shows reconstructed ocean heat, marine-heatwave severity
                      and estimate reliability. It does not predict cyclone formation, track
                      or intensity. For official warnings and evacuation orders, always
                      follow IMD, NDMA and your state or district disaster authority.
                    </span>
                  </div>
                </div>

                <Panel
                  title="Regional heat-potential grid"
                  sub={`${date} · click anywhere to inspect that point below`}
                >
                  {map(460)}
                  <Notice>
                    Coloured by Tropical Cyclone Heat Potential (TCHP) across the whole
                    displayed grid — the same reference bands as the gauge below, shown
                    spatially so severity can be compared point to point rather than read
                    at a single location only. Reliability and Argo-observation layers use
                    the same toggles as the Explore tab.
                  </Notice>
                </Panel>

                <div className="readiness-grid">
                  <Panel
                    title="Ocean heat potential"
                    sub={`${placeName(pos)} · ${fmt(pos.lat)}° N, ${fmt(pos.lon)}° E`}
                  >
                    <Load state={profile} />
                    {p && (
                      <>
                        <ArcGauge
                          value={p.diagnostics?.tchp_kj_cm2}
                          min={0}
                          max={180}
                          unit="kJ/cm² · TCHP"
                          zones={TCHP_BANDS}
                          title="Tropical Cyclone Heat Potential gauge"
                        />
                        <p className="gauge-caption">
                          {(() => {
                            const cat = tchpCategory(p.diagnostics?.tchp_kj_cm2);
                            return cat ? (
                              <>
                                <b style={{ color: cat.color }}>{cat.label} heat potential</b> at
                                this location and depth.
                              </>
                            ) : (
                              "No estimate at this location for the selected date."
                            );
                          })()}
                        </p>
                      </>
                    )}
                    <Notice>
                      Reference bands only, from commonly cited tropical-cyclone
                      heat-potential research thresholds. Higher ocean heat does not by
                      itself mean a storm will intensify — atmospheric conditions govern
                      that, and none are modelled here.
                    </Notice>
                  </Panel>

                  <Panel
                    title="Marine heatwave severity"
                    sub="Most recent qualifying event at this location"
                  >
                    <Load state={events} />
                    {latestEvent ? (
                      <>
                        <SeverityLadder category={latestEvent.category} />
                        <div className="mini-stats">
                          <span>
                            Duration<strong>{latestEvent.duration_days} days</strong>
                          </span>
                          <span>
                            Peak anomaly<strong>+{fmt(latestEvent.peak_anomaly)} °C</strong>
                          </span>
                        </div>
                      </>
                    ) : (
                      events.data && (
                        <p className="empty">
                          No qualifying heatwave event in the available series at this
                          location.
                        </p>
                      )
                    )}
                    <Notice>
                      Category reflects how far temperature rose above the seasonal
                      threshold (Moderate/Strong/Severe/Extreme heat-classification bands)
                      — a heat classification, not a storm-intensity class.
                    </Notice>
                  </Panel>

                  <Panel title="Estimate reliability" sub="Across the whole displayed grid">
                    <Load state={field} />
                    {f?.reliability_summary && (
                      <div className="donut-row">
                        <Donut counts={f.reliability_summary.counts} />
                        <div className="reliability-key">
                          {(["Supported", "Caution", "Abstain"] as const).map((state) => (
                            <div className="reliability-key-row" key={state}>
                              <span
                                className={`reliability-swatch state-${state.toLowerCase()}`}
                                aria-hidden="true"
                              />
                              <span className="reliability-key-label">{state}</span>
                              <span className="reliability-key-count">
                                {(f.reliability_summary.counts?.[state] ?? 0).toLocaleString()}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    <Notice>
                      Support for the estimate — not a danger level. It never changes a
                      severity class.
                    </Notice>
                  </Panel>
                </div>

                <Panel
                  title="Cyclone thermal snapshot"
                  sub="Retrospective heat context for the loaded track"
                >
                  <Load state={cyclone} />
                  {cyclone.data?.available ? (
                    <div className="cyclone-headline">
                      <strong>{cyclone.data.name}</strong>
                      <span className="muted">
                        Peak TCHP along track: {peakTrackTchp == null ? "—" : `${fmt(peakTrackTchp, 0)} kJ/cm²`} ·{" "}
                        {cyclone.data.points_with_thermal_context} of {cyclone.data.points_total}{" "}
                        track points have thermal context
                      </span>
                      <button className="text-button" onClick={() => setTab("Heat events")}>
                        Full thermal timeline <ChevronRight size={17} />
                      </button>
                    </div>
                  ) : (
                    <div className="empty tall">
                      <ShieldAlert size={36} />
                      <p>{cyclone.data?.note || "No cyclone context loaded."}</p>
                      <span>
                        Once a reviewed best-track file is configured, its peak ocean heat
                        potential will appear here alongside the full timeline on Heat
                        events.
                      </span>
                    </div>
                  )}
                </Panel>

                <Panel
                  title="Public awareness — before, during, after"
                  sub="General cyclone preparedness guidance"
                >
                  <div className="awareness-grid">
                    <div className="awareness-card">
                      <Home size={22} />
                      <h3>Before a cyclone</h3>
                      <ul>
                        <li>Secure loose roofing, windows, signage and outdoor objects</li>
                        <li>Keep a battery radio, torch, drinking water and a first-aid kit ready</li>
                        <li>Know your nearest cyclone shelter and evacuation route</li>
                      </ul>
                    </div>
                    <div className="awareness-card">
                      <Wind size={22} />
                      <h3>During a cyclone</h3>
                      <ul>
                        <li>Stay indoors, away from windows and glass</li>
                        <li>Do not go out to sea, to the coast, or to flooded areas</li>
                        <li>Follow official evacuation orders promptly if issued</li>
                      </ul>
                    </div>
                    <div className="awareness-card">
                      <Hospital size={22} />
                      <h3>After a cyclone</h3>
                      <ul>
                        <li>Avoid floodwater and downed power lines</li>
                        <li>Check your home for structural damage before re-entering</li>
                        <li>Wait for an official all-clear before returning to evacuated areas</li>
                      </ul>
                    </div>
                  </div>
                </Panel>

                <Panel
                  title="Get official alerts"
                  sub="This prototype does not send alerts — these are the real channels"
                >
                  <div className="channel-row">
                    <a className="channel-chip" href="https://mausam.imd.gov.in" target="_blank" rel="noreferrer">
                      <Satellite size={16} /> IMD · mausam.imd.gov.in
                    </a>
                    <a className="channel-chip" href="https://sachet.ndma.gov.in" target="_blank" rel="noreferrer">
                      <Radio size={16} /> NDMA SACHET alert portal
                    </a>
                    <span className="channel-chip static">
                      <Phone size={16} /> National emergency number · 112
                    </span>
                  </div>
                  <Notice>
                    In an active warning, always follow instructions from IMD, NDMA and
                    your state or district disaster management authority over any research
                    prototype.
                  </Notice>
                </Panel>
              </>
            )}
          </>
        )}
      </main>
      {infoPage && <div className="info-backdrop" onClick={()=>setInfoPage("")}><section className="info-dialog panel" role="dialog" aria-modal="true" aria-label={infoPage} onClick={ev=>ev.stopPropagation()}><button autoFocus className="close-info" onClick={()=>setInfoPage("")}>Close</button><h2>{infoPage}</h2>{infoPage==="About"?<p>OceanEmbed-NIO is a Team DeepSindhu student research prototype for SIH 2026. MoES and INCOIS are problem-domain references; this is not an official portal or endorsed service. Reconstructed ocean heat alone does not predict cyclone intensity.</p>:infoPage==="Data sources"?<p>Geographic context: Natural Earth 1:110m, public domain, bundled locally. The active run identifies its satellite, Argo, RAMA and reanalysis provenance. Synthetic mode contains no real observations or measured validation skill. Coastlines are for orientation, not navigation or boundary adjudication.</p>:<p>Accessibility target: WCAG 2.1 AA and relevant GIGW 3.0 guidance. Text resizing, high contrast, keyboard controls, visible focus and non-colour reliability markers are included. Formal compliance has not been audited or certified.</p>}</section></div>}
      <footer>
        <span>
          <img className="footer-mark" src="/oceanembed-mark.png" alt="" aria-hidden="true" />
          OceanEmbed-NIO <i /> Team DeepSindhu
          {["About","Data sources","Accessibility"].map(x=><button key={x} className="text-button" onClick={()=>setInfoPage(x)}>{x}</button>)}
        </span>
        <span>
          {synthetic
            ? "Synthetic engineering fixture · Not operational data"
            : "Research reconstruction · Check source and validation provenance"}
        </span>
      </footer>
      <div className="operational-notice">Research Decision-Support Prototype — Not an Operational Cyclone Intensity Warning System.</div>
    </div>
  );
}
