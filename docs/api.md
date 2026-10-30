# API契约 v1.0
2026-10-30；HTTP路由已实现；B4实际范围与差异见backend-validation.md。与backend/models.py及PRD.md同版本。
所有API以/api为前缀，JSON UTF-8；上传multipart，下载DOCX。/api/health匿名，其余鉴权；写操作需Origin/CSRF检查（见architecture.md）。资源不存在或不属于会话统一404，到期/删除统一404（当前实现）。请求禁止owner_id、API密钥、模型名、任意文件路径。
错误统一形状：{"error":{"code":"version_conflict","message":"任务已更新，请刷新","request_id":"随机追踪ID","details":{}}}。details不得含材料全文、密钥、堆栈。常用400/401/403/404/409/410/413/415/422/429/503。

## POST /api/documents/upload
multipart字段file必填，仅单文件。201响应：document_id、filename、sha256、status=ready、segments=[{segment_id,text,locator:{kind,page?,paragraph?,table?,row?,cell?,line?}}]、coverage={complete,warnings}、created_at、expires_at。locator仅服务端解析；PDF页码/TXT行号和DOCX段、表、行、单元格均从1开始。
解析同步完成；坏文件422、格式415、大小413、资源超限422(code=parse_limit)、等待服务满503。原始文件解析后删除。新上传返回新ID，不覆盖旧材料。

## POST /api/reviews
Header Idempotency-Key必填随机值，按owner保存24h；同key同body返回原任务（202 pending/running，否则200），同key不同body409。
请求对应ReviewCreate：
```json
{"document_id":"doc-uuid","material_type":"marketing","channel":"online","product_type":"理财","audience":"个人客户","use_ai":false,"external_processing_authorized":false}
```
材料必须ready且未过期；external_processing_authorized=false但use_ai=true时422。202返回{review_id,status:"pending",version:1}。创建即排队执行，不另设/tasks或/run端点。后续工作器领取后GET显示running；密钥缺失时即使选择AI也明确降级，不返回模型成功。

## GET /api/reviews/{review_id}
200返回：review_id、document_id、status（六态）、version、context（创建背景）、segments、coverage、execution={rules_status:not_started/running/succeeded/failed,ai_status:disabled/pending/succeeded/failed,ai_failure_code:null或脱敏原因}、issues、summary、created_at、expires_at、finalized_version、report_id。
Issue对应models.Issue：issue_id,risk_type,severity,original_text,location,reason,regulation_ids,suggestion,review_status,source,location_status,reference_status,unverified_regulation_ids,decision_reason。
summary固定字段：total、pending、accepted、rejected、edited、added、unverified；unverified计算任一引用/定位状态待核实的问题数，不与决定状态计数相加。
展示依据详情regulations字段为该任务知识库快照中已知引用条目的映射；未知ID仅作为待核实字符串显示，不由客户端构造URL。轮询2秒，终态/待复核停止。

## PATCH /api/reviews/{review_id}/issues/{issue_id}
仅pending_review；请求对应IssuePatch：
```json
{"expected_version":3,"review_status":"edited","decision_reason":"已核对产品背景并修订","suggestion":"请删除保证收益的表述"}
```
可选字段reason、severity、regulation_ids、location、original_text。review_status仅accepted/rejected/edited，所有操作必须有非空理由。original_text与location如变更须成对传入；edited至少有一个内容字段变更，其余操作不附内容修改。服务端按保存后的完整对象重新校验并派生核验状态；不能通过请求把verified写入。200 {issue,version}；并发409；形状422；无法定位/引用仍可保存为待核实，但不能被采纳完成。原始候选和before/after存审计。

## 补充：POST /api/reviews/{review_id}/issues
手工新增是MVP必需，不能用PATCH虚构不存在的问题。请求{expected_version,issue:AIssue字段但不含issue_id/review_status,decision_reason}；服务端分配ID、source=manual、review_status=added，验证定位和引用。201 {issue,version}。仅pending_review。无法校验者保留待核实；可后续修正或驳回。

## POST /api/reviews/{review_id}/finalize
请求对应FinalizeRequest：{expected_version,coverage_confirmed:true,limitations_acknowledged:true}。只有pending_review且can_finalize通过才转换reviewed；所有问题有决定，采纳/编辑/补充问题的引用及定位通过；拒绝项可保留未核实标志但必须有理由。空问题列表也要求两项确认。
200 {review_id,status:"reviewed",version,finalized_version}。未满足409(code=unresolved_issues)，不同版本409(version_conflict)。对已reviewed/issued任务，相同finalized_version请求可返回现有快照（幂等），不重复修改。无权身份不能提交。

## GET /api/reviews/{review_id}/report
查询draft=true/false，缺省false。draft=true仅pending_review，返回明显标记“未完成复核草稿”的DOCX，不改变业务状态；最终report仅reviewed/issued，其他409。响应200 Content-Type=application/vnd.openxmlformats-officedocument.wordprocessingml.document，Content-Disposition=attachment，Cache-Control=no-store，X-Report-Id，X-Snapshot-Version。
首次最终请求按不可变快照生成并保存文书后reviewed→issued，故此GET具有受限生成副作用；前端必须由下载按钮触发，不做预取。断网不表示下载完成；issued只表示生成完成。相同快照重复请求复用文件，锁防并行重复生成。生成失败503并保留reviewed，可重试；draft失败不变。后续如需严格无副作用GET，可新增POST reports，但本轮遵循指定路径。
文书包含任务/材料/规则/模型版本、scope、coverage、辅助声明、人工确认意见、引文位置、条款及官方链接、修改建议、拒绝项计数及审计摘要。不得把驳回项作为整改意见；不生成银行签章。

## GET /api/health
200 {status:"ok",schema_version:"1.0"}；必要依赖未就绪503 {status:"degraded"}。检查服务启动、SQLite可用及知识库结构合法，不因AI无密钥就判断服务不可用；不披露环境变量、路径、任务数或客户内容。

## 材料管理与访问补充接口
GET /api/documents：本人未过期材料列表，分页默认20/最大100，不返回全文。
DELETE /api/documents/{document_id}：204，删除关联任务和文件；运行中任务取消，按墓碑防止写回。
DELETE /api/reviews/{review_id}：204，仅删任务/意见/文书，共享document保留到期；本人已删请求可幂等204，未知或他人404。
POST /api/session：{access_token}校验Demo入口，发HttpOnly Secure SameSite=Strict cookie和CSRF token；限流且不记录密码，失败401。DELETE /api/session：注销会话cookie（资源仍按TTL清理）。
以上补充接口均已实现；列表暂未分页，删除重复请求返回404，详细限制见backend-validation.md。

## 枚举与定位约定
任务pending/running/pending_review/reviewed/issued/failed；人工pending/accepted/rejected/edited/added；risk_type=misleading/return_promise/disclosure/choice/privacy/other；severity=high/medium/low。文本半开区间[start,end)以Unicode码点计数，不是JS UTF-16。location={segment_id,start,end}；定位状态和引用状态各为verified/needs_verification；AI结果不允许携带这些服务端字段。
AIReviewResult={schema_version:"1.0",issues:[AIssue]}，AIssue.review_status只能pending；形状错误重试至多1次，仍错误ai_status=failed并规则降级。候选最多200；未知字段拒绝。模型输出不能包含最终意见书、官方链接或自动法律认定。

B4配置/行为：单次模型调用，无自动重试；失败通过execution.ai_failure_code与coverage.warnings公开，规则结果保持真实。实际后台任务使用BackgroundTasks；进程重启pending/running中断标failed；文书按锁定快照重新生成而不缓存文件。正文早期的独立410、删除重复204、生成文件缓存/重试一次为原设计，当前以本段与backend-validation.md明确的实施差异为准。

## 人工复核闭环增量（2026-10-30，已实现）
PATCH /api/reviews/{review_id}/report-fields接收ReportFieldsPatch；fields必须完整包含申请部门、审查人员、日期、范围、人工最终结论、整改建议。返回report_fields和新version，仅待复核可保存。
POST /api/reviews/{review_id}/retry接收{expected_version}及独立Idempotency-Key，仅失败任务可创建新任务（202），旧记录不变，返回新任务对应retry_of。
GET /api/session恢复原短期会话及CSRF，权限/过期仍由服务端控制。
最终确认额外要求report_fields完整；返回固定版本并持久化finalized_snapshot。正式Word只含accepted/edited/added，不列驳回项；original_issues和带时间的before/after审计在隔离GET review中可查。原报告条款中“审计摘要”不再包括驳回内容明细。
完整数据语义与统计口径见review-closure.md；report-fields.schema.json由Pydantic生成。
