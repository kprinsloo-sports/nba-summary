# NBA summary

Tracks how many games each NBA team wins per week (Monday to Sunday) and
keeps the results up to date automatically.

## What runs when

| When (Auckland time) | What | Where |
| --- | --- | --- |
| Tuesday ~07:00 | `weekly_wins.py` downloads the season's games and rewrites `data/` | GitHub Actions (`.github/workflows/weekly-wins.yml`) |
| Tuesday ~09:00 | A Claude scheduled task copies `data/weekly_wins.csv` into the NBA Weekly Wins dashboard | Claude |

To update outside the schedule, open the **Actions** tab, pick **Weekly wins**
and click **Run workflow**.

## Outputs (`data/`)

- `weekly_wins.csv`: one row per team per week, with columns `team`,
  `week_start`, `games`, `wins`, `losses`, `cumulative_wins`.
- `weekly_wins.png`: heatmap of every team's wins by week.

## Where the games come from

The script first asks stats.nba.com (via [nba_api](https://github.com/swar/nba_api)).
That API often blocks cloud servers such as GitHub's, so if it fails the
script falls back to NBA.com's published season schedule, which carries final
scores. The workflow log says which source was used. Only finished games count.

## Running it yourself

```
pip install -r requirements.txt
python weekly_wins.py                      # current season, opens the chart
python weekly_wins.py --teams BOS NYK DEN  # also a bar chart for those teams
python weekly_wins.py --season 2025-26 --source stats
```
