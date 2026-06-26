// Frontend mirror of prEngine — instant client-side calculations
// so the UI never has to wait for the backend to show a line

export function calcSpread(homePR, homeHC, awayPR, neutral = false) {
  const hca = neutral ? 0 : homeHC;
  return (homePR + hca) - awayPR;
}

export function spreadToML(spread) {
  const abs = Math.abs(spread);
  if (abs < 0.5) return { fav: -110, dog: -110 };
  const favProb = 0.5 + abs * 0.028 + Math.max(0, abs - 10) * 0.004;
  const favML   = favProb >= 1 ? -99999 : -Math.round((favProb / (1 - favProb)) * 100 / 5) * 5;
  const dogML   = Math.round(((1 - favProb) / favProb) * 100 / 5) * 5;
  return { fav: favML, dog: dogML };
}

export function formatSpread(n) {
  const r = Math.round(n * 2) / 2;
  return r > 0 ? `+${r.toFixed(1)}` : r.toFixed(1);
}

export function formatOdds(n) {
  return n > 0 ? `+${n}` : `${n}`;
}

export function calcPRAdjustment({ homeScore, awayScore, homePR, homeHC, awayPR, neutral = false }) {
  const rawSpread = calcSpread(homePR, homeHC, awayPR, neutral);
  const margin    = homeScore - awayScore;
  const coverDiff = margin - rawSpread;
  const absDiff   = Math.abs(coverDiff);

  if (absDiff <= 5) return { homeAdj: 0, awayAdj: 0, reason: 'within 5 — no change' };

  const baseAdj = absDiff === 6 ? 0.5 : 1.0;
  let homeAdj   = coverDiff > 0 ? baseAdj : -baseAdj;
  let awayAdj   = coverDiff > 0 ? -baseAdj : baseAdj;
  let reason    = `${absDiff > 6 ? '7+' : '6'} pts vs spread → ±${baseAdj}`;

  const favSpread = Math.abs(rawSpread);
  const homeFav   = rawSpread > 0;
  const homeWon   = margin > 0;

  if (favSpread >= 10 && !homeFav && homeWon)  { homeAdj += 0.5; reason += ' | 10+ dog bonus'; }
  if (favSpread >= 10 && homeFav  && !homeWon) { homeAdj -= 0.5; reason += ' | 10+ fav penalty'; }
  if (favSpread >= 10 && homeFav  && homeWon)  { awayAdj -= 0.5; reason += ' | 10+ fav loss penalty (away)'; }
  if (favSpread >= 10 && !homeFav && !homeWon) { awayAdj += 0.5; reason += ' | 10+ dog bonus (away)'; }

  return { homeAdj, awayAdj, reason };
}

export function impliedProb(americanOdds) {
  if (americanOdds > 0) return 100 / (americanOdds + 100);
  return Math.abs(americanOdds) / (Math.abs(americanOdds) + 100);
}

export function calcVig(odds1, odds2) {
  return (impliedProb(odds1) + impliedProb(odds2) - 1) * 100;
}
