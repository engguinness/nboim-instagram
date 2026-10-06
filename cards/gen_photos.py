# -*- coding: utf-8 -*-
"""앤보임 10월 인스타 카드용 사진 생성.

cards/photos/<YYYY-MM-DD>/<NN>.png  (NN = 카드 번호 01.., promo 카드는 책 표지를 쓰므로 만들지 않는다)
- 이미 있는 파일은 건너뛴다(같은 사진을 두 번 만들지 않음 = 돈이 한 번만 든다).
- 실패해도 멈추지 않고 cards/photos/FAILED.json 에 목록을 남긴다. 다시 실행하면 실패한 것만 재시도한다.
- 프롬프트 전문은 cards/prompts.json 에 저장한다.
- 생성기는 1분선불폰 쪽 imagen.py(Vertex gemini-2.5-flash-image)를 읽기만 해서 쓴다.
  자격 증명은 그 파일의 _creds() 가 읽는 경로 그대로다(내용은 출력하지 않는다).
- 사진은 인물 얼굴을 과하게 클로즈업하지 않고, 글자·로고가 없는 한국 성인 영어 학습 장면으로 한다.
  초등학생 등 미성년자는 그리지 않는다(문안에 나와도 빈 교실 같은 소품·성인 장면으로 대체).

사용: python gen_photos.py [날짜 ...] [--dry] [--workers N]
"""
import importlib.util
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit_text  # noqa: E402

IMAGEN_PATH = Path('/Users/gwagdaeyeong/Desktop/1분선불폰-site/_tools/sns/imagen.py')
PHOTOS = HERE / 'photos'
PROMPTS_JSON = HERE / 'prompts.json'
FAILED_JSON = PHOTOS / 'FAILED.json'

BASE = ("Photorealistic editorial photograph, Korean adult English learner lifestyle, warm natural daylight, "
        "soft shallow depth of field, calm encouraging mood. Full-bleed photo filling the entire vertical frame "
        "edge to edge with real scene content, no borders, no letterboxing, no blank bars, no collage. "
        "The main subject sits near the vertical middle of the frame, shot from a medium distance with the "
        "surroundings visible above and below the subject. "
        "Any person is a Korean adult, face visible but never an extreme close-up. "
        "No text anywhere, no logos, no brand names, nothing readable on notebooks, books, screens or signs "
        "(pages blank or blurred, screens turned away or off). ")

BASE_OBJ = ("Photorealistic editorial photograph, warm natural light, soft shallow depth of field, calm mood. "
            "Full-bleed photo filling the entire vertical frame edge to edge with real scene content, no borders, "
            "no letterboxing, no collage. The subject sits near the vertical middle of the frame. "
            "No people anywhere in the picture. No text anywhere, no logos, no brand names, nothing readable. ")
OBJ = 'OBJ:'   # 장면 설명이 이 접두어로 시작하면 사람이 없는 장면 — BASE 대신 BASE_OBJ 를 쓴다

FULLBLEED = ' Single full-bleed photograph filling the canvas edge to edge, no white border, no frame, no margin, not a collage.'

# 날짜 → 카드 번호 순서(promo 제외)의 장면 설명. 문안의 상황에 맞춘다.
SCENES = {
 '2026-10-07': [  # 하루에 딱 이 다섯 가지만 하세요
  "A Korean woman in her 30s at a tidy home desk in warm morning light with a laptop, a notebook and a coffee mug, calm and determined",
  "Overhead view of a wooden desk with five neat items in a row: a blank notebook, a pencil, earphones, a coffee cup and a smartphone with the screen off",
  "A Korean man in his 30s wearing a headset, smiling and talking on a video call at a cafe table, laptop screen facing away",
  "A hand writing a short note in a spiral notebook with a pen at a cafe table, page lines blurred and unreadable",
  "A Korean woman typing on a laptop at a desk in the evening with a warm lamp, screen not visible, focused",
  "A Korean man wearing earphones, lips softly moving as if repeating a phrase, standing by a bright window",
  "A hand holding a yellow highlighter over a notebook page full of blurred scribbles, blank sticky notes at the edge",
  "A Korean woman stretching her arms with a satisfied smile after studying at her desk, a cup of tea, golden late-afternoon window light",
 ],
 '2026-10-09': [  # 나이는 정말 숫자
  "A Korean man in his 40s studying at a cafe table with a notebook and earphones, relaxed smile, warm window light",
  "A Korean woman in her 50s sitting at a kitchen table looking at a laptop with a hesitant but curious expression",
  "A single student desk with a pencil and a blank notebook in an empty bright classroom, sunlight through the window, no people",
  "A Korean man in his 40s resting his chin on his hand looking thoughtfully at a notebook at a desk, soft light",
  "A Korean woman in her 30s smiling and shaking her head lightly in amusement while holding a coffee at a cafe",
  "A Korean man in his 40s looking up from a book at a library table with a warm knowing smile",
  "A Korean woman in her 50s walking in a park in morning light with earphones in, carrying a notebook, smiling",
 ],
 '2026-10-10': [  # 영어를 못하는 게 아닙니다
  "A Korean adult sitting at a desk at dawn looking out of the window with a calm determined expression, an open notebook and a closed book with a plain blank cover on the desk",
 ],
 '2026-10-12': [  # 단어를 외워도 자꾸 까먹어요
  "A small stack of blank white index flash cards on a wooden desk next to a coffee cup, one card in sharp focus, no writing",
  "A Korean woman looking up at the ceiling thoughtfully with a pen at her lips, a stack of blank flash cards on the desk",
  "A stack of blank flash cards with a rubber band lying untouched at the corner of a desk beside a closed laptop, soft afternoon light",
  "A hand holding a red apple above an open blank notebook on a wooden table, bright and simple",
  "A Korean man at a cafe table listening with his eyes looking upward in thought, another person visible only as a blurred shoulder in the foreground",
  "A Korean woman hesitating in the middle of a conversation, hand near her chin, bright cafe background",
  "Three small neat piles of blank flash cards lined up in a row on a desk, a hand placing the last card, shallow focus",
 ],
 '2026-10-13': [  # 발음이 안 좋아서 부끄러워요
  "A Korean woman wearing a headset speaking confidently to her laptop in a bright room, smiling",
  "A Korean man covering his mouth with a hand, laughing shyly at a cafe table",
  "A professional microphone on a stand in a softly lit interview room, shallow depth of field, no logos",
  "A Korean man in profile looking at a smartphone with the screen turned away, slightly skeptical expression, cafe",
  "A Korean woman and a foreign friend smiling and nodding at each other across a cafe table, friendly conversation, medium-wide",
  "A Korean woman wearing over-ear headphones listening thoughtfully by a window, eyes lowered, soft light",
  "A Korean man walking out of an office building into sunlight with earphones around his neck, confident, medium-wide",
 ],
 '2026-10-14': [  # 길거리에 떨어진 500원을 주우세요
  "A bright wall covered with a neat grid of blank yellow sticky notes, a hand placing one more note, shallow focus",
  "A single silver coin lying on a clean sunlit sidewalk seen from above, no readable markings",
  "A hand picking up a small silver coin from the pavement in morning light, shallow focus",
  "A Korean man walking briskly down a city street in sunlight, one earbud in, holding a phone with the screen away from camera",
  "A Korean woman at a cafe looking at her phone with a gentle sheepish smile, screen not visible",
  "A glass jar filled with folded small blank paper slips on a wooden desk in warm light, a pen beside it",
  "A Korean woman at a bus stop glancing through a small notebook for a few minutes, relaxed, city morning",
 ],
 '2026-10-16': [  # 106킬로그램에서 달리기를 시작
  "A Korean man seen from behind running along a river path at dawn, golden light, medium-wide shot, ordinary build",
  OBJ + "Close-up of a pair of worn gray running shoes with laces tied, standing on a stone step at dawn in soft warm light, shallow focus",
  "A Korean man stopped on a riverside path with hands on his knees catching his breath, seen from the side at dawn, face not shown close",
  "A Korean man jogging slowly along a park path in morning mist, tired but smiling, side view",
  "A Korean man tying his shoelaces on a park bench at dawn, determined, medium shot",
  "A Korean man running strongly across a river bridge at sunrise, side view, dynamic, warm light",
  OBJ + "A quiet riverside walking path at golden sunrise with mist over the water, a long empty path stretching into the distance, outdoors only",
 ],
 '2026-10-17': [  # 밀리 한줄평 부탁
  "A Korean woman reading on a tablet e-reader on a cozy sofa, screen facing away, warm evening lamp light",
  "A hand holding a pencil over an open paperback book whose pages show only blurred unreadable lines, cozy light",
  "A Korean man in a cafe passing a paperback book with a plain blank cover to a friend across the table, warm smiles",
 ],
 '2026-10-19': [  # 아무리 들어도 안 들려요
  "A Korean woman wearing earphones with eyes closed and a slight frown in a busy subway car, blurred crowd around",
  "A Korean man at a desk wearing over-ear headphones with a puzzled expression, one hand on an ear",
  "A tall stack of thick books beside a small notebook on a desk, shot from a low angle, soft light",
  "A cozy living room with a television glowing with blurred abstract light, a Korean man on a sofa holding a remote with a confused expression",
  "Two adults chatting quickly at a cafe table in the blurred foreground while a Korean woman in focus in the background listens with a lost look",
  "An open picture book with large colorful illustrations and no letters on a table beside a cup of tea, soft window light",
  "Over-ear headphones resting on a desk by a window in quiet morning light, calm, no people",
 ],
 '2026-10-20': [  # 외국인 앞에서 머리가 하얘져요
  "A Korean woman at a cafe looking nervous while a foreign friend smiles warmly at her, seen from the side, medium-wide",
  "A Korean man frozen with wide eyes at a table in washed-out soft white light, side view, blank expression",
  "A Korean woman rehearsing a speech in front of a mirror at home, seen from behind, bright room",
  "An empty classroom with rows of desks in soft morning light, first-day feeling, a blank blackboard, no people" + FULLBLEED,
  "The same kind of classroom in warm golden late-afternoon light, desks and a window with a sunset, nostalgic, no people",
  "Two adults laughing together in a small bright classroom-style room, seen from behind, relaxed",
  "A Korean woman walking through a bright open doorway out into sunlight, medium-wide shot, hopeful" + FULLBLEED,
 ],
 '2026-10-21': [  # 엉망진창으로 대화하세요
  "A Korean woman and a foreign tutor in animated conversation at a cafe table, laughing, hands gesturing, medium-wide",
  "A Korean man gesturing with both hands while talking and laughing in a casual setting, cafe, warm light",
  "A Korean woman mid-sentence looking upward searching for words with one finger raised, at a cafe table",
  "A foreign friend smiling and nodding encouragingly across a table, seen over the shoulder of a Korean woman",
  "Two friends talking over plates of food at a restaurant table with warm lights, lively conversation, medium-wide",
  "Two pairs of hands completing a small wooden puzzle together on a table in warm light",
  "A Korean man writing in a pocket notebook at a cafe after a conversation, smiling, a coffee beside him",
 ],
 '2026-10-23': [  # 시간이 없다면 지금은 시작하지 마세요
  "A tidy empty desk in calm early morning light with an open notebook and a cup of tea, one quiet hour ahead, no people",
  "A tired Korean office worker rubbing his eyes late at night in a dim office, blurred city lights through the window",
  "Rows of English study books on a bookstore shelf, shallow depth of field, spines blank and unreadable",
  "A Korean woman sitting reluctantly at a desk with a heavy expression, staring at an open notebook, gray light",
  "A closed notebook with a pen on top and an untouched cold cup of coffee on a desk in dim light, no people",
  "A Korean man relaxed on a sofa watching a tablet with a light smile in evening lamp light, screen not visible",
  "A Korean woman opening a notebook at a calm morning desk with sunlight streaming in, a fresh start feeling",
 ],
 '2026-10-24': [  # 한 달 만에 레벨 2에서 레벨 4로
  "A small green seedling in a pot on a desk by a window in soft sunlight with a notebook beside it",
  "A Korean woman climbing a few wide stone steps in a sunny park, seen from behind, medium-wide",
  "A Korean man wearing a headset speaking slowly into a laptop with a hand on his chin, hesitant, home desk",
  "A Korean woman in a video call with a headset at a kitchen table with a morning coffee, calm daily routine",
  "A Korean man resting his chin in his hand looking discouraged at a desk with a laptop, greyish window light",
  "A Korean woman wearing earphones with a surprised realizing smile, looking up, soft natural light" + FULLBLEED,
  "A hiking path winding up a green hill at sunrise with one small walker, calm and wide",
 ],
 '2026-10-26': [  # 3일 하고 그만둡니다
  "A Korean man comfortably scrolling his phone on a cozy living room sofa with a closed laptop on the coffee table, screen away",
  "An abandoned desk with a notebook open to only its first few pages, a pen lying aside, afternoon light, no people",
  "A Korean woman looking kindly and thoughtfully at a notebook at a cafe window, not blaming herself" + FULLBLEED,
  "A Korean man easily ordering coffee at a neighborhood cafe counter, everything familiar, a blurred smiling barista, no readable signs",
  "A Korean traveler with a suitcase standing in a busy airport arrivals hall in a foreign city, looking around, blurred signage",
  "A kitchen with several blank sticky notes stuck on the refrigerator door and a Korean woman placing another, bright morning",
  "A hand holding a smartphone in a cafe with the thumb about to tap, screen turned away, shallow depth of field",
 ],
 '2026-10-27': [  # AI로 영어공부하는 건 어때요?
  "A Korean woman talking to her laptop at a cozy home desk, hands on the keyboard, calm face lit softly, screen not visible",
  "A Korean man with a curious head tilt, chin on hand, looking at a laptop in the evening lamp light, screen not visible",
  "A Korean woman smiling with pleasant surprise at her laptop, bright room, screen not visible",
  "A Korean woman holding up two fingers in a friendly explaining gesture at a cafe table" + FULLBLEED,
  "A hand turning a plain round dial on a speaker on a wooden desk, shallow focus, no markings",
  "A smartphone lying screen-off on a nightstand with a glass of water in morning sunlight, no people",
  "A Korean man studying at a desk with a laptop and a headset, smiling as if with a tutor, plant on the desk, warm light",
 ],
 '2026-10-28': [  # 복습은 이 타이밍에 하세요
  "A Korean woman staring blankly at the ceiling with a hand on her forehead after studying, notebook open, afternoon light",
  "Sand slipping through an open hand, macro, soft warm light",
  "Dandelion seeds blowing away in sunlight, shallow depth of field, airy",
  "A Korean man laughing at himself with a shrug at a cafe table with a notebook" + FULLBLEED,
  "A Korean woman reviewing a notebook on a morning train, focused, medium shot",
  "Three small potted seedlings in a row of increasing size on a sunny windowsill",
  "A Korean man standing and speaking aloud with a closed notebook in his hand, looking up as he recalls, by a window",
 ],
 '2026-10-30': [  # 쉴 땐 쉬되, 끊지는 마세요
  "A Korean woman resting on a sofa under a blanket with tea and a small book on her lap, cozy evening",
  "A Korean man stretching by a window on a weekend morning with a coffee, relaxed smile",
  "A Korean woman with a cold sitting at a desk with tissues and a warm drink, tired, soft grey light",
  "A Korean man with his head resting on folded arms on a desk beside an open notebook, tired",
  "An open notebook and a pen on a bedside table next to a lamp in the evening, tidy, no people",
  "A long calm trail through a forest with light filtering through the trees, empty and peaceful, outdoors only, no people, no furniture" + FULLBLEED,
  "A Korean woman in bed reading a book by a bedside lamp at night, peaceful, medium shot",
 ],
 '2026-10-31': [  # 종이책은 교보에서도
  "A Korean woman underlining a line with a pencil in a paperback book at a cafe table, pages blurred, warm light",
  "A hand ticking a checklist in a notebook with a pen, lines blank and unreadable, soft daylight",
  "A small cardboard parcel on the doorstep of an apartment in morning light, no readable labels",
 ],
}


LOCATIONS = ['us-central1', 'us-east4', 'us-east1', 'us-west1', 'europe-west4', 'global']   # 시도마다 돌려 가며 쓴다 — 리전마다 할당량이 따로다.
# (이전 설명) global 엔드포인트는 429 가 너무 잦아(2026-10-06 실측 거의 2분에 1장) 같은 모델·같은 프로젝트의 리전 엔드포인트를 쓴다


class Regional:
    """imagen.py 와 같은 모델·같은 요청 형식, 엔드포인트만 리전(us-central1). 토큰은 25분간 재사용."""

    def __init__(self, imagen):
        self.im = imagen
        self._tok = None
        self._at = 0
        self._lock = threading.Lock()
        self._n = random.randrange(len(LOCATIONS))

    def _next_location(self):
        with self._lock:
            self._n += 1
            return LOCATIONS[self._n % len(LOCATIONS)]

    def _token(self):
        with self._lock:
            if not self._tok or time.time() - self._at > 25 * 60:
                self._tok = self.im._creds()
                self._at = time.time()
            return self._tok

    def generate(self, prompt, aspect='4:5'):
        import base64
        import requests
        tok, proj = self._token()
        loc = self._next_location()
        host = 'aiplatform.googleapis.com' if loc == 'global' else f'{loc}-aiplatform.googleapis.com'
        url = (f'https://{host}/v1/projects/{proj}/locations/{loc}'
               f'/publishers/google/models/{self.im.MODEL}:generateContent')
        body = {'contents': [{'role': 'user', 'parts': [{'text': f'{prompt}\n\n{self.im.NO_TEXT}'}]}],
                'generationConfig': {'responseModalities': ['TEXT', 'IMAGE'], 'imageConfig': {'aspectRatio': aspect}}}
        r = requests.post(url, headers={'Authorization': f'Bearer {tok}'}, json=body, timeout=180)
        if r.status_code == 200:
            for part in r.json()['candidates'][0]['content']['parts']:
                if 'inlineData' in part:
                    return base64.b64decode(part['inlineData']['data'])
            raise RuntimeError('이미지 없이 응답(안전 필터 가능성): ' + r.text[:200])
        try:
            msg = r.json().get('error', {}).get('message', r.text)[:160]
        except Exception:
            msg = r.text[:160]
        raise RuntimeError(f'{r.status_code}: {msg} [{loc}]')


def load_imagen():
    spec = importlib.util.spec_from_file_location('imagen_1min', IMAGEN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def jobs(only=None):
    """[(date, 카드번호 1.., 프롬프트, 출력 경로)] — plan() 의 카드 수(promo 제외)와 SCENES 가 맞아야 한다."""
    out = []
    for p in kit_text.plan():
        date = p['date']
        if only and date not in only:
            continue
        n = sum(1 for c in p['cards'] if c['kind'] != 'promo')
        sc = SCENES[date]
        if len(sc) != n:
            raise SystemExit(f'{date}: 장면 {len(sc)}개 ≠ 사진이 필요한 카드 {n}장')
        for i, s in enumerate(sc, 1):
            out.append((date, i, (BASE_OBJ + s[len(OBJ):]) if s.startswith(OBJ) else (BASE + s), PHOTOS / date / f'{i:02d}.png'))
    return out


def save_prompts(all_jobs):
    data = {}
    for date, i, prompt, _ in all_jobs:
        data.setdefault(date, {})[f'{i:02d}'] = prompt
    PROMPTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')


def main(argv):
    dry = '--dry' in argv
    workers = 3
    if '--workers' in argv:
        workers = int(argv[argv.index('--workers') + 1])
    only = [a for a in argv if a.startswith('2026-')]
    all_jobs = jobs()
    save_prompts(all_jobs)
    todo = [j for j in jobs(only or None) if not j[3].exists()]
    print(f'전체 {len(all_jobs)}장 · 대상 {len(jobs(only or None))}장 · 만들 것 {len(todo)}장 (이미 있는 건 건너뜀)', flush=True)
    if dry or not todo:
        return
    imagen = Regional(load_imagen())   # 429 재시도는 아래에서 직접(지터 포함) 한다 — 여러 작업이 같은 박자로 부딪치지 않게
    PHOTOS.mkdir(exist_ok=True)
    lock = threading.Lock()
    claimed = set()

    def run(job):
        date, i, prompt, out = job
        with lock:                      # 같은 사진을 두 번 만들지 않는다
            if out.exists() or out in claimed:
                return None
            claimed.add(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        t = time.time()
        err = ''
        for attempt in range(1, 13):
            try:
                b = imagen.generate(prompt, aspect='4:5')
                out.write_bytes(b)
                print(f'ok  {date}/{i:02d}  {round(time.time() - t, 1)}s (시도 {attempt})', flush=True)
                time.sleep(2)
                return None
            except Exception as e:  # 전체를 멈추지 않는다
                err = str(e)
                if not err.startswith('429'):
                    break
                time.sleep(random.uniform(3, 12))
        print(f'FAIL {date}/{i:02d}: {err[:160]}', flush=True)
        return {'date': date, 'card': i, 'error': err[:200]}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(run, todo))
    failed = [r for r in results if r]
    FAILED_JSON.write_text(json.dumps(failed, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'완료: 성공 {len(todo) - len(failed)} · 실패 {len(failed)} / {len(todo)}', flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
