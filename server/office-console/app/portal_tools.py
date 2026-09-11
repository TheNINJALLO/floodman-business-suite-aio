from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from decimal import Decimal
from urllib.parse import urlencode

from .auth import has_permission
from .portal_connection import PortalRequestError
from .ui import esc

CHUNK = 4 * 1024 * 1024
TABS = {'photos': 'Photos', 'videos': 'Videos', 'notes': 'Notes', 'receipts': 'Receipts', 'contents': 'Contents'}
FIELDS = {'photo': {'caption': 1000, 'topic': 200}, 'video': {'caption': 1000, 'topic': 200},
          'receipt': {'vendor': 200, 'amount': 20, 'notes': 5000}, 'note': {'note': 10000},
          'content': {'name': 200, 'description': 5000, 'category': 200, 'condition': 200},
          'job': {'job_name': 200, 'address': 1000, 'notes': 5000, 'default_topic': 200}}


class PortalTools:
    def __init__(self, portal):
        self.portal, self.store, self.settings = portal, portal.store, portal.settings

    @staticmethod
    def allowed(user, kind, mode='add'):
        if not has_permission(user, 'properties.view'):
            return False
        if has_permission(user, 'properties.manage'):
            return True
        return mode == 'add' and (has_permission(user, 'portal.upload') or kind == 'note' and has_permission(user, 'notes.manage'))

    def asset(self, job, kind, identifier):
        purpose = {'photo':'staff-photo', 'receipt':'staff-receipt', 'video':'staff-video'}[kind]
        expires = int(time.time()) + 600
        signature = hmac.new(self.settings.external_portal_api_token.encode(), f'{purpose}:{job}:{identifier}:{expires}'.encode(), hashlib.sha256).hexdigest()
        return self.settings.external_portal_api_url + '?' + urlencode(dict(view=purpose, key=job, asset=identifier, expires=expires, signature=signature))

    async def state(self, user, workspace, job):
        await self.portal.job(user, workspace, job)
        return await self.portal.connection.request('job-tools', {**self.portal.scope(user, workspace), 'portal_job_id': str(job)})

    async def stage(self, user, workspace, job, payload):
        kind, mode = str(payload.get('kind', '')), str(payload.get('mode', 'add'))
        if kind not in FIELDS or mode not in ('add', 'edit', 'remove'):
            raise ValueError('Choose a valid job tool.')
        if kind == 'job' and mode != 'edit':
            raise ValueError('Create jobs through the ERP customer workflow.')
        if not self.allowed(user, kind, mode):
            raise PermissionError('Your role cannot make this change.')
        await self.portal.job(user, workspace, job)
        operation = str(uuid.UUID(str(payload.get('operation_id', ''))))
        raw_fields = payload.get('fields', {})
        if not isinstance(raw_fields, dict):
            raise ValueError('Invalid fields.')
        fields = {}
        if mode != 'remove':
            for key, limit in FIELDS[kind].items():
                value = raw_fields.get(key, '')
                if not isinstance(value, str) or len(value.encode()) > limit:
                    raise ValueError('One of the fields is too long.')
                fields[key] = value.strip()
            if kind in ('note', 'content') and not fields['note' if kind == 'note' else 'name']:
                raise ValueError('Enter the note or item name.')
            if kind == 'job' and (not fields['job_name'] or not fields['address']):
                raise ValueError('Enter the job name and address.')
            if kind == 'receipt' and fields['amount']:
                import re
                if not re.fullmatch(r'\d{1,8}(\.\d{1,2})?', fields['amount']):
                    raise ValueError('Enter a positive amount with at most two decimal places.')
        identifier, revision = '', ''
        if mode != 'add':
            identifier, revision = str(payload.get('record_id', '')), str(payload.get('revision', ''))
            if not identifier.isdigit() or len(revision) != 64:
                raise ValueError('Refresh this job before editing.')
            if mode == 'remove' and payload.get('confirmed') is not True:
                raise ValueError('Confirm removal first.')
        upload = mode == 'add' and kind in ('photo', 'receipt', 'video')
        size = payload.get('size', 0)
        if upload and (type(size) is not int or size <= 0 or size > (100 if kind == 'video' else 12) * 1024 * 1024):
            raise ValueError('Photos and receipt images can be up to 12 MB; videos up to 100 MB.')
        content_id = str(payload.get('content_id') or '') if kind == 'photo' else ''
        if content_id and not content_id.isdigit():
            raise ValueError('Choose a valid contents item.')
        values = dict(id=operation, operation_id=operation, workspace_id=workspace, portal_job_id=job,
                      actor_id=str(user['id']), kind=kind, mode=mode, fields=fields, record_id=identifier,
                      revision=revision, size=size if upload else 0, content_id=content_id)
        with self.store.lock:
            old = self.store.record('portal_actions', operation)
            if old:
                if any(old.get(key) != value for key, value in values.items()):
                    raise ValueError('This operation reference was already used. Refresh and try again.')
                return old
            pending = [row for row in self.store.records('portal_actions') if row.get('actor_id') == str(user['id']) and row.get('status') not in ('SENT', 'CANCELLED')]
            if sum(int(row.get('size', 0)) for row in pending) + values['size'] > 500 * 1024 * 1024 or len(pending) >= 100:
                raise ValueError('Wait for your saved uploads to finish before adding more.')
            return self.store.create_record('portal_actions', {**values, 'status': 'STAGING' if upload else 'PENDING',
                'received': {}, 'file_id': operation, 'filename': 'portal-media.bin', 'retry_at': 0}, actor_id=str(user['id']))

    def record(self, user, workspace, job, operation):
        row = self.store.record('portal_actions', str(uuid.UUID(operation)))
        if not row or row['workspace_id'] != workspace or row['portal_job_id'] != job or row['actor_id'] != str(user['id']):
            raise PermissionError('Upload unavailable.')
        if not self.allowed(user, row['kind'], row['mode']):
            raise PermissionError('Upload permission is no longer available.')
        return row

    def chunk(self, user, workspace, job, operation, index, data):
        with self.store.lock:
            row = self.record(user, workspace, job, operation)
            total = (row['size'] + CHUNK - 1) // CHUNK
            expected = min(CHUNK, row['size'] - index * CHUNK)
            if not 0 <= index < total or len(data) != expected:
                raise ValueError('Invalid upload chunk.')
            digest = hashlib.sha256(data).hexdigest()
            received = row['received']
            if str(index) in received and received[str(index)] != digest:
                raise ValueError('The selected file changed. Start a new upload.')
            if row['status'] != 'STAGING':
                if received.get(str(index)) != digest:
                    raise ValueError('Upload is already finalized.')
                return row
            path = self.store.upload_path(row['file_id'], row['filename'])
            path.parent.mkdir(parents=True, exist_ok=True)
            chunk = path.with_name(f'chunk-{index}')
            if not chunk.exists():
                with chunk.open('xb') as stream:
                    stream.write(data); stream.flush(); os.fsync(stream.fileno())
            elif hashlib.sha256(chunk.read_bytes()).hexdigest() != digest:
                raise ValueError('Saved chunk checksum mismatch.')
            received[str(index)] = digest
            row = self.store.update_record('portal_actions', operation, {'received': received}, actor_id=str(user['id']))
            if len(received) == total:
                assembled = path.with_suffix('.assembling')
                checksum = hashlib.sha256()
                with assembled.open('wb') as target:
                    for number in range(total):
                        part = path.with_name(f'chunk-{number}').read_bytes()
                        if hashlib.sha256(part).hexdigest() != received[str(number)]:
                            raise ValueError('Saved chunk checksum mismatch.')
                        target.write(part); checksum.update(part)
                    target.flush(); os.fsync(target.fileno())
                os.replace(assembled, path)
                row = self.store.update_record('portal_actions', operation, {'sha256': checksum.hexdigest(), 'status': 'PENDING'}, actor_id=str(user['id']))
                for number in range(total):
                    path.with_name(f'chunk-{number}').unlink(missing_ok=True)
            return row

    async def sync(self, record):
        if record.get('status') != 'PENDING':
            return
        try:
            user = self.store.get_user(record['actor_id'])
            if not user or user.get('status', 'ACTIVE') != 'ACTIVE' or not self.allowed(user, record['kind'], record['mode']):
                self.store.update_record('portal_actions', record['id'], {'status':'BLOCKED', 'error':'Permission is no longer available.'}, actor_id='portal-sync')
                return
            payload = {**self.portal.scope(user, record['workspace_id']), 'portal_job_id': str(record['portal_job_id']),
                       'operation_id': record['id'], 'kind': record['kind'], 'mode': record['mode'],
                       'fields': record['fields'], 'record_id': record['record_id'], 'revision': record['revision'],
                       'content_id': record['content_id']}
            path = None
            if record.get('sha256'):
                path = self.store.upload_path(record['file_id'], record['filename'])
                with path.open('rb') as source:
                    if hashlib.file_digest(source, 'sha256').hexdigest() != record['sha256']:
                        raise ValueError('Saved file checksum mismatch.')
                payload['sha256'] = record['sha256']
                if record['kind'] == 'video':
                    payload['total'] = (record['size'] + CHUNK - 1) // CHUNK
                    # One chunk per worker pass keeps call-intake synchronization responsive.
                    index = int(record.get('remote_chunk', 0))
                    if index < payload['total']:
                        with path.open('rb') as source:
                            source.seek(index * CHUNK); chunk = source.read(CHUNK)
                        digest = hashlib.sha256(chunk).hexdigest()
                        result = await self.portal.connection.request('video-chunk', {**payload, 'index': index,
                            'chunk_base64': base64.b64encode(chunk).decode(), 'chunk_sha256': digest})
                        if result.get('sha256') != digest or result.get('index') != index:
                            raise ValueError('Chunk verification failed.')
                        self.store.update_record('portal_actions', record['id'], {'remote_chunk': index + 1, 'error': ''}, actor_id='portal-sync')
                        if index + 1 < payload['total']:
                            return
                else:
                    payload['image_base64'] = base64.b64encode(path.read_bytes()).decode()
            result = await self.portal.connection.request('job-mutate', payload)
            if not result.get('record_id') or record.get('sha256') and result.get('sha256') != record['sha256']:
                raise ValueError('Portal confirmation did not match.')
            self.store.update_record('portal_actions', record['id'], {'status':'SENT', 'remote_id':result['record_id'], 'error':''}, actor_id='portal-sync')
            if path:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as error:
            permanent = isinstance(error, ValueError) or isinstance(error, PortalRequestError) and error.status_code in (400,403,404,409,413,422)
            self.store.update_record('portal_actions', record['id'], {'status': 'FAILED' if permanent else 'PENDING',
                'error': 'Refresh the job and check the file or changed record. Your saved copy is retained.' if permanent else 'Connection unavailable. Your saved change will retry.',
                'retry_at': time.time() + 60}, actor_id='portal-sync')

    def form(self, job, kind, *, row=None, options=None, content_id='', resume=None):
        row, options = row or {}, options or {}
        mode = 'edit' if row else 'add'
        fields = ''
        for key, limit in FIELDS[kind].items():
            source = resume['fields'] if resume else row
            value, label = source.get(key) if source.get(key) is not None else '', key.replace('_',' ').capitalize()
            if key == 'topic' and not row and not resume:
                value = options.get('job',{}).get('default_topic') or ''
            identifier = f'portal-{kind}-{resume["id"] if resume else row.get("id", "new")}-{content_id}-{key}'
            if kind == 'photo' and not row and not resume and not content_id and key == 'caption':
                identifier = 'portal-caption'
            attrs = f"id='{identifier}' name='{key}' maxlength='{limit}'"
            if resume:
                attrs += ' readonly'
            if key in ('name', 'note', 'job_name', 'address'):
                attrs += ' required'
            if key == 'amount':
                field = f"<input {attrs} type='number' min='0' max='99999999.99' step='0.01' inputmode='decimal' value='{esc(value)}'>"
            elif key in ('note','notes','description'):
                field = f"<textarea {attrs} rows='3'>{esc(value)}</textarea>"
            else:
                choices = options.get({'topic':'topics','default_topic':'topics','category':'categories','condition':'conditions'}.get(key,''), [])
                datalist = f"<datalist id='{identifier}-choices'>" + ''.join(f"<option value='{esc(choice)}'></option>" for choice in choices) + '</datalist>' if choices else ''
                field = f"<input {attrs} value='{esc(value)}'" + (f" list='{identifier}-choices'" if choices else '') + '>' + datalist
            fields += f"<div class='field'><label for='{identifier}'>{label}{' (optional)' if key not in ('note','name','job_name','address') else ''}</label>{field}</div>"
        media = ''
        if not row and kind in ('photo','receipt','video'):
            accept = 'video/mp4,video/quicktime,video/webm,video/x-msvideo,.m4v' if kind == 'video' else 'image/jpeg,image/png,image/webp,image/gif'
            maximum = '100' if kind == 'video' else '12'
            media = f"<div class='field'><label>Choose {'videos' if kind == 'video' else 'receipt image' if kind == 'receipt' else 'images'}<input type='file' name='files' accept='{accept}' {'' if kind == 'receipt' or resume else 'multiple'}></label><span class='muted'>{'Select the same original file to resume. ' if resume else ''}Up to {maximum} MB each.</span></div>"
            if not resume:
                media += f"<div class='field'><label class='button secondary portal-camera'>Use camera<input type='file' name='camera' accept='{'video/*' if kind == 'video' else 'image/*'}' capture='environment'></label></div>"
        return f"<form method='post' action='/office/photo-portal/{job}/actions' class='portal-tool-form' data-portal-tool data-operation='{esc(resume['id'] if resume else '')}' data-kind='{kind}' data-mode='{mode}' data-record='{esc(row.get('id',''))}' data-revision='{esc(row.get('revision',''))}' data-content='{esc(content_id)}' data-job='{job}'>{media}<div class='portal-fields'>{fields}</div><button type='submit' disabled>{'Resume upload' if resume else 'Save changes' if row else 'Upload' if media else 'Add '+kind.replace('content','item')}</button><p role='status' data-tool-status></p><noscript><p>Enable JavaScript to use these job tools.</p></noscript></form>"

    def controls(self, user, job, kind, row, state):
        if not self.allowed(user,kind,'edit'):
            return ''
        return f"<details class='portal-edit'><summary>Edit</summary>{self.form(job,kind,row=row,options=state)}<button type='button' class='danger' data-portal-remove data-job='{job}' data-kind='{kind}' data-record='{row['id']}' data-revision='{esc(row['revision'])}'>Remove {kind.replace('content','item')}</button><p role='status' data-remove-status></p></details>"

    async def render(self, user, workspace, job, tab):
        tab = tab if tab in TABS else 'photos'
        state = await self.state(user, workspace, job)
        job_details = ''
        if state.get('job',{}).get('revision') and self.allowed(user,'job','edit'):
            job_details = "<details class='portal-job-details'><summary>Job details</summary>" + self.form(job,'job',row=state['job'],options=state) + "<small>Edits here update the photo portal's job details, not the ERP customer or property address.</small></details>"
        navigation = '<nav class="portal-tabs" aria-label="Job tools">' + ''.join(f"<a href='/office/photo-portal?job_id={job}&tab={key}' {'aria-current=page' if tab == key else ''}>{label}</a>" for key,label in TABS.items()) + '</nav>'
        kind = {'photos':'photo','videos':'video','notes':'note','receipts':'receipt','contents':'content'}[tab]
        upload = ''
        if self.allowed(user,kind):
            label = {'photos':'Add photos','videos':'Add videos','notes':'Add a note','receipts':'Add receipts','contents':'Add an item'}[tab]
            upload = f"<details class='portal-upload'><summary>{label}</summary>{self.form(job,kind,options=state)}</details>"
        rows = state.get({'photos':'media','videos':'media'}.get(tab,tab), [])
        if tab in ('photos','videos'):
            rows = [row for row in rows if (row.get('media_type') or 'photo') == kind]
        content = ''
        if tab == 'photos':
            content = f"<iframe class='portal-gallery-frame' title='Job floor plan and photos' src='{esc(self.portal.gallery(job))}' referrerpolicy='no-referrer'></iframe>"
            if rows and self.allowed(user,kind,'edit'):
                content += '<details class="portal-manage-media"><summary>Edit captions, topics or remove photos</summary><div class="portal-media-grid">'
                for row in rows:
                    content += f"<article class='portal-item'><img loading='lazy' alt='Job photo' src='{esc(self.asset(job,'photo',row['id']))}'><p>{esc(row.get('caption') or 'Photo')}</p>{self.controls(user,job,kind,row,state)}</article>"
                content += '</div></details>'
        else:
            if tab == 'receipts':
                content += f"<div class='actions portal-receipt-total'><strong>Total: ${Decimal(str(state.get('receipt_total',0))):,.2f}</strong><button class='secondary' type='button' data-portal-print>Print / Save PDF</button></div><p class='muted portal-private'>Staff only. Receipts and notes are not included in customer estimate galleries.</p>"
            content += f"<div class='portal-{'media-grid' if tab in ('videos','receipts','contents') else 'note-list'}'>"
            for row in rows:
                item = ''
                if tab == 'videos':
                    url = esc(self.asset(job,'video',row['id']))
                    item = f"<video controls preload='metadata' src='{url}'></video><p>{esc(row.get('caption') or 'Job video')}</p><a href='{url}' target='_blank' rel='noopener'>Open video</a>"
                elif tab == 'receipts':
                    url = esc(self.asset(job,'receipt',row['id']))
                    amount = f"${Decimal(str(row['amount'])):,.2f}" if row.get('amount') is not None else 'Amount not entered'
                    item = f"<a href='{url}' target='_blank' rel='noopener'><img loading='lazy' alt='Receipt image' src='{url}'></a><h3>{esc(row.get('vendor') or 'Receipt')}</h3><strong>{esc(amount)}</strong><p class='portal-preserve'>{esc(row.get('notes'))}</p>"
                elif tab == 'notes':
                    item = f"<p class='portal-preserve'>{esc(row.get('note'))}</p><small>{esc(row.get('updated_at') or row.get('created_at'))}</small>"
                else:
                    item = f"<h3>{esc(row.get('name'))}</h3><p>{esc(' / '.join(str(row.get(key) or '') for key in ('category','condition')).strip(' /'))}</p><p class='portal-preserve'>{esc(row.get('description'))}</p>"
                    item += '<div class="portal-content-photos">' + ''.join(f"<a target='_blank' rel='noopener' href='{esc(self.asset(job,'photo',identifier))}'><img alt='Contents item photo' loading='lazy' src='{esc(self.asset(job,'photo',identifier))}'></a>" for identifier in row.get('photo_ids',[])) + '</div>'
                    if self.allowed(user,'photo'):
                        item += f"<details><summary>Add item photos</summary>{self.form(job,'photo',options=state,content_id=str(row['id']))}</details>"
                content += f"<article class='portal-item'>{item}{self.controls(user,job,kind,row,state)}</article>"
            content += '</div>'
            if not rows:
                content += f"<p>No {TABS[tab].lower()} added yet.</p>"
        pending = [row for row in self.store.records('portal_actions') if row.get('workspace_id') == workspace and row.get('portal_job_id') == job and row.get('status') != 'SENT']
        status = ''
        if pending:
            status = '<details class="portal-sync"><summary>Saved changes and uploads</summary>'
            for row in pending[:30]:
                status += f"<p>{esc(row['kind'].capitalize())}: {esc(row['status'])}. {esc(row.get('error') or ('Select the original file below to resume.' if row['status']=='STAGING' else 'Saved locally; waiting for portal confirmation.'))}</p>"
                if row['status']=='STAGING' and row['actor_id']==str(user['id']) and self.allowed(user,row['kind']):
                    status += self.form(job,row['kind'],options=state,content_id=row.get('content_id',''),resume=row)
            status += '</details>'
        truncated = '<p>Showing the newest 500 entries per section. Older entries are unchanged in the original portal.</p>' if state.get('truncated') else ''
        advanced = ''
        if has_permission(user,'portal.manage'):
            from urllib.parse import urljoin
            original = urljoin(self.settings.external_portal_api_url, f'../job.php?id={job}')
            advanced = f"<details class='portal-advanced'><summary>Original portal tools</summary><a href='{esc(original)}' target='_blank' rel='noopener noreferrer'>Open posting and advanced tools</a><p class='muted'>Uses your existing portal staff login. Uploading here does not publish images for marketing.</p></details>"
        return f"{job_details}{navigation}<div class='portal-tools' data-tab='{tab}'>{upload}{status}<div class='actions portal-refresh'><a class='button secondary' href='/office/photo-portal?job_id={job}&tab={tab}'>Refresh</a></div>{truncated}{content}{advanced}<p role='status' data-portal-status></p></div><script defer src='/office/photo-portal/tools.js?release=4.7.3-parity-1'></script>"
