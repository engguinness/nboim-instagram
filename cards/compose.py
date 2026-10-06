# -*- coding: utf-8 -*-
"""앤보임 인스타 카드 합성기 (4:5, 1080×1350) — 사진이 들어간 카드.

1분선불폰 쪽 compose_photo.py 와 같은 구성이다.
  표지  : 사진 54% + 아래로 흰색으로 녹이는 그라데이션 + 흰 판(eyebrow · 큰 제목 · 부제 · 「넘겨서 보기 →」)
  본문  : 사진 42% + 흰 판(번호 · 카드 문안)
  마지막: 책 표지 + 홍보 머리글 + 서점 줄 + 「구매 링크는 프로필에」
  왼쪽 위에는 브랜드 칩(흰 판). 글자는 전부 흰 판 위에만 올린다(사진과 겹치지 않음).
문안은 kit_text.plan() (= 책 홍보 키트.html)에서만 가져온다. 여기서 새 문장을 만들지 않는다.

사진: cards/photos/<날짜>/<카드번호 NN>.png   (없으면 연한 파랑 판으로 대체하고 표시를 남긴다)
결과: cards/out/<날짜>/1080x1350_NN.jpg (품질 92) + cards/out/manifest.json

사용: python compose.py [날짜 ...]      (날짜 생략 = 전부)
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit_text  # noqa: E402

PHOTOS = HERE / 'photos'
OUT = HERE / 'out'
W, H = 1080, 1350

# 키트 색(#2f6bf0 · #1b1d21 · #7a8189)에 맞춘다
BLUE, INK, MUTED, LINE = '#2f6bf0', '#1b1d21', '#7a8189', '#e4e7ec'
SKY_TOP, SKY_BOTTOM = '#dce8ff', '#f3f7ff'

BRAND = '영포자 영어코치 곽대영'
FOOT = '영포자를 위한 마지막 영어책 · 곽대영'
STORES = '밀리의 서재 · 교보문고 · 예스24 · 알라딘'   # 키트 홍보 카드의 서점 줄 그대로
PROMO_BTN = '구매 링크는 프로필에'

# make_sns.py 와 같은 글꼴(애플 SD 산돌고딕 Neo). 없으면 다른 한글 글꼴로 대체한다.
TTC = '/System/Library/Fonts/AppleSDGothicNeo.ttc'
_IDX = {'Regular': 0, 'Medium': 2, 'SemiBold': 4, 'Bold': 6, 'Light': 8}
_FALLBACK = ['/Library/Fonts/NotoSansKR-Bold.otf', '/Library/Fonts/Pretendard-Bold.otf',
             '/System/Library/Fonts/Supplemental/AppleGothic.ttf', '/System/Library/Fonts/AppleSDGothicNeo.ttc']


def font(size, weight='Bold'):
    try:
        return ImageFont.truetype(TTC, size, index=_IDX[weight])
    except OSError:
        for p in _FALLBACK:
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


# ---------------------------------------------------------------- 글자 배치

def wrap(draw, text, f, maxw):
    """문안의 줄바꿈(\\n)은 지키고, 한 줄이 maxw 를 넘으면 어절 단위로 나눈다. 어절 하나가 넘으면 글자 단위."""
    out = []
    for line in text.split('\n'):
        cur = ''
        for word in line.split(' '):
            t = (cur + ' ' + word).strip()
            if draw.textlength(t, font=f) <= maxw:
                cur = t
                continue
            if cur:
                out.append(cur)
                cur = ''
            if draw.textlength(word, font=f) <= maxw:
                cur = word
                continue
            c = ''
            for ch in word:
                if draw.textlength(c + ch, font=f) > maxw and c:
                    out.append(c)
                    c = ch
                else:
                    c += ch
            cur = c
        out.append(cur)
    return out


def balance(draw, text, f, maxw, lines):
    """줄 수는 그대로 두고 폭을 좁혀 줄 길이를 고르게 한다(한 줄 끝에 한두 글자만 남는 것 방지).
    문안에 줄바꿈(\\n)이 있으면(저자가 직접 나눈 것) 건드리지 않는다."""
    n = len(lines)
    if n < 2 or '\n' in text:
        return lines
    best = lines
    w = maxw
    while w > maxw * 0.5:
        w -= 10
        t = wrap(draw, text, f, w)
        if len(t) != n or ' '.join(t) != text:      # 줄 수가 달라지거나 어절이 글자 단위로 쪼개지면 중단
            break
        best = t
    return best


def fit_text(draw, text, maxw, fs_max, fs_min, max_lines, max_h, weight='Bold', lh=1.28, big=None):
    """가장 큰 글자 크기를 고른다. 문안의 줄바꿈이 그대로 살아남는(=추가로 접히지 않는) 크기를 우선한다.
    big=N 이면 반대로 '글자를 키우는 쪽'을 우선한다: 줄 수가 max(문안 줄 수, N) 이하인 가장 큰 크기.
    반환: (글꼴, 줄 목록, 줄 간격 px)"""
    hard = len(text.split('\n'))
    best = None
    for fs in range(fs_max, fs_min - 1, -2):
        f = font(fs, weight)
        lines = wrap(draw, text, f, maxw)
        if big and len(lines) <= max(hard, big) and len(lines) * fs * lh <= max_h:
            return f, balance(draw, text, f, maxw, lines), round(fs * lh)
        ok = len(lines) <= max_lines and len(lines) * fs * lh <= max_h
        if ok and len(lines) == hard:
            return f, lines, round(fs * lh)
        if ok and best is None:
            best = (f, lines, round(fs * lh))
    if best:
        return best
    f = font(fs_min, weight)
    return f, wrap(draw, text, f, maxw)[:max_lines], round(fs_min * lh)


# ---------------------------------------------------------------- 사진·도형

def fit_cover(im, w, h, vbias=0.40, face=None, face_at=0.5):
    """사진을 w×h 에 꽉 차게 자른다. 가로는 중앙.
    세로: 얼굴 위치(face = focus.json 의 [x,y,w,h] 비율)가 있으면 얼굴 중심이 창 높이의 face_at 지점에 오게,
    없으면 vbias(0=맨 위 … 1=맨 아래) 지점."""
    r = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
    x = (im.width - w) // 2
    extra = im.height - h
    if face:
        cy = (face[1] + face[3] / 2) * im.height
        y = round(cy - face_at * h)
    else:
        y = round(extra * vbias)
    y = max(0, min(extra, y))
    return im.crop((x, y, x + w, y + h))


_FOCUS = None


def focus_of(path):
    """photos/focus.json 에서 이 사진의 얼굴 위치. 없으면 None."""
    global _FOCUS
    if _FOCUS is None:
        fp = PHOTOS / 'focus.json'
        _FOCUS = json.loads(fp.read_text(encoding='utf-8')) if fp.exists() else {}
    p = Path(path)
    return _FOCUS.get(f'{p.parent.name}/{p.name}')


def trim_box(im):
    """사진 가장자리의 단색 흰 테두리(생성기가 가끔 넣는 액자·여백)를 찾아 안쪽 상자를 돌려준다."""
    w, h = im.size
    def uniform_white(box):
        st = ImageStat.Stat(im.crop(box))
        return max(st.stddev) < 7 and min(st.mean) > 225
    l = t = 0
    r, b = w, h
    while l < w // 3 and uniform_white((l, 0, l + 1, h)):
        l += 1
    while w - r < w // 3 and uniform_white((r - 1, 0, r, h)):
        r -= 1
    while t < h // 3 and uniform_white((0, t, w, t + 1)):
        t += 1
    while h - b < h // 3 and uniform_white((0, b - 1, w, b)):
        b -= 1
    if (l, t, r, b) == (0, 0, w, h):
        return None
    pad = 2    # 안티앨리어싱으로 남은 연한 줄까지 조금 더 잘라낸다
    return (min(l + pad, w // 3), min(t + pad, h // 3), max(r - pad, w - w // 3), max(b - pad, h - h // 3))


def load_photo(path, w, h, vbias=0.40, face_at=0.5):
    if path and Path(path).exists():
        im = Image.open(path).convert('RGB')
        face = focus_of(path)
        box = trim_box(im)
        if box:
            l, t, r, b = box
            if face:
                W0, H0 = im.size
                face = [(face[0] * W0 - l) / (r - l), (face[1] * H0 - t) / (b - t),
                        face[2] * W0 / (r - l), face[3] * H0 / (b - t)]
            im = im.crop(box)
        return fit_cover(im, w, h, vbias, face, face_at), True
    return Image.new('RGB', (w, h), '#dce8ff'), False


def book_icon(size=54):
    """파란 둥근 네모 + 흰색 펼친 책 도형(4배로 그려 줄인다)."""
    s = size * 4
    ic = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(ic)
    d.rounded_rectangle((0, 0, s - 1, s - 1), 12 * 4, fill=BLUE)
    u = s / 54.0

    def P(pts):
        return [(x * u, y * u) for x, y in pts]
    d.polygon(P([(9, 17), (26, 20), (26, 41), (9, 38)]), fill='#ffffff')
    d.polygon(P([(28, 20), (45, 17), (45, 38), (28, 41)]), fill='#ffffff')
    d.line(P([(27, 21), (27, 42)]), fill=BLUE, width=max(2, round(1.2 * u)))
    return ic.resize((size, size), Image.LANCZOS)


def brand_chip(im):
    """왼쪽 위 흰 칩 — 브랜드. 사진 위에 올라가는 유일한 요소."""
    d0 = ImageDraw.Draw(im)
    f = font(34)
    tw = d0.textlength(BRAND, font=f)
    x0, y0, h = 60, 60, 84
    w = int(20 + 54 + 16 + tw + 28)
    # 얕은 그림자
    sh = Image.new('RGBA', (w + 40, h + 40), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((20, 24, 20 + w, 24 + h), 20, fill=(0, 0, 0, 55))
    sh = sh.filter(ImageFilter.GaussianBlur(8))
    im.paste(sh, (x0 - 20, y0 - 20), sh)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((x0, y0, x0 + w, y0 + h), 20, fill='#ffffff')
    ic = book_icon(54)
    im.paste(ic, (x0 + 20, y0 + 15), ic)
    d.text((x0 + 20 + 54 + 16, y0 + h // 2), BRAND, font=f, fill=INK, anchor='lm')


def dots(d, idx, total):
    """오른쪽 아래 작은 점 — 캐러셀 위치."""
    if total < 2:
        return
    r, gap = 6, 24
    x = W - 80 - (total - 1) * gap
    y = H - 70
    for i in range(total):
        cx = x + i * gap
        if i == idx:
            d.rounded_rectangle((cx - 12, y - r, cx + 12, y + r), r, fill=BLUE)
        else:
            d.ellipse((cx - r, y - r, cx + r, y + r), fill='#cfd5de')


def footer(d):
    d.text((80, H - 70), FOOT, font=font(28, 'Medium'), fill=MUTED, anchor='lm')


# ---------------------------------------------------------------- 카드

def cover_card(path, photo, eyebrow, title, sub, idx, total):
    ph = int(H * 0.54)
    im = Image.new('RGB', (W, H), '#ffffff')
    pic, ok = load_photo(photo, W, ph, face_at=0.40)         # 아래쪽 220px 은 흰색으로 녹으므로 얼굴을 위쪽에
    im.paste(pic, (0, 0))
    # 사진 아래쪽을 흰색으로 부드럽게 녹여 글자 판과 잇는다
    n = 220
    grad = Image.new('L', (1, n))
    for i in range(n):
        grad.putpixel((0, i), int(255 * (i / (n - 1)) ** 1.6))
    im.paste(Image.new('RGB', (W, n), '#ffffff'), (0, ph - n), grad.resize((W, n)))
    brand_chip(im)
    d = ImageDraw.Draw(im)
    y = ph - 30
    d.text((80, y), eyebrow, font=font(30, 'SemiBold'), fill=BLUE)
    y += 54
    btn_top = H - 215
    sub_h = 0
    if sub:
        sub_h = 14 + 50 * 2
    f, lines, lh = fit_text(d, title, 920, 76, 54, 4, btn_top - 40 - y - sub_h)
    for line in lines:
        d.text((80, y), line, font=f, fill=INK)
        y += lh
    if sub:
        y += 14
        sf = font(34, 'Medium')
        for line in wrap(d, sub, sf, 920)[:2]:
            d.text((80, y), line, font=sf, fill=MUTED)
            y += 50
    d.rounded_rectangle((80, btn_top, 80 + 440, btn_top + 78), 16, fill=BLUE)
    d.text((80 + 220, btn_top + 39), '넘겨서 보기  →', font=font(32), fill='#ffffff', anchor='mm')
    footer(d)
    dots(d, idx, total)
    im.save(path, 'JPEG', quality=92, optimize=True)
    return ok


def body_layout(text):
    """문안 줄 수에 따라 사진 높이 비율과 글자 크기를 정한다. 반환: (사진 비율, 글꼴, 줄 목록, 줄 간격 px)
      wrap 후 1~2줄 → 사진 56%, 글자 60→68 로 키움
      3~4줄        → 사진 50%, 글자 60
      5줄 이상      → 사진 42%, 글자를 줄여 5줄 안에(예전 규칙)"""
    d = ImageDraw.Draw(Image.new('RGB', (8, 8)))
    n60 = len(wrap(d, text, font(60), 920))
    if n60 <= 2:
        for fs in range(68, 59, -2):
            f = font(fs)
            lines = wrap(d, text, f, 920)
            if len(lines) <= 2:
                break
        return 0.56, f, balance(d, text, f, 920, lines), round(fs * 1.28)
    if n60 <= 4:
        f = font(60)
        return 0.50, f, balance(d, text, f, 920, wrap(d, text, f, 920)), round(60 * 1.28)
    ph = int(H * 0.42)
    f, lines, lh = fit_text(d, text, 920, 58, 44, 5, H - 120 - ph - 128 - 20, big=5)
    return 0.42, f, lines, lh


def body_card(path, photo, num, text, idx, total):
    ratio, f, lines, lh = body_layout(text)
    ph = int(H * ratio)
    im = Image.new('RGB', (W, H), '#ffffff')
    pic, ok = load_photo(photo, W, ph, vbias=0.30, face_at=0.50)
    im.paste(pic, (0, 0))
    brand_chip(im)
    d = ImageDraw.Draw(im)
    # 번호(+짧은 파란 선)와 문안을 한 묶음으로, 사진 아래 ~ 바닥 글씨 위 영역의 세로 가운데에 둔다
    top, bottom = ph, H - 120
    head = 128                                   # 번호 윗선 → 문안 윗선
    block = head + len(lines) * lh
    y = top + max(0, (bottom - top - block) // 2)
    d.text((80, y), f'{num:02d}', font=font(56), fill=BLUE)
    d.rounded_rectangle((80, y + 84, 80 + 56, y + 90), 3, fill=BLUE)
    ty = y + head
    for line in lines:
        d.text((80, ty), line, font=f, fill=INK)
        ty += lh
    footer(d)
    dots(d, idx, total)
    im.save(path, 'JPEG', quality=92, optimize=True)
    return ok


def promo_card(path, head, idx, total):
    im = Image.new('RGB', (W, H), '#ffffff')
    # 위쪽: 연한 하늘색 → 흰색 (표지·본문의 사진 자리에 책 표지가 온다)
    top_h = int(H * 0.56)
    g = Image.new('RGB', (1, top_h))
    a, b = (tuple(int(SKY_TOP[i:i + 2], 16) for i in (1, 3, 5)), tuple(int(SKY_BOTTOM[i:i + 2], 16) for i in (1, 3, 5)))
    for i in range(top_h):
        t = i / (top_h - 1)
        g.putpixel((0, i), tuple(round(a[k] + (b[k] - a[k]) * t) for k in range(3)))
    im.paste(g.resize((W, top_h)), (0, 0))
    n = 160
    grad = Image.new('L', (1, n))
    for i in range(n):
        grad.putpixel((0, i), int(255 * (i / (n - 1)) ** 1.6))
    im.paste(Image.new('RGB', (W, n), '#ffffff'), (0, top_h - n), grad.resize((W, n)))
    # 책 표지 (그림자 포함)
    cover = Image.open(kit_text.COVER_JPG).convert('RGB')
    bh = 560
    bw = round(cover.width * bh / cover.height)
    cover = cover.resize((bw, bh), Image.LANCZOS)
    bx, by = (W - bw) // 2, 180
    sh = Image.new('RGBA', (bw + 160, bh + 160), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((80 + 8, 80 + 22, 80 + bw + 8, 80 + bh + 22), fill=(20, 40, 90, 95))
    sh = sh.filter(ImageFilter.GaussianBlur(22))
    im.paste(sh, (bx - 80, by - 80), sh)
    im.paste(cover, (bx, by))
    ImageDraw.Draw(im).rectangle((bx, by, bx + bw - 1, by + bh - 1), outline='#cfd9ee', width=1)
    brand_chip(im)
    d = ImageDraw.Draw(im)
    y = top_h + 44
    f, lines, lh = fit_text(d, head, 920, 58, 40, 3, 240, lh=1.3)
    for line in lines:
        d.text((80, y), line, font=f, fill=BLUE)
        y += lh
    y += 18
    d.text((80, y), STORES, font=font(32, 'SemiBold'), fill=INK)
    btn_top = H - 215
    d.rounded_rectangle((80, btn_top, 80 + 520, btn_top + 78), 16, fill=BLUE)
    d.text((80 + 260, btn_top + 39), PROMO_BTN, font=font(32), fill='#ffffff', anchor='mm')
    footer(d)
    dots(d, idx, total)
    im.save(path, 'JPEG', quality=92, optimize=True)
    return True


# ---------------------------------------------------------------- 하루치

def build_day(p):
    date, cards = p['date'], p['cards']
    out_dir = OUT / date
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(cards)
    files, missing = [], []
    for i, c in enumerate(cards):
        path = out_dir / f'1080x1350_{i + 1:02d}.jpg'
        photo = PHOTOS / date / f'{i + 1:02d}.png'
        if c['kind'] == 'promo':
            promo_card(path, c['text'], i, total)
            ok = True
        elif i == 0:
            sub = p['sub']
            if sub.startswith('"') and sub.endswith('"'):
                sub = '“' + sub[1:-1] + '”'
            if sub.replace('"', '').replace('“', '').replace('”', '').strip() == c['text'].replace('\n', ' ').strip():
                sub = ''
            ok = cover_card(path, photo, p['eyebrow'], c['text'], sub, i, total)
        else:
            ok = body_card(path, photo, i + 1, c['text'], i, total)
        files.append(path.name)
        if not ok:
            missing.append(i + 1)
    # 남은 옛 파일(카드 수가 줄었을 때)을 치운다 — out/ 은 이 스크립트만 쓰는 폴더
    for old in out_dir.glob('1080x1350_*.jpg'):
        if old.name not in files:
            old.unlink()
    return {'date': date, 'folder': p['folder'].name if p['folder'] else None, 'topic': p['topic'],
            'cards': total, 'files': files, 'missing_photos': missing}


def main(argv):
    only = [a for a in argv if a.startswith('2026-')]
    OUT.mkdir(exist_ok=True)
    mf_path = OUT / 'manifest.json'
    manifest = {}
    if mf_path.exists():
        manifest = {m['date']: m for m in json.loads(mf_path.read_text(encoding='utf-8'))}
    for p in kit_text.plan():
        if only and p['date'] not in only:
            continue
        m = build_day(p)
        manifest[m['date']] = m
        print(f"{m['date']} {m['topic']:7} {m['cards']}장  사진 없음: {m['missing_photos'] or '-'}", flush=True)
    mf_path.write_text(json.dumps([manifest[k] for k in sorted(manifest)], ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main(sys.argv[1:])
