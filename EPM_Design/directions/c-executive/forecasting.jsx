// Direction C — Executive — Forecasting

function ExcForecasting() {
  return (
    <ExcFrame page="Forecasting">
      <div style={{ marginBottom: 22 }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.8, color: EXC.accent, textTransform: 'uppercase' }}>EPM Research</div>
        <div style={{ fontFamily: EXC.display, fontSize: 32, fontWeight: 600, color: EXC.ink, letterSpacing: -0.4, marginTop: 4 }}>Forecasting</div>
        <div style={{ color: EXC.inkSoft, fontSize: 14, marginTop: 6, maxWidth: 720 }}>
          House views on growth, inflation, rates, and earnings — with explicit deltas to consensus and confidence.
        </div>
      </div>

      {/* Three summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 22 }}>
        {[
          { k: 'Growth', t: 'Above consensus', d: '+25 bp', v: '2.35%', sub: 'US Real GDP, Q2', up: true },
          { k: 'Inflation', t: 'Below consensus', d: '-15 bp', v: '2.45%', sub: 'Core PCE, YE 2026', up: false },
          { k: 'Policy', t: 'More cuts expected', d: '-25 bp', v: '4.00%', sub: 'Fed Funds, YE 2026', up: false },
        ].map((c, i) => (
          <ExcCard key={i}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <ExcPill tone="accent">{c.k}</ExcPill>
              <ExcPill tone={c.up ? 'up' : 'down'}>{c.d} vs consensus</ExcPill>
            </div>
            <div style={{ fontSize: 36, fontWeight: 600, color: EXC.ink, letterSpacing: -0.6, fontFamily: EXC.mono, marginTop: 14 }}>{c.v}</div>
            <div style={{ fontSize: 13, color: EXC.inkSoft, marginTop: 4 }}>{c.sub}</div>
            <div style={{ marginTop: 12, fontSize: 13, color: EXC.text, fontWeight: 500 }}>{c.t}</div>
          </ExcCard>
        ))}
      </div>

      {/* Detailed table + scenarios */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 20 }}>
        <ExcCard pad={0}>
          <div style={{ padding: '18px 22px', borderBottom: `1px solid ${EXC.line}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ fontSize: 16, fontWeight: 600, color: EXC.ink }}>House views vs consensus</div>
            <div style={{ fontSize: 12, color: EXC.mute }}>Updated Apr 14, 2026</div>
          </div>
          <div style={{
            display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 100px',
            padding: '12px 22px', fontSize: 11, fontWeight: 600, letterSpacing: 0.4,
            color: EXC.mute, textTransform: 'uppercase', borderBottom: `1px solid ${EXC.line}`,
          }}>
            <div>Metric</div><div style={{ textAlign: 'right' }}>Consensus</div>
            <div style={{ textAlign: 'right' }}>EPM</div><div style={{ textAlign: 'right' }}>Δ</div>
            <div style={{ textAlign: 'right' }}>Confidence</div>
          </div>
          {FORECASTS.map((f, k) => (
            <div key={k} style={{
              display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 100px',
              padding: '14px 22px', borderBottom: k === FORECASTS.length - 1 ? 'none' : `1px solid ${EXC.lineSoft}`,
              alignItems: 'center', fontSize: 13,
            }}>
              <div style={{ color: EXC.text, fontWeight: 500 }}>{f.metric}</div>
              <div style={{ textAlign: 'right', fontFamily: EXC.mono, color: EXC.inkSoft }}>{f.consensus}</div>
              <div style={{ textAlign: 'right', fontFamily: EXC.mono, color: EXC.ink, fontWeight: 600 }}>{f.epm}</div>
              <div style={{ textAlign: 'right' }}>
                <ExcPill tone={f.delta.startsWith('-') ? 'down' : 'up'}>{f.delta}</ExcPill>
              </div>
              <div style={{ textAlign: 'right' }}>
                <span style={{ display: 'inline-flex', gap: 2 }}>
                  {[1,2,3].map(i => (
                    <span key={i} style={{
                      width: 18, height: 5, borderRadius: 2,
                      background: i <= ({Low: 1, Med: 2, High: 3}[f.conf]) ? EXC.accent : EXC.lineSoft,
                    }} />
                  ))}
                </span>
              </div>
            </div>
          ))}
        </ExcCard>

        <ExcCard>
          <ExcSectionHead title="Scenario probabilities" />
          {[
            { n: 'Soft landing', p: 55, c: EXC.up },
            { n: 'No landing', p: 25, c: EXC.highlight },
            { n: 'Mild recession', p: 15, c: EXC.down },
            { n: 'Stagflation', p: 5, c: EXC.mute },
          ].map((s, k) => (
            <div key={k} style={{ padding: '12px 0', borderBottom: k === 3 ? 'none' : `1px solid ${EXC.lineSoft}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 500 }}>{s.n}</span>
                <span style={{ fontFamily: EXC.mono, fontSize: 14, fontWeight: 600, color: s.c }}>{s.p}%</span>
              </div>
              <div style={{ background: EXC.lineSoft, height: 6, borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: s.p + '%', height: '100%', background: s.c }} />
              </div>
            </div>
          ))}
          <div style={{ marginTop: 16, padding: 14, background: EXC.accentSoft, borderRadius: EXC.r, fontSize: 12.5, color: EXC.ink, lineHeight: 1.5 }}>
            <b>EPM take.</b> Breadth is repairing faster than sentiment — we'd fade defensive rotation on further softness in cyclicals.
          </div>
        </ExcCard>
      </div>
    </ExcFrame>
  );
}

Object.assign(window, { ExcForecasting });
