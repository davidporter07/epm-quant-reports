// Direction A — Editorial — Homepage
// News-first hierarchy: a big lead, three secondary, then a market strip.

function EdaHomepage() {
  const lead = HEADLINES[0];
  const seconds = HEADLINES.slice(1, 4);
  const rail = HEADLINES.slice(4);

  return (
    <EdaFrame page="Homepage">
      {/* Top split: hero lead story | right rail summary */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 380px', gap: 40, marginBottom: 48 }}>
        {/* LEAD */}
        <div>
          <EdaKicker>{lead.kicker} · EPM DAILY BRIEF</EdaKicker>
          <EdaH1 size={52}>{lead.t}.</EdaH1>
          <div style={{ display: 'flex', gap: 16, marginTop: 14, color: EDA.mute, fontSize: 12, fontFamily: EDA.mono, letterSpacing: 0.4, textTransform: 'uppercase' }}>
            <span>{lead.src}</span><span>·</span><span>{lead.time} ago</span><span>·</span><span>5 min read</span>
          </div>
          <div style={{ marginTop: 28 }}>
            <PhotoPlaceholder label="lead editorial photo — 16:9" height={360} tone="navy" />
          </div>
          <div style={{ marginTop: 20, fontFamily: EDA.serif, fontSize: 18, lineHeight: 1.55, color: EDA.inkSoft, maxWidth: 680 }}>
            The latest minutes reveal a committee unwilling to declare victory, with several members
            citing residual strength in shelter and medical services. Our base case holds: one cut in
            September, a second in December, contingent on a softer labor print.
          </div>
        </div>

        {/* RIGHT RAIL — snapshot */}
        <div>
          <div style={{ borderBottom: `2px solid ${EDA.ink}`, paddingBottom: 10, marginBottom: 14 }}>
            <EdaKicker>At a Glance</EdaKicker>
            <EdaH2 size={20}>Markets snapshot</EdaH2>
          </div>
          <div>
            {INDICES.slice(0, 6).map((i, k) => (
              <div key={k} style={{
                display: 'grid', gridTemplateColumns: '1fr 90px 70px', alignItems: 'center',
                padding: '12px 0', borderBottom: `1px solid ${EDA.ruleSoft}`, fontSize: 13,
              }}>
                <div style={{ fontWeight: 500 }}>{i.sym}</div>
                <div style={{ textAlign: 'right', fontFamily: EDA.mono }}>{i.val}</div>
                <EdaDelta up={i.up}><div style={{ textAlign: 'right' }}>{i.pct}</div></EdaDelta>
              </div>
            ))}
          </div>

          <div style={{ marginTop: 28, borderBottom: `2px solid ${EDA.ink}`, paddingBottom: 10, marginBottom: 14 }}>
            <EdaKicker>EPM view</EdaKicker>
            <EdaH2 size={20}>This week's call</EdaH2>
          </div>
          <div style={{ fontFamily: EDA.serif, fontSize: 16, lineHeight: 1.55, color: EDA.ink }}>
            <span style={{ fontSize: 40, fontFamily: EDA.serif, float: 'left', lineHeight: 0.9, marginRight: 6, marginTop: 6, color: EDA.accent }}>“</span>
            Breadth is repairing faster than sentiment. We'd fade the defensive rotation on any further softness in cyclicals.
          </div>
          <div style={{ marginTop: 14, fontSize: 12, color: EDA.mute, fontFamily: EDA.mono, letterSpacing: 0.4 }}>
            — M. HARPER, CHIEF STRATEGIST
          </div>
        </div>
      </div>

      {/* Secondary headlines row */}
      <EdaSectionHeader kicker="Editor's picks" title="Stories shaping today" right="UPDATED 3:42 PM" />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 36, marginBottom: 56 }}>
        {seconds.map((h, k) => (
          <div key={k}>
            <PhotoPlaceholder label={`photo ${k + 1}`} height={180} tone={k % 2 ? 'cream' : 'navy'} />
            <div style={{ marginTop: 14 }}>
              <EdaKicker>{h.kicker}</EdaKicker>
              <div style={{ fontFamily: EDA.serif, fontSize: 22, lineHeight: 1.2, fontWeight: 600, color: EDA.ink, letterSpacing: -0.2 }}>
                {h.t}.
              </div>
              <div style={{ marginTop: 10, fontSize: 11.5, fontFamily: EDA.mono, color: EDA.mute, letterSpacing: 0.4, textTransform: 'uppercase' }}>
                {h.src} · {h.time}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Movers + sector pulse band */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 360px', gap: 28 }}>
        <div>
          <EdaSectionHeader title="Top gainers" right="S&P 500" />
          {MOVERS_UP.map((m, k) => (
            <div key={k} style={{ display: 'grid', gridTemplateColumns: '60px 1fr 80px 70px', gap: 10, padding: '12px 0', borderBottom: `1px solid ${EDA.ruleSoft}`, alignItems: 'center' }}>
              <div style={{ fontFamily: EDA.mono, fontWeight: 600 }}>{m.sym}</div>
              <div style={{ color: EDA.inkSoft, fontSize: 13 }}>{m.name}</div>
              <div style={{ textAlign: 'right', fontFamily: EDA.mono }}>{m.price}</div>
              <EdaDelta up><div style={{ textAlign: 'right' }}>{m.pct}</div></EdaDelta>
            </div>
          ))}
        </div>
        <div>
          <EdaSectionHeader title="Top decliners" right="S&P 500" />
          {MOVERS_DN.map((m, k) => (
            <div key={k} style={{ display: 'grid', gridTemplateColumns: '60px 1fr 80px 70px', gap: 10, padding: '12px 0', borderBottom: `1px solid ${EDA.ruleSoft}`, alignItems: 'center' }}>
              <div style={{ fontFamily: EDA.mono, fontWeight: 600 }}>{m.sym}</div>
              <div style={{ color: EDA.inkSoft, fontSize: 13 }}>{m.name}</div>
              <div style={{ textAlign: 'right', fontFamily: EDA.mono }}>{m.price}</div>
              <EdaDelta up={false}><div style={{ textAlign: 'right' }}>{m.pct}</div></EdaDelta>
            </div>
          ))}
        </div>
        <div>
          <EdaSectionHeader title="Sector pulse" />
          {SECTORS.slice(0, 8).map((s, k) => {
            const val = parseFloat(s.pct);
            const w = Math.min(80, Math.abs(val) * 40);
            return (
              <div key={k} style={{ display: 'grid', gridTemplateColumns: '1fr 90px 60px', gap: 10, alignItems: 'center', padding: '8px 0', fontSize: 13 }}>
                <span>{s.name}</span>
                <div style={{ position: 'relative', height: 6, background: EDA.ruleSoft }}>
                  <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: EDA.ink }} />
                  <div style={{
                    position: 'absolute', top: 0, bottom: 0,
                    left: s.up ? '50%' : `${50 - w / 2}%`,
                    width: w / 2 + '%', maxWidth: 40,
                    background: s.up ? EDA.up : EDA.down,
                  }} />
                </div>
                <EdaDelta up={s.up}><div style={{ textAlign: 'right' }}>{s.pct}</div></EdaDelta>
              </div>
            );
          })}
        </div>
      </div>
    </EdaFrame>
  );
}

Object.assign(window, { EdaHomepage });
