"""Small ASGI request bounds; no body contents are logged or echoed."""
import time
from uuid import uuid4
from starlette.responses import JSONResponse

class RequestBounds:
    def __init__(self,app,max_json_bytes=1024*1024,requests_per_minute=120):
        self.app=app;self.max_json_bytes=max_json_bytes;self.requests_per_minute=requests_per_minute;self.windows={}

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        original_send=send
        async def secured_send(message):
            if message['type']=='http.response.start':
                headers=list(message.get('headers',[]))
                headers.extend([(b'x-content-type-options',b'nosniff'),(b'x-frame-options',b'DENY'),(b'referrer-policy',b'no-referrer')])
                if scope.get('path','').startswith('/api/'):
                    headers=[(k,v) for k,v in headers if k.lower()!=b'cache-control'];headers.append((b'cache-control',b'no-store'))
                message={**message,'headers':headers}
            await original_send(message)
        send=secured_send
        if not scope.get('path','').startswith('/api/'):return await self.app(scope,receive,send)
        async def error(status,code,message):
            return await JSONResponse({'error':{'code':code,'message':message,'request_id':str(uuid4()),'details':{}}},status_code=status)(scope,receive,send)
        # The transport peer is used, never attacker-controlled forwarded headers.
        peer=(scope.get('client') or ('unknown',0))[0];minute=int(time.time()//60)
        if len(self.windows)>4096:self.windows={k:v for k,v in self.windows.items() if v[0]==minute}
        if len(self.windows)>4096:return await error(429,'rate_limited','服务繁忙，请稍后重试')
        previous,count=self.windows.get(peer,(minute,0));count=count+1 if previous==minute else 1;self.windows[peer]=(minute,count)
        if count>self.requests_per_minute:return await error(429,'rate_limited','请求频率超过限制，请稍后重试')
        # Upload has a separate authenticated streaming 10MiB limit.
        if scope['method'] in ['POST','PATCH','PUT'] and scope['path']!='/api/documents/upload':
            body=bytearray();headers=dict(scope['headers'])
            try:length=int(headers.get(b'content-length',b'0'))
            except ValueError:return await error(400,'invalid_length','请求长度无效')
            if length>self.max_json_bytes:return await error(413,'request_too_large','请求内容超过1 MiB限制')
            while True:
                message=await receive()
                if message['type']=='http.disconnect':return
                body.extend(message.get('body',b''))
                if len(body)>self.max_json_bytes:return await error(413,'request_too_large','请求内容超过1 MiB限制')
                if not message.get('more_body',False):break
            sent=False
            original_receive=receive
            async def replay():
                nonlocal sent
                if not sent:
                    sent=True;return {'type':'http.request','body':bytes(body),'more_body':False}
                return await original_receive()
            receive=replay
        return await self.app(scope,receive,send)
