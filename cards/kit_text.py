# -*- coding: utf-8 -*-
"""책 홍보 키트.html 의 데이터 객체 D 를 꺼내, 키트의 buildCards() 와 같은 규칙으로
주제별 카드 문안 목록을 만든다. (문안 정본은 키트 HTML — 여기서 새 문장을 만들지 않는다.)

카드 = {'text': 문안(줄바꿈 유지), 'kind': 'hook' | 'body' | 'promo'}
"""
import json
import re
from pathlib import Path

KIT = Path('/Users/gwagdaeyeong/Desktop/옵시디언 1번/NRC/앤보임/책 출판원고/책 홍보 키트.html')
COVER_JPG = Path('/Users/gwagdaeyeong/Desktop/옵시디언 1번/NRC/앤보임/책 출판원고/전자책 표지 (1600x2400).jpg')

FILL = ['하루 한 줄이라도 눈으로 보고\n입으로 따라 읽어보세요.',
        '쉴 땐 쉬되, 끊지는 마세요.',
        '비교해야 할 대상은 딱 하나,\n어제의 나입니다.']


def load_D():
    for line in KIT.read_text(encoding='utf-8').split('\n'):
        if line.startswith('const D={'):
            s = line[line.index('{'):line.rindex('}') + 1]
            return json.loads(s)
    raise RuntimeError('키트 HTML 에서 const D 를 찾지 못함')


def split_sent(t):
    return re.split(r'(?<=[.!?])\s+', t or '')


def build_cards(D, topic):
    """topic: 'r<i>' (완성본) | 's<i>' (절) | 'c<i>' (엄선 문장). 키트 buildCards() 와 동일."""
    kind, idx = topic[0], int(topic[1:])
    L, seen = [], set()

    def push(t, k='body'):
        t = (t or '').strip()
        if len(t) < 8:
            return
        key = re.sub(r'\s', '', t)
        if key in seen:
            return
        seen.add(key)
        L.append({'text': t, 'kind': k})

    if kind == 'r':
        rd = D['ready'][idx]
        push(rd['card'], 'hook')
        for x in rd['reels']:
            push(x[1])
    elif kind == 's':
        s = D['secs'][idx]
        push(s['hook'], 'hook')
        for c in s.get('cards') or []:
            push(c['raw'])
        for t in [p for p in (s.get('points') or []) if p]:
            push(t)
        for b in s.get('body') or []:
            for t in split_sent(b):
                if 14 <= len(t) <= 64:
                    push(t)
        if len(L) < 7:
            for c in s.get('cards') or []:
                push(c['wrapped'])
            for b in s.get('body') or []:
                for t in split_sent(b):
                    if 9 <= len(t) <= 88:
                        push(t)
            if len(L) < 7:
                push(s['title'], 'body')
            for t in FILL:
                if len(L) < 7:
                    push(t)
        del L[7:]
    else:
        push(D['curated'][idx], 'hook')
    L.append({'text': D['phead'], 'kind': 'promo'})
    return L


def ready_title(D, i):
    return D['ready'][i]['title'].strip('"“”')


def find_ready(D, title):
    """폴더 이름의 제목과 가장 잘 맞는 D.ready 인덱스. 못 찾으면 None."""
    norm = lambda s: re.sub(r'[\s"“”\'’‘?!.,~·\-]', '', s)
    t = norm(title)
    hits = [i for i, r in enumerate(D['ready']) if norm(r['title']) == t]
    if hits:
        return hits[0]
    hits = [i for i, r in enumerate(D['ready']) if t and (t in norm(r['title']) or norm(r['title']) in t)]
    return hits[0] if len(hits) == 1 else None


if __name__ == '__main__':
    D = load_D()
    print('ready', len(D['ready']), 'curated', len(D['curated']), 'secs', len(D['secs']))
    for i, r in enumerate(D['ready']):
        cs = build_cards(D, f'r{i}')
        print(f'r{i:<2} {len(cs)}장  [{r["ch"]}] {r["title"]}')
    for i, c in enumerate(D['curated']):
        print(f'c{i:<2}', c.replace('\n', ' / '))


# ---------------------------------------------------------------- 날짜별 주제 (2026-10-06 대표 지시: 10-07 ~ 10-31)

SRC_ROOT = Path('/Users/gwagdaeyeong/Desktop/옵시디언 1번/NRC/앤보임/책 출판원고/판매 실행 자료/인스타 10월 게시물')

# 날짜 → 키트 주제. 'r<i>' = D.ready, 'c<i>' = D.curated, None = 키트에 없는 문안(CUSTOM 참조)
TOPIC_BY_DATE = {
    '2026-10-07': 'r24', '2026-10-09': 'r8', '2026-10-10': 'c0', '2026-10-12': 'r4',
    '2026-10-13': 'r9', '2026-10-14': 'r20', '2026-10-16': 'r21', '2026-10-17': None,
    '2026-10-19': 'r5', '2026-10-20': 'r10', '2026-10-21': 'r18', '2026-10-23': 'r23',
    '2026-10-24': 'r25', '2026-10-26': 'r7', '2026-10-27': 'r12', '2026-10-28': 'r19',
    '2026-10-30': 'r22', '2026-10-31': None,
}

# 키트 HTML 에 없는 책안내 두 편: 폴더에 이미 들어 있던 키트 카드(1080x1350_NN.jpg) 글자를 그대로 옮긴 것.
# 마지막 promo 는 키트 공통 머리글(D.phead).
CUSTOM = {
    '2026-10-17': ['밀리의 서재로 읽으셨나요?\n한 줄만 남겨주세요.',
                   '좋았던 문장 하나면\n충분합니다.',
                   '그 한 줄이\n다음 영포자에게\n이 책을 보여줍니다.'],
    '2026-10-31': ['줄 치며 읽고 싶다면,\n종이책으로.',
                   '30일 체크리스트는\n직접 체크하시라고\n만들었습니다.',
                   '교보문고 · 예스24 · 알라딘\n주문 후 1주 정도 걸려요.'],
}


def find_folder(date_iso):
    """'2026-10-07' → SRC_ROOT 안의 '10-07 (수) …' 폴더 경로. 없으면 None."""
    prefix = date_iso[5:] + ' '
    for p in sorted(SRC_ROOT.iterdir()):
        if p.is_dir() and p.name.startswith(prefix):
            return p
    return None


def plan(D=None):
    """날짜별 계획 목록. [{'date','folder'(Path),'topic','eyebrow','sub','cards':[{text,kind}]}]
    eyebrow: 완성본 주제는 D.ready[i].ch(부 제목), 그 외는 책 제목(D.book). sub: 완성본 주제의 질문형 제목."""
    D = D or load_D()
    out = []
    for date, topic in TOPIC_BY_DATE.items():
        folder = find_folder(date)
        if topic is None:
            cards = [{'text': t, 'kind': 'hook' if i == 0 else 'body'} for i, t in enumerate(CUSTOM[date])]
            cards.append({'text': D['phead'], 'kind': 'promo'})
            eyebrow, sub = D['book'], ''
        else:
            cards = build_cards(D, topic)
            if topic[0] == 'r':
                rd = D['ready'][int(topic[1:])]
                eyebrow, sub = rd['ch'], rd['title'].strip()
            else:
                eyebrow, sub = D['book'], ''
        out.append({'date': date, 'folder': folder, 'topic': topic or 'custom',
                    'eyebrow': eyebrow, 'sub': sub, 'cards': cards})
    return out
