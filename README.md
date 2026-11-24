# Kijamii Saudi Cultural Intel

Saudi Arabia cultural-signal tracker — X/Twitter trends, bilingual news, TikTok
and Google Trends — published as a static site on GitHub Pages.

**Live site:** https://noorhussamnh-tech.github.io/Kijamii-Saudi-Cultural-Intel/

## How it updates

| Surface | Source | Cadence |
|---|---|---|
| X/Twitter trends + hashtags | getdaytrends.com | **Hourly** |
| Domestic & regional news | Google News RSS, Arab News, Al Arabiya, SPA, Okaz, Asharq Al-Awsat | **Hourly** |
| TikTok tab | Weekly upload `tiktok_upload.csv` (full top-100) + TikTok Creative Center direct (free, quality-filtered) → Apify → `tiktok_cc.json` | Every ~6h + weekly upload |
| Google tab | Google Trends official RSS (free, with linked news story) → Apify → `google_manual.json` → pytrends | **Hourly**, 24h rolling window |

`.github/workflows/update.yml` is the **only** live configuration. It runs
`update_trends.py`, commits `data.json` when it changed, and redeploys Pages.

### TikTok source (changed Nov 2026)

TikTok moved Creative Center to `ads.tiktok.com/creative/creativeCenter/trends`
and retired the old `creative_radar_api`. After that the Apify actor kept
"succeeding" with an empty dataset, and the tab silently showed the 27 Aug paste.
The tab now reads the new public endpoint directly. Logged out, TikTok shows the
**top 3 hashtags per period**, so the tab carries up to 6 (7-day + 30-day views).
Apify is only called if the direct pull fails. The page flags any TikTok data
older than 2 days, whatever the source.

The tab has three views — **All · 14 days**, **Arabic**, **English** — built
from `tiktok_history` in `data.json`: every Saudi hashtag seen in the last 14
days (first/last seen, days on the list, latest posts/views). Hashtags in the
latest pull are marked *Trending now*. Language is by script: Arabic letters →
Arabic, Latin letters → English. Categories fall back to TikTok's own industry
labels when our keyword categoriser has no match. All data is `countryCode: SA`;
a batch whose top creators aren't Saudi is discarded.

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

## Weekly TikTok upload (owner: ________ · every Sunday · ~5 min)

The automatic TikTok feed only sees the top 3 hashtags TikTok shows logged-out
visitors, and is quality-filtered. The credible full list needs a login:

1. Sign in at **ads.tiktok.com → Creative Center → Trends → Hashtags**
   (a free TikTok for Business account is enough).
2. Set **Region: Saudi Arabia** and **Last 7 days**. Click **View more** until
   the list reaches 100.
3. Select the whole table, copy it, and paste it into a blank Google Sheet
   (or Excel). Don't tidy it — the importer handles the messy paste.
   A clean sheet with columns `Rank, Hashtag, Industry, Posts, Views` also works.
4. **File → Download → CSV**. Rename the file to exactly `tiktok_upload.csv`.
5. On GitHub: repo → **Add file → Upload files** → drop it in → **Commit**
   (it replaces last week's).

The next hourly run imports it. On the TikTok tab those hashtags show as
**Weekly top #N**, and the note under the buttons shows the upload date. After
7 days the note says **⚠ due for a new upload** — that is the reminder.
If the run log says `no hashtags found`, the file isn't in a format the importer
can read; send it to whoever maintains this repo.

### Quality gate on the automatic feed

A hashtag from the logged-out feed is shown only if it has at least
`TIKTOK_MIN_POSTS` posts (3,000), `TIKTOK_MIN_VIEWS_PER_POST` views per post
(2,000), and a top creator with `TIKTOK_MIN_CREATOR_FOLLOWERS` followers (10,000).
Each is a repo variable, so it can be tuned without code changes. Dropped tags
are listed in the run log and removed from the 14-day list.

## Google tab

Reads Google's official *Trending now* RSS for Saudi Arabia every hour and keeps
the last 24 hours (`GOOGLE_WINDOW_HOURS`). Each trend carries the news story
Google linked to it, so every entry can be checked. Saudi Google also reflects
the large expat population (cricket, Bangladeshi and Indian news); the
**Arabic** view shows local conversation only. Apify is used only if the RSS is
unreachable.

## Configuration

Set under **Settings → Secrets and variables → Actions**.

| Name | Kind | Default | Purpose |
|---|---|---|---|
| `APIFY_TOKEN` | secret | — | Enables the TikTok/Google Apify pulls. Without it the script still runs on its fallbacks. |
| `APIFY_MAX_AGE_HOURS` | variable | `20` | Reuse a successful Apify pull for this long. Lower = fresher TikTok/Google, higher cost. |
| `APIFY_RETRY_HOURS` | variable | `6` | Back-off after a *failed* Apify pull, so a broken source cannot burn a run every hour. |
| `TIKTOK_DIRECT_HOURS` | variable | `6` | How often to re-pull TikTok Creative Center directly (free). |
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
data.json                      the site's entire dataset (14-day rolling window, incl. tiktok_history)
index.html                     the whole front end, no build step
tiktok_cc.json                 hand-pasted TikTok Creative Center fallback
scripts/                       standalone helper; its nested workflow file is NOT run
```
