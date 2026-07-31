#!/usr/bin/env python3
"""
Refresh player_rates in Supabase from ESPN box scores and play-by-play.

Runs on a schedule from GitHub Actions. Downloads two public parquet files, recomputes
the season counts the prop models use, and upserts them. Nothing to install locally.

  ls_1..ls_5   games finished 1st..5th in scoring, across both teams
  fs_1..fs_5   games they were the 1st..5th player to score
  f3_1..f3_3   games they were the 1st..3rd to make a three
"""
import os, sys, json, io, datetime as dt
import requests, pandas as pd, numpy as np

SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_KEY"]
BASE = ("https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
        "espn_mens_college_basketball_{kind}/{file}_{season}.parquet")
HERE = os.path.dirname(os.path.abspath(__file__))

def season_now():
    """College season is labelled by the year it ends. Nov 2026 -> season 2027."""
    t = dt.date.today()
    return t.year + 1 if t.month >= 10 else t.year

def grab(kind, file, season):
    url = BASE.format(kind=kind, file=file, season=season)
    print(f"  downloading {url.split('/')[-1]} ...", flush=True)
    r = requests.get(url, timeout=600)
    if r.status_code != 200:
        print(f"  not available yet (HTTP {r.status_code})")
        return None
    print(f"  {len(r.content)/1e6:.1f} MB")
    return pd.read_parquet(io.BytesIO(r.content))

def leading_scorer_counts(box):
    # NOTE: do NOT filter on box["active"]. That flag does not mean "played in this
    # game" -- more than half of all genuine appearances carry active=false with real
    # minutes and points. minutes > 0 is the correct test.
    b = box.copy()
    b["points"] = pd.to_numeric(b["points"], errors="coerce")
    b["minutes"] = pd.to_numeric(b["minutes"], errors="coerce")
    b = b[(b["minutes"] > 0) & (b["points"].notna())]
    b = b.dropna(subset=["athlete_id"])
    b["athlete_id"] = b["athlete_id"].astype("int64")
    b["rk"] = b.groupby("game_id")["points"].rank(method="min", ascending=False)
    ls = (b[b["rk"] <= 5]
          .groupby(["athlete_id", b["rk"].astype(int)]).size().unstack(fill_value=0))
    ls.columns = [f"ls_{c}" for c in ls.columns]
    meta = b.groupby("athlete_id").agg(games=("game_id", "count"),
                                       mpg=("minutes", "mean"),
                                       ppg=("points", "mean"),
                                       player_name=("athlete_display_name", "last"),
                                       espn_team=("team_location", "last"))
    return meta.join(ls, how="left").fillna(0)

def first_event_counts(pbp):
    sc = pbp[(pbp["scoring_play"] == True) & (pbp["athlete_id_1"].notna())].copy()
    sc["athlete_id_1"] = sc["athlete_id_1"].astype("int64")
    sc = sc.sort_values(["game_id", "sequence_number"])

    first = sc.drop_duplicates(subset=["game_id", "athlete_id_1"], keep="first").copy()
    first["rk"] = first.groupby("game_id").cumcount() + 1
    fs = (first[first["rk"] <= 5].groupby(["athlete_id_1", "rk"]).size().unstack(fill_value=0))
    fs.columns = [f"fs_{c}" for c in fs.columns]

    t3 = sc[sc["score_value"] == 3]
    f3 = t3.drop_duplicates(subset=["game_id", "athlete_id_1"], keep="first").copy()
    f3["rk"] = f3.groupby("game_id").cumcount() + 1
    f3c = (f3[f3["rk"] <= 3].groupby(["athlete_id_1", "rk"]).size().unstack(fill_value=0))
    f3c.columns = [f"f3_{c}" for c in f3c.columns]

    out = fs.join(f3c, how="outer").fillna(0)
    out.index.name = "athlete_id"
    return out

def upsert(rows, chunk=500):
    url = f"{SB_URL}/rest/v1/player_rates?on_conflict=athlete_id"
    head = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
            "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}
    sent = 0
    for i in range(0, len(rows), chunk):
        r = requests.post(url, headers=head, data=json.dumps(rows[i:i+chunk]), timeout=120)
        if r.status_code >= 300:
            print("  upsert failed:", r.status_code, r.text[:300]); sys.exit(1)
        sent += len(rows[i:i+chunk])
        print(f"  upserted {sent}/{len(rows)}", flush=True)

def main():
    season = int(os.environ.get("SEASON") or season_now())
    print(f"season {season}")

    box = grab("player_boxscores", "player_box", season)
    if box is None:
        print("no box scores yet for this season, nothing to do"); return
    pbp = grab("pbp", "play_by_play", season)

    print("computing counts ...")
    meta = leading_scorer_counts(box)
    if pbp is not None:
        meta = meta.join(first_event_counts(pbp), how="left")
    meta = meta.fillna(0).reset_index()

    tmap = json.load(open(os.path.join(HERE, "espn_team_map.json")))
    meta["team"] = meta["espn_team"].map(tmap)

    keep = meta[(meta["games"] >= 8) & (meta["mpg"] >= 10) & (meta["team"].notna())].copy()
    print(f"  {len(keep)} rotation players on {keep['team'].nunique()} teams")

    cols = (["ls_%d" % i for i in range(1, 6)] + ["fs_%d" % i for i in range(1, 6)]
            + ["f3_%d" % i for i in range(1, 4)])
    for c in cols:
        if c not in keep.columns: keep[c] = 0
        keep[c] = keep[c].astype(int)

    # updated_at has DEFAULT now(), but a default only fires on INSERT. These rows
    # already exist, so the upsert is an UPDATE and the column would never move --
    # leaving no way to tell a working job from a dead one. Send it explicitly.
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = [{"athlete_id": int(r.athlete_id), "player_name": r.player_name, "team": r.team,
             "season": season, "games": int(r.games),
             "mpg": round(float(r.mpg), 2), "ppg": round(float(r.ppg), 2),
             "updated_at": stamp,
             **{c: int(getattr(r, c)) for c in cols}} for r in keep.itertuples()]

    print("upserting ...")
    upsert(rows)
    print("done")

if __name__ == "__main__":
    main()
