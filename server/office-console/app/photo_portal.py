from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import time
import uuid
from typing import Any
from urllib.parse import urlencode

from .auth import has_permission
from .portal_connection import PortalRequestError
from .ui import esc


class PhotoPortal:
    """ERP-native access to remote photos; no remote staff password or public admin session."""
    def __init__(self, connection: Any):
        self.connection = connection
        self.store = connection.store
        self.settings = connection.settings

    def scope(self, user: dict, workspace: str) -> dict:
        return {"workspace_id": workspace, "organization_id": self.settings.external_portal_organization_id,
                "include_legacy": has_permission(user, "portal.manage")}

    async def job(self, user: dict, workspace: str, job_id: int) -> dict:
        if not has_permission(user, "properties.view"):
            raise PermissionError("Photo portal access is required")
        result = await self.connection.request("get-job", {**self.scope(user, workspace), "portal_job_id": str(job_id)})
        job = result.get("job") or {}
        if int(job.get("id") or 0) != job_id:
            raise RuntimeError("Photo portal returned an invalid job")
        return job

    def gallery(self, job_id: int) -> str:
        expires = int(time.time()) + 600
        signature = hmac.new(self.settings.external_portal_api_token.encode(), f"staff-gallery:{job_id}::{expires}".encode(), hashlib.sha256).hexdigest()
        return self.settings.external_portal_api_url + "?" + urlencode({"view": "staff-gallery", "key": str(job_id), "expires": expires, "signature": signature})

    async def stage_upload(self, user: dict, workspace: str, job_id: int, operation_id: str, content: bytes, caption: str) -> dict:
        if not has_permission(user, "properties.manage"):
            raise PermissionError("Photo upload permission is required")
        await self.job(user, workspace, job_id)
        operation_id = str(uuid.UUID(operation_id))
        if not content or len(content) > 12 * 1024 * 1024:
            raise ValueError("Choose a photo smaller than 12 MB.")
        kind = "jpg" if content.startswith(b"\xff\xd8\xff") else "png" if content.startswith(b"\x89PNG\r\n\x1a\n") else "gif" if content.startswith((b"GIF87a", b"GIF89a")) else "webp" if content.startswith(b"RIFF") and content[8:12] == b"WEBP" else ""
        if not kind:
            raise ValueError("Choose a JPEG, PNG, WebP, or GIF photo.")
        digest = hashlib.sha256(content).hexdigest()
        with self.store.lock:
            old = self.store.record("portal_uploads", operation_id)
            if old:
                if any(str(old.get(key)) != str(value) for key, value in {"workspace_id": workspace, "portal_job_id": job_id, "actor_id": user['id'], "sha256": digest}.items()):
                    raise ValueError("This upload reference was already used. Refresh and try again.")
                return old
            file_id, path = self.store.save_upload("portal-photo." + kind, content)
            return self.store.create_record("portal_uploads", {"id": operation_id, "operation_id": operation_id,
                "workspace_id": workspace, "portal_job_id": job_id, "actor_id": str(user['id']), "sha256": digest,
                "file_id": file_id, "filename": path.name, "caption": caption[:1000], "status": "PENDING", "retry_at": 0}, actor_id=str(user['id']))

    async def sync_upload(self, record: dict) -> None:
        if record.get("status") != "PENDING":
            return
        try:
            user = self.store.get_user(str(record['actor_id']))
            if not user or str(user.get('status') or 'ACTIVE') != 'ACTIVE' or not has_permission(user, 'properties.manage'):
                self.store.update_record('portal_uploads', record['id'], {'status':'BLOCKED','error':'Upload permission is no longer available'}, actor_id='portal-sync')
                return
            path = self.store.upload_path(record['file_id'], record['filename'])
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != record['sha256']:
                raise ValueError('Saved upload checksum mismatch')
            result = await self.connection.request('upload-photo', {**self.scope(user, record['workspace_id']),
                'portal_job_id':str(record['portal_job_id']), 'operation_id':record['operation_id'],
                'caption':record['caption'], 'sha256':record['sha256'], 'image_base64':base64.b64encode(content).decode()})
            if result.get('sha256') != record['sha256'] or not result.get('photo_id'):
                raise ValueError('Portal upload verification failed')
            self.store.update_record('portal_uploads', record['id'], {'status':'SENT','photo_id':result['photo_id'],'error':''}, actor_id='portal-sync')
            # The checksum-verified hosted original is durable; release only this temporary local upload copy.
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass  # Cleanup failure must not requeue an already confirmed upload.
        except asyncio.CancelledError:
            raise
        except Exception as error:
            permanent = isinstance(error, ValueError) or isinstance(error, PortalRequestError) and error.status_code in (400,403,404,409,413,422)
            self.store.update_record('portal_uploads', record['id'], {'status':'FAILED' if permanent else 'PENDING',
                'error':'The photo was rejected; check the file and job access.' if permanent else 'Connection unavailable. Your saved photo will retry.', 'retry_at':time.time()+60}, actor_id='portal-sync')

    async def render(self, user: dict, workspace: str, *, job_id: int = 0, search: str = '', before: str = '', tab: str = 'photos') -> str:
        if not has_permission(user, "properties.view"):
            raise PermissionError("Photo portal access is required")
        if not self.connection.enabled:
            return "<section class='card'><h2>Photo portal is not connected</h2><p>Ask an administrator to configure the portal connection.</p></section>"
        try:
            result = await self.connection.request('list-jobs', {**self.scope(user,workspace), 'search':search[:200], 'before_id':before})
            selected = await self.job(user, workspace, job_id) if job_id else None
        except Exception:
            return "<section class='card'><h2>Photo portal is unavailable</h2><p>Your hosted files are unchanged. Refresh to reconnect.</p></section>"
        cards = ''.join(f"<a class='portal-job-card {'active' if int(row['id']) == job_id else ''}' href='/office/photo-portal?{esc(urlencode({'job_id':row['id'],'search':search}))}'><strong>{esc(row.get('name') or 'Untitled job')}</strong><span>{esc(row.get('address') or 'No address added')}</span></a>" for row in result.get('items',[]))
        next_id = result.get('next_before_id')
        more = f"<a class='button secondary' href='/office/photo-portal?{esc(urlencode({'before':next_id,'search':search}))}'>More jobs</a>" if next_id else ''
        content = "<section class='card'><h2>Select a job</h2><p>Choose a job to see its floor plan and photos.</p></section>"
        if selected:
            from .portal_tools import PortalTools
            try:
                tools = await PortalTools(self).render(user, workspace, job_id, tab)
            except Exception:
                tools = "<p>Job tools are temporarily unavailable. Your hosted files are unchanged; refresh to reconnect.</p>"
            pending = [row for row in self.store.records('portal_uploads') if row.get('workspace_id') == workspace and int(row.get('portal_job_id') or 0) == job_id and row.get('status') != 'SENT']
            states = ''.join(f"<p role='status'>{esc(row.get('status'))}: {esc(row.get('error') or 'Photo saved locally and waiting to upload.')}</p>" for row in pending[:10])
            content = f"<section class='card portal-project'><h2>{esc(selected.get('job_name'))}</h2><p>{esc(selected.get('address'))}</p>{states}{tools}</section>"
        return f"<form method='get' class='portal-search'><label class='sr-only' for='portal-search'>Search jobs</label><input id='portal-search' name='search' value='{esc(search)}' placeholder='Search jobs or addresses' maxlength='200'><button>Search</button></form><div class='portal-workspace'><section class='portal-job-list' aria-label='Portal jobs'>{cards or '<p>No matching jobs in this workspace.</p>'}{more}</section><div>{content}</div></div>"
