// Small shared primitives used across all three directions.

// Deterministic sparkline path
function sparkPath(seed, w = 80, h = 22, pts = 20, up = true) {
  const vals = [];
  let v = 50;
  let s = seed;
  const rnd = () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };
  for (let i = 0; i < pts; i++) {
    const drift = (up ? 1 : -1) * (i / pts) * 18;
    v += (rnd() - 0.5) * 14 + drift * 0.15;
    vals.push(v);
  }
  const min = Math.min(...vals), max = Math.max(...vals);
  const nx = (i) => (i / (pts - 1)) * w;
  const ny = (val) => h - ((val - min) / Math.max(0.001, max - min)) * h;
  return vals.map((val, i) => `${i === 0 ? 'M' : 'L'}${nx(i).toFixed(1)},${ny(val).toFixed(1)}`).join(' ');
}

function Spark({ seed = 1, up = true, w = 80, h = 22, color, strokeWidth = 1.5 }) {
  const d = sparkPath(seed, w, h, 20, up);
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
      <path d={d} fill="none" stroke={color || (up ? '#2e7d4f' : '#b42318')} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// Placeholder strip with monospace label (for imagery we'd commission)
function PhotoPlaceholder({ label = 'editorial photo', height = 180, tone = 'navy', radius = 0 }) {
  const bg = tone === 'navy' ? '#0B1F3A' : tone === 'cream' ? '#E9E4D8' : tone === 'paper' ? '#F2EEE5' : '#1a1a1a';
  const fg = tone === 'cream' || tone === 'paper' ? 'rgba(0,0,0,0.55)' : 'rgba(255,255,255,0.7)';
  const stripe = tone === 'cream' || tone === 'paper' ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.06)';
  return (
    <div style={{
      height, background: bg, color: fg,
      backgroundImage: `repeating-linear-gradient(135deg, ${stripe} 0 2px, transparent 2px 14px)`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace',
      fontSize: 11, letterSpacing: 0.4, textTransform: 'uppercase',
      borderRadius: radius,
    }}>[ {label} ]</div>
  );
}

// Dot-rating (funds)
function Stars({ n = 5, filled = 5, color = '#C9A227' }) {
  return (
    <span style={{ letterSpacing: 1, color, fontSize: 11 }}>
      {'★'.repeat(filled)}<span style={{ color: 'rgba(0,0,0,0.2)' }}>{'★'.repeat(n - filled)}</span>
    </span>
  );
}

Object.assign(window, { Spark, sparkPath, PhotoPlaceholder, Stars });
