#!/usr/bin/env python3
"""
Rebuild shot_clock_data in Supabase from ESPN play-by-play.

Same shape as update_rates.py: downloads the public parquet, recomputes, upserts.
Nothing to install locally, no R, no hoopR package -- this reads the same files
hoopR reads.

ESPN publishes no shot clock, so it is reconstructed. A possession starts on a
defensive rebound, a steal, the other team's turnover, a made basket or made free
throw, or the start of a period. An offensive rebound does not start a new
possession but resets the clock to 20 rather than 30, per the NCAA rule in force
since 2018-19.

Bands are seconds REMAINING on the shot clock:
    fast 23-30   avg 15-22   press 8-14   end 0-7

Each output row is [share of shots, FG%, points per shot, 3PA share, 3P%, 2P%],
matching the payload the Shot Clock tab already expects.
"""
import os, io, json, datetime as dt
import requests, pandas as pd, numpy as np

SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_KEY"]
BASE = ("https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
        "espn_mens_college_basketball_{kind}/{file}_{season}.parquet")
HERE = os.path.dirname(os.path.abspath(__file__))
DRY = os.environ.get("DRY_RUN", "0") == "1"

BANDS = [("fast", 23, 30), ("avg", 15, 22), ("press", 8, 14), ("end", 0, 7)]
SOURCES = ["turnover", "dreb", "made_fg", "made_ft", "oreb"]
ZONES = ["rim", "paint", "mid", "three"]
FG_TYPES = {"JumpShot", "LayUpShot", "DunkShot", "TipShot", "Shot"}
RIM_TYPES = {"DunkShot", "TipShot", "LayUpShot"}


def season_now():
    """College season is labelled by the year it ends. Nov 2026 -> season 2027."""
    t = dt.date.today()
    return t.year + 1 if t.month >= 10 else t.year


def grab(kind, file, season, columns=None):
    """Download the parquet and read only the columns asked for.

    The play-by-play is ~90 MB and 2.9 million rows. Passing a column list keeps
    the runner inside its memory limit -- letting pandas expand all 62 columns
    will kill the job."""
    url = BASE.format(kind=kind, file=file, season=season)
    print(f"  downloading {url.split('/')[-1]} ...", flush=True)
    r = requests.get(url, timeout=900)
    if r.status_code != 200:
        print(f"  not available yet (HTTP {r.status_code})")
        return None
    print(f"  {len(r.content)/1e6:.1f} MB")
    return pd.read_parquet(io.BytesIO(r.content), columns=columns)


def band_of(sc):
    if sc is None or sc != sc or sc < 0 or sc > 30:
        return None
    for name, lo, hi in BANDS:
        if lo <= sc <= hi:
            return name
    return None


def zone_of(type_text, is3, x, y):
    """Three is definitional. Otherwise the shot type does most of the work and
    the coordinate separates paint from mid-range."""
    if is3:
        return "three"
    if type_text in RIM_TYPES:
        return "rim"
    if x != x or y != y:
        return "mid"
    # ESPN half-court coordinates: basket sits near (25, 0) in a 50-wide court.
    d = ((float(x) - 25.0) ** 2 + float(y) ** 2) ** 0.5
    if d <= 4:
        return "rim"
    if d <= 14:
        return "paint"
    return "mid"


def walk_game(g):
    """Replay one game and label every field goal attempt with a band, a source
    and a zone. Returns a list of tuples."""
    out = []
    hid = g.home_team_id.iloc[0]
    aid = g.away_team_id.iloc[0]
    start_sec = None
    reset = 30
    src = "period start"
    period = None

    for r in g.itertuples(index=False):
        t = r.type_text
        sec = r.start_period_seconds_remaining
        per = r.period_number

        if per != period:
            period, start_sec, reset, src = per, sec, 30, "made_fg"

        if t in FG_TYPES and r.shooting_play:
            made = bool(r.scoring_play)
            is3 = (r.points_attempted == 3)
            sc = None
            if start_sec is not None and sec is not None:
                sc = reset - (start_sec - sec)
            b = band_of(sc)
            if b is not None and src in SOURCES:
                dtid = aid if r.team_id == hid else hid
                out.append((r.team_id, dtid, b, src, made, bool(is3),
                            (r.score_value if made else 0) or 0,
                            zone_of(t, is3, r.coordinate_x, r.coordinate_y)))
            if made:
                start_sec, reset, src = sec, 30, "made_fg"
            continue

        if t == "Defensive Rebound":
            start_sec, reset, src = sec, 30, "dreb"
        elif t == "Offensive Rebound":
            start_sec, reset, src = sec, 20, "oreb"
        elif t in ("Steal", "Lost Ball Turnover"):
            start_sec, reset, src = sec, 30, "turnover"
        elif t == "MadeFreeThrow":
            start_sec, reset, src = sec, 30, "made_ft"
    return out


def row6(s):
    """[share is filled by caller, FG%, PPS, 3PA share, 3P%, 2P%]"""
    if not len(s):
        return None
    fg = s["made"].mean() * 100
    pps = s["pts"].mean()
    t3 = s["is3"].mean() * 100
    p3 = s.loc[s["is3"], "made"].mean() * 100 if s["is3"].any() else 0.0
    p2 = s.loc[~s["is3"], "made"].mean() * 100 if (~s["is3"]).any() else 0.0
    return [round(fg, 1), round(pps, 2), round(t3, 1), round(p3, 1), round(p2, 1)]


def profile(df):
    """Build the {n,b,s,z,bz,zx,sx} block for one slice of shots."""
    n = len(df)
    if not n:
        return None
    out = {"n": n, "b": {}, "s": {}, "z": {}, "bz": {}, "zx": {}, "sx": {}}

    for b, _, _ in BANDS:
        s = df[df.band == b]
        if len(s):
            out["b"][b] = [round(len(s) / n * 100, 1)] + row6(s)
    for k in SOURCES:
        s = df[df.src == k]
        if len(s):
            out["s"][k] = [round(len(s) / n * 100, 1)] + row6(s)
    for z in ZONES:
        s = df[df.zone == z]
        if len(s):
            out["z"][z] = [round(len(s) / n * 100, 1)] + row6(s)

    for b, _, _ in BANDS:
        sb = df[df.band == b]
        if not len(sb):
            continue
        out["bz"][b] = [round((sb.zone == z).mean() * 100, 1) for z in ZONES]
        out["zx"][b] = {}
        for z in ZONES:
            sz = sb[sb.zone == z]
            if len(sz):
                out["zx"][b][z] = [round(len(sz) / len(sb) * 100, 1),
                                   round(sz["pts"].mean(), 2)]
    for k in SOURCES:
        sk = df[df.src == k]
        if not len(sk):
            continue
        out["sx"][k] = {}
        for b, _, _ in BANDS:
            sb = sk[sk.band == b]
            if len(sb):
                out["sx"][k][b] = [round(len(sb) / len(sk) * 100, 1),
                                   round(sb["pts"].mean(), 2)]
    return out


def upsert(rows, table, conflict, chunk=200):
    url = f"{SB_URL}/rest/v1/{table}?on_conflict={conflict}"
    head = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal"}
    for i in range(0, len(rows), chunk):
        r = requests.post(url, headers=head, data=json.dumps(rows[i:i + chunk]), timeout=120)
        if r.status_code >= 300:
            raise SystemExit(f"upsert failed {r.status_code}: {r.text[:400]}")
        print(f"    {min(i+chunk, len(rows))}/{len(rows)}", flush=True)


def main():
    season = int(os.environ.get("SEASON") or season_now())
    print(f"season {season}")

    pbp = grab("pbp", "play_by_play", season, columns=[
        "game_id", "sequence_number", "period_number",
        "start_period_seconds_remaining", "type_text", "team_id",
        "shooting_play", "scoring_play", "score_value", "points_attempted",
        "coordinate_x", "coordinate_y", "home_team_id", "away_team_id",
        "home_team_name", "away_team_name"])
    if pbp is None or not len(pbp):
        print("no play-by-play published for this season yet, nothing to do")
        return

    # ESPN team id -> ESPN display name, then through the existing map to your names
    tmap = json.load(open(os.path.join(HERE, "espn_team_map.json")))
    ids = pd.concat([
        pbp[["home_team_id", "home_team_name"]].rename(
            columns={"home_team_id": "tid", "home_team_name": "nm"}),
        pbp[["away_team_id", "away_team_name"]].rename(
            columns={"away_team_id": "tid", "away_team_name": "nm"})]).drop_duplicates("tid")
    id2name = dict(zip(ids.tid, ids.nm.map(tmap)))
    unmapped = sorted({n for t, n in zip(ids.tid, ids.nm) if tmap.get(n) is None})
    if unmapped:
        print(f"  {len(unmapped)} ESPN teams not in espn_team_map.json: {unmapped[:8]}")

    pbp = pbp.sort_values(["game_id", "sequence_number"])
    ngames = pbp.game_id.nunique()
    print(f"  {len(pbp):,} plays across {ngames:,} games -- replaying", flush=True)

    recs = []
    for i, (_, g) in enumerate(pbp.groupby("game_id", sort=False)):
        recs.extend(walk_game(g))
        if i and i % 1000 == 0:
            print(f"    {i:,} games", flush=True)

    shots = pd.DataFrame(recs, columns=["tid", "dtid", "band", "src", "made", "is3", "pts", "zone"])
    print(f"  {len(shots):,} shots with a shot-clock reading")

    shots["team"] = shots.tid.map(id2name)
    shots["dteam"] = shots.dtid.map(id2name)
    shots = shots[shots.team.notna()]

    rows = []
    lg = profile(shots)
    rows.append({"side": "meta", "team": "_",
                 "payload": {"lg": lg, "ng": int(ngames), "ns": int(len(shots))},
                 "season": season})
    for team, s in shots.groupby("team"):
        p = profile(s)
        if p:
            rows.append({"side": "o", "team": team, "payload": p, "season": season})
    for team, s in shots.groupby("dteam"):
        p = profile(s)
        if p:
            rows.append({"side": "d", "team": team, "payload": p, "season": season})

    print(f"  {len(rows)} rows ready "
          f"({sum(1 for r in rows if r['side']=='o')} offense, "
          f"{sum(1 for r in rows if r['side']=='d')} defense)")

    # Sanity check against the known league shape. Fast breaks are about a fifth
    # of all shots and field goal percentage falls monotonically as the clock
    # runs down. If that stops being true, something upstream changed.
    b = lg["b"]
    fgs = [b[k][1] for k, _, _ in BANDS if k in b]
    if not all(x > y for x, y in zip(fgs, fgs[1:])):
        print(f"  WARNING: FG% is not falling across bands: {fgs}")
    if not (10 <= b.get("fast", [0])[0] <= 30):
        print(f"  WARNING: fast-break share looks wrong: {b.get('fast',[None])[0]}%")

    if DRY:
        print("DRY_RUN=1, nothing written")
        print(json.dumps(lg["b"], indent=1))
        return

    print("  upserting ...")
    upsert(rows, "shot_clock_data", "season,side,team")
    print("done")


if __name__ == "__main__":
    main()
