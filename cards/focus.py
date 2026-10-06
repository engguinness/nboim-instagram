# -*- coding: utf-8 -*-
"""사진마다 가장 큰 얼굴(없으면 가장 눈에 띄는 물체)의 위치를 찾아 cards/photos/focus.json 에 적는다(compose.py 가 얼굴이 안 잘리게 자를 때 쓴다).

macOS Vision(VNDetectFaceRectanglesRequest)을 Swift 도우미(facebox.swift)로 부른다. 이미 적힌 사진은 건너뛴다.
focus.json: {"2026-10-07/01.png": [x, y, w, h, "face"|"object"] | null}   (0~1 비율, 원점 = 왼쪽 위)
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHOTOS = HERE / 'photos'
SRC = HERE / 'facebox.swift'
BIN = HERE / '_bin' / 'facebox'
OUT = PHOTOS / 'focus.json'

# 자동 탐지가 엉뚱한 곳(배경 쿠션 등)을 잡은 사진은 눈으로 보고 손으로 고정한다 — 항상 이 값이 이긴다.
MANUAL = {
    '2026-10-27/06.png': [0.15, 0.45, 0.50, 0.30, 'manual'],   # 협탁 위 휴대폰·물컵(사진 아래쪽)
}


def ensure_bin():
    if BIN.exists() and BIN.stat().st_mtime >= SRC.stat().st_mtime:
        return
    BIN.parent.mkdir(exist_ok=True)
    subprocess.run(['swiftc', '-O', str(SRC), '-o', str(BIN)], check=True)


def main():
    ensure_bin()
    known = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
    todo = [p for p in sorted(PHOTOS.glob('*/*.png')) if f'{p.parent.name}/{p.name}' not in known]
    for i in range(0, len(todo), 20):
        chunk = todo[i:i + 20]
        r = subprocess.run([str(BIN)] + [str(p) for p in chunk], capture_output=True, text=True, check=True)
        for path, rects in json.loads(r.stdout).items():
            p = Path(path)
            best = max(rects, key=lambda b: b[2] * b[3]) if rects else None
            known[f'{p.parent.name}/{p.name}'] = ([round(v, 4) for v in best[:4]] + ['face' if best[4] else 'object']) if best else None
    known.update(MANUAL)
    OUT.write_text(json.dumps(known, ensure_ascii=False, indent=0, sort_keys=True), encoding='utf-8')
    faces = sum(1 for v in known.values() if v and v[4] == 'face')
    objs = sum(1 for v in known.values() if v and v[4] == 'object')
    print(f'사진 {len(known)}장 · 얼굴 {faces}장 · 물체(주목도) {objs}장 · 못 찾음 {len(known) - faces - objs}장')
    for k, v in sorted(known.items()):
        if v and v[4] == 'object':
            print('  물체 기준:', k)


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    main()
