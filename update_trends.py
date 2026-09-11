#!/usr/bin/env python3
"""Daily updater for the Kijamii Saudi Radar. Runs inside GitHub Actions."""
import json, os, re, sys, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html import unescape

# pytrends is optional — install via: pip install pytrends --break-system-packages
try:
    from pytrends.request import TrendReq as _TrendReq
    HAS_PYTRENDS = True
except ImportError:
    HAS_PYTRENDS = False

RIYADH = timezone(timedelta(hours=3))
NOW = datetime.now(RIYADH)
DAY_KEY = NOW.strftime("%Y-%m-%d")
DAY_LABEL = NOW.strftime("%a %d %b")
BANNER = NOW.strftime("%A, %d %B %Y")
NEWS_DATE = NOW.strftime("%d %b %Y")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"}
RANK_BONUS = {1: 10, 2: 8, 3: 6, 4: 4, 5: 3}
STREAK_DAYS = 3
STREAK_BONUS = 5

CYRILLIC = re.compile("[\\u0400-\\u04FF]")
ARABIC  = re.compile("[\\u0600-\\u06FF]")
PHONE   = re.compile(r"\d{7,}")

TIKTOK_GENERIC = {
    "fyp","foryou","foryoupage","foryourpage","viral","trending","duet","stitch",
    "meme","funny","tiktok","follow","like","explore","reels","shorts","goviral",
    "comedy","pov","fypage","explore","خليجي","للجميع","اكسبلور","ترند",
}

CATS = [
    ("Football", ["الاتحاد","الهلال","النصر","الاهلي","الحزم","برشلونة","ريال","ليفربول",
                  "تشيلسي","روما","نيوكاسل","فولهام","الدوري","مباراة","هدف","لاعب",
                  "سانشيز","الونسو","بيدرو","اربيلوا","مارتينيلي","بالمر","رافينها"]),
    ("Politics / Diplomacy", ["محمد_بن_سلمان","الملك","الامير","الرييس","وزير","قمة","زياره",
                              "سوريا","اليمن","فلسطين","ايران","باريس","دبلوماسي"]),
    ("Education", ["مدارس","الدراسه","الطلاب","الجامعه","المعلم","التعليم"]),
    ("Esports", ["الرياضات_الالكترونيه","الرياضات الالكترونيه","EWC","قيمرز","الالكترونيه"]),
    ("Security", ["البحر الاحمر","هجوم","عسكري","الحوثي","صاروخ","امن"]),
    ("Finance / Royalty", ["الوليد","بن طلال","اسهم","الاقتصاد","استثمار","صندوق"]),
    ("Culture / Society", ["خواطر","رمضان","العيد","فن","حفل","مهرجان","الوطني",
                           "اليوم_الوطني","التأسيس","التاسيس","موسم","الرياض_سيزون",
                           "تراث","الهجن","قهوة","عرضه"]),
]


def get(url, timeout=45):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def categorize(text):
    for cat, keys in CATS:
        if any(k in text for k in keys):
            return cat
    return "General"


def is_spam(t):
    if CYRILLIC.search(t) and ARABIC.search(t):
        return True
    if PHONE.search(t):
        return True
    if len(t) < 2 or len(t) > 60:
        return True
    return False


def scrape_trends():
    html = get("https://getdaytrends.com/saudi-arabia/")
    raw = re.findall(
        r'<a[^>]+href="/[a-z\-]+/trend/[^"]*"[^>]*>(.*?)</a>', html, re.S | re.I)
    trends, seen = [], set()
    for r in raw:
        t = unescape(re.sub(r"<[^>]+>", "", r)).strip()
        if not t or t in seen or is_spam(t):
            continue
        seen.add(t)
        trends.append(t)

    tags = []
    for m in re.finditer(
            r'<a[^>]+href="/[a-z\-]+/trend/[^"]*"[^>]*>\s*(#[^<]{2,60}?)\s*</a>'
            r'.{0,400}?<td[^>]*>\s*([\d,]{2,})\s*</td>', html, re.S | re.I):
        txt = unescape(m.group(1)).strip()
        try:
            sc = int(m.group(2).replace(",", ""))
        except ValueError:
            continue
        if is_spam(txt) or any(t["text"] == txt for t in tags):
            continue
        tags.append({"text": txt, "score": sc})
        if len(tags) >= 5:
            break

    if len(tags) < 3:
        hs = [t for t in trends if t.startswith("#")][:5]
        tags = [{"text": h, "score": 100 - i * 12} for i, h in enumerate(hs)]
        print(f"  hashtag volumes unparsed ({len(tags)} ranked from trends)",
              file=sys.stderr)

    if len(trends) < 10:
        print("=== PARSE FAILED - anchor sample ===", file=sys.stderr)
        for a in re.findall(r"<a[^>]+href=\"[^\"]*trend[^\"]*\"[^>]*>.{0,80}", html,
                            re.S | re.I)[:15]:
            print("  " + a.replace("\n", " "), file=sys.stderr)
        print(f"=== html length: {len(html)} ===", file=sys.stderr)
        sys.exit(f"FAIL: only {len(trends)} trends parsed.")
    return trends[:20], tags


def score(trends, prev_days):
    recent = [k for k in sorted(prev_days.keys()) if k < DAY_KEY][-(STREAK_DAYS - 1):]
    out, streaks = [], []
    for i, t in enumerate(trends, 1):
        pts = 4 + RANK_BONUS.get(i, 2 if i <= 10 else 0)
        run = 1
        for dk in reversed(recent):
            if any(x["text"] == t for x in prev_days[dk]["trends"]):
                run += 1
            else:
                break
        if run >= STREAK_DAYS:
            pts += STREAK_BONUS
            streaks.append((t, run))
        out.append({"rank": i, "text": t, "cat": categorize(t), "pts": pts})
    return out, streaks


def build_signals(trends):
    groups = {}
    for t in trends:
        groups.setdefault(categorize(t), []).append(t)
    icons = {"Football": "⚽", "Politics / Diplomacy": "🏛️", "Education": "📚",
             "Esports": "🎮", "Security": "🌊", "Finance / Royalty": "💰",
             "Culture / Society": "🎭", "General": "📌"}
    sigs = sorted(groups.items(), key=lambda kv: -len(kv[1]))[:5]
    return [{"icon": icons.get(k, "📌"), "label": f"{k} ({len(v)})",
             "items": " · ".join(v[:10])} for k, v in sigs]


# ── News feeds ─────────────────────────────────────────────────────────────────
GNEWS_EN = "https://news.google.com/rss/search?q={}&hl=en-US&gl=US&ceid=US:en"
GNEWS_AR = "https://news.google.com/rss/search?q={}&hl=ar&gl=SA&ceid=SA:ar"


def ar(q):
    # quote_plus encodes spaces as + and Arabic chars as %XX — what Google News expects
    return GNEWS_AR.format(urllib.parse.quote_plus(q))


def en(q):
    return GNEWS_EN.format(q)


# 10 slots reserved for English, 10 for Arabic — 20 items per section
EN_QUOTA = 10
AR_QUOTA = 10

DOMESTIC_EN = [
    en("Saudi+Arabia+when:2d"),
    en("site:arabnews.com+Saudi"),
    "https://www.arabnews.com/rss.xml",
    en("site:saudigazette.com.sa+Saudi"),
]

DOMESTIC_AR = [
    ar("المملكة العربية السعودية"),       # Saudi Arabia
    ar("السعودية اليوم"),                  # Saudi today
    ar("أخبار السعودية"),                  # Saudi news
    "https://www.alarabiya.net/tools/rss/section/saudi-arabia",
    "https://www.spa.gov.sa/rss/latest-news",
    "https://www.okaz.com.sa/rss/",
]

REGIONAL_EN = [
    en("Saudi+Arabia+Middle+East+when:3d"),
    en("site:alarabiya.net+Saudi"),
    "https://english.alarabiya.net/tools/rss/section/middle-east",
    en("site:middleeasteye.net+Saudi"),
]

REGIONAL_AR = [
    ar("السعودية الشرق الأوسط"),          # Saudi Arabia Middle East
    ar("محمد بن سلمان"),                   # MBS
    ar("الخليج العربي السعودية"),          # Gulf + Saudi
    "https://www.alarabiya.net/tools/rss/section/middle-east",
    "https://aawsat.com/feed",
]


def news_tag(text):
    t = text.lower()
    # Arabic: split into exact tokens so "هدف" doesn't fire inside "استهدفت"
    ar_tokens = set(re.split(r'[\s\،,\.؟\?!\-:]+', text))

    checks = [
        # Security FIRST — must outrank sports to catch military/geopolitical stories
        ("security", ["attack","missile","strike","military","security","drone",
                      "iran","tehran","weapon","war","bomb","nuclear","sanction"],
                     ["هجوم","صاروخ","عسكري","أمن","حوثي","دفاع","إيران",
                      "طهران","قواعد","استهداف","ضربة","سلاح","حرب","نووي"]),
        ("sports",   ["football","match","league","cup","club","goal","player",
                      "stadium","transfer","coach","referee"],
                     ["كرة","دوري","مباراة","ملعب","لاعب","بطولة","فريق",
                      "مدرب","تدريب","انتقال"]),
        ("economy",  ["billion","investment","fund","economy","trade","oil",
                      "deal","port","gdp","budget","inflation","revenue"],
                     ["استثمار","اقتصاد","نفط","صندوق","تجارة","ميناء",
                      "مليار","أسهم","ميزانية","إيرادات"]),
        ("education",["school","student","universit","educat","curriculum"],
                     ["مدرسة","طالب","جامعة","تعليم","دراسة","مناهج"]),
        ("tourism",  ["tourism","hotel","visitor","travel","resort","entertain"],
                     ["سياحة","فندق","سفر","زائر","منتجع","ترفيه"]),
        ("culture",  ["art","music","film","heritage","cultur","festival","cinema"],
                     ["فن","موسيقى","فيلم","تراث","مهرجان","ثقافة","سينما"]),
        ("housing",  ["housing","real estate","property","construction","neom"],
                     ["إسكان","عقار","بناء","مسكن","نيوم"]),
    ]

    for tag, en_keys, ar_keys in checks:
        if any(re.search(r'\b' + re.escape(k) + r'\b', t) for k in en_keys):
            return tag
        if any(k in ar_tokens for k in ar_keys):
            return tag
    return "politics"


def parse_feed(url, limit):
    try:
        root = ET.fromstring(get(url, timeout=30))
    except Exception as e:
        print(f"  feed miss: {type(e).__name__} - {str(e)[:60]}", file=sys.stderr)
        return []

    items = []
    for it in root.iter("item"):
        title = unescape((it.findtext("title") or "").strip())
        link  = (it.findtext("link") or "").strip()
        desc  = unescape(re.sub(r"<[^>]+>", " ", it.findtext("description") or "")).strip()
        desc  = re.sub(r"\s{2,}", " ", desc)
        pub   = (it.findtext("pubDate") or "")[5:16].strip()

        src = it.findtext("{http://search.yahoo.com/mrss/}source") or it.findtext("source")
        if not src and " - " in title:
            title, _, src = title.rpartition(" - ")
        src = (src or "News").strip()[:24]

        if not title or not link or len(title) < 5:
            continue
        if any(x["headline"] == title for x in items):
            continue
        items.append({"headline": title,
                      "summary": desc[:260] or title,
                      "source": src, "date": pub or NEWS_DATE,
                      "tag": news_tag(title + " " + desc), "url": link})
        if len(items) >= limit:
            break
    return items


def pull_from(feeds, quota, seen):
    """Collect up to `quota` unique items from a feed list, skipping seen headlines."""
    collected = []
    for url in feeds:
        if len(collected) >= quota:
            break
        for item in parse_feed(url, quota):
            if item["headline"] not in seen:
                seen.add(item["headline"])
                collected.append(item)
                if len(collected) >= quota:
                    break
    return collected


def fetch_news_bilingual(en_feeds, ar_feeds, en_quota, ar_quota, label):
    """
    Pull EN_QUOTA items from English feeds and AR_QUOTA from Arabic feeds.
    If Arabic feeds fall short, backfill from English to hit the total.
    """
    seen = set()
    en_items = pull_from(en_feeds, en_quota, seen)
    ar_items = pull_from(ar_feeds, ar_quota, seen)

    total = en_quota + ar_quota
    shortfall = total - len(en_items) - len(ar_items)
    if shortfall > 0:
        # Arabic feeds came up short — backfill from English
        extra = pull_from(en_feeds, shortfall, seen)
        en_items.extend(extra)

    merged = en_items + ar_items
    print(f"  {label}: {len(en_items)} EN + {len(ar_items)} AR = {len(merged)} items")
    return merged


GOOGLE_TRENDS_SA = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=SA"


def scrape_google_trends_sa():
    """Google Trends Saudi Arabia – stable official RSS. Returns Arabic topics only."""
    results = []
    try:
        root = ET.fromstring(get(GOOGLE_TRENDS_SA, timeout=20))
        for it in root.iter("item"):
            title = unescape((it.findtext("title") or "").strip())
            # grab traffic volume from ht:approx_traffic
            traffic_raw = it.findtext("{https://trends.google.com/trends/trendingsearches/daily}approx_traffic") or "0"
            traffic = int(traffic_raw.replace(",","").replace("+","") or 0)
            if not title or not ARABIC.search(title):
                continue
            if is_spam(title):
                continue
            low = title.lstrip("#").lower()
            if low in TIKTOK_GENERIC:
                continue
            results.append({"text": title, "count": traffic,
                            "cat": categorize(title), "source": "google"})
            if len(results) >= 15:
                break
        print(f"  Google Trends SA: {len(results)} Arabic topics")
    except Exception as e:
        print(f"  Google Trends SA miss: {type(e).__name__}: {str(e)[:70]}", file=sys.stderr)
    return results


# ── Apify ─────────────────────────────────────────────────────────────────────
# Apify scrapes from its own infrastructure, not GitHub's, so TikTok and Google
# do not block it. This is the primary source for both tabs; the hand-pasted
# JSON files and the direct scrapers are fallbacks behind it.
APIFY_API   = "https://api.apify.com/v2"
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
# `or` (not a get() default) — GitHub Actions passes "" for an unset repo var,
# which would otherwise blank the actor id out.
APIFY_TIKTOK_ACTOR = (os.environ.get("APIFY_TIKTOK_ACTOR") or "").strip() \
                     or "khadinakbar~tiktok-trending-hashtags-scraper"
APIFY_GOOGLE_ACTOR = (os.environ.get("APIFY_GOOGLE_ACTOR") or "").strip() \
                     or "scrapesage~google-trends-scraper"
# Reuse a successful Apify run younger than this instead of paying for a new one.
APIFY_MAX_AGE_H = int(os.environ.get("APIFY_MAX_AGE_HOURS", "20"))


def _json_req(url, payload=None, timeout=90):
    body = json.dumps(payload).encode() if payload is not None else None
    hdrs = dict(UA)
    hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdrs,
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore") or "null")


def apify_items(actor, run_input, label):
    """
    Fetch dataset items from `actor` using the account's APIFY_TOKEN.
    Reuses the last successful run while it is younger than APIFY_MAX_AGE_H, so
    three GitHub runs a day cost one Apify run. Falls back to starting a fresh
    synchronous run. Returns raw dataset items, or [].
    """
    if not APIFY_TOKEN:
        print(f"  Apify {label}: APIFY_TOKEN not set — skipping")
        return []
    base = f"{APIFY_API}/acts/{actor}"

    # 1. Is there a recent successful run we can just read for free?
    try:
        last = _json_req(f"{base}/runs/last?status=SUCCEEDED&token={APIFY_TOKEN}", timeout=40)
        fin = ((last or {}).get("data") or {}).get("finishedAt")
        if fin:
            ts = datetime.strptime(fin[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
            if age_h <= APIFY_MAX_AGE_H:
                items = _json_req(
                    f"{base}/runs/last/dataset/items?status=SUCCEEDED&token={APIFY_TOKEN}",
                    timeout=60)
                if items:
                    print(f"  Apify {label}: {len(items)} items from last run "
                          f"({age_h:.1f}h old) — no new run charged")
                    return items
            else:
                print(f"  Apify {label}: last run {age_h:.1f}h old — starting a fresh run")
    except Exception as e:
        print(f"  Apify {label} last-run check: {type(e).__name__}: {str(e)[:70]}", file=sys.stderr)

    # 2. Otherwise run it now and wait (Apify caps run-sync at 300s).
    try:
        items = _json_req(f"{base}/run-sync-get-dataset-items?token={APIFY_TOKEN}",
                          payload=run_input, timeout=300) or []
        print(f"  Apify {label}: {len(items)} items from a fresh run")
        return items
    except Exception as e:
        print(f"  Apify {label} run failed: {type(e).__name__}: {str(e)[:90]}", file=sys.stderr)
        return []


def _pick(item, names, default=""):
    """Read the first present field from `names`, tolerating case/space/underscore."""
    for n in names:
        if n in item and item[n] not in (None, ""):
            return item[n]
    low = {str(k).lower().replace(" ", "").replace("_", "").replace("#", ""): v
           for k, v in item.items()}
    for n in names:
        k = n.lower().replace(" ", "").replace("_", "").replace("#", "")
        if k in low and low[k] not in (None, ""):
            return low[k]
    return default


def _humanize(v):
    """1234567 -> '1.2M'. Passes through strings already formatted that way."""
    if isinstance(v, str):
        s = v.strip()
        if re.match(r"^[\d.,]+\s*[KMB]", s, re.I):
            return s.replace(" ", "").upper()
        try:
            v = float(s.replace(",", "").replace("+", ""))
        except ValueError:
            return s
    try:
        n = float(v)
    except (TypeError, ValueError):
        return ""
    if n <= 0:   return ""
    if n >= 1e9: return f"{n/1e9:.1f}B".replace(".0B", "B")
    if n >= 1e6: return f"{n/1e6:.1f}M".replace(".0M", "M")
    if n >= 1e3: return f"{n/1e3:.1f}K".replace(".0K", "K")
    return str(int(n))


def _to_int(v):
    """'100K+' -> 100000, '1.2M' -> 1200000, 50000 -> 50000, junk -> 0."""
    if isinstance(v, (int, float)):
        return int(v)
    mt = re.match(r"\s*([\d][\d.,]*)\s*([KMB])?", str(v), re.I)
    if not mt:
        return 0
    try:
        n = float(mt.group(1).replace(",", ""))
    except ValueError:
        return 0
    unit = (mt.group(2) or "").upper()
    return int(n * {"K": 1e3, "M": 1e6, "B": 1e9}.get(unit, 1))


def fetch_apify_tiktok():
    """Saudi TikTok trending hashtags via Apify (real Creative Center data)."""
    raw = apify_items(APIFY_TIKTOK_ACTOR,
                      {"country": "SA", "timePeriod": "7",
                       "industry": "All Industries", "maxResults": 20},
                      "TikTok")
    items = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        name = str(_pick(it, ["hashtag_name", "hashtag", "name", "title", "text"])).strip()
        if not name:
            continue
        if not name.startswith("#"):
            name = "#" + name
        bare = name.lstrip("#")
        if is_spam(bare) or bare.lower() in TIKTOK_GENERIC:
            continue
        if any(x["text"] == name for x in items):
            continue
        items.append({
            "rank":   len(items) + 1,
            "text":   name,
            "posts":  _humanize(_pick(it, ["post_count", "publish_cnt", "posts",
                                           "postCount", "videoCount"], 0)),
            "views":  _humanize(_pick(it, ["video_views", "views", "viewCount",
                                           "view_count"], 0)),
            "trend":  "rising",
            "cat":    categorize(name),
            "source": "cc",
        })
        if len(items) >= 20:
            break
    return items


def fetch_apify_google():
    """Saudi Google trending searches via Apify."""
    raw = apify_items(APIFY_GOOGLE_ACTOR,
                      {"what_to_scrape": "trending", "location": "SA"},
                      "Google")
    items = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        term = str(_pick(it, ["Trending search", "trendingSearch", "title",
                              "query", "term", "keyword"])).strip()
        if not term or is_spam(term):
            continue
        if term.lstrip("#").lower() in TIKTOK_GENERIC:
            continue
        if any(x["text"] == term for x in items):
            continue
        traffic = _pick(it, ["Traffic #", "trafficNumber", "Traffic", "traffic",
                             "formattedTraffic", "searchVolume"], 0)
        cnt = _to_int(traffic)
        items.append({"text": term, "count": cnt,
                      "cat": categorize(term), "source": "google"})
        if len(items) >= 20:
            break
    return items


def read_manual_json(path, label, max_age_days=30):
    """
    Generic reader for a hand-pasted data file: {"date": "11 Sep 2026", "items": [...]}.
    Returns the dict (with stale_days attached) or None if missing / empty / too old.
    Used for google_manual.json — and the same shape tiktok_cc.json uses.
    """
    if not os.path.exists(path):
        print(f"  {path} not found — using auto-fallback")
        return None
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        date_str = obj.get("date", "")
        if not date_str:
            return None
        d = datetime.strptime(date_str, "%d %b %Y").replace(tzinfo=RIYADH)
        age_days = (NOW - d).days
        if age_days > max_age_days:
            print(f"  {path} is {age_days}d old — too stale (>{max_age_days}d), using auto-fallback")
            return None
        items = obj.get("items") or []
        if not items:
            return None
        note = f" ⚠ {age_days}d old — refresh {path}" if age_days > 7 else ""
        print(f"  {path}: {len(items)} items (age {age_days}d) — manual {label} data live{note}")
        obj["stale_days"] = age_days if age_days > 7 else 0
        return obj
    except Exception as e:
        print(f"  {path} error: {type(e).__name__}: {str(e)[:70]}", file=sys.stderr)
        return None


def read_tiktok_cc_json():
    """
    Read tiktok_cc.json if it exists and is ≤30 days old.
    Returns the full dict {date, items, stale_days} or None to trigger fallback.
    The user pastes this file to GitHub after each Creative Center extraction.
    Real CC data — even if a few weeks old — is far better than the X-trends fallback.
    """
    CC_PATH = "tiktok_cc.json"
    if not os.path.exists(CC_PATH):
        print("  tiktok_cc.json not found — using auto-fallback")
        return None
    try:
        with open(CC_PATH, encoding="utf-8") as f:
            cc = json.load(f)
        date_str = cc.get("date", "")
        if not date_str:
            return None
        cc_date = datetime.strptime(date_str, "%d %b %Y").replace(tzinfo=RIYADH)
        age_days = (NOW - cc_date).days
        if age_days > 30:
            print(f"  tiktok_cc.json is {age_days}d old — too stale (>30d), using auto-fallback")
            return None
        items = cc.get("items") or []
        if not items:
            return None
        stale_note = f" ⚠ {age_days}d old — update tiktok_cc.json" if age_days > 7 else ""
        print(f"  tiktok_cc.json: {len(items)} items (age {age_days}d) — CC data live{stale_note}")
        # Attach stale_days so the frontend can show a freshness warning
        cc["stale_days"] = age_days if age_days > 7 else 0
        return cc
    except Exception as e:
        print(f"  tiktok_cc.json error: {type(e).__name__}: {str(e)[:70]}", file=sys.stderr)
        return None


def fetch_google_trends_tab():
    """
    Fetch Saudi Google Trends for the standalone Google Trends tab.
    Source 1: Google Trends daily JSON API (most reliable, no auth needed)
    Source 2: pytrends (requires: pip install pytrends --break-system-packages in Actions)
    Source 3: Google Trends daily RSS fallback
    Returns list of {text, count, cat, source} — both Arabic and English topics.
    """
    results = []

    # ── Source 1: Google Trends daily JSON API ────────────────────────────────
    try:
        import json as _json
        url = "https://trends.google.com/trending/api/dailytrends?hl=en-US&geo=SA&ns=15"
        raw = get(url, timeout=20)
        # Response starts with ")]}'\n" — strip it
        clean = raw.lstrip(")]}'\n").strip()
        obj = _json.loads(clean)
        topics = (obj.get("trendingSearchesDays") or [])
        for day in topics[:2]:
            for ts in (day.get("trendingSearches") or []):
                title = (ts.get("title") or {}).get("query", "").strip()
                traffic_raw = (ts.get("formattedTraffic") or "0").replace("+", "").replace("K", "000").replace("M", "000000").replace(",", "")
                try:
                    traffic = int(float(traffic_raw))
                except (ValueError, TypeError):
                    traffic = 0
                if not title or is_spam(title):
                    continue
                if title.lstrip("#").lower() in TIKTOK_GENERIC:
                    continue
                if any(r["text"] == title for r in results):
                    continue
                results.append({"text": title, "count": traffic,
                                "cat": categorize(title), "source": "google"})
                if len(results) >= 25:
                    break
            if len(results) >= 25:
                break
        print(f"  Google Trends JSON API: {len(results)} topics")
    except Exception as e:
        print(f"  Google Trends JSON API miss: {type(e).__name__}: {str(e)[:70]}", file=sys.stderr)

    # ── Source 2: pytrends ────────────────────────────────────────────────────
    if HAS_PYTRENDS and len(results) < 5:
        try:
            pt = _TrendReq(hl="ar", tz=180, timeout=(10, 30), retries=2, backoff_factor=0.5)
            df = pt.trending_searches(pn="saudi_arabia")
            for term in df[0].tolist()[:25]:
                term = str(term).strip()
                if not term or is_spam(term):
                    continue
                results.append({"text": term, "count": 0,
                                "cat": categorize(term), "source": "google"})
            print(f"  Google Trends (pytrends): {len(results)} topics")
        except Exception as e:
            print(f"  pytrends miss: {type(e).__name__}: {str(e)[:70]}", file=sys.stderr)

    # ── Source 3: Google Trends RSS ───────────────────────────────────────────
    if len(results) < 5:
        try:
            root = ET.fromstring(get(GOOGLE_TRENDS_SA, timeout=20))
            for it in root.iter("item"):
                title = unescape((it.findtext("title") or "").strip())
                traffic_raw = (
                    it.findtext("{https://trends.google.com/trends/trendingsearches/daily}approx_traffic")
                    or "0"
                )
                traffic = int(traffic_raw.replace(",", "").replace("+", "") or 0)
                if not title or is_spam(title):
                    continue
                low = title.lstrip("#").lower()
                if low in TIKTOK_GENERIC:
                    continue
                # avoid duplicates from pytrends
                if any(r["text"] == title for r in results):
                    continue
                results.append({"text": title, "count": traffic,
                                "cat": categorize(title), "source": "google"})
                if len(results) >= 25:
                    break
            print(f"  Google Trends RSS: {len(results)} topics total")
        except Exception as e:
            print(f"  Google Trends RSS miss: {type(e).__name__}: {str(e)[:70]}", file=sys.stderr)

    # ── Source 4: Google News "top stories in Saudi Arabia" ───────────────────
    # trends.google.com blocks datacenter IPs (GitHub Actions), but news.google.com
    # does NOT — the News tab proves it works. So when all three trend sources are
    # blocked, fall back to what Saudi Google News is surfacing, rather than an
    # empty tab. Marked source="gnews" so the UI can label it honestly.
    if len(results) < 5:
        try:
            url = "https://news.google.com/rss/headlines/section/geo/Saudi%20Arabia?hl=ar&gl=SA&ceid=SA:ar"
            root = ET.fromstring(get(url, timeout=25))
            for it in root.iter("item"):
                title = unescape((it.findtext("title") or "").strip())
                # Google News titles end in " - Publisher"; keep only the topic
                topic = title.rsplit(" - ", 1)[0].strip()
                if not topic or is_spam(topic):
                    continue
                if topic.lstrip("#").lower() in TIKTOK_GENERIC:
                    continue
                if any(r["text"] == topic for r in results):
                    continue
                results.append({"text": topic, "count": 0,
                                "cat": categorize(topic), "source": "gnews"})
                if len(results) >= 20:
                    break
            print(f"  Google News SA fallback: {len(results)} topics total")
        except Exception as e:
            print(f"  Google News SA miss: {type(e).__name__}: {str(e)[:70]}", file=sys.stderr)

    return results[:20]


def scrape_tiktok_sa(x_trends):
    """
    Saudi social-media trending topics for the TikTok tab.
    Source priority:
      1. TikTok Ads Creative Center (real TikTok data, undocumented – may break)
      2. Google Trends Saudi Arabia RSS (official, very stable, Arabic-first)
      3. Arabic-script X trends (already scraped, zero extra cost)
    Quality gates: Arabic script required, TIKTOK_GENERIC blocklist, no spam.
    """
    results = []

    # ── Source 1: TikTok Creative Center ──────────────────────────────────────
    try:
        url = ("https://ads.tiktok.com/creative_radar_api/v1/popular_trend/hashtag/list"
               "?page=1&limit=50&period=7&country_code=SA&sort_by=popular")
        raw = json.loads(get(url, timeout=25))
        lst = (raw.get("data") or {}).get("list") or []
        for item in lst:
            tag = (item.get("hashtag_name") or "").strip()
            cnt = item.get("publish_cnt") or 0
            if not tag:
                continue
            tag_norm = "#" + tag if not tag.startswith("#") else tag
            low = tag_norm.lstrip("#").lower()
            if low in TIKTOK_GENERIC or cnt < 200:
                continue
            if not ARABIC.search(tag_norm) or is_spam(tag_norm):
                continue
            results.append({"text": tag_norm, "count": cnt,
                            "cat": categorize(tag_norm), "source": "cc"})
        print(f"  TikTok CC: {len(results)} SA Arabic trends")
    except Exception as e:
        print(f"  TikTok CC miss: {type(e).__name__}: {str(e)[:70]}", file=sys.stderr)

    # ── Source 2: Google Trends SA (stable fallback) ───────────────────────────
    if len(results) < 6:
        seen = {r["text"] for r in results}
        for item in scrape_google_trends_sa():
            if item["text"] not in seen:
                seen.add(item["text"])
                item["source"] = "google"
                results.append(item)

    # ── Source 3: Arabic X-trends cross-reference ──────────────────────────────
    if len(results) < 8:
        seen = {r["text"] for r in results}
        for t in x_trends:
            if not ARABIC.search(t):
                continue
            if t.lstrip("#").lower() in TIKTOK_GENERIC:
                continue
            if t not in seen:
                seen.add(t)
                results.append({"text": t, "count": 0,
                                "cat": categorize(t), "source": "x"})
        print(f"  TikTok: X Arabic supplement applied ({len(results)} total)")

    return results[:15]


def main():
    data = json.load(open("data.json", encoding="utf-8"))
    days, cumul = data["days"], data["cumul"]

    trends, tags = scrape_trends()
    print(f"Parsed {len(trends)} trends, {len(tags)} hashtags")

    scored, streaks = score(trends, days)
    days[DAY_KEY] = {"label": DAY_LABEL, "trends": scored,
                     "hashtags": tags or days[max(days)]["hashtags"],
                     "signals": build_signals(trends)}

    cumul.clear()
    for dk in sorted(days):
        for t in days[dk]["trends"]:
            cumul[t["text"]] = cumul.get(t["text"], 0) + t["pts"]

    for old in sorted(days)[:-14]:
        del days[old]

    # TikTok source order:
    #   1. Apify (runs on Apify's infrastructure — TikTok doesn't block it)
    #   2. tiktok_cc.json, hand-pasted from Creative Center
    #   3. the direct scraper (usually blocked from GitHub Actions)
    tiktok_items = fetch_apify_tiktok()
    if tiktok_items:
        data["tiktok"] = {"date": NEWS_DATE, "items": tiktok_items}
    else:
        cc_data = read_tiktok_cc_json()
        if cc_data:
            data["tiktok"] = cc_data
        else:
            raw_x = [t["text"] for t in scored]
            scraped = scrape_tiktok_sa(raw_x)
            if scraped:
                data["tiktok"] = {"date": NEWS_DATE, "items": scraped}
            elif "tiktok" not in data:
                data["tiktok"] = {"date": NEWS_DATE, "items": []}

    # Google source order: Apify → hand-pasted google_manual.json → direct scrape
    google_items = fetch_apify_google()
    if google_items:
        data["google"] = {"date": NEWS_DATE, "items": google_items}
    else:
        gm_data = read_manual_json("google_manual.json", "google")
        if gm_data:
            data["google"] = gm_data
        else:
            scraped = fetch_google_trends_tab()
            if scraped:
                data["google"] = {"date": NEWS_DATE, "items": scraped}
            elif "google" not in data:
                data["google"] = {"date": NEWS_DATE, "items": []}

    dom = fetch_news_bilingual(DOMESTIC_EN, DOMESTIC_AR, EN_QUOTA, AR_QUOTA, "domestic")
    reg = fetch_news_bilingual(REGIONAL_EN, REGIONAL_AR, EN_QUOTA, AR_QUOTA, "regional")
    reg = [r for r in reg if not any(d["headline"] == r["headline"] for d in dom)]

    if len(dom) >= 5 and len(reg) >= 5:
        for i, n in enumerate(dom, 1):
            n["rank"] = i
        for i, n in enumerate(reg, 21):
            n["rank"] = i
        data["news"] = {"date": NEWS_DATE, "domestic": dom, "regional": reg}
        print(f"News refreshed: {len(dom)} domestic + {len(reg)} regional")
    else:
        print(f"News feeds unavailable - kept stories from {data['news']['date']}",
              file=sys.stderr)

    data["lastUpdated"] = BANNER
    json.dump(data, open("data.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"\nUpdated {DAY_KEY} ({DAY_LABEL})")
    print("Top 3: " + " | ".join(f"{t['text']} ({t['pts']}pts)" for t in scored[:3]))
    print("STREAK BONUS: " + ", ".join(f"{t} ({r}d)" for t, r in streaks)
          if streaks else "No streak bonuses today")


if __name__ == "__main__":
    main()
