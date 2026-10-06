# -*- coding: utf-8 -*-
"""cards/out 의 새 카드(사진형)를 원본 날짜 폴더에 넣고, posts/ 를 다시 만든다.

순서
  1. 날짜마다 점검: 새 카드 장수 == 원본 폴더의 1080x1350_NN.jpg 장수, 사진 빠진 카드 없음.
     하나라도 어긋나면 그 날짜는 건드리지 않고 이유를 보고한다.
  2. 점검을 통과한 날짜만: 원본 1080x1350_NN.jpg 를
        /Users/gwagdaeyeong/Desktop/옵시디언 1번/NRC/앤텔레콤/_보관/앤보임카드_키트원본_20261006/<폴더명>/
     로 백업(이미 백업돼 있으면 덮어쓰지 않음 = 처음 원본이 보존됨)한 뒤 새 카드로 바꿔 넣는다.
  3. 원본 폴더의 다른 파일(1080x1920_*, 4x5_*, kit4x5_*, 3_*, 캡션)은 건드리지 않는다.
  4. sync_content.py "<원본 상위 폴더>" --from 2026-10-07 --force 로 posts/ 갱신, pytest 로 확인.

사용: python apply.py [--dry] [--no-sync] [날짜 ...]
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit_text  # noqa: E402

REPO = HERE.parent
OUT = HERE / 'out'
PHOTOS = HERE / 'photos'
PY = Path.home() / 'Apps/_venvs/media/bin/python'
BACKUP_ROOT = Path('/Users/gwagdaeyeong/Desktop/옵시디언 1번/NRC/앤텔레콤/_보관/앤보임카드_키트원본_20261006')


def check_day(p):
    """통과하면 (True, 새 카드 경로 목록), 아니면 (False, 이유)."""
    date, folder = p['date'], p['folder']
    if folder is None:
        return False, '원본 날짜 폴더를 찾지 못함'
    old = sorted(folder.glob('1080x1350_*.jpg'))
    new = sorted((OUT / date).glob('1080x1350_*.jpg')) if (OUT / date).is_dir() else []
    if len(new) != len(p['cards']):
        return False, f'새 카드 {len(new)}장 ≠ 문안 {len(p["cards"])}장 (compose.py 를 먼저 실행)'
    if len(new) != len(old):
        return False, f'새 카드 {len(new)}장 ≠ 원본 폴더 {len(old)}장'
    miss = [i for i, c in enumerate(p['cards'], 1) if c['kind'] != 'promo' and not (PHOTOS / date / f'{i:02d}.png').exists()]
    if miss:
        return False, f'사진 없는 카드 {miss}'
    mf = OUT / 'manifest.json'
    if mf.exists():
        m = {x['date']: x for x in json.loads(mf.read_text(encoding='utf-8'))}.get(date)
        if m and m.get('missing_photos'):
            return False, f'합성 때 사진이 빠진 카드 {m["missing_photos"]} (compose.py 다시 실행)'
    return True, new


def main(argv):
    dry = '--dry' in argv
    no_sync = '--no-sync' in argv
    only = [a for a in argv if a.startswith('2026-')]
    applied, skipped = [], []
    for p in kit_text.plan():
        if only and p['date'] not in only:
            continue
        ok, res = check_day(p)
        if not ok:
            skipped.append((p['date'], res))
            print(f"건너뜀 {p['date']}: {res}")
            continue
        folder = p['folder']
        bdir = BACKUP_ROOT / folder.name
        print(f"{'(dry) ' if dry else ''}적용 {p['date']} {len(res)}장  ← 백업 {bdir.name}")
        if not dry:
            bdir.mkdir(parents=True, exist_ok=True)
            for old in sorted(folder.glob('1080x1350_*.jpg')):
                dst = bdir / old.name
                if not dst.exists():
                    shutil.copy2(old, dst)
            for new in res:
                shutil.copyfile(new, folder / new.name)
        applied.append(p['date'])
    print(f'\n적용 {len(applied)}일 · 건너뜀 {len(skipped)}일')
    for d, why in skipped:
        print(f'  - {d}: {why}')
    if dry or no_sync or not applied:
        return
    print('\n== sync_content ==')
    r = subprocess.run([str(PY), '-W', 'ignore', str(REPO / 'sync_content.py'), str(kit_text.SRC_ROOT),
                        '--from', '2026-10-07', '--force'], cwd=REPO)
    if r.returncode != 0:
        sys.exit(r.returncode)
    print('\n== pytest ==')
    r = subprocess.run([str(PY), '-W', 'ignore', '-m', 'pytest', '-q'], cwd=REPO)
    sys.exit(r.returncode)


if __name__ == '__main__':
    main(sys.argv[1:])
