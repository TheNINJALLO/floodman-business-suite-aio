"""Exercise the PHP portal connector against fictional data in a disposable container."""
from __future__ import annotations

import base64
from contextlib import closing
import hashlib
import hmac
import json
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'php@sha256:afdf8b1fee58486ccc0dab5f30f634b86873d56dac985f71ba217945647c05ad'
SECRET = 'fictional-portal-test-secret-' * 3


def run():
    with tempfile.TemporaryDirectory(prefix='floodman-php-portal-') as temporary:
        root = Path(temporary)
        shutil.copytree(ROOT / 'server/external-portal', root, dirs_exist_ok=True)
        (root / 'includes/config.php').write_text("<?php return ['DB_FILE'=>__DIR__.'/../data/portal.db','JOBS_PHOTOS_DIR'=>__DIR__.'/../data/jobs/'];", encoding='utf-8')
        (root / 'data/floodman-suite/config.php').write_text("<?php return ['secret'=>'" + SECRET + "'];", encoding='utf-8')
        with closing(sqlite3.connect(root / 'data/portal.db')) as db, db:
            db.executescript('CREATE TABLE jobs(id INTEGER PRIMARY KEY,job_name TEXT,address TEXT,notes TEXT,employee_id INTEGER,client_job_id TEXT UNIQUE); CREATE TABLE photos(id INTEGER PRIMARY KEY,job_id INTEGER,filename TEXT,caption TEXT,uploaded_at TEXT,media_type TEXT);')
        container = subprocess.check_output(['docker','run','--rm','-d','-p','127.0.0.1::8080','--mount',f'type=bind,source={root},target=/app',IMAGE,'php','-S','0.0.0.0:8080','-t','/app'], text=True).strip()
        try:
            port = subprocess.check_output(['docker','port',container,'8080/tcp'], text=True).strip().split(':')[-1]
            url = f'http://127.0.0.1:{port}/api/floodman.php'
            for attempt in range(50):
                try:
                    if httpx.get(url, timeout=1).status_code == 405: break
                except httpx.HTTPError:
                    pass
                time.sleep(.2)
            else: raise AssertionError('PHP fixture did not start')

            def request(data, *, signed=True, timestamp=None):
                body = json.dumps(data, separators=(',', ':')).encode()
                timestamp = str(timestamp or int(time.time()))
                headers = {'Content-Type': 'application/json'}
                if signed:
                    headers.update({'X-Floodman-Timestamp': timestamp, 'X-Floodman-Signature': hmac.new(SECRET.encode(), timestamp.encode()+b'.'+body, hashlib.sha256).hexdigest()})
                return httpx.post(url, content=body, headers=headers)

            assert request({'action':'health'}, signed=False).status_code == 401
            assert request({'action':'health'}, timestamp=int(time.time())-400).status_code == 401
            assert request({'action':'health'}).json()['status'] == 'ready'
            payload = {'action':'upsert-job','organization_id':'fictional-org','workspace_id':'fictional-workspace','job_id':'fictional-job',
                       'customer_id':'fictional-customer','property_id':'fictional-property','customer_name':'Jordan Test','address':'12 Fictional Street'}
            first = request(payload)
            assert first.status_code == 200, first.text
            data = first.json()
            replay = request(payload).json()
            assert replay['portal_job_id'] == data['portal_job_id'] and not replay['created']
            other = request({**payload,'workspace_id':'other-workspace'}).json()
            assert other['portal_job_id'] != data['portal_job_id']
            key = data['source_key']
            def view(purpose='gallery', asset='', *, source_key=key, expiry=None):
                expires = expiry or int(time.time())+3600
                signature = hmac.new(SECRET.encode(), f'{purpose}:{source_key}:{asset}:{expires}'.encode(), hashlib.sha256).hexdigest()
                return url+'?'+urlencode({'view':purpose,'key':source_key,'asset':asset,'expires':expires,'signature':signature})
            assert httpx.get(view()).status_code == 200
            assert httpx.get(view(expiry=int(time.time())-5)).status_code == 403
            assert httpx.get(view().replace(key,other['source_key'])).status_code == 403
            image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jB6kAAAAASUVORK5CYII=')
            jobdir = root/'data/jobs'/str(data['portal_job_id'])
            jobdir.mkdir(parents=True)
            (jobdir/'photo.png').write_bytes(image)
            with closing(sqlite3.connect(root/'data/portal.db')) as db, db:
                db.execute('INSERT INTO photos VALUES(1,?,?,?,?,?)',(data['portal_job_id'],'photo.png','<script>bad()</script>','2026-09-11','photo'))
                db.execute('INSERT INTO photos VALUES(2,?,?,?,?,?)',(other['portal_job_id'],'other.png','Private other job','2026-09-11','photo'))
            gallery = httpx.get(view())
            assert '&lt;script&gt;' in gallery.text and '<script>bad()' not in gallery.text
            assert 'Private other job' not in gallery.text
            assert httpx.get(view('photo','1')).content == image
            assert httpx.get(view('photo','2')).status_code == 404
            layout = {**payload,'action':'save-layout','sha256':hashlib.sha256(image).hexdigest(),'image_base64':base64.b64encode(image).decode()}
            assert request(layout).status_code == 200
            assert httpx.get(view('layout')).content == image
            assert request({**layout,'sha256':'a'*64}).status_code == 422
            assert request({**layout,'image_base64':base64.b64encode(b'<?php ?>').decode()}).status_code == 422
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                for width, height in [(320,568),(390,844),(1440,900)]:
                    page.set_viewport_size({'width':width,'height':height})
                    page.goto(view(), wait_until='networkidle')
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                    assert page.locator('img').count() == 2
                    for rendered_image in page.locator('img').all():
                        rendered_image.scroll_into_view_if_needed()
                        page.wait_for_function('image => image.complete && image.naturalWidth > 0', arg=rendered_image.element_handle(), timeout=5000)
                    assert page.locator('img').evaluate_all('images => images.every(image => image.complete && image.naturalWidth > 0)')
                browser.close()
            with closing(sqlite3.connect(root/'data/portal.db')) as db, db:
                assert db.execute('SELECT count(*) FROM jobs').fetchone()[0] == 2
            print('PHP portal authentication, expiry, idempotency, workspace isolation, image ownership, XSS, and floor plan checks passed')
        finally:
            subprocess.run(['docker','stop',container], stdout=subprocess.DEVNULL, check=True)


if __name__ == '__main__':
    run()
