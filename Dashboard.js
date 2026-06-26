// ============================================================
// Dashboard.js
// ============================================================
import React, { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { calcSpread, spreadToML, formatSpread, formatOdds } from '../lib/prEngine';

export default function Dashboard({ setSyncStatus }) {
  const [teams,  setTeams]  = useState([]);
  const [sync,   setSync]   = useState(null);

  useEffect(() => {
    supabase.from('teams').select('*').order('pr', { ascending: false }).limit(25)
      .then(({ data }) => setTeams(data || []));
    supabase.from('sync_log').select('*').order('synced_at', { ascending: false }).limit(1)
      .then(({ data }) => setSync(data?.[0] || null));
  }, []);

  async function manualSync() {
    setSyncStatus('syncing');
    try {
      const r = await fetch(`${process.env.REACT_APP_API_URL}/sync/scores`, { method: 'POST' });
      const d = await r.json();
      setSyncStatus('done');
      setTimeout(() => setSyncStatus(null), 3000);
    } catch { setSyncStatus('error'); }
  }

  const topPR = teams[0]?.pr || 100;

  return (
    <div>
      {sync && (
        <div className="update-banner">
          <span className="dot" style={{ width: 6, height: 6, background: 'var(--amb)', borderRadius: '50%', display: 'inline-block' }} />
          Last sync: {sync.synced_at?.split('T')[0]} — {sync.games_final} games final, {sync.prs_updated} PRs updated
          <button className="btn primary" onClick={manualSync} style={{ marginLeft: 'auto' }}>⟳ SYNC NOW</button>
        </div>
      )}

      <div className="kpi-grid cols4">
        <div className="kpi"><div className="kpi-label">Teams tracked</div><div className="kpi-val">364</div><div className="kpi-sub">All D-I</div></div>
        <div className="kpi"><div className="kpi-label">Top PR</div><div className="kpi-val">{teams[0]?.pr?.toFixed(1) || '—'}</div><div className="kpi-sub">{teams[0]?.team || '—'}</div></div>
        <div className="kpi"><div className="kpi-label">PRs updated today</div><div className="kpi-val">{sync?.prs_updated || 0}</div><div className="kpi-sub">from {sync?.games_final || 0} finals</div></div>
        <div className="kpi"><div className="kpi-label">Last sync</div><div className="kpi-val" style={{ fontSize: 14 }}>{sync?.synced_at?.split('T')[1]?.slice(0,5) || '—'}</div><div className="kpi-sub">ET</div></div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div className="panel">
          <div className="panel-hdr"><div className="panel-title">Top 25 Power Ratings</div></div>
          <div className="tbl-wrap">
            <table className="data">
              <thead><tr><th>#</th><th>TEAM</th><th>CONF</th><th>PR</th><th>HC</th><th>VS PRE</th></tr></thead>
              <tbody>
                {teams.slice(0, 25).map((t, i) => {
                  const delta = t.pr_preseason != null ? (t.pr - t.pr_preseason) : null;
                  return (
                    <tr key={t.id}>
                      <td className="muted">{i + 1}</td>
                      <td className="bold">{t.team}</td>
                      <td className="muted">{t.conference}</td>
                      <td>
                        {t.pr?.toFixed(1)}
                        <div className="pr-bar" style={{ width: 40, display: 'inline-block' }}>
                          <div className="pr-bar-fill" style={{ width: `${((t.pr - 10) / (topPR - 10)) * 100}%` }} />
                        </div>
                      </td>
                      <td className="amb">{t.hc?.toFixed(1)}</td>
                      <td>{delta != null ? <span className={delta > 0 ? 'up' : delta < 0 ? 'dn' : 'neu'}>{delta > 0 ? `▲${delta.toFixed(1)}` : delta < 0 ? `▼${Math.abs(delta).toFixed(1)}` : '—'}</span> : <span className="muted">—</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <div className="panel-hdr"><div className="panel-title">Sample Lines (Top 10 vs Field)</div></div>
          <div className="tbl-wrap">
            <table className="data">
              <thead><tr><th>MATCHUP</th><th>SPREAD</th><th>FAV ML</th><th>DOG ML</th></tr></thead>
              <tbody>
                {teams.slice(0, 5).map(home =>
                  teams.slice(5, 6).map(away => {
                    const sp = calcSpread(home.pr, home.hc, away.pr);
                    const ml = spreadToML(sp);
                    return (
                      <tr key={`${home.id}-${away.id}`}>
                        <td className="bold">{away.team} @ {home.team}</td>
                        <td className="acc">{sp < 0 ? `${away.team} ${formatSpread(-sp)}` : `${home.team} ${formatSpread(sp)}`}</td>
                        <td className="odds-fav">{formatOdds(ml.fav)}</td>
                        <td className="odds-dog">{formatOdds(ml.dog)}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
