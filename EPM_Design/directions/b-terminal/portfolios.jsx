// Direction B — Terminal — Model Portfolios

function TrmPortfolios() {
  return (
    <TrmFrame page="Model Portfolios">
      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 12 }}>
        {/* Left: portfolio list */}
        <TrmPanel title="MODELS · 5" pad={0}>
          {PORTFOLIOS.map((p, k) => (
            <div key={k} style={{
              padding: '10px 12px',
              background: k === 1 ? TRM.surface2 : 'transparent',
              borderLeft: k === 1 ? `2px solid ${TRM.accent}` : '2px solid transparent',
              borderBottom: k === PORTFOLIOS.length - 1 ? 'none' : `1px solid ${TRM.lineSoft}`,
              cursor: 'pointer',
            }}>
              <div style={{ fontFamily: TRM.mono, fontSize: 10.5, color: TRM.mute, letterSpacing: 0.5 }}>PM-{k + 1}</div>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: k === 1 ? TRM.accent : TRM.text, marginTop: 2 }}>{p.name}</div>
              <div style={{ fontFamily: TRM.mono, fontSize: 11, color: TRM.textSoft, marginTop: 2 }}>
                YTD <span style={{ color: TRM.up }}>{p.ytd}</span> · SHARPE {p.sharpe}
              </div>
            </div>
          ))}
        </TrmPanel>

        {/* Right: detail panels */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <TrmPanel title="PM-2 · STRATEGIC GROWTH · EQUITY TILT" right="AS OF 04.18.26 · 15:42 ET">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8 }}>
              {[
                ['YTD', '+11.42%', TRM.up],
                ['1Y', '+18.30%', TRM.up],
                ['3Y ann', '+9.44%', TRM.up],
                ['SHARPE', '0.91', TRM.text],
                ['VOL', '12.1%', TRM.text],
                ['MAX DD', '-14.2%', TRM.down],
              ].map((m, i) => (
                <div key={i} style={{ padding: '10px 12px', background: TRM.surface2, border: `1px solid ${TRM.line}` }}>
                  <div style={{ fontFamily: TRM.mono, fontSize: 10, color: TRM.mute, letterSpacing: 0.5 }}>{m[0]}</div>
                  <div style={{ fontFamily: TRM.mono, fontSize: 16, fontWeight: 600, color: m[2], marginTop: 4 }}>{m[1]}</div>
                </div>
              ))}
            </div>
          </TrmPanel>

          <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 12 }}>
            <TrmPanel title="ALLOCATION · ASSET CLASS" pad={0}>
              <div style={{ display: 'flex', height: 14 }}>
                {[
                  { c: TRM.accent, w: 72 }, { c: TRM.accent2, w: 18 },
                  { c: TRM.up, w: 6 }, { c: TRM.mute, w: 4 },
                ].map((s, i) => <div key={i} style={{ width: s.w + '%', background: s.c }} />)}
              </div>
              <div style={{ padding: 12 }}>
                {[
                  ['Equities',  '72%', TRM.accent],
                  ['Fixed Inc', '18%', TRM.accent2],
                  ['Alts',      '6%',  TRM.up],
                  ['Cash',      '4%',  TRM.mute],
                ].map((r, k) => (
                  <div key={k} style={{
                    display: 'grid', gridTemplateColumns: '12px 1fr 60px',
                    padding: '4px 0', fontFamily: TRM.mono, fontSize: 11.5, alignItems: 'center',
                  }}>
                    <div style={{ width: 8, height: 8, background: r[2] }} />
                    <div style={{ color: TRM.textSoft, paddingLeft: 8 }}>{r[0]}</div>
                    <div style={{ textAlign: 'right', color: TRM.text }}>{r[1]}</div>
                  </div>
                ))}
              </div>
            </TrmPanel>

            <TrmPanel title="TOP 10 HOLDINGS · EQUITIES" pad={0}>
              {[
                ['NVDA', 'Nvidia', '6.2%'], ['MSFT', 'Microsoft', '5.8%'], ['AAPL', 'Apple', '5.1%'],
                ['GOOGL', 'Alphabet', '3.9%'], ['META', 'Meta', '3.4%'], ['AMZN', 'Amazon', '3.2%'],
                ['AVGO', 'Broadcom', '2.8%'], ['LLY',  'Eli Lilly', '2.1%'], ['BRK.B','Berkshire', '1.9%'],
                ['JPM',  'JPMorgan', '1.8%'],
              ].map((r, k) => (
                <div key={k} style={{
                  display: 'grid', gridTemplateColumns: '60px 1fr 60px',
                  padding: '4px 12px', fontFamily: TRM.mono, fontSize: 11,
                  borderBottom: k === 9 ? 'none' : `1px solid ${TRM.lineSoft}`,
                }}>
                  <div style={{ color: TRM.accent }}>{r[0]}</div>
                  <div style={{ color: TRM.textSoft, fontFamily: TRM.sans, fontSize: 11.5 }}>{r[1]}</div>
                  <div style={{ textAlign: 'right' }}>{r[2]}</div>
                </div>
              ))}
            </TrmPanel>
          </div>

          <TrmPanel title="GROWTH OF $10,000 · SINCE INCEPTION 2018">
            <div style={{ background: '#05080C', border: `1px solid ${TRM.line}`, height: 200 }}>
              <svg viewBox="0 0 900 200" width="100%" height="100%" preserveAspectRatio="none">
                {[0, 1, 2, 3, 4].map(i => <line key={i} x1="0" x2="900" y1={i * 50} y2={i * 50} stroke={TRM.line} />)}
                <path d="M0,170 L90,160 L180,155 L270,142 L360,128 L450,118 L540,105 L630,92 L720,74 L810,60 L900,45"
                  fill="none" stroke={TRM.accent} strokeWidth="1.8" />
                <path d="M0,170 L90,165 L180,160 L270,150 L360,142 L450,134 L540,124 L630,115 L720,102 L810,90 L900,80"
                  fill="none" stroke={TRM.textSoft} strokeWidth="1.2" strokeDasharray="3 3" />
              </svg>
            </div>
            <div style={{ display: 'flex', gap: 18, marginTop: 8, fontFamily: TRM.mono, fontSize: 10.5, letterSpacing: 0.4 }}>
              <span style={{ color: TRM.accent }}>■ PM-2 · $23,840</span>
              <span style={{ color: TRM.textSoft }}>■ 60/40 BENCHMARK · $17,220</span>
            </div>
          </TrmPanel>
        </div>
      </div>
    </TrmFrame>
  );
}

Object.assign(window, { TrmPortfolios });
