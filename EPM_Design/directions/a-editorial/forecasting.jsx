// Direction A — Editorial — Forecasting

function EdaForecasting() {
  return (
    <EdaFrame page="Forecasting">
      <div style={{ marginBottom: 28 }}>
        <EdaKicker>EPM Research</EdaKicker>
        <EdaH1 size={44}>Forecasting</EdaH1>
        <div style={{ marginTop: 10, fontFamily: EDA.serif, fontSize: 18, color: EDA.inkSoft, maxWidth: 760 }}>
          Our house views across growth, inflation, rates, and earnings — updated monthly, benchmarked against consensus.
        </div>
      </div>

      {/* Two-up: macro call vs market call */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 36, marginBottom: 48 }}>
        <div>
          <div style={{ borderTop: `2px solid ${EDA.ink}`, paddingTop: 14 }}>
            <EdaKicker>Macro</EdaKicker>
            <EdaH2 size={26}>Patient, not pivoting.</EdaH2>
            <div style={{ marginTop: 12, fontFamily: EDA.serif, fontSize: 16, lineHeight: 1.6, color: EDA.inkSoft }}>
              Real GDP tracks 2.3% into Q2 on firm services consumption and a bottoming goods cycle.
              Core PCE decelerates to 2.45% by year-end, below consensus at 2.60%, giving the Fed room
              for two cuts in H2.
            </div>
          </div>
        </div>
        <div>
          <div style={{ borderTop: `2px solid ${EDA.ink}`, paddingTop: 14 }}>
            <EdaKicker>Markets</EdaKicker>
            <EdaH2 size={26}>Earnings do the heavy lifting.</EdaH2>
            <div style={{ marginTop: 12, fontFamily: EDA.serif, fontSize: 16, lineHeight: 1.6, color: EDA.inkSoft }}>
              S&P 500 EPS $278 (Street: $271) with margin expansion in Tech & Comm Services.
              Ten-year yield drifts to 3.90% on softer growth; duration adds to balanced portfolios.
            </div>
          </div>
        </div>
      </div>

      {/* Consensus table */}
      <EdaSectionHeader kicker="House views vs consensus" title="Key forecasts" right="UPDATED APR 14, 2026" />
      <div style={{ background: EDA.card, border: `1px solid ${EDA.rule}` }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr', padding: '14px 22px',
          fontSize: 11, letterSpacing: 0.8, fontFamily: EDA.sans, fontWeight: 600,
          color: EDA.mute, textTransform: 'uppercase', borderBottom: `1px solid ${EDA.rule}`,
        }}>
          <div>Metric</div><div style={{ textAlign: 'right' }}>Consensus</div>
          <div style={{ textAlign: 'right' }}>EPM</div><div style={{ textAlign: 'right' }}>Δ</div>
          <div style={{ textAlign: 'right' }}>Confidence</div>
        </div>
        {FORECASTS.map((f, k) => (
          <div key={k} style={{
            display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr',
            padding: '16px 22px', borderBottom: k === FORECASTS.length - 1 ? 'none' : `1px solid ${EDA.ruleSoft}`,
            fontSize: 14, alignItems: 'center',
          }}>
            <div style={{ fontFamily: EDA.serif, fontSize: 16, color: EDA.ink }}>{f.metric}</div>
            <div style={{ textAlign: 'right', fontFamily: EDA.mono, color: EDA.inkSoft }}>{f.consensus}</div>
            <div style={{ textAlign: 'right', fontFamily: EDA.mono, fontWeight: 600, color: EDA.ink }}>{f.epm}</div>
            <div style={{ textAlign: 'right', fontFamily: EDA.mono, color: f.delta.startsWith('-') ? EDA.down : EDA.up }}>
              {f.delta}
            </div>
            <div style={{ textAlign: 'right' }}>
              <span style={{
                fontSize: 11, letterSpacing: 0.5, padding: '3px 9px',
                border: `1px solid ${EDA.rule}`, color: EDA.inkSoft, fontFamily: EDA.sans,
                textTransform: 'uppercase', fontWeight: 500,
              }}>{f.conf}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Scenario fan + methodology */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 36, marginTop: 48 }}>
        <div>
          <EdaSectionHeader title="Rate path scenarios" right="FED FUNDS · 2026–2027" />
          <div style={{ background: EDA.card, border: `1px solid ${EDA.rule}`, height: 280, padding: 16 }}>
            <svg viewBox="0 0 600 240" width="100%" height="100%" preserveAspectRatio="none">
              {[0, 1, 2, 3, 4].map((i) => (
                <line key={i} x1="0" x2="600" y1={i * 60} y2={i * 60} stroke={EDA.ruleSoft} />
              ))}
              {/* bull/bear fan */}
              <path d="M0,120 L100,115 L200,105 L300,95 L400,80 L500,65 L600,50 L600,160 L500,160 L400,150 L300,140 L200,130 L100,125 Z"
                fill={EDA.accent} opacity="0.14" />
              <path d="M0,120 L100,112 L200,100 L300,88 L400,72 L500,55 L600,40"
                fill="none" stroke={EDA.up} strokeWidth="1.5" strokeDasharray="4 3" />
              <path d="M0,120 L100,118 L200,110 L300,100 L400,90 L500,80 L600,70"
                fill="none" stroke={EDA.ink} strokeWidth="2" />
              <path d="M0,120 L100,125 L200,128 L300,135 L400,145 L500,155 L600,165"
                fill="none" stroke={EDA.down} strokeWidth="1.5" strokeDasharray="4 3" />
            </svg>
            <div style={{ display: 'flex', gap: 22, fontSize: 12, fontFamily: EDA.mono, color: EDA.inkSoft, paddingLeft: 12, paddingTop: 6 }}>
              <span>— EPM BASE · 4.00%</span>
              <span style={{ color: EDA.up }}>-- BULL · 3.50%</span>
              <span style={{ color: EDA.down }}>-- BEAR · 4.75%</span>
            </div>
          </div>
        </div>
        <div>
          <EdaSectionHeader title="Methodology" />
          <div style={{ fontFamily: EDA.serif, fontSize: 15, lineHeight: 1.65, color: EDA.inkSoft }}>
            Forecasts combine a structural macro model (Taylor-rule rates, NKPC inflation) with a
            cross-sectional earnings model tuned on sector margins. Revisions are published the first
            Wednesday of each month; delta against Bloomberg consensus is reported unadjusted.
          </div>
          <div style={{ marginTop: 18, display: 'flex', gap: 12 }}>
            <button style={{ border: `1px solid ${EDA.ink}`, background: EDA.ink, color: EDA.paper, padding: '10px 18px', fontSize: 12, letterSpacing: 0.4, textTransform: 'uppercase' }}>Read full paper</button>
            <button style={{ border: `1px solid ${EDA.ink}`, background: 'transparent', color: EDA.ink, padding: '10px 18px', fontSize: 12, letterSpacing: 0.4, textTransform: 'uppercase' }}>Download PDF</button>
          </div>
        </div>
      </div>
    </EdaFrame>
  );
}

Object.assign(window, { EdaForecasting });
