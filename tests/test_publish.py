# -*- coding: utf-8 -*-
"""publish.py 테스트 — 인스타 API·미디어 서버는 전부 목(mock). 실제 네트워크 호출은 없다."""
import base64
import datetime
import hashlib
import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest
import requests

import publish as pb

TOKEN = 'IGAAtesttoken1234567890SECRETVALUE'
KEY = 'a very long passphrase 한글 included for the tests 0123456789'
REPO = 'engguinness/nboim-instagram'
RAW = f'https://raw.githubusercontent.com/{REPO}/main/posts'
GRAPH = 'graph.instagram.com'


# ---------------------------------------------------------------- 가짜 requests

class Resp:
    def __init__(self, status=200, body=None, headers=None, text=''):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError('no json')
        return self._body

    def close(self):
        pass


class FakeIG:
    """requests 를 흉내 내는 목 — graph.instagram.com 과 미디어 서버(raw) 둘 다."""
    RequestException = requests.RequestException

    def __init__(self, username=pb.EXPECTED_USERNAME, media_status=200, video_ctype='video/mp4',
                 container_status=None, publish_ok=True, recent=None, permalink='https://www.instagram.com/p/TEST123/',
                 refresh_body=None, refresh_status=200, raise_on_get=None):
        self.username = username
        self.media_status = media_status
        self.video_ctype = video_ctype
        self.container_status = container_status or {}      # id -> [상태, 상태, …] (마지막 값이 계속 반복)
        self.publish_ok = publish_ok
        self.recent = recent or []
        self.permalink = permalink
        self.refresh_body = refresh_body if refresh_body is not None else {'access_token': 'IGAArefreshedtoken9876543210NEW', 'token_type': 'bearer', 'expires_in': 5184000}
        self.refresh_status = refresh_status
        self.raise_on_get = raise_on_get
        self.calls = []            # (method, url, fields)
        self.n = 0
        self.containers = {}       # id -> fields
        self.published = False

    # -- 도우미
    @property
    def graph_calls(self):
        return [c for c in self.calls if GRAPH in c[1]]

    def posts(self, suffix):
        return [c for c in self.calls if c[0] == 'POST' and c[1].endswith(suffix)]

    # -- requests API
    def head(self, url, **kw):
        self.calls.append(('HEAD', url, None))
        if self.media_status != 200:
            return Resp(self.media_status)
        ctype = self.video_ctype if url.endswith('.mp4') else 'image/jpeg'
        return Resp(200, headers={'Content-Type': ctype})

    def get(self, url, params=None, **kw):
        self.calls.append(('GET', url, dict(params or {})))
        if self.raise_on_get:
            raise self.RequestException(f'boom {url}?access_token={(params or {}).get("access_token")}')
        if GRAPH not in url:
            return self.head(url)
        if url.endswith('/refresh_access_token'):
            return Resp(self.refresh_status, self.refresh_body)
        if url.endswith('/me'):
            return Resp(200, {'user_id': '17841400000000000', 'id': '999', 'username': self.username})
        if url.endswith('/media'):
            return Resp(200, {'data': self.recent})
        cid = url.rsplit('/', 1)[-1]
        if cid in self.containers:
            seq = self.container_status.get(cid) or ['FINISHED']
            state = seq.pop(0) if len(seq) > 1 else seq[0]
            body = {'status_code': state, 'id': cid}
            if state == 'ERROR':
                body['status'] = 'Error: Media upload has failed with error code 2207026'
            return Resp(200, body)
        if cid.startswith('mid'):
            return Resp(200, {'permalink': self.permalink, 'id': cid})
        return Resp(400, {'error': {'message': 'unknown id', 'code': 100}})

    def post(self, url, data=None, **kw):
        fields = dict(data or {})
        self.calls.append(('POST', url, fields))
        if url.endswith('/media_publish'):
            if not self.publish_ok:
                return Resp(500, {'error': {'message': 'Unexpected error', 'code': 2}})
            self.published = True
            return Resp(200, {'id': 'mid1'})
        if url.endswith('/media'):
            self.n += 1
            cid = f'c{self.n}'
            self.containers[cid] = fields
            return Resp(200, {'id': cid})
        return Resp(400, {'error': {'message': 'bad route'}})


@pytest.fixture(autouse=True)
def _no_sleep_no_secret_leak(monkeypatch):
    monkeypatch.setattr(pb.time, 'sleep', lambda s: None)
    pb._SECRETS.clear()
    yield
    pb._SECRETS.clear()


@pytest.fixture
def env():
    return {'IG_ACCESS_TOKEN': TOKEN, 'IG_TOKEN_KEY': KEY, 'GITHUB_REPOSITORY': REPO}


def install(monkeypatch, fake):
    monkeypatch.setattr(pb, 'requests', fake)
    return fake


def make_post(root, date='2026-10-07', ptype='carousel', n=3, caption='첫 줄\n\n둘째 줄\n\n#태그', ctype_files=True):
    d = Path(root) / 'posts' / date
    d.mkdir(parents=True)
    (d / 'caption.txt').write_text(caption + '\n', encoding='utf-8')
    if ptype == 'carousel':
        names = [f'{i:02d}.jpg' for i in range(1, n + 1)]
        for nm in names:
            (d / nm).write_bytes(b'\xff\xd8jpeg')
        post = {'type': 'carousel', 'date': date, 'source': '테스트 폴더', 'images': names, 'caption': 'caption.txt'}
    else:
        (d / 'video.mp4').write_bytes(b'mp4')
        (d / 'cover.jpg').write_bytes(b'\xff\xd8jpeg')
        post = {'type': 'reel', 'date': date, 'source': '테스트 릴스', 'video': 'video.mp4', 'cover': 'cover.jpg', 'caption': 'caption.txt'}
    (d / 'post.json').write_text(json.dumps(post, ensure_ascii=False), encoding='utf-8')
    return d


# ---------------------------------------------------------------- 게시물 없음 · 이미 게시됨

def test_no_post_today_exits_zero_without_any_request(tmp_path, monkeypatch, env, capsys):
    fake = install(monkeypatch, FakeIG())
    assert pb.main(['--date', '2026-10-08'], root=tmp_path, env=env) == 0
    assert '게시물 없음' in capsys.readouterr().out
    assert fake.calls == []


def test_already_published_is_skipped(tmp_path, monkeypatch, env, capsys):
    fake = install(monkeypatch, FakeIG())
    d = make_post(tmp_path)
    (d / 'published.json').write_text('{"media_id": "1"}', encoding='utf-8')
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 0
    assert '이미 게시됨' in capsys.readouterr().out
    assert fake.calls == []


def test_default_date_is_today_in_seoul(tmp_path, monkeypatch, env, capsys):
    # UTC 23:00(10-06) = KST 08:00(10-07)
    kst = datetime.timezone(datetime.timedelta(hours=9))
    monkeypatch.setattr(pb, 'kst_now', lambda: datetime.datetime(2026, 10, 7, 8, 0, tzinfo=kst))
    install(monkeypatch, FakeIG())
    make_post(tmp_path, '2026-10-07')
    assert pb.main(['--dry', '--no-url-check'], root=tmp_path, env=env) == 0
    assert '2026-10-07' in capsys.readouterr().out


def test_real_kst_now_is_plus_nine():
    assert pb.kst_now().utcoffset() == datetime.timedelta(hours=9)


def test_invalid_date_argument_rejected(tmp_path, env):
    with pytest.raises(SystemExit):
        pb.main(['--date', '2026/10/07'], root=tmp_path, env=env)


# ---------------------------------------------------------------- 드라이런

def test_dry_run_calls_no_instagram_api(tmp_path, monkeypatch, capsys):
    fake = install(monkeypatch, FakeIG())
    make_post(tmp_path)
    # 시크릿이 하나도 없어도 드라이런은 돌아야 한다
    assert pb.main(['--date', '2026-10-07', '--dry'], root=tmp_path, env={'GITHUB_REPOSITORY': REPO}) == 0
    out = capsys.readouterr().out
    assert fake.graph_calls == []                                   # graph.instagram.com 호출 없음
    assert [c[0] for c in fake.calls] == ['HEAD'] * 3               # 미디어 URL 확인(HEAD)만
    assert all(c[1].startswith(RAW + '/2026-10-07/') for c in fake.calls)
    assert '캐러셀 3장' in out and f'{RAW}/2026-10-07/01.jpg' in out and '실제 게시는 하지 않았습니다' in out
    assert not (tmp_path / 'posts' / '2026-10-07' / 'published.json').exists()


def test_dry_run_with_no_url_check_makes_zero_requests(tmp_path, monkeypatch, env, capsys):
    fake = install(monkeypatch, FakeIG())
    make_post(tmp_path, ptype='reel')
    assert pb.main(['--date', '2026-10-07', '--dry', '--no-url-check'], root=tmp_path, env=env) == 0
    assert fake.calls == []
    out = capsys.readouterr().out
    assert '릴스' in out and f'{RAW}/2026-10-07/video.mp4' in out and f'{RAW}/2026-10-07/cover.jpg' in out
    assert TOKEN not in out and KEY not in out


def test_dry_run_reports_unreachable_urls_and_octet_stream_warning(tmp_path, monkeypatch, env, capsys):
    install(monkeypatch, FakeIG(media_status=404))
    make_post(tmp_path)
    assert pb.main(['--date', '2026-10-07', '--dry'], root=tmp_path, env=env) == 0
    assert '문제' in capsys.readouterr().out
    install(monkeypatch, FakeIG(video_ctype='application/octet-stream'))
    make_post(tmp_path, '2026-10-09', ptype='reel')
    assert pb.main(['--date', '2026-10-09', '--dry'], root=tmp_path, env=env) == 0
    out = capsys.readouterr().out
    assert '경고' in out and 'octet-stream' in out


def test_media_base_override_for_github_pages(tmp_path, monkeypatch, capsys):
    fake = install(monkeypatch, FakeIG())
    make_post(tmp_path, ptype='reel')
    env = {'MEDIA_BASE': 'https://engguinness.github.io/nboim-instagram/', 'GITHUB_REPOSITORY': REPO}
    assert pb.main(['--date', '2026-10-07', '--dry'], root=tmp_path, env=env) == 0
    assert 'https://engguinness.github.io/nboim-instagram/posts/2026-10-07/video.mp4' in capsys.readouterr().out
    assert all(c[1].startswith('https://engguinness.github.io/nboim-instagram/posts/') for c in fake.calls)


# ---------------------------------------------------------------- 계정 불일치

def test_username_mismatch_publishes_nothing(tmp_path, monkeypatch, env, capsys):
    fake = install(monkeypatch, FakeIG(username='modu_ntelecom'))
    d = make_post(tmp_path)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 1
    out = capsys.readouterr().out
    assert 'justenglish_guinness' in out and 'modu_ntelecom' in out
    assert fake.posts('/media') == [] and fake.posts('/media_publish') == []
    assert not [c for c in fake.calls if c[0] == 'HEAD']            # 미디어 확인 단계까지도 가지 않음
    assert not (d / 'published.json').exists()


def test_missing_token_fails_clearly(tmp_path, monkeypatch, capsys):
    fake = install(monkeypatch, FakeIG())
    make_post(tmp_path)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env={'GITHUB_REPOSITORY': REPO}) == 1
    assert 'IG_ACCESS_TOKEN' in capsys.readouterr().out
    assert fake.calls == []


# ---------------------------------------------------------------- 게시 흐름

def test_carousel_publish_sequence(tmp_path, monkeypatch, env, capsys):
    fake = install(monkeypatch, FakeIG())
    d = make_post(tmp_path, n=3)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 0

    medias = fake.posts('/media')
    assert len(medias) == 4
    children, parent = medias[:3], medias[3]
    for i, c in enumerate(children, start=1):
        assert c[2]['is_carousel_item'] == 'true' and c[2]['image_url'] == f'{RAW}/2026-10-07/{i:02d}.jpg'
        assert 'caption' not in c[2]
    assert parent[2]['media_type'] == 'CAROUSEL' and parent[2]['children'] == 'c1,c2,c3'
    assert parent[2]['caption'] == '첫 줄\n\n둘째 줄\n\n#태그'
    assert all(c[1].startswith(f'{pb.IG_API}/17841400000000000/media') for c in fake.calls if c[0] == 'POST')
    pub = fake.posts('/media_publish')
    assert len(pub) == 1 and pub[0][2]['creation_id'] == 'c4'

    rec = json.loads((d / 'published.json').read_text(encoding='utf-8'))
    assert rec['media_id'] == 'mid1' and rec['permalink'] == 'https://www.instagram.com/p/TEST123/'
    assert rec['published_at'].endswith('+09:00')
    out = capsys.readouterr().out
    assert TOKEN not in out and KEY not in out
    # 같은 날 다시 돌려도 새로 올리지 않는다
    n_before = len(fake.calls)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 0
    assert len(fake.calls) == n_before


def test_single_photo_uses_image_container(tmp_path, monkeypatch, env):
    fake = install(monkeypatch, FakeIG())
    make_post(tmp_path, n=1)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 0
    medias = fake.posts('/media')
    assert len(medias) == 1
    assert medias[0][2]['image_url'].endswith('/01.jpg') and 'is_carousel_item' not in medias[0][2]
    assert medias[0][2]['caption'].startswith('첫 줄')
    assert fake.posts('/media_publish')[0][2]['creation_id'] == 'c1'


def test_reel_publish_polls_until_finished(tmp_path, monkeypatch, env):
    fake = install(monkeypatch, FakeIG(container_status={'c1': ['IN_PROGRESS', 'IN_PROGRESS', 'FINISHED']}))
    d = make_post(tmp_path, ptype='reel')
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 0
    medias = fake.posts('/media')
    assert len(medias) == 1
    f = medias[0][2]
    assert f['media_type'] == 'REELS' and f['video_url'] == f'{RAW}/2026-10-07/video.mp4'
    assert f['cover_url'] == f'{RAW}/2026-10-07/cover.jpg' and f['share_to_feed'] == 'true'
    assert f['caption'].startswith('첫 줄')
    polls = [c for c in fake.calls if c[0] == 'GET' and c[1].endswith('/c1')]
    assert len(polls) == 3                                           # IN_PROGRESS ×2 → FINISHED
    assert fake.calls.index(polls[-1]) < fake.calls.index(fake.posts('/media_publish')[0])   # 처리 끝난 뒤에 발행
    assert (d / 'published.json').exists()


def test_reel_error_status_stops_before_publish(tmp_path, monkeypatch, env, capsys):
    fake = install(monkeypatch, FakeIG(container_status={'c1': ['IN_PROGRESS', 'ERROR']}))
    d = make_post(tmp_path, ptype='reel')
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 1
    assert '2207026' in capsys.readouterr().out
    assert fake.posts('/media_publish') == [] and not (d / 'published.json').exists()


def test_reel_timeout_after_five_minutes_of_polling(tmp_path, monkeypatch, env, capsys):
    fake = install(monkeypatch, FakeIG(container_status={'c1': ['IN_PROGRESS']}))
    make_post(tmp_path, ptype='reel')
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 1
    polls = [c for c in fake.calls if c[0] == 'GET' and c[1].endswith('/c1')]
    assert len(polls) == pb.REEL_POLL[0] and pb.REEL_POLL[0] * pb.REEL_POLL[1] == 300
    assert fake.posts('/media_publish') == []


def test_unreachable_media_url_blocks_container_creation(tmp_path, monkeypatch, env, capsys):
    fake = install(monkeypatch, FakeIG(media_status=404))
    d = make_post(tmp_path)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 1
    assert '접근할 수 없음' in capsys.readouterr().out
    assert fake.posts('/media') == [] and not (d / 'published.json').exists()


def test_wrong_content_type_only_warns_and_continues(tmp_path, monkeypatch, env, capsys):
    fake = install(monkeypatch, FakeIG(video_ctype='application/octet-stream'))
    d = make_post(tmp_path, ptype='reel')
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 0
    assert 'octet-stream' in capsys.readouterr().out
    assert fake.posts('/media_publish') and (d / 'published.json').exists()


def test_same_caption_already_on_account_is_not_posted_again(tmp_path, monkeypatch, env):
    now = datetime.datetime.now(datetime.timezone.utc)
    recent = [{'id': 'old1', 'caption': '첫 줄  \n\n둘째 줄\n\n#태그', 'permalink': 'https://www.instagram.com/p/OLD/',
               'timestamp': (now - datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S+0000')}]
    fake = install(monkeypatch, FakeIG(recent=recent))
    d = make_post(tmp_path)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 0
    assert fake.posts('/media') == [] and fake.posts('/media_publish') == []
    rec = json.loads((d / 'published.json').read_text(encoding='utf-8'))
    assert rec['media_id'] == 'old1' and rec['permalink'].endswith('/OLD/')


def test_old_post_with_same_caption_does_not_block(tmp_path, monkeypatch, env):
    now = datetime.datetime.now(datetime.timezone.utc)
    recent = [{'id': 'old1', 'caption': '첫 줄\n\n둘째 줄\n\n#태그', 'permalink': 'x',
               'timestamp': (now - datetime.timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S+0000')}]
    fake = install(monkeypatch, FakeIG(recent=recent))
    make_post(tmp_path)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 0
    assert fake.posts('/media_publish')


def test_publish_error_but_post_actually_exists_is_recovered(tmp_path, monkeypatch, env):
    class Flaky(FakeIG):
        def get(self, url, params=None, **kw):
            if url.endswith('/17841400000000000/media') and self.published:     # 발행 '실패' 뒤에는 글이 보임
                self.recent = [{'id': 'new1', 'caption': '첫 줄\n\n둘째 줄\n\n#태그', 'permalink': 'https://www.instagram.com/p/NEW/',
                                'timestamp': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+0000')}]
            return super().get(url, params, **kw)

        def post(self, url, data=None, **kw):
            r = super().post(url, data, **kw)
            if url.endswith('/media_publish'):
                self.published = True
                return Resp(500, {'error': {'message': 'timeout-ish', 'code': 2}})
            return r

    fake = install(monkeypatch, Flaky(publish_ok=True))
    d = make_post(tmp_path)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 0
    assert len(fake.posts('/media_publish')) == 1                    # 두 번 발행하지 않음
    assert json.loads((d / 'published.json').read_text(encoding='utf-8'))['media_id'] == 'new1'


def test_publish_failure_returns_one_and_writes_nothing(tmp_path, monkeypatch, env, capsys):
    fake = install(monkeypatch, FakeIG(publish_ok=False))
    d = make_post(tmp_path)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 1
    assert 'media_publish 실패' in capsys.readouterr().out
    assert not (d / 'published.json').exists()


def test_connection_error_never_prints_token(tmp_path, monkeypatch, env, capsys):
    install(monkeypatch, FakeIG(raise_on_get=True))
    make_post(tmp_path)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 1
    out = capsys.readouterr().out
    assert TOKEN not in out and 'access_token=***' in out


def test_redact_masks_query_tokens_and_known_secrets():
    pb.register_secret('LONGSECRETVALUE123')
    s = pb.redact('GET https://graph.instagram.com/me?fields=x&access_token=ABCDEF123456&b=1 ... LONGSECRETVALUE123')
    assert 'ABCDEF123456' not in s and 'LONGSECRETVALUE123' not in s and 'access_token=***' in s


def test_post_json_problems_are_reported(tmp_path, monkeypatch, env, capsys):
    install(monkeypatch, FakeIG())
    d = make_post(tmp_path)
    (d / '02.jpg').unlink()
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 1
    assert '파일이 없음' in capsys.readouterr().out
    post = json.loads((d / 'post.json').read_text(encoding='utf-8'))
    post['images'] = ['../evil.jpg']
    (d / 'post.json').write_text(json.dumps(post), encoding='utf-8')
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 1


# ---------------------------------------------------------------- 토큰 암호화 · 선택 · 갱신

def test_encrypt_decrypt_roundtrip_and_wrong_key():
    enc = pb.encrypt_text('{"access_token": "abc"}', KEY)
    assert enc.startswith('U2FsdGVkX1')                              # base64("Salted__")
    assert 'abc' not in enc
    assert pb.decrypt_text(enc, KEY) == '{"access_token": "abc"}'
    with pytest.raises(pb.PublishError):
        pb.decrypt_text(enc, 'wrong key')


def test_encryption_is_standard_pbkdf2_sha256_openssl_compatible():
    """OpenSSL 3(깃허브 러너)과 호환되는지: 우리 암호문을 표준 PBKDF2-HMAC-SHA256 으로 직접 유도한 키·IV 로 풀어 본다."""
    enc = pb.encrypt_text('plain-check-value', KEY)
    raw = base64.b64decode(enc)
    assert raw[:8] == b'Salted__'
    salt, ct = raw[8:16], raw[16:]
    km = hashlib.pbkdf2_hmac('sha256', KEY.encode('utf-8'), salt, pb.KDF_ITER, 48)
    r = subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-K', km[:32].hex(), '-iv', km[32:].hex()],
                       input=ct, capture_output=True)
    assert r.returncode == 0 and r.stdout.decode() == 'plain-check-value'


def test_token_source_prefers_token_enc_when_fingerprint_matches(tmp_path, env):
    pb.save_token_record(tmp_path, {'access_token': 'IGAAnewerrefreshedtoken0001', 'src_fp': pb.fingerprint(TOKEN)}, KEY)
    assert pb.load_token(tmp_path, env) == ('IGAAnewerrefreshedtoken0001', 'token.enc')


def test_token_source_uses_secret_when_secret_changed_or_key_wrong_or_no_file(tmp_path, env, capsys):
    assert pb.load_token(tmp_path, env) == (TOKEN, 'secret')                     # token.enc 없음
    pb.save_token_record(tmp_path, {'access_token': 'IGAAoldrefreshedtoken0001', 'src_fp': pb.fingerprint('previous-secret')}, KEY)
    assert pb.load_token(tmp_path, env) == (TOKEN, 'secret')                     # 시크릿이 새로 바뀜
    assert pb.load_token(tmp_path, dict(env, IG_TOKEN_KEY='another key')) == (TOKEN, 'secret')   # 키가 달라 못 풂
    assert pb.load_token(tmp_path, {'IG_ACCESS_TOKEN': TOKEN}) == (TOKEN, 'secret')              # 키 없음
    out = capsys.readouterr().out
    assert TOKEN not in out and 'IGAAoldrefreshedtoken0001' not in out


def test_token_enc_used_when_secret_missing(tmp_path):
    pb.save_token_record(tmp_path, {'access_token': 'IGAAonlyenctoken00000001', 'src_fp': None}, KEY)
    assert pb.load_token(tmp_path, {'IG_TOKEN_KEY': KEY}) == ('IGAAonlyenctoken00000001', 'token.enc')


def test_publish_uses_token_enc_token_for_api_calls(tmp_path, monkeypatch, env):
    fake = install(monkeypatch, FakeIG())
    pb.save_token_record(tmp_path, {'access_token': 'IGAAfromtokenenc00000001', 'src_fp': pb.fingerprint(TOKEN)}, KEY)
    make_post(tmp_path, n=2)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 0
    used = {(c[2] or {}).get('access_token') for c in fake.graph_calls}
    assert used == {'IGAAfromtokenenc00000001'}


def test_refresh_token_writes_encrypted_token_enc(tmp_path, monkeypatch, env, capsys):
    fake = install(monkeypatch, FakeIG())
    assert pb.main(['--refresh-token'], root=tmp_path, env=env) == 0
    enc_path = tmp_path / 'state' / 'token.enc'
    text = enc_path.read_text(encoding='utf-8')
    assert 'IGAArefreshedtoken9876543210NEW' not in text and TOKEN not in text
    rec = json.loads(pb.decrypt_text(text, KEY))
    assert rec['access_token'] == 'IGAArefreshedtoken9876543210NEW'
    assert rec['src_fp'] == pb.fingerprint(TOKEN) and rec['refreshed_at'] and rec['expires_at']
    gets = [c for c in fake.calls if c[1].endswith('/refresh_access_token')]
    assert gets[0][2]['grant_type'] == 'ig_refresh_token' and gets[0][2]['access_token'] == TOKEN
    out = capsys.readouterr().out
    assert 'IGAArefreshedtoken9876543210NEW' not in out and TOKEN not in out
    # 다음 게시부터는 갱신된 토큰이 쓰인다
    assert pb.load_token(tmp_path, env) == ('IGAArefreshedtoken9876543210NEW', 'token.enc')


def test_refresh_failure_keeps_old_file_and_returns_one(tmp_path, monkeypatch, env, capsys):
    install(monkeypatch, FakeIG(refresh_status=400, refresh_body={'error': {'message': 'Session has expired', 'code': 190}}))
    assert pb.main(['--refresh-token'], root=tmp_path, env=env) == 1
    assert not (tmp_path / 'state' / 'token.enc').exists()
    assert '190' in capsys.readouterr().out


def test_refresh_too_young_token_is_not_a_failure(tmp_path, monkeypatch, env, capsys):
    fake = install(monkeypatch, FakeIG(refresh_status=400, refresh_body={'error': {'message': 'Token must be at least 24 hours old to refresh', 'code': 10}}))
    assert pb.main(['--refresh-token'], root=tmp_path, env=env) == 0
    assert not (tmp_path / 'state' / 'token.enc').exists()
    assert [c for c in fake.calls if c[1].endswith('/me')]                      # 건너뛰어도 계정 확인은 먼저 했다


def test_refresh_refuses_wrong_account_and_missing_key(tmp_path, monkeypatch, env):
    install(monkeypatch, FakeIG(username='someone_else'))
    assert pb.main(['--refresh-token'], root=tmp_path, env=env) == 1
    assert not (tmp_path / 'state' / 'token.enc').exists()
    assert pb.main(['--refresh-token'], root=tmp_path, env={'IG_ACCESS_TOKEN': TOKEN}) == 1


# ---------------------------------------------------------------- sync_content → publish 이어 붙이기

def test_synced_post_is_publishable(tmp_path, monkeypatch, env):
    """sync_content 가 만든 post.json 을 publish 가 그대로 읽는지."""
    from PIL import Image
    import sync_content as sc
    src = tmp_path / 'src' / '10-07 (수) 카드뉴스 · 연결 확인'
    src.mkdir(parents=True)
    for i in (1, 2):
        Image.new('RGB', sc.CAROUSEL_SIZE, (i * 40, 90, 160)).save(src / f'1080x1350_{i:02d}.jpg', 'JPEG', quality=92)
    (src / sc.CAPTION_SRC).write_text('연결 확인 캡션\n', encoding='utf-8')
    root = tmp_path / 'repo'
    assert sc.main([str(tmp_path / 'src')], posts_dir=root / 'posts') == 0
    fake = install(monkeypatch, FakeIG())
    assert pb.main(['--date', '2026-10-07'], root=root, env=env) == 0
    assert fake.posts('/media')[-1][2]['caption'] == '연결 확인 캡션'


# ---------------------------------------------------------------- 계정 번호 기록(state/account.json) — 아이디를 바꿔도 게시가 이어지게 (2026-10-15)

def _account(root):
    p = root / 'state' / 'account.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def test_first_publish_records_account_user_id(tmp_path, monkeypatch, env):
    install(monkeypatch, FakeIG())
    make_post(tmp_path)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 0
    rec = _account(tmp_path)
    assert rec['user_id'] == '17841400000000000' and rec['username'] == pb.EXPECTED_USERNAME and rec['verified_at']


def test_renamed_username_still_publishes_when_user_id_matches(tmp_path, monkeypatch, env, capsys):
    (tmp_path / 'state').mkdir()
    (tmp_path / 'state' / 'account.json').write_text(json.dumps({'user_id': '17841400000000000', 'username': pb.EXPECTED_USERNAME}), encoding='utf-8')
    fake = install(monkeypatch, FakeIG(username='justenglish_new'))      # 아이디를 바꾼 뒤
    d = make_post(tmp_path)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 0
    out = capsys.readouterr().out
    assert '아이디 변경 감지' in out and '@justenglish_new' in out
    assert fake.posts('/media_publish') and (d / 'published.json').exists()
    assert _account(tmp_path)['username'] == 'justenglish_new'          # 기록도 새 아이디로


def test_account_user_id_mismatch_refuses_even_if_username_expected(tmp_path, monkeypatch, env, capsys):
    (tmp_path / 'state').mkdir()
    (tmp_path / 'state' / 'account.json').write_text(json.dumps({'user_id': '17841499999999999', 'username': pb.EXPECTED_USERNAME}), encoding='utf-8')
    fake = install(monkeypatch, FakeIG())
    d = make_post(tmp_path)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 1
    assert '계정 번호' in capsys.readouterr().out
    assert fake.posts('/media') == [] and not (d / 'published.json').exists()


def test_refresh_bootstraps_account_record(tmp_path, monkeypatch, env):
    install(monkeypatch, FakeIG())
    assert pb.main(['--refresh-token'], root=tmp_path, env=env) == 0
    assert _account(tmp_path)['user_id'] == '17841400000000000'


# ---------------------------------------------------------------- 릴스 경로(--root reels)

PAGES = 'https://nboim-reels.pages.dev/reels'


def make_reel(root, date='2026-11-19', caption='릴스 첫 줄\n\n#태그'):
    d = Path(root) / 'reels' / date
    d.mkdir(parents=True)
    (d / 'caption.txt').write_text(caption + '\n', encoding='utf-8')
    (d / 'video.mp4').write_bytes(b'mp4')
    (d / 'cover.jpg').write_bytes(b'\xff\xd8jpeg')
    post = {'type': 'reel', 'date': date, 'video': 'video.mp4', 'cover': 'cover.jpg', 'caption': 'caption.txt'}
    (d / 'post.json').write_text(json.dumps(post, ensure_ascii=False), encoding='utf-8')
    return d


@pytest.fixture
def renv(env):
    return dict(env)


def test_reel_media_urls_use_pages_base_and_env_override():
    assert pb.REEL_MEDIA_BASE_DEFAULT == 'https://nboim-reels.pages.dev'
    e = {'GITHUB_REPOSITORY': REPO, 'MEDIA_BASE': 'https://x.github.io/y'}
    base = pb.reel_media_base(e)                              # MEDIA_BASE(카드용) 는 릴스에 영향 없음, SHA 도 필요 없음
    assert base == 'https://nboim-reels.pages.dev'
    assert pb.media_url(base, '2026-11-19', 'video.mp4', 'reels') == f'{PAGES}/2026-11-19/video.mp4'
    assert pb.reel_media_base({'REEL_MEDIA_BASE': 'https://r.example/x/'}) == 'https://r.example/x'
    assert pb.media_url('B', '2026-11-19', '01.jpg') == 'B/posts/2026-11-19/01.jpg'     # 카드 기본 불변
    assert 'jsdelivr' not in open(pb.__file__, encoding='utf-8').read().lower()


def test_reel_date_rule_schedule_minus_12h_otherwise_today(monkeypatch):
    KST = datetime.timezone(datetime.timedelta(hours=9))
    def at(*a):
        monkeypatch.setattr(pb, 'kst_now', lambda: datetime.datetime(*a, tzinfo=KST))
    ns = lambda date=None: type('A', (), {'date': date})()
    sched = {'GITHUB_EVENT_NAME': 'schedule'}
    at(2026, 11, 19, 18, 13)                                  # 제때
    assert pb.resolve_date(ns(), sched, True)[0] == '2026-11-19'
    at(2026, 11, 20, 1, 13)                                   # 7시간 늦음 — 그날 몫
    assert pb.resolve_date(ns(), sched, True)[0] == '2026-11-19'
    at(2026, 11, 20, 11, 59)                                  # 한계 직전(11시간 46분 늦음)
    assert pb.resolve_date(ns(), sched, True)[0] == '2026-11-19'
    at(2026, 11, 20, 12, 0)                                   # 정오가 지나면 다음 날 몫
    assert pb.resolve_date(ns(), sched, True)[0] == '2026-11-20'
    d, why = pb.resolve_date(ns(), {'GITHUB_EVENT_NAME': 'workflow_dispatch'}, True)    # 수동 실행은 그대로
    assert d == '2026-11-20' and '오늘' in why
    assert pb.resolve_date(ns('2026-12-01'), sched, True)[0] == '2026-12-01'            # --date 우선
    at(2026, 11, 20, 1, 13)
    assert pb.resolve_date(ns(), sched, False)[0] == '2026-11-20'                       # 카드 경로는 불변


def test_reel_scheduled_run_outside_evening_window_does_nothing(tmp_path, monkeypatch, renv, capsys):
    # 11-19 몫이 깃허브 지연으로 11-20 03:13 에 올라갔다 — 이제 저녁(18~24시)이 아니면 예약 실행은 아무것도 안 한다.
    KST = datetime.timezone(datetime.timedelta(hours=9))
    fake = install(monkeypatch, FakeIG())
    d = make_reel(tmp_path, '2026-11-19')
    make_reel(tmp_path, '2026-11-20')
    for hm in [(2, 30), (11, 59), (17, 59)]:
        monkeypatch.setattr(pb, 'kst_now', lambda hm=hm: datetime.datetime(2026, 11, 20, *hm, tzinfo=KST))
        assert pb.main(['--root', 'reels'], root=tmp_path, env=dict(renv, GITHUB_EVENT_NAME='schedule')) == 0
        out = capsys.readouterr().out
        assert '저녁 시간대(18~24시)가 아니라' in out and '대상 날짜' not in out
    assert fake.calls == []
    assert not (d / 'published.json').exists() and not (tmp_path / 'reels' / '2026-11-20' / 'published.json').exists()


def test_reel_scheduled_run_in_evening_posts_today_and_logs_rule(tmp_path, monkeypatch, renv, capsys):
    KST = datetime.timezone(datetime.timedelta(hours=9))
    monkeypatch.setattr(pb, 'kst_now', lambda: datetime.datetime(2026, 11, 20, 19, 5, tzinfo=KST))
    fake = install(monkeypatch, FakeIG())
    make_reel(tmp_path, '2026-11-19')                         # 어제 몫이 남아 있어도 오늘 몫만
    d = make_reel(tmp_path, '2026-11-20')
    assert pb.main(['--root', 'reels'], root=tmp_path, env=dict(renv, GITHUB_EVENT_NAME='schedule')) == 0
    out = capsys.readouterr().out
    assert '대상 날짜 : 2026-11-20' in out and '예약 실행' in out and (d / 'published.json').exists()
    assert not (tmp_path / 'reels' / '2026-11-19' / 'published.json').exists()
    # 같은 저녁에 다시 깨어도(매시간 예약) 두 번 올리지 않는다
    n = len(fake.calls)
    monkeypatch.setattr(pb, 'kst_now', lambda: datetime.datetime(2026, 11, 20, 20, 5, tzinfo=KST))
    assert pb.main(['--root', 'reels'], root=tmp_path, env=dict(renv, GITHUB_EVENT_NAME='schedule')) == 0
    assert '이미 게시됨' in capsys.readouterr().out and len(fake.calls) == n


def test_reel_window_boundaries_and_manual_runs_ignore_window(monkeypatch):
    KST = datetime.timezone(datetime.timedelta(hours=9))
    def at(*a):
        monkeypatch.setattr(pb, 'kst_now', lambda: datetime.datetime(*a, tzinfo=KST))
    ns = lambda date=None: type('A', (), {'date': date})()
    sched = {'GITHUB_EVENT_NAME': 'schedule'}
    assert pb.REEL_WINDOW == (18, 24)
    at(2026, 11, 20, 17, 59); assert pb.reel_window_skip(ns(), sched)
    at(2026, 11, 20, 18, 0);  assert pb.reel_window_skip(ns(), sched) is None
    at(2026, 11, 20, 23, 59); assert pb.reel_window_skip(ns(), sched) is None
    at(2026, 11, 21, 0, 0);   assert pb.reel_window_skip(ns(), sched)
    at(2026, 11, 21, 3, 0)
    assert pb.reel_window_skip(ns(), {'GITHUB_EVENT_NAME': 'workflow_dispatch'}) is None    # 수동 실행은 시간대 무관
    assert pb.reel_window_skip(ns(), {}) is None                                             # 로컬 실행도
    assert pb.reel_window_skip(ns('2026-11-21'), sched) is None                              # --date 지정도


def test_reels_workflow_wakes_hourly_and_gate_matches_window():
    wf = (Path(pb.__file__).resolve().parent / '.github' / 'workflows' / 'reels.yml').read_text(encoding='utf-8')
    assert "cron: '13 * * * *'" in wf                         # 매시간 깨움(하루 한 번 예약은 5~9시간 늦게 돌았다)
    assert f'-lt {pb.REEL_WINDOW[0]} ]' in wf and "TZ=KST-9 date '+%-H %F'" in wf    # gate 의 시작 시각 = REEL_WINDOW 시작
    assert 'needs: gate' in wf and "needs.gate.outputs.go == 'true'" in wf
    assert '--max-time' in wf                                 # 깃허브 API 가 멈춰도 gate 가 5분 제한에 걸려 실패하지 않게
    # 상태 줄(concurrency)은 실제로 올릴 수 있는 실행만 들어간다 — 매시간 실행이 카드·토큰 갱신 대기 실행을 밀어내지 않게
    head, _, jobs = wf.partition('\njobs:')
    assert not re.search(r'^concurrency:', head, re.M) and 'group: nboim-instagram-state' in jobs.split('\n  reels:', 1)[1]


def test_root_reels_reads_reels_dir_not_posts(tmp_path, monkeypatch, renv, capsys):
    fake = install(monkeypatch, FakeIG())
    make_post(tmp_path, date='2026-11-19')                   # 같은 날 카드가 있어도
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 0
    assert fake.calls == [] and '릴스 없음' in capsys.readouterr().out    # reels/ 가 비었으니 아무것도 안 함
    make_reel(tmp_path)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19', '--dry', '--no-url-check'], root=tmp_path, env=renv) == 0
    out = capsys.readouterr().out
    assert '릴스(REELS)' in out and f'{PAGES}/2026-11-19/video.mp4' in out and f'{PAGES}/2026-11-19/cover.jpg' in out
    assert fake.calls == []


def test_reels_dry_run_needs_no_repo_or_sha_and_makes_no_calls(tmp_path, monkeypatch, env, capsys):
    fake = install(monkeypatch, FakeIG())
    make_reel(tmp_path)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19', '--dry', '--no-url-check'],
                   root=tmp_path, env={}) == 0
    assert fake.calls == [] and f'{PAGES}/2026-11-19/video.mp4' in capsys.readouterr().out


def test_reels_dry_run_url_check_waits_and_retries(tmp_path, monkeypatch, renv, capsys):
    fake = install(monkeypatch, FakeIG())
    make_reel(tmp_path)
    state = {'n': 0}
    orig = fake.head
    def flaky(url, **kw):
        if url.endswith('video.mp4'):
            state['n'] += 1
            if state['n'] < 3:
                fake.calls.append(('HEAD', url, None))
                return Resp(404)
        return orig(url, **kw)
    fake.head = flaky
    assert pb.main(['--root', 'reels', '--date', '2026-11-19', '--dry'], root=tmp_path, env=renv) == 0
    out = capsys.readouterr().out
    assert '모두 200' in out and state['n'] == 3 and fake.graph_calls == []
    # 끝내 안 되면 정해진 횟수(3번)만 보고 문제로 표시(드라이런이라 종료 코드는 0)
    fake2 = install(monkeypatch, FakeIG(media_status=404))
    assert pb.main(['--root', 'reels', '--date', '2026-11-19', '--dry'], root=tmp_path, env=renv) == 0
    assert len([c for c in fake2.calls if c[0] == 'HEAD' and c[1].endswith('video.mp4')]) == pb.REEL_URL_WAIT_DRY[0] == 3
    assert '접근 안 됨' in capsys.readouterr().out


def test_reel_publish_uses_pages_urls_and_writes_published_under_reels(tmp_path, monkeypatch, renv):
    fake = install(monkeypatch, FakeIG())
    d = make_reel(tmp_path)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 0
    f = fake.posts('/media')[0][2]
    assert f['media_type'] == 'REELS' and f['video_url'] == f'{PAGES}/2026-11-19/video.mp4'
    assert f['cover_url'] == f'{PAGES}/2026-11-19/cover.jpg'
    assert (d / 'published.json').exists() and not (tmp_path / 'posts').exists()
    # 두 번째 실행: 이미 게시됨 → 요청 0건
    n = len(fake.calls)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 0
    assert len(fake.calls) == n


def test_reel_wrong_content_type_waits_then_fails_safely(tmp_path, monkeypatch, renv, capsys):
    fake = install(monkeypatch, FakeIG(video_ctype='application/octet-stream'))
    d = make_reel(tmp_path)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 1
    assert fake.posts('/media') == [] and not fake.posts('/media_publish') and not (d / 'published.json').exists()
    heads = [c for c in fake.calls if c[0] == 'HEAD' and c[1].endswith('video.mp4')]
    assert len(heads) == pb.REEL_URL_WAIT[0]                  # 여러 번 다시 봄
    assert 'Content-Type' in capsys.readouterr().out


def test_reel_url_becomes_ready_after_retries(tmp_path, monkeypatch, renv):
    fake = install(monkeypatch, FakeIG())
    make_reel(tmp_path)
    state = {'n': 0}
    orig = fake.head
    def flaky(url, **kw):
        if url.endswith('video.mp4'):
            state['n'] += 1
            if state['n'] < 3:
                fake.calls.append(('HEAD', url, None))
                return Resp(404)
        return orig(url, **kw)
    fake.head = flaky
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 0
    assert fake.published


def test_reel_same_caption_dedupe_and_card_same_day_independent(tmp_path, monkeypatch, renv):
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+0000')
    recent = [{'id': 'old', 'caption': '릴스 첫 줄\n\n#태그', 'permalink': 'https://www.instagram.com/p/OLD/', 'timestamp': now}]
    fake = install(monkeypatch, FakeIG(recent=recent))
    d = make_reel(tmp_path)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 0
    assert fake.posts('/media') == [] and (d / 'published.json').exists()      # 중복 → 올리지 않고 기록만
    # 같은 날 카드: reels 의 published.json 이 posts/ 를 막지 않는다
    fake2 = install(monkeypatch, FakeIG())
    make_post(tmp_path, date='2026-11-19')
    assert pb.main(['--date', '2026-11-19'], root=tmp_path, env=renv) == 0
    assert fake2.published and (tmp_path / 'posts' / '2026-11-19' / 'published.json').exists()


def test_reel_dedupe_lookup_failure_aborts_but_card_continues(tmp_path, monkeypatch, renv, capsys):
    class NoRecent(FakeIG):
        def get(self, url, params=None, **kw):
            if url.endswith('/media'):
                return Resp(500, {'error': {'message': 'boom', 'code': 2}})
            return super().get(url, params, **kw)
    fake = install(monkeypatch, NoRecent())
    d = make_reel(tmp_path)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 1
    assert fake.posts('/media') == [] and not (d / 'published.json').exists()
    assert '중복 확인을 못 해 게시하지 않습니다' in capsys.readouterr().out
    fake2 = install(monkeypatch, NoRecent())                  # 카드는 지금처럼 경고 후 진행
    make_post(tmp_path, date='2026-11-19')
    assert pb.main(['--date', '2026-11-19'], root=tmp_path, env=renv) == 0
    assert fake2.published and '경고: 중복 확인을 못 했습니다' in capsys.readouterr().out


class PublishLost(FakeIG):
    """media_publish 가 연결 오류/5xx 로 끝나고, appears_after 번째 최근 글 조회부터 글이 보인다(None 이면 끝내 안 보임)."""
    def __init__(self, mode='5xx', appears_after=None, **kw):
        super().__init__(**kw)
        self.mode, self.appears_after, self.lookups = mode, appears_after, 0

    def post(self, url, data=None, **kw):
        if url.endswith('/media_publish'):
            self.calls.append(('POST', url, dict(data or {})))
            if self.mode == '4xx':
                return Resp(400, {'error': {'message': 'Invalid creation_id', 'code': 100}})
            if self.mode == 'conn':
                raise requests.ConnectionError('reset')
            if self.mode.startswith('t400'):
                err = {'t400-transient': {'message': 'Temporary error', 'code': 100, 'is_transient': True},
                       't400-code2': {'message': 'Service temporarily unavailable', 'code': 2},
                       't400-sub': {'message': 'Instagram server error', 'code': 9007, 'error_subcode': 2207001}}[self.mode]
                return Resp(400, {'error': err})
            return Resp(503, {'error': {'message': 'Service unavailable', 'code': 2}})
        return super().post(url, data, **kw)

    def get(self, url, params=None, **kw):
        if url.endswith('/media') and 'user' not in url and self.mode != '4xx':
            self.lookups += 1
            self.calls.append(('GET', url, dict(params or {})))
            if self.appears_after is not None and self.lookups > self.appears_after:
                now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+0000')
                return Resp(200, {'data': [{'id': 'found1', 'caption': '릴스 첫 줄\n\n#태그', 'permalink': 'https://www.instagram.com/p/F/', 'timestamp': now}]})
            return Resp(200, {'data': []})
        return super().get(url, params, **kw)


@pytest.mark.parametrize('mode', ['5xx', 'conn'])
def test_reel_unknown_publish_result_found_on_recheck_counts_as_success(tmp_path, monkeypatch, renv, mode):
    fake = install(monkeypatch, PublishLost(mode=mode, appears_after=3))     # 1번(게시 전 중복 확인)+2번 지나고 나타남
    d = make_reel(tmp_path)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 0
    rec = json.loads((d / 'published.json').read_text(encoding='utf-8'))
    assert rec['media_id'] == 'found1' and 'status' not in rec


@pytest.mark.parametrize('mode', ['5xx', 'conn'])
def test_reel_unknown_publish_result_never_found_writes_unknown_and_blocks_repost(tmp_path, monkeypatch, renv, capsys, mode):
    fake = install(monkeypatch, PublishLost(mode=mode))
    d = make_reel(tmp_path)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 1
    rec = json.loads((d / 'published.json').read_text(encoding='utf-8'))
    assert rec['status'] == 'unknown' and rec['creation_id'] == 'c1' and rec['at'] and rec['note']
    assert fake.lookups == 1 + pb.REEL_UNKNOWN_RECHECK[0]                   # 중복 확인 1 + 재확인 6
    n = len(fake.calls)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 0     # 다음 실행: 올리지 않음
    assert len(fake.calls) == n and '게시 여부 확인 필요 — 다시 올리지 않음' in capsys.readouterr().out


@pytest.mark.parametrize('mode', ['t400-transient', 't400-code2', 't400-sub'])
def test_reel_transient_400_is_treated_as_unknown(tmp_path, monkeypatch, renv, capsys, mode):
    fake = install(monkeypatch, PublishLost(mode=mode))
    d = make_reel(tmp_path)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 1
    assert json.loads((d / 'published.json').read_text(encoding='utf-8'))['status'] == 'unknown'
    assert fake.lookups == 1 + pb.REEL_UNKNOWN_RECHECK[0]
    n = len(fake.calls)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 0
    assert len(fake.calls) == n


def test_reel_transient_400_found_on_recheck_is_success(tmp_path, monkeypatch, renv):
    install(monkeypatch, PublishLost(mode='t400-code2', appears_after=3))
    d = make_reel(tmp_path)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 0
    assert json.loads((d / 'published.json').read_text(encoding='utf-8'))['media_id'] == 'found1'


def test_reel_clear_4xx_rejection_writes_no_record(tmp_path, monkeypatch, renv):
    fake = install(monkeypatch, PublishLost(mode='4xx'))
    d = make_reel(tmp_path)
    assert pb.main(['--root', 'reels', '--date', '2026-11-19'], root=tmp_path, env=renv) == 1
    assert not (d / 'published.json').exists()


def test_card_5xx_publish_failure_behaviour_unchanged(tmp_path, monkeypatch, env):
    fake = install(monkeypatch, PublishLost(mode='5xx'))
    d = make_post(tmp_path)
    assert pb.main(['--date', '2026-10-07'], root=tmp_path, env=env) == 1
    assert not (d / 'published.json').exists()                 # 카드는 unknown 기록을 남기지 않는다


def test_reels_root_rejects_non_reel_post(tmp_path, monkeypatch, renv, capsys):
    install(monkeypatch, FakeIG())
    d = make_reel(tmp_path)
    j = json.loads((d / 'post.json').read_text(encoding='utf-8'))
    j['type'] = 'carousel'; j['images'] = ['cover.jpg']
    (d / 'post.json').write_text(json.dumps(j), encoding='utf-8')
    assert pb.main(['--root', 'reels', '--date', '2026-11-19', '--dry', '--no-url-check'], root=tmp_path, env=renv) == 1


def test_card_path_unchanged_when_root_omitted(tmp_path, monkeypatch, renv):
    fake = install(monkeypatch, FakeIG())
    make_post(tmp_path, ptype='reel', date='2026-10-09')      # 카드 경로의 옛 릴스도 raw 주소 그대로
    assert pb.main(['--date', '2026-10-09'], root=tmp_path, env=renv) == 0
    assert fake.posts('/media')[0][2]['video_url'] == f'{RAW}/2026-10-09/video.mp4'
    assert pb.build_parser().parse_args([]).root == 'posts'


# ---------------------------------------------------------------- reels.yml gate 스크립트(11-20 검토 반영)
# gate 를 실제 bash 로 돌린다 — date·curl 은 가짜. 한국 시각은 TZ 가 KST-9(또는 Asia/Seoul)일 때만, 아니면 UTC 로 답한다.

WF_REELS = Path(pb.__file__).resolve().parent / '.github' / 'workflows' / 'reels.yml'
KST_TZ = datetime.timezone(datetime.timedelta(hours=9))

_FAKE_DATE = '''#!/bin/bash
d="${FAKE_KST% *}"; h=$((10#${FAKE_KST#* }))
case "$TZ" in KST-9|Asia/Seoul) ;; *) h=$(( (h + 15) % 24 ));; esac      # TZ 없이 부르면 UTC 시각
for a; do case "$a" in '+%-H %F') echo "$h $d";; +%-H) echo "$h";; +%F) echo "$d";; esac; done
'''
_FAKE_CURL = '''#!/bin/bash
u="${@: -1}"; echo "$u" >> "$CURL_LOG"
case "$u" in */published.json\\?*) c=$FAKE_PUB;; */post.json\\?*) c=$FAKE_POST;; *) c=999;; esac
printf '%s' "$c"; [ "$c" != 000 ]
'''


def _gate_block():
    return WF_REELS.read_text(encoding='utf-8').split('\n  gate:', 1)[1].split('\n  reels:', 1)[0]


@pytest.mark.parametrize('event,kst,pub,post,go', [
    ('workflow_dispatch', '2026-11-21 03', '', '', 'true'),   # 수동 실행: 시각·기록을 안 봄
    ('schedule', '2026-11-21 00', '404', '200', 'false'),     # 자정 넘김(11-19 몫이 11-20 03:13 에 올라간 시각대)
    ('schedule', '2026-11-20 03', '404', '200', 'false'),
    ('schedule', '2026-11-20 17', '404', '200', 'false'),
    ('schedule', '2026-11-20 18', '404', '200', 'true'),
    ('schedule', '2026-11-20 23', '404', '200', 'true'),
    ('schedule', '2026-11-20 19', '200', '200', 'false'),     # 게시 기록 있음(status=unknown 포함)
    ('schedule', '2026-11-20 19', '404', '404', 'false'),     # 그날 몫 없음
    ('schedule', '2026-11-20 19', '000', '000', 'true'),      # API 모름(타임아웃 포함) → publish.py 가 판정
])
def test_reels_gate_script(tmp_path, event, kst, pub, post, go):
    bin_ = tmp_path / 'bin'
    bin_.mkdir()
    for name, src in (('date', _FAKE_DATE), ('curl', _FAKE_CURL)):
        (bin_ / name).write_text(src)
        (bin_ / name).chmod(0o755)
    script = textwrap.dedent(_gate_block().split('run: |\n', 1)[1])
    out, log = tmp_path / 'out', tmp_path / 'curl.log'
    out.write_text('')
    log.write_text('')
    env = {k: v for k, v in os.environ.items() if k != 'TZ'}
    env.update(PATH=f'{bin_}{os.pathsep}{env["PATH"]}', GITHUB_EVENT_NAME=event, GITHUB_OUTPUT=str(out),
               GITHUB_REPOSITORY='o/r', GITHUB_REF_NAME='main', GH_TOKEN='t', FAKE_KST=kst,
               FAKE_PUB=pub, FAKE_POST=post, CURL_LOG=str(log))
    r = subprocess.run(['bash', '-e', '-c', script], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr                         # gate 가 실패하면 매시간 실패 메일
    assert re.findall(r'^go=(\w+)$', out.read_text(), re.M) == [go]
    if event != 'schedule' or int(kst[-2:]) < pb.REEL_WINDOW[0]:
        assert log.read_text() == ''                           # 시간대 밖·수동은 API 호출 없음
    else:
        assert f'/contents/reels/{kst[:10]}/published.json?ref=main' in log.read_text()


def test_reels_gate_wiring_and_no_concurrency_on_gate():
    wf = WF_REELS.read_text(encoding='utf-8')
    gate = _gate_block()
    assert '      go: ${{ steps.g.outputs.go }}' in gate and '      - id: g\n' in gate
    assert '''read -r h d <<< "$(TZ=KST-9 date '+%-H %F')"''' in gate and f'[ "$h" -lt {pb.REEL_WINDOW[0]} ]' in gate
    assert pb.REEL_WINDOW[1] == 24                             # gate 에는 끝 시각 검사가 없다(하루 끝까지)
    assert 'contents: read' in gate                            # gate 는 읽기 권한만
    assert not re.search(r'^\s*concurrency:', gate, re.M)      # 주석의 「(concurrency)」는 제외
    assert not re.search(r'^concurrency:', wf.split('\njobs:', 1)[0], re.M)


def test_card_schedule_run_is_not_limited_by_reel_window(tmp_path, monkeypatch, env):
    monkeypatch.setattr(pb, 'kst_now', lambda: datetime.datetime(2026, 11, 20, 12, 56, tzinfo=KST_TZ))   # 11-19 실측 카드 시각
    fake = install(monkeypatch, FakeIG())
    d = make_post(tmp_path, date='2026-11-20')
    assert pb.main([], root=tmp_path, env=dict(env, GITHUB_EVENT_NAME='schedule')) == 0
    assert fake.published and (d / 'published.json').exists()


class _NoNet:
    def __getattr__(self, name):
        raise AssertionError(f'네트워크 호출: requests.{name}')


def test_reel_schedule_outside_window_touches_nothing_all_hours(tmp_path, monkeypatch, capsys):
    make_reel(tmp_path, '2026-11-20')
    make_reel(tmp_path, '2026-11-21')
    before = sorted(str(p) for p in tmp_path.rglob('*'))
    monkeypatch.setattr(pb, 'requests', _NoNet())
    for day, h in [(21, 0), (21, 3), (21, 12), (21, 17)]:
        monkeypatch.setattr(pb, 'kst_now', lambda day=day, h=h: datetime.datetime(2026, 11, day, h, 13, tzinfo=KST_TZ))
        assert pb.main(['--root', 'reels'], root=tmp_path, env={'GITHUB_EVENT_NAME': 'schedule'}) == 0   # 시크릿 없이도 0
        assert '저녁 시간대' in capsys.readouterr().out
    assert sorted(str(p) for p in tmp_path.rglob('*')) == before          # 어제 몫(11-20)도 안 건드림


def test_reel_manual_run_at_3am_posts_today_and_date_recovers_missed_day(tmp_path, monkeypatch, env):
    monkeypatch.setattr(pb, 'kst_now', lambda: datetime.datetime(2026, 11, 21, 3, 0, tzinfo=KST_TZ))
    y, t = make_reel(tmp_path, '2026-11-20'), make_reel(tmp_path, '2026-11-21')
    manual = dict(env, GITHUB_EVENT_NAME='workflow_dispatch')
    install(monkeypatch, FakeIG())
    assert pb.main(['--root', 'reels'], root=tmp_path, env=manual) == 0
    assert (t / 'published.json').exists() and not (y / 'published.json').exists()
    install(monkeypatch, FakeIG())
    assert pb.main(['--root', 'reels', '--date', '2026-11-20'], root=tmp_path, env=manual) == 0
    assert (y / 'published.json').exists()
