"""Fictional consent, replay, isolation, withdrawal, restart and retry tests."""
import asyncio
import base64
import os
import re
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace
from unittest.mock import patch

from fastapi import HTTPException

from app.config import Settings
from app.customer_sms import CustomerSms, phone_number
from app.security import SignedClient
from app.sms_policy import CUSTOMER_DISCLOSURE, CUSTOMER_VERSION, render_policy
from app.store import OfficeStore


class Mirror:
    def __init__(self, store):
        self.store, self.fail, self.calls = store, True, []

    async def request(self, method, path, payload, **kwargs):
        assert self.store.record('customer_sms_events', payload['idempotency_key']), 'Remote write preceded local evidence'
        self.calls.append(payload)
        if self.fail:
            raise RuntimeError('Fictional service outage')
        return {'recorded': True}


def setup(root):
    config = replace(Settings.from_env(), data_dir=root, public_url='https://portal.example.test',
                     customer_public_url='https://portal.example.test/customer',
                     internal_hmac_keys='test:' + base64.b64encode(b'fictional-only-key-0123456789abcde').decode())
    store = OfficeStore(root)
    contact = store.create_record('contacts', {'name':'Fictional Customer','email':'customer@example.test'})
    document = store.create_record('estimates', {'contact_id':contact['id'], 'public_token':'fictional-secure-link-' + uuid.uuid4().hex})
    mirror = Mirror(store)
    return CustomerSms(store, SimpleNamespace(orchestrator=mirror), config), document, mirror


async def checks():
    with tempfile.TemporaryDirectory(prefix='floodman-sms-consent-') as root:
        sms, document, mirror = setup(root)
        cid, token = document['contact_id'], document['public_token']
        def save(ticket=None, **changes):
            values = dict(ticket=ticket or sms.ticket(token,cid), phone='231-555-0100', choice='enable', consent='yes')
            values.update(changes)
            return sms.save('estimate', document, **values)
        assert not sms.current(cid) and not sms.store.records('customer_sms_events')
        assert 'checked' not in re.search(r'<input id="sms-consent"[^>]+>', sms.form('estimate',document)).group()
        for values in ({'consent':''}, {'phone':'letters2315550100'}, {'phone':'+442315550100'},
                       {'phone':'2315550100 ext 2'}, {'origin':'https://attacker.example.test'},
                       {'ticket':sms.ticket(token,'other-customer')}, {'ticket':sms.ticket(token,cid,now=1)},
                       {'choice':'verified'}, {'website':'bot'}):
            try:
                save(**values)
                raise AssertionError('Invalid consent accepted')
            except (ValueError,HTTPException):
                pass
        assert not sms.store.records('customer_sms_events')
        with patch.object(sms.store, '_save', side_effect=OSError('Fictional disk failure')):
            try:
                save()
                raise AssertionError('Disk failure was ignored')
            except OSError:
                pass
        assert not sms.store.records('customer_sms_events') and not sms.current(cid)
        ticket = sms.ticket(token,cid)
        enrolled = save(ticket)
        assert sms.current(cid)['status']=='OPTED_IN'
        assert enrolled['disclosure_text']==CUSTOMER_DISCLOSURE and enrolled['disclosure_version']==CUSTOMER_VERSION
        assert enrolled['source']=='FLOODMAN_CUSTOMER_PORTAL' and enrolled['organization_id']=='floodman'
        assert token not in str(sms.store.records('customer_sms_events'))
        assert save(ticket)['id']==enrolled['id'] and len(sms.store.records('customer_sms_events'))==1
        try:
            save(ticket,phone='2315550101')
            raise AssertionError('A consumed form changed number')
        except ValueError:
            pass
        await sms.sync_once()
        assert sms.store.record('customer_sms_events',enrolled['id'])['sync_status']=='PENDING'
        sms.store = OfficeStore(root); mirror.store=sms.store
        assert sms.current(cid)['status']=='OPTED_IN', 'Restart lost consent'
        second = save(phone='2315550101')
        events = sms.store.records('customer_sms_events')
        assert len(events)==3 and any(e['phone_e164']=='+12315550100' and e['status']=='OPTED_OUT' for e in events)
        out = save(choice='disable',phone='',consent='')
        assert sms.current(cid)['status']=='OPTED_OUT'
        # Replaying the previous opt-in must not restore a later withdrawal.
        save(ticket)
        assert sms.current(cid)['status']=='OPTED_OUT'
        mirror.fail=False
        await sms.sync_once()
        assert all(e['sync_status']=='SYNCED' for e in sms.store.records('customer_sms_events'))
        mirrored = len(mirror.calls)
        await sms.sync_once()
        assert len(mirror.calls)==mirrored, 'Synced events were unnecessarily replayed'
        assert phone_number('(231) 555-0100')=='+12315550100'
        for kind in ('privacy','terms','program'):
            page=render_policy(kind)
            assert 'customer' in page.lower() and 'staff' in page.lower()
            assert 'Message and data rates may apply' in page
        assert CUSTOMER_DISCLOSURE in render_policy('program')
        assert 'third parties or affiliates for marketing or promotional purposes' in render_policy('privacy')
        assert 'checked' not in re.search(r'<input type="checkbox"[^>]+>',render_policy('program')).group()
    print('Customer SMS consent core: PASS')


if __name__=='__main__':
    asyncio.run(checks())
