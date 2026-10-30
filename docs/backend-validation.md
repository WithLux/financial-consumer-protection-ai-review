# B4 后端实现与验证记录
2026-10-30。真实业务实现，不包含后端Mock兜底；端口/模型实测边界如下。

## 已实现模块
- main.py：FastAPI静态前端、会话、上传、创建/轮询、人工修改/补充、最终确认、Word报告及删除。
- document_parser.py：真实类型检查、UTF-8/BOM、PyMuPDF文本/页、python-docx正文与表格顺序、Unicode偏移；隔离子进程15秒超时，Linux地址空间512MiB；macOS不宣称已实施内存硬上限。
- regulation_service.py/rule_engine.py：独立法规/规则JSON，日期/材料/渠道/产品范围筛选；关键词命中与缺词提示均为启发式，不是法律结论。
- ai_service.py：兼容Chat Completions、服务端配置、单次调用、60秒默认超时、3000输出tokens、2MiB响应上限、2万码点输入限制；超限/出错明确降级为真实规则结果，不返回Mock。
- storage.py：SQLite所有者隔离、会话、幂等、复核版本、短期审计、每日保守预算；到期清理，不留原始上传文件。
- reports.py：python-docx真实Word生成，依据来自任务快照，保留人工判断和处理限制。
- models.py复用已有Pydantic结构和原文/依据校验，不另建平行schemas.py以免字段冲突。

## 本轮实测
使用本机离线可用Python3.12运行环境（运行时docx/lxml/Pydantic加本机纯Python服务依赖）执行真实FastAPI TestClient/ASGI应用。
25项Python测试：24通过，1项PDF实测跳过；3组前端契约测试通过。
实测包括TXT与DOCX真实解析（含API隔离子进程）、上传类型/编码/大小、规则结果非固定样本、同域静态页面、会话/CSRF与数据隔离、幂等/过期/版本冲突、人工补充的错误定位及虚构ID标记、最终确认和Word ZIP结构。
模拟模型HTTP响应测试覆盖成功JSON、错误JSON、429、5xx、超时、网络失败、长文本超限；提示注入样本确认作为user.document数据传递，不提升为system指令。此检查不证明可以消除所有提示注入风险。

## 明确未验证
没有DEEPSEEK_API_KEY，未发起真实DeepSeek请求，不能宣称真实AI调用通过。模型成功与失败只完成httpx.MockTransport模拟测试；解析和规则则是真实运行，不能把全部测试统称Mock。
PyMuPDF本机缺失，pip联网安装因DNS限制失败；PDF实现已编写但真实PDF提取、扫描及加密PDF测试待安装依赖后执行。缺组件时API明确503 parser_unavailable。
Uvicorn实际启动成功、应用生命周期初始化完成，但监听127.0.0.1:8765被系统EPERM拒绝；无可访问的本地HTTP服务。通过ASGI验证接口响应不等于已完成浏览器网络联调或公网部署。
完整requirements安装/精确锁定、Linux内存限制、并发负载和Render部署仍需可联网运行环境验证。

## 当前实现相对设计文档的差异（以此为已实施状态）
- 法规库regulations.json中的rules为空；rules.json是唯一执行规则源，由load_library合并并校验外键。三个真实官方条款已核验；三个启用关键词规则仍是unverified/heuristic，不把启用等同法规强制要求。缺词提示没有硬编法律依据。
- 异步任务使用FastAPI BackgroundTasks和SQLite状态；单worker，最多2个在途任务，每会话1个。进程重启后pending/running标为failed/interrupted，不恢复网络调用。
- 原件只驻留上传解析生命周期，multipart临时文件退出form上下文关闭；解析结果/审计/意见书快照24小时TTL。Word按不可变快照请求时生成，未保存文书文件缓存；已出具表示生成完成，不证明下载成功。
- 到期或删除、他人资源统一404，暂未采用独立410及删除重复204语义；材料列表最多100条，未实现分页；API文档同步说明。
- 每日Token预算按保守预留记账，不按实际账单结算；失败也不自动返还，避免重试耗费放大。限制1次外部调用/任务，无自动重试。管理员可设置兼容供应商HTTPS URL，不接受客户端覆盖；不提供外部工具执行或自动抓取。
- 会话和版本检查支持单worker；不宣称可直接多worker或多实例扩容。清理周期5分钟、读写检查到期；删除后晚到模型结果只UPDATE现有未过期行，无法重新创建记录。
- 公开部署仍需强口令、HTTPS Cookie、持久化、网关限流、资源/配额实测与完整安全评估；当前是独立Demo，不能用于真实敏感材料生产审查。
