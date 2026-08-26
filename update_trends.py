#!/usr/bin/env python3
"""
Daily updater for the Kijamii Saudi Radar.
Runs inside GitHub Actions. Rewrites data.json in place.

Fails LOUDLY (non-zero exit) rather than publishing garbage — if a source
changes its markup, the Action goes red and emails you instead of silently
shipping an empty tracker.
"""
import json, re, sys, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html import unescape

RIYADH = timezone(timedelta(hours=3))
NOW = datetime.now(RIYADH)
DAY_KEY = NOW.strftime("%Y-%m-%d")
DAY_LABEL = NOW.strftime("%a %d %b")
BANNER = NOW.strftime("%A, %d %B %Y")
NEWS_DATE = NOW.strftime("%d %b %Y")

UA = {"User-Agent": "Mozilla/5.0 (compatible; KijamiiRadar/1.0)"}
RANK_BONUS = {1: 10, 2: 8, 3: 6, 4: 4, 5: 3}
STREAK_DAYS = 3
STREAK_BONUS = 5

# Spam filters: mixed Cyrillic, phone numbers, paid-trend markers
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
PHONE = re.compile(r"\d{7,}")

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
    if CYRILLIC.search(t) and re.search(r"[؀-ۿ]", t):
        return True
    if PHONE.search(t):
        return True
    if len(t) < 2 or len(t) > 60:
        return True
    return False


def scrape_trends():
    """Return (trends[list of str], hashtags[list of (str,int)])."""
    html = get("https://getdaytrends.com/saudi-arabia/")

    # Trend links look like /saudi-arabia/trend/<name>/ — capture anchor text.
    raw = re.findall(
        r'<a[^>]+href="/[a-z\-]+/trend/[^"]*"[^>]*>(.*?)</a>', html, re.S | re.I)
    trends, seen = [], set()
    for r in raw:
        t = unescape(re.sub(r"<[^>]+>", "", r)).strip()
        if not t or t in seen or is_spam(t):
            continue
        seen.add(t)
        trends.append(t)

    # Hashtag table rows: hashtag anchor followed by a numeric cell.
    tags = []
    for m in re.finditer(
            r'<a[^>]+href="/[a-z\-]+/trend/[^"]*"[^>]*>(#[^<]{2,60})</a>.*?'
            r'<td[^>]*>\s*([\d,]+)\s*</td>', html, re.S | re.I):
        txt = unescape(m.group(1)).strip()
        score = int(m.group(2).replace(",", ""))
        if not is_spam(txt):
            tags.append({"text": txt, "score": score})
        if len(tags) >= 5:
            break

    if len(trends) < 10:
        # Self-diagnosing failure: dump anchor samples into the Actions log so
        # the selector can be fixed without guesswork.
        print("=== PARSE FAILED — anchor sample for debugging ===", file=sys.stderr)
        for a in re.findall(r"<a[^>]+href=\"[^\"]*trend[^\"]*\"[^>]*>.{0,80}", html,
                            re.S | re.I)[:15]:
            print("  " + a.replace("\n", " "), file=sys.stderr)
        print(f"=== html length: {len(html)} ===", file=sys.stderr)
        sys.exit(f"FAIL: only {len(trends)} trends parsed — markup likely changed.")
    return trends[:20], tags


def score(trends, prev_days):
    """+4 per appearance, rank bonus, +5 if 3+ consecutive days."""
    # Prior days only — exclude today, since we may run several times a day
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


def rss(url, source, limit):
    """Parse an RSS feed into news items. Returns [] on any failure."""
    try:
        root = ET.fromstring(get(url, timeout=30))
    except Exception as e:
        print(f"  RSS warn ({source}): {e}", file=sys.stderr)
        return []
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        desc = re.sub(r"<[^>]+>", "", it.findtext("description") or "").strip()
        pub = (it.findtext("pubDate") or "")[:16]
        if not title or not link:
            continue
        items.append({"headline": unescape(title),
                      "summary": unescape(desc)[:280] or unescape(title),
                      "source": source, "date": pub or NEWS_DATE,
                      "tag": news_tag(title + " " + desc), "url": link})
        if len(items) >= limit:
            break
    return items


def news_tag(text):
    t = text.lower()
    for tag, keys in [("sports", ["football","match","league","cup","club"]),
                      ("economy", ["billion","investment","fund","economy","trade","oil","deal","port"]),
                      ("security", ["attack","missile","strike","military","security","drone"]),
                      ("education", ["school","student","universit","educat"]),
                      ("tourism", ["tourism","hotel","visitor","travel","resort"]),
                      ("culture", ["art","music","film","heritage","cultur","festival"]),
                      ("housing", ["housing","real estate","property","construction"])]:
        if any(k in t for k in keys):
            return tag
    return "politics"


def main():
    data = json.load(open("data.json", encoding="utf-8"))
    days, cumul = data["days"], data["cumul"]

    trends, tags = scrape_trends()
    print(f"Parsed {len(trends)} trends, {len(tags)} hashtags")

    scored, streaks = score(trends, days)

    days[DAY_KEY] = {"label": DAY_LABEL, "trends": scored,
                     "hashtags": tags or days[max(days)]["hashtags"],
                     "signals": build_signals(trends)}

    # Rebuild cumulative totals from the full archive rather than incrementing.
    # This is idempotent — safe to run many times per day without double-counting.
    cumul.clear()
    for dk in sorted(days):
        for t in days[dk]["trends"]:
            cumul[t["text"]] = cumul.get(t["text"], 0) + t["pts"]

    # Keep the archive to the last 14 days so the page stays fast
    for old in sorted(days)[:-14]:
        del days[old]

    # News via RSS — keep yesterday's if a feed is down
    dom = rss("https://www.arabnews.com/cat/1/rss.xml", "Arab News", 10)
    reg = rss("https://english.alarabiya.net/tools/rss/section/middle-east", "Al Arabiya", 10)
    if len(dom) >= 5 and len(reg) >= 5:
        for i, n in enumerate(dom, 1):
            n["rank"] = i
        for i, n in enumerate(reg, 11):
            n["rank"] = i
        data["news"] = {"date": NEWS_DATE, "domestic": dom, "regional": reg}
        print(f"News refreshed: {len(dom)} domestic + {len(reg)} regional")
    else:
        data["news"]["date"] = NEWS_DATE
        print("News feeds thin — retained previous stories", file=sys.stderr)

    data["lastUpdated"] = BANNER
    json.dump(data, open("data.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"\nUpdated {DAY_KEY} ({DAY_LABEL})")
    print("Top 3: " + " | ".join(f"{t['text']} ({t['pts']}pts)" for t in scored[:3]))
    if streaks:
        print("STREAK BONUS: " + ", ".join(f"{t} ({r}d)" for t, r in streaks))
    else:
        print("No streak bonuses today")


if __name__ == "__main__":
    main()
