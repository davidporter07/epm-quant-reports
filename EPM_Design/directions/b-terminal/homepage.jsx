// Direction B — Terminal — Homepage (dense multi-panel)

function TrmHomepage() {
  return (
    <TrmFrame page="Homepage">
      {/* Big ticker strip */}
      <div style={{ background: TRM.surface, border: `1px solid ${TRM.line}`, padding: '8px 0', marginBottom: 12, display: 'flex', overflow: 'hidden' }}>
        {INDICES.map((i, k) => (
          <div key={k} style={{
            flex: 1, padding: '4px 14px', borderRight: k < INDICES.length - 1 ? `1px solid ${TRM.line}` : 'none',
            display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0,
          }}>
            <div style={{ fontFamily: TRM.mono, fontSize: 10.5, color: TRM.mute, letterSpacing: 0.4 }}>{i.sym}</div>
            <div style={{ fontFamily: TRM.mono, fontSize: 13, fontWeight: 600 }}>{i.val}</div>
            <TrmDelta up={i.up}><span style={{ fontSize: 11 }}>{i.chg} {i.pct}</span></TrmDelta>
          </div>
        ))}
      </div>

      {/* 3-column workspace */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1.6fr 1fr', gap: 12 }}>
        {/* LEFT — watchlist */}
        <TrmPanel title="Watchlist · Core 20" right="20 / 20" pad={0}>
          <div style={{
            display: 'grid', gridTemplateColumns: '60px 1fr 70px 70px 80px',
            padding: '6px 12px', fontFamily: TRM.mono, fontSize: 10, color: TRM.mute,
            borderBottom: `1px solid ${TRM.line}`, letterSpacing: 0.4,
          }}>
            <div>SYM</div><div>NAME</div><div style={{ textAlign: 'right' }}>LAST</div>
            <div style={{ textAlign: 'right' }}>CHG%</div><div style={{ textAlign: 'right' }}>SPARK</div>
          </div>
          {[...MOVERS_UP, ...MOVERS_DN].map((m, k) => (
            <div key={k} style={{
              display: 'grid', gridTemplateColumns: '60px 1fr 70px 70px 80px',
              padding: '5px 12px', fontSize: 11, alignItems: 'center',
              borderBottom: `1px solid ${TRM.lineSoft}`, fontFamily: TRM.mono,
            }}>
              <div style={{ color: TRM.accent }}>{m.sym}</div>
              <div style={{ color: TRM.textSoft, fontFamily: TRM.sans, fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.name}</div>
              <div style={{ textAlign: 'right' }}>{m.price}</div>
              <TrmDelta up={m.pct.startsWith('+')}><div style={{ textAlign: 'right' }}>{m.pct}</div></TrmDelta>
              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <Spark seed={k * 13 + 1} up={m.pct.startsWith('+')} w={70} h={16} color={m.pct.startsWith('+') ? TRM.up : TRM.down} strokeWidth={1} />
              </div>
            </div>
          ))}
        </TrmPanel>

        {/* MIDDLE — chart + depth */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <TrmPanel title="SPX · S&P 500 INDEX" right="1D · 1MIN">
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 8, fontFamily: TRM.mono }}>
              <span style={{ fontSize: 22, fontWeight: 600 }}>5,247.18</span>
              <TrmDelta up><span>+18.42 (+0.35%)</span></TrmDelta>
              <span style={{ color: TRM.mute, fontSize: 10.5, letterSpacing: 0.4 }}>H 5,251.04  L 5,232.88  O 5,236.10  PREV 5,228.76</span>
            </div>
            <div style={{ background: '#05080C', border: `1px solid ${TRM.line}`, height: 220, padding: 8, position: 'relative' }}>
              <svg viewBox="0 0 780 200" width="100%" height="100%" preserveAspectRatio="none">
                {[0, 1, 2, 3, 4].map((i) => (
                  <line key={i} x1="0" x2="780" y1={i * 50} y2={i * 50} stroke={TRM.line} strokeWidth="1" />
                ))}
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <line key={i} x1={i * 156} x2={i * 156} y1="0" y2="200" stroke={TRM.line} strokeWidth="1" />
                ))}
                <path d="M0,150 L50,140 L100,148 L160,125 L220,130 L280,108 L340,115 L400,92 L460,88 L520,72 L580,82 L640,60 L700,52 L780,42"
                  fill="none" stroke={TRM.accent} strokeWidth="1.5" />
                <path d="M0,150 L50,140 L100,148 L160,125 L220,130 L280,108 L340,115 L400,92 L460,88 L520,72 L580,82 L640,60 L700,52 L780,42 L780,200 L0,200 Z"
                  fill={TRM.accent} opacity="0.08" />
              </svg>
              <div style={{ position: 'absolute', right: 10, top: 10, fontFamily: TRM.mono, fontSize: 10, color: TRM.mute }}>5,260</div>
              <div style={{ position: 'absolute', right: 10, bottom: 10, fontFamily: TRM.mono, fontSize: 10, color: TRM.mute }}>5,220</div>
            </div>
            <div style={{ display: 'flex', gap: 2, marginTop: 6 }}>
              {['1D', '5D', '1M', '3M', '6M', 'YTD', '1Y', '5Y'].map((r, i) => (
                <div key={r} style={{
                  padding: '3px 10px', fontSize: 10.5, fontFamily: TRM.mono, letterSpacing: 0.4,
                  background: i === 0 ? TRM.accent : TRM.surface2,
                  color: i === 0 ? '#000' : TRM.textSoft,
                  border: `1px solid ${TRM.line}`,
                }}>{r}</div>
              ))}
            </div>
          </TrmPanel>

          <TrmPanel title="Market internals">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
              {[
                { l: 'ADV / DEC', v: '317 / 183', c: TRM.up },
                { l: 'UP / DOWN VOL', v: '1.84 : 1', c: TRM.up },
                { l: 'NEW HI / LO', v: '142 / 28', c: TRM.up },
                { l: 'TICK', v: '+412', c: TRM.up },
                { l: 'TRIN', v: '0.82', c: TRM.up },
                { l: 'PUT / CALL', v: '0.78', c: TRM.textSoft },
                { l: 'VIX', v: '14.22', c: TRM.down },
                { l: '10Y-2Y', v: '-38 bp', c: TRM.down },
              ].map((m, i) => (
                <div key={i} style={{ padding: '8px 10px', background: TRM.surface2, border: `1px solid ${TRM.line}` }}>
                  <div style={{ fontFamily: TRM.mono, fontSize: 10, color: TRM.mute, letterSpacing: 0.4 }}>{m.l}</div>
                  <div style={{ fontFamily: TRM.mono, fontSize: 14, fontWeight: 600, color: m.c }}>{m.v}</div>
                </div>
              ))}
            </div>
          </TrmPanel>
        </div>

        {/* RIGHT — news + sectors */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <TrmPanel title="News · EPM Priority" right="LIVE">
            {HEADLINES.map((h, k) => (
              <div key={k} style={{
                display: 'grid', gridTemplateColumns: '40px 72px 1fr',
                padding: '5px 0', borderBottom: k === HEADLINES.length - 1 ? 'none' : `1px solid ${TRM.lineSoft}`,
                fontFamily: TRM.mono, fontSize: 11, alignItems: 'baseline',
              }}>
                <div style={{ color: TRM.mute }}>{h.time}</div>
                <div style={{ color: TRM.accent, fontSize: 10.5, letterSpacing: 0.5 }}>{h.kicker}</div>
                <div style={{ fontFamily: TRM.sans, color: TRM.text, lineHeight: 1.35 }}>{h.t}</div>
              </div>
            ))}
          </TrmPanel>

          <TrmPanel title="Sectors · SPX" right="1D">
            {SECTORS.map((s, k) => {
              const val = parseFloat(s.pct);
              const w = Math.min(50, Math.abs(val) * 30);
              return (
                <div key={k} style={{
                  display: 'grid', gridTemplateColumns: '1fr 70px 60px', alignItems: 'center', gap: 8,
                  padding: '3px 0', fontFamily: TRM.mono, fontSize: 11,
                }}>
                  <div style={{ color: TRM.textSoft }}>{s.name}</div>
                  <div style={{ position: 'relative', height: 10, background: TRM.surface2 }}>
                    <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: TRM.mute }} />
                    <div style={{
                      position: 'absolute', top: 0, bottom: 0,
                      left: s.up ? '50%' : `${50 - w}%`,
                      width: `${w}%`, background: s.up ? TRM.up : TRM.down,
                    }} />
                  </div>
                  <TrmDelta up={s.up}><div style={{ textAlign: 'right' }}>{s.pct}</div></TrmDelta>
                </div>
              );
            })}
          </TrmPanel>
        </div>
      </div>
    </TrmFrame>
  );
}

Object.assign(window, { TrmHomepage });
