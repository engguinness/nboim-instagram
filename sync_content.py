#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""원본 콘텐츠 폴더 → 이 저장소의 posts/YYYY-MM-DD/ 로 변환·복사한다.

원본 폴더(날짜 폴더 여러 개가 든 상위 폴더)를 인자로 받는다. 폴더 이름 규칙:
    "10-07 (수) 카드뉴스 · 하루에 딱 이 다섯 가지"      (MM-DD (요일) 종류 · 제목)
  - 종류 카드뉴스·책안내 → carousel : 1080x1350_NN.jpg(4:5) 를 그대로 복사 + caption.txt + post.json
  - 종류 릴스            → reel     : 1080x1920_NN.jpg(9:16) 를 mp4 한 개로(장당 3.5초) + cover.jpg + caption.txt + post.json
  - 같은 폴더의 4x5_*.jpg, 3_릴스 영상*.mp4 등 다른 파일은 무시한다.
  - 날짜가 안 붙은 폴더(예: 11월 예비 게시물의 "01 문법부터 …")는 건너뛰고 알려 준다 —
    날짜를 붙여 폴더 이름을 바꾸면(예: "11-02 (월) 카드뉴스 · 문법부터 vs 회화부터") 변환된다.

이미 변환된 날짜(posts/<날짜>/post.json 있음)는 건너뛴다(--force 로 다시 만든다).
이미 게시된 날짜(published.json 있음)는 --force 여도 건드리지 않는다.
원본 폴더의 파일은 읽기만 한다.

사용 예:
    python sync_content.py "<원본 폴더>"                       # 전부
    python sync_content.py "<원본 폴더>" --from 2026-10-07     # 이 날짜부터
    python sync_content.py "<원본 폴더>" --dry                 # 무엇을 할지만 출력
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / 'posts'

CAPTION_SRC = '1_인스타 본문.txt'
CAROUSEL_RE = re.compile(r'^1080x1350_(\d{2})\.jpg$')
REEL_RE = re.compile(r'^1080x1920_(\d{2})\.jpg$')
FOLDER_RE = re.compile(r'^(\d{1,2})-(\d{1,2})\s*(?:\(([월화수목금토일])\))?\s*(\S+?)\s*[·・•]\s*(.+?)\s*$')
WEEKDAYS = '월화수목금토일'   # datetime.weekday(): 월=0

KIND_TO_TYPE = {'카드뉴스': 'carousel', '책안내': 'carousel', '릴스': 'reel'}
CAROUSEL_SIZE = (1080, 1350)
REEL_SIZE = (1080, 1920)
CAROUSEL_MIN, CAROUSEL_MAX = 2, 10      # 인스타 캐러셀 제한
FRAME_SEC = 3.5                          # 릴스: 카드 한 장당 길이
MAX_VIDEO_BYTES = 10 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024        # 인스타 이미지 제한
CAPTION_MAX_CHARS = 2200                 # 인스타 캡션 제한
CAPTION_MAX_HASHTAGS = 30
JPEG_QUALITY = 92                        # JPEG 가 아닌 원본을 변환할 때만 쓴다(JPEG 는 바이트 그대로 복사)

KNOWN_FFMPEG = Path.home() / 'Apps/_venvs/media/lib/python3.9/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1'


class SyncError(RuntimeError):
    pass


# ---------------------------------------------------------------- 폴더 이름·캡션·이미지

def parse_folder_name(name, year=2026):
    """폴더 이름에서 게시 날짜 등을 뽑는다. 규칙에 안 맞거나 없는 날짜면 None.
    반환: {'date': date, 'weekday': '수'|None, 'weekday_ok': bool, 'kind': '카드뉴스', 'title': '…', 'name': name}"""
    m = FOLDER_RE.match((name or '').strip())
    if not m:
        return None
    month, day, weekday, kind, title = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4), m.group(5)
    try:
        d = datetime.date(year, month, day)
    except ValueError:
        return None
    return {'date': d, 'weekday': weekday, 'weekday_ok': (weekday is None or WEEKDAYS[d.weekday()] == weekday),
            'kind': kind, 'title': title, 'name': name}


def read_caption(folder):
    """1_인스타 본문.txt 를 읽는다(그대로 쓰되 줄바꿈은 LF, 끝 공백은 제거). 없거나 비면 SyncError."""
    p = Path(folder) / CAPTION_SRC
    if not p.is_file():
        raise SyncError(f'캡션 파일 없음: {CAPTION_SRC}')
    text = p.read_text(encoding='utf-8-sig').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        raise SyncError(f'캡션이 비어 있음: {CAPTION_SRC}')
    return text


def caption_warnings(text):
    out = []
    if len(text) > CAPTION_MAX_CHARS:
        out.append(f'캡션 {len(text)}자 — 인스타 한도 {CAPTION_MAX_CHARS}자 초과')
    tags = re.findall(r'(?<!\S)#[^\s#]+', text)
    if len(tags) > CAPTION_MAX_HASHTAGS:
        out.append(f'해시태그 {len(tags)}개 — 인스타 한도 {CAPTION_MAX_HASHTAGS}개 초과')
    return out


def list_cards(folder, pattern):
    """폴더에서 pattern(CAROUSEL_RE|REEL_RE)에 맞는 카드 이미지를 번호순으로. 번호는 01 부터 빠짐없어야 한다."""
    found = []
    for p in Path(folder).iterdir():
        m = pattern.match(p.name)
        if m and p.is_file():
            found.append((int(m.group(1)), p))
    found.sort()
    nums = [n for n, _ in found]
    if nums and nums != list(range(1, len(nums) + 1)):
        raise SyncError(f'카드 번호가 01부터 이어지지 않음: {nums}')
    return [p for _, p in found]


def _open_image(path):
    from PIL import Image
    im = Image.open(path)
    im.load()
    return im


def check_card(path, expect_size):
    """이미지가 열리고 기대 크기인지 확인. 반환: 이미지 형식('JPEG' 등)."""
    try:
        im = _open_image(path)
    except Exception as e:
        raise SyncError(f'이미지를 열 수 없음: {Path(path).name} ({e})')
    if im.size != expect_size:
        raise SyncError(f'이미지 크기 {im.size[0]}x{im.size[1]} — {expect_size[0]}x{expect_size[1]} 이어야 함: {Path(path).name}')
    return im.format


def copy_card(src, dst, expect_size):
    """카드 한 장을 dst 로. JPEG 은 바이트 그대로 복사(재압축 없음), 아니면 JPEG 로 변환(품질 JPEG_QUALITY)."""
    fmt = check_card(src, expect_size)
    if fmt == 'JPEG':
        shutil.copyfile(src, dst)
    else:
        im = _open_image(src).convert('RGB')
        im.save(dst, 'JPEG', quality=JPEG_QUALITY, optimize=True)
    if os.path.getsize(dst) > MAX_IMAGE_BYTES:
        raise SyncError(f'이미지가 {MAX_IMAGE_BYTES // 1024 // 1024}MB 초과: {Path(src).name}')


# ---------------------------------------------------------------- ffmpeg

def find_ffmpeg(explicit=None):
    cands = [explicit, os.environ.get('FFMPEG'), shutil.which('ffmpeg')]
    try:
        import imageio_ffmpeg
        cands.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    cands.append(str(KNOWN_FFMPEG))
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return str(c)
    raise SyncError('ffmpeg 를 찾을 수 없음 — --ffmpeg 경로를 주거나 FFMPEG 환경변수를 설정하세요')


def ffmpeg_command(ffmpeg, frames_pattern, seconds, out_path):
    """릴스 영상 인코딩 명령. 1080x1920·30fps·H.264 high/yuv420p tv range·bt709 태그·무음 AAC·faststart.
    원래 쓰던 명령에서 색 변환 한 가지만 바꿨다: JPEG 카드(BT.601 행렬)를 RGB 를 거쳐 BT.709 로 제대로 바꾼 뒤
    bt709 로 태그한다(원래 명령은 행렬은 그대로 두고 태그만 bt709 라 붉은·푸른 쪽이 살짝 어긋남)."""
    vf = ('format=gbrp,scale=1080:1920:flags=lanczos+accurate_rnd:out_color_matrix=bt709:out_range=tv,'
          'format=yuv420p,fps=30')
    return [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
            '-framerate', '2/7', '-i', str(frames_pattern),
            '-f', 'lavfi', '-i', 'sine=frequency=1:sample_rate=44100', '-af', 'volume=0',
            '-vf', vf, '-fps_mode', 'cfr',
            '-color_range', 'tv', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
            '-c:v', 'libx264', '-profile:v', 'high', '-level', '4.1', '-preset', 'medium', '-crf', '20',
            '-g', '30', '-keyint_min', '30',
            '-c:a', 'aac', '-b:a', '128k', '-ar', '44100',
            '-t', f'{seconds:g}', '-movflags', '+faststart', str(out_path)]


def probe_video(ffmpeg, path):
    """`ffmpeg -i` 출력에서 길이·코덱·화소형식·오디오 유무를 읽는다."""
    r = subprocess.run([ffmpeg, '-hide_banner', '-i', str(path)], capture_output=True, text=True)
    text = r.stderr or ''
    m = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', text)
    if not m:
        raise SyncError('영상 길이를 읽지 못함(인코딩 실패?)')
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    v = re.search(r'Video:\s*(\w+)[^\n]*?,\s*(yuv\w+)\(([^)]*)\)[^\n]*?(\d{3,5})x(\d{3,5})', text)
    info = {'duration': duration, 'has_audio': 'Audio:' in text, 'raw': text}
    if v:
        info.update(codec=v.group(1), pix_fmt=v.group(2), color=v.group(3), width=int(v.group(4)), height=int(v.group(5)))
    return info


def build_video(cards, out_mp4, ffmpeg):
    """cards(9:16 JPEG 경로 목록)를 mp4 한 개로. 장당 FRAME_SEC 초. 반환: probe_video 결과."""
    seconds = len(cards) * FRAME_SEC
    with tempfile.TemporaryDirectory(prefix='nboim-frames-') as tmp:
        for i, c in enumerate(cards, start=1):
            shutil.copyfile(c, Path(tmp) / f'frame_{i:02d}.jpg')   # 한글 경로·%·번호 빈틈 걱정 없이 ASCII 이름으로
        cmd = ffmpeg_command(ffmpeg, Path(tmp) / 'frame_%02d.jpg', seconds, out_mp4)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not Path(out_mp4).is_file():
            raise SyncError('ffmpeg 인코딩 실패: ' + (r.stderr or '')[-300:])
    info = probe_video(ffmpeg, out_mp4)
    if abs(info['duration'] - seconds) > 0.3:
        raise SyncError(f'영상 길이 {info["duration"]:.2f}초 — {seconds:g}초여야 함')
    if not info['has_audio']:
        raise SyncError('오디오 트랙이 없음')
    return info


# ---------------------------------------------------------------- 폴더 하나 변환

def decide_type(parsed, folder):
    # 2026-10-06 대표 결정 「릴스 말고 사진(4:5)만」: 4:5 카드(1080x1350_NN.jpg)가 있으면 폴더 이름이 「릴스」여도 캐러셀로 올린다.
    has_car = any(CAROUSEL_RE.match(p.name) for p in Path(folder).iterdir())
    has_reel = any(REEL_RE.match(p.name) for p in Path(folder).iterdir())
    if has_car:
        return 'carousel'
    t = KIND_TO_TYPE.get(parsed['kind'])
    if t:
        return t
    if has_car and not has_reel:
        return 'carousel'
    if has_reel and not has_car:
        return 'reel'
    raise SyncError(f'종류를 알 수 없음("{parsed["kind"]}") — 폴더 이름에 카드뉴스·책안내·릴스 중 하나를 쓰세요')


def convert_folder(folder, parsed, posts_dir, ffmpeg=None, force=False, dry=False):
    """폴더 하나를 posts_dir/<날짜>/ 로 변환. 반환: {'status','date','type',...}.
    status: 'converted' | 'skipped'(이미 변환) | 'published'(이미 게시, 건드리지 않음) | 'dry'. 실패는 SyncError."""
    folder, posts_dir = Path(folder), Path(posts_dir)
    iso = parsed['date'].isoformat()
    target = posts_dir / iso
    if (target / 'published.json').exists():
        return {'status': 'published', 'date': iso}
    if (target / 'post.json').exists() and not force:
        return {'status': 'skipped', 'date': iso}

    ptype = decide_type(parsed, folder)
    caption = read_caption(folder)
    warns = caption_warnings(caption)
    cards = list_cards(folder, CAROUSEL_RE if ptype == 'carousel' else REEL_RE)
    if ptype == 'carousel' and not (CAROUSEL_MIN <= len(cards) <= CAROUSEL_MAX):
        raise SyncError(f'캐러셀은 이미지 {CAROUSEL_MIN}~{CAROUSEL_MAX}장이어야 함(현재 {len(cards)}장)')
    if ptype == 'reel' and not cards:
        raise SyncError('릴스 카드(1080x1920_NN.jpg)가 없음')
    result = {'status': 'dry' if dry else 'converted', 'date': iso, 'type': ptype, 'count': len(cards), 'warnings': warns}
    if dry:
        return result

    posts_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='.tmp-', dir=posts_dir))   # 다 만든 뒤에 한 번에 교체 — 중간에 죽어도 반쪽 폴더가 안 남는다
    try:
        post = {'type': ptype, 'date': iso, 'source': parsed['name'], 'title': parsed['title'], 'caption': 'caption.txt'}
        (tmp / 'caption.txt').write_text(caption + '\n', encoding='utf-8')
        if ptype == 'carousel':
            names = []
            for i, c in enumerate(cards, start=1):
                copy_card(c, tmp / f'{i:02d}.jpg', CAROUSEL_SIZE)
                names.append(f'{i:02d}.jpg')
            post['images'] = names
        else:
            for c in cards:
                check_card(c, REEL_SIZE)
            ff = find_ffmpeg(ffmpeg)
            info = build_video(cards, tmp / 'video.mp4', ff)
            copy_card(cards[0], tmp / 'cover.jpg', REEL_SIZE)
            size = (tmp / 'video.mp4').stat().st_size
            if size > MAX_VIDEO_BYTES:
                raise SyncError(f'영상 {size / 1024 / 1024:.1f}MB — 10MB 초과')
            post.update(video='video.mp4', cover='cover.jpg', frames=len(cards),
                        duration_sec=round(info['duration'], 2), video_bytes=size)
            result.update(duration=info['duration'], video_bytes=size)
        (tmp / 'post.json').write_text(json.dumps(post, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.chmod(tmp, 0o755)
        if target.exists():
            shutil.rmtree(target)
        os.replace(tmp, target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return result


# ---------------------------------------------------------------- 상위 폴더 전체

def _parse_date_arg(s):
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f'날짜는 YYYY-MM-DD 형식이어야 합니다: {s}')


def main(argv=None, posts_dir=None):
    ap = argparse.ArgumentParser(description='원본 콘텐츠 폴더 → posts/YYYY-MM-DD/ 변환')
    ap.add_argument('src', help='날짜 폴더들이 든 원본 상위 폴더')
    ap.add_argument('--from', dest='date_from', type=_parse_date_arg, help='이 날짜(포함)부터만 (YYYY-MM-DD)')
    ap.add_argument('--to', dest='date_to', type=_parse_date_arg, help='이 날짜(포함)까지만 (YYYY-MM-DD)')
    ap.add_argument('--year', type=int, default=2026, help='폴더 이름의 MM-DD 에 붙일 연도 (기본 2026)')
    ap.add_argument('--force', action='store_true', help='이미 변환된 날짜도 다시 만든다(게시된 날짜는 제외)')
    ap.add_argument('--dry', action='store_true', help='아무것도 쓰지 않고 무엇을 할지만 출력')
    ap.add_argument('--ffmpeg', help='ffmpeg 실행 파일 경로(기본: FFMPEG 환경변수 → PATH → imageio-ffmpeg)')
    args = ap.parse_args(argv)

    posts_dir = Path(posts_dir) if posts_dir else POSTS_DIR
    src = Path(args.src).expanduser()
    if not src.is_dir():
        print(f'원본 폴더가 없습니다: {src}', file=sys.stderr)
        return 2

    rows, undated = [], []
    for child in sorted(src.iterdir()):
        if not child.is_dir() or child.name.startswith('.'):
            continue
        parsed = parse_folder_name(child.name, args.year)
        if parsed is None:
            undated.append(child.name)
        else:
            rows.append((parsed, child))
    rows.sort(key=lambda r: r[0]['date'])

    errors = 0
    seen = {}
    counts = {'converted': 0, 'skipped': 0, 'published': 0, 'dry': 0, 'filtered': 0}
    for parsed, folder in rows:
        d = parsed['date']
        label = f'{d.isoformat()}  {folder.name}'
        if (args.date_from and d < args.date_from) or (args.date_to and d > args.date_to):
            counts['filtered'] += 1
            continue
        if not parsed['weekday_ok']:
            print(f'[주의] {label} — 요일 표기({parsed["weekday"]})가 실제 요일({WEEKDAYS[d.weekday()]})과 다름')
        if d in seen:
            print(f'[오류] {label} — 같은 날짜가 이미 있음({seen[d]})', file=sys.stderr)
            errors += 1
            continue
        seen[d] = folder.name
        try:
            r = convert_folder(folder, parsed, posts_dir, ffmpeg=args.ffmpeg, force=args.force, dry=args.dry)
        except SyncError as e:
            print(f'[오류] {label} — {e}', file=sys.stderr)
            errors += 1
            continue
        counts[r['status']] += 1
        if r['status'] == 'skipped':
            print(f'[건너뜀·이미 변환] {label}')
        elif r['status'] == 'published':
            print(f'[건너뜀·이미 게시됨] {label}')
        else:
            extra = ''
            if r['type'] == 'reel' and 'duration' in r:
                extra = f' · 영상 {r["duration"]:.1f}초 {r["video_bytes"] / 1024 / 1024:.2f}MB'
            tag = '변환 예정' if r['status'] == 'dry' else '변환'
            print(f'[{tag}] {label} → {r["type"]} {r["count"]}장{extra}')
            for w in r['warnings']:
                print(f'[주의] {label} — {w}')
    for name in undated:
        print(f'[건너뜀·날짜 없음] {name} — "MM-DD (요일) 종류 · 제목" 형식으로 이름을 바꾸면 변환됩니다')

    print(f'요약: 변환 {counts["converted"] + counts["dry"]} · 이미 변환 {counts["skipped"]} · 이미 게시 {counts["published"]}'
          f' · 날짜 범위 밖 {counts["filtered"]} · 날짜 없음 {len(undated)} · 오류 {errors}')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
