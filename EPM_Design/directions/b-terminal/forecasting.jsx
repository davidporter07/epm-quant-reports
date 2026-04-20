// Direction B — Terminal — Forecasting

function TrmForecasting() {
  return (
    <TrmFrame page="Forecasting">
      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 12, marginBottom: 12 }}>
        <TrmPanel title="EPM HOUSE VIEW · CONSENSUS DELTA" right="UPDATED 04.14.26" pad={0}>
          <div style={{
            display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr 90px',
            padding: '6px 12px', fontFamily: TRM.mono, fontSize: 10, color: TRM.mute, letterSpacing: 0.4,
            borderBottom: `1px solid ${TRM.line}`,
          }}>
            <div>METRIC</div>
            <div style={{ textAlign: 'right' }}>CONS</div>
            <div style={{ textAlign: 'right' }}>EPM</div>
            <div style={{ textAlign: 'right' }}>Δ</div>
            <div style={{ textAlign: 'center' }}>CONF</div>
            <div style={{ textAlign: 'right' }}>REVISED</div>
          </div>
          {FORECASTS.map((f, k) => (
            <div key={k} style={{
              display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr 90px',
              padding: '8px 12px', fontFamily: TRM.mono, fontSize: 11.5,
              alignItems: 'center',
              borderBottom: k === FORECASTS.length - 1 ? 'none' : `1px solid ${TRM.lineSoft}`,
            }}>
              <div style={{ color: TRM.text, fontFamily: TRM.sans, fontSize: 12 }}>{f.metric}</div>
              <div style={{ textAlign: 'right', color: TRM.textSoft }}>{f.consensus}</div>
              <div style={{ textAlign: 'right', color: TRM.accent, fontWeight: 600 }}>{f.epm}</div>
              <TrmDelta up={!f.delta.startsWith('-')}><div style={{ textAlign: 'right' }}>{f.delta}</div></TrmDelta>
              <div style={{ textAlign: 'center' }}>
                {[1, 2, 3].map(i => (
                  <span key={i} style={{
                    display: 'inline-block', width: 6, height: 10, marginRight: 2,
                    background: i <= ({ Low: 1, Med: 2, High: 3 }[f.conf]) ? TRM.accent : TRM.line,
                  }} />
                ))}
              </div>
              <div style={{ textAlign: 'right', color: TRM.mute, fontSize: 10.5 }}>04.14.26</div>
            </div>
          ))}
        </TrmPanel>

        <TrmPanel title="SCENARIO PROBABILITIES">
          {[
            { n: 'SOFT LANDING',  p: 55, c: TRM.up },
            { n: 'NO LANDING',    p: 25, c: TRM.accent },
            { n: 'MILD RECESSION',p: 15, c: TRM.down },
            { n: 'STAGFLATION',   p: 5,  c: TRM.mute },
          ].map((s, k) => (
            <div key={k} style={{ padding: '7px 0', borderBottom: k === 3 ? 'none' : `1px solid ${TRM.lineSoft}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: TRM.mono, fontSize: 11, marginBottom: 4 }}>
                <span style={{ color: TRM.textSoft, letterSpacing: 0.4 }}>{s.n}</span>
                <span style={{ color: s.c, fontWeight: 600 }}>{s.p}%</span>
              </div>
              <div style={{ background: TRM.surface2, height: 6 }}>
                <div style={{ width: s.p + '%', height: '100%', background: s.c }} />
              </div>
            </div>
          ))}
        </TrmPanel>
      </div>

      {/* Fan chart + revisions log */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 12 }}>
        <TrmPanel title="FED FUNDS PATH · EPM vs OIS vs SEP" right="2026 · 2027">
          <div style={{ background: '#05080C', height: 260, border: `1px solid ${TRM.line}`, padding: 8, position: 'relative' }}>
            <svg viewBox="0 0 700 240" width="100%" height="100%" preserveAspectRatio="none">
              {[0, 1, 2, 3, 4].map((i) => (
                <line key={i} x1="0" x2="700" y1={i * 60} y2={i * 60} stroke={TRM.line} />
              ))}
              <path d="M0,60 L120,80 L240,100 L360,120 L480,130 L600,135 L700,140 L700,180 L600,165 L480,155 L360,145 L240,125 L120,105 L0,85 Z"
                fill={TRM.accent} opacity="0.12" />
              <path d="M0,72 L120,92 L240,112 L360,130 L480,140 L600,145 L700,148" fill="none" stroke={TRM.accent} strokeWidth="1.8" />
              <path d="M0,72 L120,84 L240,96 L360,108 L480,116 L600,122 L700,125" fill="none" stroke={TRM.accent2} strokeWidth="1.5" strokeDasharray="4 3" />
              <path d="M0,72 L120,88 L240,104 L360,120 L480,132 L600,140 L700,146" fill="none" stroke={TRM.up} strokeWidth="1.5" strokeDasharray="2 2" />
            </svg>
          </div>
          <div style={{ display: 'flex', gap: 18, paddingTop: 8, fontFamily: TRM.mono, fontSize: 10.5, letterSpacing: 0.4 }}>
            <span style={{ color: TRM.accent }}>■ EPM · 4.00%</span>
            <span style={{ color: TRM.accent2 }}>■ OIS · 4.18%</span>
            <span style={{ color: TRM.up }}>■ FED SEP · 4.25%</span>
          </div>
        </TrmPanel>

        <TrmPanel title="REVISION LOG" right="LAST 30D" pad={0}>
          {[
            { d: '04.14', m: 'Core PCE YE26',       o: '2.55%', n: '2.45%', dir: 'down' },
            { d: '04.07', m: 'S&P EPS 2026',        o: '$274',  n: '$278',  dir: 'up'   },
            { d: '03.28', m: 'Fed Funds YE26',      o: '4.25%', n: '4.00%', dir: 'down' },
            { d: '03.21', m: 'Real GDP Q2',         o: '2.20%', n: '2.35%', dir: 'up'   },
            { d: '03.14', m: 'Brent Q4 avg',        o: '$80',   n: '$76',   dir: 'down' },
            { d: '03.07', m: 'EUR/USD YE26',        o: '1.10',  n: '1.12',  dir: 'up'   },
            { d: '02.28', m: 'US UNR YE26',         o: '4.1%',  n: '4.0%',  dir: 'down' },
          ].map((r, k) => (
            <div key={k} style={{
              display: 'grid', gridTemplateColumns: '50px 1fr 60px 60px 24px',
              padding: '7px 12px', fontFamily: TRM.mono, fontSize: 11,
              alignItems: 'center',
              borderBottom: k === 6 ? 'none' : `1px solid ${TRM.lineSoft}`,
            }}>
              <div style={{ color: TRM.mute }}>{r.d}</div>
              <div style={{ color: TRM.textSoft, fontFamily: TRM.sans }}>{r.m}</div>
              <div style={{ textAlign: 'right', color: TRM.mute }}>{r.o}</div>
              <div style={{ textAlign: 'right', color: TRM.accent }}>{r.n}</div>
              <div style={{ textAlign: 'right', color: r.dir === 'up' ? TRM.up : TRM.down }}>{r.dir === 'up' ? '▲' : '▼'}</div>
            </div>
          ))}
        </TrmPanel>
      </div>
    </TrmFrame>
  );
}

Object.assign(window, { TrmForecasting });
