#!/bin/bash
# 릴스 영상·표지를 Cloudflare Pages 전용 프로젝트 nboim-reels 에 올린다(맥북에서 실행).
#
# 왜: 인스타 릴스 API 는 video_url 을 직접 받아 가는데, raw.githubusercontent 는 mp4 를 application/octet-stream 으로 주고,
#     jsDelivr 는 패키지 크기 한도·이용약관(영상 호스팅 금지) 문제가 있다. 모두통신 릴스(modu-reels)와 같은 방식으로 바꿈(2026-11-18).
# 무엇을: reels/<날짜>/video.mp4·cover.jpg 를 전부 모아 한 번에 배포한다(Pages 배포는 매번 전체 스냅숏 — 일부만 올리면 나머지가 사라진다).
#         reels_hold/(유튜브 공개 전 보류분)는 올리지 않는다. 검색 제외 헤더(X-Robots-Tag: noindex)만 붙인다.
# 주소: https://nboim-reels.pages.dev/reels/<날짜>/video.mp4 — reels.yml 의 REEL_MEDIA_BASE 와 같아야 한다.
# 주의: wrangler 는 홈 폴더가 아닌 곳에서 실행한다(이 저장소 폴더). 프로젝트는 이미 있으니 --force 를 쓰지 않는다.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO/.pages_build"
PROJECT="nboim-reels"
BASE="https://nboim-reels.pages.dev"
WRANGLER="${WRANGLER:-$HOME/Apps/_tools/node/bin/wrangler}"
MAX_BYTES=$((25 * 1024 * 1024))   # Pages 파일당 한도 25MiB

trap 'rm -rf "$OUT"' EXIT
rm -rf "$OUT"
mkdir -p "$OUT/reels"
n=0
for d in "$REPO"/reels/*/; do
  date="$(basename "$d")"
  if [ -f "$d/post.json" ]; then
    # 게시 예정 편(post.json 있음)은 파일이 하나라도 없으면 배포하지 않는다 — 전체 스냅숏이라 빠지면 그 날짜 주소가 사라진다
    names="$(python3 -c 'import json,sys; j=json.load(open(sys.argv[1],encoding="utf-8")); print(j.get("video","video.mp4"), j.get("cover","cover.jpg"))' "$d/post.json")" \
      || { echo "실패: $date post.json 을 읽을 수 없음" >&2; exit 1; }
    if [ "$names" != "video.mp4 cover.jpg" ]; then echo "실패: $date post.json 의 video·cover 이름이 video.mp4·cover.jpg 가 아님($names) — 배포 스크립트는 이 이름만 올린다" >&2; exit 1; fi
    if [ ! -f "$d/video.mp4" ] || [ ! -f "$d/cover.jpg" ]; then echo "실패: $date 에 post.json 은 있는데 video.mp4·cover.jpg 가 없음 — 배포하면 그 날짜 주소가 사라진다" >&2; exit 1; fi
  elif [ ! -f "$d/video.mp4" ] || [ ! -f "$d/cover.jpg" ]; then
    echo "건너뜀: $date (post.json 도 영상·표지도 없는 빈 폴더)"; continue
  fi
  size=$(stat -f %z "$d/video.mp4" 2>/dev/null || stat -c %s "$d/video.mp4")
  if [ "$size" -gt "$MAX_BYTES" ]; then echo "실패: $date 영상이 Pages 한도(25MiB)를 넘음 ($size 바이트)" >&2; exit 1; fi
  mkdir -p "$OUT/reels/$date"
  cp "$d/video.mp4" "$d/cover.jpg" "$OUT/reels/$date/"
  n=$((n + 1))
done
[ "$n" -gt 0 ] || { echo "올릴 릴스가 없음" >&2; exit 1; }
printf '/*\n  X-Robots-Tag: noindex\n' > "$OUT/_headers"
echo "배포할 릴스 $n 편 → $PROJECT"

# wrangler 는 실행한 폴더에 .wrangler/ 캐시(계정 이름 포함)를 만든다 — 공개 저장소·홈 폴더가 아닌 임시 작업 폴더에서 돌린다.
WORKDIR="${TMPDIR:-/tmp}/nboim-pages-wrangler"
mkdir -p "$WORKDIR"
cd "$WORKDIR"
PATH="$(dirname "$WRANGLER"):$PATH" "$WRANGLER" pages deploy "$OUT" --project-name "$PROJECT" --branch main --commit-dirty=true

# 확인: 모든 편이 200·video/mp4, 표지 200·image/jpeg 인지(배포 반영이 늦으면 몇 번 다시 본다)
fail=0
for d in "$OUT"/reels/*/; do
  date="$(basename "$d")"
  for pair in "video.mp4:video/mp4" "cover.jpg:image/jpeg"; do
    f="${pair%%:*}"; want="${pair##*:}"; ok=0
    for i in 1 2 3 4 5 6; do
      h="$(curl -sI -m 20 "$BASE/reels/$date/$f" || true)"
      st="$(printf '%s' "$h" | head -1 | awk '{print $2}' || true)"
      ct="$(printf '%s' "$h" | { grep -i '^content-type:' || true; } | head -1 | awk '{print $2}' | tr -d '\r')"
      if [ "$st" = "200" ] && [ "${ct%%;*}" = "$want" ]; then
        # 내용까지 대조 — 같은 날짜 주소에 예전 배포의 다른 영상이 캐시로 남아 있으면 인스타가 엉뚱한 영상을 가져간다(11-18 실측: 배포에서 빠진 옛 경로는 캐시가 남음)
        got="$(curl -s -m 60 "$BASE/reels/$date/$f" | { md5 -q 2>/dev/null || md5sum | awk '{print $1}'; } || true)"
        exp="$( { md5 -q "$d$f" 2>/dev/null || md5sum "$d$f" | awk '{print $1}'; } )"
        if [ -n "$got" ] && [ "$got" = "$exp" ]; then ok=1; break; fi
        st="내용 다름"
      fi
      sleep 10
    done
    if [ "$ok" = 1 ]; then echo "확인 $date/$f 200 $want"; else echo "확인 실패 $date/$f (상태 ${st:-없음}, 형식 ${ct:-없음})" >&2; fail=1; fi
  done
done
exit "$fail"
