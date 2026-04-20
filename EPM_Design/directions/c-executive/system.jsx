// Direction C — EXECUTIVE / CLIENT-FACING
// Modern geometric sans, soft cards with disciplined elevation, confident color use.
// Anchor: Addepar / Koyfin Pro / modern wealth platforms.
// Palette: deep EPM navy primary, cool off-white canvas, single teal accent for positive actions, amber for highlights.

const EXC = {
  bg:        '#F4F6FA',
  canvas:    '#FFFFFF',
  ink:       '#0B1F3A',   // EPM navy
  inkSoft:   '#3E4C63',
  text:      '#1F2937',
  mute:      '#6B7688',
  line:      '#E3E7EE',
  lineSoft:  '#EEF1F6',
  accent:    '#1E7F74',   // teal
  accentSoft:'#D8EAE7',
  highlight: '#C28A2B',   // amber
  up:        '#0F8A56',
  upSoft:    '#E4F3EC',
  down:      '#B3271C',
  downSoft:  '#FBE8E5',
  sans:      '"Söhne", "Inter", "Helvetica Neue", Arial, sans-serif',
  display:   '"GT Sectra", "Söhne", "Inter", serif',
  mono:      '"JetBrains Mono", "SF Mono", Menlo, monospace',
  r:         6,
  shadow:    '0 1px 2px rgba(11,31,58,0.04), 0 6px 20px rgba(11,31,58,0.06)',
};

function ExcFrame({ children, page }) {
  return (
    <div style={{
      width: 1440, minHeight: 900, background: EXC.bg, color: EXC.text,
      fontFamily: EXC.sans, fontSize: 13, lineHeight: 1.5,
    }}>
      <ExcNav active={page} />
      <div style={{ padding: '28px 40px 56px' }}>{children}</div>
    </div>
  );
}

function ExcNav({ active }) {
  const items = ['Homepage', 'Markets', 'Forecasting', 'Model Portfolios', 'Fund Search', 'Research', 'Watchlists'];
  return (
    <div style={{
      background: EXC.ink, color: '#E9EDF3',
      padding: '0 40px', display: 'flex', alignItems: 'center',
      borderBottom: '1px solid rgba(255,255,255,0.06)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, paddingRight: 36 }}>
        <div style={{
          width: 28, height: 28, background: EXC.highlight, color: EXC.ink,
          display: 'grid', placeItems: 'center', fontWeight: 700, fontSize: 13, borderRadius: 4,
        }}>E</div>
        <div style={{ fontWeight: 600, fontSize: 15, letterSpacing: -0.2 }}>
          EPM <span style={{ opacity: 0.7, fontWeight: 400 }}>Market Intelligence</span>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 4 }}>
        {items.map((n) => {
          const on = n === active;
          return (
            <div key={n} style={{
              padding: '20px 16px', fontSize: 13, fontWeight: on ? 600 : 500,
              color: on ? '#fff' : 'rgba(255,255,255,0.72)',
              borderBottom: on ? `2px solid ${EXC.highlight}` : '2px solid transparent',
            }}>{n}</div>
          );
        })}
      </div>
      <div style={{ flex: 1 }} />
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.08)',
        padding: '7px 12px', borderRadius: EXC.r, fontSize: 12,
      }}>
        <span>⌕</span><span style={{ opacity: 0.65 }}>Search markets, funds, research</span>
        <span style={{ marginLeft: 24, opacity: 0.5, fontFamily: EXC.mono, fontSize: 11 }}>⌘K</span>
      </div>
      <div style={{ marginLeft: 16, width: 32, height: 32, borderRadius: '50%', background: EXC.highlight, color: EXC.ink, display: 'grid', placeItems: 'center', fontSize: 12, fontWeight: 600 }}>MH</div>
    </div>
  );
}

function ExcCard({ children, style = {}, pad = 20 }) {
  return (
    <div style={{
      background: EXC.canvas, border: `1px solid ${EXC.line}`, borderRadius: EXC.r,
      padding: pad, boxShadow: EXC.shadow, ...style,
    }}>{children}</div>
  );
}

function ExcSectionHead({ eyebrow, title, action }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 14 }}>
      <div>
        {eyebrow && <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.8, color: EXC.accent, textTransform: 'uppercase', marginBottom: 4 }}>{eyebrow}</div>}
        <div style={{ fontSize: 20, fontWeight: 600, color: EXC.ink, letterSpacing: -0.2 }}>{title}</div>
      </div>
      {action && <div style={{ fontSize: 13, color: EXC.accent, fontWeight: 500 }}>{action} →</div>}
    </div>
  );
}

function ExcPill({ children, tone = 'neutral' }) {
  const map = {
    up:      { bg: EXC.upSoft, fg: EXC.up },
    down:    { bg: EXC.downSoft, fg: EXC.down },
    neutral: { bg: EXC.lineSoft, fg: EXC.inkSoft },
    accent:  { bg: EXC.accentSoft, fg: EXC.accent },
  };
  const t = map[tone];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 10px', borderRadius: 100, background: t.bg, color: t.fg,
      fontSize: 11.5, fontWeight: 600, fontFamily: EXC.mono, letterSpacing: 0.2,
    }}>{children}</span>
  );
}

Object.assign(window, { EXC, ExcFrame, ExcCard, ExcSectionHead, ExcPill });
