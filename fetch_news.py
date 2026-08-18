#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
5대 리그(EPL, LaLiga, Bundesliga, Serie A, Ligue 1) 당일 축구 뉴스 수집기
- 공식/공신력 있는 언론·리그 RSS 피드를 수집해 리그별로 분류
- 리그별 지정 기자(메인/보강)의 바이라인이 확인되면 우선 태그 및 상단 노출
- 라리가는 레알 마드리드 관련 기사를 1순위로 정렬
- 산출물: data.json (웹 대시보드가 읽어서 렌더링)

사용법: python3 fetch_news.py
매일 자동 실행하려면 cron 또는 GitHub Actions 스케줄러에 등록하세요.
"""
import feedparser
import json
import re
import time
from datetime import datetime, timezone, timedelta
from html import unescape

# ---- 수집 소스: 공식 리그/구단 + 공신력 있는 언론사 RSS ----
SOURCES = [
    # 종합/공신력 언론 (전 리그 커버)
    {"name": "BBC Sport", "url": "http://feeds.bbci.co.uk/sport/football/rss.xml", "trust": "언론"},
    {"name": "Sky Sports", "url": "https://www.skysports.com/rss/12040", "trust": "언론"},
    {"name": "ESPN FC", "url": "https://www.espn.com/espn/rss/soccer/news", "trust": "언론"},
    {"name": "Guardian Football", "url": "https://www.theguardian.com/football/rss", "trust": "언론"},
    # 스페인 (라리가) - Sid Lowe(가디언/디애슬레틱), Dermot Corrigan, Guillem Balague 활동 매체
    {"name": "Marca", "url": "https://e00-marca.uecdn.es/rss/futbol/primera-division.xml", "trust": "언론"},
    {"name": "AS", "url": "https://as.com/rss/futbol/primera.xml", "trust": "언론"},
    {"name": "Real Madrid 공식", "url": "https://www.realmadrid.com/en-US/rss/rmtv-news", "trust": "공식"},
    # 이탈리아 (세리에A) - Paolo Bandini(가디언), Fabrizio Romano, Matteo Bonetti 활동 매체
    {"name": "Gazzetta dello Sport", "url": "https://www.gazzetta.it/rss/calcio.xml", "trust": "언론"},
    {"name": "Football Italia", "url": "https://www.football-italia.net/rss.xml", "trust": "언론"},
    {"name": "CaughtOffside (Romano)", "url": "https://www.caughtoffside.com/feed/", "trust": "기자"},
    # 프랑스 (리그앙) - Jonathan Johnson(ESPN), Julien Laurens(ESPN/르키프), Tom Williams(GFFN)
    {"name": "L'Équipe Football", "url": "https://dwh.lequipe.fr/api/edito/rss?path=/Football", "trust": "언론"},
    {"name": "Get French Football News", "url": "https://www.getfrenchfootballnews.com/feed/", "trust": "기자"},
    # 독일 (분데스리가) - Raphael Honigstein(디애슬레틱/ESPN), Jonathan Harding, Nick Ames(가디언)
    {"name": "Kicker Bundesliga", "url": "https://newsfeed.kicker.de/news/bundesliga", "trust": "언론"},
    {"name": "Bundesliga 공식", "url": "https://www.bundesliga.com/en/bundesliga/news/rss", "trust": "공식"},
]

LEAGUE_KEYWORDS = {
    "EPL": ["premier league", "epl", "arsenal", "man city", "manchester city", "man utd", "manchester united",
            "liverpool", "chelsea", "tottenham", "newcastle", "aston villa", "west ham", "everton",
            "brighton", "wolves", "fulham", "brentford", "crystal palace", "nottingham forest",
            "coventry", "leeds", "sunderland", "burnley", "bournemouth"],
    "LaLiga": ["la liga", "laliga", "real madrid", "barcelona", "atletico madrid", "atlético",
               "sevilla", "villarreal", "real sociedad", "athletic bilbao", "real betis",
               "valencia", "girona", "osasuna", "deportivo", "elche", "mallorca", "celta"],
    "Bundesliga": ["bundesliga", "bayern", "borussia dortmund", "rb leipzig", "bayer leverkusen",
                   "eintracht frankfurt", "vfb stuttgart", "wolfsburg", "borussia mönchengladbach",
                   "union berlin", "freiburg", "mainz", "hoffenheim", "werder bremen", "augsburg", "koln"],
    "SerieA": ["serie a", "juventus", "inter milan", "ac milan", "napoli", "roma", "lazio",
               "atalanta", "fiorentina", "bologna", "torino", "udinese", "sassuolo", "cagliari",
               "genoa", "parma", "hellas verona", "como", "cremonese"],
    "Ligue1": ["ligue 1", "psg", "paris saint-germain", "marseille", "monaco", "lyon", "lille",
               "lens", "rennes", "nice", "nantes", "strasbourg", "toulouse", "montpellier",
               "reims", "brest", "le havre", "angers", "auxerre"],
}

# 리그별 지정 기자 (메인/보강) - 바이라인/본문에서 이름이 확인되면 우선 태그
LEAGUE_REPORTERS = {
    "EPL": {"main": ["David Ornstein"], "support": ["Kaveh Solhekol", "Phil McNulty"]},
    "LaLiga": {"main": ["Sid Lowe"], "support": ["Dermot Corrigan", "Guillem Balague", "Guillem Balagué"]},
    "SerieA": {"main": ["Paolo Bandini"], "support": ["Fabrizio Romano", "Matteo Bonetti"]},
    "Bundesliga": {"main": ["Raphael Honigstein"], "support": ["Jonathan Harding", "Nick Ames"]},
    "Ligue1": {"main": ["Jonathan Johnson"], "support": ["Julien Laurens", "Tom Williams"]},
}

REAL_MADRID_KEYWORDS = ["real madrid", "레알 마드리드", "bernabeu", "bernabéu"]

def classify_league(title, summary):
    text = f"{title} {summary}".lower()
    scores = {lg: 0 for lg in LEAGUE_KEYWORDS}
    for lg, kws in LEAGUE_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                scores[lg] += 1
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return None
    return best

def detect_reporter(league, text_blob):
    """바이라인/본문에서 지정 기자 이름이 확인되면 (이름, 등급) 반환"""
    reps = LEAGUE_REPORTERS.get(league, {})
    low = text_blob.lower()
    for name in reps.get("main", []):
        if name.lower() in low:
            return name, "메인 기자"
    for name in reps.get("support", []):
        if name.lower() in low:
            return name, "보강 기자"
    return None, None

def is_real_madrid(text):
    low = text.lower()
    return any(kw in low for kw in REAL_MADRID_KEYWORDS)

def clean(text):
    text = unescape(text or "")
    text = re.sub("<[^<]+?>", "", text)
    return text.strip()

def parse_time(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
    return None

def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=48)  # 최근 48시간 이내 뉴스만 (당일+전일 보정)
    items = {lg: [] for lg in LEAGUE_KEYWORDS}
    errors = []

    for src in SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            for entry in feed.entries[:60]:
                title = clean(entry.get("title", ""))
                summary = clean(entry.get("summary", entry.get("description", "")))
                author = clean(entry.get("author", entry.get("dc_creator", "")))
                link = entry.get("link", "")
                pub = parse_time(entry)
                if pub and pub < cutoff:
                    continue
                league = classify_league(title, summary)
                if not league:
                    continue
                blob = f"{author} {title} {summary}"
                reporter, reporter_tier = detect_reporter(league, blob)
                item = {
                    "title": title,
                    "summary": summary[:220],
                    "link": link,
                    "source": src["name"],
                    "trust": src["trust"],
                    "published": pub.isoformat() if pub else None,
                    "reporter": reporter,
                    "reporter_tier": reporter_tier,
                    "real_madrid": is_real_madrid(f"{title} {summary}") if league == "LaLiga" else False,
                }
                items[league].append(item)
        except Exception as e:
            errors.append(f"{src['name']}: {e}")

    # 리그별 중복 제거(제목 기준) + 정렬
    # 정렬 우선순위: (1) 레알 마드리드(라리가 한정) (2) 메인기자 (3) 보강기자 (4) 최신순
    def sort_key(it):
        rm = 0 if it.get("real_madrid") else 1
        tier_rank = {"메인 기자": 0, "보강 기자": 1}.get(it.get("reporter_tier"), 2)
        pub = it.get("published") or ""
        return (rm, tier_rank, "" if pub else "z", pub == "", pub)

    for lg in items:
        seen = set()
        dedup = []
        for it in items[lg]:
            key = it["title"].lower()
            if key in seen:
                continue
            seen.add(key)
            dedup.append(it)
        # 최신순으로 우선 정렬한 뒤, 레알마드리드/기자 우선순위로 재정렬(안정정렬 활용)
        dedup.sort(key=lambda x: x["published"] or "", reverse=True)
        if lg == "LaLiga":
            dedup.sort(key=lambda x: (0 if x.get("real_madrid") else 1,
                                       {"메인 기자": 0, "보강 기자": 1}.get(x.get("reporter_tier"), 2)))
        else:
            dedup.sort(key=lambda x: {"메인 기자": 0, "보강 기자": 1}.get(x.get("reporter_tier"), 2))
        items[lg] = dedup[:25]

    out = {
        "generated_at": now.isoformat(),
        "leagues": items,
        "errors": errors,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    total = sum(len(v) for v in items.values())
    print(f"완료: {total}건 수집, 갱신시각 {now.isoformat()}")
    if errors:
        print("오류:", errors)

if __name__ == "__main__":
    main()
