import {MockAPI} from './mock.js';
export class RealAPI{
 constructor(){this.csrf='';this.createKeys=new Map();this.retryKeys=new Map();}
 async request(path,{method='GET',body,headers={},binary=false}={}){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),60000);try{const h={...headers};if(body&&!(body instanceof FormData))h['Content-Type']='application/json';if(method!=='GET'&&this.csrf)h['X-CSRF-Token']=this.csrf;let response;try{response=await fetch(`/api${path}`,{method,headers:h,body:body instanceof FormData?body:body?JSON.stringify(body):undefined,credentials:'same-origin',signal:controller.signal});}catch(e){throw new Error(e.name==='AbortError'?'请求超时，请检查任务状态后重试':'无法连接后端API，请确认FastAPI已启动；不会自动切换为Mock。');}if(!response.ok){let value;try{value=await response.json();}catch{}throw new Error(value?.error?.message||`API请求失败（${response.status}）`);}if(binary){const type=response.headers.get('content-type')||'';if(!type.includes('application/vnd.openxmlformats-officedocument.wordprocessingml.document'))throw new Error('接口未返回Word文件');return {blob:await response.blob(),filename:'消保审查意见书.docx'};}return response.status===204?null:await response.json();}finally{clearTimeout(timer);}}
 async login(token){const response=await this.request('/session',{method:'POST',body:{access_token:token}});this.csrf=response.csrf_token;return response;}
 async resume(){const result=await this.request('/session');this.csrf=result.csrf_token;return result;}
 saveReport(id,body){return this.request(`/reviews/${encodeURIComponent(id)}/report-fields`,{method:'PATCH',body});}
 retry(id,body){if(!this.retryKeys.has(id))this.retryKeys.set(id,crypto.randomUUID());return this.request(`/reviews/${encodeURIComponent(id)}/retry`,{method:'POST',body,headers:{'Idempotency-Key':this.retryKeys.get(id)}});}
 upload(file,progress){const form=new FormData();form.append('file',file);progress?.(10);return this.request('/documents/upload',{method:'POST',body:form}).then(x=>{progress?.(100);return x;});}
 create(data){const {scenario,...body}=data;const signature=JSON.stringify(body);if(!this.createKeys.has(signature))this.createKeys.set(signature,crypto.randomUUID());return this.request('/reviews',{method:'POST',body,headers:{'Idempotency-Key':this.createKeys.get(signature)}});}
 get(id){return this.request(`/reviews/${encodeURIComponent(id)}`);}
 patch(id,issue,body){return this.request(`/reviews/${encodeURIComponent(id)}/issues/${encodeURIComponent(issue)}`,{method:'PATCH',body});}
 add(id,body){return this.request(`/reviews/${encodeURIComponent(id)}/issues`,{method:'POST',body});}
 finalize(id,body){return this.request(`/reviews/${encodeURIComponent(id)}/finalize`,{method:'POST',body});}
 report(id,draft){return this.request(`/reviews/${encodeURIComponent(id)}/report?draft=${draft}`,{binary:true});}
}
export const createAPI=mode=>mode==='real'?new RealAPI():new MockAPI();
