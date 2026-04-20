// Direction B — Terminal — Markets

function TrmMarkets() {
  return (
    <TrmFrame page="Markets">
      {/* Sub-tabs */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 12 }}>
        {['OVERVIEW', 'EQUITIES', 'FIXED INCOME', 'FX', 'COMMODITIES', 'CREDIT', 'CRYPTO'].map((t, i) => (
          <div key={t} style={{
            padding: '7px 14px', fontFamily: TRM.mono, fontSize: 10.5, letterSpacing: 0.6,
            background: i === 0 ? TRM.surface : 'transparent',
            color: i === 0 ? TRM.accent : TRM.textSoft,
            border: `1px solid ${i === 0 ? TRM.accent : TRM.line}`,
          }}>{t}</div>
        ))}
      </div>

      {/* Quad grid: 4 asset classes */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        {[
          { t: 'EQUITY INDICES · GLOBAL', rows: INDICES.slice(0, 5) },
          { t: 'RATES · SOVEREIGN YIELDS', rows: [
            { sym: 'US 2Y',  val: '4.598%', chg: '-0.012', pct: '-0.26%', up: false },
            { sym: 'US 5Y',  val: '4.310%', chg: '-0.018', pct: '-0.42%', up: false },
            { sym: 'US 10Y', val: '4.218%', chg: '-0.021', pct: '-0.50%', up: false },
            { sym: 'US 30Y', val: '4.402%', chg: '-0.019', pct: '-0.43%', up: false },
            { sym: 'DE 10Y', val: '2.418%', chg: '-0.014', pct: '-0.58%', up: false },
          ] },
          { t: 'FX · MAJORS', rows: [
            { sym: 'EUR/USD', val: '1.0841', chg: '+0.0018', pct: '+0.17%', up: true },
            { sym: 'USD/JPY', val: '153.82', chg: '-0.31',   pct: '-0.20%', up: false },
            { sym: 'GBP/USD', val: '1.2648', chg: '+0.0021', pct: '+0.17%', up: true },
            { sym: 'USD/CNH', val: '7.2408', chg: '-0.0042', pct: '-0.06%', up: false },
            { sym: 'AUD/USD', val: '0.6524', chg: '+0.0009', pct: '+0.14%', up: true },
          ] },
          { t: 'COMMODITIES', rows: [
            { sym: 'GOLD',   val: '2,384.40', chg: '+11.20', pct: '+0.47%', up: true },
            { sym: 'SILVER', val: '28.94',    chg: '+0.22',  pct: '+0.77%', up: true },
            { sym: 'WTI',    val: '78.92',    chg: '-0.61',  pct: '-0.77%', up: false },
            { sym: 'BRENT',  val: '82.44',    chg: '-0.48',  pct: '-0.58%', up: false },
            { sym: 'COPPER', val: '4.218',    chg: '+0.022', pct: '+0.52%', up: true },
          ] },
        ].map((panel, i) => (
          <TrmPanel key={i} title={panel.t} pad={0}>
            <div style={{
              display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr 1fr 80px',
              padding: '6px 12px', fontFamily: TRM.mono, fontSize: 10, color: TRM.mute, letterSpacing: 0.4,
              borderBottom: `1px solid ${TRM.line}`,
            }}>
              <div>SYMBOL</div>
              <div style={{ textAlign: 'right' }}>LAST</div>
              <div style={{ textAlign: 'right' }}>CHG</div>
              <div style={{ textAlign: 'right' }}>%CHG</div>
              <div style={{ textAlign: 'right' }}>TREND</div>
            </div>
            {panel.rows.map((r, k) => (
              <div key={k} style={{
                display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr 1fr 80px',
                padding: '6px 12px', fontFamily: TRM.mono, fontSize: 11.5,
                alignItems: 'center',
                borderBottom: k === panel.rows.length - 1 ? 'none' : `1px solid ${TRM.lineSoft}`,
              }}>
                <div style={{ color: TRM.accent }}>{r.sym}</div>
                <div style={{ textAlign: 'right' }}>{r.val}</div>
                <TrmDelta up={r.up}><div style={{ textAlign: 'right' }}>{r.chg}</div></TrmDelta>
                <TrmDelta up={r.up}><div style={{ textAlign: 'right' }}>{r.pct}</div></TrmDelta>
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <Spark seed={i * 17 + k + 1} up={r.up} w={70} h={14} color={r.up ? TRM.up : TRM.down} strokeWidth={1} />
                </div>
              </div>
            ))}
          </TrmPanel>
        ))}
      </div>

      {/* Heatmap */}
      <TrmPanel title="S&P 500 · SECTOR HEATMAP" right="MARKET CAP WEIGHTED · 1D">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gridAutoRows: 52, gap: 2 }}>
          {[
            ['AAPL', '+1.42', 3.8], ['MSFT', '+1.12', 3.5], ['NVDA', '+4.82', 3.2], ['GOOGL', '+0.94', 1.9],
            ['AMZN', '+1.18', 2.0], ['META', '+2.14', 1.7], ['BRK.B', '+0.22', 1.6], ['TSLA', '-3.21', 1.4],
            ['LLY', '-0.44', 1.3], ['JPM', '+0.82', 1.2], ['V', '+0.21', 1.0], ['XOM', '-1.44', 0.9],
            ['AVGO', '+3.91', 1.4], ['WMT', '-0.12', 0.9], ['UNH', '-0.51', 0.9], ['MA', '+0.31', 0.8],
            ['JNJ', '-0.22', 0.7], ['PG', '-0.41', 0.7], ['HD', '+0.92', 0.7], ['COST', '+0.62', 0.6],
            ['ORCL', '+1.82', 0.7], ['AMD', '+3.44', 0.6], ['BAC', '+0.44', 0.6], ['PFE', '-2.11', 0.4],
          ].map((c, k) => {
            const v = parseFloat(c[1]);
            const up = v > 0;
            const a = Math.min(0.9, 0.2 + Math.abs(v) * 0.2);
            return (
              <div key={k} style={{
                background: up ? `rgba(54,197,138,${a})` : `rgba(255,90,90,${a})`,
                color: a > 0.5 ? '#000' : TRM.text,
                padding: '4px 6px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
                fontFamily: TRM.mono,
              }}>
                <div style={{ fontSize: 10.5, fontWeight: 700 }}>{c[0]}</div>
                <div style={{ fontSize: 10, opacity: 0.9 }}>{c[1]}%</div>
              </div>
            );
          })}
        </div>
      </TrmPanel>
    </TrmFrame>
  );
}

Object.assign(window, { TrmMarkets });
