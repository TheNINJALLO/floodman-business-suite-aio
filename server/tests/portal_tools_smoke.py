"""Fictional local-first job actions, chunked media, permissions and retry checks."""
import asyncio
import base64
import hashlib
import tempfile
import uuid
from dataclasses import replace

from photo_portal_smoke import FakeConnection, IMAGE
from app.config import Settings
from app.photo_portal import PhotoPortal
from app.portal_tools import CHUNK, PortalTools
from app.portal_connection import PortalRequestError
from app.store import OfficeStore


class ToolsConnection(FakeConnection):
    async def request(self, action, payload):
        if action not in ('job-mutate', 'video-chunk'):
            return await super().request(action,payload)
        if self.failure:
            raise self.failure
        self.requests.append((action,payload))
        record = self.store.record('portal_actions',payload['operation_id'])
        assert record and record['status']=='PENDING', 'Remote operation preceded local write'
        if action=='video-chunk':
            assert hashlib.sha256(base64.b64decode(payload['chunk_base64'])).hexdigest()==payload['chunk_sha256']
            return {'index':payload['index'],'sha256':payload['chunk_sha256']}
        if 'image_base64' in payload:
            assert hashlib.sha256(base64.b64decode(payload['image_base64'])).hexdigest()==payload['sha256']
        return {'record_id':7,'sha256':payload.get('sha256')}


async def checks():
    with tempfile.TemporaryDirectory(prefix='floodman-job-tools-') as temporary:
        store = OfficeStore(temporary)
        owner = store.create_owner('Fictional Owner','owner@example.test','Fictional-Pass-2026!')
        config = replace(Settings.from_env(),external_portal_api_url='https://portal.example.test/api/floodman.php',external_portal_api_token='fictional-'*8)
        connection = ToolsConnection(store,config)
        tools = PortalTools(PhotoPortal(connection))
        def payload(kind='note', **extra):
            return {'kind':kind, 'operation_id':str(uuid.uuid4()), 'fields':{'note':'Fictional note'}, **extra}
        for role in ('TECHNICIAN','VIEWER','BILLING','OFFICE_MANAGER','OWNER'):
            user={**owner,'role':role}
            assert tools.allowed(user,'receipt') == (role in ('TECHNICIAN','OFFICE_MANAGER','OWNER'))
            assert tools.allowed(user,'receipt','remove') == (role in ('OFFICE_MANAGER','OWNER'))
        for invalid in (payload('receipt',fields={'amount':'NaN'},size=100),payload('receipt',fields={'amount':'-1'},size=100),
                        payload('video',fields={},size=101*1024*1024),payload(mode='remove',record_id='1',revision='a'*64),payload(fields={'note':''})):
            try:
                await tools.stage(owner,'workspace',42,invalid)
                raise AssertionError('Invalid action accepted')
            except ValueError:
                pass
        note = payload()
        record = await tools.stage(owner,'workspace',42,note)
        assert record['status']=='PENDING'
        assert (await tools.stage(owner,'workspace',42,note))['id']==record['id']
        for user, workspace, job in [({**owner,'role':'VIEWER'},'workspace',42),(owner,'other',42),(owner,'workspace',999)]:
            try:
                await tools.stage(user,workspace,job,note)
                raise AssertionError('Cross-scope action accepted')
            except (ValueError,PermissionError,PortalRequestError):
                pass
        connection.failure=RuntimeError('Provider unavailable')
        await tools.sync(record)
        assert store.record('portal_actions',record['id'])['status']=='PENDING'
        connection.failure=None
        await tools.sync(store.record('portal_actions',record['id']))
        assert store.record('portal_actions',record['id'])['status']=='SENT'
        photo=payload('photo',fields={'caption':'Fictional photograph'},size=len(IMAGE))
        record=await tools.stage(owner,'workspace',42,photo)
        assert record['status']=='STAGING'
        record=tools.chunk(owner,'workspace',42,record['id'],0,IMAGE)
        assert record['status']=='PENDING'
        assert tools.chunk(owner,'workspace',42,record['id'],0,IMAGE)['id']==record['id']
        try:
            tools.chunk(owner,'workspace',42,record['id'],0,b'X'*len(IMAGE))
            raise AssertionError('Changed chunk accepted')
        except ValueError:
            pass
        path=store.upload_path(record['file_id'],record['filename'])
        assert path.is_relative_to(store.upload_root) and path.read_bytes()==IMAGE
        await tools.sync(record)
        assert store.record('portal_actions',record['id'])['status']=='SENT' and not path.exists()
        data=b'\x00\x00\x00\x18ftypmp42'+b'\x00'*(CHUNK+10)
        video=payload('video',fields={},size=len(data))
        record=await tools.stage(owner,'workspace',42,video)
        tools.chunk(owner,'workspace',42,record['id'],0,data[:CHUNK])
        # Restart while a large video is incomplete; resume the same operation.
        store=OfficeStore(temporary); connection.store=store; tools=PortalTools(PhotoPortal(connection))
        record=tools.chunk(owner,'workspace',42,record['id'],1,data[CHUNK:])
        assert record['status']=='PENDING'
        await tools.sync(record)
        record=store.record('portal_actions',record['id'])
        assert record['status']=='PENDING' and record['remote_chunk']==1
        await tools.sync(record)
        assert store.record('portal_actions',record['id'])['status']=='SENT'
        for kind, fields in [('receipt',{'amount':'12.34'}),('content',{'name':'Fictional chair'}),('note',{'note':'Private'})]:
            action=payload(kind,fields=fields,**({'size':len(IMAGE)} if kind=='receipt' else {}))
            row=await tools.stage(owner,'workspace',42,action)
            if kind=='receipt': row=tools.chunk(owner,'workspace',42,row['id'],0,IMAGE)
            await tools.sync(row)
            assert store.record('portal_actions',row['id'])['status']=='SENT'
        revoked=await tools.stage(owner,'workspace',42,payload())
        original=store.get_user
        store.get_user=lambda key:{**original(key),'status':'DISABLED'}
        await tools.sync(revoked)
        assert store.record('portal_actions',revoked['id'])['status']=='BLOCKED'
        store.get_user=original
        rejected=await tools.stage(owner,'workspace',42,payload())
        connection.failure=PortalRequestError(422)
        await tools.sync(rejected)
        assert store.record('portal_actions',rejected['id'])['status']=='FAILED'
        connection.failure=None
        for tab in ('photos','videos','notes','receipts','contents'):
            rendered=await tools.render(owner,'workspace',42,tab)
            assert config.external_portal_api_token not in rendered and 'Job tools' in rendered
            assert "<form method='post' action='/office/photo-portal/42/actions'" in rendered
            assert "type='submit' disabled" in rendered, 'Forms must fail closed before upload handlers attach'
        assert 'staff-receipt' in tools.asset(42,'receipt',1)
        assert 'staff-photo' in tools.asset(42,'photo',1)
    print('Job tools: local-first actions, receipt validation, permission/revocation, chunk replay, restart resume, video fairness and cleanup passed')


if __name__=='__main__':
    asyncio.run(checks())
