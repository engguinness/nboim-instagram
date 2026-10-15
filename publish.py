#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""앤보임 인스타(@justenglish_guinness) 자동 게시기 — GitHub Actions 에서 매일 아침 08:00(KST)에 돈다.

동작: 오늘(Asia/Seoul) 날짜의 posts/<날짜>/post.json 을 읽어 캐러셀(또는 사진 1장)·릴스를 올린다.
  - Instagram API with Instagram Login (graph.instagram.com) — 컨테이너 만들기 → (릴스는 처리 대기) → media_publish
  - 미디어는 공개 URL 로 인스타가 가져간다: 기본 https://raw.githubusercontent.com/<저장소>/main/posts/<날짜>/<파일>
    (환경변수 MEDIA_BASE 로 바꿀 수 있다. 예: GitHub Pages https://<계정>.github.io/<저장소>)
  - 게시가 끝나면 posts/<날짜>/published.json 을 쓴다(워크플로가 커밋). 있으면 그날은 다시 안 올린다.

토큰: 환경변수 IG_ACCESS_TOKEN(GitHub Secret). state/token.enc(IG_TOKEN_KEY 로 암호화)가 있으면 그게 우선이다 —
  매주 월요일 refresh 작업(--refresh-token)이 갱신해서 다시 쓴다. 토큰은 어떤 로그·출력에도 찍지 않는다.
계정 확인: state/account.json 에 기록된 계정 번호(user_id)와 토큰의 계정이 같아야 게시한다 — 인스타 아이디를 바꿔도 번호는
  그대로라 계속 게시된다(2026-10-15). 기록이 없을 때(처음 한 번)만 아이디가 justenglish_guinness 인지 보고 번호를 기록한다.

사용:
    python publish.py                       # 오늘(KST) 게시
    python publish.py --date 2026-10-07     # 날짜 지정
    python publish.py --dry                 # API 호출 없이 무엇을 올릴지만 출력(미디어 URL 확인은 함)
    python publish.py --refresh-token       # 토큰 갱신 → state/token.enc

종료 코드: 0 = 게시함·게시물 없음·이미 게시됨·드라이런 / 1 = 실패(Actions 가 실패 메일을 보낸다)
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

try:
    import requests
except ImportError:          # 드라이런·테스트에서 requests 없이도 import 는 되게
    requests = None

ROOT = Path(__file__).resolve().parent
EXPECTED_USERNAME = 'justenglish_guinness'
TZ_NAME = 'Asia/Seoul'
IG_API_VERSION = os.environ.get('IG_API_VERSION') or 'v21.0'
IG_API = f'https://graph.instagram.com/{IG_API_VERSION}'
REFRESH_URL = 'https://graph.instagram.com/refresh_access_token'
USER_AGENT = 'nboim-instagram/1.0'

MAX_CAROUSEL = 10
CHILD_POLL = (30, 3)         # 이미지 컨테이너: (최대 횟수, 간격 초) — 보통 바로 끝난다
REEL_POLL = (60, 5)          # 릴스 컨테이너: 5초 간격 최대 60번 = 5분
DEDUPE_HOURS = 48            # 같은 캡션이 이 시간 안에 이미 올라가 있으면 다시 안 올린다
KDF_ITER = 200000

STATE_FILE = Path('state') / 'token.enc'
ACCOUNT_FILE = Path('state') / 'account.json'   # 계정 번호 기록 — 인스타 아이디를 바꿔도 번호는 그대로라 이걸로 계정을 확인한다


class PublishError(RuntimeError):
    pass


# ---------------------------------------------------------------- 로그·비밀값 가리기

_SECRETS = set()
_TOKEN_RE = re.compile(r'(access_token|client_secret|fb_exchange_token)=[^&\s"\']+', re.IGNORECASE)


def register_secret(value):
    if value and len(value) >= 8:
        _SECRETS.add(value)


def redact(text):
    """요청 URL 쿼리의 access_token 과, 알고 있는 토큰·키 값 자체를 가린다."""
    s = str(text if text is not None else '')
    s = _TOKEN_RE.sub(lambda m: m.group(1) + '=***', s)
    for v in _SECRETS:
        s = s.replace(v, '***')
    return s


def log(msg=''):
    print(redact(msg), flush=True)


# ---------------------------------------------------------------- 시간

def kst_now():
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(TZ_NAME)
    except Exception:        # tzdata 가 없는 환경 대비 — 한국은 서머타임이 없어 고정 +9 로 충분하다
        tz = datetime.timezone(datetime.timedelta(hours=9))
    return datetime.datetime.now(tz)


def valid_date(s):
    try:
        return datetime.date.fromisoformat(s).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f'날짜는 YYYY-MM-DD 형식이어야 합니다: {s!r}')


# ---------------------------------------------------------------- HTTP (requests 한 겹)

def _http(method, url, params=None, data=None, timeout=30, retries=1):
    """(상태코드, JSON dict) 를 돌려준다. 연결 오류는 ApiError 로(메시지에서 토큰 가림).
    retries>1 이면 연결 오류·5xx 에서 다시 시도한다(조회용 — 게시 요청은 retries=1)."""
    if requests is None:
        raise PublishError('requests 가 설치돼 있지 않습니다 (pip install requests)')
    last = None
    for attempt in range(retries):
        try:
            r = getattr(requests, method)(url, params=params, data=data, timeout=timeout,
                                          headers={'User-Agent': USER_AGENT})
        except requests.RequestException as e:
            last = PublishError('연결 오류: ' + redact(str(e))[:300])
            if attempt < retries - 1:
                time.sleep(2)
                continue
            raise last from None
        if r.status_code >= 500 and attempt < retries - 1:
            time.sleep(2)
            continue
        try:
            body = r.json()
        except Exception:
            body = {'error': {'message': redact(getattr(r, 'text', '') or '')[:200]}}
        return r.status_code, body
    raise last  # pragma: no cover


def api_get(url, params, token, retries=3):
    return _http('get', url, params=dict(params, access_token=token), retries=retries)


def api_post(url, data, token):
    return _http('post', url, data=dict(data, access_token=token), retries=1)


def api_error_text(body, status):
    err = body.get('error') if isinstance(body, dict) else None
    if not isinstance(err, dict):
        return f'HTTP {status}'
    msg = err.get('error_user_msg') or err.get('message') or f'HTTP {status}'
    code = err.get('code')
    sub = err.get('error_subcode')
    tag = ''.join([f'#{code}' if code else '', f'/{sub}' if sub else ''])
    return redact(f'({tag}) {msg}' if tag else msg)[:300]


# ---------------------------------------------------------------- 토큰 (시크릿 / state/token.enc)

def fingerprint(secret):
    return hashlib.sha256((secret or '').encode('utf-8')).hexdigest()[:16]


def _openssl(decrypt, data, key):
    cmd = ['openssl', 'enc', '-d' if decrypt else '-e', '-aes-256-cbc', '-pbkdf2', '-iter', str(KDF_ITER),
           '-md', 'sha256', '-salt', '-a', '-pass', 'env:NBOIM_TOKEN_KEY']
    env = dict(os.environ, NBOIM_TOKEN_KEY=key)       # 키는 명령줄이 아니라 환경변수로만 넘긴다
    r = subprocess.run(cmd, input=data.encode('utf-8'), capture_output=True, env=env)
    if r.returncode != 0:
        raise PublishError('openssl ' + ('복호화' if decrypt else '암호화') + ' 실패 (키가 다르거나 파일이 깨짐)')
    return r.stdout.decode('utf-8')


def encrypt_text(plain, key):
    """AES-256-CBC + PBKDF2(SHA-256, 200000회) + salt, base64 텍스트. openssl 호환:
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -a -pass env:… < token.enc"""
    return _openssl(False, plain, key)


def decrypt_text(enc, key):
    return _openssl(True, enc, key)


def load_token(root, env=None):
    """쓸 토큰을 고른다. 반환: (token, source) — source: 'token.enc' | 'secret'.
    token.enc 가 있고 복호화되며, 기록된 시크릿 지문이 지금 시크릿과 같을 때만 token.enc 를 쓴다
    (대표가 시크릿을 새 토큰으로 바꿨으면 시크릿이 더 새 것이므로 시크릿을 쓴다)."""
    env = os.environ if env is None else env
    secret = (env.get('IG_ACCESS_TOKEN') or '').strip()
    key = env.get('IG_TOKEN_KEY') or ''
    register_secret(secret)
    register_secret(key)
    enc_path = Path(root) / STATE_FILE
    if enc_path.is_file():
        if not key:
            log('경고: state/token.enc 가 있지만 IG_TOKEN_KEY 시크릿이 없어 IG_ACCESS_TOKEN 을 씁니다.')
        else:
            try:
                rec = json.loads(decrypt_text(enc_path.read_text(encoding='utf-8'), key))
                tok = (rec.get('access_token') or '').strip()
                if not tok:
                    raise PublishError('token.enc 안에 토큰이 없음')
            except Exception as e:
                log(f'경고: state/token.enc 를 읽지 못해 IG_ACCESS_TOKEN 을 씁니다 ({redact(e)})')
            else:
                register_secret(tok)
                if secret and rec.get('src_fp') != fingerprint(secret):
                    log('알림: IG_ACCESS_TOKEN 시크릿이 token.enc 를 만든 뒤에 바뀐 것으로 보여 시크릿 토큰을 씁니다.')
                else:
                    return tok, 'token.enc'
    if not secret:
        raise PublishError('IG_ACCESS_TOKEN 시크릿이 설정돼 있지 않습니다 (GitHub 저장소 Settings → Secrets and variables → Actions)')
    return secret, 'secret'


def save_token_record(root, record, key):
    path = Path(root) / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    enc = encrypt_text(json.dumps(record, ensure_ascii=False), key)
    tmp = path.with_suffix('.enc.tmp')
    tmp.write_text(enc if enc.endswith('\n') else enc + '\n', encoding='utf-8')
    os.replace(tmp, path)


def load_account(root):
    """state/account.json 의 계정 기록 {user_id, username, verified_at}. 없거나 깨졌으면 None."""
    p = Path(root) / ACCOUNT_FILE
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get('user_id') else None


def save_account(root, user_id, username):
    p = Path(root) / ACCOUNT_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {'user_id': str(user_id), 'username': username, 'verified_at': kst_now().strftime('%Y-%m-%d %H:%M')}
    tmp = p.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, p)


def verify_account(token, root=None):
    """토큰이 가리키는 계정을 확인한다. 반환: user_id. 계정이 다르면 PublishError(게시 안 함).

    - state/account.json(계정 번호 기록)이 있으면 **계정 번호**로 확인한다. 인스타 아이디(username)를 바꿔도 번호는
      그대로라 계속 게시되고, 바뀐 아이디는 기록에 고쳐 둔다(워크플로가 state/ 를 커밋).
    - 기록이 없으면(처음 한 번) 아이디가 EXPECTED_USERNAME 과 같을 때만 통과하고, 그때 번호를 기록한다.
    """
    root = Path(root) if root else ROOT
    st, d = api_get(f'{IG_API}/me', {'fields': 'user_id,username'}, token)
    if st != 200 or 'error' in d:
        raise PublishError('토큰으로 계정을 확인하지 못함: ' + api_error_text(d, st))
    username = d.get('username') or ''
    user_id = d.get('user_id') or d.get('id')
    if not user_id:
        raise PublishError('계정 id 를 받지 못함')
    user_id = str(user_id)
    rec = load_account(root)
    if rec:
        if str(rec['user_id']) != user_id:
            raise PublishError(f'토큰의 계정 번호({user_id})가 기록된 계정(@{rec.get("username")}, 번호 {rec["user_id"]})과 다름 — 게시하지 않습니다')
        if username and username != rec.get('username'):
            log(f'아이디 변경 감지: @{rec.get("username")} → @{username} (계정 번호 {user_id} 동일 — 계속 게시합니다)')
            save_account(root, user_id, username)
        log(f'계정 확인 : @{username or rec.get("username")} OK (번호 {user_id})')
        return user_id
    if username != EXPECTED_USERNAME:
        raise PublishError(f'토큰의 계정이 {EXPECTED_USERNAME} 가 아님(조회된 계정: {username or "알 수 없음"}) — 게시하지 않습니다')
    save_account(root, user_id, username)
    log(f'계정 확인 : @{username} OK (번호 {user_id} 를 state/account.json 에 기록 — 앞으로는 번호로 확인)')
    return user_id


def refresh_token(root, env=None):
    """토큰을 갱신해 state/token.enc 로 저장한다(매주 월요일 작업). 반환 종료 코드."""
    env = os.environ if env is None else env
    key = env.get('IG_TOKEN_KEY') or ''
    if not key:
        log('실패: IG_TOKEN_KEY 시크릿이 없어 token.enc 를 만들 수 없습니다.')
        return 1
    token, source = load_token(root, env)
    log(f'토큰 갱신 시도 (현재 토큰 출처: {source})')
    verify_account(token, root)                # 갱신 전에 계정부터 확인 — 설정 확인용으로 수동 실행해도 의미가 있게
    st, d = api_get(REFRESH_URL, {'grant_type': 'ig_refresh_token'}, token)
    if st != 200 or 'error' in d or not d.get('access_token'):
        msg = api_error_text(d, st)
        if re.search(r'24\s*hour', msg, re.IGNORECASE):
            log('알림: 토큰 발급 24시간 이내라 이번 주는 갱신을 건너뜁니다. (' + msg + ')')
            return 0
        log('실패: 토큰 갱신 — ' + msg)
        return 1
    new_token = d['access_token']
    register_secret(new_token)
    verify_account(new_token, root)
    now = kst_now()
    expires_in = int(d.get('expires_in') or 0)
    secret = (env.get('IG_ACCESS_TOKEN') or '').strip()
    record = {'access_token': new_token, 'refreshed_at': now.isoformat(timespec='seconds'),
              'expires_at': (now + datetime.timedelta(seconds=expires_in)).isoformat(timespec='seconds') if expires_in else None,
              'src_fp': fingerprint(secret) if secret else None}
    save_token_record(root, record, key)
    log(f'완료: state/token.enc 갱신 (유효 {expires_in // 86400}일)' if expires_in else '완료: state/token.enc 갱신')
    return 0


# ---------------------------------------------------------------- 게시물 읽기

def safe_name(name):
    if not isinstance(name, str) or not name or '/' in name or '\\' in name or name.startswith('.'):
        raise PublishError(f'post.json 의 파일 이름이 이상함: {name!r}')
    return name


def load_post(post_dir):
    """post.json 과 캡션을 읽고 파일이 다 있는지 확인. 반환: dict(type, files, caption, ...)."""
    post_dir = Path(post_dir)
    try:
        post = json.loads((post_dir / 'post.json').read_text(encoding='utf-8'))
    except Exception as e:
        raise PublishError(f'post.json 을 읽지 못함: {e}')
    ptype = post.get('type')
    cap_name = safe_name(post.get('caption') or 'caption.txt')
    try:
        caption = (post_dir / cap_name).read_text(encoding='utf-8-sig').strip()
    except Exception as e:
        raise PublishError(f'캡션을 읽지 못함({cap_name}): {e}')
    if not caption:
        raise PublishError('캡션이 비어 있음')
    if ptype == 'carousel':
        images = [safe_name(x) for x in post.get('images') or []]
        if not images:
            raise PublishError('post.json 에 images 가 없음')
        if len(images) > MAX_CAROUSEL:
            raise PublishError(f'이미지 {len(images)}장 — 캐러셀은 최대 {MAX_CAROUSEL}장')
        files = images
    elif ptype == 'reel':
        video, cover = safe_name(post.get('video')), safe_name(post.get('cover'))
        files = [video, cover]
    else:
        raise PublishError(f'알 수 없는 post.json type: {ptype!r}')
    for f in files:
        if not (post_dir / f).is_file():
            raise PublishError(f'파일이 없음: {post_dir.name}/{f}')
    post['_caption'] = caption
    return post


def media_base(repo=None, env=None):
    env = os.environ if env is None else env
    base = (env.get('MEDIA_BASE') or '').strip().rstrip('/')
    if base:
        return base
    repo = repo or env.get('GITHUB_REPOSITORY')
    if not repo:
        raise PublishError('저장소를 알 수 없음 — GITHUB_REPOSITORY 환경변수, --repo, 또는 MEDIA_BASE 가 필요합니다')
    branch = (env.get('MEDIA_BRANCH') or 'main').strip()
    return f'https://raw.githubusercontent.com/{repo}/{branch}'


def media_url(base, date, filename):
    return f'{base}/posts/{date}/{quote(filename)}'


def check_media_urls(urls, kinds):
    """공개 URL 확인. 반환: (문제 목록, 경고 목록). 문제 = 200 이 아님(게시 중단 사유), 경고 = content-type 이상."""
    problems, warns = [], []
    for url, kind in zip(urls, kinds):
        short = url.rsplit('/posts/', 1)[-1]
        try:
            st, ctype = _head(url)
        except PublishError as e:
            problems.append(f'{short}: {e}')
            continue
        if st != 200:
            problems.append(f'{short}: HTTP {st}')
            continue
        if not ctype.startswith(kind + '/'):
            hint = ' — raw.githubusercontent 는 mp4 를 application/octet-stream 으로 줄 수 있음(README: GitHub Pages 로 전환)' if kind == 'video' else ''
            warns.append(f'{short}: Content-Type {ctype or "없음"} ({kind}/ 아님){hint}')
    return problems, warns


def _head(url):
    """(상태코드, content-type). HEAD 가 막히면(405/403/501) GET 으로 헤더만 본다."""
    if requests is None:
        raise PublishError('requests 가 설치돼 있지 않습니다')
    last = None
    for attempt in range(3):
        try:
            r = requests.head(url, timeout=20, allow_redirects=True, headers={'User-Agent': USER_AGENT})
            if r.status_code in (403, 405, 501):
                r = requests.get(url, timeout=20, allow_redirects=True, stream=True, headers={'User-Agent': USER_AGENT})
                r.close()
        except requests.RequestException as e:
            last = PublishError('연결 오류: ' + redact(str(e))[:200])
            time.sleep(2)
            continue
        if r.status_code >= 500 and attempt < 2:
            time.sleep(2)
            continue
        return r.status_code, (r.headers.get('Content-Type') or '').split(';')[0].strip().lower()
    raise last


# ---------------------------------------------------------------- 인스타 게시

def create_container(token, user_id, fields, label):
    st, d = api_post(f'{IG_API}/{user_id}/media', fields, token)
    if st != 200 or 'id' not in d:
        raise PublishError(f'{label} 컨테이너 생성 실패: ' + api_error_text(d, st))
    return d['id']


def wait_container(token, container_id, label, polls, interval):
    """status_code 가 FINISHED 가 될 때까지 interval 초 간격으로 최대 polls 번 본다. ERROR·EXPIRED·시간 초과면 PublishError."""
    last, errors = None, 0
    for i in range(polls):
        st, d = api_get(f'{IG_API}/{container_id}', {'fields': 'status_code,status'}, token, retries=2)
        if st == 200 and 'error' not in d:
            errors = 0
            last = d.get('status_code')
            if last == 'FINISHED':
                return
            if last in ('ERROR', 'EXPIRED'):
                detail = redact(str(d.get('status') or ''))[:200]
                raise PublishError(f'{label} 처리 실패({last}){": " + detail if detail else ""}')
        else:
            errors += 1
            if errors >= 3:
                raise PublishError(f'{label} 상태 조회 실패: ' + api_error_text(d, st))
        if i < polls - 1:
            time.sleep(interval)
    raise PublishError(f'{label} 가 {polls * interval}초 안에 FINISHED 되지 않음(마지막 상태: {last})')


def prepare_carousel(token, user_id, image_urls, caption):
    """사진 1장이면 단일 IMAGE 컨테이너, 2~10장이면 자식 컨테이너 → 부모(CAROUSEL). 반환: creation_id."""
    n = len(image_urls)
    if n == 1:
        cid = create_container(token, user_id, {'image_url': image_urls[0], 'caption': caption}, '사진')
        wait_container(token, cid, '사진', *CHILD_POLL)
        return cid
    if not 2 <= n <= MAX_CAROUSEL:
        raise PublishError(f'캐러셀 이미지는 1~{MAX_CAROUSEL}장 (입력 {n}장)')
    children = []
    for i, url in enumerate(image_urls, start=1):
        children.append(create_container(token, user_id, {'image_url': url, 'is_carousel_item': 'true'},
                                         f'자식 {i}/{n}'))
    for i, cid in enumerate(children, start=1):
        wait_container(token, cid, f'자식 {i}/{n}', *CHILD_POLL)
    parent = create_container(token, user_id, {'media_type': 'CAROUSEL', 'children': ','.join(children),
                                               'caption': caption}, '캐러셀')
    wait_container(token, parent, '캐러셀', *CHILD_POLL)
    return parent


def prepare_reel(token, user_id, video_url, cover_url, caption):
    fields = {'media_type': 'REELS', 'video_url': video_url, 'caption': caption, 'share_to_feed': 'true'}
    if cover_url:
        fields['cover_url'] = cover_url
    cid = create_container(token, user_id, fields, '릴스')
    wait_container(token, cid, '릴스', *REEL_POLL)
    return cid


def do_publish(token, user_id, creation_id):
    st, d = api_post(f'{IG_API}/{user_id}/media_publish', {'creation_id': creation_id}, token)
    if st != 200 or 'id' not in d:
        raise PublishError('media_publish 실패: ' + api_error_text(d, st))
    return d['id']


def wait_permalink(token, media_id, tries=4, pause=3):
    for i in range(tries):
        try:
            st, d = api_get(f'{IG_API}/{media_id}', {'fields': 'permalink'}, token, retries=1)
            if st == 200 and d.get('permalink'):
                return d['permalink']
        except PublishError:
            pass
        if i < tries - 1:
            time.sleep(pause)
    return ''


def _norm_caption(s):
    return re.sub(r'\s+', ' ', s or '').strip()[:300]


def find_recent_same_caption(token, user_id, caption, now=None):
    """최근 게시물 중 같은 캡션이 DEDUPE_HOURS 시간 안에 올라간 게 있으면 그 글(dict), 없으면 None.
    조회가 실패하면 PublishError — 호출부가 경고로 처리한다."""
    st, d = api_get(f'{IG_API}/{user_id}/media', {'fields': 'id,caption,permalink,timestamp', 'limit': 10}, token)
    if st != 200 or 'error' in d:
        raise PublishError('최근 게시물 조회 실패: ' + api_error_text(d, st))
    now = now or datetime.datetime.now(datetime.timezone.utc)
    want = _norm_caption(caption)
    for m in d.get('data') or []:
        if _norm_caption(m.get('caption')) != want:
            continue
        try:
            ts = datetime.datetime.strptime(m.get('timestamp') or '', '%Y-%m-%dT%H:%M:%S%z')
        except ValueError:
            return m                       # 시각을 모르면 안전 쪽(중복으로 본다)
        if abs((now - ts).total_seconds()) <= DEDUPE_HOURS * 3600:
            return m
    return None


def write_published(post_dir, media_id, permalink):
    rec = {'media_id': media_id, 'permalink': permalink, 'published_at': kst_now().isoformat(timespec='seconds')}
    (Path(post_dir) / 'published.json').write_text(json.dumps(rec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return rec


# ---------------------------------------------------------------- 본 흐름

def describe_plan(date, post, urls, env, root):
    caption = post['_caption']
    first = caption.split('\n', 1)[0]
    log(f'날짜     : {date} ({TZ_NAME})')
    kind = '릴스(REELS)' if post['type'] == 'reel' else f'캐러셀 {len(post["images"])}장' if len(post['images']) > 1 else '사진 1장'
    log(f'종류     : {kind}')
    log(f'원본     : {post.get("source", "")}')
    log(f'캡션     : {len(caption)}자 — "{first[:40]}{"…" if len(first) > 40 else ""}"')
    for u in urls:
        log(f'미디어   : {u}')
    has_enc = (Path(root) / STATE_FILE).is_file()
    log('시크릿   : IG_ACCESS_TOKEN {} · IG_TOKEN_KEY {} · state/token.enc {}'.format(
        '있음' if (env.get('IG_ACCESS_TOKEN') or '').strip() else '없음',
        '있음' if env.get('IG_TOKEN_KEY') else '없음', '있음' if has_enc else '없음'))


def run(args, root=None, env=None):
    root = Path(root) if root else ROOT
    env = os.environ if env is None else env
    date = args.date or kst_now().date().isoformat()
    post_dir = root / 'posts' / date

    if not (post_dir / 'post.json').is_file():
        log(f'{date}: 오늘 게시물 없음 — 아무것도 하지 않습니다.')
        return 0
    if (post_dir / 'published.json').is_file():
        log(f'{date}: 이미 게시됨(published.json) — 다시 올리지 않습니다.')
        return 0

    post = load_post(post_dir)
    base = media_base(args.repo, env)
    if post['type'] == 'reel':
        files, kinds = [post['video'], post['cover']], ['video', 'image']
    else:
        files, kinds = post['images'], ['image'] * len(post['images'])
    urls = [media_url(base, date, f) for f in files]

    if args.dry:
        log('[드라이런] 인스타 API 를 호출하지 않습니다.')
        describe_plan(date, post, urls, env, root)
        if args.no_url_check:
            log('미디어 URL 확인: 건너뜀(--no-url-check)')
        else:
            problems, warns = check_media_urls(urls, kinds)
            for w in warns:
                log(f'경고     : {w}')
            for p in problems:
                log(f'문제     : {p}')
            log('미디어 URL 확인: ' + ('모두 200' if not problems else f'{len(problems)}개 접근 안 됨 — 저장소를 푸시했는지·공개 저장소인지 확인'))
        log('[드라이런] 끝 — 실제 게시는 하지 않았습니다.')
        return 0

    token, source = load_token(root, env)
    log(f'토큰 출처 : {source}')
    user_id = verify_account(token, root)

    problems, warns = check_media_urls(urls, kinds)
    for w in warns:
        log(f'경고: {w}')
    if problems:
        raise PublishError('미디어 URL 에 접근할 수 없음 — ' + '; '.join(problems))

    caption = post['_caption']
    try:
        dup = find_recent_same_caption(token, user_id, caption)
    except PublishError as e:
        log(f'경고: 중복 확인을 못 했습니다({e}) — 계속 진행합니다.')
        dup = None
    if dup:
        log(f'이미 같은 캡션의 글이 올라가 있음({dup.get("permalink", dup.get("id"))}) — 다시 올리지 않고 기록만 남깁니다.')
        write_published(post_dir, dup.get('id', ''), dup.get('permalink', ''))
        return 0

    if post['type'] == 'reel':
        creation_id = prepare_reel(token, user_id, urls[0], urls[1], caption)
    else:
        creation_id = prepare_carousel(token, user_id, urls, caption)
    log(f'컨테이너 준비 완료({creation_id}) — 발행합니다.')

    try:
        media_id = do_publish(token, user_id, creation_id)
    except PublishError as e:
        # 응답을 못 받았어도 실제로는 올라갔을 수 있다 — 잠시 뒤 최근 글에서 같은 캡션을 찾아 본다.
        time.sleep(5)
        try:
            found = find_recent_same_caption(token, user_id, caption)
        except PublishError:
            found = None
        if not found:
            raise
        log(f'발행 응답은 실패였지만 글이 올라가 있음({e}) — 성공으로 처리합니다.')
        write_published(post_dir, found.get('id', ''), found.get('permalink', ''))
        return 0

    write_published(post_dir, media_id, '')                      # permalink 조회가 실패해도 게시 기록은 남긴다
    permalink = wait_permalink(token, media_id)
    if permalink:
        write_published(post_dir, media_id, permalink)
    log(f'게시 완료: {permalink or media_id}')
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description='앤보임 인스타 자동 게시기')
    ap.add_argument('--date', type=valid_date, help='게시할 날짜 YYYY-MM-DD (기본: 오늘, Asia/Seoul)')
    ap.add_argument('--dry', action='store_true', help='API 호출 없이 무엇을 올릴지만 출력')
    ap.add_argument('--repo', help='owner/repo — 미디어 URL 용(기본: GITHUB_REPOSITORY 환경변수)')
    ap.add_argument('--no-url-check', action='store_true', help='--dry 에서 미디어 URL 확인(HEAD 요청)도 하지 않음')
    ap.add_argument('--refresh-token', action='store_true', help='토큰을 갱신해 state/token.enc 로 저장(매주 월요일 작업)')
    return ap


def main(argv=None, root=None, env=None):
    args = build_parser().parse_args(argv)
    try:
        if args.refresh_token:
            return refresh_token(Path(root) if root else ROOT, env)
        return run(args, root, env)
    except PublishError as e:
        log(f'실패: {e}')
        return 1
    except Exception as e:            # 예상 밖 오류도 토큰이 새지 않게 가려서 한 줄로
        log(f'실패(예상 밖 오류 {type(e).__name__}): {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
