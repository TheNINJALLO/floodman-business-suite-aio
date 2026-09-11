from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'office-console'))
from ai_call_intake_smoke import projection
from app.call_approval import approve_call, approval_form
from app.config import Settings
from app.portal_connection import PortalConnection
from app.roomflow_supabase import ensure_roomflow_workspaces
from app.store import OfficeStore


class Providers:
    calls = 0

    async def gauzy_context(self):
        return {'tenant_id': 'fictional-tenant', 'organization_id': 'fictional-org', 'sync_enabled': True}

    async def _gauzy_request(self, *args, **kwargs):
        return []

    def _provider_items(self, response):
        return response

    async def full_gauzy_create_contact(self, *args):
        self.calls += 1
        return {'id': 'fictional-erp-customer'}

    async def full_gauzy_create_project(self, *args, **kwargs):
        self.calls += 1
        return {'id': 'fictional-erp-project'}


def run():
    with tempfile.TemporaryDirectory(prefix='floodman-portal-test-') as root:
        store = OfficeStore(root)
        owner = store.create_owner('Fictional Owner', 'owner@example.test', 'Fictional-Pass-2026!')
        workspace = ensure_roomflow_workspaces(store, actor_id=owner['id'])[0]['id']
        payload = projection('portal-fictional-call', workspace)
        pending = store.project_call_intake(payload, require_approval=True)
        assert pending['approval_status'] == 'PENDING'
        assert not store.records('contacts') and not store.records('properties')
        assert not store.records('roomflow_jobs') and not store.records('estimates')
        replay = store.project_call_intake(payload, require_approval=True)
        assert replay['replayed']
        values = {'name': 'Reviewed Name', 'email': 'reviewed@example.test', 'phone': '+12315550155',
                  'street': '12 Fictional Street', 'city': 'Traverse City', 'state': 'MI', 'postal_code': '49684'}
        approved = approve_call(store, pending, owner['id'], values)
        assert approved['approval_status'] == 'APPROVED'
        assert all(len(store.records(kind)) == 1 for kind in ('contacts','properties','roomflow_jobs','estimates'))
        assert store.record('estimates', approved['estimate_id'])['publication_status'] == 'UNPUBLISHED'
        assert not approved['caller']['phone_verified']
        again = approve_call(store, pending, owner['id'], values)
        assert again['customer_id'] == approved['customer_id']
        later = projection('portal-fictional-call', workspace, sequence=1)
        later['caller']['name'] = 'Later unreviewed transcription'
        updated = store.project_call_intake(later, require_approval=True)
        assert updated['caller']['name'] == 'Reviewed Name'
        assert updated['customer_id'] == approved['customer_id']
        assert len(store.records('contacts')) == 1
        # Explicit customer selection reuses that customer and only their properties.
        second = store.project_call_intake(projection('portal-second-call', workspace), require_approval=True)
        selected = approve_call(store, second, owner['id'], {**values, 'customer_id': approved['customer_id'], 'property_id': approved['property_id']})
        assert selected['customer_id'] == approved['customer_id'] and selected['property_id'] == approved['property_id']
        assert len(store.records('contacts')) == 1 and len(store.records('properties')) == 1
        foreign = store.create_record('contacts', {'workspace_id': 'different-workspace', 'name': 'Private Foreign Name'}, actor_id=owner['id'])
        third = store.project_call_intake(projection('portal-third-call', workspace), require_approval=True)
        try:
            approve_call(store, third, owner['id'], {**values, 'customer_id': foreign['id']})
            raise AssertionError('Cross-workspace customer accepted')
        except ValueError:
            pass
        assert store.record('call_intakes', third['id'])['approval_status'] == 'PENDING'
        rendered = approval_form(store, third, approved['customer_id'])
        assert 'Private Foreign Name' not in rendered and approved['property_id'] in rendered
        config = replace(Settings.from_env(), external_portal_api_url='https://portal.example.test/portal/api/floodman.php', external_portal_api_token='test-only-key-' * 4)
        providers = Providers()
        connection = PortalConnection(store, providers, config)
        requests = []

        async def fake_request(action, data):
            requests.append(action)
            key = hashlib.sha256(json.dumps([data[k] for k in ('organization_id','workspace_id','job_id')], separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
            return {'portal_job_id': 42, 'source_key': key}

        connection.request = fake_request
        asyncio.run(connection.sync_one(third))
        assert not requests and providers.calls == 0
        asyncio.run(connection.sync_one(store.record('call_intakes', approved['id'])))
        linked = store.record('call_intakes', approved['id'])
        assert linked['portal_job_id'] == 42 and linked['gauzy_contact_id'] == 'fictional-erp-customer'
        assert linked['gauzy_project_id'] == 'fictional-erp-project'
        asyncio.run(connection.sync_one(linked))
        assert requests == ['upsert-job'] and providers.calls == 2
        estimate = store.record('estimates', approved['estimate_id'])
        assert not connection.gallery_html(estimate)
        published = {**estimate, 'status': 'SENT', 'sent_at': '2026-09-11T00:00:00Z'}
        assert 'iframe' in connection.gallery_html(published)
        assert not connection.gallery_html({**published, 'contact_id': 'another-customer'})
        assert not connection.gallery_html({**published, 'property_id': 'another-property'})
        assert not connection.gallery_url('invalid')
        restarted = OfficeStore(root)
        assert restarted.record('call_intakes', approved['id'])['approval_status'] == 'APPROVED'
        assert restarted.record('call_intakes', third['id'])['approval_status'] == 'PENDING'
    print('Portal approval, customer/property isolation, replay, ERP linkage, customer gallery, and persistence checks passed')


if __name__ == '__main__':
    run()
