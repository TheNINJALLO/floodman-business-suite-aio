"""Load the backend in its own package namespace; all DB/network calls are fake."""
import importlib.util
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from pydantic import ValidationError

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('sms_backend',ROOT/'orchestrator/app/__init__.py',submodule_search_locations=[str(ROOT/'orchestrator/app')])
package=importlib.util.module_from_spec(spec);sys.modules['sms_backend']=package;spec.loader.exec_module(package)
from sms_backend.customer_sms import CustomerSmsConsent, event_is_newer, may_resume_existing_consent
from sms_backend import receivables


def checks():
    now=datetime.now(UTC)
    payload=dict(idempotency_key=str(uuid.uuid4()),organization_id='floodman',contact_id='fictional-customer',
                 phone_e164='+12315550100',status='OPTED_IN',captured_at=now.isoformat(),
                 disclosure_version='fictional-v1',disclosure_text='Fictional exact disclosure. '*8)
    assert CustomerSmsConsent(**payload).status=='OPTED_IN'
    for changes in ({'status':'UNKNOWN'},{'phone_e164':'+442315550100'},{'captured_at':now.replace(tzinfo=None).isoformat()},
                    {'captured_at':(now+timedelta(days=1)).isoformat()},{'disclosure_text':''},{'verified':True}):
        try:
            CustomerSmsConsent(**{**payload,**changes})
            raise AssertionError('Invalid internal consent payload accepted')
        except ValidationError:
            pass
    assert event_is_newer(None,now)
    assert not event_is_newer({'captured_at':now},now-timedelta(seconds=1))
    assert not event_is_newer({'captured_at':now},now)
    assert event_is_newer({'captured_at':now-timedelta(minutes=2),'opted_in_at':now+timedelta(minutes=10)},now)
    assert not may_resume_existing_consent(None)
    assert not may_resume_existing_consent({'disclosure_version':'v1','evidence':{}})
    assert may_resume_existing_consent({'disclosure_version':'v1','evidence':{'disclosure_text':'Accepted disclosure'}})
    @contextmanager
    def transaction(): yield object()
    class Office:
        preference={'managed':True,'status':'OPTED_IN','sync_status':'SYNCED'}
        failure=False
        def __init__(self,settings): pass
        def customer_sms_status(self,org,phone):
            assert org=='floodman' and phone=='+12315550100'
            if self.failure: raise RuntimeError('Fictional outage')
            return self.preference
        def close(self): pass
    manager=object.__new__(receivables.ReceivablesManager)
    manager.settings=SimpleNamespace(twilio_enabled=True,ar_require_sms_consent=True,
                                    customer_sms_check_enabled=True,ar_max_sms_per_seven_days=3)
    case={'organization_id':'floodman','recipient_phone_e164':'+12315550100'}
    with patch.object(receivables,'transaction',transaction),patch.object(receivables,'get_sms_consent',return_value={'status':'OPTED_IN'}), \
         patch.object(receivables,'count_recent_outbound_sms',return_value=0),patch.object(receivables,'FloodmanOfficeClient',Office):
        assert manager._sms_allowed(case,{'id':'thread'})==(True,'ALLOWED')
        for preference in ({'managed':True,'status':'OPTED_OUT','sync_status':'PENDING'},
                           {'managed':True,'status':'OPTED_IN','sync_status':'PENDING'},{}):
            Office.preference=preference
            assert manager._sms_allowed(case,{'id':'thread'})[0] is False
        Office.failure=True
        assert manager._sms_allowed(case,{'id':'thread'})==(False,'SMS_CONSENT_CHECK_UNAVAILABLE')
        Office.failure=False;Office.preference={'managed':False}
        assert manager._sms_allowed(case,{'id':'thread'})[0] is True
        with patch.object(receivables,'get_sms_consent',return_value={'status':'OPTED_OUT'}):
            assert manager._sms_allowed(case,{'id':'thread'})==(False,'SMS_CONSENT_REQUIRED')
        with patch.object(receivables,'count_recent_outbound_sms',return_value=3):
            assert manager._sms_allowed(case,{'id':'thread'})==(False,'SMS_RATE_LIMIT')
    policy_spec=importlib.util.spec_from_file_location('sms_patch',ROOT.parent/'containers/unified-portal/patch_sms_policy.py')
    policy_patch=importlib.util.module_from_spec(policy_spec);policy_spec.loader.exec_module(policy_patch)
    source='preserve_call_routing = True\n'+''.join(f'@app.get("{route}")\nasync def {name}(request):\n    return "old"\n\n' for name,route in [('sms_program','/sms-program'),('privacy_policy','/privacy'),('sms_terms','/terms')])
    changed=policy_patch.patch(source)
    assert changed.startswith('preserve_call_routing = True') and changed.count('render_policy(')==3
    assert policy_patch.patch(changed)==changed
    nginx_source='server {\n        location = /floodman-login {\n            return 302 /office;\n        }\n}\n'
    nginx_changed=policy_patch.patch_nginx(nginx_source)
    assert nginx_changed.count('return 302 https://aicall.oninetwork.com/')==3
    assert 'return 302 /office;' in nginx_changed
    assert policy_patch.patch_nginx(nginx_changed)==nginx_changed
    try:
        policy_patch.patch_nginx('server {}')
        raise AssertionError('Missing routing anchor was accepted')
    except RuntimeError:
        pass
    print('Customer SMS backend validation, stale events, STOP/START, delivery guard and Voice patch: PASS')


if __name__=='__main__': checks()
