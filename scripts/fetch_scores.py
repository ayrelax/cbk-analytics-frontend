#!/usr/bin/env python3
"""Pull finished scores from ESPN and stage them for approval.

Runs on a schedule through the evening. For every game ESPN reports as complete,
it finds the matching row in `games`, writes the score and ESPN's game id, and
marks it pending. Nothing is graded and no rating moves -- the PR Update tab
still has the final say.

Two things make this simpler than it looks:

  * ESPN's scoreboard returns `competitors[].team.location`, which uses exactly
    the same names as the keys in espn_team_map.json. That file already exists
    and is already correct, so team matching is solved.
  * Matching is done on date plus both team ids, so a game only matches when
    everything agrees. Anything ambiguous is skipped and reported rather than
    guessed at.

Environment:
  SUPABASE_URL, SUPABASE_KEY   required
  SCORE_DATE                   optional, YYYY-MM-DD. Defaults to today in US
                               Eastern, and also sweeps the previous day so late
                               west-coast finals are not missed.
  DRY_RUN                      set to 1 to print what would be written
"""
import os
import sys
import json
import datetime as dt
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_KEY", "")
DRY = os.environ.get("DRY_RUN", "") == "1"

ESPN = ("https://site.api.espn.com/apis/site/v2/sports/basketball/"
        "mens-college-basketball/scoreboard")

# ESPN carries far more programmes than we rate. A game against an unmapped
# opponent is expected, not an error -- it just stays manual.
UNMAPPED_IS_FINE = True


def die(msg):
    print("ERROR: " + msg)
    sys.exit(1)


def sb_get(table, params):
    r = requests.get(f"{SB_URL}/rest/v1/{table}",
                     headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"},
                     params=params, timeout=60)
    if r.status_code >= 300:
        die(f"read {table} failed: {r.status_code} {r.text[:200]}")
    return r.json()


def sb_patch(table, row_id, body):
    r = requests.patch(f"{SB_URL}/rest/v1/{table}",
                       headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
                                "Content-Type": "application/json",
                                "Prefer": "return=minimal"},
                       params={"id": f"eq.{row_id}"}, data=json.dumps(body), timeout=60)
    if r.status_code >= 300:
        die(f"write games failed: {r.status_code} {r.text[:200]}")


def eastern_today():
    """ESPN's scoreboard day rolls over on US Eastern, so match that."""
    return (dt.datetime.utcnow() - dt.timedelta(hours=5)).date()


def fetch_scoreboard(date):
    """One day of Division I games. groups=50 is all of D1; the limit has to
    exceed the number of games or ESPN silently truncates at 100."""
    try:
        r = requests.get(ESPN, params={"dates": date.strftime("%Y%m%d"),
                                       "groups": "50", "limit": "400"}, timeout=45)
        if r.status_code >= 300:
            print(f"  ESPN returned {r.status_code} for {date} -- skipping this date")
            return []
        return r.json().get("events", [])
    except Exception as exc:
        # An undocumented endpoint can move or rate-limit. Never take the job
        # down over it; the manual path still works.
        print(f"  ESPN request failed for {date}: {exc}")
        return []


def parse_event(ev):
    """Pull the few fields we care about out of a large response."""
    comps = (ev.get("competitions") or [{}])[0]
    status = (comps.get("status") or {}).get("type") or {}
    if not status.get("completed"):
        return None                       # not finished, nothing to stage yet
    if status.get("name") != "STATUS_FINAL":
        return None                       # postponed, cancelled, forfeited
    home = away = None
    for c in comps.get("competitors") or []:
        side = {"homeAway": c.get("homeAway"),
                "loc": ((c.get("team") or {}).get("location") or "").strip(),
                "score": c.get("score")}
        if side["homeAway"] == "home":
            home = side
        elif side["homeAway"] == "away":
            away = side
    if not home or not away:
        return None
    try:
        hs, as_ = int(home["score"]), int(away["score"])
    except (TypeError, ValueError):
        return None
    return {"espn_id": str(ev.get("id")), "home_loc": home["loc"],
            "away_loc": away["loc"], "home_score": hs, "away_score": as_,
            "neutral": bool(comps.get("neutralSite"))}


def main():
    if not SB_URL or not SB_KEY:
        die("SUPABASE_URL and SUPABASE_KEY must be set")

    tmap = json.load(open(os.path.join(HERE, "espn_team_map.json")))

    # our teams, by work name
    teams = sb_get("teams", {"select": "id,team"})
    by_name = {t["team"]: t["id"] for t in teams}
    print(f"teams loaded: {len(by_name)}")

    # which dates to sweep
    if os.environ.get("SCORE_DATE"):
        dates = [dt.date.fromisoformat(os.environ["SCORE_DATE"])]
    else:
        today = eastern_today()
        dates = [today, today - dt.timedelta(days=1)]
    print("dates: " + ", ".join(str(d) for d in dates))

    # our scheduled games for those dates, still without a score
    lo, hi = min(dates).isoformat(), max(dates).isoformat()
    ours = sb_get("games", {
        "select": "id,game_date,home_team_id,away_team_id,home_score,away_score,espn_game_id",
        "game_date": f"gte.{lo}", "and": f"(game_date.lte.{hi})"})
    ours = [g for g in ours if lo <= str(g["game_date"])[:10] <= hi]
    open_games = {}
    for g in ours:
        if g.get("home_score") is not None:
            continue                       # already has a score, leave it alone
        key = (str(g["game_date"])[:10], g["home_team_id"], g["away_team_id"])
        open_games[key] = g
    print(f"our games in range: {len(ours)}, still without a score: {len(open_games)}")

    staged, unmapped, nomatch, already = 0, [], [], 0
    for date in dates:
        events = fetch_scoreboard(date)
        print(f"  {date}: ESPN returned {len(events)} events")
        for ev in events:
            p = parse_event(ev)
            if not p:
                continue
            hn, an = tmap.get(p["home_loc"]), tmap.get(p["away_loc"])
            if not hn or not an:
                unmapped.append((p["away_loc"], p["home_loc"]))
                continue
            hid, aid = by_name.get(hn), by_name.get(an)
            if not hid or not aid:
                unmapped.append((an, hn))
                continue
            key = (date.isoformat(), hid, aid)
            g = open_games.get(key)
            if not g:
                # either we do not carry this game, or it already has a score
                nomatch.append((p["away_loc"], p["home_loc"], date.isoformat()))
                continue
            body = {"espn_game_id": p["espn_id"],
                    "home_score": p["home_score"],
                    "away_score": p["away_score"],
                    "status": "pending_approval"}
            if DRY:
                print(f"    would stage: {an} {p['away_score']} at "
                      f"{hn} {p['home_score']}")
            else:
                sb_patch("games", g["id"], body)
            staged += 1
            del open_games[key]

    print()
    print(f"staged for approval: {staged}")
    if nomatch:
        print(f"finished but not in our schedule: {len(nomatch)}")
        for a, h, d in nomatch[:6]:
            print(f"    {d}  {a} at {h}")
    if unmapped:
        seen = sorted({f"{a} at {h}" for a, h in unmapped})
        print(f"unmapped opponents, left manual: {len(seen)}")
        for x in seen[:6]:
            print(f"    {x}")
        if not UNMAPPED_IS_FINE:
            die("unmapped teams present")
    if open_games:
        print(f"still awaiting a final: {len(open_games)}")
    print("done" + (" (dry run, nothing written)" if DRY else ""))


if __name__ == "__main__":
    main()
