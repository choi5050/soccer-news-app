# 5대 리그 오늘의 축구 뉴스 웹앱

EPL / La Liga / Bundesliga / Serie A / Ligue 1 뉴스를 매일 자동 수집해 리그별 탭으로 보여주는 정적 웹 대시보드입니다.

## 구성
- `fetch_news.py` — 공식/공신력 언론 RSS + 지정 기자 바이라인을 수집·분류해 `data.json` 생성
- `index.html` — `data.json`을 읽어 렌더링하는 대시보드 (정적 HTML, 별도 서버 불필요)
- `data.json` — 최근 수집 결과 (GitHub Actions가 매일 자동 갱신)
- `.github/workflows/update.yml` — 매일 KST 오전 8시 자동 실행 + 결과 자동 커밋

## 수집 소스

### 공식/언론 (전 리그 공통)
BBC Sport, Sky Sports, ESPN FC, The Guardian

### 리그별 전담 소스
| 리그 | 리그/구단 공식 | 언론 | 지정 기자 (메인 / 보강) |
|---|---|---|---|
| EPL | — | BBC, Sky, ESPN, Guardian | **David Ornstein** / Kaveh Solhekol, Phil McNulty |
| La Liga | Real Madrid 공식 | Marca, AS | **Sid Lowe** / Dermot Corrigan, Guillem Balague |
| Serie A | — | Gazzetta dello Sport, Football Italia | **Paolo Bandini** / Fabrizio Romano(CaughtOffside), Matteo Bonetti |
| Bundesliga | Bundesliga 공식 | Kicker | **Raphael Honigstein** / Jonathan Harding, Nick Ames |
| Ligue 1 | — | L'Équipe, Get French Football News | **Jonathan Johnson** / Julien Laurens, Tom Williams |

지정 기자의 바이라인(작성자명)이 기사에서 확인되면 카드에 배지로 표시됩니다(★=메인 기자, 주황=보강 기자).

### 우선순위 규칙
- **La Liga: 레알 마드리드 관련 기사가 항상 최상단**에 노출됩니다.
- 그 다음 메인 기자 → 보강 기자 → 최신순으로 정렬됩니다.

> 참고: 기자 개인 X/SNS 계정은 공개 API/RSS 정책상 직접 크롤링이 제한적이라, 해당 기자들이 실제로 기고하는 매체(Guardian, ESPN, Sky Sports, Marca, Gazzetta, CaughtOffside, Get French Football News 등)의 RSS를 수집한 뒤 바이라인으로 매칭하는 방식을 사용했습니다.

## GitHub에 배포해서 완전 자동화하는 방법

1. GitHub에서 새 저장소 생성 (예: `soccer-news-app`), Public으로 설정
2. 이 폴더 전체를 저장소에 업로드:
   ```bash
   cd soccer-news-app
   git init
   git remote add origin https://github.com/<본인계정>/soccer-news-app.git
   git add .
   git commit -m "init: soccer news dashboard"
   git branch -M main
   git push -u origin main
   ```
3. 저장소 Settings → Pages → Source를 `main` 브랜치 `/ (root)`로 설정 → 저장
4. 몇 분 후 `https://<본인계정>.github.io/soccer-news-app/` 로 접속하면 대시보드가 보입니다.
5. `.github/workflows/update.yml`이 이미 포함되어 있어서, 저장소를 올리는 순간부터 **매일 KST 오전 8시에 자동으로 `fetch_news.py`가 실행되고 `data.json`이 갱신되어 커밋**됩니다. Actions 탭에서 수동 실행(`Run workflow`)도 가능합니다.

### 로컬 PC에서만 쓰고 싶다면 (GitHub 없이)
```bash
pip install feedparser
python3 fetch_news.py     # data.json 갱신
# index.html을 브라우저로 열면 바로 확인 가능
```
매일 자동 실행하려면 cron 등록:
```bash
crontab -e
0 8 * * * cd /경로/soccer-news-app && python3 fetch_news.py
```

## 한계
- 세리에A/리그앙 등 시즌 초반에는 이탈리아어/프랑스어 매체 RSS 갱신이 뜸해 기사 수가 적을 수 있습니다.
- 기자 배지는 "바이라인에 이름이 명시된 경우"에만 표시됩니다. 해당 기자가 트위터 단독 속보를 올렸지만 정식 기사화 전이라면 아직 반영되지 않을 수 있습니다.
