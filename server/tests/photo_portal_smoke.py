"""Fictional ERP photo access and durable upload regression checks."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import sys
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'office-console'))
from app.config import Settings
from app.photo_portal import PhotoPortal
from app.portal_connection import PortalRequestError
from app.store import OfficeStore

IMAGE = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jB6kAAAAASUVORK5CYII=')


class FakeConnection:
    enabled = True
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.requests = []
        self.failure = None

    async def request(self, action, payload):
        self.requests.append((action, payload))
        if self.failure:
            raise self.failure
        if action == 'list-jobs':
            return {'items':[{'id':42,'name':'Fictional Residence','address':'12 Test Lane'}]}
        if int(payload.get('portal_job_id') or 0) != 42:
            raise PortalRequestError(404)
        if action == 'get-job':
            return {'job':{'id':42,'job_name':'Fictional Residence','address':'12 Test Lane'}}
        if action == 'job-tools':
            return {'media':[], 'notes':[], 'receipts':[], 'contents':[], 'receipt_total':0}
        assert action == 'upload-photo'
        record = self.store.record('portal_uploads', payload['operation_id'])
        assert record and record['status'] == 'PENDING', 'Remote write preceded local business record'
        path = self.store.upload_path(record['file_id'], record['filename'])
        assert path.read_bytes() == base64.b64decode(payload['image_base64'])
        return {'photo_id':9,'sha256':payload['sha256']}


async def checks():
    with tempfile.TemporaryDirectory(prefix='floodman-photo-test-') as root:
        store = OfficeStore(root)
        owner = store.create_owner('Test Owner','owner@example.test','Fictional-Pass-2026!')
        config = replace(Settings.from_env(), external_portal_api_url='https://portal.example.test/portal/api/floodman.php', external_portal_api_token='fictional-test-secret-'*3)
        connection = FakeConnection(store, config)
        portal = PhotoPortal(connection)
        assert portal.scope(owner,'workspace')['include_legacy']
        viewer = {**owner,'role':'VIEWER'}
        assert not portal.scope(viewer,'workspace')['include_legacy']
        for user, job_id, content in [(viewer,42,IMAGE),(owner,777,IMAGE),(owner,42,b'<?php echo 1;')]:
            try:
                await portal.stage_upload(user,'workspace',job_id,str(uuid.uuid4()),content,'')
                raise AssertionError('Unsafe upload accepted')
            except (PermissionError,PortalRequestError,ValueError):
                pass
        assert not store.records('portal_uploads')
        operation = str(uuid.uuid4())
        saved = await portal.stage_upload(owner,'workspace',42,operation,IMAGE,'Test caption')
        path = store.upload_path(saved['file_id'],saved['filename'])
        assert path.exists() and saved['status'] == 'PENDING'
        replay = await portal.stage_upload(owner,'workspace',42,operation,IMAGE,'Test caption')
        assert replay['id'] == saved['id'] and len(store.records('portal_uploads')) == 1
        try:
            await portal.stage_upload(owner,'different-workspace',42,operation,IMAGE,'')
            raise AssertionError('Cross-workspace upload replay accepted')
        except ValueError:
            pass
        connection.failure = RuntimeError('Unavailable')
        await portal.sync_upload(saved)
        assert store.record('portal_uploads',operation)['status'] == 'PENDING' and path.exists()
        connection.failure = None
        await portal.sync_upload(store.record('portal_uploads',operation))
        assert store.record('portal_uploads',operation)['status'] == 'SENT' and not path.exists()
        count = len(connection.requests)
        await portal.sync_upload(store.record('portal_uploads',operation))
        assert len(connection.requests) == count
        revoked = await portal.stage_upload(owner,'workspace',42,str(uuid.uuid4()),IMAGE,'')
        original_get_user = store.get_user
        store.get_user = lambda user_id: {**original_get_user(user_id), 'status':'DISABLED'}
        await portal.sync_upload(revoked)
        assert store.record('portal_uploads',revoked['id'])['status'] == 'BLOCKED'
        store.get_user = original_get_user
        rejected = await portal.stage_upload(owner,'workspace',42,str(uuid.uuid4()),IMAGE,'')
        connection.failure = PortalRequestError(404)
        await portal.sync_upload(rejected)
        assert store.record('portal_uploads',rejected['id'])['status'] == 'FAILED'
        connection.failure = None
        page = await portal.render(owner,'workspace',job_id=42,search="'><script>bad()</script>")
        assert '<script>bad()' not in page and config.external_portal_api_token not in page
        assert 'type=\'file\'' in page and 'staff-gallery' in page
        assert "type='file'" not in await portal.render(viewer,'workspace',job_id=42)
        assert OfficeStore(root).record('portal_uploads',operation)['status'] == 'SENT'
    print('ERP photo permissions, local-first writes, retries, replay, revocation, escaping, and cleanup passed')


if __name__ == '__main__':
    asyncio.run(checks())
