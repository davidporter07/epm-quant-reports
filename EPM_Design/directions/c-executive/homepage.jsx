// Direction C — Executive — Homepage

function ExcHomepage() {
  const hero = HEADLINES[0];
  return (
    <ExcFrame page="Homepage">
      {/* Welcome strip */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 22 }}>
        <div>
          <div style={{ fontSize: 12, color: EXC.mute, letterSpacing: 0.3 }}>Saturday, April 18, 2026 · 3:42 PM ET</div>
          <div style={{ fontFamily: EXC.display, fontSize: 30, fontWeight: 600, color: EXC.ink, marginTop: 4, letterSpacing: -0.3 }}>
            Good afternoon, Michael.
          </div>
          <div style={{ color: EXC.inkSoft, fontSize: 14, marginTop: 4 }}>
            Markets are mixed into the close. Your watchlist is outperforming the S&P by <b style={{ color: EXC.up }}>+0.42%</b>.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button style={{ background: EXC.canvas, color: EXC.ink, border: `1px solid ${EXC.line}`, padding: '9px 16px', borderRadius: EXC.r, fontSize: 13, fontWeight: 500 }}>Customize</button>
          <button style={{ background: EXC.ink, color: '#fff', border: 'none', padding: '9px 16px', borderRadius: EXC.r, fontSize: 13, fontWeight: 500 }}>+ Add widget</button>
        </div>
      </div>

      {/* KPI strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16, marginBottom: 22 }}>
        {INDICES.slice(0, 5).map((i, k) => (
          <ExcCard key={k} pad={16}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: EXC.mute, letterSpacing: 0.4, textTransform: 'uppercase' }}>{i.sym}</div>
              <ExcPill tone={i.up ? 'up' : 'down'}>{i.pct}</ExcPill>
            </div>
            <div style={{ fontSize: 22, fontWeight: 600, color: EXC.ink, marginTop: 8, letterSpacing: -0.3, fontFamily: EXC.mono }}>{i.val}</div>
            <div style={{ marginTop: 8 }}>
              <Spark seed={k * 13 + 1} up={i.up} w={220} h={30} color={i.up ? EXC.up : EXC.down} strokeWidth={1.6} />
            </div>
          </ExcCard>
        ))}
      </div>

      {/* Hero news + right column */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 20, marginBottom: 22 }}>
        <ExcCard pad={0}>
          <PhotoPlaceholder label="hero editorial photo" height={260} tone="navy" radius={0} />
          <div style={{ padding: 24 }}>
            <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
              <ExcPill tone="accent">{hero.kicker}</ExcPill>
              <ExcPill>EPM Daily Brief</ExcPill>
            </div>
            <div style={{ fontFamily: EXC.display, fontSize: 26, fontWeight: 600, color: EXC.ink, letterSpacing: -0.3, lineHeight: 1.2 }}>
              {hero.t}.
            </div>
            <div style={{ color: EXC.inkSoft, fontSize: 14, marginTop: 10, lineHeight: 1.6 }}>
              Base case holds: one cut in September, a second in December, contingent on a softer labor print. Services inflation remains the swing factor.
            </div>
            <div style={{ marginTop: 14, fontSize: 12, color: EXC.mute }}>{hero.src} · {hero.time} ago · 5 min read</div>
          </div>
        </ExcCard>

        <ExcCard>
          <ExcSectionHead eyebrow="Today's brief" title="What to watch" action="Full agenda" />
          {[
            { t: '8:30 AM', e: 'Retail Sales, Mar', exp: 'Cons +0.4%' },
            { t: '10:00 AM', e: 'Fed Chair speaks · Economic Club', exp: 'Headline risk' },
            { t: '2:00 PM', e: 'FOMC minutes release', exp: 'Rate path cues' },
            { t: '4:15 PM', e: 'NFLX earnings (AMC)', exp: 'Subs +5.8M' },
            { t: 'After close', e: 'UAL, CSX earnings', exp: 'Guide watch' },
          ].map((r, k) => (
            <div key={k} style={{
              display: 'grid', gridTemplateColumns: '80px 1fr 100px',
              padding: '11px 0', borderBottom: k === 4 ? 'none' : `1px solid ${EXC.lineSoft}`,
              alignItems: 'center',
            }}>
              <div style={{ fontFamily: EXC.mono, fontSize: 12, color: EXC.mute }}>{r.t}</div>
              <div style={{ fontSize: 13, color: EXC.text }}>{r.e}</div>
              <div style={{ textAlign: 'right' }}><ExcPill>{r.exp}</ExcPill></div>
            </div>
          ))}
        </ExcCard>
      </div>

      {/* Three column: gainers, losers, headlines */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1.4fr', gap: 20 }}>
        <ExcCard>
          <ExcSectionHead title="Top gainers" action="Markets" />
          {MOVERS_UP.map((m, k) => (
            <div key={k} style={{
              display: 'grid', gridTemplateColumns: '1fr 80px 70px',
              padding: '10px 0', borderBottom: k === 4 ? 'none' : `1px solid ${EXC.lineSoft}`,
              alignItems: 'center', fontSize: 13,
            }}>
              <div>
                <div style={{ fontWeight: 600, color: EXC.ink }}>{m.sym}</div>
                <div style={{ fontSize: 11.5, color: EXC.mute }}>{m.name}</div>
              </div>
              <div style={{ textAlign: 'right', fontFamily: EXC.mono }}>{m.price}</div>
              <div style={{ textAlign: 'right' }}><ExcPill tone="up">{m.pct}</ExcPill></div>
            </div>
          ))}
        </ExcCard>
        <ExcCard>
          <ExcSectionHead title="Top decliners" action="Markets" />
          {MOVERS_DN.map((m, k) => (
            <div key={k} style={{
              display: 'grid', gridTemplateColumns: '1fr 80px 70px',
              padding: '10px 0', borderBottom: k === 4 ? 'none' : `1px solid ${EXC.lineSoft}`,
              alignItems: 'center', fontSize: 13,
            }}>
              <div>
                <div style={{ fontWeight: 600, color: EXC.ink }}>{m.sym}</div>
                <div style={{ fontSize: 11.5, color: EXC.mute }}>{m.name}</div>
              </div>
              <div style={{ textAlign: 'right', fontFamily: EXC.mono }}>{m.price}</div>
              <div style={{ textAlign: 'right' }}><ExcPill tone="down">{m.pct}</ExcPill></div>
            </div>
          ))}
        </ExcCard>
        <ExcCard>
          <ExcSectionHead title="Newswire" action="All news" />
          {HEADLINES.slice(0, 5).map((h, k) => (
            <div key={k} style={{
              padding: '10px 0', borderBottom: k === 4 ? 'none' : `1px solid ${EXC.lineSoft}`,
            }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                <ExcPill tone="accent">{h.kicker}</ExcPill>
                <span style={{ fontSize: 11, color: EXC.mute }}>{h.src} · {h.time}</span>
              </div>
              <div style={{ fontSize: 13, color: EXC.ink, lineHeight: 1.4 }}>{h.t}.</div>
            </div>
          ))}
        </ExcCard>
      </div>
    </ExcFrame>
  );
}

Object.assign(window, { ExcHomepage });
