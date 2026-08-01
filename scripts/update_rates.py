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

_CACHE = {}


def grab(kind, file, season, columns=None):
    """Download once, keep the bytes, and read only the columns asked for.

    The play-by-play is 87 MB and 2.9 million rows. Fetching it twice and letting
    pandas expand every column killed the job outright -- the runner ran out of
    memory. Caching the raw bytes and passing a column list keeps it inside the
    runner's limit."""
    key = (kind, file, season)
    if key not in _CACHE:
        url = BASE.format(kind=kind, file=file, season=season)
        print(f"  downloading {url.split('/')[-1]} ...", flush=True)
        r = requests.get(url, timeout=600)
        if r.status_code != 200:
            print(f"  not available yet (HTTP {r.status_code})")
            _CACHE[key] = None
        else:
            print(f"  {len(r.content)/1e6:.1f} MB")
            _CACHE[key] = r.content
    raw = _CACHE[key]
    if raw is None:
        return None
    return pd.read_parquet(io.BytesIO(raw), columns=columns)

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

# ---------------------------------------------------------------------------
# team_profiles: pace, opponent-adjusted efficiency, shot mix and fouling.
# Feeds Method Of First Basket. Needs the team box scores and the play-by-play.
# ---------------------------------------------------------------------------

def possessions(df):
    return (df["field_goals_attempted"] - df["offensive_rebounds"]
            + df["total_turnovers"] + 0.475 * df["free_throws_attempted"])


def adjust(df, col_off, col_def, K=10, iters=40):
    """Iteratively strip out schedule strength. A raw margin badly understates
    teams from strong conferences -- on 2025-26 data Marquette read -0.7 raw but
    +5.0 adjusted, and every Big East side gained 4 to 6 points."""
    teams = sorted(set(df["team_location"]))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    L = df[col_off].mean()
    ti = df["team_location"].map(idx).values
    oi = df["opponent_team_location"].map(idx).values
    ok = ~pd.isna(oi)
    ti, oi = ti[ok].astype(int), oi[ok].astype(int)
    vo, vd = df[col_off].values[ok], df[col_def].values[ok]
    gp = np.bincount(ti, minlength=n).astype(float)
    aO = np.full(n, L); aD = np.full(n, L)
    for _ in range(iters):
        cO = vo * (L / np.maximum(aD[oi], 1))
        cD = vd * (L / np.maximum(aO[oi], 1))
        t = pd.DataFrame({"ti": ti, "o": cO, "d": cD}).groupby("ti").mean()
        nO = np.full(n, L); nD = np.full(n, L)
        nO[t.index] = t["o"]; nD[t.index] = t["d"]
        w = gp / (gp + K)
        aO = w * nO + (1 - w) * L
        aD = w * nD + (1 - w) * L
    return pd.DataFrame({"adj_off": aO, "adj_def": aD}, index=teams)


def build_team_profiles(season, tmap):
    tb = grab("team_boxscores", "team_box", season, columns=[
        "game_id", "team_id", "team_location", "opponent_team_id", "opponent_team_location",
        "team_home_away", "fouls", "field_goals_attempted", "free_throws_attempted",
        "offensive_rebounds", "total_turnovers", "team_score", "opponent_team_score"])
    if tb is None:
        print("  no team box scores yet"); return None
    pbp = grab("pbp", "play_by_play", season, columns=[
        "game_id", "team_id", "type_text", "text", "scoring_play", "score_value", "shooting_play"])

    num = ["fouls", "field_goals_attempted", "free_throws_attempted",
           "offensive_rebounds", "total_turnovers", "team_score", "opponent_team_score"]
    for c in num:
        tb[c] = pd.to_numeric(tb[c], errors="coerce")
    tb = tb.dropna(subset=num)
    tb["poss"] = possessions(tb)
    tb = tb[tb["poss"] > 40]
    tb["off_eff"] = tb["team_score"] / tb["poss"] * 100
    tb["def_eff"] = tb["opponent_team_score"] / tb["poss"] * 100
    tb["ftr"] = tb["free_throws_attempted"] / tb["field_goals_attempted"]
    tb["foul_rate"] = tb["fouls"] / tb["poss"]

    cnt = pd.concat([tb["team_location"], tb["opponent_team_location"]]).value_counts()
    ok = set(cnt[cnt >= 8].index)
    tb = tb[tb["team_location"].isin(ok) & tb["opponent_team_location"].isin(ok)].copy()
    if not len(tb):
        print("  not enough games yet"); return None

    A = adjust(tb, "off_eff", "def_eff")
    A["net"] = A["adj_off"] - A["adj_def"]

    # free-throw rate the defence allows
    opp = tb[["game_id", "team_id", "ftr"]].rename(
        columns={"team_id": "opponent_team_id", "ftr": "opp_got_ftr"})
    tb = tb.merge(opp, on=["game_id", "opponent_team_id"], how="left")

    # shot mix from the play-by-play
    if pbp is not None:
        s2 = pbp[(pbp["shooting_play"] == True) & (pbp["type_text"] != "MadeFreeThrow")]
        s2 = s2[~s2["text"].fillna("").str.contains("free throw", case=False, na=False)]
        is3 = (s2["text"].fillna("").str.contains("three point", case=False, na=False)
               | (s2["score_value"] == 3))
        rim = s2["type_text"].isin(["LayUpShot", "DunkShot", "TipShot"])
        zt = pd.DataFrame({"game_id": s2["game_id"], "team_id": s2["team_id"],
                           "is3": is3.astype(int),
                           "rim": (~is3 & rim).astype(int),
                           "rimmade": ((~is3 & rim) & (s2["scoring_play"] == True)).astype(int)})
        zg = zt.groupby(["game_id", "team_id"]).agg(
            three_rate=("is3", "mean"), rim_rate=("rim", "mean"),
            rm=("rimmade", "sum"), ra=("rim", "sum")).reset_index()
        zg["rim_pct"] = zg["rm"] / zg["ra"].replace(0, np.nan)
        tb = tb.merge(zg[["game_id", "team_id", "three_rate", "rim_rate", "rim_pct"]],
                      on=["game_id", "team_id"], how="left")
        oz = zg[["game_id", "team_id", "three_rate"]].rename(
            columns={"team_id": "opponent_team_id", "three_rate": "opp_three"})
        tb = tb.merge(oz, on=["game_id", "opponent_team_id"], how="left")
    else:
        for c in ["three_rate", "rim_rate", "rim_pct", "opp_three"]:
            tb[c] = np.nan

    p = tb.groupby("team_location").agg(
        games=("game_id", "count"), poss=("poss", "mean"), ftr=("ftr", "mean"),
        foul_rate=("foul_rate", "mean"), d_ftr_allowed=("opp_got_ftr", "mean"),
        three_rate=("three_rate", "mean"), rim_rate=("rim_rate", "mean"),
        rim_pct=("rim_pct", "mean"), d_three_rate=("opp_three", "mean")).join(A)
    p = p[p["games"] >= 8]
    p["mid_rate"] = 1 - p["three_rate"] - p["rim_rate"]

    K = 8
    for c in ["poss", "ftr", "foul_rate", "d_ftr_allowed", "three_rate",
              "rim_rate", "mid_rate", "rim_pct", "d_three_rate"]:
        L = p[c].mean()
        w = p["games"] / (p["games"] + K)
        p[c] = w * p[c] + (1 - w) * L

    p["team"] = p.index.map(tmap)
    p = p[p["team"].notna()].reset_index(drop=True)
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()

    def num_or_none(v):
        return None if pd.isna(v) else round(float(v), 4)

    rows = [{"team": r["team"], "season": season, "games": int(r["games"]),
             "poss": num_or_none(r["poss"]), "off_eff": num_or_none(r["adj_off"]),
             "def_eff": num_or_none(r["adj_def"]), "net": num_or_none(r["net"]),
             "ftr": num_or_none(r["ftr"]), "foul_rate": num_or_none(r["foul_rate"]),
             "d_ftr_allowed": num_or_none(r["d_ftr_allowed"]),
             "three_rate": num_or_none(r["three_rate"]), "mid_rate": num_or_none(r["mid_rate"]),
             "rim_rate": num_or_none(r["rim_rate"]), "rim_pct": num_or_none(r["rim_pct"]),
             "d_three_rate": num_or_none(r["d_three_rate"]),
             "updated_at": stamp}
            for _, r in p.iterrows()]
    return rows


def upsert(rows, table, conflict, chunk=500):
    url = f"{SB_URL}/rest/v1/{table}?on_conflict={conflict}"
    head = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
            "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}
    sent = 0
    for i in range(0, len(rows), chunk):
        r = requests.post(url, headers=head, data=json.dumps(rows[i:i+chunk]), timeout=120)
        if r.status_code >= 300:
            print("  upsert failed:", r.status_code, r.text[:300]); sys.exit(1)
        sent += len(rows[i:i+chunk])
        print(f"  upserted {sent}/{len(rows)}", flush=True)

def season_counts(season, min_games, min_mpg, release=True):
    """All the per-player counts for one season. Returns None if the files are not
    published yet, which is the normal state before a season tips off."""
    box = grab("player_boxscores", "player_box", season, columns=[
        "game_id", "athlete_id", "athlete_display_name", "team_id", "team_location",
        "minutes", "points", "did_not_play", "active"])
    if box is None:
        return None
    pbp = grab("pbp", "play_by_play", season, columns=[
        "game_id", "sequence_number", "scoring_play", "score_value", "athlete_id_1"])
    meta = leading_scorer_counts(box)
    if pbp is not None:
        meta = meta.join(first_event_counts(pbp), how="left")
    meta = meta.fillna(0)
    cols = (["ls_%d" % i for i in range(1, 6)] + ["fs_%d" % i for i in range(1, 6)]
            + ["f3_%d" % i for i in range(1, 4)])
    for c in cols:
        if c not in meta.columns:
            meta[c] = 0
        meta[c] = meta[c].astype(int)
    keep = meta[(meta["games"] >= min_games) & (meta["mpg"] >= min_mpg)]
    if release:
        _CACHE.clear()      # drop the prior season's bytes before loading the current one
    return keep


def main():
    season = int(os.environ.get("SEASON") or season_now())
    print(f"season {season}")

    # Last season is the fallback the app blends against early in a new year, so it
    # is kept on a looser filter -- a player who logged 8 games last year is still
    # useful evidence when this year has none.
    print(f"prior season {season - 1} ...")
    prev = season_counts(season - 1, 8, 10)
    print(f"  {0 if prev is None else len(prev)} players")

    print(f"current season {season} ...")
    # keep the current season cached -- team_profiles needs the same play-by-play
    cur = season_counts(season, 1, 0, release=False)
    if cur is None or not len(cur):
        if prev is None or not len(prev):
            print("nothing published for either season, nothing to do"); return
        print("  none yet, carrying the prior season forward")
        cur = prev.iloc[0:0]

    meta = cur.reset_index()

    tmap = json.load(open(os.path.join(HERE, "espn_team_map.json")))
    cols = (["ls_%d" % i for i in range(1, 6)] + ["fs_%d" % i for i in range(1, 6)]
            + ["f3_%d" % i for i in range(1, 4)])

    # Every player who appears in either season gets a row, so a returning player
    # with no games yet still carries last year's numbers for the blend.
    if prev is not None and len(prev):
        pv = prev[["games", "espn_team", "player_name"] + cols].copy()
        pv.columns = ["prev_games", "prev_espn_team", "prev_name"] + ["prev_" + c for c in cols]
        meta = meta.set_index("athlete_id").join(pv, how="outer").reset_index()
    else:
        for c in ["prev_games", "prev_espn_team", "prev_name"] + ["prev_" + c for c in cols]:
            meta[c] = np.nan

    # a player with no current-season row is carried on last year's name and team
    meta["player_name"] = meta["player_name"].fillna(meta.get("prev_name"))
    meta["espn_team"] = meta["espn_team"].fillna(meta.get("prev_espn_team"))
    meta["games"] = meta["games"].fillna(0)
    meta["mpg"] = meta["mpg"].fillna(0)
    meta["ppg"] = meta["ppg"].fillna(0)
    for c in cols:
        meta[c] = meta[c].fillna(0)
    meta["team"] = meta["espn_team"].map(tmap)

    keep = meta[meta["team"].notna()].copy()
    keep = keep[(keep["games"] > 0) | (keep["prev_games"].fillna(0) > 0)]
    has_prev = int((keep["prev_games"].fillna(0) > 0).sum())
    print(f"  {len(keep)} players on {keep['team'].nunique()} teams "
          f"({has_prev} carrying prior-season counts)")

    for c in cols:
        keep[c] = keep[c].astype(int)

    # updated_at has DEFAULT now(), but a default only fires on INSERT. These rows
    # already exist, so the upsert is an UPDATE and the column would never move --
    # leaving no way to tell a working job from a dead one. Send it explicitly.
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = [{"athlete_id": int(r.athlete_id), "player_name": r.player_name, "team": r.team,
             "season": season, "games": int(r.games),
             "mpg": round(float(r.mpg), 2), "ppg": round(float(r.ppg), 2),
             "updated_at": stamp,
             "prev_season": (season - 1) if (r.prev_games == r.prev_games and r.prev_games > 0) else None,
             "prev_games": int(r.prev_games) if (r.prev_games == r.prev_games) else 0,
             **{c: int(getattr(r, c)) for c in cols},
             **{"prev_" + c: (int(getattr(r, "prev_" + c))
                              if getattr(r, "prev_" + c) == getattr(r, "prev_" + c) else 0)
                for c in cols}} for r in keep.itertuples()]

    del meta
    print("upserting player_rates ...")
    upsert(rows, "player_rates", "athlete_id")

    print("building team_profiles ...")
    tp = build_team_profiles(season, tmap)
    if tp:
        print(f"  {len(tp)} teams")
        upsert(tp, "team_profiles", "team")
    else:
        print("  skipped")
    print("done")

if __name__ == "__main__":
    main()
