import io
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from docx import Document
import test_backend as helpers
from backend.models import ReviewCreate
from backend.document_parser import parse_bytes, parse_document, ParseError
from backend.regulation_service import load_library
from backend.rule_engine import detect

class QualityFixtureTests(unittest.TestCase):
    def test_three_classes_and_quote_reference_integrity(self):
        context=ReviewCreate(document_id='test',material_type='marketing',channel='online',product_type='理财',audience='虚构客户')
        library=load_library();registry={r.regulation_id for r in library.regulations}
        results={}
        for name in ['A-high-risk','B-context','C-normal']:
            data=Path(f'data/demo_samples/qa/{name}.txt').read_bytes();parsed=parse_bytes('demo.txt',data)
            issues=detect(parsed['segments'],library,context);results[name]=issues
            source={s['segment_id']:s['text'] for s in parsed['segments']}
            for i in issues:
                self.assertEqual(source[i.location.segment_id][i.location.start:i.location.end],i.original_text)
                self.assertTrue(set(i.regulation_ids)<=registry)
                self.assertEqual(i.review_status,'pending')
        self.assertTrue(any(i.severity=='high' for i in results['A-high-risk']))
        self.assertTrue(results['B-context'])
        self.assertTrue(all(i.severity=='low' and '上下文' in i.reason for i in results['B-context']))
        self.assertEqual(results['C-normal'],[])
        # Record a known semantic gap rather than inventing an accuracy number.
        self.assertFalse(any(i.original_text=='投入资金只增不减' for i in results['A-high-risk']))

    def test_parser_timeout_and_zip_resource_limit(self):
        with self.assertRaises(ParseError) as e:parse_document('small.txt',b'hello',timeout=0)
        self.assertEqual(e.exception.code,'parse_timeout')
        import zipfile
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            for i in range(1001):z.writestr(str(i),'')
        with self.assertRaises(ParseError) as e:parse_bytes('zip.docx',stream.getvalue())
        self.assertEqual(e.exception.code,'parse_limit')

class SecurityGateTests(unittest.TestCase):
    setUp=helpers.BackendTests.setUp
    tearDown=helpers.BackendTests.tearDown
    upload=helpers.BackendTests.upload
    review=helpers.BackendTests.review

    def test_json_body_cap_and_common_error_without_input(self):
        health=self.client.get('/api/health');self.assertEqual(health.headers['cache-control'],'no-store');self.assertEqual(health.headers['x-content-type-options'],'nosniff')
        secret_marker='DO_NOT_ECHO_TEST_INPUT'
        result=self.client.post('/api/session',content=json.dumps({'access_token':secret_marker+'x'*1048576}),headers={'Content-Type':'application/json'})
        self.assertEqual(result.status_code,413,result.text[:300])
        self.assertNotIn(secret_marker,result.text)
        malformed=self.client.post('/api/session',content=b'{bad',headers={'Content-Type':'application/json'})
        self.assertEqual(malformed.status_code,422)
        self.assertNotIn('{bad',malformed.text)

    def test_missing_empty_corrupt_unsupported_upload(self):
        for filename,data,code in [('empty.txt',b'',422),('broken.docx',b'PKxx',415),('wrong.exe',b'text',415)]:
            with self.subTest(filename=filename):
                response=self.client.post('/api/documents/upload',files={'file':(filename,data)},headers=self.headers)
                self.assertEqual(response.status_code,code,response.text)
        response=self.client.post('/api/documents/upload',files={'wrong':('a.txt',b'a')},headers=self.headers)
        self.assertEqual(response.status_code,422)

    def test_report_throttled_and_expired_data_removed(self):
        r=self.review(self.upload()['document_id']);rid=r['review_id']
        for _ in range(10):self.assertEqual(self.client.get(f'/api/reviews/{rid}/report?draft=true').status_code,200)
        self.assertEqual(self.client.get(f'/api/reviews/{rid}/report?draft=true').status_code,429)
        self.app.state.store.db.execute('UPDATE resources SET expires=0 WHERE kind IN (?,?)',('review','document'));self.app.state.store.db.commit()
        self.app.state.store.cleanup()
        self.assertEqual(self.app.state.store.db.execute("SELECT count(*) FROM resources WHERE kind IN ('review','document')").fetchone()[0],0)
        self.assertEqual(self.app.state.store.db.execute('PRAGMA secure_delete').fetchone()[0],1)

    def test_budget_no_call_and_cross_user_write_delete(self):
        from pydantic import SecretStr
        self.settings.llm_enabled=True;self.settings.api_key=SecretStr('test-only-not-real');self.settings.daily_token_budget=0
        with patch('backend.main.AIService.review') as call:
            r=self.review(self.upload()['document_id'],use_ai=True,external_processing_authorized=True)
            self.assertEqual(r['execution']['ai_failure_code'],'ai_budget_exhausted');call.assert_not_called()
        from fastapi.testclient import TestClient
        other=TestClient(self.app,base_url='https://testserver');session=other.post('/api/session',json={'access_token':'test-secret'}).json()
        hdr={'X-CSRF-Token':session['csrf_token']}
        self.assertEqual(other.delete('/api/reviews/'+r['review_id'],headers=hdr).status_code,404)
        issue=r['issues'][0]
        response=other.patch(f"/api/reviews/{r['review_id']}/issues/{issue['issue_id']}",json={'expected_version':r['version'],'review_status':'accepted','decision_reason':'unauthorized'},headers=hdr)
        self.assertEqual(response.status_code,404)

class RequestBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_chunked_limit_and_disconnect_never_call_application(self):
        from backend.security import RequestBounds
        calls=[];sent=[]
        async def app(scope,receive,send):calls.append(True)
        scope={'type':'http','method':'POST','path':'/api/session','headers':[], 'client':('qa-peer',1)}
        messages=iter([{'type':'http.request','body':b'123','more_body':True},{'type':'http.request','body':b'456','more_body':False}])
        async def receive():return next(messages)
        async def send(message):sent.append(message)
        await RequestBounds(app,max_json_bytes=5)(scope,receive,send)
        self.assertEqual(sent[0]['status'],413);self.assertEqual(calls,[])
        async def disconnected():return {'type':'http.disconnect'}
        await RequestBounds(app)(scope,disconnected,send);self.assertEqual(calls,[])

    async def test_transport_peer_rate_limit_ignores_forwarded_header(self):
        from backend.security import RequestBounds
        from starlette.responses import Response
        async def app(scope,receive,send):await Response(status_code=200)(scope,receive,send)
        gate=RequestBounds(app,requests_per_minute=2);statuses=[]
        async def receive():return {'type':'http.request','body':b''}
        async def send(message):
            if message['type']=='http.response.start':statuses.append(message['status'])
        for forwarded in [b'1.1.1.1',b'2.2.2.2',b'3.3.3.3']:
            await gate({'type':'http','method':'GET','path':'/api/health','headers':[(b'x-forwarded-for',forwarded)],'client':('peer',1)},receive,send)
        self.assertEqual(statuses,[200,200,429])
