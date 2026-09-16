# Kijamii Saudi Cultural Intel

Saudi Arabia cultural-signal tracker — X/Twitter trends, bilingual news, TikTok
and Google Trends — published as a static site on GitHub Pages.

**Live site:** https://noorhussamnh-tech.github.io/Kijamii-Saudi-Cultural-Intel/

## How it updates

| Surface | Source | Cadence |
|---|---|---|
| X/Twitter trends + hashtags | getdaytrends.com | **Hourly** |
| Domestic & regional news | Google News RSS, Arab News, Al Arabiya, SPA, Okaz, Asharq Al-Awsat | **Hourly** |
| TikTok tab | Apify (`clockworks~tiktok-trends-scraper`) → `tiktok_cc.json` → direct scrape | ~Daily (paid, throttled) |
| Google tab | Apify (`automation-lab~google-trends-scraper`) → `google_manual.json` → pytrends | ~Daily (paid, throttled) |

`.github/workflows/update.yml` is the **only** live configuration. It runs
`update_trends.py`, commits `data.json` when it changed, and redeploys Pages.

### Why the TikTok and Google tabs are slower

Those two sources cost money per pull, so they sit behind a reuse window
(`APIFY_MAX_AGE_HOURS`, default 20) rather than running every hour. Everything
else is free to fetch and runs on every tick.

### Scheduling caveat

GitHub does not guarantee punctual scheduled workflows — runs on this repo have
historically been delayed by **2–5 hours** past their cron time, and GitHub drops
ticks entirely under load. Hourly cron therefore means *up to* 24 refreshes a day,
not one exactly on the hour.

The banner on the site shows the real last-change time in KSA, so freshness is
always visible rather than assumed. For punctual updates, point an external
scheduler at the `repository_dispatch` trigger:

```
curl -X POST https://api.github.com/repos/noorhussamnh-tech/Kijamii-Saudi-Cultural-Intel/dispatches \
  -H "Authorization: Bearer $GITHUB_PAT" \
  -H "Accept: application/vnd.github+json" \
  -d '{"event_type":"refresh"}'
```

## Configuration

Set under **Settings → Secrets and variables → Actions**.

| Name | Kind | Default | Purpose |
|---|---|---|---|
| `APIFY_TOKEN` | secret | — | Enables the TikTok/Google Apify pulls. Without it the script still runs on its fallbacks. |
| `APIFY_MAX_AGE_HOURS` | variable | `20` | Reuse a successful Apify pull for this long. Lower = fresher TikTok/Google, higher cost. |
| `APIFY_RETRY_HOURS` | variable | `6` | Back-off after a *failed* Apify pull, so a broken source cannot burn a run every hour. |
| `APIFY_TIKTOK_ACTOR` | variable | `clockworks~tiktok-trends-scraper` | Swap in a different actor. |
| `APIFY_GOOGLE_ACTOR` | variable | `automation-lab~google-trends-scraper` | Swap in a different actor. |

## Behaviour worth knowing

- **Quiet hours produce no commit.** `update_trends.py` compares content against
  what is already in `data.json` and only rewrites the file when something a
  reader would see has changed. The commit log stays a log of real movement.
- **`Last updated` means last *change*, not last *run*.** A run that finds nothing
  new leaves the stamp alone.
- **A source outage does not fail the run.** If getdaytrends is unreachable the
  workflow logs a warning, keeps the stored reading, and still refreshes news and
  redeploys the site.
- **Uploading a file redeploys immediately.** Pushes to `main` skip the scrape and
  go straight to the Pages deploy, so editing `index.html` in the GitHub UI goes
  live without waiting for or paying for a data refresh.
- **The open page refreshes itself** every 15 minutes, and whenever the tab is
  brought back to the foreground — a wall-mounted dashboard stays current without
  anyone reloading it. Your selected month/day is preserved across a refresh.

## Local preview

```bash
python3 -m http.server 8000     # then open http://localhost:8000/index.html
```

## Repo layout

```
.github/workflows/update.yml   the live workflow — the only one GitHub runs
update_trends.py               scraper + scorer; writes data.json
data.json                      the site's entire dataset (14-day rolling window)
index.html                     the whole front end, no build step
tiktok_cc.json                 hand-pasted TikTok Creative Center fallback
scripts/                       standalone helper; its nested workflow file is NOT run
```
