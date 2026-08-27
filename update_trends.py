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
    ("Culture / Society", ["خواطر","رمضان","العيد","فن","حفل","مهرجان"]),
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


def read_tiktok_cc_json():
    """
    Read tiktok_cc.json if it exists and is ≤7 days old.
    Returns the full dict {date, items} or None to trigger fallback.
    The user pastes this file to GitHub after each Creative Center extraction.
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
        if age_days > 7:
            print(f"  tiktok_cc.json is {age_days}d old — stale, using auto-fallback")
            return None
        items = cc.get("items") or []
        if not items:
            return None
        print(f"  tiktok_cc.json: {len(items)} items (age {age_days}d) — CC data live")
        return cc
    except Exception as e:
        print(f"  tiktok_cc.json error: {type(e).__name__}: {str(e)[:70]}", file=sys.stderr)
        return None


def fetch_google_trends_tab():
    """
    Fetch Saudi Google Trends for the standalone Google Trends tab.
    Source 1: pytrends (requires: pip install pytrends --break-system-packages in Actions)
    Source 2: Google Trends daily RSS fallback
    Returns list of {text, count, cat, source} — both Arabic and English topics.
    """
    results = []

    # ── Source 1: pytrends ────────────────────────────────────────────────────
    if HAS_PYTRENDS:
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

    # ── Source 2: Google Trends RSS ───────────────────────────────────────────
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

    # TikTok: prefer fresh Creative Center data from tiktok_cc.json (user-pasted)
    # If that file is missing or >7 days old, fall back to the 3-source auto-scraper
    cc_data = read_tiktok_cc_json()
    if cc_data:
        data["tiktok"] = cc_data
    else:
        raw_x = [t["text"] for t in scored]
        tiktok_items = scrape_tiktok_sa(raw_x)
        if tiktok_items:
            data["tiktok"] = {"date": NEWS_DATE, "items": tiktok_items}
        elif "tiktok" not in data:
            data["tiktok"] = {"date": NEWS_DATE, "items": []}

    # Google Trends tab (separate from TikTok fallback)
    google_items = fetch_google_trends_tab()
    if google_items:
        data["google"] = {"date": NEWS_DATE, "items": google_items}
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
