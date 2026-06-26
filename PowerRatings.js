import React, { useState, useEffect, useCallback } from 'react';
import { supabase } from '../lib/supabase';
import { formatSpread, calcSpread } from '../lib/prEngine';

const CONFS = ['ALL','ACC','B10','B12','SEC','BE','P12','AAC','A10','MWC','WCC','ASUN','AE','BSky','BW','CAA','CUSA','Hor','Ivy','MAAC','MAC','MEAC','MVC','NEC','OVC','Pat','SoCon','SL','SWAC','Sum','SBC','WAC'];

export default function PowerRatings() {
  const [teams,     setTeams]     = useState([]);
  const [loading,   setLoading]   = useState(true);
  const [search,    setSearch]    = useState('');
  const [conf,      setConf]      = useState('ALL');
  const [sortCol,   setSortCol]   = useState('pr');
  const [sortAsc,   setSortAsc]   = useState(false);
  const [editing,   setEditing]   = useState({});   // teamId -> { pr, hc }
  const [saving,    setSaving]    = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    const { data } = await supabase
      .from('teams')
      .select('*')
      .order('pr', { ascending: false });
    setTeams(data || []);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Real-time subscription — updates push automatically
  useEffect(() => {
    const channel = supabase
      .channel('teams-changes')
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'teams' }, payload => {
        setTeams(prev => prev.map(t => t.id === payload.new.id ? { ...t, ...payload.new } : t));
      })
      .subscribe();
    return () => supabase.removeChannel(channel);
  }, []);

  function handleSort(col) {
    if (sortCol === col) setSortAsc(a => !a);
    else { setSortCol(col); setSortAsc(col === 'team' || col === 'conference'); }
  }

  function startEdit(team) {
    setEditing(prev => ({ ...prev, [team.id]: { pr: team.pr, hc: team.hc } }));
  }

  function cancelEdit(id) {
    setEditing(prev => { const n = { ...prev }; delete n[id]; return n; });
  }

  async function saveEdit(team) {
    const vals = editing[team.id];
    if (!vals) return;
    setSaving(team.id);
    const { error } = await supabase
      .from('teams')
      .update({ pr: parseFloat(vals.pr), hc: parseFloat(vals.hc), updated_at: new Date().toISOString() })
      .eq('id', team.id);
    if (!error) cancelEdit(team.id);
    setSaving(null);
  }

  const filtered = teams
    .filter(t =>
      (conf === 'ALL' || t.conference === conf) &&
      (!search || t.team.toLowerCase().includes(search.toLowerCase()))
    )
    .sort((a, b) => {
      const av = a[sortCol], bv = b[sortCol];
      if (typeof av === 'string') return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortAsc ? av - bv : bv - av;
    });

  const topPR = teams[0]?.pr || 100;

  function SortTh({ col, children }) {
    const active = sortCol === col;
    return (
      <th onClick={() => handleSort(col)} style={{ color: active ? 'var(--acc2)' : undefined }}>
        {children}{active ? (sortAsc ? ' ▲' : ' ▼') : ''}
      </th>
    );
  }

  return (
    <div>
      <div className="search-bar">
        <input className="field" placeholder="Search team..." value={search}
          onChange={e => setSearch(e.target.value)} style={{ flex: 1 }} />
        <select className="field" value={conf} onChange={e => setConf(e.target.value)}>
          {CONFS.map(c => <option key={c}>{c}</option>)}
        </select>
        <button className="btn" onClick={load}>⟳ REFRESH</button>
        <button className="btn" onClick={() => {
          const csv = ['Rank,Team,Conference,W,L,PR,PR_Pre,HC,HC_Pre,Updated']
            .concat(filtered.map((t, i) => `${i+1},${t.team},${t.conference},${t.wins||0},${t.losses||0},${t.pr},${t.pr_preseason||''},${t.hc},${t.hc_preseason||''},${t.updated_at?.split('T')[0]}`))
            .join('\n');
          const a = document.createElement('a');
          a.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv);
          a.download = 'cbk_power_ratings.csv';
          a.click();
        }}>↓ EXPORT CSV</button>
      </div>

      <div className="panel">
        <div className="panel-hdr">
          <div className="panel-title">
            Power ratings — {filtered.length} teams
            {loading && <span style={{ color: 'var(--amb)', marginLeft: 8 }}>⟳</span>}
          </div>
          <div style={{ fontSize: 9, color: 'var(--txt3)' }}>
            Click a row's PR or HC to edit inline · Changes save to Supabase instantly
          </div>
        </div>

        <div className="tbl-wrap">
          <table className="data">
            <thead>
              <tr>
                <th style={{ width: 32 }}>#</th>
                <SortTh col="team">TEAM</SortTh>
                <SortTh col="conference">CONF</SortTh>
                <th>W-L</th>
                <SortTh col="pr">POWER RTG</SortTh>
                <th>VS PRE</th>
                <SortTh col="hc">HC</SortTh>
                <th>LAST UPD</th>
                <th>ACTIONS</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t, i) => {
                const isEditing = !!editing[t.id];
                const ed        = editing[t.id] || {};
                const delta     = t.pr_preseason != null ? (t.pr - t.pr_preseason) : null;
                const barPct    = Math.max(0, Math.min(100, ((t.pr - 10) / (topPR - 10)) * 100));

                return (
                  <tr key={t.id} style={{ background: isEditing ? '#3b82f608' : undefined }}>
                    <td className="muted">{i + 1}</td>
                    <td className="bold">{t.team}</td>
                    <td className="muted">{t.conference}</td>
                    <td className="muted">{t.wins || 0}-{t.losses || 0}</td>
                    <td>
                      {isEditing ? (
                        <input className="field-sm" type="number" step="0.5"
                          value={ed.pr}
                          onChange={e => setEditing(p => ({ ...p, [t.id]: { ...p[t.id], pr: e.target.value } }))} />
                      ) : (
                        <>
                          <span className="bold" onClick={() => startEdit(t)} style={{ cursor: 'pointer' }}>{t.pr?.toFixed(1)}</span>
                          <div className="pr-bar" style={{ width: 60, display: 'inline-block' }}>
                            <div className="pr-bar-fill" style={{ width: `${barPct}%` }} />
                          </div>
                        </>
                      )}
                    </td>
                    <td>
                      {delta != null ? (
                        <span className={delta > 0 ? 'up' : delta < 0 ? 'dn' : 'neu'}>
                          {delta > 0 ? `▲${delta.toFixed(1)}` : delta < 0 ? `▼${Math.abs(delta).toFixed(1)}` : '—'}
                        </span>
                      ) : <span className="muted">—</span>}
                    </td>
                    <td>
                      {isEditing ? (
                        <input className="field-sm" type="number" step="0.5"
                          value={ed.hc}
                          onChange={e => setEditing(p => ({ ...p, [t.id]: { ...p[t.id], hc: e.target.value } }))} />
                      ) : (
                        <span onClick={() => startEdit(t)} style={{ cursor: 'pointer', color: 'var(--amb2)' }}>{t.hc?.toFixed(1)}</span>
                      )}
                    </td>
                    <td className="muted">{t.updated_at?.split('T')[0] || '—'}</td>
                    <td>
                      {isEditing ? (
                        <span style={{ display: 'flex', gap: 4 }}>
                          <button className="btn success" onClick={() => saveEdit(t)} disabled={saving === t.id}>
                            {saving === t.id ? '⟳' : '✓ SAVE'}
                          </button>
                          <button className="btn" onClick={() => cancelEdit(t.id)}>✕</button>
                        </span>
                      ) : (
                        <button className="btn" onClick={() => startEdit(t)}>EDIT</button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
