"""Weekly wins per NBA team, as a CSV and a chart.

Setup:  py -m pip install nba_api pandas matplotlib
Run:    py weekly_wins.py                      (current season)
        py weekly_wins.py --teams BOS NYK DEN  (also draws a bar chart for those teams)
        py weekly_wins.py --season 2025-26

Each run re-downloads the whole season from NBA.com, so just run it again to
update. Games come from stats.nba.com, falling back to NBA.com's schedule feed
and then ESPN's scoreboard if that is blocked (--source picks one). Weeks run
Monday to Sunday. Outputs go next to this script:
  weekly_wins.csv        one row per team per week (games, wins, losses, cumulative_wins)
  weekly_wins.png        heatmap of all teams; each cell is wins/games that week
  weekly_wins_teams.png  grouped bars for the chosen teams, only when --teams is given
"""

import argparse
import datetime as dt
import time
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import MaxNLocator
from nba_api.stats.endpoints import leaguegamelog


def default_season(today=None):
    today = today or dt.date.today()
    start = today.year if today.month >= 10 else today.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


GAME_COLUMNS = ["TEAM_ABBREVIATION", "GAME_ID", "GAME_DATE", "WL"]
NBA_TEAMS = set(
    "ATL BOS BKN CHA CHI CLE DAL DEN DET GSW HOU IND LAC LAL MEM MIA "
    "MIL MIN NOP NYK OKC ORL PHI PHX POR SAC SAS TOR UTA WAS".split()
)
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
}
CDN_SCHEDULE = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
# NBA game ids start with a code for the kind of game.
GAME_ID_PREFIX = {"Pre Season": "001", "Regular Season": "002", "Playoffs": "004", "PlayIn": "005"}


def fetch_games_stats(season, season_type, attempts=3, timeout=60):
    """stats.nba.com game log via nba_api: one row per team per game."""
    for attempt in range(attempts):
        try:
            log = leaguegamelog.LeagueGameLog(
                season=season, season_type_all_star=season_type, timeout=timeout
            )
            return log.get_data_frames()[0]
        except Exception as exc:
            if attempt == attempts - 1:
                raise
            print(f"stats.nba.com request failed ({exc}); retrying in 5 seconds...")
            time.sleep(5)


def fetch_games_cdn(season, season_type):
    """NBA.com's published season schedule, which carries final scores.

    Used when stats.nba.com refuses the request (it often blocks cloud servers
    such as GitHub's). It only covers the current season.
    """
    import requests

    r = requests.get(CDN_SCHEDULE, timeout=60, headers=BROWSER_HEADERS)
    r.raise_for_status()
    sched = r.json()["leagueSchedule"]
    if sched.get("seasonYear") and sched["seasonYear"] != season:
        raise RuntimeError(
            f"the schedule feed is for {sched['seasonYear']}, not {season}"
        )
    prefix = GAME_ID_PREFIX.get(season_type)
    rows = []
    for day in sched.get("gameDates", []):
        for g in day.get("games", []):
            gid = str(g.get("gameId", ""))
            if (prefix and not gid.startswith(prefix)) or g.get("gameStatus") != 3:
                continue  # wrong kind of game, or not finished
            date = str(g.get("gameDateEst") or g.get("gameDateTimeEst") or "")[:10]
            home, away = g.get("homeTeam") or {}, g.get("awayTeam") or {}
            hs, aws = int(home.get("score") or 0), int(away.get("score") or 0)
            if not date or hs == aws:
                continue
            for team, won in ((home, hs > aws), (away, aws > hs)):
                rows.append([team.get("teamTricode"), gid, date, "W" if won else "L"])
    return pd.DataFrame(rows, columns=GAME_COLUMNS)


ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
# ESPN's season type codes, checked on each game (the API rejects some filters).
ESPN_SEASON_TYPE = {"Pre Season": 1, "Regular Season": 2, "Playoffs": 3, "PlayIn": 5}
# ESPN abbreviations that differ from NBA.com's.
ESPN_TO_NBA = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}


def fetch_games_espn(season, season_type):
    """ESPN's public scoreboard, in chunks of four weeks across the season.

    Game dates are converted to US Eastern time to match NBA.com's dates.
    """
    import requests
    from zoneinfo import ZoneInfo

    start_year = int(season[:4])
    start = dt.date(start_year, 10, 1)
    end = min(dt.date.today(), dt.date(start_year + 1, 7, 15))
    want = ESPN_SEASON_TYPE.get(season_type)
    eastern = ZoneInfo("America/New_York")

    def get(dates):
        r = requests.get(ESPN_SCOREBOARD, params={"dates": dates, "limit": 1000},
                         timeout=60, headers=BROWSER_HEADERS)
        r.raise_for_status()
        return r.json().get("events", [])

    def events(lo, hi):
        """A date range in one request, or day by day if ESPN rejects the range."""
        try:
            return get(f"{lo:%Y%m%d}-{hi:%Y%m%d}")
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 400 or lo == hi:
                raise
            out, day = [], lo
            while day <= hi:
                out += get(f"{day:%Y%m%d}")
                day += dt.timedelta(days=1)
            return out

    rows, seen = [], set()
    chunk = start
    while chunk <= end:
        chunk_end = min(chunk + dt.timedelta(days=27), end)
        for ev in events(chunk, chunk_end):
            if ev.get("id") in seen:
                continue
            seen.add(ev.get("id"))
            if want and (ev.get("season") or {}).get("type") not in (None, want):
                continue
            comp = (ev.get("competitions") or [{}])[0]
            status = comp.get("status") or ev.get("status") or {}
            teams = comp.get("competitors") or []
            if not (status.get("type") or {}).get("completed") or len(teams) != 2:
                continue
            scores = [int(float(t.get("score") or 0)) for t in teams]
            if scores[0] == scores[1]:
                continue
            when = dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            day = when.astimezone(eastern).date().isoformat()
            for t, mine, theirs in zip(teams, scores, scores[::-1]):
                abbr = (t.get("team") or {}).get("abbreviation", "")
                rows.append([ESPN_TO_NBA.get(abbr, abbr), str(ev["id"]), day,
                             "W" if mine > theirs else "L"])
        chunk = chunk_end + dt.timedelta(days=1)
    return pd.DataFrame(rows, columns=GAME_COLUMNS)


def check_teams(games):
    """Fail loudly rather than write data with team codes we don't recognise."""
    unknown = sorted(set(games["TEAM_ABBREVIATION"]) - NBA_TEAMS)
    if unknown:
        raise RuntimeError(f"unrecognised team codes: {', '.join(map(str, unknown))}")
    return games


def fetch_games(season, season_type, source="auto"):
    """One row per team per game, from the chosen source.

    "auto" tries stats.nba.com, then NBA.com's schedule feed, then ESPN.
    """
    sources = {
        "stats": ("stats.nba.com game log",
                  lambda: fetch_games_stats(season, season_type, attempts=2, timeout=30)),
        "cdn": ("NBA.com schedule feed", lambda: fetch_games_cdn(season, season_type)),
        "espn": ("ESPN scoreboard", lambda: fetch_games_espn(season, season_type)),
    }
    order = list(sources) if source == "auto" else [source]
    for key in order:
        name, fetch = sources[key]
        try:
            games = check_teams(fetch())
        except Exception as exc:
            if source != "auto":
                raise
            print(f"Source failed: {name}: {exc}")
            continue
        print(f"Source: {name} ({games['GAME_ID'].nunique()} games)")
        return games
    raise SystemExit("All sources failed: " + ", ".join(sources[k][0] for k in order))


def weekly_wins(games):
    g = games[games["WL"].isin(["W", "L"])].copy()  # finished games only
    if g.empty:
        raise SystemExit("No finished games found for that season yet.")
    g["GAME_DATE"] = pd.to_datetime(g["GAME_DATE"])
    g["week_start"] = (
        g["GAME_DATE"] - pd.to_timedelta(g["GAME_DATE"].dt.weekday, unit="D")
    ).dt.normalize()
    g["win"] = (g["WL"] == "W").astype(int)

    wk = (
        g.groupby(["TEAM_ABBREVIATION", "week_start"])
        .agg(games=("win", "size"), wins=("win", "sum"))
        .reset_index()
        .rename(columns={"TEAM_ABBREVIATION": "team"})
    )
    # Include weeks where a team didn't play, so every team has every week.
    weeks = pd.date_range(wk["week_start"].min(), wk["week_start"].max(), freq="7D")
    full = pd.MultiIndex.from_product(
        [sorted(wk["team"].unique()), weeks], names=["team", "week_start"]
    )
    wk = wk.set_index(["team", "week_start"]).reindex(full, fill_value=0).reset_index()
    wk["losses"] = wk["games"] - wk["wins"]
    wk["cumulative_wins"] = wk.groupby("team")["wins"].cumsum()
    return wk


def week_labels(weeks):
    labels = [d.strftime("%b %d") for d in weeks]
    if (weeks[-1] + pd.Timedelta(days=6)).date() >= dt.date.today():
        labels[-1] += "\n(in progress)"
    return labels


def plot_heatmap(wk, title, path):
    wins = wk.pivot(index="team", columns="week_start", values="wins")
    games = wk.pivot(index="team", columns="week_start", values="games")
    totals = wk.groupby("team")[["wins", "losses"]].sum()
    order = totals.sort_values(["wins", "losses"], ascending=[False, True]).index
    wins, games, totals = wins.loc[order], games.loc[order], totals.loc[order]

    cmap = plt.get_cmap("Blues").copy()
    cmap.set_bad("#eeeeee")  # weeks with no games
    vmax = max(int(wins.to_numpy().max()), 1)

    fig, ax = plt.subplots(
        figsize=(max(6.0, 1.15 * wins.shape[1] + 3.5), 0.34 * len(order) + 2.4)
    )
    ax.imshow(
        wins.where(games > 0).to_numpy(dtype=float),
        cmap=cmap, vmin=0, vmax=vmax, aspect="auto",
    )
    for i, team in enumerate(order):
        for j, week in enumerate(wins.columns):
            w, n = int(wins.loc[team, week]), int(games.loc[team, week])
            text = f"{w}/{n}" if n else "–"
            dark = n and w > 0.6 * vmax
            ax.text(j, i, text, ha="center", va="center", fontsize=9,
                    color="white" if dark else "#222222")

    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(
        [f"{t} ({int(totals.loc[t, 'wins'])}-{int(totals.loc[t, 'losses'])})" for t in order]
    )
    ax.set_xticks(range(wins.shape[1]))
    ax.set_xticklabels(week_labels(wins.columns))
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    fig.suptitle(title, fontsize=13, fontweight="bold", x=0.02, ha="left")
    fig.text(0.02, 0.005, "Weeks start Monday. Cell = wins/games played that week. "
             "Sorted by total wins; record in brackets.", fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.savefig(path, dpi=150)
    return fig


def plot_bars(wk, teams, title, path):
    """Grouped bars: one group per week, one bar per chosen team."""
    known = set(wk["team"])
    bad = [t for t in teams if t not in known]
    if bad:
        raise SystemExit(f"Unknown team(s): {', '.join(bad)}. Valid: {', '.join(sorted(known))}")
    teams = list(dict.fromkeys(teams))  # drop duplicates, keep order
    pivot = wk.pivot(index="week_start", columns="team", values="wins")[teams]
    n, weeks = len(teams), len(pivot)
    width = 0.8 / n
    fig, ax = plt.subplots(figsize=(max(7.0, 1.7 * weeks + 3), 4.5))
    for k, t in enumerate(teams):
        pos = [i + (k - (n - 1) / 2) * width for i in range(weeks)]
        bars = ax.bar(pos, pivot[t], width=width * 0.95, label=t)
        ax.bar_label(bars, fontsize=8)
    ax.set_xticks(range(weeks))
    ax.set_xticklabels(week_labels(pivot.index))
    ax.set_ylim(0, max(int(pivot.to_numpy().max()), 1) + 1)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylabel("Wins in week")
    ax.set_title(title, loc="left", fontweight="bold")
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    ax.legend(ncol=min(n, 6), frameon=False, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    return fig


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--season", default=default_season(), help="e.g. 2026-27")
    p.add_argument("--type", default="Regular Season",
                   help='"Regular Season", "Playoffs", "PlayIn" or "Pre Season"')
    p.add_argument("--source", choices=["auto", "stats", "cdn", "espn"], default="auto",
                   help="where games come from: stats.nba.com, the NBA.com schedule feed, "
                        "ESPN's scoreboard, or auto (tries them in that order)")
    p.add_argument("--teams", nargs="+", metavar="ABBR",
                   help="team abbreviations for an extra bar chart, e.g. BOS NYK")
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent,
                   help="folder for the outputs (default: next to this script)")
    p.add_argument("--no-show", action="store_true", help="save files without opening windows")
    args = p.parse_args()

    print(f"Fetching {args.season} {args.type} games from NBA.com...")
    wk = weekly_wins(fetch_games(args.season, args.type, args.source))
    args.out.mkdir(parents=True, exist_ok=True)

    csv = args.out / "weekly_wins.csv"
    wk.assign(week_start=wk["week_start"].dt.date).to_csv(csv, index=False)
    title = f"NBA wins per team per week – {args.season} {args.type}"
    plot_heatmap(wk, title, args.out / "weekly_wins.png")
    saved = ["weekly_wins.csv", "weekly_wins.png"]
    if args.teams:
        plot_bars(wk, [t.upper() for t in args.teams], title, args.out / "weekly_wins_teams.png")
        saved.append("weekly_wins_teams.png")

    print(f"Saved in {args.out}: {', '.join(saved)}")
    if not args.no_show:
        plt.show()


if __name__ == "__main__":
    main()
