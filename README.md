# nboim-instagram — 앤보임 인스타 매일 아침 8시 자동 게시

> **2026-10-06 대표 결정: 릴스(영상) 대신 사진(4:5) 캐러셀만 올립니다.** 화·금 폴더도 `책 홍보 키트.html`에서 「4:5」로 받은 `1080x1350_NN.jpg`를 넣어 두면 캐러셀로 변환됩니다(4:5 카드가 있으면 폴더 이름이 「릴스」여도 캐러셀). 릴스 코드는 남겨 두었지만 지금은 쓰지 않으므로 Pages 전환은 선택 사항입니다.


> **2026-10-10 진행 상황:** ①(저장소 생성)·②(푸시)·Actions 쓰기 권한은 끝났습니다 — https://github.com/engguinness/nboim-instagram (공개, publish·refresh-token 워크플로 활성). **남은 건 ③ 인스타 토큰 발급 → ④ Secret 2개 → ⑤ 드라이런 확인**뿐이며 대표님 계정으로만 할 수 있습니다. 10-07 은 수동 게시됐고, 10-09·10-10 은 대표 결정으로 건너뜁니다(파일은 남아 있으니 Run workflow 로 나중에 올릴 수 있음).

앤보임 인스타(**@justenglish_guinness**)에 **매일 08:00(한국 시간)** 게시물을 자동으로 올립니다.
컴퓨터가 꺼져 있어도 됩니다 — GitHub Actions(깃허브 서버)가 알아서 돌립니다.

- 올리는 방식: Instagram API (인스타 로그인 방식, `graph.instagram.com`)
- 올릴 내용: 이 저장소의 `posts/날짜/` 폴더 (카드뉴스·책안내 = 사진 캐러셀, 릴스 = mp4 영상)
- 미디어 주소: 인스타가 이 저장소의 공개 주소에서 사진·영상을 가져갑니다 → **저장소는 반드시 공개(Public)**

```
posts/2026-10-07/   post.json  caption.txt  01.jpg … 09.jpg            (카드뉴스·책안내)
posts/2026-10-09/   post.json  caption.txt  video.mp4  cover.jpg       (릴스)
posts/날짜/published.json   ← 게시가 끝나면 자동으로 생김 (있으면 그날은 다시 안 올림)
state/token.enc             ← 매주 갱신되는 인스타 토큰(암호화) — 손대지 마세요
state/account.json          ← 계정 번호 기록(아이디를 바꿔도 이 번호로 확인) — 자동 생성
publish.py                  ← 게시기 (+ 토큰 갱신)
sync_content.py             ← 원본 콘텐츠 폴더 → posts/ 변환기
.github/workflows/          ← publish.yml(카드, 매일 08:00 예약) · reels.yml(릴스, 매시간 :13 · 18~24시만 게시) · refresh-token.yml(월·목 10:00)
```

현재 `posts/` 에는 **2026-10-07 ~ 2026-10-31** (18편)이 들어 있습니다. 10-03·10-05·10-06 은 이미 지난 날이라 뺐습니다.


> **릴스 경로 (2026-11-18 대표 지시: 모두영어 쇼츠를 하루 1편씩 릴스로):** `reels/<YYYY-MM-DD>/` 에 `video.mp4`·`cover.jpg`·`caption.txt`·`post.json`(type `reel`)을 두면, 워크플로 `reels.yml` 이 매일 저녁 그날 폴더를 올립니다(`python publish.py --root reels`). 카드(`posts/`, `publish.yml`, 08:00)와는 완전히 별개라 같은 날 둘 다 있어도 서로 막지 않습니다.
>
> - **호스팅 = Cloudflare Pages 프로젝트 `nboim-reels`**: 영상·표지 주소는 `https://nboim-reels.pages.dev/reels/<날짜>/video.mp4`·`cover.jpg`(검색 제외 헤더 noindex). 인스타 릴스 API 는 `video_url` 을 직접 받아 가는데, raw.githubusercontent 는 mp4 를 `application/octet-stream` 으로 주고, jsDelivr 는 패키지 크기 한도·이용약관(영상 호스팅 금지) 문제가 있어 둘 다 쓰지 않습니다. 앞부분은 환경변수 `REEL_MEDIA_BASE`(reels.yml 에 명시), 없으면 코드 상수 `REEL_MEDIA_BASE_DEFAULT`. 컨테이너를 만들기 전에 영상 `video/…`·표지 `image/…` 형식으로 200 이 오는지 확인하고(최대 8번, 20초 간격), 끝내 안 되면 게시하지 않고 실패합니다.
> - **새 편 추가 = 맥북에서 `tools/deploy_pages.sh`**: 새 편을 `reels/<날짜>/` 에 넣고 이 스크립트를 실행하면 `reels/` 전체를 Pages 에 다시 배포하고 모든 주소가 200·mp4 이고 **내용(md5)도 로컬 파일과 같은지** 확인합니다(배포에서 빠진 옛 경로는 Cloudflare 캐시에 예전 영상이 남는 것을 11-18 에 봤음 — 같은 날짜 주소에 다른 영상이 걸리면 인스타가 엉뚱한 영상을 가져간다). wrangler 는 저장소가 아닌 임시 폴더에서 돌립니다(`.wrangler/` 캐시에 계정 이름이 들어감). Pages 배포는 매번 **전체 스냅숏**이라 일부만 올리면 나머지가 사라지므로 항상 전체를 올립니다. 깃허브 푸시만으로는 영상이 Pages 에 올라가지 않습니다. 영상 파일은 25MiB 이하여야 합니다. `post.json` 이 있는 날짜에 `video.mp4`·`cover.jpg` 가 없거나 이름이 다르면 배포를 중단합니다(일부만 올라가 주소가 사라지는 것을 막음). 확인 단계는 늦은 반영을 6번×10초 다시 봅니다.
> - **`reels_hold/` = 유튜브 공개 전 보류분**: 아직 유튜브에 공개되지 않은 편은 `reels_hold/<날짜>/` 에 두어 올리지도(deploy 가 안 봄) 게시하지도 않습니다(`.gitignore` 로 제외). 유튜브에 공개된 것을 확인하면 `reels/` 로 옮기고 다시 배포합니다 — 클로드 앱 1회 루틴 `nboim-reels-hold-check-2026-12-07`(12-05 10:30)이 공개·중복을 확인해 12-07 부터 넣습니다(11-18 기준 세트4 s2~s7 6편 보류).
> - **대표가 손으로 먼저 올린 쇼츠는 넣지 않음**: 10-26 「영어 단어 몇 개나」(모션 시안), 10-28 세트1 s2(1901), 11-02 세트1 s3(띄어쓰기)는 이미 계정에 릴스로 있어 뺐습니다(`reels_dropped/`, `.gitignore`). 새 묶음을 넣기 전에 공개 프로필의 릴스 탭에서 같은 영상이 있는지 확인하고, **같은 쇼츠를 앱에서 직접 올리지 않습니다**(중복).
> - **예약 지연과 저녁 시간대(11-20 고침)**: 이 저장소의 깃허브 예약 실행은 5~9시간씩 늦게 돕니다(11-18·19 실측 — 하루 한 번 `13 9 * * *`(18:13 KST) 예약이 다음 날 03:00 무렵에 돌아 11-19 몫이 11-20 03:13 에 올라감). 그래서 cron 은 **매시간 `13 * * * *`**(정각 혼잡을 피해 :13)이고, 첫 작업 `gate`(checkout 없음, 읽기 권한만)가 **한국 시간 18~24시인 예약 실행만** 통과시킵니다. 그날 `reels/<날짜>/published.json` 이 이미 있거나(게시됨·status=unknown) `post.json` 이 없으면 gate 에서 끝나고, 깃허브 API 응답을 모르면(네트워크·5xx·20초 타임아웃) 통과시켜 publish.py 가 판정합니다. `publish.py` 도 한 번 더 확인합니다: 예약 실행이고 `--date` 가 없으면 `REEL_WINDOW`(18~24시) 밖에서는 아무것도 하지 않고 0 으로 끝나며(로그 한 줄), 안에서는 대상 날짜가 늘 오늘입니다(로그에 `대상 날짜 : … — 이유` 한 줄). 상태 줄(concurrency `nboim-instagram-state`)에는 gate 를 통과한 `reels` 작업만 들어가 매시간 깨움이 카드·토큰 갱신의 대기 실행을 밀어내지 않습니다. 실패(rc 1)하면 published.json 이 안 생기므로 그날 24시 전까지 다음 매시간 실행이 다시 시도합니다 — 원인이 그대로면 실패 메일도 시도마다 옵니다. **빠진 날은 자동으로 다시 올리지 않습니다**(다음 날 저녁은 그날 몫만). 수동 실행(Actions → reels → Run workflow, 기본 dry)·`--date`·로컬 실행은 시간대와 상관없이 오늘(한국 시간) 또는 지정한 날짜로 진행합니다. checkout 은 `ref: ${{ github.ref_name }}` 로 시작 시점의 최신 main 을 받습니다.
> - **이중 게시 방지(릴스는 카드보다 엄격)**: ① `reels/<날짜>/published.json` 이 있으면 그날은 다시 안 올림 ② 최근 48시간 같은 캡션 대조 — 릴스는 **최근 게시물 조회가 실패하면 경고 후 진행하지 않고 게시하지 않고 실패**합니다(하루 빠지는 편이 두 번 올라가는 것보다 낫다 — 그날 24시 전이면 다음 매시간 실행이 다시 시도) ③ 발행(`media_publish`)이 연결 오류·타임아웃·5xx, 또는 일시 오류 표시(`is_transient`, 코드 -1·-2·1·2, 하위코드 2207001·2207008·2207053)가 붙은 400 으로 끝나 결과를 모르면 10초 간격 6번 최근 글을 다시 보고, 찾으면 성공으로 기록, 끝내 못 찾으면 `published.json` 에 `{"status":"unknown", …}` 를 남기고 실패(rc 1) — 다음 예약 실행은 기록 파일이 있으므로 gate 에서 끝나고, 수동 실행은 「게시 여부 확인 필요 — 다시 올리지 않음」만 남기고 건너뜁니다. 사람이 인스타를 확인해 올라갔으면 실제 기록으로, 안 올라갔으면 파일을 지워 다시 올립니다. 그 밖의 분명한 4xx 거절은 기록 없이 실패. **빠진 날 복구는 실패한 실행의 Re-run 이 아니라 Run workflow 에서 날짜를 넣고 dry 를 끄는 방식**으로 합니다(Re-run 은 예약 실행 그대로라 18~24시 밖이면 아무것도 하지 않고, 다음 날 저녁이면 그날 몫을 올림).
> - **`tools/reels_convert.py`**: 유튜브 쇼츠 원본(모두영어 세트1~4 `…/모두영어-세트1/v2`)에서 끝의 구독 장면만 잘라 `reels/<날짜>/{video.mp4,cover.jpg,post.json}` 을 만드는 변환기(ffmpeg 는 `imageio_ffmpeg` 번들). `--verify` 로 형식·길이 점검(out 에 영상이 있는 날짜만). id 를 적거나 `--all` 을 줘야 돌고, `reels_hold/<날짜>`·`published.json` 이 있는 날짜는 건너뛰며, 이미 있는 `reels/<날짜>` 는 `--overwrite` 없이는 덮어쓰지 않습니다. `caption.txt` 는 만들지 않으니 사실 점검 후 따로 넣습니다.
> - 로컬 확인: `python3 publish.py --root reels --date <아직 안 올린 날짜> --dry`(예: `2026-12-06`. 이미 올린 날짜는 「이미 게시됨」만 나옴 · 주소 확인 포함, 3번×10초까지 기다림; `--no-url-check` 면 생략 · 로컬 실행은 저녁 시간대와 상관없음).

---

## 처음 한 번만 — 대표님이 할 일 (순서대로)

### ① GitHub 에 공개 저장소 만들기

1. https://github.com 에 `engguinness` 계정으로 로그인
2. 오른쪽 위 **`+`** → **New repository**
3. **Repository name**: `nboim-instagram`
4. **Public** 선택 (이유: 인스타가 사진·영상을 공개 주소로 가져가야 해서)
5. 아래 체크박스 3개(**Add a README file / Add .gitignore / Choose a license**)는 **전부 비워 둔 채로**
6. **Create repository** 클릭

### ② 이 폴더를 올리기 (터미널에서)

```bash
cd ~/Apps/nboim-instagram
git remote add origin https://github.com/engguinness/nboim-instagram.git
git push -u origin main
```

- 비밀번호를 물으면 GitHub 비밀번호가 아니라 **개인 액세스 토큰**을 넣어야 합니다:
  GitHub 오른쪽 위 프로필 → **Settings** → 맨 아래 **Developer settings** → **Personal access tokens** → **Tokens (classic)** → **Generate new token (classic)** → 체크: **`repo`** 와 **`workflow`** (워크플로 파일을 올리려면 `workflow` 도 필요) → 만들어진 토큰을 비밀번호 칸에 붙여넣기.
- 올라가면 저장소 페이지에 `posts/`, `publish.py` 등이 보입니다.

### ③ 인스타 연결: 메타 앱 「클로드 자동화」에서 토큰 받기

> `justenglish_guinness` 는 **프로페셔널 계정**(비즈니스/크리에이터)이어야 합니다. (인스타 앱 → 설정 → 계정 유형 및 도구에서 확인)

1. https://developers.facebook.com → 로그인 → 위쪽 **내 앱** → **클로드 자동화** (앱 ID `2766202690403847`) 클릭
2. 왼쪽 메뉴 **앱 역할** → **역할** → **역할 추가** → **Instagram 테스터** 선택 → 사용자 이름 칸에 `justenglish_guinness` 입력 → **추가**
   (이미 목록에 있으면 이 단계는 건너뜀)
3. **인스타 앱**(휴대폰, `justenglish_guinness` 로 로그인): 프로필 → 오른쪽 위 ☰ → **설정 및 활동** → **앱 및 웹사이트** → **테스터 초대** → 「클로드 자동화」 초대를 **수락**
   (컴퓨터라면 instagram.com → 설정 → 앱 및 웹사이트 → 테스터 초대 탭)
4. 다시 개발자 사이트 「클로드 자동화」 앱 → 왼쪽 메뉴 **Instagram** → **Instagram API 설정** (Instagram 로그인을 통한 API 설정)
5. **액세스 토큰 생성** 목록에 `justenglish_guinness` 가 없으면 **계정 추가** → 인스타 로그인 창에서 로그인 → 권한(콘텐츠 게시 포함) **허용**
6. 목록에 `justenglish_guinness` 가 보이면 **토큰 생성** → 긴 문자열이 나옵니다 → **복사** (60일짜리 토큰이며, 아래 자동 갱신이 계속 연장합니다)
7. ⚠️ 이 토큰은 채팅·메모 어디에도 붙여넣지 말고, **바로 ④ 의 Secret 칸에만** 붙여넣으세요.

### ④ GitHub 에 Secret 2개 넣기

저장소 페이지 → **Settings** → 왼쪽 **Secrets and variables** → **Actions** → **New repository secret**

| Name | Secret (값) |
|---|---|
| `IG_ACCESS_TOKEN` | ③-6 에서 복사한 토큰 |
| `IG_TOKEN_KEY` | **아무 긴 문장** — 40자 이상 권장. 터미널에서 `openssl rand -base64 32` 로 만든 값을 써도 됩니다 |

각각 값을 붙여넣고 **Add secret**. `IG_TOKEN_KEY` 는 매주 갱신된 토큰을 저장소에 **암호화**해서 보관할 때 쓰는 암호입니다.
저장소가 공개라 암호문이 누구에게나 보이므로 **짧은 암호는 쓰지 마세요.**

### ⑤ 한 번 연습 실행 (실제로 올리지 않음)

1. 저장소 위쪽 **Actions** 탭 (처음이면 초록 버튼 「I understand my workflows, go ahead and enable them」이 뜰 수 있음 → 클릭)
2. 왼쪽 **publish** → 오른쪽 **Run workflow** 드롭다운 → `date` 는 비우거나 `2026-10-07` → **dry** 체크가 켜져 있는 걸 확인 → 초록 **Run workflow**
3. 잠시 뒤 새로 생긴 실행을 클릭 → **publish** 작업 → **Publish** 단계를 펼쳐서 확인:
   - `종류 : 캐러셀 9장`, 미디어 주소 줄들, 마지막에 `미디어 URL 확인: 모두 200` → 정상
   - `시크릿 : IG_ACCESS_TOKEN 있음 · IG_TOKEN_KEY 있음` → ④ 에서 넣은 Secret 이 잘 읽힌다는 뜻 (`없음` 이면 ④ 를 다시)
   - `문제 : …HTTP 404` → 저장소가 비공개이거나 ② 를 안 한 것
4. **토큰이 맞는지** 보려면: Actions → 왼쪽 **refresh-token** → **Run workflow** → 로그에 `계정 확인 : @justenglish_guinness OK` 가 나오면 성공 (이 작업이 토큰도 한 번 갱신해 `state/token.enc` 를 만듭니다. 발급 24시간 이내라면 「갱신 건너뜀」이 나오는데, 계정 확인은 그 전에 이미 통과한 것입니다)
5. **릴스 영상 주소 문제**가 걱정되면 아래 「GitHub Pages 로 전환」을 지금 해 두세요. 릴스 첫 게시일은 **10-09(금)** 입니다.

### ⑥ 끝 — 매일 08:00 에 자동 게시

- 첫 게시: **2026-10-07(수) 08:00** 카드뉴스 9장
- 올라가면 `posts/2026-10-07/published.json` 이 저장소에 자동 커밋됩니다 (인스타 글 주소 포함)
- 안 올라가면 GitHub 이 **실패 메일**을 보냅니다 (아래 「실패했을 때」)

---

## 새 달 콘텐츠 넣는 법

1. 원본 폴더 이름이 `MM-DD (요일) 종류 · 제목` 형식인지 확인 (종류 = `카드뉴스` · `책안내` · `릴스`)
   - 예: `11-02 (월) 카드뉴스 · 문법부터 vs 회화부터`
   - `인스타 11월 예비 게시물/` 의 `01 문법부터 vs 회화부터` 처럼 **날짜가 없는 폴더는 건너뜁니다** (변환기가 알려 줌). 날짜를 붙여 이름을 바꾸면 됩니다.
   - 카드뉴스·책안내는 `1080x1350_NN.jpg`, 릴스는 `1080x1920_NN.jpg` 를 씁니다. 캡션은 `1_인스타 본문.txt`.
2. 변환 (미리 보기는 `--dry` 를 붙이세요):
   ```bash
   cd ~/Apps/nboim-instagram
   ~/Apps/_venvs/media/bin/python sync_content.py "<원본 폴더 경로>" --from 2026-11-01
   ```
   - 이미 변환된 날짜는 건너뜁니다. 다시 만들려면 `--force` (이미 게시된 날짜는 건드리지 않음).
3. 올리기:
   ```bash
   git add posts
   git commit -m "11월 게시물 추가"
   git push
   ```
   **게시 전날까지** 푸시해 두세요 (파일이 공개 주소에 반영되는 데 몇 분 걸림).
4. 콘텐츠가 없는 날은 「게시물 없음」으로 **조용히 성공 처리**됩니다(알림 없음). 달이 끝나기 전에 다음 달을 넣어 두세요.

---

## 실패했을 때

GitHub 저장소 → **Actions** 탭 → 빨간 ✗ 가 붙은 실행 클릭 → **Publish** 단계 로그 맨 아래 `실패: …` 줄을 읽습니다.

| 로그 문구 | 뜻 / 할 일 |
|---|---|
| `미디어 URL 에 접근할 수 없음 … HTTP 404` | 파일을 푸시하지 않았거나 저장소가 비공개. `git push` 확인, Settings → General 맨 아래에서 Public 확인 |
| `토큰의 계정이 justenglish_guinness 가 아님` | 다른 계정으로 토큰을 만들었음 → ③ 을 `justenglish_guinness` 로 다시 |
| `토큰으로 계정을 확인하지 못함 … #190` | 토큰이 만료·무효 → ③ 에서 새 토큰 발급 → Secret `IG_ACCESS_TOKEN` 값을 교체(Secret 이 새것이면 자동으로 그걸 씀) → refresh-token 한 번 실행 |
| `릴스 처리 실패(ERROR)` | 영상을 인스타가 못 가져왔거나 형식 문제 → 아래 「GitHub Pages 로 전환」 |
| `릴스 가 300초 안에 FINISHED 되지 않음` | 인스타 쪽 지연 → 카드는 같은 날 수동 재실행. 릴스는 그날 24시 전이면 다음 매시간 실행이 다시 시도(급하면 Run workflow, dry 끄기) |
| push 단계 `403` / `Permission denied` | Settings → Actions → General → **Workflow permissions** → **Read and write permissions** → Save |
| `경고: … Content-Type …` | 실패 아님. 영상 주소가 `video/mp4` 로 안 내려온다는 뜻 → 릴스가 거부되면 Pages 로 전환 |

**빠진 날 수동으로 올리기**: Actions → publish → Run workflow → `date` 에 날짜 → **dry 체크를 끄고** 실행.
**같은 날 앱에서 직접 올리지 마세요** — 자동 게시와 겹치면 중복됩니다. (같은 캡션이 최근 48시간 안에 올라가 있으면 자동 게시기가 알아채고 건너뛰긴 합니다.)
**이미 게시된 날을 일부러 다시 올리려면** `posts/날짜/published.json` 을 지우고 푸시해야 합니다 (인스타의 기존 글은 직접 삭제).

---

## GitHub Pages 로 전환 (릴스 영상 주소용 — 권장)

기본값은 `https://raw.githubusercontent.com/engguinness/nboim-instagram/main/posts/날짜/파일` 입니다.
2026-10-06 에 확인해 보니 **raw 주소는 사진(jpg)은 `image/jpeg` 로 주지만 mp4 는 `application/octet-stream` 으로 줍니다.**
인스타가 이 영상 주소를 받아줄지는 확실하지 않습니다(카드뉴스는 문제 없음). 릴스가 거부되면, 또는 미리 안전하게 가려면 Pages 로 바꾸세요 — Pages 는 mp4 를 `video/mp4` 로 줍니다.

1. 저장소 → **Settings** → 왼쪽 **Pages** → **Build and deployment** → **Source**: `Deploy from a branch` → **Branch**: `main` / `/ (root)` → **Save**
   (1~2분 뒤 같은 화면 위에 `https://engguinness.github.io/nboim-instagram/` 주소가 뜸)
2. **Settings** → **Secrets and variables** → **Actions** → 위쪽 **Variables** 탭 → **New repository variable**
   - Name: `MEDIA_BASE`
   - Value: `https://engguinness.github.io/nboim-instagram` (맨 끝에 `/` 없이)
   - **Add variable**
3. publish 를 `dry` 로 다시 실행 → 미디어 주소가 `engguinness.github.io/…` 로 나오고 `경고` 줄이 없어졌는지 확인

되돌리려면 `MEDIA_BASE` 변수를 삭제하면 다시 raw 주소를 씁니다. 로컬에서 확인할 때는 `MEDIA_BASE=… python publish.py --dry` 로 같은 값을 줄 수 있습니다.

---

## 알아 둘 것

- **시간**: 이 저장소의 깃허브 예약 실행은 몇 분이 아니라 몇 시간씩 늦습니다(11-18·19 실측 5~9시간 — 카드 08:00 예약이 12:49~12:58, 토큰 갱신 10:00 예약이 17:18, 릴스 18:13 예약이 다음 날 03:00 무렵). 카드는 「08:00 예약, 실제 게시는 오전~낮」으로 보세요. 릴스는 그래서 매시간(:13) 깨우고 한국 시간 18~24시에 닿은 실행만 올립니다(위 릴스 경로).
- **토큰 갱신**: 인스타 토큰은 60일 뒤 만료됩니다. 매주 월·목 10:00(KST) 예약(실제로는 몇 시간 늦게 돎) `refresh-token` 이 연장해서 `state/token.enc` 에 암호화해 저장하고, 게시기는 그걸 우선 씁니다. 공개 저장소라 암호문은 누구나 볼 수 있으니 `IG_TOKEN_KEY` 는 길게, 그리고 **절대 다른 곳에 쓰지 마세요**.
- **토큰을 바꿨을 때**: Secret `IG_ACCESS_TOKEN` 을 새 토큰으로 교체하면 됩니다. `token.enc` 가 옛 토큰으로 만든 것이면 자동으로 무시하고 새 Secret 을 씁니다.
- **계정 안전장치**: `state/account.json` 에 기록된 **계정 번호(user_id)** 와 토큰의 계정이 같을 때만 게시합니다(2026-10-15). 인스타 **아이디를 바꿔도 번호는 그대로라 그냥 계속 게시**되고, 로그에 「아이디 변경 감지: @옛 → @새」가 찍히며 기록이 새 아이디로 고쳐집니다. 기록이 아직 없을 때(처음 한 번)만 아이디가 `justenglish_guinness` 인지 보고 번호를 적습니다. 다른 계정 토큰이면 게시하지 않고 실패합니다.
- **스케줄 자동 중지**: 공개 저장소는 60일 동안 아무 활동이 없으면 깃허브가 스케줄을 끕니다. 게시 기록 커밋이 매일 생기니 보통은 문제 없지만, 콘텐츠가 떨어져 한참 비면 Actions 탭에서 다시 켜야 할 수 있습니다.
- **API 버전**: 기본 `v21.0` 입니다. 메타가 이 버전을 종료해서 오류가 나면 저장소 Variable `IG_API_VERSION` 에 더 높은 버전(예: `v23.0`)을 넣으세요.
- **로그**: 토큰·암호 키는 로그에 찍히지 않습니다(오류 문구에서도 가림).

## 개발자용

```bash
cd ~/Apps/nboim-instagram
~/Apps/_venvs/media/bin/python -m pytest -q                                      # 테스트 (네트워크 호출 없음, API 는 목)
~/Apps/_venvs/media/bin/python publish.py --date 2026-10-07 --dry --repo engguinness/nboim-instagram
~/Apps/_venvs/media/bin/python publish.py --date 2026-10-07 --dry --no-url-check --repo x/y   # 요청 0건
```

- `publish.py` 는 표준 라이브러리 + `requests` 만 씁니다(파이썬 3.9+). 토큰 암호화는 `openssl` 명령(AES-256-CBC, PBKDF2-SHA256 200000회)이라 직접 풀 수도 있습니다:
  `openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -a -pass env:IG_TOKEN_KEY < state/token.enc`
- 릴스 mp4 인코딩 규격: 1080x1920 · 30fps · H.264 high · yuv420p(tv range) · bt709 태그 · 무음 AAC 포함 · faststart · 장당 3.5초 · 10MB 이하(실제 약 3MB).
  원래 명령에서 한 가지만 바꿨습니다 — JPEG 카드의 색 행렬(BT.601)을 RGB 를 거쳐 BT.709 로 제대로 변환(원래 명령은 태그만 bt709 라 색이 약간 어긋남).
- `post.json` 형식: `{"type": "carousel", "date", "source", "caption": "caption.txt", "images": ["01.jpg", …]}` 또는 `{"type": "reel", …, "video": "video.mp4", "cover": "cover.jpg", "duration_sec", "video_bytes"}`
