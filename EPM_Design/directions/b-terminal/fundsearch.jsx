// Direction B — Terminal — Fund Search

function TrmFundSearch() {
  return (
    <TrmFrame page="Fund Search">
      {/* Query builder bar */}
      <div style={{
        background: TRM.surface, border: `1px solid ${TRM.line}`,
        padding: '10px 12px', marginBottom: 12,
        display: 'grid', gridTemplateColumns: 'repeat(6, 1fr) 120px', gap: 8,
        fontFamily: TRM.mono, fontSize: 11,
      }}>
        {[
          ['TYPE', 'MUTUAL + ETF'],
          ['CATEGORY', 'LARGE BLEND'],
          ['EXP ≤', '0.50%'],
          ['AUM ≥', '$1B'],
          ['RATING ≥', '4★'],
          ['1Y RET ≥', '10%'],
        ].map((f, k) => (
          <div key={k}>
            <div style={{ fontSize: 9.5, color: TRM.mute, letterSpacing: 0.5 }}>{f[0]}</div>
            <div style={{ background: '#05080C', border: `1px solid ${TRM.line}`, padding: '5px 8px', color: TRM.accent, marginTop: 3 }}>{f[1]}</div>
          </div>
        ))}
        <div>
          <div style={{ fontSize: 9.5, color: TRM.mute, letterSpacing: 0.5 }}>&nbsp;</div>
          <div style={{ background: TRM.accent, color: '#000', padding: '5px 8px', marginTop: 3, textAlign: 'center', fontWeight: 700, letterSpacing: 0.6 }}>
            RUN ▶
          </div>
        </div>
      </div>

      <TrmPanel title="FUND SEARCH · RESULTS" right="7 MATCHES · SORT: 1Y RET ↓" pad={0}>
        <div style={{
          display: 'grid', gridTemplateColumns: '60px 2fr 1fr 80px 70px 80px 80px 100px 60px 80px',
          padding: '6px 12px', fontFamily: TRM.mono, fontSize: 10, color: TRM.mute, letterSpacing: 0.4,
          borderBottom: `1px solid ${TRM.line}`,
        }}>
          <div>TICKER</div><div>NAME</div><div>CATEGORY</div>
          <div style={{ textAlign: 'right' }}>AUM</div>
          <div style={{ textAlign: 'right' }}>EXP</div>
          <div style={{ textAlign: 'right' }}>YTD</div>
          <div style={{ textAlign: 'right' }}>1Y</div>
          <div style={{ textAlign: 'center' }}>12M TREND</div>
          <div style={{ textAlign: 'center' }}>★</div>
          <div style={{ textAlign: 'right' }}>ACTION</div>
        </div>
        {FUNDS.map((f, k) => (
          <div key={k} style={{
            display: 'grid', gridTemplateColumns: '60px 2fr 1fr 80px 70px 80px 80px 100px 60px 80px',
            padding: '6px 12px', fontFamily: TRM.mono, fontSize: 11,
            alignItems: 'center',
            borderBottom: k === FUNDS.length - 1 ? 'none' : `1px solid ${TRM.lineSoft}`,
            background: k % 2 ? TRM.surface2 : 'transparent',
          }}>
            <div style={{ color: TRM.accent }}>{f.ticker}</div>
            <div style={{ color: TRM.text, fontFamily: TRM.sans, fontSize: 11.5 }}>{f.name}</div>
            <div style={{ color: TRM.textSoft, fontSize: 10.5 }}>{f.cat}</div>
            <div style={{ textAlign: 'right' }}>{f.aum}</div>
            <div style={{ textAlign: 'right' }}>{f.er}</div>
            <TrmDelta up><div style={{ textAlign: 'right' }}>{f.ytd}</div></TrmDelta>
            <TrmDelta up><div style={{ textAlign: 'right' }}>{f.oneYr}</div></TrmDelta>
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <Spark seed={k * 19 + 2} up w={90} h={16} color={TRM.up} strokeWidth={1} />
            </div>
            <div style={{ textAlign: 'center', color: TRM.accent, fontSize: 11 }}>{'★'.repeat(f.stars)}</div>
            <div style={{ textAlign: 'right', color: TRM.accent2, letterSpacing: 0.5 }}>ANALYZE</div>
          </div>
        ))}
      </TrmPanel>

      {/* Peer comparison */}
      <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <TrmPanel title="SELECTED · VTSAX · PEER COMPARE" right="LARGE BLEND">
          <div style={{ fontFamily: TRM.mono, fontSize: 11 }}>
            {[
              ['1Y RETURN',   '+14.22%', 'TOP 18%'],
              ['3Y ANN',      '+11.80%', 'TOP 22%'],
              ['5Y ANN',      '+13.10%', 'TOP 14%'],
              ['EXPENSE',     '0.04%',   'TOP 1%'],
              ['SHARPE 3Y',   '0.88',    'TOP 20%'],
              ['CAPTURE UP',  '98%',     'TOP 30%'],
              ['CAPTURE DN',  '92%',     'TOP 40%'],
            ].map((r, k) => (
              <div key={k} style={{
                display: 'grid', gridTemplateColumns: '1fr 90px 90px',
                padding: '5px 0', borderBottom: k === 6 ? 'none' : `1px solid ${TRM.lineSoft}`,
              }}>
                <div style={{ color: TRM.textSoft, letterSpacing: 0.4 }}>{r[0]}</div>
                <div style={{ textAlign: 'right', color: TRM.text }}>{r[1]}</div>
                <div style={{ textAlign: 'right', color: TRM.accent }}>{r[2]}</div>
              </div>
            ))}
          </div>
        </TrmPanel>
        <TrmPanel title="RISK / RETURN · 3Y">
          <div style={{ background: '#05080C', border: `1px solid ${TRM.line}`, height: 220, position: 'relative' }}>
            <svg viewBox="0 0 400 220" width="100%" height="100%" preserveAspectRatio="none">
              {[0, 1, 2, 3, 4].map(i => <line key={i} x1="0" x2="400" y1={i * 55} y2={i * 55} stroke={TRM.line} />)}
              {[0, 1, 2, 3, 4].map(i => <line key={i} x1={i * 100} x2={i * 100} y1="0" y2="220" stroke={TRM.line} />)}
              {[
                [80, 120, 4, TRM.textSoft], [140, 100, 4, TRM.textSoft], [200, 90, 4, TRM.textSoft],
                [220, 110, 4, TRM.textSoft], [150, 130, 4, TRM.textSoft], [260, 80, 4, TRM.textSoft],
                [180, 105, 4, TRM.textSoft], [280, 70, 4, TRM.textSoft],
                [160, 75, 7, TRM.accent],
              ].map(([x, y, r, c], k) => (
                <circle key={k} cx={x} cy={y} r={r} fill={c} opacity={c === TRM.accent ? 1 : 0.5} />
              ))}
            </svg>
            <div style={{ position: 'absolute', bottom: 6, left: 8, fontFamily: TRM.mono, fontSize: 10, color: TRM.mute, letterSpacing: 0.4 }}>VOL →</div>
            <div style={{ position: 'absolute', top: 6, left: 8, fontFamily: TRM.mono, fontSize: 10, color: TRM.mute, letterSpacing: 0.4, transform: 'rotate(-90deg)', transformOrigin: 'left top' }}>RET →</div>
          </div>
        </TrmPanel>
      </div>
    </TrmFrame>
  );
}

Object.assign(window, { TrmFundSearch });
