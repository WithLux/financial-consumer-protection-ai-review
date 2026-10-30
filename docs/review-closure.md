# 人工复核与意见书闭环
2026-10-30；已实现内容，延续独立Demo和24小时隔离会话边界。

## 操作流程
上传并执行 → 待复核 → 逐条接受/驳回/编辑/人工补充 → 填写整体审查意见并保存 → 确认解析覆盖和法规具体适用等限制 → 最终确认 → 预览/下载Word。
编辑支持风险等级、风险说明、修改建议及法规ID；法规ID修改后由服务端重新核验，不能手写verified。原文位置不通过或法规未核实的采纳意见不能最终确认。驳回必须有人工理由。
整体意见必填申请部门、审查人员、审查日期、范围、最终结论、整改建议及说明；结论无AI默认值，由人工自主填写。所有字段只在pending_review可修改，最终确认后锁定。需要改动的正式版本应新建任务复核，本轮不提供绕过确认的直接改写接口。

## 数据与状态
- review.original_issues保存初始机器候选，review.issues保存当前人工意见；events包含时间、会话操作者、动作及修改前后内容。人工新增有独立事件和source=manual。原始候选不会因编辑/驳回被覆盖。
- summary.total/severity为当前候选（含驳回）统计；accepted/rejected/edited/added按状态计数；manual_added按source=manual计数（即使被编辑/驳回仍计为曾人工新增），formal_total为accepted/edited/added问题数。均不是模型准确率。
- report_fields保存整体意见，带expected_version乐观锁；最终确认要求全部问题已处理、已采纳项目依据/位置通过校验、整体意见完整且两项人工确认成立。
- 最终确认生成finalized_snapshot，固定问题、法规文本和URL、人工整体意见、范围、材料与版本。正式报告从该快照生成；旧任务若没有快照，拒绝生成最终文书，需新建任务复核。
- 六态保持pending/running/pending_review/reviewed/issued/failed。GET Word只有reviewed/issued可生成正式版本；pending_review可生成带明显标识的草稿。生成失败保留reviewed可重试。已出具表示文书已生成，不表示具有银行正式签批效力或证明已下载。
- 失败重试仅failed；POST retry创建独立新任务并记录retry_of，旧失败记录不变；必须原会话材料仍有效、独立幂等键、版本匹配，仍受并发/限流/预算控制。不把已完成但AI降级的任务自动重跑并消耗费用。

## 接口增量
PATCH /api/reviews/{review_id}/report-fields：{expected_version,fields:{applicant_department,reviewer,review_date,review_scope,final_conclusion,remediation_notes}}。
POST /api/reviews/{review_id}/retry：{expected_version}，另带独立Idempotency-Key，返回202的新review_id。
GET /api/session：原HttpOnly会话有效时返回CSRF token；不会返回全站材料或其他用户信息。
GET review增加original_issues、report_fields、events、summary及retry_of（重试任务）。后端不对客户端暴露可写的最终快照字段。

## Word范围
标题《金融消费者权益保护审查意见书》；包含编号、材料名称、申请部门、材料类型、人员、日期、范围、材料哈希/版本、人工确认问题、引文位置、风险说明、法规ID/条文/来源及建议、整体结论、整改说明和辅助审查边界。
正式清单只采用accepted/edited/added；rejected不会以问题、理由、法规、建议或审计明细的方式出现在文书。被驳回内容仅在隔离任务审计中保留。草稿也排除驳回项。

## 隐私与持久化
SQLite和审计仅短期会话内保存；浏览器sessionStorage仅保存当前任务ID，不保存材料、密钥或问题原文。刷新真实模式通过现有cookie恢复会话及当前任务，仍受服务端owner检查与TTL。重新连接会创建新会话，不可恢复旧会话数据；无全站历史列表。
Render仍需实际配置持久磁盘；临时文件系统可能丢记录。本轮本地同数据库重启测试不构成Render长期持久化证明。

## 验证记录
新增5项后端闭环测试：接受模拟AI候选入Word；驳回项排除；等级/说明/建议及原始意见保留；人工新增；整体意见完整性与快照锁定；法规文本/链接一致；任务/报告/修改跨会话隔离；失败重试；同文件重启恢复。
Word使用python-docx重新打开并检查正文及表格，不声称已在Microsoft Word实测分页。模拟AI只用于构造候选，不代表真实DeepSeek调用成功。
前端最小DOM契约测试执行真实app.js事件，增加等级/说明编辑、整体意见保存、结论展示及失败重试；该测试不替代真实浏览器视觉验收。
本机Uvicorn监听受EPERM限制，接口经真实ASGI应用验证；PyMuPDF仍缺失，相关实测跳过；没有真实模型密钥。上述既有环境限制仍有效。

最终回归：30项Python测试中29通过、1项PDF环境相关实测跳过；3组前端契约测试通过。无真实DeepSeek调用验证，浏览器端口限制未解除。
