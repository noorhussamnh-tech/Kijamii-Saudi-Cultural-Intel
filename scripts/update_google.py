import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

DATA_JSON_PATH = Path("data.json")

RSS_URLS = [
    "https://trends.google.com/trending/rss?geo=SA&hl=ar",
    "https://trends.google.com/trending/rss?geo=SA",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
}

CATEGORY_RULES = [
    (r"\b(vs|ضد|مباراة|دوري|كأس|فريق|نادي|لاعب|هدف|goal|league|cup|match|fc|sport|football|soccer|basketball|tennis|f1|formula|أولمبي|بطولة)\b", "Sports"),
    (r"(وزارة|وزير|حكومة|رسمي|هيئة|مجلس|ministry|government|official|authority)", "Government"),
    (r"(مسلسل|فيلم|برنامج|ممثل|ممثلة|مطرب|مغني|movie|series|actor|actress|singer|celebrity|أغنية|حفلة|عرض)", "Entertainment"),
    (r"(جزيرة|سياحة|منتجع|رحلة|فندق|island|resort|travel|tourism|hotel|beach|شاطئ)", "Travel / Culture"),
    (r"(طقس|أمطار|weather|حرارة|درجة|forecast|مناخ)", "Weather"),
    (r"(مرض|صحة|علاج|دواء|فيروس|وباء|health|disease|medicine|treatment|hospital|مستشفى)", "Health"),
    (r"(دولار|ريال|سهم|بورصة|اقتصاد|تضخم|dollar|stock|economy|finance|inflation|bank|بنك)", "Finance"),
    (r"(حرب|صراع|أزمة|قضية|war|conflict|crisis|politics|election|سياسة|انتخاب)", "News"),
    (r"(رمضان|عيد|حج|صلاة|ديني|islamic|muslim|quran|prayer|religion)", "Religion / Culture"),
    (r"(تقنية|تطبيق|ذكاء|هاتف|tech|app|ai|phone|iphone|android|software)", "Technology"),
]

COMPILED_RULES = [(re.compile(p, re.IGNORECASE), cat) for p, cat in CATEGORY_RULES]


def detect_category(term, news_headline=""):
    text = f"{term} {news_headline}"
    for pattern, cat in COMPILED_RULES:
        if pattern.search(text):
            return cat
    return "General"


def parse_traffic(raw):
    if not raw:
        return 0
    raw = raw.replace(",", "").replace("+", "").strip()
    if raw.upper().endswith("M"):
        return int(float(raw[:-1]) * 1_000_000)
    if raw.upper().endswith("K"):
        return int(float(raw[:-1]) * 1_000)
    try:
        return int(raw)
    except ValueError:
        return 0


def fetch_rss():
    ns = {"ht": "https://trends.google.com/trends/trendingearches/daily"}
    items = []
    for url in RSS_URLS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  RSS fetch failed for {url}: {e}", flush=True)
            continue

        try:
            root = ET.fromstring(resp.text.encode("utf-8"))
        except ET.ParseError as e:
            print(f"  XML parse error: {e}", flush=True)
            continue

        channel = root.find("channel")
        raw_items = channel.findall("item") if channel is not None else root.findall(".//item")

        if not raw_items:
            print(f"  No items in feed from {url}", flush=True)
            continue

        print(f"  RSS from {url}: {len(raw_items)} items", flush=True)

        for entry in raw_items:
            title_el = entry.find("title")
            traffic_el = None
            for child in entry:
                if "approx_traffic" in child.tag:
                    traffic_el = child
                    break

            news_title = ""
            for child in entry:
                if "news_item_title" in child.tag:
                    news_title = child.text or ""
                    break

            term = title_el.text.strip() if title_el is not None and title_el.text else ""
            count = parse_traffic(traffic_el.text.strip() if traffic_el is not None and traffic_el.text else "")

            if term:
                items.append({"text": term, "count": count, "cat": detect_category(term, news_title)})

        if items:
            break

    return items


def main():
    if not DATA_JSON_PATH.exists():
        print(f"ERROR: {DATA_JSON_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    print("Fetching Google Trends RSS — Saudi Arabia...", flush=True)
    items = fetch_rss()
    print(f"Fetched {len(items)} items.", flush=True)

    if not items:
        print("No items — data.json NOT modified.", flush=True)
        sys.exit(1)

    raw = DATA_JSON_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    today = datetime.now(timezone.utc).strftime("%a %d %b %Y")
    data["google"] = {"date": today, "items": items}
    DATA_JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  data.json updated — {len(items)} Google items, date: {today}", flush=True)


if __name__ == "__main__":
    main()
