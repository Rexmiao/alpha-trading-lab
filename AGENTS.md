# 项目后续操作约定

- 先读 `SPEC.md`。变更数据、标签、模型、风险、成本、决策或界面时，同步更新 SPEC 与对应说明，明确已实现和未实现的范围。
- GitHub 优先使用现有 GitHub App，目标仓库为 `Rexmiao/alpha-trading-lab`。只为当前个人目标仓库补充必要访问，不另起包含组织访问的登录或授权流程，也不把授权扩大到全部仓库。
- GitHub 返回 `Resource not accessible by integration` 时，先检查现有 App 的 Selected repositories 是否包含目标仓库；保留其他现有授权，不重新申请组织权限或索取令牌。
- 使用现有连接器上传文本和二进制资源。保留远端 LICENSE 与提交历史，核对文件哈希，用预期旧提交号更新分支，不强制覆盖别人提交。
- 只上传源代码、规格、说明、教学媒体和静态网页。`data/`、`runs/`、`state/`、凭据、账户、聊天截图与本机模型权重留在本地。
- 论文原文入口与实现偏离写入 `docs/papers/README.md`；moomoo 接口和认证边界写入 `docs/MOOMOO_API.md`；GitHub 操作方法写入 `docs/GITHUB_WORKFLOW.md`。
- 更新网页动画时，同步检查中英文 GIF、暂停封面、下载文件、README 路径及 `web/` 导出内容。教学示例不能被描述为真实回测结果。
- 云端模拟使用 `hf_space/streamlit_app.py`，不部署读取本机runs的根app.py。云端不连接moomoo、不携带本机快照、账户、密钥或模型；合成教学与访客CSV必须明确区分。
- Hugging Face与Streamlit Community Cloud共用同一引擎，分别按各自部署文档处理账号和认证。源码仍用现有GitHub App；不将它误当作第三方托管服务的登录，也不请求组织或私库权限。付费套餐或硬件不得自动开通。

- 在线历史仅使用固定Yahoo公开端点与严格USD股票/ETF代码，不提供任意URL或券商认证入口；限流或数据错误明确失败，不转合成。仅当前会话保存快照，参数对比复用原快照，提供CSV与来源JSON下载；分别标记已运行来源和新获取但未使用的快照。

- 部署后用实际结果JSON核对依赖，不假定requirements已全部生效。本次Community Cloud实际PyArrow24.0.0、HF Docker25.0.1，差异写入SPEC；严格复现以同一CSV和固定Docker环境为参照。
