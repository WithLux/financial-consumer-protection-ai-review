# 金融消保智能审查工作台
Financial Consumer Protection AI Review

独立开发的银行消保辅助审查Demo；参考公开行业资料，不代表拓尔思官方软件，不暗示授权、合作或背书。AI输出是待人工复核的辅助意见，不自动认定违法违规。

## 当前交付
仓库初始化、基础目录、配置模板、PRD/架构/API文档及Pydantic契约。业务应用尚未实现，尚未部署，不存在可用的公网应用地址。

## 目标技术栈
HTML5/CSS3/原生JavaScript；Python FastAPI；DeepSeek API；PyMuPDF、python-docx；JSON法规库；Python规则引擎；SQLite；Render。
详细范围、用户故事、优先级和验收标准见 [docs/requirements.md](docs/requirements.md)。
开发顺序见 [docs/implementation-plan.md](docs/implementation-plan.md)。

## 目录
- frontend/：后续页面、样式与交互
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
