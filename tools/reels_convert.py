#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""유튜브 쇼츠 원본(모두영어 세트1~4 v2)에서 끝의 구독 장면만 잘라 인스타 릴스(reels/<날짜>/)로 만든다.

만드는 것: reels/<날짜>/video.mp4(1080x1920·30fps·h264·aac) · cover.jpg · post.json. caption.txt 는 만들지 않는다(사람이 사실 점검 후 따로).
방식: 원본 timing.json 의 scenes 에서 type == 'subscribe' 장면을 찾아 그 앞까지 + (바로 뒤에 type == 'end' 장면이 있으면) 끝 카드만 이어 붙인다.
      자른 자리에는 25ms 오디오 페이드. 표지는 첫 장면의 큰 글자가 다 뜬 뒤 한 프레임.
ffmpeg: imageio_ffmpeg 번들(pip install imageio-ffmpeg)을 쓴다. --verify 의 ffprobe 는 PATH 의 것 또는 --ffprobe 로 지정.

사용:
    python3 tools/reels_convert.py --all                 # 26편 전부 변환(원본 기본 경로 → 이 저장소 reels/) — 아래 보호 규칙 적용
    python3 tools/reels_convert.py iKklNSsx4Bk 8YMTfAQPjGw   # 유튜브 id 로 일부만(id 도 --all 도 없으면 아무것도 안 한다)
    python3 tools/reels_convert.py --verify              # 변환 결과 점검(형식·길이·표지) — 변환 때 남긴 rows_all.json 필요
    python3 tools/reels_convert.py --src <v2 폴더> --out <reels 폴더> --work <기록·점검 이미지 폴더> --start 2026-11-19

보호: reels_hold/<날짜>(유튜브 비공개 보류분)가 있는 날짜, reels/<날짜>/published.json(이미 게시·확인 필요)이 있는 날짜는 건너뛴다.
      이미 폴더가 있는 날짜(사실 점검을 마친 video·cover·post.json)는 --overwrite 를 줘야만 덮어쓴다. --verify 는 out 에 영상이 있는 날짜만 본다.
날짜는 세트1 s1 부터 --start 로 하루씩 차례로 붙는다(세트별 순서는 IDS). 변환 뒤에는 tools/deploy_pages.sh 로 Pages 에 올린다.
"""
import argparse
import csv
import datetime
import glob
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# 기본 경로는 맥북 볼트 기준(홈 폴더 아래) — 다른 곳이면 --src·--titles 또는 환경변수 NBOIM_REELS_SRC·NBOIM_REELS_TITLES 로 준다.
_VAULT = os.path.join(os.path.expanduser('~'), 'Desktop', '옵시디언 1번')
DEFAULT_SRC = os.environ.get('NBOIM_REELS_SRC') or os.path.join(_VAULT, '선불폰 영상만들기', 'output', '모두영어-세트1', 'v2')
DEFAULT_TITLES = os.environ.get('NBOIM_REELS_TITLES') or os.path.join(_VAULT, 'NRC', '앤보임', '_자동', '유튜브_영상_목록.csv')

# 세트별 유튜브 영상 id — 순서가 곧 s1, s2, … 이고 게시 날짜 순서다
IDS = {
    1: 'iKklNSsx4Bk D8N8csQWAIs uhKl7X-oFLA OXi0XAzwayM U7hrEpptGgQ',
    2: '8YMTfAQPjGw 09-dZZ8xlh8 B73pgFW2wWg oSdkT8wR8dI cHWxF4mESwI PjiEBHc5fuM C4VDDm9ebS4',
    3: 'YxzSLRyi7Dc CKiYZhjD6qw 3lUoBF24hso b89ZPTgxNjc gfT5JDhn8mY DJ1bl3ZTWkA ETQQrJaSbMc',
    4: 'cuFYe-ZxNT8 io-5yNNh7ao wPA3OX1Y_tc BQ1J-7exT4Y 09cusO4EkkY 2dTPqAuwRoQ QKK6qQr7Nak',
}
FADE = 0.025


def set_dirs(src):
    """세트별 (납품 폴더, build 폴더, 납품 파일 패턴 — %d 는 s 번호)."""
    return {
        1: (f'{src}/납품', f'{src}/build', f'{src}/납품/모두영어_세트1_s%d_*.mp4'),
        2: (f'{src}/세트2쇼츠/납품', f'{src}/세트2쇼츠/build', f'{src}/세트2쇼츠/납품/*_s%d_*.mp4'),
        3: (f'{src}/세트3쇼츠/납품', f'{src}/세트3쇼츠/build', f'{src}/세트3쇼츠/납품/*_s%d_*.mp4'),
        4: (f'{src}/세트4쇼츠/납품', f'{src}/세트4쇼츠/build', f'{src}/세트4쇼츠/납품/*_s%d_*.mp4'),
    }


def get_ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def convert(args):
    ff = get_ffmpeg()
    dirs = set_dirs(args.src)
    out_root = Path(args.out)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    titles = {r[0].lstrip('﻿'): r[1] for r in csv.reader(open(args.titles, encoding='utf-8')) if len(r) > 1}
    d0 = datetime.date.fromisoformat(args.start)
    only = set(args.ids)
    # 이미 있는 편은 영상 ID 로 건너뛴다(날짜가 아니라) — 11-18 에 대표가 손으로 먼저 올린 2편을 빼고 날짜를 당겨서
    # IDS 순서로 매기는 날짜와 실제 폴더 날짜가 다르다. reels/·reels_hold/·reels_dropped/ 어디에든 같은 ID 가 있으면 다시 만들지 않는다.
    known = {}
    for sub_root in ('reels', 'reels_hold', 'reels_dropped'):
        for pj in (out_root.parent / sub_root).glob('*/post.json'):
            try:
                known[json.load(open(pj, encoding='utf-8'))['source']['youtube_id']] = f'{sub_root}/{pj.parent.name}'
            except (OSError, ValueError, KeyError, TypeError):
                pass
    rows, n = [], 0
    for st in (1, 2, 3, 4):
        for i, yid in enumerate(IDS[st].split(), 1):
            date = (d0 + datetime.timedelta(days=n)).isoformat()
            n += 1
            if only and yid not in only:
                continue
            if yid in known and not args.overwrite:
                print(f'건너뜀 {yid}: 이미 {known[yid]} 에 있음(덮어쓰려면 --overwrite — 그래도 날짜는 IDS 순서 기준이니 확인)', flush=True)
                continue
            out_dir = out_root / date
            if (out_root.parent / 'reels_hold' / date).exists():
                print(f'건너뜀 {date} {yid}: reels_hold/{date} 가 있음(유튜브 비공개 보류분)', flush=True)
                continue
            if (out_dir / 'published.json').exists():
                print(f'건너뜀 {date} {yid}: published.json 이 있음(이미 게시했거나 확인 필요)', flush=True)
                continue
            if out_dir.exists() and not args.overwrite:
                print(f'건너뜀 {date} {yid}: {out_dir} 가 이미 있음(덮어쓰려면 --overwrite)', flush=True)
                continue
            src = glob.glob(dirs[st][2] % i)
            assert len(src) == 1, (st, i, src)
            src = src[0]
            t = json.load(open(f'{dirs[st][1]}/s{i}/timing.json'))
            sc = t['scenes']
            sub = [s for s in sc if s['type'] == 'subscribe']
            assert len(sub) == 1, (st, i, 'subscribe 장면이 하나가 아님')
            sub = sub[0]
            idx = sc.index(sub)
            end = sc[idx + 1] if idx + 1 < len(sc) and sc[idx + 1]['type'] == 'end' else None
            cf = round(sub['start'] * 30)            # 자르는 프레임(30fps)
            cfs = cf / 30
            ct = round(end['start'] * 30) / 30 if end else None
            # 잘린 구간에 남는 본 말이 있는지(경고) — 자막·효과 줄(S·E 로 시작)은 제외
            warn = [k for k, v in t['lines'].items()
                    if k.split('-')[1][0] not in 'SE' and v['end'] > cfs + 0.02 and v['start'] < (ct or 1e9)]
            od = out_root / date
            od.mkdir(parents=True, exist_ok=True)
            if end:
                vf = (f'[0:v]trim=start_frame=0:end_frame={cf},setpts=PTS-STARTPTS[v1];'
                      f'[0:v]trim=start={ct:.5f},setpts=PTS-STARTPTS[v2];[v1][v2]concat=n=2:v=1:a=0[v];')
                af = (f'[0:a]atrim=0:{cfs:.5f},asetpts=PTS-STARTPTS,afade=t=out:st={cfs - FADE:.5f}:d={FADE}[a1];'
                      f'[0:a]atrim=start={ct:.5f},asetpts=PTS-STARTPTS,afade=t=in:st=0:d={FADE}[a2];'
                      f'[a1][a2]concat=n=2:v=0:a=1[a]')
            else:
                vf = f'[0:v]trim=start_frame=0:end_frame={cf},setpts=PTS-STARTPTS[v];'
                af = f'[0:a]atrim=0:{cfs:.5f},asetpts=PTS-STARTPTS,afade=t=out:st={cfs - FADE:.5f}:d={FADE}[a]'
            subprocess.run([ff, '-v', 'error', '-y', '-i', src, '-filter_complex', vf + af, '-map', '[v]', '-map', '[a]',
                            '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'medium',
                            '-s', '1080x1920', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart',
                            str(od / 'video.mp4')], check=True)
            # 표지: 첫 장면의 큰 글자가 다 뜬 뒤 한 프레임
            s1 = sc[0]
            bigs = [b['t_abs'] for b in t['scene_big'].get('s01', [])]
            tc = min(max(bigs + [0.3]) + 0.5, s1['end'] - 0.3)
            subprocess.run([ff, '-v', 'error', '-y', '-ss', f'{tc:.3f}', '-i', src, '-frames:v', '1', '-q:v', '2',
                            '-vf', 'scale=1080:1920', str(od / 'cover.jpg')], check=True)
            post = {'date': date, 'type': 'reel',
                    'source': {'youtube_id': yid, 'set': st, 's': i, 'title': titles.get(yid, '')},
                    'video': 'video.mp4', 'cover': 'cover.jpg', 'caption': 'caption.txt'}
            (od / 'post.json').write_text(json.dumps(post, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            row = dict(date=date, id=yid, set=st, s=i, orig_s=i, new_s=i, cut_from=cfs, cut_to=ct,
                       orig_dur=t['total'], cover_t=round(tc, 2), warn=warn)
            rows.append(row)
            print(row, flush=True)
    (work / f'rows_{"part" if only else "all"}.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')


def verify(args):
    ff = get_ffmpeg()
    work = Path(args.work)
    out_root = Path(args.out)
    (work / 'check').mkdir(parents=True, exist_ok=True)
    rows = json.load(open(work / 'rows_all.json'))
    missing = [r['date'] for r in rows if not (out_root / r['date'] / 'video.mp4').exists()]
    if missing:
        print('영상이 없어 점검에서 뺌:', ', '.join(missing))
    rows = [r for r in rows if r['date'] not in missing]

    def probe(p):
        o = subprocess.check_output([args.ffprobe, '-v', 'error', '-show_entries',
                                     'format=duration,size:stream=codec_name,codec_type,width,height,pix_fmt,r_frame_rate,sample_rate',
                                     '-of', 'json', str(p)])
        return json.loads(o)

    def frame(p, t, name):
        subprocess.run([ff, '-v', 'error', '-y', '-ss', f'{max(t, 0):.3f}', '-i', str(p), '-frames:v', '1',
                        '-vf', 'scale=270:-1,format=yuvj420p', str(work / 'check' / name)], check=True)

    res = []
    for r in rows:
        p = out_root / r['date'] / 'video.mp4'
        j = probe(p)
        v = [s for s in j['streams'] if s['codec_type'] == 'video'][0]
        a = [s for s in j['streams'] if s['codec_type'] == 'audio']
        dur = float(j['format']['duration'])
        mb = int(j['format']['size']) / 1e6
        exp = r['cut_from'] + ((r['orig_dur'] - r['cut_to']) if r['cut_to'] else 0)
        ok = (v['codec_name'] == 'h264' and v['pix_fmt'] == 'yuv420p' and (v['width'], v['height']) == (1080, 1920)
              and v['r_frame_rate'] == '30/1' and len(a) == 1 and a[0]['codec_name'] == 'aac'
              and abs(dur - exp) < 0.2 and (out_root / r['date'] / 'cover.jpg').exists())
        frame(p, dur - 3.0, f'{r["id"]}_e3.jpg')                # 끝 3초 전·끝 직전 프레임
        frame(p, dur - 0.1, f'{r["id"]}_e0.jpg')
        seams = (('seamA', r['cut_from'] - 0.05), ('seamB', r['cut_from'] + 0.05)) if r['cut_to'] else (('seamA', r['cut_from'] - 0.05),)
        for k, t in seams:                                      # 이어 붙인 자리 앞뒤
            frame(p, t, f'{r["id"]}_{k}.jpg')
        res.append(dict(date=r['date'], id=r['id'], set=r['set'], s=r['s'], cut_from=round(r['cut_from'], 3),
                        cut_to=(round(r['cut_to'], 3) if r['cut_to'] else None), orig_dur=r['orig_dur'],
                        new_dur=round(dur, 3), size_mb=round(mb, 2), has_end=bool(r['cut_to']), warn=r['warn'], ok=ok))
        print(res[-1])
    (work / 'video_table.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    return 0 if all(x['ok'] for x in res) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description='유튜브 쇼츠 원본 → 인스타 릴스(끝 구독 장면 제거)')
    ap.add_argument('ids', nargs='*', help='유튜브 영상 id(비우면 --all 이 있어야 전부)')
    ap.add_argument('--src', default=DEFAULT_SRC, help='모두영어 세트1 v2 폴더(납품·build·세트2~4쇼츠가 있는 곳)')
    ap.add_argument('--out', default=str(REPO / 'reels'), help='릴스 폴더(기본: 이 저장소 reels/)')
    ap.add_argument('--titles', default=DEFAULT_TITLES, help='유튜브_영상_목록.csv(id,제목)')
    ap.add_argument('--work', default=os.path.join(tempfile.gettempdir(), 'nboim_reels'), help='변환 기록·점검 이미지를 둘 폴더')
    ap.add_argument('--start', default='2026-11-19', help='첫 편(세트1 s1)의 게시 날짜')
    ap.add_argument('--ffprobe', default='ffprobe', help='--verify 용 ffprobe 경로')
    ap.add_argument('--all', action='store_true', help='id 없이 26편 전부 변환(보호 규칙은 그대로)')
    ap.add_argument('--overwrite', action='store_true', help='이미 있는 reels/<날짜> 폴더도 덮어씀(사실 점검을 마친 파일이 바뀐다)')
    ap.add_argument('--verify', action='store_true', help='변환하지 않고 결과 점검')
    args = ap.parse_args(argv)
    if args.verify:
        return verify(args)
    if not args.ids and not args.all:
        print('변환할 유튜브 id 를 적거나 전부 하려면 --all 을 주세요(아무것도 하지 않음).', file=sys.stderr)
        return 2
    convert(args)
    return 0


if __name__ == '__main__':
    sys.exit(main())
