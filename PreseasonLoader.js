import React, { useState, useRef } from 'react';
import * as XLSX from 'xlsx';
import axios from 'axios';
import { API } from '../lib/supabase';

const KNOWN_CONFS = new Set([
  'AMERICAN','ATLANTIC 10','ACC','ASUN','AMERICAN EAST','BIG EAST',
  'BIG SKY','BIG SOUTH','BIG TEN','BIG 12','BIG WEST','CAA',
  'CONFERENCE USA','HORIZON','IVY','MAAC','MAC','MEAC',
  'MISSOURI VALLEY','MOUNTAIN WEST','NEC','OVC','PAC-12','PATRIOT',
  'SEC','SOUTHERN','SOUTHLAND','SWAC','SUMMIT','SUN BELT','WAC','WCC','EXTRA',
]);

const CONF_MAP = {
  'AMERICAN':'AAC','ATLANTIC 10':'A10','ACC':'ACC','ASUN':'ASUN',
  'AMERICAN EAST':'AE','BIG EAST':'BE','BIG SKY':'BSky','BIG SOUTH':'BSouth',
  'BIG TEN':'B10','BIG 12':'B12','BIG WEST':'BW','CAA':'CAA',
  'CONFERENCE USA':'CUSA','HORIZON':'Hor','IVY':'Ivy','MAAC':'MAAC',
  'MAC':'MAC','MEAC':'MEAC','MISSOURI VALLEY':'MVC','MOUNTAIN WEST':'MWC',
  'NEC':'NEC','OVC':'OVC','PAC-12':'P12','PATRIOT':'Pat','SEC':'SEC',
  'SOUTHERN':'SoCon','SOUTHLAND':'SL','SWAC':'SWAC','SUMMIT':'Sum',
  'SUN BELT':'SBC','WAC':'WAC','WCC':'WCC',
};

function parseExcelClient(buffer) {
  const wb   = XLSX.read(buffer, { type: 'array' });
  const rows = [];
  let conf   = 'Unknown';

  for (const sheetName of wb.SheetNames) {
    const ws  = wb.Sheets[sheetName];
    const raw = XLSX.utils.sheet_to_json(ws, { header: 1, defval: '' });

    for (const row of raw) {
      const teamVal = String(row[0] || '').trim();
      const prVal   = parseFloat(String(row[1] || '').replace(/[^0-9.]/g, ''));
      const hcVal   = parseFloat(String(row[2] || '').replace(/[^0-9.]/g, ''));

      if (!teamVal || teamVal.toLowerCase() === 'team') continue;

      if (KNOWN_CONFS.has(teamVal.toUpperCase())) {
        const mapped = CONF_MAP[teamVal.toUpperCase()];
        if (mapped) conf = mapped;
        continue;
      }

      if (isNaN(prVal)) continue;

      rows.push({
        team:       teamVal,
        pr:         prVal,
        hc:         isNaN(hcVal) ? 3.0 : hcVal,
        conference: conf,
        _edited:    false,
      });
    }
  }

  return rows;
}

export default function PreseasonLoader() {
  const [teams,       setTeams]       = useState([]);
  const [loading,     setLoading]     = useState(false);
  const [saving,      setSaving]      = useState(false);
  const [saved,       setSaved]       = useState(false);
  const [error,       setError]       = useState(null);
  const [dragOver,    setDragOver]    = useState(false);
  const [lockPre,     setLockPre]     = useState(true);
  const [search,      setSearch]      = useState('');
  const [confFilter,  setConfFilter]  = useState('ALL');
  const fileRef = useRef();

  const confs = ['ALL', ...new Set(teams.map(t => t.conference))].sort();

  function handleFile(file) {
    if (!file) return;
    setError(null);
    setLoading(true);
    setSaved(false);
    const reader = new FileReader();
    reader.onload = e => {
      try {
        const parsed = parseExcelClient(e.target.result);
        setTeams(parsed);
      } catch (err) {
        setError('Could not parse file: ' + err.message);
      }
      setLoading(false);
    };
    reader.readAsArrayBuffer(file);
  }

  function onDrop(e) {
    e.preventDefault();
    setDragOver(false);
    handleFile(e.dataTransfer.files[0]);
  }

  function updateRow(idx, field, val) {
    setTeams(prev => prev.map((t, i) =>
      i === idx ? { ...t, [field]: field === 'team' || field === 'conference' ? val : parseFloat(val) || t[field], _edited: true } : t
    ));
  }

  function removeRow(idx) {
    setTeams(prev => prev.filter((_, i) => i !== idx));
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const resp = await axios.post(`${API}/import/commit`, {
        teams:         teams.map(({ _edited, ...t }) => t),
        lockPreseason: lockPre,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 4000);
    } catch (err) {
      setError(err.response?.data?.error || err.message);
    }
    setSaving(false);
  }

  const visible = teams.filter(t =>
    (confFilter === 'ALL' || t.conference === confFilter) &&
    (!search || t.team.toLowerCase().includes(search.toLowerCase()))
  );

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 11, color: 'var(--txt2)', marginBottom: 8, letterSpacing: 1 }}>
          PRESEASON RATINGS LOADER — Drop your Excel file below. All 364 teams with PR + HC will be parsed automatically based on your existing format.
        </div>

        {/* Drop Zone */}
        <div
          className={`dropzone ${dragOver ? 'drag-over' : ''}`}
          onClick={() => fileRef.current.click()}
          onDragOver={e => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
        >
          <div className="dropzone-icon">↑</div>
          <h3>Drop your Excel file here</h3>
          <p>Supports .xlsx with your ABC order, ranking order, or by-conference layout</p>
          <p style={{ marginTop: 6, color: 'var(--acc2)' }}>Click to browse files</p>
          <input
            type="file"
            accept=".xlsx,.xls,.csv"
            ref={fileRef}
            style={{ display: 'none' }}
            onChange={e => handleFile(e.target.files[0])}
          />
        </div>

        {loading && <div style={{ color: 'var(--amb)', fontSize: 11, marginBottom: 10 }}>⟳ Parsing file...</div>}
        {error   && <div style={{ color: 'var(--red)', fontSize: 11, marginBottom: 10 }}>⚠ {error}</div>}

        {teams.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
            <div style={{ color: 'var(--grn)', fontSize: 11 }}>✓ {teams.length} teams loaded</div>

            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: 'var(--txt2)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={lockPre}
                onChange={e => setLockPre(e.target.checked)}
              />
              Lock as preseason baseline (stores PR_preseason — you can always compare back to this)
            </label>

            <button
              className={`btn ${saved ? 'success' : 'primary'}`}
              onClick={handleSave}
              disabled={saving}
              style={{ marginLeft: 'auto' }}
            >
              {saving ? '⟳ SAVING...' : saved ? '✓ SAVED TO SUPABASE' : `↑ COMMIT ${teams.length} TEAMS TO DB`}
            </button>
          </div>
        )}
      </div>

      {teams.length > 0 && (
        <div className="panel">
          <div className="panel-hdr">
            <div className="panel-title">Preview — {visible.length} teams shown</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                className="field"
                placeholder="Search team..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                style={{ width: 160 }}
              />
              <select
                className="field"
                value={confFilter}
                onChange={e => setConfFilter(e.target.value)}
              >
                {confs.map(c => <option key={c}>{c}</option>)}
              </select>
            </div>
          </div>

          <div className="tbl-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th style={{ width: 32 }}>#</th>
                  <th>TEAM</th>
                  <th>CONF</th>
                  <th style={{ textAlign: 'right' }}>POWER RATING</th>
                  <th style={{ textAlign: 'right' }}>HOME COURT</th>
                  <th style={{ textAlign: 'right' }}>SPREAD vs #1</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {visible.map((t, idx) => {
                  const globalIdx = teams.indexOf(t);
                  const topPR     = Math.max(...teams.map(x => x.pr));
                  const spread    = (topPR + 3) - t.pr; // rough spread vs top team
                  return (
                    <tr key={idx} style={{ background: t._edited ? '#3b82f608' : undefined }}>
                      <td className="muted">{globalIdx + 1}</td>
                      <td className="bold">
                        <input
                          className="field-sm"
                          value={t.team}
                          onChange={e => updateRow(globalIdx, 'team', e.target.value)}
                          style={{ width: 160, textAlign: 'left' }}
                        />
                      </td>
                      <td>
                        <input
                          className="field-sm"
                          value={t.conference}
                          onChange={e => updateRow(globalIdx, 'conference', e.target.value)}
                          style={{ width: 60, textAlign: 'center' }}
                        />
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <input
                          className="field-sm"
                          type="number"
                          step="0.5"
                          value={t.pr}
                          onChange={e => updateRow(globalIdx, 'pr', e.target.value)}
                        />
                        <span style={{ display: 'inline-block', width: 50, marginLeft: 8 }}>
                          <div className="pr-bar" style={{ width: 50 }}>
                            <div className="pr-bar-fill" style={{ width: `${((t.pr - 10) / (topPR - 10)) * 100}%` }} />
                          </div>
                        </span>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <input
                          className="field-sm"
                          type="number"
                          step="0.5"
                          value={t.hc}
                          onChange={e => updateRow(globalIdx, 'hc', e.target.value)}
                        />
                      </td>
                      <td className={spread <= 0 ? 'grn' : 'acc'} style={{ textAlign: 'right' }}>
                        {spread <= 0 ? `FAV ${spread.toFixed(1)}` : `+${spread.toFixed(1)}`}
                      </td>
                      <td>
                        <button className="btn" onClick={() => removeRow(globalIdx)} style={{ color: 'var(--red)', padding: '2px 6px' }}>✕</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Manual single-team add */}
      <div className="panel" style={{ marginTop: 12 }}>
        <div className="panel-hdr"><div className="panel-title">Add / Edit Single Team</div></div>
        <div style={{ padding: 12, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <ManualTeamForm onSave={t => setTeams(prev => {
            const existing = prev.findIndex(x => x.team.toLowerCase() === t.team.toLowerCase());
            if (existing >= 0) { const n = [...prev]; n[existing] = { ...t, _edited: true }; return n; }
            return [...prev, { ...t, _edited: true }];
          })} />
        </div>
      </div>
    </div>
  );
}

function ManualTeamForm({ onSave }) {
  const [form, setForm] = useState({ team: '', conference: '', pr: '', hc: '' });
  const set = (k, v) => setForm(p => ({ ...p, [k]: v }));

  function submit() {
    if (!form.team || !form.pr) return;
    onSave({ ...form, pr: parseFloat(form.pr), hc: parseFloat(form.hc) || 3.0 });
    setForm({ team: '', conference: '', pr: '', hc: '' });
  }

  return (
    <>
      <div><div style={{ fontSize: 9, color: 'var(--txt3)', marginBottom: 3, letterSpacing: 1 }}>TEAM NAME</div>
        <input className="field" value={form.team} onChange={e => set('team', e.target.value)} placeholder="e.g. Duke" style={{ width: 160 }} /></div>
      <div><div style={{ fontSize: 9, color: 'var(--txt3)', marginBottom: 3, letterSpacing: 1 }}>CONFERENCE</div>
        <input className="field" value={form.conference} onChange={e => set('conference', e.target.value)} placeholder="ACC" style={{ width: 80 }} /></div>
      <div><div style={{ fontSize: 9, color: 'var(--txt3)', marginBottom: 3, letterSpacing: 1 }}>POWER RATING</div>
        <input className="field" type="number" step="0.5" value={form.pr} onChange={e => set('pr', e.target.value)} placeholder="58.0" style={{ width: 90 }} /></div>
      <div><div style={{ fontSize: 9, color: 'var(--txt3)', marginBottom: 3, letterSpacing: 1 }}>HOME COURT</div>
        <input className="field" type="number" step="0.5" value={form.hc} onChange={e => set('hc', e.target.value)} placeholder="3.0" style={{ width: 80 }} /></div>
      <button className="btn primary" onClick={submit} style={{ alignSelf: 'flex-end' }}>ADD TO PREVIEW</button>
    </>
  );
}
