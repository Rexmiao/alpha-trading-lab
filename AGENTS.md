# 项目后续操作约定

- 先读 `SPEC.md`。变更数据、标签、模型、风险、成本、决策或界面时，同步更新 SPEC 与对应说明，明确已实现和未实现的范围。
- GitHub 优先使用现有 GitHub App，目标仓库为 `Rexmiao/alpha-trading-lab`。只为当前个人目标仓库补充必要访问，不另起包含组织访问的登录或授权流程，也不把授权扩大到全部仓库。
- GitHub 返回 `Resource not accessible by integration` 时，先检查现有 App 的 Selected repositories 是否包含目标仓库；保留其他现有授权，不重新申请组织权限或索取令牌。
- 使用现有连接器上传文本和二进制资源。保留远端 LICENSE 与提交历史，核对文件哈希，用预期旧提交号更新分支，不强制覆盖别人提交。
- 只上传源代码、规格、说明、教学媒体和静态网页。`data/`、`runs/`、`state/`、凭据、账户、聊天截图与本机模型权重留在本地。
- 论文原文入口与实现偏离写入 `docs/papers/README.md`；moomoo 接口和认证边界写入 `docs/MOOMOO_API.md`；GitHub 操作方法写入 `docs/GITHUB_WORKFLOW.md`。
- 更新网页动画时，同步检查中英文 GIF、暂停封面、下载文件、README 路径及 `web/` 导出内容。教学示例不能被描述为真实回测结果。
- 云端研究使用 `hf_space/streamlit_app.py`，不部署根app.py或execution_lab。HF可用独立只读Secret从固定Private Dataset读取已净化moomoo快照，原始OHLCV只在服务端会话，不提供原始下载；公开包不携带行情、账户、券商密钥或模型。合成、访客CSV与已发布快照必须分别标记，禁止失败回退成合成。

- 当前本机执行增量先读specs/VEIGHNA_MOOMOO_SYSTEM.md：独立requirements-veighna环境、活动SQLite在本机非同步目录。用户已授权先验收券商模拟；LIVE未实现，不能升级真实账户。HF私有Dataset、本机发布、Space独立只读读取与三规则研究已实测成功；没有常驻同步任务，不索取聊天令牌。
- Windows凭据与签名文件的ACL以实际交互桌面用户为准，不能把普通工具沙箱的当前身份当作用户本人。DPAPI与密钥可用性须在本人进程验证；ACL限制为本人及SYSTEM，私钥不打印，账户发现输出与落盘前丢弃所有实盘行。
- 用户当前要求零实盘连接／授权。新REST或MCP只有在官方独立模拟授权方法明确后才启动登录；公开工具存在、URL白名单或翻译字典中的旧模拟文案不证明paper-only服务端权限。只列实盘的授权下拉不能拿实盘替代；默认宽scope CLI不用于试接。
- Hugging Face与Streamlit Community Cloud共用同一引擎，分别按各自部署文档处理账号和认证。源码仍用现有GitHub App；不将它误当作第三方托管服务的登录，也不请求组织或私库权限。付费套餐或硬件不得自动开通。

- 在线历史仅使用固定Yahoo公开端点与严格USD股票/ETF代码，不提供任意URL或券商认证入口；限流或数据错误明确失败，不转合成。仅当前会话保存快照，参数对比复用原快照，提供CSV与来源JSON下载；分别标记已运行来源和新获取但未使用的快照。

- 部署后用实际结果JSON核对依赖，不假定requirements已全部生效。本次Community Cloud实际PyArrow24.0.0、HF Docker25.0.1，差异写入SPEC；严格复现以同一CSV和固定Docker环境为参照。

- 每日信号／自动交易的后续实现先读specs/DAILY_SIGNAL_SYSTEM.md。用户最终希望全自动实盘，M1范围先为采集、因子、信号及审计；计划与已实现状态分开。活动SQLite放本机非同步目录，REPLAY与CAPTURE发布键隔离，不能把未来实盘目标误当作当前下单授权。

- 提醒、半自动与全自动是同一策略引擎的可选执行策略；automation_mode与execution_environment、workflow_kind分开。模式切换不重写信号、不补执行旧提醒，不自动迁移在途订单或升级为真钱账户；M1仍固定CAPTURE＋ALERT_ONLY＋NONE。
