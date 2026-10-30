# 技术架构与执行边界
版本1.0；2026-10-30。合同模型和校验函数已实现，以下HTTP、工作器、存储、解析、AI与文书模块为待实现设计。

## 1. 单服务结构
浏览器HTML/CSS/原生JS → 同域FastAPI /api → 鉴权/限流/对象归属检查 → 文档解析或任务服务 → SQLite。
任务服务 → Python规则引擎 + 可选DeepSeek客户端 → 候选校验/合并 → 人工工作台。
任务服务 → 固定最终快照 → python-docx文书生成 → 授权流式下载。
JSON法规库只读加载且版本化。模型只接收筛选后的条款ID和必要文本，不可写入知识库、执行工具或访问文件系统。
计划文件：backend/main.py入口；documents.py文档；reviews.py状态/复核；parsers.py子进程解析；rules.py初筛；ai.py模型；repository.py参数化SQLite；reports.py文书。backend/models.py为当前已存在的契约及纯校验函数。
前端规划：index.html、styles.css、app.js；后端同域挂载静态资源，/api路由先注册，静态回退不得吞掉API错误。无外部向量库、前端框架或微服务。

## 2. 执行与持久化
上传同步校验/解析，返回201 ready或错误，不暴露半成品文档。解析在隔离子进程执行，父进程执行超时终止，ZIP解压前检查总量和条目；PDF混合扫描检测产生coverage告警。不能认为限制文件大小就限制了解压/CPU/内存。
POST /api/reviews持久化pending和幂等键后202；单Uvicorn worker内轮询SQLite队列，通过条件更新原子领取running。不在请求中阻塞模型调用。启动恢复遗留running为failed（interrupted），pending保留待领取；TTL到期任务不执行。
规则必须成功；AI由use_ai及服务端开关/密钥共同控制。AI不可用时rule-only并显示原因；无可用规则仍允许人工复核，但coverage标记no_rules，不宣称自动审查成功。规则自身异常则failed，不以空结果掩盖。
合并仅对相同segment/start/end/risk_type候选；保留来源链和原始候选；去重后服务端生成新issue_id，模型ID只作为candidate_id审计字段。source为ai/rule/manual，不能由用户任意指定。

## 3. 数据关系
SQLite计划表：documents(id, owner_id, sha256, status, segments_json, warnings_json, created_at, expires_at)；reviews(id, document_id, owner_id, status, version, context_json, library_snapshot_json, model_state, coverage_json, finalized_snapshot_json, created_at, expires_at)；issues(id, review_id, current_json, original_json)；events(id, review_id, actor_id, before_json, after_json, at)；reports(id, review_id, snapshot_version, is_draft, file_path, at)；idempotency(owner_id,key,request_hash,review_id,expires_at)。外键开启，事务保护状态及审计同时提交。
文档1:N任务、任务1:N问题/事件/文书。ID使用服务端随机UUID，owner从会话获取；不靠UUID难猜作为权限控制。
version初值1，每次问题变更/新增/finalize递增；PATCH/finalize携带expected_version，SQL按version条件更新，失败409；工作器状态更新也递增。最终快照包含材料哈希、segment、证据条款和规则版本、人工意见及覆盖，之后只读。
模型候选schema位于schemas/ai-review-result.schema.json，由Pydantic生成。JSON shape校验后validate_issue核对原文、库ID、生效和失效日期、材料/渠道；产品类型和上下文适用需人工确认。任一未知/不适用ID标needs_verification，列表保留待核实ID；不自动补造链接。引文必须在单segment范围，缺失披露类以现有上下文锚定并解释缺失，禁止虚构原文。

## 4. 安全与数据生命周期
同源HTTPS。Demo入口采用服务端DEMO_ACCESS_TOKEN校验登录，成功建立独立随机HttpOnly/Secure/SameSite=Strict会话；session标识仅存服务端，页面无API Key。共享入口密码不共享owner_id；会话丢失不可恢复旧数据，UI须说明。实现需补POST /api/session与DELETE /api/session，状态变更请求检查Origin及CSRF token；禁止宽松CORS。
服务端环境变量读取DeepSeek密钥，客户端不提交/覆盖Key、base_url、模型名。base_url管理员可信配置，限制官方HTTPS地址，避免SSRF。用户选择AI时须确认合成/授权脱敏数据并明确外部传输；此确认不是法定授权证明。
文件随机目录、扩展名及magic/ZIP结构校验、上传流式硬限额、TXT拒绝NUL及非法UTF-8；不下载文档中远程资源。展示用textContent/文本节点，不拼innerHTML；查询参数化。下载只用存储文件ID，不接收任意路径。
原始文件在解析finally删除，异常和超时同样删除；文本/结果/文书TTL默认24h。清理每5分钟执行，读写请求先检查过期；删除文档事务删除所有关联任务及审计、设置墓碑令牌，工作器写回检查墓碑以防复活，文件异步清理失败进入重试队列。清理日志只记录计数和随机ID。短期Demo审计随任务删除，不宣称法定长期档案。
限流/并发/日预算见PRD；日预算通过SQLite原子预留token额度，失败结算；达到上限只允许规则模式。网关/IP限流为补充，同会话配额不足以防反复建会话滥用。

## 5. Render单服务
计划构建pip install -r requirements.txt；入口实现后启动uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 1。健康路径/api/health。选Python3.12；本轮模型测试实际环境Python3.13/Pydantic2.11.5，完整依赖/3.12兼容性仍待验证。
SQLite及runtime置于同一持久目录DATA_DIR；公开演示选择有足够资源及持久磁盘的Render配置。若使用临时文件系统，重启/部署会丢任务，必须明示且不能承诺持久化；无持久化条件时暂不开放用户材料上传。扩容多实例前需改造共享存储/队列，不直接复制SQLite。
render.yaml暂不提供可执行部署入口：main.py尚未实现。config/runtime.example.json为设计配置，仍需后续运行时加载、约束和启动校验。

## 6. 验证边界
已测试纯契约：未知引用、引用日期/渠道、错引文、Unicode、重复ID、人工决定限制、状态允许边和完成门槛。未测试HTTP、鉴权、资源隔离、AI真实请求、解析库、SQLite并发、Word和Render；不得把Schema测试当端到端成功。
