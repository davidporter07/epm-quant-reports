// Direction A — Editorial — Markets
// Big chart + indices rail + movers in a single, disciplined grid.

function EdaMarkets() {
  return (
    <EdaFrame page="Markets">
      {/* Page header */}
      <div style={{ marginBottom: 28 }}>
        <EdaKicker>Section</EdaKicker>
        <EdaH1 size={44}>Markets</EdaH1>
        <div style={{ marginTop: 10, fontFamily: EDA.serif, fontSize: 18, color: EDA.inkSoft, maxWidth: 760 }}>
          Equities, fixed income, commodities, FX, and credit — at a glance and in depth.
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 28, borderBottom: `1px solid ${EDA.rule}`, marginBottom: 28 }}>
        {['Overview', 'Equities', 'Fixed Income', 'Commodities', 'FX', 'Credit', 'Crypto'].map((t, i) => (
          <div key={t} style={{
            padding: '12px 0', fontSize: 13, fontWeight: i === 0 ? 600 : 500,
            color: i === 0 ? EDA.ink : EDA.inkSoft,
            borderBottom: i === 0 ? `2px solid ${EDA.accent}` : '2px solid transparent',
          }}>{t}</div>
        ))}
      </div>

      {/* Feature chart + key metrics */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 36, marginBottom: 48 }}>
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
            <div>
              <EdaKicker>Benchmark</EdaKicker>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}>
                <EdaH2 size={28}>S&P 500</EdaH2>
                <div style={{ fontFamily: EDA.mono, fontSize: 22, color: EDA.ink }}>5,247.18</div>
                <EdaDelta up>+18.42 (+0.35%)</EdaDelta>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              {['1D', '5D', '1M', '6M', 'YTD', '1Y', '5Y', 'MAX'].map((r, i) => (
                <div key={r} style={{
                  padding: '6px 12px', fontSize: 12, fontFamily: EDA.mono,
                  border: `1px solid ${i === 4 ? EDA.ink : EDA.rule}`,
                  background: i === 4 ? EDA.ink : 'transparent',
                  color: i === 4 ? EDA.paper : EDA.inkSoft,
                }}>{r}</div>
              ))}
            </div>
          </div>
          {/* Chart area */}
          <div style={{ background: EDA.card, border: `1px solid ${EDA.rule}`, padding: '20px 24px 12px', height: 360, position: 'relative' }}>
            <svg viewBox="0 0 780 300" width="100%" height="100%" preserveAspectRatio="none">
              {/* grid */}
              {[0, 1, 2, 3, 4].map((i) => (
                <line key={i} x1="0" x2="780" y1={i * 75} y2={i * 75} stroke={EDA.ruleSoft} strokeWidth="1" />
              ))}
              {/* area */}
              <path d="M0,220 L60,200 L120,210 L180,180 L240,190 L300,160 L360,170 L420,140 L480,130 L540,110 L600,120 L660,95 L720,80 L780,70 L780,300 L0,300 Z"
                fill={EDA.accent} opacity="0.08" />
              <path d="M0,220 L60,200 L120,210 L180,180 L240,190 L300,160 L360,170 L420,140 L480,130 L540,110 L600,120 L660,95 L720,80 L780,70"
                fill="none" stroke={EDA.accent} strokeWidth="1.8" />
            </svg>
            <div style={{ position: 'absolute', right: 16, top: 16, fontFamily: EDA.mono, fontSize: 10.5, color: EDA.mute, letterSpacing: 0.4 }}>
              YTD · INTRADAY · 1-MIN
            </div>
          </div>
        </div>

        <div>
          <EdaSectionHeader title="Global indices" right="LIVE" />
          {INDICES.map((i, k) => (
            <div key={k} style={{
              display: 'grid', gridTemplateColumns: '1fr 80px 60px', alignItems: 'center',
              padding: '11px 0', borderBottom: `1px solid ${EDA.ruleSoft}`, fontSize: 13,
            }}>
              <div style={{ fontWeight: 500 }}>{i.sym}</div>
              <div style={{ textAlign: 'right', fontFamily: EDA.mono }}>{i.val}</div>
              <EdaDelta up={i.up}><div style={{ textAlign: 'right' }}>{i.pct}</div></EdaDelta>
            </div>
          ))}
        </div>
      </div>

      {/* Heatmap + movers */}
      <EdaSectionHeader kicker="S&P 500" title="Sector heatmap" right="1-DAY CHANGE" />
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 2fr 3fr 2fr', gridAutoRows: '80px', gap: 4, marginBottom: 48 }}>
        {[
          { t: 'Info Tech',     v: '+1.82%', u: true,  span: 'span 2 / span 2' },
          { t: 'Comm Svcs',     v: '+1.14%', u: true,  span: 'span 2 / span 1' },
          { t: 'Cons Discr',    v: '+0.62%', u: true,  span: 'span 1 / span 1' },
          { t: 'Financials',    v: '+0.18%', u: true,  span: 'span 1 / span 1' },
          { t: 'Industrials',   v: '-0.04%', u: false, span: 'span 1 / span 1' },
          { t: 'Health Care',   v: '-0.22%', u: false, span: 'span 1 / span 1' },
          { t: 'Staples',       v: '-0.41%', u: false, span: 'span 1 / span 1' },
          { t: 'Utilities',     v: '-0.58%', u: false, span: 'span 1 / span 1' },
          { t: 'Real Estate',   v: '-0.71%', u: false, span: 'span 1 / span 1' },
          { t: 'Materials',     v: '-0.88%', u: false, span: 'span 1 / span 1' },
          { t: 'Energy',        v: '-1.12%', u: false, span: 'span 1 / span 1' },
        ].map((c, k) => {
          const mag = Math.abs(parseFloat(c.v));
          const a = Math.min(0.85, 0.15 + mag * 0.35);
          return (
            <div key={k} style={{
              gridColumn: k === 0 ? 'span 2' : undefined,
              gridRow: k === 0 ? 'span 2' : undefined,
              background: c.u ? `rgba(31,107,67,${a})` : `rgba(166,48,27,${a})`,
              color: a > 0.4 ? '#fff' : EDA.ink,
              padding: 14, display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, fontFamily: EDA.sans }}>{c.t}</div>
              <div style={{ fontSize: 14, fontFamily: EDA.mono }}>{c.v}</div>
            </div>
          );
        })}
      </div>

      {/* Two-col movers */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 36 }}>
        <div>
          <EdaSectionHeader title="Gainers" />
          {MOVERS_UP.map((m, k) => (
            <div key={k} style={{ display: 'grid', gridTemplateColumns: '60px 1fr 90px 100px 80px', gap: 10, padding: '13px 0', borderBottom: `1px solid ${EDA.ruleSoft}`, alignItems: 'center', fontSize: 13 }}>
              <div style={{ fontFamily: EDA.mono, fontWeight: 600 }}>{m.sym}</div>
              <div style={{ color: EDA.inkSoft }}>{m.name}</div>
              <Spark seed={k * 7 + 3} up w={90} h={22} color={EDA.up} />
              <div style={{ textAlign: 'right', fontFamily: EDA.mono }}>{m.price}</div>
              <EdaDelta up><div style={{ textAlign: 'right' }}>{m.pct}</div></EdaDelta>
            </div>
          ))}
        </div>
        <div>
          <EdaSectionHeader title="Decliners" />
          {MOVERS_DN.map((m, k) => (
            <div key={k} style={{ display: 'grid', gridTemplateColumns: '60px 1fr 90px 100px 80px', gap: 10, padding: '13px 0', borderBottom: `1px solid ${EDA.ruleSoft}`, alignItems: 'center', fontSize: 13 }}>
              <div style={{ fontFamily: EDA.mono, fontWeight: 600 }}>{m.sym}</div>
              <div style={{ color: EDA.inkSoft }}>{m.name}</div>
              <Spark seed={k * 11 + 5} up={false} w={90} h={22} color={EDA.down} />
              <div style={{ textAlign: 'right', fontFamily: EDA.mono }}>{m.price}</div>
              <EdaDelta up={false}><div style={{ textAlign: 'right' }}>{m.pct}</div></EdaDelta>
            </div>
          ))}
        </div>
      </div>
    </EdaFrame>
  );
}

Object.assign(window, { EdaMarkets });
