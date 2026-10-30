# 前端实现与验证记录
日期：2026-10-30；页面产品名：智能消保审查平台；独立Demo，不使用TRS品牌标识。

## 实现范围
index.html/style.css/app.js：深蓝导航、材料区、任务状态/统计、原文和结果双栏、详情/筛选、人工处理弹窗、补充问题、最终确认及意见书预览/下载。
api.js：同源/api封装、会话cookie、CSRF、幂等创建、超时、错误反馈及二进制Word响应检查；不自动回退Mock。
mock.js：独立内存MockAPI；TXT读取用户文本；PDF/DOCX明确使用固定合成样本，不假装解析。含正常、AI失败降级、处理失败三种情形。刷新页面清空数据；执行状态和结果均明确属于Mock。
report.js：Mock专用最小OOXML文书生成；含明确Mock和非银行签批标识；真实模式下载后端python-docx文件。前端预览为内容预览，不承诺与正式Word分页相同。

## 自动化检查
- tests/frontend-contracts.mjs：独立Mock端到端状态、版本冲突、确认门槛及Word二进制。
- tests/frontend-api.mjs：真实API请求URL/方法、cookie/CSRF、重复创建幂等键、Mock专属字段剔除、非Word及网络错误。
- tests/frontend-ui.mjs：最小DOM契约测试（非完整浏览器），执行实际app.js事件；样本/选择与拖拽、任务简短响应、轮询、Unicode映射高亮、必填理由、接受/驳回/编辑/补充、计数、最终确认、预览与下载。
- Node语法检查通过；既有14项Python契约测试通过。
- Mock DOCX用Python zipfile检查CRC及全部XML可解析；尚未在Microsoft Word检查分页排版。

## 浏览器实测与限制
终端Python HTTP服务器及Node预览服务器均因EPERM无法监听本地端口。Playwright默认浏览器未安装，尝试已安装Chrome无头进程时受环境权限限制退出。
在已登录Chrome中，以临时离线内联副本实际运行前端，确认页面加载、样本读取、原文展示、审查中→待复核、问题列表、风险统计。发现初始创建响应没有issues数组的运行错误并修复，再次验证状态和结果正常。
独立预览浏览器拒绝file协议（仅允许http/https），之后未绕过此限制。完整浏览器高亮/弹窗/下载、控制台无异常检查，以及1440px/常见笔记本视觉截图验收尚未完成。CSS已提供1200px/850px断点，但不能把断点存在当作视觉实测。
临时离线副本不提交，正式运行依旧使用ES模块及同域HTTP。

## 待B4后端连接
/api/session；/api/documents/upload；POST /api/reviews；GET /api/reviews/{id}；PATCH /api/reviews/{id}/issues/{issue_id}；POST /api/reviews/{id}/issues；POST /api/reviews/{id}/finalize；GET /api/reviews/{id}/report。
HTTP路由、鉴权、真实文件解析、模型、持久化与文书仍未实现，前端选择“真实API”会真实发请求并展示失败，不生成替代结果。材料历史/删除接口尚未接入当前页面，待后续材料管理迭代。
