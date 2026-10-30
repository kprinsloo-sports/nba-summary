# NBA summary

Tracks how many games each NBA team wins per week (Monday to Sunday) and
keeps the results up to date automatically.

**Live page: https://kprinsloo-sports.github.io/nba-summary/** - line chart of
wins by week, wins to date, and a sortable table, with conference, division
and team filters. The page (`index.html`) reads `data/` directly, so it shows
the new numbers as soon as the weekly run commits them. Filters are kept in
the link, so a filtered view can be bookmarked or shared.

## What runs when

| When (Auckland time) | What | Where |
| --- | --- | --- |
| Tuesday ~07:00 | `weekly_wins.py` downloads the season's games and rewrites `data/`; the live page shows it within a few minutes | GitHub Actions (`.github/workflows/weekly-wins.yml`) |
| Tuesday ~09:00 | A Claude scheduled task copies `data/weekly_wins.csv` into the NBA Weekly Wins dashboard | Claude |

To update outside the schedule, open the **Actions** tab, pick **Weekly wins**
and click **Run workflow**.

## Outputs (`data/`)

- `weekly_wins.csv`: one row per team per week, with columns `team`,
  `week_start`, `games`, `wins`, `losses`, `cumulative_wins`.
- `weekly_wins_meta.json`: when the data was built, which source it came from, and the game count.
- `weekly_wins.png`: heatmap of every team's wins by week.
- `nba_teams.csv`: each team's full name, conference and division (used by the page's filters).

## Where the games come from

The script first asks stats.nba.com (via [nba_api](https://github.com/swar/nba_api)).
NBA.com blocks cloud servers such as GitHub's, so when that fails it tries
NBA.com's published season schedule (also blocked from GitHub so far), then
ESPN's public scoreboard. `data/weekly_wins_meta.json`, the page header and the
workflow run's annotations all say which source was used. Only finished games
count. Run on a home connection, the script normally gets stats.nba.com.

## Running it yourself

```
pip install -r requirements.txt
python weekly_wins.py                      # current season, opens the chart
python weekly_wins.py --teams BOS NYK DEN  # also a bar chart for those teams
python weekly_wins.py --season 2025-26 --source stats
```

## Viewing the page locally

Browsers won't load the data files from a page opened straight off disk.
Run `python -m http.server` in the repo folder and open http://localhost:8000.

`vendor/` holds a copy of [d3](https://d3js.org) v7.9.0 (ISC licence, see `vendor/d3-LICENSE.txt`) so the page needs no outside scripts.
