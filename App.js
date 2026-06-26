import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import Dashboard    from './pages/Dashboard';
import PowerRatings from './pages/PowerRatings';
import PreseasonLoader from './pages/PreseasonLoader';
import Spreads      from './pages/Spreads';
import Futures      from './pages/Futures';
import NCAABracket  from './pages/NCAABracket';
import Tools        from './pages/Tools';
import './App.css';

export default function App() {
  const [clock, setClock] = useState('');
  const [syncStatus, setSyncStatus] = useState(null);

  useEffect(() => {
    const tick = () => {
      const n  = new Date();
      const h  = n.getHours() % 12 || 12;
      const m  = String(n.getMinutes()).padStart(2, '0');
      const s  = String(n.getSeconds()).padStart(2, '0');
      const ap = n.getHours() < 12 ? 'AM' : 'PM';
      setClock(`${h}:${m}:${s} ${ap} ET`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <BrowserRouter basename={process.env.PUBLIC_URL}>
      <div className="app">
        <header className="top-bar">
          <div className="logo">CAESARS <span>// </span>CBK ANALYTICS</div>
          <div className="top-right">
            {syncStatus && (
              <div className={`sync-badge ${syncStatus}`}>
                {syncStatus === 'syncing' ? '⟳ SYNCING' : syncStatus === 'done' ? '✓ SYNCED' : '⚠ ERROR'}
              </div>
            )}
            <div className="live-badge"><span className="dot" />LIVE</div>
            <div className="clock">{clock}</div>
          </div>
        </header>

        <nav className="nav">
          <NavLink to="/"              end>DASHBOARD</NavLink>
          <NavLink to="/ratings">POWER RATINGS</NavLink>
          <NavLink to="/preseason">PRESEASON LOADER</NavLink>
          <NavLink to="/spreads">GAME SPREADS</NavLink>
          <NavLink to="/futures">FUTURES</NavLink>
          <NavLink to="/ncaa">NCAA TOURNAMENT</NavLink>
          <NavLink to="/tools">ODDS TOOLS</NavLink>
        </nav>

        <main className="main-content">
          <Routes>
            <Route path="/"          element={<Dashboard setSyncStatus={setSyncStatus} />} />
            <Route path="/ratings"   element={<PowerRatings />} />
            <Route path="/preseason" element={<PreseasonLoader />} />
            <Route path="/spreads"   element={<Spreads />} />
            <Route path="/futures"   element={<Futures />} />
            <Route path="/ncaa"      element={<NCAABracket />} />
            <Route path="/tools"     element={<Tools />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
