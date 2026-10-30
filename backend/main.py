"""FastAPI single-process demo. No mock results are returned by this server."""
import asyncio
import hashlib
import hmac
import json
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from uuid import uuid4
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse, Response, FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile
from .config import Settings, ROOT
from .storage import Store
from .security import RequestBounds
from .document_parser import parse_document, ParseError
from .regulation_service import load_library, candidates
from .rule_engine import detect, deduplicate
from .ai_service import AIService, AIError
from .models import (ReviewCreate, IssuePatch, FinalizeRequest, AIssue, Issue,
                     KnowledgeBase, Contract, can_finalize, validate_issue, ReportFields, ReportFieldsPatch, RetryRequest)
from pydantic import Field

class APIError(Exception):
    def __init__(self,status,code,message):self.status,self.code,self.message=status,code,message

class SessionInput(Contract):
    access_token: str = Field(min_length=1,max_length=512)

class ManualCandidate(AIssue):
    # Input does not let clients select source or artificial validation status.
    pass

class AddIssue(Contract):
    expected_version: int = Field(ge=1,strict=True)
    issue: dict
    decision_reason: str = Field(min_length=1,max_length=4000,pattern=r'\S')


def now():return datetime.now(timezone.utc).isoformat()
def digest(value):return hashlib.sha256(value.encode()).hexdigest()


def create_app(settings=None):
    cfg=settings or Settings.from_env();cfg.data_dir.mkdir(parents=True,exist_ok=True)
    store=Store(cfg.data_dir/'reviews.sqlite3');kb=load_library();rate={}
    async def clean():
        while True:
            store.cleanup();await asyncio.sleep(300)
    @asynccontextmanager
    async def lifespan(app):
        job=asyncio.create_task(clean())
        try:yield
        finally:
            job.cancel()
            try:await job
            except asyncio.CancelledError:pass
            store.db.close()
    app=FastAPI(title='智能消保审查平台',lifespan=lifespan)
    app.add_middleware(RequestBounds)
    app.state.store=store;app.state.settings=cfg
    parser_slots=asyncio.Semaphore(2)
    @app.exception_handler(APIError)
    async def api_error(req,e):return JSONResponse({'error':{'code':e.code,'message':e.message,'request_id':str(uuid4()),'details':{}}},status_code=e.status)
    @app.exception_handler(RequestValidationError)
    async def validation_error(req,e):return JSONResponse({'error':{'code':'invalid_request','message':'请求字段无效，请检查填写内容','request_id':str(uuid4()),'details':{}}},status_code=422)
    @app.exception_handler(Exception)
    async def unexpected(req,e):return JSONResponse({'error':{'code':'internal_error','message':'服务处理失败，请稍后重试','request_id':str(uuid4()),'details':{}}},status_code=500)

    def limit(key,max_count):
        tick=int(time.time()//60)
        if len(rate)>1000:
            for k in list(rate):
                if rate[k][0]!=tick:rate.pop(k,None)
            if len(rate)>1000:raise APIError(429,'rate_limited','服务繁忙，请稍后重试')
        previous,count=rate.get(key,(tick,0));count=count+1 if previous==tick else 1;rate[key]=(tick,count)
        if count>max_count:raise APIError(429,'rate_limited','请求过于频繁，请稍后重试')

    def auth(req,write=False):
        session=store.get(digest(req.cookies.get('session','')),'session','session')
        if not session:raise APIError(401,'unauthorized','请先连接服务端会话')
        if write:
            if not hmac.compare_digest(req.headers.get('x-csrf-token',''),session['csrf']):raise APIError(403,'csrf_failed','会话校验失败，请重新连接')
            if req.headers.get('origin') and req.headers['origin']!=str(req.base_url).rstrip('/'):
                raise APIError(403,'origin_failed','来源校验失败')
        return session['owner']

    def require(id,kind,owner):
        obj=store.get(id,kind,owner)
        if obj is None:raise APIError(404,'not_found','记录不存在、已到期或无访问权限')
        return obj

    def event(r,action,owner):r['events'].append({'at':now(),'action':action,'actor':owner})
    def checked(candidate,r,source):
        evidence=KnowledgeBase.model_validate(r['evidence'])
        result=validate_issue(candidate,{s['segment_id']:s['text'] for s in r['segments']},evidence,date.fromisoformat(r['review_date']),r['context']['material_type'],r['context']['channel'])
        result.source=source;return result

    @app.get('/api/health')
    async def health():
        store.db.execute('SELECT 1');return {'status':'ok','schema_version':'1.0'}

    @app.post('/api/session')
    async def login(body:SessionInput,req:Request):
        limit('login:'+str(req.client.host if req.client else 'unknown'),10)
        if not cfg.access_token.get_secret_value():raise APIError(503,'auth_not_configured','服务端未配置Demo访问口令')
        if req.headers.get('origin') and req.headers['origin']!=str(req.base_url).rstrip('/'):raise APIError(403,'origin_failed','来源校验失败')
        if not hmac.compare_digest(body.access_token,cfg.access_token.get_secret_value()):raise APIError(401,'unauthorized','访问口令错误')
        sid=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32);owner=str(uuid4())
        # Reconnecting replaces the browser session; old data expires independently.
        store.put(digest(sid),'session','session',{'owner':owner,'csrf':csrf},time.time()+cfg.retention_seconds)
        response=JSONResponse({'csrf_token':csrf})
        response.set_cookie('session',sid,httponly=True,secure=cfg.cookie_secure,samesite='strict',max_age=cfg.retention_seconds)
        return response

    @app.delete('/api/session')
    async def logout(req:Request):
        auth(req,True);store.delete(digest(req.cookies.get('session','')),'session')
        res=Response(status_code=204);res.delete_cookie('session');return res

    @app.post('/api/documents/upload',status_code=201)
    async def upload(req:Request):
        owner=auth(req,True);limit('upload:'+owner,10);store.cleanup()
        if len(store.list('document',owner))>=20:raise APIError(429,'document_limit','最多保留20份材料，请先删除')
        if not req.headers.get('content-type','').startswith('multipart/form-data'):raise APIError(415,'unsupported_type','请使用multipart文件上传')
        raw=bytearray()
        async for chunk in req.stream():
            raw.extend(chunk)
            if len(raw)>cfg.max_upload_bytes+65536:raise APIError(413,'file_too_large','文件超过10 MiB')
        sent=False
        async def receive():
            nonlocal sent
            if sent:return {'type':'http.request','body':b'','more_body':False}
            sent=True;return {'type':'http.request','body':bytes(raw),'more_body':False}
        bounded=Request(req.scope,receive)
        try:
            async with bounded.form(max_files=1,max_fields=0,max_part_size=cfg.max_upload_bytes+1) as form:
                file=form.get('file')
                if not isinstance(file,UploadFile) or len(form)!=1:raise APIError(422,'invalid_upload','请只上传一个file文件')
                data=await file.read(cfg.max_upload_bytes+1)
                if len(data)>cfg.max_upload_bytes:raise APIError(413,'file_too_large','文件超过10 MiB')
                filename=(file.filename or 'unnamed').replace('\\','/').split('/')[-1][:200]
                try:
                    if parser_slots.locked():raise APIError(503,'parser_busy','解析服务繁忙，请稍后重试')
                    async with parser_slots:parsed=await asyncio.to_thread(parse_document,filename,data)
                except ParseError as e:raise APIError(e.status,e.code,e.message)
        except APIError:raise
        except Exception:raise APIError(422,'invalid_upload','文件上传格式无效') from None
        doc={'document_id':str(uuid4()),'filename':filename,'sha256':hashlib.sha256(data).hexdigest(),'status':'ready',**parsed,'created_at':now(),'expires_at':time.time()+cfg.retention_seconds}
        store.put(doc['document_id'],'document',owner,doc,doc['expires_at']);return doc

    @app.get('/api/documents')
    async def documents(req:Request):
        return {'documents':[{k:v for k,v in d.items() if k not in ['segments']} for d in store.list('document',auth(req))]}

    async def execute(review_id,owner):
        r=store.get(review_id,'review',owner)
        if not r:return
        r['status']='running';r['version']+=1;store.save(review_id,r)
        try:
            context=ReviewCreate.model_validate(r['context'])
            results=detect(r['segments'],kb,context)
            r['execution']['rules_status']='succeeded'
            if context.use_ai:
                try:
                    if not cfg.llm_enabled or not cfg.api_key.get_secret_value():raise AIError('ai_not_configured')
                    if sum(len(s['text']) for s in r['segments'])>cfg.max_ai_chars:raise AIError('ai_text_limit')
                    reserve=sum(len(s['text'].encode()) for s in r['segments'])*4+20000+cfg.max_output_tokens
                    if not store.reserve(reserve,cfg.daily_token_budget):raise AIError('ai_budget_exhausted')
                    response=await AIService(cfg).review(r['segments'],KnowledgeBase.model_validate(r['evidence']))
                    for candidate in response.issues:
                        candidate.issue_id=str(uuid4());results.append(checked(candidate,r,'ai'))
                    r['execution']['ai_status']='succeeded'
                except AIError as e:
                    r['execution']['ai_status']='failed';r['execution']['ai_failure_code']=e.code
                    r['coverage']['warnings'].append('AI审查未完成：'+e.code+'；仅返回真实规则结果，不含替代Mock')
            merged=deduplicate(results)
            if len(merged)>=200:r['coverage']['warnings'].append('最多展示200条候选问题，其余未完整覆盖，请缩小送审范围')
            r['issues']=[i.model_dump(mode='json') for i in merged[:200]]
            r['original_issues']=json.loads(json.dumps(r['issues']))
            r['status']='pending_review';r['version']+=1
            r['coverage']['warnings'].append('当前规则只作启发式初筛，不能证明全文合规；未覆盖语义及事实需人工审查')
            event(r,'analysis_completed',owner)
        except Exception:
            r['status']='failed';r['failure_code']='review_failed';r['execution']['rules_status']='failed'
        # UPDATE only: a deletion/expiry cannot be resurrected by a late network response.
        store.save(review_id,r)

    @app.post('/api/reviews',status_code=202)
    async def create(body:ReviewCreate,req:Request,background:BackgroundTasks):
        owner=auth(req,True);limit('create:'+owner,5)
        key=req.headers.get('idempotency-key','')
        if not key or len(key)>200:raise APIError(422,'idempotency_required','请提供有效幂等键')
        request_hash=digest(body.model_dump_json());idemid=digest(owner+':'+key)
        previous=store.get(idemid,'idempotency',owner)
        if previous:
            if previous['hash']!=request_hash:raise APIError(409,'idempotency_conflict','相同幂等键对应不同请求')
            r=require(previous['review_id'],'review',owner);return {'review_id':r['review_id'],'status':r['status'],'version':r['version']}
        if len(store.list('review',owner))>=100:raise APIError(429,'review_limit','最多保留100个任务，请先删除')
        doc=require(body.document_id,'document',owner)
        active=store.db.execute("SELECT COUNT(*) FROM resources WHERE kind='review' AND expires>? AND json_extract(payload,'$.status') IN ('pending','running')",(time.time(),)).fetchone()[0]
        if active>=2:raise APIError(503,'queue_full','审查队列繁忙，请稍后重试')
        if any(r['status'] in ['pending','running'] for r in store.list('review',owner)):raise APIError(409,'review_active','已有审查任务正在执行')
        evidence=candidates(kb,body)
        r={'review_id':str(uuid4()),'document_id':body.document_id,'filename':doc['filename'],'sha256':doc['sha256'],'segments':doc['segments'],'coverage':json.loads(json.dumps(doc['coverage'])),'context':body.model_dump(),'status':'pending','version':1,'issues':[],'original_issues':[],'report_fields':None,'finalized_snapshot':None,'regulations':{i.regulation_id:i.model_dump(mode='json') for i in evidence.regulations},'evidence':evidence.model_dump(mode='json'),'library_version':kb.version,'review_date':date.today().isoformat(),'execution':{'rules_status':'not_started','ai_status':'pending' if body.use_ai else 'disabled','ai_failure_code':None},'events':[],'created_at':now(),'expires_at':doc['expires_at'],'finalized_version':None,'report_id':None}
        store.put(r['review_id'],'review',owner,r,r['expires_at']);store.put(idemid,'idempotency',owner,{'hash':request_hash,'review_id':r['review_id']},r['expires_at'])
        background.add_task(execute,r['review_id'],owner)
        return {'review_id':r['review_id'],'status':'pending','version':1}

    @app.get('/api/reviews/{review_id}')
    async def get_review(review_id:str,req:Request):
        r=require(review_id,'review',auth(req));r.pop('evidence',None);r.pop('finalized_snapshot',None)
        r['summary']={'total':len(r['issues']),**{s:sum(i['review_status']==s for i in r['issues']) for s in ['pending','accepted','rejected','edited','added']},'unverified':sum(i['reference_status']!='verified' or i['location_status']!='verified' for i in r['issues']),
                      'severity':{s:sum(i['severity']==s for i in r['issues']) for s in ['high','medium','low']},
                      'manual_added':sum(i['source']=='manual' for i in r['issues']),
                      'formal_total':sum(i['review_status'] in ['accepted','edited','added'] for i in r['issues'])}
        return r

    def editable(r,version):
        if r['status']!='pending_review':raise APIError(409,'invalid_state','任务不在待复核状态')
        if version!=r['version']:raise APIError(409,'version_conflict','任务已更新，请刷新')

    @app.patch('/api/reviews/{review_id}/issues/{issue_id}')
    async def patch_issue(review_id:str,issue_id:str,body:IssuePatch,req:Request):
        owner=auth(req,True);r=require(review_id,'review',owner);editable(r,body.expected_version)
        original=next((i for i in r['issues'] if i['issue_id']==issue_id),None)
        if original is None:raise APIError(404,'not_found','问题不存在')
        data={k:original[k] for k in AIssue.model_fields if k!='review_status'}
        changes=body.model_dump(exclude_unset=True,exclude={'expected_version','review_status','decision_reason'})
        data.update(changes)
        candidate=AIssue(**data);result=checked(candidate,r,original['source'])
        result.review_status=body.review_status;result.decision_reason=body.decision_reason
        before=json.loads(json.dumps(original));original.clear();original.update(result.model_dump(mode='json'))
        event(r,'issue_'+body.review_status,owner);r['events'][-1].update(before=before,after=original.copy());r['version']+=1;store.save(review_id,r)
        return {'issue':original,'version':r['version']}

    @app.post('/api/reviews/{review_id}/issues',status_code=201)
    async def add_issue(review_id:str,body:AddIssue,req:Request):
        owner=auth(req,True);r=require(review_id,'review',owner);editable(r,body.expected_version)
        if len(r['issues'])>=200:raise APIError(422,'issue_limit','最多200条问题')
        if 'issue_id' in body.issue or 'review_status' in body.issue:raise APIError(422,'invalid_request','问题ID和状态由服务端生成')
        try:candidate=AIssue(**body.issue,issue_id=str(uuid4()))
        except Exception:raise APIError(422,'invalid_issue','问题字段无效') from None
        result=checked(candidate,r,'manual');result.review_status='added';result.decision_reason=body.decision_reason
        obj=result.model_dump(mode='json');r['issues'].append(obj);event(r,'issue_added',owner);r['events'][-1]['after']=json.loads(json.dumps(obj));r['version']+=1;store.save(review_id,r);return {'issue':obj,'version':r['version']}

    @app.get('/api/session')
    async def resume_session(req:Request):
        auth(req)
        session=store.get(digest(req.cookies.get('session','')),'session','session')
        return {'csrf_token':session['csrf']}

    @app.patch('/api/reviews/{review_id}/report-fields')
    async def save_report_fields(review_id:str,body:ReportFieldsPatch,req:Request):
        owner=auth(req,True);r=require(review_id,'review',owner);editable(r,body.expected_version)
        before=r.get('report_fields');r['report_fields']=body.fields.model_dump(mode='json')
        event(r,'report_fields_saved',owner);r['events'][-1].update(before=before,after=r['report_fields'].copy())
        r['version']+=1;store.save(review_id,r)
        return {'report_fields':r['report_fields'],'version':r['version']}

    @app.post('/api/reviews/{review_id}/retry',status_code=202)
    async def retry_review(review_id:str,body:RetryRequest,req:Request,background:BackgroundTasks):
        owner=auth(req,True);r=require(review_id,'review',owner)
        if r['status']!='failed' or r['version']!=body.expected_version:
            raise APIError(409,'retry_conflict','仅可重试当前版本的失败任务')
        # New task and new quota reservation; preserve the previous failure audit.
        result=await create(ReviewCreate.model_validate(r['context']),req,background)
        if result['review_id']==review_id:raise APIError(409,'retry_key_reused','重试请使用独立幂等键')
        new=require(result['review_id'],'review',owner)
        if not new.get('retry_of'):
            new['retry_of']=review_id;event(new,'retry_created',owner);store.save(new['review_id'],new)
        return result

    @app.post('/api/reviews/{review_id}/finalize')
    async def finalize(review_id:str,body:FinalizeRequest,req:Request):
        owner=auth(req,True);r=require(review_id,'review',owner)
        if r['status'] in ['reviewed','issued'] and body.expected_version==r['finalized_version']:return {'review_id':review_id,'status':r['status'],'version':r['version'],'finalized_version':r['finalized_version']}
        editable(r,body.expected_version)
        if not r.get('report_fields'):raise APIError(409,'report_fields_required','请先填写并保存申请部门、审查人员及整体审查意见')
        ReportFields.model_validate(r['report_fields'])
        if not can_finalize([Issue.model_validate(i) for i in r['issues']],coverage_confirmed=body.coverage_confirmed,limitations_acknowledged=body.limitations_acknowledged):raise APIError(409,'unresolved_issues','请完成全部复核并修正或驳回待核实问题')
        r['status']='reviewed';r['version']+=1;r['finalized_version']=r['version'];event(r,'finalized',owner)
        snapshot_keys=['review_id','filename','context','sha256','library_version','execution','coverage','issues','regulations','report_fields','review_date','version','finalized_version']
        r['finalized_snapshot']={k:json.loads(json.dumps(r[k])) for k in snapshot_keys}
        store.save(review_id,r)
        return {'review_id':review_id,'status':r['status'],'version':r['version'],'finalized_version':r['finalized_version']}

    @app.get('/api/reviews/{review_id}/report')
    async def report(review_id:str,req:Request,draft:bool=False):
        owner=auth(req);limit('report:'+owner,10);r=require(review_id,'review',owner)
        if (draft and r['status']!='pending_review') or (not draft and r['status'] not in ['reviewed','issued']):raise APIError(409,'invalid_state','当前状态不能生成此意见书')
        from .reports import build_report
        if not draft and not r.get('finalized_snapshot'):raise APIError(409,'snapshot_required','旧任务缺少人工确认快照，请重新创建并复核')
        try:data=await asyncio.to_thread(build_report,r if draft else r['finalized_snapshot'],draft)
        except Exception:raise APIError(503,'report_failed','文书生成失败，请重试') from None
        # Recheck owner/expiry/deletion after document generation.
        latest=require(review_id,'review',owner)
        if draft and latest['version']!=r['version']:raise APIError(409,'version_conflict','意见已更新，请重新生成')
        if not draft:
            r=latest;r['status']='issued';r['report_id']=r['report_id'] or str(uuid4());store.save(review_id,r)
        return Response(data,media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':'attachment; filename="review-report.docx"','Cache-Control':'no-store','X-Snapshot-Version':str(r['finalized_version'] or r['version']),'X-Report-Id':r['report_id'] or 'draft'})

    @app.delete('/api/reviews/{review_id}',status_code=204)
    async def delete_review(review_id:str,req:Request):
        owner=auth(req,True);require(review_id,'review',owner);store.delete(review_id,owner);return Response(status_code=204)

    @app.delete('/api/documents/{document_id}',status_code=204)
    async def delete_document(document_id:str,req:Request):
        owner=auth(req,True);require(document_id,'document',owner)
        for r in store.list('review',owner):
            if r['document_id']==document_id:store.delete(r['review_id'],owner)
        store.delete(document_id,owner);return Response(status_code=204)

    app.mount('/',StaticFiles(directory=ROOT/'frontend',html=True),name='frontend')
    return app


app=create_app()
