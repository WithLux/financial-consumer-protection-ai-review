// Minimal DOM contract harness. Does not replace browser layout/accessibility testing.
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createAPI} from '../frontend/api.js';
import {reportText} from '../frontend/report.js';
class Element{
 constructor(tag='div'){this.tag=tag;this.children=[];this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.textContent='';this.attrs={};this.className='';this.classList={add:()=>{},remove:()=>{},toggle:()=>{}};}
 append(...nodes){this.children.push(...nodes);if(this.tag==='select'&&!this.value&&nodes[0]?.value)this.value=nodes[0].value;}
 replaceChildren(...nodes){this.children=[...nodes];}
 setAttribute(k,v){this.attrs[k]=v;}
 addEventListener(name,fn){this['on'+name]=fn;}
 querySelector(selector){return flatten(this).find(x=>x.tag===selector)||null;}
 click(){return this.onclick?.({preventDefault(){}});}
 remove(){} showModal(){this.open=true;} close(){this.open=false;} scrollIntoView(){}
}
const flatten=node=>[node,...node.children.flatMap(x=>flatten(x))];
const nodes=new Map();
const html=await readFile('frontend/index.html','utf8');
for(const match of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"[^>]*>/g))nodes.set(match[2],new Element(match[1]));
for(const [id,value]of Object.entries({material:'marketing',channel:'online',product:'理财',audience:'个人客户',scenario:'normal','risk-filter':'all','status-filter':'all'}))nodes.get(id).value=value;
const document={getElementById:id=>nodes.get(id),createElement:tag=>new Element(tag),createTextNode:text=>Object.assign(new Element('#text'),{textContent:text}),querySelectorAll:()=>flatten(nodes.get('issues')).filter(x=>x.tag==='button'),body:new Element('body')};
let queued=[];const context=vm.createContext({document,createAPI,reportText,URL,URLSearchParams,File,crypto,console,location:{search:'',href:'http://localhost/'},history:{replaceState(){}},setTimeout:fn=>{queued.push(fn);return queued.length;},clearTimeout:()=>{queued=[];}});
const js=(await readFile('frontend/app.js','utf8')).replace(/^import .*?;\n/gm,'');
vm.runInContext(js,context);
assert.equal(nodes.get('start').disabled,true);
await nodes.get('sample').click();
assert.equal(nodes.get('start').disabled,false);
await nodes.get('start').click(); // Covers API create returning only id, status and version.
assert.equal(nodes.get('task-status').textContent,'审查中');
await queued.shift()();
assert.equal(nodes.get('task-status').textContent,'待复核');assert.equal(nodes.get('total').textContent,2);
const buttons=()=>flatten(nodes.get('issues')).filter(x=>x.tag==='button');
await buttons().find(x=>x.textContent==='保证收益').click();
assert.equal(nodes.get('source').querySelector('mark').textContent,'保证收益');
const modalInput=label=>flatten(nodes.get('modal-body')).find(x=>x.tag==='label'&&x.textContent===label).children[0];
async function submit(){await nodes.get('modal-form').onsubmit({preventDefault(){}});}
await buttons().find(x=>x.textContent==='接受').click();
await submit();assert.match(nodes.get('modal-error').textContent,/理由/);
modalInput('人工决定理由（必填）').value='人工核实采纳';await submit();
assert.equal(nodes.get('review-progress').textContent,'1 / 2');
await buttons().find(x=>x.textContent==='无需阅读风险提示').click();
// The second expanded card has no confirmed legal reference: reject rather than falsely finalize.
await buttons().filter(x=>x.textContent==='驳回').at(-1).click();modalInput('人工决定理由（必填）').value='仅为合成负例';await submit();
assert.equal(nodes.get('review-progress').textContent,'2 / 2');
await buttons().find(x=>x.textContent==='编辑').click();
modalInput('人工决定理由（必填）').value='根据产品背景修订建议';
modalInput('问题说明（必填）').value='人工修改的问题说明';modalInput('风险等级').value='low';modalInput('修改建议（必填）').value='准确说明风险，删除保证性表述';await submit();
await nodes.get('add').click();
modalInput('原文段落').value='s2';
modalInput('问题原文（必须与所选段落完全相同）').value='保证收益';
modalInput('起始位置（Unicode码点，从0开始；重复句须准确指定）').value='2';
modalInput('分析原因及人工决定理由（必填）').value='人工补充核实';
modalInput('修改建议（必填）').value='核实并修改';
await submit();assert.equal(nodes.get('review-progress').textContent,'3 / 3');

await nodes.get('finalize').click();assert.match(nodes.get('feedback').textContent,/复核/);
nodes.get('coverage-confirm').checked=true;nodes.get('limits-confirm').checked=true;
await nodes.get('report-fields').click();
for(const [label,value] of [['申请部门（必填）','测试业务部'],['审查人员（必填）','测试审查员'],['最终审查结论（必填，由人工自主填写）','人工认为需修改'],['整改建议及审查说明（必填）','请逐项核实']])modalInput(label).value=value;
await submit();assert.match(nodes.get('final-conclusion').textContent,/人工认为需修改/);
await nodes.get('finalize').click();assert.equal(nodes.get('task-status').textContent,'复核完成');
await nodes.get('preview').click();assert.equal(nodes.get('modal').open,true);nodes.get('modal').close();
await nodes.get('download').click();assert.equal(nodes.get('task-status').textContent,'已出具意见书');
// Drag/drop and extension validation use the same real handlers as file input.
await nodes.get('dropzone').ondrop({preventDefault(){},dataTransfer:{files:[new File(['测试文本'],'drag.txt')]}});
await new Promise(resolve=>setImmediate(resolve));
assert.match(nodes.get('file-info').textContent,/drag.txt/);
nodes.get('file').files=[new File(['x'],'bad.exe')];nodes.get('file').onchange({target:nodes.get('file')});
await new Promise(resolve=>setImmediate(resolve));assert.match(nodes.get('feedback').textContent,/仅支持/);
nodes.get('scenario').value='failed';await nodes.get('start').click();await queued.shift()();assert.equal(nodes.get('task-status').textContent,'处理失败');
await nodes.get('retry').click();await queued.shift()();assert.equal(nodes.get('task-status').textContent,'待复核');
console.log('UI contracts passed: upload, partial create response, polling, highlight, reason guard, accept/reject, counters, finalize, preview and download');
