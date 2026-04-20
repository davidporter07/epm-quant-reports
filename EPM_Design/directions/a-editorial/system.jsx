// Direction A — EDITORIAL / PREMIUM
// Serif display + refined sans, generous whitespace, hairline rules.
// Anchor references: FT, CNBC Pro, Bloomberg.com (web, not Terminal)
// Palette: deep ink navy, warm paper cream, a single burnished gold accent.

const EDA = {
  ink:       '#0E1A2B',
  inkSoft:   '#334155',
  mute:      '#6B7280',
  rule:      '#D9D3C4',
  ruleSoft:  '#E8E2D3',
  paper:     '#F6F1E6',
  paperAlt:  '#FBF7EC',
  card:      '#FFFFFF',
  accent:    '#9A6B1F',   // burnished gold
  up:        '#1F6B43',
  down:      '#A6301B',
  serif:     '"Source Serif 4", "Source Serif Pro", Georgia, "Times New Roman", serif',
  sans:      '"Inter Tight", "Helvetica Neue", Helvetica, Arial, sans-serif',
  mono:      'ui-monospace, "SF Mono", Menlo, monospace',
};

// Page frame ─────────────────────────────────────────────────────────
function EdaFrame({ children, page }) {
  return (
    <div style={{
      width: 1440, minHeight: 900, background: EDA.paper, color: EDA.ink,
      fontFamily: EDA.sans, fontSize: 14, lineHeight: 1.5,
    }}>
      <EdaTickerBar />
      <EdaMasthead />
      <EdaNav active={page} />
      <div style={{ padding: '40px 56px 64px' }}>
        {children}
      </div>
      <EdaFooter />
    </div>
  );
}

function EdaTickerBar() {
  return (
    <div style={{
      background: EDA.ink, color: '#F6F1E6', fontFamily: EDA.mono,
      fontSize: 11, letterSpacing: 0.3, padding: '8px 56px',
      display: 'flex', gap: 28, overflow: 'hidden', borderBottom: `1px solid ${EDA.ink}`,
    }}>
      {INDICES.slice(0, 8).map((i, k) => (
        <span key={k} style={{ display: 'inline-flex', gap: 8, alignItems: 'baseline' }}>
          <span style={{ opacity: 0.6 }}>{i.sym}</span>
          <span>{i.val}</span>
          <span style={{ color: i.up ? '#6FD19A' : '#F1867A' }}>{i.pct}</span>
        </span>
      ))}
    </div>
  );
}

function EdaMasthead() {
  return (
    <div style={{
      padding: '28px 56px 18px', background: EDA.paper,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      borderBottom: `1px solid ${EDA.rule}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}>
        <div style={{ fontFamily: EDA.serif, fontSize: 32, fontWeight: 600, letterSpacing: -0.5, color: EDA.ink }}>
          EPM <span style={{ fontStyle: 'italic', fontWeight: 400 }}>Market Intelligence</span>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 22, fontSize: 12, color: EDA.inkSoft }}>
        <span style={{ fontFamily: EDA.mono, textTransform: 'uppercase', letterSpacing: 0.6 }}>
          Saturday · Apr 18, 2026 · 3:42 PM ET
        </span>
        <span style={{ width: 1, height: 14, background: EDA.rule }} />
        <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: EDA.up }} />
          Markets Open
        </span>
        <button style={{
          border: `1px solid ${EDA.ink}`, background: 'transparent', color: EDA.ink,
          padding: '6px 14px', fontFamily: EDA.sans, fontSize: 12, fontWeight: 500,
          letterSpacing: 0.3, cursor: 'pointer',
        }}>Sign in</button>
      </div>
    </div>
  );
}

function EdaNav({ active }) {
  const items = ['Homepage', 'Markets', 'Forecasting', 'Model Portfolios', 'Fund Search', 'Research', 'Watchlists'];
  return (
    <div style={{
      padding: '0 56px', background: EDA.paper,
      borderBottom: `1px solid ${EDA.rule}`,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <div style={{ display: 'flex', gap: 36 }}>
        {items.map((n) => {
          const on = n === active;
          return (
            <div key={n} style={{
              padding: '16px 0', fontSize: 13, fontWeight: on ? 600 : 500,
              color: on ? EDA.ink : EDA.inkSoft,
              borderBottom: on ? `2px solid ${EDA.accent}` : '2px solid transparent',
              letterSpacing: 0.1,
            }}>{n}</div>
          );
        })}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 0' }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          border: `1px solid ${EDA.rule}`, padding: '6px 12px',
          fontFamily: EDA.mono, fontSize: 11, color: EDA.mute, background: EDA.paperAlt,
        }}>
          <span>⌕</span><span>Search ticker, fund, topic</span>
          <span style={{ marginLeft: 16, opacity: 0.6 }}>⌘K</span>
        </div>
      </div>
    </div>
  );
}

function EdaFooter() {
  return (
    <div style={{
      borderTop: `1px solid ${EDA.rule}`, padding: '28px 56px',
      fontFamily: EDA.mono, fontSize: 11, color: EDA.mute, letterSpacing: 0.3,
      display: 'flex', justifyContent: 'space-between',
    }}>
      <span>© 2026 EPM FINANCIAL · MARKET INTELLIGENCE</span>
      <span>DATA AS OF 15:42 ET · REFRESH 30S</span>
    </div>
  );
}

// Atoms ──────────────────────────────────────────────────────────────
function EdaKicker({ children, color }) {
  return (
    <div style={{
      fontFamily: EDA.sans, fontSize: 10.5, fontWeight: 600, letterSpacing: 1.4,
      textTransform: 'uppercase', color: color || EDA.accent, marginBottom: 8,
    }}>{children}</div>
  );
}

function EdaH1({ children, size = 34 }) {
  return (
    <div style={{
      fontFamily: EDA.serif, fontSize: size, lineHeight: 1.1, letterSpacing: -0.6,
      fontWeight: 600, color: EDA.ink,
    }}>{children}</div>
  );
}
function EdaH2({ children, size = 22 }) {
  return (
    <div style={{
      fontFamily: EDA.serif, fontSize: size, lineHeight: 1.15, letterSpacing: -0.3,
      fontWeight: 600, color: EDA.ink,
    }}>{children}</div>
  );
}

function EdaSectionHeader({ kicker, title, right }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between',
      borderBottom: `2px solid ${EDA.ink}`, paddingBottom: 10, marginBottom: 20 }}>
      <div>
        {kicker && <EdaKicker>{kicker}</EdaKicker>}
        <EdaH2>{title}</EdaH2>
      </div>
      {right && <div style={{ fontSize: 12, color: EDA.mute, fontFamily: EDA.mono, letterSpacing: 0.4 }}>{right}</div>}
    </div>
  );
}

function EdaDelta({ up, children }) {
  return (
    <span style={{ fontFamily: EDA.mono, color: up ? EDA.up : EDA.down, fontSize: 12, fontWeight: 500 }}>
      {children}
    </span>
  );
}

// Tall card container — hairline, paper white
function EdaCard({ children, style = {}, pad = 24 }) {
  return (
    <div style={{ background: EDA.card, border: `1px solid ${EDA.rule}`, padding: pad, ...style }}>
      {children}
    </div>
  );
}

Object.assign(window, {
  EDA, EdaFrame, EdaTickerBar, EdaMasthead, EdaNav, EdaFooter,
  EdaKicker, EdaH1, EdaH2, EdaSectionHeader, EdaDelta, EdaCard,
});
