// ============================================================
// Spreads.js
// ============================================================
import React, { useState, useEffect } from 'react';
import { supabase } from '../lib/supabase';
import { calcSpread, spreadToML, formatSpread, formatOdds } from '../lib/prEngine';

export function Spreads() {
  const [games,  setGames]  = useState([]);
  const [teams,  setTeams]  = useState({});
  const [filter, setFilter] = useState('today');

  useEffect(() => {
    supabase.from('teams').select('id,team,pr,hc,conference').then(({ data }) => {
      const map = {};
      (data || []).forEach(t => { map[t.id] = t; });
      setTeams(map);
    });
  }, []);

  useEffect(() => {
    const today = new Date().toISOString().split('T')[0];
    let q = supabase.from('games').select('*').in('status', ['scheduled','live']);
    if (filter === 'today') q = q.eq('game_date', today);
    q.order('game_date').limit(100).then(({ data }) => setGames(data || []));
  }, [filter]);

  return (
    <div>
      <div className="search-bar">
        {['today','tomorrow','week','all'].map(f => (
          <button key={f} className={`btn ${filter === f ? 'active' : ''}`} onClick={() => setFilter(f)}>
            {f.toUpperCase()}
          </button>
        ))}
      </div>
      <div className="panel">
        <div className="panel-hdr"><div className="panel-title">Game Spreads — derived from current PRs</div></div>
        <div className="tbl-wrap">
          <table className="data">
            <thead><tr>
              <th>DATE</th><th>AWAY</th><th>HOME</th>
              <th>PR DIFF</th><th>HC</th><th>RAW LINE</th>
              <th>SPREAD</th><th>TOTAL</th><th>ML FAV</th><th>ML DOG</th>
            </tr></thead>
            <tbody>
              {games.map(g => {
                const home = teams[g.home_team_id];
                const away = teams[g.away_team_id];
                if (!home || !away) return null;
                const sp    = calcSpread(home.pr, home.hc, away.pr, g.neutral_site);
                const ml    = spreadToML(sp);
                const total = Math.round(((home.pr + away.pr) / 2) * 0.185 + 118);
                const homeFav = sp >= 0;
                const favTeam = homeFav ? home : away;
                const dogTeam = homeFav ? away : home;
                const favML   = homeFav ? ml.fav : ml.dog;
                const dogML   = homeFav ? ml.dog : ml.fav;
                const posted  = Math.round(sp * 2) / 2;
                return (
                  <tr key={g.id}>
                    <td className="muted">{g.game_date}</td>
                    <td>{away.team}</td>
                    <td className="bold">{home.team}</td>
                    <td className="muted">{(home.pr - away.pr).toFixed(1)}</td>
                    <td className="amb">{home.hc?.toFixed(1)}</td>
                    <td className="muted">{sp.toFixed(1)}</td>
                    <td className="acc bold">{favTeam.team} {formatSpread(-Math.abs(posted))}</td>
                    <td>{total}.5</td>
                    <td className="odds-fav">{formatOdds(favML)}</td>
                    <td className="odds-dog">{formatOdds(dogML)}</td>
                  </tr>
                );
              })}
              {games.length === 0 && (
                <tr><td colSpan={10} style={{ textAlign: 'center', color: 'var(--txt3)', padding: 20 }}>
                  No games found — games populate from ESPN score sync
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// Futures.js
// ============================================================
import React2, { useState as useState2, useEffect as useEffect2 } from 'react';
import { supabase as sb2 } from '../lib/supabase';
import { formatOdds as fmt2 } from '../lib/prEngine';

export function Futures() {
  const [tab,   setTab]   = useState2('conf_winner');
  const [data,  setData]  = useState2([]);
  const [conf,  setConf]  = useState2('ALL');

  useEffect2(() => {
    let q = sb2.from('futures')
      .select('*, team:team_id(team, conference, pr)')
      .eq('market', tab)
      .order('odds', { ascending: true })
      .limit(50);
    if (conf !== 'ALL') q = q.eq('team.conference', conf);
    q.then(({ data: d }) => setData(d || []));
  }, [tab, conf]);

  const markets = [
    { id: 'conf_winner',  label: 'CONF WINNER' },
    { id: 'champ',        label: 'NCAA CHAMP' },
    { id: 'finalist',     label: 'FINALIST' },
    { id: 'final4',       label: 'FINAL FOUR' },
    { id: 'elite8',       label: 'ELITE EIGHT' },
    { id: 'sweet16',      label: 'SWEET 16' },
    { id: 'rd32',         label: 'RD OF 32' },
    { id: 'make_field',   label: 'MAKE FIELD' },
    { id: 'mte',          label: 'MTEs' },
  ];

  return (
    <div>
      <div className="sec-tabs">
        {markets.map(m => (
          <button key={m.id} className={`sec-tab ${tab === m.id ? 'active' : ''}`} onClick={() => setTab(m.id)}>
            {m.label}
          </button>
        ))}
      </div>
      <div className="panel">
        <div className="panel-hdr">
          <div className="panel-title">{markets.find(m => m.id === tab)?.label}</div>
          <div style={{ fontSize: 9, color: 'var(--txt3)' }}>Derived from current power ratings · Run Recalc to refresh</div>
        </div>
        <div className="tbl-wrap">
          <table className="data">
            <thead><tr><th>#</th><th>TEAM</th><th>CONF</th><th>PR</th><th>ODDS</th><th>IMPLIED %</th></tr></thead>
            <tbody>
              {data.map((row, i) => {
                const impl = row.odds > 0
                  ? 100 / (row.odds + 100) * 100
                  : Math.abs(row.odds) / (Math.abs(row.odds) + 100) * 100;
                return (
                  <tr key={row.id}>
                    <td className="muted">{i + 1}</td>
                    <td className="bold">{row.team?.team}</td>
                    <td className="muted">{row.team?.conference}</td>
                    <td>{row.team?.pr?.toFixed(1)}</td>
                    <td className={row.odds < 0 ? 'odds-fav' : 'odds-dog'}>{fmt2(row.odds)}</td>
                    <td className="muted">{impl.toFixed(1)}%</td>
                  </tr>
                );
              })}
              {data.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--txt3)', padding: 20 }}>
                  Run POST /api/futures/recalc to generate futures from current PRs
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// NCAABracket.js
// ============================================================
const NCAA_MARKETS = [
  { id: 'champ',      label: 'CHAMPION' },
  { id: 'finalist',   label: 'FINALIST' },
  { id: 'final4',     label: 'FINAL FOUR' },
  { id: 'elite8',     label: 'ELITE EIGHT' },
  { id: 'sweet16',    label: 'SWEET 16' },
  { id: 'rd32',       label: 'ROUND OF 32' },
  { id: 'make_field', label: 'MAKE TOURNAMENT' },
];

export function NCAABracket() {
  const [tab,  setTab]  = useState2('champ');
  const [rows, setRows] = useState2([]);

  useEffect2(() => {
    sb2.from('futures')
      .select('*, team:team_id(team, conference, pr)')
      .eq('market', tab)
      .order('odds', { ascending: true })
      .limit(64)
      .then(({ data: d }) => setRows(d || []));
  }, [tab]);

  return (
    <div>
      <div className="sec-tabs">
        {NCAA_MARKETS.map(m => (
          <button key={m.id} className={`sec-tab ${tab === m.id ? 'active' : ''}`} onClick={() => setTab(m.id)}>
            {m.label}
          </button>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {[0, 1].map(half => (
          <div className="panel" key={half}>
            <div className="panel-hdr"><div className="panel-title">{half === 0 ? 'Top half' : 'Bottom half'}</div></div>
            <div className="tbl-wrap">
              <table className="data">
                <thead><tr><th>#</th><th>TEAM</th><th>CONF</th><th>PR</th><th>ODDS</th><th>IMPL %</th></tr></thead>
                <tbody>
                  {rows.slice(half === 0 ? 0 : Math.ceil(rows.length / 2), half === 0 ? Math.ceil(rows.length / 2) : rows.length).map((row, i) => {
                    const impl = row.odds > 0 ? 100 / (row.odds + 100) * 100 : Math.abs(row.odds) / (Math.abs(row.odds) + 100) * 100;
                    const rank = (half === 0 ? 0 : Math.ceil(rows.length / 2)) + i + 1;
                    return (
                      <tr key={row.id}>
                        <td className="muted">{rank}</td>
                        <td className="bold">{row.team?.team}</td>
                        <td className="muted">{row.team?.conference}</td>
                        <td>{row.team?.pr?.toFixed(1)}</td>
                        <td className={row.odds < 0 ? 'odds-fav' : 'odds-dog'}>{fmt2(row.odds)}</td>
                        <td className="muted">{impl.toFixed(1)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================
// Tools.js
// ============================================================
import React3, { useState as useState3 } from 'react';
import { calcSpread as cs, spreadToML as sml, formatSpread as fs, formatOdds as fo, impliedProb, calcVig, calcPRAdjustment } from '../lib/prEngine';

export function Tools() {
  const [conv,  setConv]  = useState3('');
  const [v1,    setV1]    = useState3('');
  const [v2,    setV2]    = useState3('');
  const [pra,   setPra]   = useState3('');
  const [prb,   setPrb]   = useState3('');
  const [hca,   setHca]   = useState3('3');
  const [loc,   setLoc]   = useState3('home');
  // PR Update Simulator
  const [hs,    setHs]    = useState3('');
  const [as_,   setAs]    = useState3('');
  const [hpr,   setHpr]   = useState3('');
  const [apr,   setApr]   = useState3('');
  const [hhc,   setHhc]   = useState3('3');
  const [simResult, setSimResult] = useState3(null);

  const convNum  = parseInt(conv);
  const decOdds  = !isNaN(convNum) ? (convNum > 0 ? (convNum / 100 + 1).toFixed(3) : (100 / Math.abs(convNum) + 1).toFixed(3)) : '—';
  const implPct  = !isNaN(convNum) ? (impliedProb(convNum) * 100).toFixed(1) + '%' : '—';

  const v1n = parseInt(v1), v2n = parseInt(v2);
  const vig  = !isNaN(v1n) && !isNaN(v2n) ? calcVig(v1n, v2n).toFixed(2) + '%' : '—';

  const span = !isNaN(parseFloat(pra)) && !isNaN(parseFloat(prb))
    ? cs(parseFloat(pra), parseFloat(hca), parseFloat(prb), loc === 'neutral')
    : null;
  const spanML = span != null ? sml(span) : null;

  function simulate() {
    const r = calcPRAdjustment({
      homeScore: parseInt(hs), awayScore: parseInt(as_),
      homePR: parseFloat(hpr), homeHC: parseFloat(hhc), awayPR: parseFloat(apr)
    });
    setSimResult(r);
  }

  return (
    <div>
      <div className="page-grid cols3" style={{ marginBottom: 12 }}>
        <div className="panel">
          <div className="panel-hdr"><div className="panel-title">Odds Converter</div></div>
          <div style={{ padding: 12 }}>
            <div style={{ fontSize: 9, color: 'var(--txt3)', marginBottom: 4, letterSpacing: 1 }}>AMERICAN ODDS</div>
            <input className="field" value={conv} onChange={e => setConv(e.target.value)} placeholder="-110" style={{ width: '100%', marginBottom: 10 }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
              <span style={{ color: 'var(--txt3)' }}>Decimal:</span><span className="acc">{decOdds}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginTop: 4 }}>
              <span style={{ color: 'var(--txt3)' }}>Implied prob:</span><span className="grn">{implPct}</span>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-hdr"><div className="panel-title">Vig Calculator</div></div>
          <div style={{ padding: 12 }}>
            <input className="field" value={v1} onChange={e => setV1(e.target.value)} placeholder="Side 1 (e.g. -110)" style={{ width: '100%', marginBottom: 6 }} />
            <input className="field" value={v2} onChange={e => setV2(e.target.value)} placeholder="Side 2 (e.g. -110)" style={{ width: '100%', marginBottom: 10 }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
              <span style={{ color: 'var(--txt3)' }}>Vig / hold:</span><span className="red">{vig}</span>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-hdr"><div className="panel-title">PR → Spread</div></div>
          <div style={{ padding: 12 }}>
            <input className="field" value={pra} onChange={e => setPra(e.target.value)} placeholder="Team A power rating" style={{ width: '100%', marginBottom: 6 }} />
            <input className="field" value={hca} onChange={e => setHca(e.target.value)} placeholder="Team A home court" style={{ width: '100%', marginBottom: 6 }} />
            <input className="field" value={prb} onChange={e => setPrb(e.target.value)} placeholder="Team B power rating" style={{ width: '100%', marginBottom: 6 }} />
            <select className="field" value={loc} onChange={e => setLoc(e.target.value)} style={{ width: '100%', marginBottom: 10 }}>
              <option value="home">Team A is home</option>
              <option value="away">Team A is away</option>
              <option value="neutral">Neutral site</option>
            </select>
            {span != null && (
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--acc2)' }}>
                {span < 0 ? 'Team B' : 'Team A'} {fs(-Math.abs(span))}
                &nbsp;&nbsp;<span style={{ color: 'var(--txt3)', fontWeight: 400, fontSize: 11 }}>
                  ML: {fo(spanML.fav)} / {fo(spanML.dog)}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-hdr"><div className="panel-title">PR Adjustment Simulator — test your formula on any result</div></div>
        <div style={{ padding: 12, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          {[
            ['HOME SCORE', hs, setHs], ['AWAY SCORE', as_, setAs],
            ['HOME PR', hpr, setHpr], ['HOME HC', hhc, setHhc], ['AWAY PR', apr, setApr],
          ].map(([lbl, val, set]) => (
            <div key={lbl}>
              <div style={{ fontSize: 9, color: 'var(--txt3)', marginBottom: 3, letterSpacing: 1 }}>{lbl}</div>
              <input className="field" type="number" step="0.5" value={val} onChange={e => set(e.target.value)} style={{ width: 100 }} />
            </div>
          ))}
          <button className="btn primary" onClick={simulate} style={{ alignSelf: 'flex-end' }}>SIMULATE</button>
        </div>
        {simResult && (
          <div style={{ padding: '0 12px 12px', display: 'flex', gap: 20, fontSize: 11, flexWrap: 'wrap' }}>
            <div><span style={{ color: 'var(--txt3)' }}>Home adj: </span>
              <span className={simResult.homeAdj > 0 ? 'up' : simResult.homeAdj < 0 ? 'dn' : 'neu'}>
                {simResult.homeAdj > 0 ? '+' : ''}{simResult.homeAdj}
              </span>
            </div>
            <div><span style={{ color: 'var(--txt3)' }}>Away adj: </span>
              <span className={simResult.awayAdj > 0 ? 'up' : simResult.awayAdj < 0 ? 'dn' : 'neu'}>
                {simResult.awayAdj > 0 ? '+' : ''}{simResult.awayAdj}
              </span>
            </div>
            <div style={{ color: 'var(--txt2)' }}>{simResult.reason}</div>
          </div>
        )}
      </div>
    </div>
  );
}

export default Spreads;
