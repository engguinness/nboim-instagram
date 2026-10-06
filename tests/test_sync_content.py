# -*- coding: utf-8 -*-
"""sync_content.py 테스트 — 폴더 이름 파싱, 캡션 읽기, post.json 생성, 건너뛰기·--force·--from, 릴스 mp4."""
import datetime
import json
from pathlib import Path

import pytest
from PIL import Image

import sync_content as sc


# ---------------------------------------------------------------- 도우미

def make_jpg(path, size, color=(240, 230, 210)):
    Image.new('RGB', size, color).save(path, 'JPEG', quality=92)


def make_folder(src, name, n=3, kind='carousel', caption='첫 줄\n\n둘째 줄\n\n#태그1 #태그2\n', extra=True):
    d = Path(src) / name
    d.mkdir(parents=True)
    size = sc.CAROUSEL_SIZE if kind == 'carousel' else sc.REEL_SIZE
    prefix = '1080x1350' if kind == 'carousel' else '1080x1920'
    for i in range(1, n + 1):
        make_jpg(d / f'{prefix}_{i:02d}.jpg', size, (30 * i, 100, 200 - 10 * i))
    (d / sc.CAPTION_SRC).write_text(caption, encoding='utf-8')
    if extra:   # 무시돼야 하는 파일들
        make_jpg(d / '4x5_01.jpg', sc.CAROUSEL_SIZE)
        (d / '3_릴스 영상 v2.mp4').write_bytes(b'not a video')
        (d / '2_릴스 대본.txt').write_text('대본', encoding='utf-8')
    return d


def have_ffmpeg():
    try:
        sc.find_ffmpeg()
        return True
    except sc.SyncError:
        return False


needs_ffmpeg = pytest.mark.skipif(not have_ffmpeg(), reason='ffmpeg 없음')


# ---------------------------------------------------------------- 폴더 이름 파싱

def test_parse_folder_name_carousel():
    p = sc.parse_folder_name('10-07 (수) 카드뉴스 · 하루에 딱 이 다섯 가지', 2026)
    assert p['date'] == datetime.date(2026, 10, 7)
    assert p['kind'] == '카드뉴스'
    assert p['title'] == '하루에 딱 이 다섯 가지'
    assert p['weekday'] == '수' and p['weekday_ok'] is True


@pytest.mark.parametrize('name,kind,date', [
    ('10-09 (금) 릴스 · 나이가 많은데 시작해도 되나요', '릴스', (2026, 10, 9)),
    ('10-10 (토) 책안내 · 안 되는 방법으로 열심히', '책안내', (2026, 10, 10)),
    ('10-30 (금) 릴스 · 쉬어도 되는 날 지킬 한 문장', '릴스', (2026, 10, 30)),
    ('10-27 (화) 릴스 · AI로 영어공부 어때요', '릴스', (2026, 10, 27)),
    ('10-26 (월) 카드뉴스 · 3일 하고 그만둡니다', '카드뉴스', (2026, 10, 26)),
])
def test_parse_folder_name_real_names(name, kind, date):
    p = sc.parse_folder_name(name, 2026)
    assert p['kind'] == kind and p['date'] == datetime.date(*date)
    assert p['weekday_ok'] is True


def test_parse_folder_name_weekday_mismatch_flagged():
    p = sc.parse_folder_name('10-07 (목) 카드뉴스 · 요일이 틀림', 2026)    # 실제로는 수요일
    assert p['date'] == datetime.date(2026, 10, 7) and p['weekday_ok'] is False


@pytest.mark.parametrize('name', ['01 문법부터 vs 회화부터', '08 발음은 운동 자세와 같습니다', '그냥 폴더', '13-45 (월) 카드뉴스 · 없는 날짜', ''])
def test_parse_folder_name_rejects_undated(name):
    assert sc.parse_folder_name(name, 2026) is None


# ---------------------------------------------------------------- 캡션

def test_read_caption_normalizes(tmp_path):
    d = tmp_path / 'f'
    d.mkdir()
    (d / sc.CAPTION_SRC).write_bytes('﻿첫 줄\r\n\r\n둘째 줄  \r\n\r\n'.encode('utf-8'))
    assert sc.read_caption(d) == '첫 줄\n\n둘째 줄'


def test_read_caption_missing_or_empty(tmp_path):
    d = tmp_path / 'f'
    d.mkdir()
    with pytest.raises(sc.SyncError):
        sc.read_caption(d)
    (d / sc.CAPTION_SRC).write_text('  \n', encoding='utf-8')
    with pytest.raises(sc.SyncError):
        sc.read_caption(d)


def test_caption_warnings():
    assert sc.caption_warnings('짧은 글 #a #b') == []
    assert any('2200' in w for w in sc.caption_warnings('가' * 2201))
    assert any('30' in w for w in sc.caption_warnings(' '.join(f'#t{i}' for i in range(31))))


# ---------------------------------------------------------------- 카드뉴스 변환

def test_convert_carousel_creates_post_json(tmp_path):
    src, posts = tmp_path / 'src', tmp_path / 'posts'
    folder = make_folder(src, '10-07 (수) 카드뉴스 · 하루에 딱 이 다섯 가지', n=4)
    parsed = sc.parse_folder_name(folder.name)
    r = sc.convert_folder(folder, parsed, posts)
    assert r['status'] == 'converted' and r['type'] == 'carousel' and r['count'] == 4

    out = posts / '2026-10-07'
    post = json.loads((out / 'post.json').read_text(encoding='utf-8'))
    assert post['type'] == 'carousel'
    assert post['date'] == '2026-10-07'
    assert post['source'] == folder.name
    assert post['images'] == ['01.jpg', '02.jpg', '03.jpg', '04.jpg']
    assert (out / 'caption.txt').read_text(encoding='utf-8').strip() == '첫 줄\n\n둘째 줄\n\n#태그1 #태그2'
    for i in range(1, 5):   # JPEG 는 재압축 없이 그대로
        assert (out / f'{i:02d}.jpg').read_bytes() == (folder / f'1080x1350_{i:02d}.jpg').read_bytes()
    assert sorted(p.name for p in out.iterdir()) == ['01.jpg', '02.jpg', '03.jpg', '04.jpg', 'caption.txt', 'post.json']
    assert not [p for p in posts.iterdir() if p.name.startswith('.tmp-')]


def test_convert_carousel_converts_non_jpeg_and_ignores_4x5(tmp_path):
    src, posts = tmp_path / 'src', tmp_path / 'posts'
    folder = make_folder(src, '10-10 (토) 책안내 · 두 장', n=2)
    Image.new('RGB', sc.CAROUSEL_SIZE, (10, 20, 30)).save(folder / '1080x1350_02.jpg', 'PNG')   # 이름만 jpg 인 PNG
    sc.convert_folder(folder, sc.parse_folder_name(folder.name), posts)
    im = Image.open(posts / '2026-10-10' / '02.jpg')
    assert im.format == 'JPEG' and im.size == sc.CAROUSEL_SIZE


def test_convert_carousel_rejects_wrong_size_and_leaves_nothing(tmp_path):
    src, posts = tmp_path / 'src', tmp_path / 'posts'
    folder = make_folder(src, '10-12 (월) 카드뉴스 · 크기 틀림', n=3)
    make_jpg(folder / '1080x1350_02.jpg', (1080, 1920))
    with pytest.raises(sc.SyncError, match='1080x1350'):
        sc.convert_folder(folder, sc.parse_folder_name(folder.name), posts)
    assert not (posts / '2026-10-12').exists()
    assert not [p for p in posts.iterdir() if p.name.startswith('.tmp-')]


def test_convert_carousel_needs_two_to_ten_images(tmp_path):
    src, posts = tmp_path / 'src', tmp_path / 'posts'
    one = make_folder(src, '10-12 (월) 카드뉴스 · 한 장', n=1)
    with pytest.raises(sc.SyncError, match='2~10'):
        sc.convert_folder(one, sc.parse_folder_name(one.name), posts)
    eleven = make_folder(src, '10-13 (화) 카드뉴스 · 열한 장', n=11)
    with pytest.raises(sc.SyncError, match='2~10'):
        sc.convert_folder(eleven, sc.parse_folder_name(eleven.name), posts)


def test_list_cards_requires_contiguous_numbers(tmp_path):
    d = make_folder(tmp_path, 'x', n=3)
    (d / '1080x1350_02.jpg').unlink()
    with pytest.raises(sc.SyncError, match='이어지지'):
        sc.list_cards(d, sc.CAROUSEL_RE)


# ---------------------------------------------------------------- 릴스 변환 (ffmpeg 필요)

@needs_ffmpeg
def test_convert_reel_makes_mp4(tmp_path):
    src, posts = tmp_path / 'src', tmp_path / 'posts'
    folder = make_folder(src, '10-09 (금) 릴스 · 나이가 많은데 시작해도 되나요', n=2, kind='reel')
    r = sc.convert_folder(folder, sc.parse_folder_name(folder.name), posts)
    assert r['type'] == 'reel'
    out = posts / '2026-10-09'
    post = json.loads((out / 'post.json').read_text(encoding='utf-8'))
    assert post['type'] == 'reel' and post['video'] == 'video.mp4' and post['cover'] == 'cover.jpg'
    assert post['frames'] == 2
    assert post['duration_sec'] == pytest.approx(7.0, abs=0.1)
    assert post['video_bytes'] == (out / 'video.mp4').stat().st_size < sc.MAX_VIDEO_BYTES
    assert (out / 'cover.jpg').read_bytes() == (folder / '1080x1920_01.jpg').read_bytes()
    info = sc.probe_video(sc.find_ffmpeg(), out / 'video.mp4')
    assert (info['width'], info['height']) == (1080, 1920)
    assert info['codec'] == 'h264' and info['pix_fmt'] == 'yuv420p' and info['has_audio']
    assert 'tv' in info['color'] and 'bt709' in info['color']
    assert sorted(p.name for p in out.iterdir()) == ['caption.txt', 'cover.jpg', 'post.json', 'video.mp4']


def test_ffmpeg_command_matches_required_settings():
    cmd = sc.ffmpeg_command('ffmpeg', Path('/t/frame_%02d.jpg'), 28.0, Path('/t/video.mp4'))
    joined = ' '.join(cmd)
    for needle in ['-framerate 2/7', 'sine=frequency=1:sample_rate=44100', 'volume=0', 'fps=30', 'format=yuv420p',
                   '-fps_mode cfr', '-color_range tv', '-colorspace bt709', '-color_primaries bt709', '-color_trc bt709',
                   '-profile:v high', '-level 4.1', '-crf 20', '-g 30', '-keyint_min 30', '-c:a aac', '-b:a 128k',
                   '-ar 44100', '-t 28', '-movflags +faststart', 'scale=1080:1920']:
        assert needle in joined, needle


# ---------------------------------------------------------------- main (상위 폴더 전체)

def build_src(tmp_path):
    src = tmp_path / 'src'
    make_folder(src, '10-05 (월) 카드뉴스 · 지난 날', n=2)
    make_folder(src, '10-07 (수) 카드뉴스 · 하루에 딱 이 다섯 가지', n=3)
    make_folder(src, '10-10 (토) 책안내 · 안 되는 방법으로 열심히', n=2)
    make_folder(src, '01 날짜 없는 폴더', n=2)
    return src


def test_main_from_filter_undated_skip_and_rerun(tmp_path, capsys):
    src, posts = build_src(tmp_path), tmp_path / 'posts'
    rc = sc.main([str(src), '--from', '2026-10-07'], posts_dir=posts)
    out = capsys.readouterr().out
    assert rc == 0
    assert sorted(p.name for p in posts.iterdir()) == ['2026-10-07', '2026-10-10']      # 10-05 는 --from 으로 제외
    assert '날짜 없음' in out and '01 날짜 없는 폴더' in out

    before = (posts / '2026-10-07' / '01.jpg').stat().st_mtime_ns
    rc = sc.main([str(src), '--from', '2026-10-07'], posts_dir=posts)
    out = capsys.readouterr().out
    assert rc == 0 and out.count('이미 변환') >= 2
    assert (posts / '2026-10-07' / '01.jpg').stat().st_mtime_ns == before                # 건드리지 않음


def test_main_force_rebuilds_but_never_touches_published(tmp_path):
    src, posts = build_src(tmp_path), tmp_path / 'posts'
    sc.main([str(src), '--from', '2026-10-07'], posts_dir=posts)

    (posts / '2026-10-07' / 'caption.txt').write_text('손으로 고친 캡션\n', encoding='utf-8')
    (posts / '2026-10-10' / 'published.json').write_text('{"media_id": "1"}', encoding='utf-8')
    (posts / '2026-10-10' / 'caption.txt').write_text('게시된 날의 캡션\n', encoding='utf-8')

    assert sc.main([str(src), '--from', '2026-10-07', '--force'], posts_dir=posts) == 0
    assert (posts / '2026-10-07' / 'caption.txt').read_text(encoding='utf-8').startswith('첫 줄')     # 다시 만들어짐
    assert (posts / '2026-10-10' / 'caption.txt').read_text(encoding='utf-8') == '게시된 날의 캡션\n'  # 게시된 날은 그대로
    assert (posts / '2026-10-10' / 'published.json').exists()


def test_main_dry_writes_nothing(tmp_path, capsys):
    src, posts = build_src(tmp_path), tmp_path / 'posts'
    assert sc.main([str(src), '--dry'], posts_dir=posts) == 0
    assert 'carousel' in capsys.readouterr().out
    assert not posts.exists() or not any(posts.iterdir())


def test_main_duplicate_date_and_bad_folder_return_error(tmp_path, capsys):
    src, posts = tmp_path / 'src', tmp_path / 'posts'
    make_folder(src, '10-07 (수) 카드뉴스 · 첫째', n=2)
    make_folder(src, '10-07 (수) 카드뉴스 · 둘째', n=2)
    make_folder(src, '10-09 (금) 카드뉴스 · 캡션 없음', n=2)
    (src / '10-09 (금) 카드뉴스 · 캡션 없음' / sc.CAPTION_SRC).unlink()
    rc = sc.main([str(src)], posts_dir=posts)
    err = capsys.readouterr().err
    assert rc == 1
    assert '같은 날짜' in err and '캡션 파일 없음' in err
    assert (posts / '2026-10-07' / 'post.json').exists()       # 정상인 쪽은 변환됨
    assert not (posts / '2026-10-09').exists()


def test_main_missing_source_dir(tmp_path):
    assert sc.main([str(tmp_path / 'nope')], posts_dir=tmp_path / 'posts') == 2


@needs_ffmpeg
def test_main_reel_folder_via_kind_in_name(tmp_path, capsys):
    src, posts = tmp_path / 'src', tmp_path / 'posts'
    make_folder(src, '10-13 (화) 릴스 · 발음이 부끄러워요', n=2, kind='reel')
    assert sc.main([str(src)], posts_dir=posts) == 0
    assert '영상 7.0초' in capsys.readouterr().out
    assert json.loads((posts / '2026-10-13' / 'post.json').read_text(encoding='utf-8'))['type'] == 'reel'
