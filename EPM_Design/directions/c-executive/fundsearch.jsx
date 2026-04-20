// Direction C — Executive — Fund Search

function ExcFundSearch() {
  return (
    <ExcFrame page="Fund Search">
      <div style={{ marginBottom: 22 }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.8, color: EXC.accent, textTransform: 'uppercase' }}>Research</div>
        <div style={{ fontFamily: EXC.display, fontSize: 32, fontWeight: 600, color: EXC.ink, letterSpacing: -0.4, marginTop: 4 }}>Fund Search</div>
        <div style={{ color: EXC.inkSoft, fontSize: 14, marginTop: 6 }}>32,000+ mutual funds and ETFs. Screen, compare, save.</div>
      </div>

      {/* Search hero */}
      <ExcCard pad={24} style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
          <div style={{
            flex: 1, background: EXC.bg, border: `1px solid ${EXC.line}`,
            padding: '12px 16px', borderRadius: EXC.r, fontSize: 14, color: EXC.mute,
            display: 'flex', alignItems: 'center', gap: 10,
          }}>
            <span style={{ fontSize: 16 }}>⌕</span>
            <span>Search by ticker, fund name, or manager…</span>
          </div>
          <button style={{ background: EXC.ink, color: '#fff', border: 'none', padding: '12px 22px', borderRadius: EXC.r, fontSize: 13, fontWeight: 600 }}>Search</button>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {[
            ['Category', 'Large Blend'],
            ['Expense', '≤ 0.50%'],
            ['AUM', '≥ $1B'],
            ['Rating', '★★★★ & up'],
            ['1Y Return', '≥ 10%'],
            ['+ Add filter'],
          ].map((f, i) => (
            <div key={i} style={{
              padding: '7px 13px', fontSize: 12.5, borderRadius: 999,
              background: i === 5 ? 'transparent' : EXC.accentSoft,
              color: i === 5 ? EXC.inkSoft : EXC.accent,
              border: i === 5 ? `1px dashed ${EXC.line}` : 'none',
              fontWeight: 500,
            }}>
              {f[1] ? <><span style={{ opacity: 0.7 }}>{f[0]}: </span>{f[1]} <span style={{ marginLeft: 6, opacity: 0.6 }}>×</span></> : f[0]}
            </div>
          ))}
        </div>
      </ExcCard>

      {/* Results */}
      <ExcCard pad={0}>
        <div style={{ padding: '16px 22px', borderBottom: `1px solid ${EXC.line}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: EXC.ink }}>7 results</div>
          <div style={{ display: 'flex', gap: 10, fontSize: 12, color: EXC.mute }}>
            <span>Sort: <b style={{ color: EXC.ink }}>1Y return ↓</b></span>
            <span>·</span>
            <span>Export</span>
          </div>
        </div>
        <div style={{
          display: 'grid', gridTemplateColumns: '80px 2.2fr 1.2fr 90px 90px 90px 100px 110px 100px',
          padding: '12px 22px', fontSize: 11, fontWeight: 600, letterSpacing: 0.4,
          color: EXC.mute, textTransform: 'uppercase', borderBottom: `1px solid ${EXC.line}`,
        }}>
          <div>Ticker</div><div>Name</div><div>Category</div>
          <div style={{ textAlign: 'right' }}>AUM</div>
          <div style={{ textAlign: 'right' }}>Expense</div>
          <div style={{ textAlign: 'right' }}>YTD</div>
          <div style={{ textAlign: 'right' }}>1Y</div>
          <div style={{ textAlign: 'center' }}>Trend</div>
          <div style={{ textAlign: 'right' }}>Rating</div>
        </div>
        {FUNDS.map((f, k) => (
          <div key={k} style={{
            display: 'grid', gridTemplateColumns: '80px 2.2fr 1.2fr 90px 90px 90px 100px 110px 100px',
            padding: '14px 22px', borderBottom: k === FUNDS.length - 1 ? 'none' : `1px solid ${EXC.lineSoft}`,
            alignItems: 'center', fontSize: 13,
          }}>
            <div style={{ fontFamily: EXC.mono, fontWeight: 700, color: EXC.ink }}>{f.ticker}</div>
            <div>
              <div style={{ fontWeight: 500, color: EXC.ink }}>{f.name}</div>
            </div>
            <div style={{ color: EXC.inkSoft, fontSize: 12 }}>{f.cat}</div>
            <div style={{ textAlign: 'right', fontFamily: EXC.mono }}>{f.aum}</div>
            <div style={{ textAlign: 'right', fontFamily: EXC.mono }}>{f.er}</div>
            <div style={{ textAlign: 'right' }}><ExcPill tone="up">{f.ytd}</ExcPill></div>
            <div style={{ textAlign: 'right' }}><ExcPill tone="up">{f.oneYr}</ExcPill></div>
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <Spark seed={k * 23 + 5} up w={90} h={22} color={EXC.up} strokeWidth={1.5} />
            </div>
            <div style={{ textAlign: 'right' }}>
              <Stars filled={f.stars} color={EXC.highlight} />
            </div>
          </div>
        ))}
      </ExcCard>
    </ExcFrame>
  );
}

Object.assign(window, { ExcFundSearch });
