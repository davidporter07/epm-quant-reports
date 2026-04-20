// Direction C — Executive — Markets

function ExcMarkets() {
  return (
    <ExcFrame page="Markets">
      <div style={{ marginBottom: 22, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <div style={{ fontFamily: EXC.display, fontSize: 32, fontWeight: 600, color: EXC.ink, letterSpacing: -0.4 }}>Markets</div>
          <div style={{ color: EXC.inkSoft, fontSize: 14, marginTop: 4 }}>Global equities, rates, FX, commodities & crypto — one view.</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {['Overview', 'Equities', 'Rates', 'FX', 'Commodities', 'Crypto'].map((t, i) => (
            <div key={t} style={{
              padding: '8px 14px', fontSize: 13, fontWeight: i === 0 ? 600 : 500,
              background: i === 0 ? EXC.ink : EXC.canvas, color: i === 0 ? '#fff' : EXC.inkSoft,
              border: `1px solid ${i === 0 ? EXC.ink : EXC.line}`, borderRadius: EXC.r,
            }}>{t}</div>
          ))}
        </div>
      </div>

      {/* Featured chart + summary */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 20, marginBottom: 22 }}>
        <ExcCard>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
            <div>
              <div style={{ fontSize: 12, color: EXC.mute, fontWeight: 600, letterSpacing: 0.4 }}>S&P 500 · SPX</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, marginTop: 4 }}>
                <div style={{ fontSize: 32, fontWeight: 600, color: EXC.ink, letterSpacing: -0.4, fontFamily: EXC.mono }}>5,247.18</div>
                <ExcPill tone="up">+18.42 · +0.35%</ExcPill>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              {['1D','5D','1M','6M','YTD','1Y','5Y'].map((r,i) => (
                <div key={r} style={{
                  padding: '6px 12px', fontSize: 12, fontFamily: EXC.mono,
                  background: i === 4 ? EXC.ink : 'transparent',
                  color: i === 4 ? '#fff' : EXC.inkSoft,
                  border: `1px solid ${i === 4 ? EXC.ink : EXC.line}`, borderRadius: 4,
                }}>{r}</div>
              ))}
            </div>
          </div>
          <div style={{ height: 300, position: 'relative' }}>
            <svg viewBox="0 0 800 300" width="100%" height="100%" preserveAspectRatio="none">
              {[0,1,2,3,4].map(i => <line key={i} x1="0" x2="800" y1={i*75} y2={i*75} stroke={EXC.lineSoft} />)}
              <defs>
                <linearGradient id="excgrad" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor={EXC.accent} stopOpacity="0.25" />
                  <stop offset="100%" stopColor={EXC.accent} stopOpacity="0" />
                </linearGradient>
              </defs>
              <path d="M0,220 L60,205 L120,210 L180,180 L240,188 L300,160 L360,170 L420,140 L480,128 L540,108 L600,118 L660,92 L720,78 L800,62 L800,300 L0,300 Z" fill="url(#excgrad)" />
              <path d="M0,220 L60,205 L120,210 L180,180 L240,188 L300,160 L360,170 L420,140 L480,128 L540,108 L600,118 L660,92 L720,78 L800,62" fill="none" stroke={EXC.accent} strokeWidth="2" />
            </svg>
          </div>
        </ExcCard>

        <ExcCard>
          <ExcSectionHead title="Global indices" action="See all" />
          {INDICES.map((i, k) => (
            <div key={k} style={{
              display: 'grid', gridTemplateColumns: '1fr 90px 70px',
              padding: '9px 0', borderBottom: k === INDICES.length - 1 ? 'none' : `1px solid ${EXC.lineSoft}`,
              alignItems: 'center', fontSize: 13,
            }}>
              <div style={{ fontWeight: 500 }}>{i.sym}</div>
              <div style={{ textAlign: 'right', fontFamily: EXC.mono }}>{i.val}</div>
              <div style={{ textAlign: 'right' }}><ExcPill tone={i.up ? 'up' : 'down'}>{i.pct}</ExcPill></div>
            </div>
          ))}
        </ExcCard>
      </div>

      {/* Sector blocks */}
      <ExcSectionHead eyebrow="S&P 500" title="Sector performance" action="Heatmap" />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 22 }}>
        {SECTORS.slice(0, 8).map((s, k) => (
          <ExcCard key={k} pad={16}>
            <div style={{ fontSize: 12, color: EXC.mute, fontWeight: 600, letterSpacing: 0.3, textTransform: 'uppercase' }}>{s.name}</div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 10 }}>
              <div style={{ fontSize: 22, fontWeight: 600, fontFamily: EXC.mono, color: s.up ? EXC.up : EXC.down }}>{s.pct}</div>
              <Spark seed={k * 5 + 1} up={s.up} w={72} h={26} color={s.up ? EXC.up : EXC.down} strokeWidth={1.6} />
            </div>
          </ExcCard>
        ))}
      </div>

      {/* Movers */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        <ExcCard>
          <ExcSectionHead title="Gainers" />
          {MOVERS_UP.map((m, k) => (
            <div key={k} style={{
              display: 'grid', gridTemplateColumns: '60px 1fr 80px 100px 80px', gap: 10,
              padding: '12px 0', borderBottom: k === 4 ? 'none' : `1px solid ${EXC.lineSoft}`,
              alignItems: 'center', fontSize: 13,
            }}>
              <div style={{ fontWeight: 600 }}>{m.sym}</div>
              <div style={{ color: EXC.inkSoft, fontSize: 12 }}>{m.name}</div>
              <Spark seed={k * 9 + 3} up w={80} h={22} color={EXC.up} strokeWidth={1.5} />
              <div style={{ textAlign: 'right', fontFamily: EXC.mono }}>{m.price}</div>
              <div style={{ textAlign: 'right' }}><ExcPill tone="up">{m.pct}</ExcPill></div>
            </div>
          ))}
        </ExcCard>
        <ExcCard>
          <ExcSectionHead title="Decliners" />
          {MOVERS_DN.map((m, k) => (
            <div key={k} style={{
              display: 'grid', gridTemplateColumns: '60px 1fr 80px 100px 80px', gap: 10,
              padding: '12px 0', borderBottom: k === 4 ? 'none' : `1px solid ${EXC.lineSoft}`,
              alignItems: 'center', fontSize: 13,
            }}>
              <div style={{ fontWeight: 600 }}>{m.sym}</div>
              <div style={{ color: EXC.inkSoft, fontSize: 12 }}>{m.name}</div>
              <Spark seed={k * 11 + 5} up={false} w={80} h={22} color={EXC.down} strokeWidth={1.5} />
              <div style={{ textAlign: 'right', fontFamily: EXC.mono }}>{m.price}</div>
              <div style={{ textAlign: 'right' }}><ExcPill tone="down">{m.pct}</ExcPill></div>
            </div>
          ))}
        </ExcCard>
      </div>
    </ExcFrame>
  );
}

Object.assign(window, { ExcMarkets });
