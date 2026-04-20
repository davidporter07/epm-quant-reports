// Direction A — Editorial — Model Portfolios

function EdaPortfolios() {
  return (
    <EdaFrame page="Model Portfolios">
      <div style={{ marginBottom: 28 }}>
        <EdaKicker>Advisory</EdaKicker>
        <EdaH1 size={44}>Model Portfolios</EdaH1>
        <div style={{ marginTop: 10, fontFamily: EDA.serif, fontSize: 18, color: EDA.inkSoft, maxWidth: 760 }}>
          Five systematic allocations, rebalanced quarterly, aligned to risk tolerance and objectives.
        </div>
      </div>

      {/* Filter row */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 32, alignItems: 'center' }}>
        {['All', 'Conservative', 'Moderate', 'Aggressive', 'Thematic'].map((f, i) => (
          <div key={f} style={{
            padding: '8px 16px', fontSize: 12, fontWeight: 500, letterSpacing: 0.3,
            border: `1px solid ${i === 0 ? EDA.ink : EDA.rule}`,
            background: i === 0 ? EDA.ink : 'transparent',
            color: i === 0 ? EDA.paper : EDA.inkSoft, textTransform: 'uppercase',
          }}>{f}</div>
        ))}
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11, fontFamily: EDA.mono, color: EDA.mute, letterSpacing: 0.4 }}>AS OF Q1 2026</span>
      </div>

      {/* Portfolio cards — two-up hero + compact row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 28, marginBottom: 36 }}>
        {PORTFOLIOS.slice(0, 2).map((p, k) => (
          <div key={k} style={{ background: EDA.card, border: `1px solid ${EDA.rule}`, padding: 32 }}>
            <EdaKicker>{p.strat}</EdaKicker>
            <EdaH2 size={26}>{p.name}</EdaH2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 18, marginTop: 22, paddingTop: 18, borderTop: `1px solid ${EDA.ruleSoft}` }}>
              <Stat label="YTD" val={p.ytd} mono color={EDA.up} />
              <Stat label="1Y Return" val={p.oneYr} mono color={EDA.up} />
              <Stat label="Sharpe" val={p.sharpe} mono />
              <Stat label="Risk" val={p.risk} />
            </div>
            {/* Allocation bar */}
            <div style={{ marginTop: 24 }}>
              <div style={{ fontSize: 11, letterSpacing: 0.6, color: EDA.mute, fontFamily: EDA.sans, textTransform: 'uppercase', marginBottom: 8 }}>Allocation</div>
              <div style={{ display: 'flex', height: 10, border: `1px solid ${EDA.rule}` }}>
                <div style={{ width: '55%', background: EDA.ink }} />
                <div style={{ width: '30%', background: EDA.accent }} />
                <div style={{ width: '10%', background: '#7D8A9B' }} />
                <div style={{ width: '5%', background: EDA.rule }} />
              </div>
              <div style={{ display: 'flex', gap: 16, marginTop: 10, fontSize: 11, fontFamily: EDA.mono, color: EDA.inkSoft, letterSpacing: 0.3 }}>
                <LegDot c={EDA.ink} label="Equities 55%" />
                <LegDot c={EDA.accent} label="Fixed Inc 30%" />
                <LegDot c="#7D8A9B" label="Alts 10%" />
                <LegDot c={EDA.rule} label="Cash 5%" />
              </div>
            </div>
            <div style={{ marginTop: 24, display: 'flex', gap: 10 }}>
              <button style={{ border: `1px solid ${EDA.ink}`, background: EDA.ink, color: EDA.paper, padding: '9px 16px', fontSize: 12, letterSpacing: 0.4, textTransform: 'uppercase' }}>View details</button>
              <button style={{ border: `1px solid ${EDA.ink}`, background: 'transparent', color: EDA.ink, padding: '9px 16px', fontSize: 12, letterSpacing: 0.4, textTransform: 'uppercase' }}>Factsheet</button>
            </div>
          </div>
        ))}
      </div>

      {/* Compact rest */}
      <EdaSectionHeader title="Remaining models" right="3 MODELS" />
      <div style={{ background: EDA.card, border: `1px solid ${EDA.rule}` }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '2fr 1.4fr 1fr 1fr 1fr 1fr 120px',
          padding: '14px 22px', fontSize: 11, fontWeight: 600, letterSpacing: 0.8,
          color: EDA.mute, textTransform: 'uppercase', borderBottom: `1px solid ${EDA.rule}`,
        }}>
          <div>Portfolio</div><div>Strategy</div><div style={{ textAlign: 'right' }}>YTD</div>
          <div style={{ textAlign: 'right' }}>1Y</div><div style={{ textAlign: 'right' }}>Sharpe</div>
          <div>Risk</div><div style={{ textAlign: 'right' }}></div>
        </div>
        {PORTFOLIOS.slice(2).map((p, k) => (
          <div key={k} style={{
            display: 'grid', gridTemplateColumns: '2fr 1.4fr 1fr 1fr 1fr 1fr 120px',
            padding: '18px 22px', borderBottom: k === PORTFOLIOS.length - 3 ? 'none' : `1px solid ${EDA.ruleSoft}`,
            alignItems: 'center', fontSize: 14,
          }}>
            <div style={{ fontFamily: EDA.serif, fontSize: 17, fontWeight: 600 }}>{p.name}</div>
            <div style={{ color: EDA.inkSoft }}>{p.strat}</div>
            <div style={{ textAlign: 'right', fontFamily: EDA.mono, color: EDA.up }}>{p.ytd}</div>
            <div style={{ textAlign: 'right', fontFamily: EDA.mono, color: EDA.up }}>{p.oneYr}</div>
            <div style={{ textAlign: 'right', fontFamily: EDA.mono }}>{p.sharpe}</div>
            <div style={{ color: EDA.inkSoft, fontSize: 12 }}>{p.risk}</div>
            <div style={{ textAlign: 'right', color: EDA.accent, fontSize: 12, letterSpacing: 0.4, textTransform: 'uppercase' }}>View →</div>
          </div>
        ))}
      </div>
    </EdaFrame>
  );
}

function Stat({ label, val, mono, color }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, letterSpacing: 0.8, color: EDA.mute, fontFamily: EDA.sans, textTransform: 'uppercase', fontWeight: 600, marginBottom: 6 }}>{label}</div>
      <div style={{ fontFamily: mono ? EDA.mono : EDA.serif, fontSize: mono ? 22 : 18, color: color || EDA.ink, fontWeight: mono ? 500 : 600 }}>{val}</div>
    </div>
  );
}
function LegDot({ c, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 8, height: 8, background: c }} />{label}
    </span>
  );
}

Object.assign(window, { EdaPortfolios });
