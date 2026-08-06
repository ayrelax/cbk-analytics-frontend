#!/usr/bin/env python3
"""
Rebuild player_shots in Supabase from ESPN play-by-play.

Sibling of update_shot_clock.py -- same parquet source, same possession
reconstruction, same team map. The difference is the grouping: shot clock
aggregates by team, this aggregates by player.

Replaces the manual load_player_shots.sql step.

Each cell is [share of the player's shots, FG%, points per shot], matching the
payload the Player Shots tab already reads:

    splits = {
      "ov": [FG%, PPS],
      "b":  {band   -> [share, FG%, PPS]},   fast / avg / press / end
      "s":  {source -> [share, FG%, PPS]},   turnover / dreb / made_fg / made_ft / oreb
      "z":  {zone   -> [share, FG%, PPS]}    rim / paint / mid / three
    }
"""
import os, io, json, datetime as dt
import requests, pandas as pd

SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_KEY"]
BASE = ("https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
        "espn_mens_college_basketball_{kind}/{file}_{season}.parquet")
HERE = os.path.dirname(os.path.abspath(__file__))
DRY = os.environ.get("DRY_RUN", "0") == "1"

# A player needs a real sample before percentages mean anything. Early in the
# season almost nobody clears this, which is correct -- better an empty tab than
# a shooter listed at 100% on two attempts.
MIN_SHOTS = int(os.environ.get("MIN_SHOTS", "40"))

BANDS = [("fast", 23, 30), ("avg", 15, 22), ("press", 8, 14), ("end", 0, 7)]
SOURCES = ["turnover", "dreb", "made_fg", "made_ft", "oreb"]
ZONES = ["rim", "paint", "mid", "three"]
FG_TYPES = {"JumpShot", "LayUpShot", "DunkShot", "TipShot", "Shot"}
RIM_TYPES = {"DunkShot", "TipShot", "LayUpShot"}


def season_now():
    t = dt.date.today()
    return t.year + 1 if t.month >= 10 else t.year


def grab(kind, file, season, columns=None):
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
    if is3:
        return "three"
    if type_text in RIM_TYPES:
        return "rim"
    if x != x or y != y:
        return "mid"
    d = ((float(x) - 25.0) ** 2 + float(y) ** 2) ** 0.5
    if d <= 4:
        return "rim"
    if d <= 14:
        return "paint"
    return "mid"


def walk_game(g):
    """Replay one game, labelling every field goal attempt with the shooter,
    the shot-clock band, how the possession started and the zone."""
    out = []
    start_sec, reset, src, period = None, 30, "made_fg", None

    for r in g.itertuples(index=False):
        t, sec, per = r.type_text, r.start_period_seconds_remaining, r.period_number

        if per != period:
            period, start_sec, reset, src = per, sec, 30, "made_fg"

        if t in FG_TYPES and r.shooting_play:
            made = bool(r.scoring_play)
            is3 = (r.points_attempted == 3)
            sc = None
            if start_sec is not None and sec is not None:
                sc = reset - (start_sec - sec)
            b = band_of(sc)
            aid = r.athlete_id_1
            if b is not None and src in SOURCES and aid == aid and aid is not None:
                out.append((int(aid), b, src, made,
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


def cell(s, total):
    """[share of the player's shots, FG%, points per shot]"""
    return [round(len(s) / total * 100, 1),
            round(s["made"].mean() * 100, 1),
            round(s["pts"].mean(), 2)]


def splits_for(df):
    n = len(df)
    out = {"ov": [round(df["made"].mean() * 100, 1), round(df["pts"].mean(), 2)],
           "b": {}, "s": {}, "z": {}}
    for b, _, _ in BANDS:
        s = df[df.band == b]
        if len(s):
            out["b"][b] = cell(s, n)
    for k in SOURCES:
        s = df[df.src == k]
        if len(s):
            out["s"][k] = cell(s, n)
    for z in ZONES:
        s = df[df.zone == z]
        if len(s):
            out["z"][z] = cell(s, n)
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
        "start_period_seconds_remaining", "type_text", "shooting_play",
        "scoring_play", "score_value", "points_attempted",
        "coordinate_x", "coordinate_y", "athlete_id_1"])
    if pbp is None or not len(pbp):
        print("no play-by-play published for this season yet, nothing to do")
        return

    box = grab("player_boxscores", "player_box", season,
               columns=["athlete_id", "athlete_display_name", "team_location"])
    if box is None:
        print("no player box scores yet, nothing to do")
        return

    tmap = json.load(open(os.path.join(HERE, "espn_team_map.json")))
    box = box[box["athlete_id"].notna()].drop_duplicates("athlete_id").copy()
    box["athlete_id"] = pd.to_numeric(box["athlete_id"], errors="coerce")
    box = box[box["athlete_id"].notna()]
    box["athlete_id"] = box["athlete_id"].astype("int64")
    names = dict(zip(box.athlete_id, box.athlete_display_name))
    teams = {a: tmap.get(t) for a, t in zip(box.athlete_id, box.team_location)}

    pbp = pbp.sort_values(["game_id", "sequence_number"])
    ngames = pbp.game_id.nunique()
    print(f"  {len(pbp):,} plays across {ngames:,} games -- replaying", flush=True)

    recs = []
    for i, (_, g) in enumerate(pbp.groupby("game_id", sort=False)):
        recs.extend(walk_game(g))
        if i and i % 1000 == 0:
            print(f"    {i:,} games", flush=True)

    shots = pd.DataFrame(recs, columns=["aid", "band", "src", "made", "pts", "zone"])
    print(f"  {len(shots):,} shots with a shot-clock reading")

    rows, skipped = [], 0
    for aid, s in shots.groupby("aid"):
        if len(s) < MIN_SHOTS:
            skipped += 1
            continue
        nm, tm = names.get(aid), teams.get(aid)
        if not nm or not tm:
            continue
        rows.append({"athlete_id": str(aid), "player_name": nm, "team": tm,
                     "shots": int(len(s)), "splits": splits_for(s),
                     "season": season})

    print(f"  {len(rows):,} players with at least {MIN_SHOTS} shots "
          f"({skipped:,} below the threshold)")

    if not rows:
        print("  nothing clears the sample threshold yet -- normal early in a season")
        return

    # Sanity check: rim shots should convert far better than anything else.
    rim = [r for r in rows if "rim" in r["splits"]["z"]]
    if rim:
        avg_rim = sum(r["splits"]["z"]["rim"][1] for r in rim) / len(rim)
        if not (55 <= avg_rim <= 80):
            print(f"  WARNING: average rim FG% is {avg_rim:.1f}%, expected 55-80")

    if DRY:
        print("DRY_RUN=1, nothing written")
        print(json.dumps(rows[0], indent=1)[:700])
        return

    print("  upserting ...")
    upsert(rows, "player_shots", "season,athlete_id")
    print("done")


if __name__ == "__main__":
    main()
