// Direction C — Executive — Model Portfolios

function ExcPortfolios() {
  return (
    <ExcFrame page="Model Portfolios">
      <div style={{ marginBottom: 22, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.8, color: EXC.accent, textTransform: 'uppercase' }}>Advisory</div>
          <div style={{ fontFamily: EXC.display, fontSize: 32, fontWeight: 600, color: EXC.ink, letterSpacing: -0.4, marginTop: 4 }}>Model Portfolios</div>
          <div style={{ color: EXC.inkSoft, fontSize: 14, marginTop: 6 }}>Systematic allocations rebalanced quarterly — Q1 2026.</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {['All', 'Conservative', 'Moderate', 'Aggressive', 'Thematic'].map((t, i) => (
            <div key={t} style={{
              padding: '8px 14px', fontSize: 12.5, fontWeight: i === 0 ? 600 : 500,
              background: i === 0 ? EXC.ink : EXC.canvas, color: i === 0 ? '#fff' : EXC.inkSoft,
              border: `1px solid ${i === 0 ? EXC.ink : EXC.line}`, borderRadius: EXC.r,
            }}>{t}</div>
          ))}
        </div>
      </div>

      {/* Two-up hero cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20 }}>
        {PORTFOLIOS.slice(0, 2).map((p, k) => (
          <ExcCard key={k}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <ExcPill tone="accent">{p.strat}</ExcPill>
                <div style={{ fontFamily: EXC.display, fontSize: 24, fontWeight: 600, color: EXC.ink, letterSpacing: -0.3, marginTop: 8 }}>{p.name}</div>
              </div>
              <ExcPill tone={k === 1 ? 'up' : 'neutral'}>{p.risk}</ExcPill>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginTop: 20, paddingTop: 18, borderTop: `1px solid ${EXC.lineSoft}` }}>
              {[
                ['YTD', p.ytd, EXC.up],
                ['1 Year', p.oneYr, EXC.up],
                ['Sharpe', p.sharpe, EXC.ink],
                ['Max DD', '-9.2%', EXC.down],
              ].map(([l, v, c], i) => (
                <div key={i}>
                  <div style={{ fontSize: 11, color: EXC.mute, fontWeight: 600, letterSpacing: 0.4, textTransform: 'uppercase' }}>{l}</div>
                  <div style={{ fontFamily: EXC.mono, fontSize: 20, fontWeight: 600, color: c, marginTop: 4 }}>{v}</div>
                </div>
              ))}
            </div>

            <div style={{ marginTop: 22 }}>
              <div style={{ fontSize: 11, color: EXC.mute, fontWeight: 600, letterSpacing: 0.4, textTransform: 'uppercase', marginBottom: 8 }}>Allocation</div>
              <div style={{ display: 'flex', height: 10, borderRadius: 5, overflow: 'hidden' }}>
                <div style={{ width: '55%', background: EXC.ink }} />
                <div style={{ width: '30%', background: EXC.accent }} />
                <div style={{ width: '10%', background: EXC.highlight }} />
                <div style={{ width: '5%', background: EXC.mute }} />
              </div>
              <div style={{ display: 'flex', gap: 14, marginTop: 10, fontSize: 12, color: EXC.inkSoft }}>
                <LegCx c={EXC.ink} l="Equities 55%" />
                <LegCx c={EXC.accent} l="Fixed Inc 30%" />
                <LegCx c={EXC.highlight} l="Alts 10%" />
                <LegCx c={EXC.mute} l="Cash 5%" />
              </div>
            </div>

            <div style={{ marginTop: 20, display: 'flex', gap: 10 }}>
              <button style={{ background: EXC.ink, color: '#fff', border: 'none', padding: '9px 18px', borderRadius: EXC.r, fontSize: 13, fontWeight: 500 }}>View details</button>
              <button style={{ background: 'transparent', color: EXC.ink, border: `1px solid ${EXC.line}`, padding: '9px 18px', borderRadius: EXC.r, fontSize: 13, fontWeight: 500 }}>Factsheet</button>
            </div>
          </ExcCard>
        ))}
      </div>

      {/* Remaining compact */}
      <ExcCard pad={0}>
        <div style={{
          display: 'grid', gridTemplateColumns: '2fr 1.4fr 1fr 1fr 1fr 1fr 120px',
          padding: '14px 22px', fontSize: 11, fontWeight: 600, letterSpacing: 0.4,
          color: EXC.mute, textTransform: 'uppercase', borderBottom: `1px solid ${EXC.line}`,
        }}>
          <div>Portfolio</div><div>Strategy</div><div style={{ textAlign: 'right' }}>YTD</div>
          <div style={{ textAlign: 'right' }}>1Y</div><div style={{ textAlign: 'right' }}>Sharpe</div>
          <div>Risk</div><div></div>
        </div>
        {PORTFOLIOS.slice(2).map((p, k) => (
          <div key={k} style={{
            display: 'grid', gridTemplateColumns: '2fr 1.4fr 1fr 1fr 1fr 1fr 120px',
            padding: '16px 22px', borderBottom: k === PORTFOLIOS.length - 3 ? 'none' : `1px solid ${EXC.lineSoft}`,
            alignItems: 'center', fontSize: 13.5,
          }}>
            <div style={{ fontWeight: 600, color: EXC.ink }}>{p.name}</div>
            <div style={{ color: EXC.inkSoft }}>{p.strat}</div>
            <div style={{ textAlign: 'right' }}><ExcPill tone="up">{p.ytd}</ExcPill></div>
            <div style={{ textAlign: 'right' }}><ExcPill tone="up">{p.oneYr}</ExcPill></div>
            <div style={{ textAlign: 'right', fontFamily: EXC.mono }}>{p.sharpe}</div>
            <div style={{ color: EXC.inkSoft, fontSize: 12 }}>{p.risk}</div>
            <div style={{ textAlign: 'right', color: EXC.accent, fontSize: 13, fontWeight: 500 }}>View →</div>
          </div>
        ))}
      </ExcCard>
    </ExcFrame>
  );
}

function LegCx({ c, l }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 8, height: 8, background: c, borderRadius: 2 }} />{l}
    </span>
  );
}

Object.assign(window, { ExcPortfolios });
