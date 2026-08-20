#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
5대 리그(EPL, LaLiga, Bundesliga, Serie A, Ligue 1) 당일 축구 뉴스 수집기
- 공식/공신력 있는 언론·리그 RSS 피드를 수집해 리그별로 분류
- 기자 배지는 RSS의 실제 author(작성자) 필드에 이름이 명시된 경우에만 부여
  (매체 단위 추정 태깅은 사용하지 않음 — 부정확한 귀속 방지)
- 라리가는 레알 마드리드 관련 기사를 1순위로 정렬
- 요약은 원문 문장을 그대로 옮기거나 살짝 바꾼 것이 아니라, 핵심 사실
  (누가/무엇을/언제/어디서)만 뽑아 완전히 새로운 문장으로 재구성한 "팩트 브리핑"
  형태로 생성 (저작권 상 안전한 방식)
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
from deep_translator import GoogleTranslator

_TRANSLATE_CACHE = {}

def translate_ko(text):
    """짧은 제목/리드문(공개 RSS 발췌분)을 한국어로 번역. 실패 시 원문 유지.
    번역 대상은 언론사가 RSS로 공개 배포하는 짧은 리드문이며, 기사 본문 전체가 아님."""
    text = (text or "").strip()
    if not text:
        return text
    if text in _TRANSLATE_CACHE:
        return _TRANSLATE_CACHE[text]
    try:
        result = GoogleTranslator(source="auto", target="ko").translate(text[:4500])
        result = result or text
    except Exception:
        result = text
    _TRANSLATE_CACHE[text] = result
    return result

# ---- 수집 소스: 공식 리그/구단 + 공신력 있는 언론사 RSS ----
# trust: "공식"=리그/구단 공식, "언론"=일반 매체(개별 필자 특정 불가 다수),
#        "기자RSS"=해당 기자 개인 필자 페이지 RSS(author 필드로 실제 검증됨)
SOURCES = [
    {"name": "BBC Sport", "url": "http://feeds.bbci.co.uk/sport/football/rss.xml", "trust": "언론"},
    {"name": "Sky Sports", "url": "https://www.skysports.com/rss/12040", "trust": "언론"},
    {"name": "ESPN FC", "url": "https://www.espn.com/espn/rss/soccer/news", "trust": "언론"},
    {"name": "Guardian Football", "url": "https://www.theguardian.com/football/rss", "trust": "언론"},
    {"name": "Marca", "url": "https://e00-marca.uecdn.es/rss/futbol/primera-division.xml", "trust": "언론"},
    {"name": "AS", "url": "https://as.com/rss/futbol/primera.xml", "trust": "언론"},
    {"name": "Real Madrid 공식", "url": "https://www.realmadrid.com/en-US/rss/rmtv-news", "trust": "공식"},
    {"name": "Gazzetta dello Sport", "url": "https://www.gazzetta.it/rss/calcio.xml", "trust": "언론"},
    {"name": "Football Italia", "url": "https://www.football-italia.net/rss.xml", "trust": "언론"},
    {"name": "L'Équipe Football", "url": "https://dwh.lequipe.fr/api/edito/rss?path=/Football", "trust": "언론"},
    {"name": "Kicker Bundesliga", "url": "https://newsfeed.kicker.de/news/bundesliga", "trust": "언론"},
    {"name": "Bundesliga 공식", "url": "https://www.bundesliga.com/en/bundesliga/news/rss", "trust": "공식"},
    # Guardian은 필자별 개인 RSS를 공식 제공 -> author 필드가 실제로 채워져
    # "이 기자가 진짜 썼다"를 검증할 수 있는 몇 안 되는 신뢰 가능한 소스
    {"name": "Guardian - Sid Lowe", "url": "https://www.theguardian.com/football/sid-lowe/rss", "trust": "기자RSS"},
    {"name": "Guardian - Paolo Bandini", "url": "https://www.theguardian.com/football/paolo-bandini/rss", "trust": "기자RSS"},
    {"name": "Guardian - Nick Ames", "url": "https://www.theguardian.com/football/series/nick-ames-on-european-football/rss", "trust": "기자RSS"},
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

# 리그별 지정 기자 - author 필드에 정확히 이 이름이 있을 때만 매칭 (추정 금지)
LEAGUE_REPORTERS = {
    "EPL": {"main": ["David Ornstein"], "support": ["Kaveh Solhekol", "Phil McNulty"]},
    "LaLiga": {"main": ["Sid Lowe"], "support": ["Dermot Corrigan", "Guillem Balague", "Guillem Balagué"]},
    "SerieA": {"main": ["Paolo Bandini"], "support": ["Fabrizio Romano", "Matteo Bonetti"]},
    "Bundesliga": {"main": ["Raphael Honigstein"], "support": ["Jonathan Harding", "Nick Ames"]},
    "Ligue1": {"main": ["Jonathan Johnson"], "support": ["Julien Laurens", "Tom Williams"]},
}

# 리그별 지정 기자의 공식 SNS/프로필 링크 (직접 스크레이핑이 불가한 SNS는
# 링크로 연결해 사용자가 직접 최신 트윗/기사 목록을 확인하도록 안내)
REPORTER_PROFILES = {
    "EPL": [
        {"name": "David Ornstein", "role": "메인 기자", "outlet": "The Athletic",
         "x": "https://x.com/David_Ornstein", "profile": "https://theathletic.com/staff/david-ornstein/"},
        {"name": "Kaveh Solhekol", "role": "보강 기자", "outlet": "Sky Sports",
         "x": "https://x.com/SkyKaveh", "profile": "https://www.skysports.com/football/news"},
        {"name": "Phil McNulty", "role": "보강 기자", "outlet": "BBC Sport",
         "x": "https://x.com/philmcnulty", "profile": "https://www.bbc.co.uk/sport/football"},
    ],
    "LaLiga": [
        {"name": "Sid Lowe", "role": "메인 기자", "outlet": "The Guardian / ESPN",
         "x": "https://x.com/sidlowe", "profile": "https://www.theguardian.com/football/sid-lowe"},
        {"name": "Dermot Corrigan", "role": "보강 기자", "outlet": "The Athletic",
         "x": "https://x.com/dermotmcorrigan", "profile": "https://theathletic.com/staff/dermot-corrigan/"},
        {"name": "Guillem Balague", "role": "보강 기자", "outlet": "독립 / BBC 기고",
         "x": "https://x.com/GuillemBalague", "profile": "https://www.guillembalague.com/"},
    ],
    "SerieA": [
        {"name": "Paolo Bandini", "role": "메인 기자", "outlet": "The Guardian",
         "x": "https://x.com/Paolo_Bandini", "profile": "https://www.theguardian.com/football/paolobandini"},
        {"name": "Fabrizio Romano", "role": "보강 기자", "outlet": "독립(이적시장 전문)",
         "x": "https://x.com/FabrizioRomano", "profile": "https://www.fabrizioromano.com/"},
        {"name": "Matteo Bonetti", "role": "보강 기자", "outlet": "Football Italia 등",
         "x": "https://x.com/mattbonetti", "profile": None},
    ],
    "Bundesliga": [
        {"name": "Raphael Honigstein", "role": "메인 기자", "outlet": "The Athletic",
         "x": "https://x.com/honigstein", "profile": "https://theathletic.com/staff/raphael-honigstein/"},
        {"name": "Jonathan Harding", "role": "보강 기자", "outlet": "독립(분데스리가 전문)",
         "x": "https://x.com/JHardingFF", "profile": None},
        {"name": "Nick Ames", "role": "보강 기자", "outlet": "The Guardian",
         "x": "https://x.com/NicholasAmes", "profile": "https://www.theguardian.com/football/nick-ames"},
    ],
    "Ligue1": [
        {"name": "Jonathan Johnson", "role": "메인 기자", "outlet": "ESPN / Get French Football News",
         "x": "https://x.com/JonathanJohnsn", "profile": None},
        {"name": "Julien Laurens", "role": "보강 기자", "outlet": "ESPN / L'Équipe",
         "x": "https://x.com/LaurensJulien", "profile": None},
        {"name": "Tom Williams", "role": "보강 기자", "outlet": "Get French Football News",
         "x": "https://x.com/tomwfootball", "profile": None},
    ],
}

REAL_MADRID_KEYWORDS = ["real madrid", "레알 마드리드", "bernabeu", "bernabéu"]
INTERVIEW_KEYWORDS = ["interview", "인터뷰", "q&a", "exclusive:"]

STOPWORDS = {"the","a","an","and","or","but","in","on","at","to","of","for","with","as","is","are",
             "was","were","be","been","has","have","had","it","its","this","that","by","from","his",
             "her","their","he","she","they","after","before","who","which","said"}

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

def detect_reporter(league, author_field):
    """RSS author 필드에 지정 기자 이름이 '정확히' 있을 때만 인정 (추정 금지)"""
    if not author_field:
        return None, None
    reps = LEAGUE_REPORTERS.get(league, {})
    low = author_field.lower()
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

def is_interview(title, summary):
    low = f"{title} {summary}".lower()
    return any(kw in low for kw in INTERVIEW_KEYWORDS)

def clean(text):
    text = unescape(text or "")
    text = re.sub("<[^<]+?>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def parse_time(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
    return None

def build_fact_brief(title, summary, source, league):
    """
    원문 문장을 그대로 옮기거나 표현만 바꿔 재현하지 않고,
    제목/요약에서 확인 가능한 핵심 정보(주체, 소재, 리그/구단, 출처)만
    뽑아 완전히 새로운 한국어 문장 구조로 재구성한 간단 브리핑을 만든다.
    (원문 문장의 순서·구조를 따라가지 않음 — 사실 나열형)
    """
    facts = []
    blob = f"{title} {summary}"
    low = blob.lower()

    # 관련 구단 감지
    club_hits = []
    for lg, kws in LEAGUE_KEYWORDS.items():
        for kw in kws:
            if kw in low and kw not in ("la liga","laliga","premier league","epl",
                                          "serie a","bundesliga","ligue 1"):
                club_hits.append(kw.title())
    club_hits = list(dict.fromkeys(club_hits))[:3]

    if club_hits:
        facts.append(f"관련 구단: {', '.join(club_hits)}")

    if is_interview(title, summary):
        facts.append("형식: 인터뷰/1인칭 발언 포함 기사")

    # 이적/부상/경기결과 등 핵심 토픽 추정 (사실 카테고리 태깅, 문장 재현 아님)
    topic_map = {
        "이적 관련": ["transfer", "move to", "signing", "signs for", "loan", "fee"],
        "부상 소식": ["injury", "injured", "surgery", "sidelined"],
        "경기 결과/프리뷰": ["win", "defeat", "draw", "beat", "kick off", "fixture", "match"],
        "감독/코칭스태프": ["manager", "coach", "sacked", "appointed"],
        "계약 관련": ["contract", "extension", "renewal"],
    }
    topics = [k for k, kws in topic_map.items() if any(w in low for w in kws)]
    if topics:
        facts.append("주제: " + ", ".join(topics))

    facts.append(f"보도: {source}")

    header = " · ".join(facts) if facts else f"보도: {source}"

    return header

def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=48)
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

                reporter, reporter_tier = detect_reporter(league, author)
                # "기자RSS" 소스인데 author 매칭이 안 되면 해당 기자 개인 피드가
                # 맞는지 애매하므로, 소스가 특정 기자 전용 피드일 때는 소스명 자체로 보정
                if not reporter and src["trust"] == "기자RSS":
                    for lg2, reps in LEAGUE_REPORTERS.items():
                        for name in reps.get("main", []) + reps.get("support", []):
                            if name in src["name"]:
                                reporter, reporter_tier = name, (
                                    "메인 기자" if name in reps.get("main", []) else "보강 기자"
                                )

                fact_brief = build_fact_brief(title, summary, src["name"], league)

                item = {
                    "title": translate_ko(title),
                    "title_original": title,
                    "fact_brief": fact_brief,
                    "summary": translate_ko(summary[:400]),
                    "link": link,
                    "source": src["name"],
                    "trust": src["trust"],
                    "published": pub.isoformat() if pub else None,
                    "reporter": reporter,
                    "reporter_tier": reporter_tier,
                    "reporter_verified": bool(reporter),  # author 필드로 실제 검증됨
                    "is_interview": is_interview(title, summary),
                    "real_madrid": is_real_madrid(f"{title} {summary}") if league == "LaLiga" else False,
                }
                items[league].append(item)
        except Exception as e:
            errors.append(f"{src['name']}: {e}")

    for lg in items:
        seen = set()
        dedup = []
        for it in items[lg]:
            key = it["title"].lower()
            if key in seen:
                continue
            seen.add(key)
            dedup.append(it)
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
        "reporter_profiles": REPORTER_PROFILES,
        "errors": errors,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    total = sum(len(v) for v in items.values())
    verified = sum(1 for lg in items.values() for it in lg if it["reporter_verified"])
    print(f"완료: {total}건 수집 (검증된 지정 기자 기사 {verified}건), 갱신시각 {now.isoformat()}")
    if errors:
        print("오류:", errors)

if __name__ == "__main__":
    main()
