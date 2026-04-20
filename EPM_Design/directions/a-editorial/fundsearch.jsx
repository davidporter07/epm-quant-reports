// Direction A — Editorial — Fund Search

function EdaFundSearch() {
  return (
    <EdaFrame page="Fund Search">
      <div style={{ marginBottom: 28 }}>
        <EdaKicker>Research</EdaKicker>
        <EdaH1 size={44}>Fund Search</EdaH1>
        <div style={{ marginTop: 10, fontFamily: EDA.serif, fontSize: 18, color: EDA.inkSoft, maxWidth: 760 }}>
          Screen 32,000+ mutual funds and ETFs by category, cost, performance, and rating.
        </div>
      </div>

      {/* Filter rail + results */}
      <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 36 }}>
        <aside>
          <div style={{ borderTop: `2px solid ${EDA.ink}`, paddingTop: 14, marginBottom: 20 }}>
            <EdaKicker>Filters</EdaKicker>
            <EdaH2 size={18}>Refine results</EdaH2>
          </div>
          {[
            { t: 'Category', v: ['Large Blend', 'Large Growth', 'Large Value', 'Allocation 50-70', '+ 14 more'] },
            { t: 'Expense ratio', v: ['< 0.10%', '0.10 – 0.50%', '0.50 – 1.00%', '> 1.00%'] },
            { t: 'Rating', v: ['5 ★', '4 ★ & up', '3 ★ & up'] },
            { t: 'AUM', v: ['< $1B', '$1 – $10B', '$10 – $100B', '> $100B'] },
          ].map((g, i) => (
            <div key={i} style={{ marginBottom: 24, borderBottom: `1px solid ${EDA.ruleSoft}`, paddingBottom: 18 }}>
              <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.8, color: EDA.ink, textTransform: 'uppercase', marginBottom: 10 }}>{g.t}</div>
              {g.v.map((v, k) => (
                <div key={k} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, color: EDA.inkSoft, padding: '5px 0' }}>
                  <span style={{ width: 13, height: 13, border: `1px solid ${EDA.rule}`, background: k === 0 && i === 0 ? EDA.ink : 'transparent' }} />
                  {v}
                </div>
              ))}
            </div>
          ))}
        </aside>

        <section>
          {/* Search + meta */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 14, alignItems: 'center' }}>
            <div style={{
              flex: 1, border: `1px solid ${EDA.ink}`, padding: '12px 16px',
              fontFamily: EDA.mono, fontSize: 13, color: EDA.ink, display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <span style={{ fontSize: 15 }}>⌕</span>
              <span style={{ color: EDA.mute }}>Search by ticker, fund name, or manager…</span>
            </div>
            <button style={{ border: `1px solid ${EDA.ink}`, background: EDA.ink, color: EDA.paper, padding: '12px 22px', fontSize: 12, letterSpacing: 0.4, textTransform: 'uppercase' }}>Apply</button>
          </div>
          <div style={{ fontSize: 12, fontFamily: EDA.mono, color: EDA.mute, letterSpacing: 0.4, marginBottom: 14 }}>
            7 RESULTS · SORTED BY 1Y RETURN · SHOWING 1–7
          </div>

          {/* Results table */}
          <div style={{ background: EDA.card, border: `1px solid ${EDA.rule}` }}>
            <div style={{
              display: 'grid', gridTemplateColumns: '80px 2.4fr 1.2fr 80px 90px 90px 100px 80px',
              padding: '14px 20px', fontSize: 10.5, fontWeight: 600, letterSpacing: 0.8,
              color: EDA.mute, textTransform: 'uppercase', borderBottom: `1px solid ${EDA.rule}`,
            }}>
              <div>Ticker</div><div>Name</div><div>Category</div>
              <div style={{ textAlign: 'right' }}>AUM</div>
              <div style={{ textAlign: 'right' }}>Expense</div>
              <div style={{ textAlign: 'right' }}>YTD</div>
              <div style={{ textAlign: 'right' }}>1Y</div>
              <div style={{ textAlign: 'right' }}>Rating</div>
            </div>
            {FUNDS.map((f, k) => (
              <div key={k} style={{
                display: 'grid', gridTemplateColumns: '80px 2.4fr 1.2fr 80px 90px 90px 100px 80px',
                padding: '14px 20px', borderBottom: k === FUNDS.length - 1 ? 'none' : `1px solid ${EDA.ruleSoft}`,
                alignItems: 'center', fontSize: 13,
              }}>
                <div style={{ fontFamily: EDA.mono, fontWeight: 600 }}>{f.ticker}</div>
                <div style={{ fontFamily: EDA.serif, fontSize: 15, color: EDA.ink }}>{f.name}</div>
                <div style={{ color: EDA.inkSoft, fontSize: 12 }}>{f.cat}</div>
                <div style={{ textAlign: 'right', fontFamily: EDA.mono }}>{f.aum}</div>
                <div style={{ textAlign: 'right', fontFamily: EDA.mono }}>{f.er}</div>
                <div style={{ textAlign: 'right', fontFamily: EDA.mono, color: EDA.up }}>{f.ytd}</div>
                <div style={{ textAlign: 'right', fontFamily: EDA.mono, color: EDA.up }}>{f.oneYr}</div>
                <div style={{ textAlign: 'right' }}><Stars filled={f.stars} color={EDA.accent} /></div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </EdaFrame>
  );
}

Object.assign(window, { EdaFundSearch });
