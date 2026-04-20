// Direction B — TERMINAL / DATA-DENSE
// Compact sans + mono numerics, tight rows, rules over cards.
// Anchor: Bloomberg Terminal, Koyfin, trading consoles.
// Palette: deep charcoal/near-black, amber accent for EPM, red/green semantic.

const TRM = {
  bg:        '#0B0F14',
  surface:   '#11161D',
  surface2:  '#161D26',
  line:      '#1E2732',
  lineSoft:  '#161D26',
  text:      '#E6EBF2',
  textSoft:  '#9AA7B8',
  mute:      '#5F6E82',
  accent:    '#E8A33D',   // amber
  accent2:   '#4EA3FF',   // cyan-blue for hyperlinks
  up:        '#36C58A',
  down:      '#FF5A5A',
  sans:      '"IBM Plex Sans", "Inter", "Helvetica Neue", Arial, sans-serif',
  mono:      '"IBM Plex Mono", "JetBrains Mono", "SF Mono", Menlo, monospace',
};

function TrmFrame({ children, page }) {
  return (
    <div style={{
      width: 1440, minHeight: 900, background: TRM.bg, color: TRM.text,
      fontFamily: TRM.sans, fontSize: 12, lineHeight: 1.4,
    }}>
      <TrmTopBar />
      <TrmNav active={page} />
      <TrmCommandBar />
      <div style={{ padding: '16px 20px 40px' }}>{children}</div>
      <TrmStatus />
    </div>
  );
}

function TrmTopBar() {
  return (
    <div style={{
      height: 38, background: '#000', borderBottom: `1px solid ${TRM.line}`,
      display: 'flex', alignItems: 'center', padding: '0 20px', gap: 18,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ width: 22, height: 22, background: TRM.accent, display: 'grid', placeItems: 'center', color: '#000', fontWeight: 700, fontSize: 11 }}>E</div>
        <div style={{ fontWeight: 600, fontSize: 13, letterSpacing: 0.3 }}>EPM <span style={{ color: TRM.textSoft, fontWeight: 400 }}>MARKET INTELLIGENCE</span></div>
      </div>
      <div style={{ flex: 1 }} />
      <div style={{ fontFamily: TRM.mono, fontSize: 11, color: TRM.textSoft, letterSpacing: 0.4 }}>
        15:42:08 ET · SAT 04.18.26
      </div>
      <div style={{ display: 'flex', gap: 14, fontSize: 11, color: TRM.textSoft, fontFamily: TRM.mono, letterSpacing: 0.4 }}>
        <span><span style={{ color: TRM.up }}>●</span> US OPEN</span>
        <span><span style={{ color: TRM.mute }}>●</span> EU CLOSED</span>
        <span><span style={{ color: TRM.mute }}>●</span> ASIA CLOSED</span>
      </div>
      <div style={{ width: 1, height: 18, background: TRM.line }} />
      <span style={{ fontSize: 11, color: TRM.textSoft, fontFamily: TRM.mono }}>M.HARPER · TIER 2</span>
    </div>
  );
}

function TrmNav({ active }) {
  const items = ['HOME', 'MARKETS', 'FORECASTING', 'PORTFOLIOS', 'FUND SEARCH', 'WATCHLIST', 'SCREENER', 'NEWS'];
  return (
    <div style={{
      background: TRM.surface, borderBottom: `1px solid ${TRM.line}`,
      padding: '0 20px', display: 'flex', gap: 2,
    }}>
      {items.map((n) => {
        const on = active && (n === active.toUpperCase() || n === 'PORTFOLIOS' && active === 'Model Portfolios' || n === 'HOME' && active === 'Homepage' || n === 'FUND SEARCH' && active === 'Fund Search');
        return (
          <div key={n} style={{
            padding: '12px 16px', fontSize: 11.5, fontWeight: 600, letterSpacing: 0.6,
            color: on ? '#000' : TRM.textSoft,
            background: on ? TRM.accent : 'transparent',
            fontFamily: TRM.mono,
          }}>{n}</div>
        );
      })}
    </div>
  );
}

function TrmCommandBar() {
  return (
    <div style={{
      background: TRM.surface2, borderBottom: `1px solid ${TRM.line}`,
      padding: '8px 20px', display: 'flex', alignItems: 'center', gap: 12, fontFamily: TRM.mono,
    }}>
      <span style={{ color: TRM.accent, fontSize: 11, letterSpacing: 0.6 }}>CMD</span>
      <div style={{
        flex: 1, background: '#05080C', border: `1px solid ${TRM.line}`, padding: '6px 10px',
        fontSize: 12, color: TRM.text,
      }}>
        <span style={{ color: TRM.accent }}>&gt; </span>
        <span style={{ color: TRM.mute }}>type ticker, function, or FUNC code (e.g. SPX {'<'}GO{'>'})</span>
      </div>
      <span style={{ fontSize: 10.5, color: TRM.mute, letterSpacing: 0.4 }}>F1 HELP · F2 NEWS · F3 WATCH · F4 SCREEN</span>
    </div>
  );
}

function TrmStatus() {
  return (
    <div style={{
      borderTop: `1px solid ${TRM.line}`, background: '#000',
      padding: '6px 20px', fontFamily: TRM.mono, fontSize: 10.5,
      color: TRM.mute, letterSpacing: 0.5,
      display: 'flex', justifyContent: 'space-between',
    }}>
      <span>CONN: <span style={{ color: TRM.up }}>LIVE</span> · FEED: <span style={{ color: TRM.text }}>CONSOLIDATED</span> · LAT: 42ms</span>
      <span>© 2026 EPM FINANCIAL · MI v4.2.1</span>
    </div>
  );
}

function TrmPanel({ title, right, children, pad = 12 }) {
  return (
    <div style={{ background: TRM.surface, border: `1px solid ${TRM.line}` }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '7px 12px', background: TRM.surface2, borderBottom: `1px solid ${TRM.line}`,
        fontFamily: TRM.mono, fontSize: 10.5, letterSpacing: 0.7, color: TRM.textSoft, textTransform: 'uppercase',
      }}>
        <span>{title}</span>
        {right && <span style={{ color: TRM.mute }}>{right}</span>}
      </div>
      <div style={{ padding: pad }}>{children}</div>
    </div>
  );
}

function TrmDelta({ up, children }) {
  return <span style={{ color: up ? TRM.up : TRM.down, fontFamily: TRM.mono }}>{children}</span>;
}

Object.assign(window, { TRM, TrmFrame, TrmPanel, TrmDelta });
