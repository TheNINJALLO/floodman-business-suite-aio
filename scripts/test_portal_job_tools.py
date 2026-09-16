"""Additional job-tool checks, called within the disposable PHP portal fixture."""
import base64
import hashlib
import json
import sqlite3
import uuid
from contextlib import closing

import httpx


def check_tools(request, view, root, scope, job, other, image):
    base = {**scope, 'portal_job_id': str(job['portal_job_id'])}

    def state():
        response = request({**base, 'action':'job-tools'})
        assert response.status_code == 200, response.text
        return response.json()

    def mutation(kind, fields=None, **extra):
        return {**base, 'action':'job-mutate', 'kind':kind, 'mode':'add',
                'operation_id':str(uuid.uuid4()), 'fields':fields or {}, **extra}

    def success(payload):
        response = request(payload)
        assert response.status_code == 200, response.text
        return response.json()

    def remove(kind, key, identifier):
        row = next(row for row in state()[key] if row['id']==identifier)
        payload = mutation(kind, mode='remove', record_id=str(identifier), revision=row['revision'])
        success(payload); assert success(payload)['replayed']
        return payload

    assert request({**base,'action':'job-tools','workspace_id':'wrong'}).status_code == 404
    job_row=state()['job']
    edit_job=mutation('job',{'job_name':'Jordan Test','address':'12 Fictional Street','notes':'Updated portal description','default_topic':'Restoration'},
                      mode='edit',record_id=base['portal_job_id'],revision=job_row['revision'])
    success(edit_job); assert success(edit_job)['replayed']
    assert state()['job']['notes']=='Updated portal description'
    assert request(mutation('job',mode='remove',record_id=base['portal_job_id'],revision=state()['job']['revision'])).status_code==422
    note = mutation('note',{'note':'Private staff note <script>unsafe</script>'})
    note_id = success(note)['record_id']
    assert success(note)['replayed'] and len(state()['notes'])==1
    assert request({**note,'fields':{'note':'Changed replay'}}).status_code == 422
    # Simulate a crash after the DB commit but before the acknowledgement journal.
    journal = root/'data/floodman-suite'/f"operation-{note['operation_id']}.json"
    plan = json.loads(journal.read_text()); plan['status']='PREPARED'; journal.write_text(json.dumps(plan))
    success(note); assert len(state()['notes'])==1
    row = state()['notes'][0]
    edit = mutation('note',{'note':'Updated private note'},mode='edit',record_id=str(note_id),revision=row['revision'])
    success(edit)
    assert request({**edit,'operation_id':str(uuid.uuid4()),'fields':{'note':'Stale overwrite'}}).status_code == 422
    assert request({**edit,'operation_id':str(uuid.uuid4()),'portal_job_id':str(other['portal_job_id'])}).status_code == 404
    receipt = mutation('receipt',{'vendor':'Fictional hardware','amount':'12.34','notes':'Private receipt'},
                       image_base64=base64.b64encode(image).decode(), sha256=hashlib.sha256(image).hexdigest())
    receipt_id = success(receipt)['record_id']
    assert success(receipt)['replayed'] and state()['receipt_total']==12.34
    assert 'filename' not in state()['receipts'][0]
    private_receipt = view('staff-receipt',str(receipt_id),source_key=base['portal_job_id'])
    assert httpx.get(private_receipt).content==image
    assert httpx.get(private_receipt.replace('staff-receipt','photo')).status_code==403
    assert httpx.get(view('staff-receipt',str(receipt_id),source_key=str(other['portal_job_id']))).status_code==404
    for amount in ('-1', 'NaN', '1.001','1e2'):
        assert request({**receipt,'operation_id':str(uuid.uuid4()),'fields':{'amount':amount}}).status_code==422
    bad_file = {**receipt,'operation_id':str(uuid.uuid4()),'image_base64':base64.b64encode(b'<?php ?>').decode()}
    assert request(bad_file).status_code==422
    content = mutation('content',{'name':'Chair','description':'Test item','category':'Furniture','condition':'Wet'})
    content_id = success(content)['record_id']
    assert success(content)['replayed'] and len(state()['contents'])==1
    photo = mutation('photo',{'caption':'Contents photo','topic':'Restoration'},content_id=str(content_id),
                     image_base64=base64.b64encode(image).decode(),sha256=hashlib.sha256(image).hexdigest())
    photo_id = success(photo)['record_id']; assert success(photo)['replayed']
    assert state()['contents'][0]['photo_ids']==[photo_id]
    assert httpx.get(view('staff-photo',str(photo_id),source_key=base['portal_job_id'])).content==image
    video_bytes = b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 100 # Structural fixture, not a playable recording.
    video = mutation('video',{'caption':'Fictional video'},total=1,sha256=hashlib.sha256(video_bytes).hexdigest())
    chunk = {**video,'action':'video-chunk','index':0,'chunk_base64':base64.b64encode(video_bytes).decode(),'chunk_sha256':hashlib.sha256(video_bytes).hexdigest()}
    success(chunk); success(chunk)
    assert request({**chunk,'chunk_sha256':'0'*64}).status_code==422
    video_id = success(video)['record_id']; assert success(video)['replayed']
    video_url = view('staff-video',str(video_id),source_key=base['portal_job_id'])
    assert httpx.get(video_url).content==video_bytes
    ranged = httpx.get(video_url,headers={'Range':'bytes=4-11'})
    assert ranged.status_code==206 and ranged.content==video_bytes[4:12]
    assert httpx.get(video_url,headers={'Range':'bytes=999999-'}).status_code==416
    assert httpx.get(view('photo',str(video_id))).status_code==404
    assert 'Private receipt' not in httpx.get(view()).text and 'Updated private note' not in httpx.get(view()).text
    # Simulate malicious legacy database filenames; signed staff links still cannot escape the job.
    with closing(sqlite3.connect(root/'data/portal.db')) as db, db:
        filename = db.execute('SELECT filename FROM receipts WHERE id=?',(receipt_id,)).fetchone()[0]
        db.execute("UPDATE receipts SET filename='../../floodman-suite/config.php' WHERE id=?",(receipt_id,))
    assert httpx.get(private_receipt).status_code==404
    with closing(sqlite3.connect(root/'data/portal.db')) as db, db:
        db.execute('UPDATE receipts SET filename=? WHERE id=?',(filename,receipt_id))
    remove('receipt','receipts',receipt_id)
    assert (root/'data/jobs'/base['portal_job_id']/filename).is_file(), 'Removal destroyed original'
    assert state()['receipt_total']==0 and httpx.get(private_receipt).status_code==404
    replacement=success({**receipt,'operation_id':str(uuid.uuid4())})['record_id']
    assert replacement>receipt_id and httpx.get(private_receipt).status_code==404, 'Removed signed-link ID was reused'
    remove('receipt','receipts',replacement)
    remove('photo','media',photo_id)
    assert state()['contents'][0]['photo_ids']==[]
    remove('content','contents',content_id); remove('note','notes',note_id); remove('video','media',video_id)
    assert not state()['notes'] and not state()['receipts'] and not state()['contents']
    print('Job tools: notes, receipts/totals, inventory/photo links, video/ranges, CRUD, crash replay, stale edits, retained originals, and staff-only access passed')
