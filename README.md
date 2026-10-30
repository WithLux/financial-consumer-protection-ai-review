# 金融消保智能审查工作台
Financial Consumer Protection AI Review

独立开发的银行消保辅助审查Demo；参考公开行业资料，不代表拓尔思官方软件，不暗示授权、合作或背书。AI输出是待人工复核的辅助意见，不自动认定违法违规。

## 当前交付
仓库初始化、基础目录、配置模板、PRD/架构/API文档及Pydantic契约。前端工作台及独立Mock已实现；后端业务接口尚未实现，尚未部署，无公网应用地址。

## 目标技术栈
HTML5/CSS3/原生JavaScript；Python FastAPI；DeepSeek API；PyMuPDF、python-docx；JSON法规库；Python规则引擎；SQLite；Render。
详细范围、用户故事、优先级和验收标准见 [docs/requirements.md](docs/requirements.md)。
开发顺序见 [docs/implementation-plan.md](docs/implementation-plan.md)。

## 目录
- frontend/：已实现页面、样式、原生JS及Mock/真实API适配器
- backend/：后续接口、解析、规则、模型、任务和导出服务
- data/regulations/：一个官方核验条款样例及默认禁用的启发式规则，非完整规则库
- data/demo_samples/：仅合成演示材料，不含真实客户资料
- tests/：后续解析、审查、人工处置、导出与端到端测试
- docs/：需求、证据和执行记录

## 开发准备（业务启动入口尚待实现）
Python 3.11或3.12，创建虚拟环境后安装 requirements.txt。依赖版本范围为初始约束，尚未完成全量安装验证及锁定。
复制 .env.example 为 .env 并填写服务端配置；不得提交 .env。后续运行命令和Render配置将在接口入口实现并验证后补充。
DeepSeek缺省采用环境变量中的模型标识；实际可用模型需按官方文档核验。无密钥时未来仅提供明确标识的规则审查模式。

## 演示数据边界
只允许合成或已获授权且脱敏的材料。公开HTTPS演示与私有仓库相互独立；启用用户上传和模型调用前应完成访问保护、限流、任务隔离和数据清理机制。

## 版本与远程
默认分支 main；开发分支 feature/ai-review-demo。
GitHub：https://github.com/WithLux/financial-consumer-protection-ai-review （Private）。

## 当前设计与校验
- [PRD](docs/PRD.md)
- [架构](docs/architecture.md)
- [API](docs/api.md)
- backend/models.py：Pydantic契约、引用/引文校验和状态门槛
- schemas/：从模型生成的JSON Schema
运行纯契约测试：`python3 -m unittest discover -s tests -v`；HTTP路由和业务运行入口尚待实现。

## 前端运行（无需npm安装或构建）
在项目根目录运行：
```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory frontend
```
浏览器访问 http://127.0.0.1:8765/ ，默认Mock演示。使用“载入演示样本”或上传TXT；PDF/DOCX在Mock中只显示固定合成样本。页面始终标记Mock，不调用真实AI。Mock刷新即清空，Word是有明确演示标识的最小文书。
如系统禁止监听端口，需在允许本地监听的开发环境启动；本轮环境遇到该限制，验证范围见 [前端验证记录](docs/frontend-validation.md)。直接file打开源index.html不支持ES模块加载，应通过HTTP运行。

### 连接FastAPI
后续FastAPI在同一域名提供frontend静态资源与/api路由；选择右上角“真实API”或访问 `/?mode=real`。点击“连接会话”输入服务端Demo访问口令（不是DeepSeek密钥）；密钥始终仅存在服务端。静态Python服务器不提供API，真实模式请求失败属于预期，不会回退Mock。
接口路径统一在frontend/api.js；B4遵循docs/api.md即可连接，不需重写页面。Mock数据和专属DOCX生成仅在mock.js/report.js使用。

### 前端测试
Node.js 20+，无新增依赖：
```sh
npm run test:frontend
```
测试覆盖接口/交互契约；完整浏览器视觉验收、真实后端联调及Word分页另需执行。
