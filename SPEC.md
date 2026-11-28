# Alpha Lab 可复现规格

版本：0.12.1（已发布：研究界面统一视觉与导航）；此前0.12.0（已发布：盘前涨幅与开盘下探）；更新日期：2026-11-27（America/New_York）。此前公开应用0.11.1及免费MM样本验收记录保留；三ETF盘前统计的实现、程序测试和公网验收见文末。研究主线仍为美股日频DL／GenAI alpha预测，另有独立日频／5分钟规则、Beta、S&R和期权研究。公开HF只负责研究，不提供委托入口；本机VeighNa＋moomoo真实券商模拟认证与成交验收尚未完成，没有实盘路径。真实MM库存估计仍未识别。

## 系统实施路线与当前增量

用户目标是一套系统共用数据、信号、组合、风控和审计，可选择仅提醒、人工确认执行或自动执行；执行方式与影子／券商模拟／实盘环境分开配置，最终支持真实资金自动化。初期先每天自动采集、计算因子并捕捉信号。完整模块、时点、存储、状态、25项M1验收及7项后续统一模式验收写入[每日信号与自动交易系统实施规格](specs/DAILY_SIGNAL_SYSTEM.md)。

- M1：CAPTURE＋ALERT_ONLY＋NONE，只读行情、不可修改快照、有版本因子与事件、固定模型推理、成熟标签、日报和可恢复任务；不生成券商订单、不读取真实账户。
- M2：同一引擎增加三种执行策略、共同提案／确认／分发和持续影子账本，固定五日调仓锚点。
- M3：同一引擎增加券商模拟适配及订单状态／重启对账。
- M4：增加已配置的实盘环境，在同一系统选择提醒、人工确认或自动执行；独立账户与风险要求、模式切换审计及在途订单对账。

开发采用 Python 模块化单体，复用现有只读采集和研究代码；先贯通真实日 K、快照／状态、五项因子及本机日报，再补齐模型与全量验收。框架参考、接口契约、小批次评审和端到端验收方式见实施规格第13.1–13.4节。

框架选型证据见[选型研究](docs/FRAMEWORK_COMPARISON.md)。按用户最新选择，VeighNa＋moomoo作为本机执行路线，独立环境固定vnpy4.5.0，不升级公开研究应用依赖。LEAN／Qlib／Nautilus的比较保留；它们尚未安装或联调。

当前增量以[VeighNa＋moomoo系统规格](specs/VEIGHNA_MOOMOO_SYSTEM.md)为准：已实现本机5分钟采集／信号、SQLite审计、提醒／确认／自动模式、模拟订单适配、持久UNKNOWN恢复及真实MainEngine订单桥。离线贯通采用假券商边界；真实3日行情已完成VeighNa影子回放。原每日M1的全部因子／模型／成熟标签／日报验收仍未完成；没有注册或启动常驻任务，不能据此宣称M1–M4全部完成。

## 数据与时点

原始响应保存在data/raw并记录SHA256、采集时间、代码、接口参数、复权口径。归一化表字段为date、symbol、open、high、low、close、volume。拒绝重复主键、不合法OHLC及非正价格；只接受已完成的美东交易日。实际历史长度以接口返回为准，不伪造或用随机数据填充缺失结果。

当前采集器为scripts/collect-moomoo.mjs，通过已登录的moomoo桌面CLI访问本机Host，默认地址为http://127.0.0.1:22222。CLI路径、Host地址与进程内凭据分别支持ALPHA_MOOMOO_CLI、OPENAPI_HOST_URL、OPENAPI_HOST_APPKEY覆盖；无凭据时明确失败。当前只调用采集所需的subscribe与get-kline，最近1000条日K请求不等于完整历史。行情权限以账户地区和实际订阅为准，不承诺所有市场或品种免费。

docs/MOOMOO_API.md必须区分本项目桌面CLI适配、传统OpenD/SDK与官方REST服务，链接各自官方手册。不同服务的凭据和分页参数不得混用；官网能力与本项目已实现能力分别标注。接入说明使用占位符，不保存任何可用密钥。

研究股票池是用户可修改的原型固定名单；它不是历史时点可投资股票池，不足以证明无生存者偏差。SPY单独作为基准。前复权OHLC的分红处理和可成交价近似要在运行报告标注。

当前研究池扩为45只主题股票，类别和代码写入config.research_groups。上市/业务重启日期由config.symbol_start_dates定义，原始数据不删除；research.coverage在计算任何特征前剔除边界前记录并保存审计。逐股计算历史长度、有效特征与标签样本，不为凑齐1000根而填充。主题标签只是当前研究范围，不作为历史行业事实输入模型。

收盘后产生信号。预测标签从下一交易日开盘起，至第h+1个交易日开盘的收益，减去SPY同一期间收益。默认h=5，即持有5个交易日的开盘到开盘收益。标签涉及的数据必须完全处于训练或验证边界内，禁止训练标签跨入验证或测试。所有股票按共同交易日切分，禁止逐行随机拆分。

## 因子与模型

输入仅包含历史价量变化、波动等在信号日可见的信息。标准化只拟合训练数据。模型包括Ridge基线、两隐藏层MLP、同架构重采样MLP及条件DDPM增强MLP。DDPM仅拟合训练期，生成与条件输入配套的收益标签；这种条件生成是本项目研究设计，不是ADNN或DARL论文的精确复现。

MLP当前是48及24单元的两层ReLU网络，训练目标为标准化超额收益MSE；三组MLP具有相同预测器更新预算。DDPM为余弦噪声日程、v参数化、训练期PCA条件表示和逐步高斯后验采样，生成计算量另行披露。输入标签缩放、生成范围裁剪、训练次数和采样统计保存在训练元信息。保存可重载的模型、预处理和生成器权重。

神经网络预测未来相对收益，横截面排序形成选股分数。保存模型设置、随机种子、训练样本区间及逐日预测。模型训练失败不得以基线结果冒充成功。

## 因子到决策

同一信号日按预测分数排序，只有分数超过min_expected_excess的股票参与前k只选择，仅做多，以预测波动率倒数分配初始权重。默认门槛0.002是与当前双边研究成本相对应的演示值，不是经验证的最优参数。EWMA仅使用截至信号日的收益更新方差。逐只仓位上限、现金下限、组合波动预算和最小交易金额由config.json控制；均为可修改的研究假设。

组合风险使用仅含历史数据的协方差估计并作风险缩放，不以独立资产假设低估相关性。风险缩放只能减少仓位，现金承接剩余权重。首版使用EWMA波动尺度，未实现Lévy或GARCH拟合。

每h个交易日调仓一次，在次日开盘模拟执行目标权重；开盘前按持仓漂移重算权重，按真实换手扣单边成交成本，持仓持有至下一调仓。交易、成本、现金及持仓变化均可追溯。信号持有期与调仓周期一致，避免重复叠加五日收益。

根目录日频研究执行层只生成独立模拟账户的目标权重、数量及BUY/SELL订单草稿。参考价格采用最后完整日K收盘价，明确标为待重新报价；不得宣称可直接按该价成交。新的本机5分钟执行器独立于此研究草稿，必须重新校验报价、账户、模式及时间，不能直接消费公开网页结果。

## 结果与界面

研究应用首次访问固定English，不从浏览器语言推断中文。手动语言选择仅将`en`或`zh`写入当前浏览器的`alpha-lab.uiLanguage`，刷新／重访恢复；无效值忽略，本地存储不可用时回退为首次English且当前会话仍可切换。延迟到达的偏好不得覆盖本会话已做的手动选择。偏好不含行情、研究结果、账户或凭据；恢复和切换只重绘界面，不触发训练、取数或交易。

界面展示数据质量、四组实验预测Rank IC、含成本净值及回撤、目标持仓与订单草稿。数学原理页给出标签、预测、Rank IC、DDPM、EWMA、权重及成本计算，能对应SPEC与代码。无数据时展示原因，不展示伪造收益。

默认先显示研究结果，另有因子到决策、数据、数学原理和论文机制复现Tab。中文与English切换覆盖说明、图表和指标；原始审计JSON保留字段名和来源值。

数学原理的第一个子页是零基础训练全流程，先区分训练、回测和决策，再串起日K、历史特征、未来答案、时间分割、损失和参数更新、生成式增强及仓位规则。教学数值明确标为假设，不把本次收益作为原理有效的证明。

## 公开教学网页与动画

主教学入口为https://rexmiao.github.io/alpha-trading-lab/，原chatgpt.site教学链接保留。2026-11-25已完成实际Pages部署，七个静态文件经HTTP状态与内容哈希核对；五个滑块、中英文媒体切换、播放/暂停和手机布局经浏览器验证。工作流检查通过与实际发布成功须分别记录。

web/是可独立托管的静态教学网页源码和素材。运行python -m http.server 8512 --bind 127.0.0.1 --directory web即可本地预览；不依赖Streamlit运行、moomoo在线、账户或本机研究结果。公开网页中的数值和资产A/B/C均为假设示例，不展示真实回测收益或可发送订单。EWMA演示的混合系数不能标成方差贡献比例；组合风险缩放只能减少风险预算外的仓位。

页面语言切换必须同时更新说明、公式解释、GIF、暂停封面、下载文件和README嵌入路径。English模式使用纯英文动画web/assets/training-flow-en.gif及封面poster-en.png；中文模式使用现有双语training-flow.gif及poster.png。切换语言保留播放/暂停状态，遵循prefers-reduced-motion时默认显示相应语言封面；电脑及手机视口均可操作。

动画由scripts/export_training_gif.py绘制，只使用固定教学形状和假设配置，不读取data、runs、账户、凭据或券商接口。默认命令生成docs/media/alpha-training-flow.gif与poster.png；加--language en生成docs/media/en/中的纯英文版本。当前成品为1200×600、48帧、约11.16秒无限循环，README分别链接两种语言。更新动画后需同步web/assets对应文件，并检查英文关键帧不出现中文或裁剪。

网页源码、动画脚本、依赖版本与生成命令均进入GitHub；托管服务的身份配置和发布凭据不进入项目仓库。公开网址是教学展示入口，不能替代本机研究程序或当作策略有效性证明。

GitHub Pages使用.github/workflows/pages.yml部署main分支的web/目录，发布前运行scripts/validate_public_site.py核对七个静态文件及本机信息隔离；禁止以仓库根目录作为上传产物。工作流只使用contents:read、pages:write和id-token:write，保留现有GitHub App，不索取PAT或组织范围授权。首次启用需仓库Settings→Pages选择GitHub Actions；未启用时工作流给出notice并跳过发布，校验成功不等于网站已上线；当前连接器不提供该管理设置，不能用普通GITHUB_TOKEN自动启用。后续web/、发布校验脚本或工作流变更触发部署，也可手动运行工作流。

## 云端 Python 模拟

新增独立入口hf_space/streamlit_app.py，可用于Hugging Face Docker Space和Streamlit Community Cloud；GitHub Pages主站继续只运行浏览器教学交互。本次已准备共同模拟代码与部署资料。已核实用户个人HF账号Rexymiao为PRO，公开Docker / CPU Basic Space Rexymiao/alpha-trading-lab已创建，发布令牌由用户保存到GitHub Secret；HF已于2026-11-26通过实际公网验收，入口为https://huggingface.co/spaces/Rexymiao/alpha-trading-lab；Streamlit Community Cloud入口为https://alpha-trading-lab-rnb8nqgww7tgbdvgdcysxm.streamlit.app/，手填7日、四模型及双语提示已验证；本次实际下载报告确认Cloud为PyArrow24.0.0、HF为25.0.1；其余所记录的NumPy、pandas、SciPy、scikit-learn、joblib、threadpoolctl、Streamlit与Plotly版本一致，不宣称两个托管运行环境完全相同。两个平台发布状态分别记录。

hf_space/engine.py直接复用research/data.py、models.py、portfolio.py中的特征、时间切分、四模型和含成本回测函数，不调用load_snapshot、run_experiment、moomoo CLI或根目录本机结果查看器。默认选择上传CSV，访客也可使用；合成教学数据需明确选择：BENCH加6只TOY虚构资产、400个工作日、seed42，日历并非交易所节假日日历；全部收益和IC仅说明教学模拟，不代表市场证据。上传失败或数据不足时明确报错，不能自动以合成数据替代。

上传只接受UTF-8 CSV字节与严格七列date,symbol,open,high,low,close,volume；同文件含基准及3至12只股票。上限3MiB、8000行、600个日期、3000训练行；拒绝重复键、非法OHLC、非有限数、缺基准、非完成日及股票不在基准日历中的记录。不补上市前或缺失行情，也不声称已重建交易所假日、历史股票池或公司行动。公开界面只接受CSV，不接受模型权重、可执行内容、路径或URL输入。

为控制共享CPU，云端固定30日特征窗口、30日验证、60日测试和至少90日训练，按label_end剔除跨边界标签。模型为Ridge、MLP、重采样MLP、条件DDPM增强MLP；MLP采用24/12隐藏单元与20轮同预算训练，DDPM采用8个噪声时步及40个训练步。该预算不同于本机完整研究设置，生成器额外计算量单列，验证期只做诊断、不按测试收益选参数。

horizon改为可手动输入1–20的整数，默认5，同时决定收益标签持有期和调仓间隔。中英文界面提示先从5个交易日开始、初期在10个交易日以内研究；该提示是教学起点，不是由测试收益选出的最优参数。较长周期会减少可用标签和测试段内的调仓次数。另可调seed、单边成本、单股上限和年化风险预算。持有/调仓周期与horizon一致，成本门槛为两倍单边成本，保留现金、EWMA相关性风险缩放和次日开盘模拟。参考权重中的现金采用保留标识__CASH__及kind=cash，股票为kind=asset，不与真实CASH股票代码混淆。没有账户连接、报价或订单提交。

训练与回测放在进程内单个非阻塞信号量中；已有访客运行时明确报告繁忙，不全局缓存用户输入或结果。界面点击运行后才计算，结果只保留在当前会话，语言切换不重新训练；修改参数后仍显示上次实际执行设置，直至再次运行。CSV会发送到承载服务的服务器临时处理，不宣传为纯本机或纯浏览器计算。支持下载JSON指标、曲线、预测和参考权重，不导出可加载模型。

JSON记录来源标识、标准化数据哈希、配置、seed、分割边界、训练预算、各模型成功/失败、运行依赖和固定公开源码SHA256。源码哈希仅在模块加载时读取列明的五个公开Python文件，不读取本机config/data/runs/凭据。失败模型没有净值替代结果；必须显示其错误及状态。

Hugging Face使用deploy/huggingface的Docker模板，Python3.12、非root UID1000、端口7860、数值线程1及3MiB上传限制。scripts/package_hf_space.py按白名单生成父目录outputs/hf-space-bundle及ZIP，只包含共同UI、引擎、三个计算模块、依赖、模板和许可证，保存文件哈希。账号PRO门槛、临时磁盘和实际发布状态写入docs/HUGGINGFACE_DEPLOYMENT.md；不代购套餐，不自动选择计费硬件。Streamlit Community Cloud使用同一入口，步骤见docs/STREAMLIT_CLOUD_DEPLOYMENT.md，并就近读取hf_space/requirements.txt；此文件与Docker依赖清单保持一致，根目录原有研究环境不升级。

HF源码同步使用.github/workflows/huggingface.yml与scripts/upload_hf_space.py。用户在GitHub仓库Secret中安全设置HF_TOKEN，目标默认Rexymiao/alpha-trading-lab，也可用Variable HF_SPACE_ID指定自己已创建的公开个人Docker Space；凭据不发送到聊天。缺少发布令牌或有效目标时工作流明确跳过，不冒称部署成功。上传前校验18个包文件及哈希、个人所有权、Docker SDK和CPU Basic硬件，拒绝其他项目文件；用已读取的远端提交号作并发保护。流程不创建Space、不改硬件、不设置计费、不授权组织；代码上传与新版本应用运行分别验证。

云端两份依赖清单显式固定pyarrow==25.0.1，与numpy==1.26.4和pandas==2.2.2配套。首次公网运行发现未约束的PyArrow26要求NumPy2，故在Docker构建阶段增加实际NumPy→pandas→Arrow表转换，失败即中止镜像构建；不以容器RUNNING替代表格渲染验收。JSON同时记录PyArrow、Streamlit与Plotly版本。

当前已验证的应用源码为GitHub commit b54637fb25eef7746a0ce2c93a97e18c672fcb62，Space commit及runtime.sha均为24cdfa5c21ec02cf0ed4e7971c9716691c1d59f0，当前/请求硬件为cpu-basic。两个公网入口均实测默认访客CSV、真实Yahoo取数7股加SPY、400个交易日、四模型成功、三类下载及中英切换保留结果。输入框1–20/default5和真实手填7日的持有/调仓一致性已核对，CSV拒绝错误不使用合成回退。57项数据/引擎测试及三来源AppTest通过。

新增online_history来源，显式选择并点击运行后才访问Yahoo公开日线端点。hf_space/history.py仅请求固定HTTPS域名和严格股票代码，支持3–8只USD股票/ETF加基准、400个基准日期；要求America/New_York时区，保守排除美东当天。请求有时间及大小上限，HTTP限流、无数据、非法价格与不支持币种明确失败，不使用合成回退。

在线OHLC按Yahoo adjclose/close比率同步调整，成交量保留来源值；此复权价格仍是成交价近似，不等同moomoo固定快照，也不证明历史时点可投资池已重建。基准定义日历，上市前和缺失行情不补填；逐股覆盖、原始响应SHA256、请求参数、获取UTC、范围、公司行动计数和CSV快照SHA写入来源记录。CSV解析采用round_trip浮点精度，便于下载后读回相同数据。

在线快照仅在当前会话缓存，股票/基准变化或主动刷新会重新获取；模型参数对比默认复用同一快照。提供当前快照CSV和来源JSON下载，已显示结果仍按该次运行保存的source及external_data标记；切换来源或取得新快照不会伪装成旧结果所用数据。公开包只增加获取器源码，不内置本机行情、账户或券商凭据，包扩为14文件。

本机真实moomoo快照已整理为8股加SPY、2025-04-24至2026-11-24、400个交易日，共3600行；CSV SHA256为8748612159d562adc85661068f149d9f8ce9ea82bdcaa75b56276860a45acc17，留在data/cloud-inputs。已在HF临时会话h5/10bps实际运行四模型并下载报告，真实数据、报告及来源审计不推入公开源码。步骤见docs/HISTORICAL_DATA.md；该窗口内四组均未跑赢SPY，不能描述为已证明有效alpha。

两站的独立在线请求时间与CSV快照哈希分别记录在部署说明中；不同快照不等于同一实验。精确复现应保存相同CSV与JSON配置，并以HF Docker固定环境为参照，结果中始终记录实际依赖版本，不以requirements声明替代运行值。

新云端行为须通过CSV边界、无工作目录写入、时间purge、模型失败与并发测试；还需在云端依赖环境实际运行四模型界面，验证语言切换和参数改动不会错误重训或冒称已经应用。Docker构建与真实平台上线是额外状态，只有各自构建和公网检查成功后才更新相应入口。

## 论文核心机制实验

独立的rank实验只复建ADNN同日股票成组训练与可微平滑IC目标，和同架构MSE目标比较。使用g(z)=sigmoid(1.83*(z-mean)/(2*std))并对g(pred)、g(target)取标准Pearson相关；原论文式6排版含糊，所采用解释在结果中公开。当前小网络、41个历史特征、美股与可执行开盘标签均属于偏离原论文的设定，未复建GP、预训练、剪枝或完整因子池。

docs/papers/README.md提供朋友分享的三篇论文入口、书目信息、阅读顺序和与本项目的映射。两篇综述提供研究框架，不能当作固定算法直接复现；DARL的原方法与本项目条件收益增强设计分开说明。ADNN是补充的原始方法来源，不冒称朋友最初分享的第三篇。PAPER_REPLICATION.md与本节共同列明已实现机制和未覆盖范围；论文原文通过官方链接访问，不将无法确认再分发许可的全文纳入公开仓库。

两组使用相同初始化、同日期分组抽样及更新预算。raw_score没有收益单位，只计算原始排序预测力；独立验证期拟合非负斜率线性收益校准后，再接组合成本门槛。验证数据不训练原始网络，测试数据不训练或校准。校准斜率为零时明确报告；不能为了让策略交易而按测试结果翻转信号。输出与主实验分开，不覆盖latest.json。

## 复现与GitHub

保存运行ID、配置哈希、数据哈希、代码哈希、依赖版本、随机种子、时区、样本边界、模型元信息及完整结果。相同代码、数据快照和配置应能重跑。网络重新采集可能修订历史，因此复现实验使用冻结快照。

项目仓库为https://github.com/Rexmiao/alpha-trading-lab，沿用用户初始化的MIT License和提交历史。上传通过明确的源文件清单，记录文件内容哈希并核对远端提交；README中的原理、论文、接口及网页入口必须能解析到实际文件。规格变更时同步更新本SPEC及相应说明，不以README单独新增功能描述替代规格更新。

GitHub优先复用现有GitHub App，仅为本次目标个人仓库补充必要的Selected repositories授权，不另起包含组织访问的登录流程，不扩大为全部仓库授权，也不移除其他现有授权。遇到403 Resource not accessible by integration时先检查该目标仓库是否已加入现有App。操作步骤写入docs/GITHUB_WORKFLOW.md，并由AGENTS.md记录为后续项目约定；凭据不落盘、不输出，不索取个人访问令牌。分支更新必须校验预期旧提交，禁止强制覆盖远端并发变更。

GitHub包含代码、SPEC、README、依赖清单、论文原文入口与阅读说明、moomoo接口接入手册、教学动画、静态网页源码和不含用户信息的测试数据。论文与接口手册入口分别为docs/papers/README.md和docs/MOOMOO_API.md，官方原文与本项目实现范围分别标注。data、runs、state、凭据、账户及聊天截图均不进入仓库。密钥通过本机受保护存储或进程环境变量在内存中使用，禁止输出或复制到项目。

## 验收

必须检验标签与成交时点、跨边界标签剔除、历史特征截断不变性、权重和现金约束、风险缩放、已持仓到目标数量的转换、成本扣除、无真实订单路径。真实数据不可获得时，采集失败可重试，离线测试必须明确为测试数据。

发布资料和网页时还需检查：论文及官方API来源可追溯；所有仓库内相对链接与静态素材存在；中英文切换同步切换动画、封面、下载与README示例；暂停/播放与手机布局正常；公开文件不引用本机研究目录或交易接口；待上传文件不含data、runs、state、凭据和聊天截图。远端文件的Git blob哈希需与最终上传清单一致，并保留已有LICENSE。


## 动量与趋势研究页（0.6.0）

新增 hf_space/strategies.py 和 strategy_ui.py，由云端应用侧栏“研究页面”在AI模型与动量／趋势间切换；静态GitHub Pages新增双语策略原理、教学价格交互和真实应用入口。原四模型入口保留，规则页不训练模型，不连接账户或提交订单。

四类规则分别为：cross_sectional_momentum按L日历史收益选前4只（允许负收益）；time_series_momentum要求L日收益>0；moving_average_trend要求close>SMA_slow且SMA_fast>SMA_slow；channel_breakout以收盘突破此前E日high进入候选状态、跌破此前X日low退出，两个通道窗口都排除当日，期间保持状态。后三类所有合格股票参与风险分配，不附加Top4排名。默认L=60、快慢50/200、E/X=55/20；原始值分别为历史收益、close/慢均线−1、close/此前入场高点−1，均非未来收益预测。完整说明和分钟原始研究见[策略文档](docs/MOMENTUM_TREND.md)。

规则采用明确eligibility分配路径，不向现有收益成本门槛塞入排名或伪造预测。四组共用逆波动、年化252的零均值归一化EWMA协方差、单股上限、20%调仓目标现金下限和只减仓的组合风险缩放（非调仓日持仓／现金比例随价格漂移）；实际整数股交易每边扣一次成本，最小交易金额0，逐笔记录、现金及在途／成交时点仅为离线模拟。research.portfolio.backtest新增可选allocation_fn，原模型默认路径保持原行为。规则参数、数据及代码哈希、实际依赖版本与账本审计进入JSON。

所有策略使用相同的最长连续预热要求（默认200根）和末尾共同评估窗口（默认60个基准日期），窗口不足明确失败，不换短窗口、不填补新上市／停牌历史。首个评估日收盘现金起步，按固定锚点每5个交易日产生调仓，下一已观察基准交易日实际open模拟执行；最终close只估值，不虚构下一open或最后平仓。通道状态逐日更新、仅锚点换仓。缺少已持仓开盘／收盘价时该策略明确失败。最新权重为最后收盘后的参考，不表示已执行。

云端三种数据来源沿用原CSV／在线日K／合成教学边界。源、参数、结果和下载保持当前会话；语言和未提交参数变化不运行策略。两研究页可复用会话内在线快照，但AI训练留出与规则末尾评估并不自动对齐，界面说明需统一数据、日期、仓位和成本后再比较。规则本身不宣称已发现alpha。分钟论文与数据候选只提供原文入口；当前没有分钟接入、分钟曲线或自动交易实现，也不改变M1尚未实现的状态。

本轮完成代码和本地验收后再更新各公网平台状态；不能以GitHub上传或HF容器构建成功替代页面、四策略结果、双语与下载验收。HF明确包清单增加两个规则模块，共16个文件（含MANIFEST），不包含研究快照、结果、模型或密钥。


0.6.1修正：研究页面、规则说明和数据来源选项保存在独立于widget身份的会话状态中，通过显式回调更新，避免中英往返时恢复旧默认页面；结果不重算。公网验收已发现Cloud加载旧portfolio模块导致allocation_fn调用失败，先保留失败JSON证据；hf_space/requirements.txt加入运行代际标记以触发Cloud依赖文件重新部署，不改变依赖版本或在活跃进程中热重载共享模块。HF为主要入口，Cloud为备用，两个平台单独核验，不让Cloud的状态代表HF功能。Cloud成功恢复前不得标成四策略已验证可用。

## 0.7.0：独立5分钟研究

本节保留0.7.0历史交付状态；当前真实行情、框架及私有读取的变化以文末0.8.0为准。

新增`hf_space/intraday.py`、`intraday_ui.py`，主入口保留AI／日频两个模式，并增加独立5分钟页面。CSV字段固定`timestamp,symbol,open,high,low,close,volume`；timestamp为带时区的bar-start并归一到UTC，上限8MiB、50000行、12股票加基准。日频解析仍按原3MiB等限制执行，不将分钟时间截成日期。仅用户显式运行才计算，不用上传文件名或URL读其他路径。

首版为本日正动量、均线趋势、冻结开盘区间收盘确认突破；同日预热、共同最长预热起点、共同完整RTH交易日。固定XNYS日历处理DST与半日市；缺少任一证券／基准bar的日期列入覆盖报告并整日排除，不填补价格。还须在共同预热、调仓锚点和额外延迟后有可执行窗口，无窗口日单独排除；至少两个完整且可执行的共同日才运行，分别报告完整日与有效日数量。时间与公式、逐日聚合及数学推导见[策略说明](docs/MOMENTUM_TREND.md)。这三条是工程基线，不是分钟原文或DL／GenAI论文完整复现。

多头／现金，合格股等权并封顶，默认单股20%、目标现金至少20%，整数股先卖后买且不透支现金。日内本次不采用日频EWMA协方差或分钟直接252年化。上一bar完成后的下一bar开盘仅为零延迟OHLC成交代理，提供额外延迟一根K线对照；日历最后一bar开盘预先清仓并禁止再入，无隔夜。费用、半点差、滑点分别按每实际买卖方向扣除。基准每日首bar开盘全额买入、最后bar开盘退出，整数股及相同费用，但风险暴露与策略不同。每日末权益收益再按252描述，少于20日不展示夏普或年化波动；不以分钟根数当独立样本数或计算规则Rank IC。权重分别展示最后一次实际调仓的目标参考及期末真实模拟全现金状态，附各自时点，不冒称当前账户仓位。

本机`collect-moomoo-intraday.mjs`独立于旧日K脚本，使用已安装桌面CLI的`request-history-kl`、kl_type=6、RTH及next_req_key分页；无账户或交易方法，默认不复权、仅以前的美东日期。帮助版本16.40.27608.11182326已核；真实首SPY页请求超时，0页／0根，NVDA未发出。本地TCP可达，超时原因未定，不能报告已取得真实分钟数据或所有账户均免费。时间标签未确认时仅保留原始响应和来源清单；不会静默平移成bar-start。所有行情、凭据与结果仍留本机，不进入发布包。

公开5分钟入口支持访客CSV和明确的合成教学数据，参数与结果仅会话保存，中英及页面往返不重算既有JSON。包清单从16增为18个文件（17源码及MANIFEST），不带collector或真实数据。新增固定依赖`exchange-calendars==4.11.2`、`pyluach==2.3.0`、`toolz==1.0.0`、`korean-lunar-calendar==0.3.1`，并显式固定`python-dateutil==2.9.0.post0`、`pytz==2025.2`、`six==1.17.0`。使用独立环境安装验证，未升级原研究环境。

执行框架补充见[选型研究第9节](docs/FRAMEWORK_COMPARISON.md)及[系统SPEC第13.7节](specs/DAILY_SIGNAL_SYSTEM.md)。保留moomoo时优先技术验证VeighNa组合执行适配，采用已支持美股券商时优先比较LEAN；本轮没有引入交易框架依赖或实现M1–M4运行系统。公开HF继续是研究入口。

### 0.7.0 实际验收与发布

原95项Python回归、新48项分钟引擎测试、4项分钟AppTest和17项Node采集器离线测试通过。独立复核发现的“半日市长窗口仍报success”问题已修正并复验。手机长数学式已拆成15条短式，实际宽度102–264px，小于390px手机页面的358px内容区；页面无横向溢出，截图已人工核对。

应用源码commit为`369d3208e82b63af86d05df35309aa802e7250df`，同步工作流`45813206990`成功；HF仓库与实际runtime均为`6a73f09770868ef0ac645452a9b4dc832a6b6866`、RUNNING、CPU Basic。17源码逐字节／SHA一致；MANIFEST仅创建时间不同，其余语义一致。公网默认CSV入口已核；主动选择合成数据后只运行一次三策略，三者均success、5个有效日、4条权益曲线（含基准）、3条回撤，逐日记录、信号、目标与成交可见。中英中三份JSON逐字节相同，SHA256为`50b56f5bfebbcc6cd5c7a53d8a708a51c9e5e7a6b25920ce8629378118daf095`；JS异常0。该演示不是市场业绩。

实际HF报告Python3.12.16，本机QA为3.12.7；已核NumPy1.26.4、pandas2.2.2、日历4.11.2、Streamlit1.67.0、Plotly5.24.1、PyArrow25.0.1。保留真实运行依赖，不宣称两个Python环境完全相同。版本、输入hash、参数与执行代理约定均写入JSON，严格复现应使用同一快照及所记录环境。证据仅留本机`state/intraday-qa/`；公开发布包没有测试行情或结果。Cloud备用入口本轮未重新验收，不阻塞HF交付。

## 0.8.0：本机执行试点与私有行情快照

本节记录0.8.0阶段；最新私有上传与配置进度见文末0.8.1。

执行范围与命令以[VeighNa＋moomoo规格](specs/VEIGHNA_MOOMOO_SYSTEM.md)为准。独立环境固定vnpy4.5.0、SDK及签名依赖；本机SQLite默认ALERT_ONLY＋NONE，明确支持提醒／确认／自动策略、不同账号命名空间、持久提交意图、UNKNOWN查询恢复及已拥有仓位对账。真实MainEngine／BaseGateway路由同一模拟适配器，SQLite提交后投射订单及累计数量派生成交，OMS失败阻止后续新意图；不伪造完整AccountData／PositionData或第二现金账本。LIVE不开放，没有常驻任务或开机启动被注册。

真实moomoo SPY／NVDA在2026-11-23至25日共468行，CSV SHA256为`5b126b01d9bf29d4d1bb7e63735f0994b15193b3ac1792fb0b29bb130794ff14`，as_of为2026-11-25T21:00:00Z。原始时间是bar-end；78组5分钟OHLC与1分钟右端聚合相符后明确减5分钟转换为UTC bar-start。高精度volume相符，供方整数volume差异保留本机审计；不修订价格、不填缺失。真实3日影子回放213信号／71本地委托与成交，对账一致；不属于券商成交，也不是策略盈利证据。

`scripts/sync_moomoo_snapshot.py`仅在显式--publish时向固定Private Dataset发布内容寻址CSV、净化manifest、latest三文件，校验私有范围、hash、时点和预期parent；独立写令牌不得复用HF_TOKEN。`scripts/run_snapshot_sync.py`提供已完成日期的窗口采集／准备／发布幂等前台入口，显式--watch才循环；首次私有上传／读取验收前不启动自动发布。本机DPAPI与HF只读Secret配置见[操作说明](docs/MOOMOO_CLOUD_SYNC.md)，目前由用户另行协助，真实云端链路尚未验收。

HF新增`moomoo_snapshot`来源，固定Dataset与revision，核对相对路径、字节数、SHA和时间口径；凭据仅服务端专用读权限，raw OHLCV只留服务端会话，不提供原始CSV下载。研究JSON含策略记录及来源指纹，可供访客下载；不含整张原始行情表。同会话参数比较复用同一revision，刷新不重算既有结果；缺配置、鉴权或坏快照明确失败，不转教学数据。原访客CSV与合成入口保留，空CSV时Run禁用并提示上传。公开包扩为19文件（18源码＋MANIFEST），不部署execution_lab、采集器、账户、真实行情或令牌。

最终执行栈218项离线测试、分钟／快照／UI／发布器124项Python测试与26项Node测试通过。真实时钟休市运行未加载认证或调用券商，REPLAY前后活动DB字节与政策不变。独立本地浏览器验证三策略教学运行、中英中同JSON、15条数学式及390px布局，无raw下载、无失败教学回退。真实开市报价与采集、受限paper授权、REST DAY默认及券商订单／成交尚待逐项实测；不能用这些离线结果标记模拟闭环或完整每日M1完成。公网版本另在[部署记录](docs/HUGGINGFACE_DEPLOYMENT.md)核对。

0.8.0公网验收已完成：应用源码`a91cdc9043fc5909fbfd83c4451876b2879a3317`，工作流45825078929成功；HF仓库／runtime为`72a793dd3c1cc77468818335b5dd5d916e6ad10a`，RUNNING、CPU Basic。18源码一致，MANIFEST仅创建时点差异。公网三策略教学成功、双语JSON不重算、390px及15数学式通过；快照来源实际仍为NOT_CONFIGURED，未做真实私有读取。SHADOW目前仅独立历史回放，本机paper没有预定EOD强平，0／1股执行与HF研究的权重／退出政策不可混称。具体限制与下一步券商验收见执行SPEC。

## 0.8.1：真实私有发布与验收展示

2026-11-26已用本机专用DPAPI凭据核对固定Dataset确为Private，并首次发布三文件快照；Dataset revision为`81acd7bef19dcfc890b71bc9a70ca7d5a7208c20`。服务端存储下载重新核对468行、SHA256 `5b126b01d9bf29d4d1bb7e63735f0994b15193b3ac1792fb0b29bb130794ff14`及as_of `2026-11-25T21:00:00Z`一致；重复检查读取现有revision，不重复POST。用户随后完成Space的独立读取配置，新访客已从该私有revision读取并实际运行三规则研究；本机上传与Space独立凭据分别验收通过。没有启动watch或计划任务。

真实运行发现父PowerShell7的PSModulePath使Windows PowerShell5无法自动加载Security模块，有效DPAPI凭据被误报不可用。发布器现使用绝对Windows PowerShell路径、仅系统Modules的子进程环境，并移除父缓存路径；不更改父环境、不输出凭据、不回退HF_TOKEN。新增3项相关回归，publisher16项全通过，真实凭据读取及同快照再验证通过。

此前342项Python及26项Node已在2026-11-26T19:38:08Z–19:38:49Z重新执行，零失败、零跳过；基线期间67个源码／依赖文件hash不变。其后只针对发布器修复新增3例，不把重复运行的旧13例再次计数。公开的逐文件覆盖、五场景9条测试与复跑命令见[验收展示说明](docs/ACCEPTANCE_DEMO.md)，完整日志／JUnit与来源指纹留本机。

本机paper实际就绪检查仍为ALERT_ONLY／NONE，模拟订单数0。文档指定的REST私有config不存在，未读取任何未知凭据、未查询账户或提交订单；桌面登录与Host监听不替代REST认证。管理者入口、精确账户与只读对账顺序见[模拟账户接入](docs/PAPER_ACCOUNT_SETUP.md)。真实下单／成交、开市实时权限及隔夜退出政策仍待验收。

真实HF研究验收：source=moomoo_snapshot，468行／28908字节、3共同完整且可执行日、无缺bar填补；三策略均success，9条逐日指标齐备，研究期末模拟仓位为0。动量、均线趋势、开盘突破的含成本总收益分别约−1.2467%、−1.0642%、−0.3407%；仅3日样本，不展示夏普，也不能作为策略有效性的证据。研究JSON原生下载，中英切换字节相同，SHA256为`7fb87ddb0fc521b29a25961458b893c0a544e9adb0aa6c3a7ba3311bd825002d`；无原始CSV下载。应用源码`37e0304920eb1cd194250bab06d164c732888a40`，HF仓库／runtime为`33d83478f01e4cc5739fa7a3158b38304f27aab7`，RUNNING／CPU Basic；真实读取与本机交易执行验收分开。

2026-11-26授权页现场核对补充：AppKey的账户下拉只列实盘现金／保证金账户，没有模拟账户；不保存任何号或尾号。用户范围仍为仅模拟，不选择实盘账户代替，REST保持未配置。新模拟账户通过独立sim-trade/accounts取得，不能混用实盘或旧SDK编号；仅凭trade:read／trade:write名称无法证实凭据为paper-only。原生本机或真正OpenD的SIMULATE＋US路径作为备用验证，旧美股paper逐步退出必须实测，不承诺可用。具体进度及正确名称alpha_trading_lab_paper见[接入说明](docs/PAPER_ACCOUNT_SETUP.md)。

用户随后已在客户端完成美股融资融券模拟账户初始化，截图可见模拟标记与虚拟资金。2026-11-26又进行3次有界桌面账户元信息请求：初次数字枚举筛选缺少真实形态核对；后续按实际snake_case与字符串枚举复核，以及显式开启综合证券账户的参数对照，均为ret_type=0／err_code=0、只返回1条REAL／US元信息，无可见SIMULATE记录。只保存安全聚合，不保存任何实盘行或账号；没有资金、持仓、订单查询或委托写入。结论为桌面接口通信成功，但还未识别可绑定的模拟账户，不能否认App中账户已存在，也不能用实盘记录替代。

活动DB只读复核仍为ALERT_ONLY／NONE，broker_states／intents／executions均0，主DB字节不变。当前只见OpenAPIHost在运行，未发现独立OpenD运行证据；官方moomoo-api10.12.7208源码静态审计与已有futu SDK关键握手及schema一致，不能将此前超时直接归因于SDK品牌，也没有安装／执行新SDK或重试握手。下一步需独立OpenD网关或官方新模拟认证路线的进一步验证，不能仅凭开启客户端模拟页面或更换包名承诺接通。签名DACL已按交互桌面用户与SYSTEM校正；初始化、认证、只读模拟账户核验及券商成交继续分别验收。

## 0.8.2（本机草案）：独立模拟授权核验

用户再次明确只连接美股模拟账户，不连接或授权实盘账户。2026-11-26匿名读取官方OpenAPI schema、MCP协议元数据、工具目录与公开前端资源：模拟账户列表要求`trade:read`；普通AppKey／OAuth前端在已有账户且选择任一交易权限时拒绝空选账户，行情权限可空选。该结论来自静态前端条件，不等于服务端授权实测；用户界面目前只列实盘账户，因此还没有满足独立模拟授权门槛。未创建AppKey、注册OAuth客户端、启动登录、交换令牌或请求交易业务接口。

MCP目录中的8个`sim_trade_*`工具映射服务器模拟业务，不能据此推断只给行情权限就能调用。匿名MCP初始化返回401，公开权限元数据没有独立模拟scope；“不授权交易时自动走模拟”的旧文字只见翻译字典，没有找到当前渲染引用，不作为有效授权步骤。官方[2026-10-27更新](https://open.moomoo.com/changelog)已将模拟交易纳入交易读写权限。当前阻点仍是官方如何在零实盘账户授权下提供模拟访问，不能通过本地URL白名单代替服务端权限限制。

现有真实行情、HF研究及本机执行状态不因本轮核验而改变。授权结论与可发给官方客服的问题见[接入说明](docs/PAPER_ACCOUNT_SETUP.md)；可复核的公开资源哈希和匿名协议响应只保存在本机`state/moomoo-auth-ui-audit/`及`state/veighna-qa/oauth-readonly-public-audit/`，不混入应用发布包。后续必须先取得官方支持的独立模拟授权方法，再核验实际scope、发现唯一US paper账户并只读检查资金／持仓；这些完成前不启用执行。

另有独立只读OAuth实验核心`execution_lab/paper_oauth_read.py`，未接CLI／数据库／HF，未启动授权。其最小scope请求能否被官方接受尚未实测，不能将离线PKCE、scope拒绝和sim-only路由测试描述为认证或paper-only服务端绑定成功；具体契约与issuer限制见[执行规格](specs/VEIGHNA_MOOMOO_SYSTEM.md#024-独立模拟授权核验)。

用户后续表达“实在不行就用真实账户”，作为独立模拟授权确实不可行时的条件性后备方向；优先级仍是零实盘授权接US paper。现阶段仅整理官方客服问题，核对真实账户关联与身份／行情资格、只读查询、交易写权限的区别，没有启动后备授权或改变运行状态。账户、权限和交易上限尚未确定，LIVE适配也未实现；不能将模拟配置换成实盘ID后执行。英文问题保存在[模拟账户接入说明](docs/PAPER_ACCOUNT_SETUP.md#英文版本)。

## SNR支撑／阻力：研究依据与实施范围

2026-11-26用户明确SNR是Support & Resistance，关注反弹、突破与回踩。已核对原始研究与官方／作者开源实现，比较前日HLC／高低点、历史滚动通道、延迟确认swing、价位聚类与成交量分布；来源及局限见[支撑／阻力研究](docs/MOMENTUM_TREND.md#snr支撑阻力的量化研究)。0.10.0按用户新授权实现前日高低区域的三种独立研究；不将其描述为上述所有方法或原论文的精确复现。

本轮使用紧邻前一完整XNYS RTH日高低，固定区域及available_at，分别比较反弹、收盘突破、严格后续bar回踩；窗口、失效、超时和延迟目标替代见[实施规格](specs/SUPPORT_RESISTANCE.md)。已确认swing聚类、Volume Profile及S&R输入DL／GenAI仍未实现。5分钟OHLC无法确定同根先后，本轮退出采用收盘确认与下一开盘代理，不含通用盘中止损／止盈／OCO。真实5分钟快照扩为10日SPY／NVDA，默认首日预热、9日评价；该短样本用于工程验证，不能证明S&R长期效果。没有把研究信号接入券商执行。

## 0.9.0：Beta测量与五组历史对照

按用户授权实现独立`hf_space/beta.py`及双语`beta_ui.py`。从HF侧栏「Beta测量与策略对照」进入；默认读取固定Private Dataset的已发布moomoo日K，另有访客七列CSV入口，没有合成回退。页面提供净值、回撤、事前组合Beta、个股Beta／总波动散点图、持仓／目标、数学原理与审计JSON；不下载整张原始OHLCV。[原始研究](docs/BETA_STRATEGIES_RESEARCH.md)与[实施契约](specs/BETA_RESEARCH_PLAN.md)明确项目变体与论文方法差异。

日收益OLS含截距，以中心化协方差／SPY方差估计Beta，并报告相关系数、R²、经典OLS标准误、样本数、总／残差波动。默认126日收益窗，可显式选择252日；每次只运行所选一个窗，不按测试收益选窗。要求完整XNYS基准日历、每只股票连续完整窗口、方差非退化；不填上市前或缺失记录。测量截至信号收盘，实际供应商交付延迟未模拟。原始价格收益、无风险利率未提供，截距不是Jensen alpha；标准误不是HAC稳健推断。

共同默认评估末252个交易日；初始在评估前一完整收盘选股、首个评估日开盘建仓，其后实际XNYS月末收盘形成目标、下一交易日开盘执行。每次形成目标至少20只合格股票；按Beta排序取前／后20%（向下取整，与代码及专题SPEC一致），组内等权；全池等权使用同一时点合格股票。三股票篮子均为80%股票／至少20%现金、单股目标上限20%；另有80% SPY／现金和100% SPY两基准，SPY豁免个股上限。资本100000、默认单边10bps，可调0–50bps；整数股、先卖后买、实际每笔买卖扣费，现金收益0。仓位限制约束调仓目标，之后持仓自然漂移；期末仅收盘估值，不虚构卖出。缺持有证券开盘／收盘时该组明确失败；已卖到零的旧证券不作为持仓要求价格。

事前组合Beta用当日实际收盘权重乘截至该日的滚动个股Beta，作为后续暴露估计；实现Beta回归共同评估期的净账户收盘至收盘收益与SPY收益，排除首个开盘至收盘片段。收益含首日成交成本，夏普以零现金收益率计算，年化按252日。高／低是本主题池内排名，低组仍可能Beta>1；没有Beta-cap、市场中性、BAB、杠杆、借券、动态择时或盈利证明。现有DL／GenAI标签与执行器未接入或改变。

真实输入为只读桌面日K采集、46个成功响应且0错误；规范化后43907行、45只主题股票加SPY，1000个基准交易日、2022-12-01至2026-11-25。SNDK／CRWV／NBIS身份起点按有版本配置应用，缺历史不补填；27个绝对日收益>30%的观测保留并告警，不自动清洗。前复权`rehab_type=1`、`provider_daily`，未独立证明RTH日线／分红再投资总收益；当前主题池有选择／生存者偏差，不能推广为全市场或官方指数复现。

`scripts/prepare_moomoo_daily_snapshot.py`读取并核对本机原始文件哈希，输出不可覆盖的日K包；`sync_moomoo_daily_snapshot.py`只向现有私有Dataset写`daily/latest.json`及内容寻址CSV／净化manifest三文件。CSV SHA256为`ceeb074914341a862c5c640f8d0ef8a3a9678a5ca98d1b17211f2e510a21f9bf`，3186590字节；实际上传与重读核对成功，Dataset revision为`3b4a403d9696cb2e690b3e2f9b39c8e7cd2c437b`。原5分钟`latest.json`字节未变。HF以现有专用只读Secret按固定revision读取，路径／长度／hash／交易日／已完成时点与身份边界全部校验；同会话复用快照，刷新不重算旧结果。原始数据仍为私有；应用包为22文件（21源码＋MANIFEST），不携带价格、账户、数据库、券商凭据或本机发布器。没有启动常驻采集／上传任务。

本地及公网的最终回测、测试与发布验收记录见[HF部署说明](docs/HUGGINGFACE_DEPLOYMENT.md#090-beta日频测量与五组对照)。部署和真实数据运行分别验收，不能以离线测试或容器RUNNING代替实际页面结果。

0.9.0最终验收：345项研究相关测试通过（96项新增），固定私有日K已由新HF访客独立读取并运行五组；21源码与本地哈希一致，HF runtime `edf0847ef2951d2d26c19b8bdcf52d713d958921`。中英下载JSON字节相同、四图及390px六条公式通过；本地与HF数值满足1e-12容差，未声称跨OS位级完全相同。源码由现有GitHub App发布，工作流45937075386成功；原始价格不在公开包／源ZIP或下载中。详细结果及证据见上述部署说明。

## 0.10.0：5分钟S&R与主内容导航

新增独立三组S&R及同日日内基准，严格前日高低、冻结区域、后续确认、延迟目标替代、收盘确认退出与日终清仓，完整契约见[专题SPEC](specs/SUPPORT_RESISTANCE.md)。语言及研究入口位于主内容顶部，数据和运行在可折叠侧栏，高级参数收起；原四研究页保留。新增24文件HF包（23源码＋MANIFEST），不包含采集器、券商执行器或原始数据。

真实10日SPY／NVDA 1560行已发布到私有revision `1166944d51191723e2b4f3ce428cb3f818cb1bd1`，日K指针未变。默认9日回测三策略及SPY基准均success，反弹6笔−0.6615%、突破4笔+0.2785%、回踩0笔0%，未触发不伪造结果；1根额外延迟独立对照也完成。仅NVDA可交易且上限20%，与100%SPY日内基准不匹配暴露，短样本不报告夏普／年化。实际参数、费用、数据指纹、验证边界及后续公网证据见[部署说明](docs/HUGGINGFACE_DEPLOYMENT.md#0100-支撑阻力三规则与主内容导航)。

导出JSON仅提供派生状态／事件／成交／价位／曲线，逐bar信号移除signal_close，完整OHLCV及图上选定收盘路径不提供数据下载。稀疏事件确认和成交参考价保留审计。没有接入Beta覆盖、期权指标、DL／GenAI训练或券商委托；未启动常驻采集／同步。

0.10.0实际公网验收：应用源码`815ccdf0b6f9214118201b76076a8a165de9c95c`，[工作流45948835366](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/45948835366)成功；HF仓库／runtime均为`323bf775ed0480a29cd48816ba58a2b909260422`，RUNNING、CPU Basic，23源码逐字节相同，MANIFEST仅created_at不同。新访客独立读取相同私有10日快照，三策略及基准均成功；中英原生JSON下载字节相同，SHA256 `ed99dab6c8f126b528eedb509c35cbaa23997f57e3d48ab24b24c847119ce026`。无原始CSV下载、逐bar信号无signal_close；三图、390px主内容导航和8条短数学式实测通过，JS异常0。408项相关测试通过，其中S&R54、UI7、全局导航2项为新增；旧注入非法字段用例有一个pandas FutureWarning。本机与HF指标满足1e-12容差，HF Python3.12.16、本机3.12.7，不称跨OS完全相同。证据保存在本机state/sr-qa；Cloud备用本轮未重新验收。

## 0.11.0：期权库存、GEX与Max Pain研究

用户提供PCR研究框架已阅读并区分为背景与候选假设；实际源审计见[数据表](docs/OPTIONS_DATA_AUDIT.md)，多模型与原始文献见[GEX替代模型研究](docs/GEX_MODELS_RESEARCH.md)，完整目标／模型／时间／验证／淘汰契约见[期权研究SPEC](specs/OPTIONS_RESEARCH.md)。新增第六个「期权结构研究」页；不修改S&R入场、Beta、原DL／GenAI训练或券商模式。

当前真实最小实验是准入审计：SPY／QQQ静态链438／514条已取得；当前完整OI／Greeks未取得，旧Cboe单点OI的时间／乘数／完整性未核，MM身份与开平仓标签缺失。完整GEX／MP自建及历史样本外预测为NOT_ESTIMABLE，合格历史预测样本N=0；真实库存NOT_IDENTIFIABLE。没有把旧链、今天静态乘数、异动列表或未知OI日期拼成历史。

2026-11-27 12:08—12:09美东新增有界实测：SPY／QQQ在11/27、11/30两个到期日共2118份静态合约；其中8份近现价Call／Put的OI、IV、Greeks动态字段成功返回，另有4合约共400笔最新成交和8次1档盘口。动态路径为订阅basic后get-basic-qot，全量snapshot小批仍15秒超时。本次非空有限字段不等于独立经济有效性或全链验证；盘口缺源时间，MM侧、q0、开平及完整历史仍缺。供应商净主动流代理已对真实窗口离线计算，q保持null，不冒充MM净流或GEX符号。细表见[最新审计](docs/MOOMOO_DEALER_INVENTORY_AUDIT.md)。

做市商持仓方向研究按[独立识别SPEC](specs/DEALER_INVENTORY_IDENTIFICATION.md)执行：分别验主动方、MM买卖侧、库存增量、库存存量、Call／Put／总GEX；手动p_long仅教学情景，无符号集中度不参加方向准确率比较。没有独立capacity标签不训练声称恢复q的模型；有分类增量仍需初仓、覆盖及调整才可识别存量。新增前台只读审计脚本与20项离线检查，不启动后台任务、不改HF教学应用或券商路径。

2026-11-27外部MM分类来源研究已补充[免费与付费比较](docs/MM_CLASSIFIED_DATA_SOURCES.md)，识别SPEC更新至0.2。实际C1 TBT免费旧日样本113,018条参与者侧记录、58,293条MM，抽样多数缺对侧，不等于完整成交或净库存；Open-Close样本具有MM买卖数量，累计日内文件须差分。OCC免费日级MM活动无买卖／行权价；NYSE旧示例日期未核、JFE复现包为伪数据，均不作为真实历史标签。当前moomoo同期逐笔真标签匹配仍N=0，未训练／校准F2或恢复q；仅完成下载审计、官方费用与许可核对及接入设计，没有付费订阅、申请试用、新HF发布或原始样本外传。


独立research/max_pain.py做精确单期理论支付最小集合，保留平底／无界、拒绝缺OI／未知乘数／不完整链／非标准条款；提供冻结目标、未来观察可得时间及目标迁移函数。hf_space/gex_scenarios.py对全链逐点重算欧式BSM Gamma，比较固定符号、启发式库存先验、无符号集中度与极端压力；使用.01*S²共同单位，IV／时间情景与库存推断区分，情景包络不是置信区间。其数学与TOY演示不代表真实库存、已校准概率或预测准确率。

HF新增数据审计、GEX情景、Max Pain计算器、实验设计四Tab；只在明确的TOY演示按钮后计算，中文／English切换保留报告字节。不从HF读取本机PCR数据库／原始链／凭据，也不上传这些文件。公开包为27文件（26源码＋MANIFEST），仅新增两个研究UI／GEX模块及独立Max Pain源文件，无券商执行器或新采集任务。预测／交易用途须先通过真实point-in-time归档、强基线及独立留出；未通过仅作结构参考。实际测试和公网证据另行补录。

本轮性能优化保持研究口径：首屏不再预加载AI训练与Plotly Express，只在实际训练／画图时导入；Max Pain曲线使用一次验证的精确批量支付扫描；S&R逐交易日提取对齐价量数组，替代逐bar的Pandas索引。真实1560行、延迟0／1的完整报告除代码指纹与运行时刻外完全相同。独立本机测量中，S&R延迟0中位610.57→326.40ms；合成5000合约的Max Pain计算加62点曲线4.542→0.201秒。它们不是公网端到端时延或策略成绩。完整优化后522项研究测试通过；随后仅语言／首页文案调整另复测4项导航测试。

本项目各托管入口默认English，保留中文切换。HF与Community Cloud由同一入口实现；GitHub Pages在无有效保存语言时使用English，显式保存的zh／en优先，存储不可用也回到English。主站首页说明覆盖六类研究，AI模型仅是其中一个专题；语言变化不触发取数／训练，也不改已有报告字节。旧Sites教学页单独核对，不因仓库或Pages已更新就声称旧站同步完成。

性能维护约定：仅在用户明确要求时集中做一次性能测量与优化；日常功能开发只做必要验证，不自动扩大为持续提速或启动定时优化。当前一次提速来自用户明确请求，验收完成后即结束该增量。

研究与Trading System可分别在两个chat讨论，并以现有spec交接。用户已澄清当前在讨论chat组织；本轮没有建立新代码项目、移动执行模块或创建新的GitHub仓库。

0.11.0源码已由现有GitHub App提交为9d208a85e656eb6f04bc338129b4b38b836e25cd；HF与Pages工作流成功。HF固定仓库／runtime为2daea2aeab31b573999c73160daaa9c253a4cce0，26应用源码一致、MANIFEST仅时间不同，另核纯LFS.gitattributes。当前真实S&R、中英同字节、English默认及390px已复验；Pages／备用Cloud的English默认与中文切换也实际通过，Cloud本轮不宣称完整新增研究验收。期权UI与旧Sites记录在各自实际通过后追加，不以测试脚本准备状态代替成功。

期权页实际公网验收已完成：明确TOY数据的GEX与Max Pain、固定数据审计、原生下载、中英同字节、改参不重算和390px公式均通过（37事件／130检查，JS异常0）。原生GEX与MP指纹及明细见部署说明0.11.0；合格真实历史预测样本仍为0，不能把界面成功解释为真实做市商库存或预测有效。

本项目四处托管入口均已实际验收默认English／中文切换：HF、Community Cloud、GitHub Pages及旧Sites教学页。旧Sites单独发布v3（源156002b064b10f1eb3b15dbc8f82708f95d5d5a3，部署succeeded），保留原PUBLIC与网址，双语媒体／交互／手机验证通过。它与仓库／HF发布分开记证据，详见部署说明。

发布收尾核对到并行界面增量a17603bfc459824c945fe2de002d75022468d1ec：浏览器保存手动语言选择，新访客仍默认English。已保留该提交，并核定本机主程序与发布版仅一处空行差异；现在已对齐发布版，原工作区快照保留。新增界面以6项导航增量测试及实际浏览器偏好刷新另验；原522项核心研究结果按未改变的计算源码指纹保留，不能宣称完整524项全部重跑。云端源码仍须固定revision逐字验证，Cloud只记录已实际观察的界面行为。

后续Trading System拟采用独立GitHub仓库与HF Space，研究Lab与执行系统的模块、数据、权限与消息边界已追加到specs/VEIGHNA_MOOMOO_SYSTEM.md。此处为用户确认的后续组织方向；当前没有创建新repo／Space／代码项目或迁移活动账本，真实券商模拟接入状态未改变。

追加界面偏好版本已复验：发布提交a17603bfc459824c945fe2de002d75022468d1ec、HF工作流45956854531成功，当前HF仓库／runtime为c5f954328abb4af42e9bac36dfe3f69dd132d772，RUNNING／CPU Basic。26源码与新本机包逐字一致，MANIFEST仅created_at不同，纯LFS元数据单独核对。主程序SHA256为4d571abd4a3c8133786091297d459ffe3bea9dba7b2be1cfed19dc7be250dbb4。原9d208／2daea记录保留为核心研究功能验收基线；S&R／GEX／Max Pain计算及其独立UI源码未变，新增偏好另经6项导航和实际浏览器English→中文→document刷新保留中文→English→刷新保留English验收，无连续重跑或Run／取数动作。证据为state/options-research/qa/language-persistence-a176-browser-20261127T024037及当前hf-package-verification.json。

## 0.11.1：免费MM样本核验与方法目录

按用户新授权实现本机`research/cboe_mm_sample.py`与`scripts/run_cboe_mm_validation.py`，只用已下载免费C1样本；不采购付费数据、不申请试用、不新增持续采集。严格解析真实MM侧买卖量，隔离507条非期权／未证腿、未知side与capacity，保留原始root和精确行权价，未知乘数／交付物不填100。执行与组合分组、重复拒绝、累计差分修订及来源哈希明确；不对抽样放大，不把数据量当独立证据。真实结果与反例在本机ignored state的英文默认／中文可切换HTML及JSON，具体见[复跑说明](docs/CBOE_MM_SAMPLE_VALIDATION.md)。

样本可核MM买减卖和双MM相抵，但不识别q0或完整区间；真实q、净存量GEX、校准概率和预测准确率仍未知。与同日EOD的精确合约交集只作抽样范围诊断，调整root单列；EOD完整性未验，不称完整库存真值。2025样本没有同期Gamma，不能配2026 moomoo Greeks；同期逐笔标签匹配仍0。

新增九种方法的`research/dealer_methods.py`能力目录与门槛，包含此前固定符号、先验、集中度、NBP、capacity流、需求框架、隐状态、组合及有限风险重定价。公开期权页增加Inventory methods／持仓方向方法Tab及独立TOY初仓敏感性；不上传真实Cboe样本／逐合约净流，原教学GEX／MP机制保留。完整状态契约更新至[库存识别0.3](specs/DEALER_INVENTORY_IDENTIFICATION.md)。HF白名单只增加无行情方法目录一个模块，预期28文件（27源码＋MANIFEST），不包含本机Cboe适配器或结果。此处记录实现范围；实际部署与新访客验收见下文，不能仅以本机测试当公网成功。


0.11.1实际验收：代码提交566e710d68dbeb00999baedcce9a9b4f89748816，经现有GitHub App按旧head校验发布；[HF工作流46051157414](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/46051157414)成功。HF仓库／runtime均为b4a23e18bec37c0095c6f1461d93f8e902f4070f，RUNNING／CPU Basic；27源码逐字匹配本机，MANIFEST存在，公开包未纳入Cboe本机适配器、样本或结果。相关165项核心／方法／UI／既有GEX、MP及导航加8项运行器测试，共173项通过；没有声称重跑历史全部研究测试。新访客English、九方法、显式TOY、中文切换后同一报告、390px及JS异常0均实测通过。本机HTML亦通过中英与390px，无JS异常；数据驱动明细仅本机。验收证据在state/cboe-mm-validation/，程序、真实数据、部署及页面验收分别记录。备用Cloud本轮未单独重验，Pages未改。

## 新研究设计：QQQ／SPY盘前大涨后的开盘回撤

用户先要求方法和数据可得性，计划见[盘前事件研究SPEC](specs/PREMARKET_OPENING_DRAWDOWN.md)。暂将QQO理解为QQQ；主观察09:25 ET、独立09:29敏感性，按已完成分钟价格相对前一真实常规收盘涨幅>2.5%选日；统计09:30—10:00相对开盘下探0.5%／1%／2%的频率、幅度分布、10:00是否收跌及回补缺口。不得以日K开盘gap代替盘前条件，或混用盘前最高价和固定观察值。

初始设计阶段的成功5m快照为SPY／NVDA十日RTH，缺盘前和QQQ；当时只读CLI帮助与官方限制，未报概率。后续先核验盘前1m与当天个案，再按用户要求扩展365自然日，当前实际状态见下文。非常规时段可能不足两年，不能把本次一年覆盖外推为八年；所有频率及区间须带事件数。此增量仅本地研究，未改HF应用或执行模式。

后续按用户要求已只读核验2026-11-27当天QQQ：6页历史响应、前日常规收盘和当天210根RTH 1m及盘前ALL；保留结束日界限探测、空占位及采集时未完成bar，不将未来标签纳入完成行情。当天支持盘前涨、开盘回落与后续修复，但固定09:25／09:29不满足>2.5%，不作为该主事件命中。个案图、价格、哈希及独立复核留本机state/premarket-case，未公开新行情；设计SPEC更新至0.2，历史概率仍未估计，没有新应用发布或执行变更。

365日增量现已完成：专题SPEC升为0.3，目标2025-11-27至2026-11-26，不含今天，250个交易日。独立只读1m历史采集器`collect_premarket_history.py`取得QQQ／SPY各74页366841行（含暖机和夜盘），冻结分页与不可变progress清单；全部148页SHA／行数／美东与Unix时间通过核对。纯事件引擎`research/premarket_events.py`与本机双语报告器`run_premarket_365.py`分别计算09:25／09:29固定涨幅及截至09:25／开盘曾涨幅>2.5%的四种条件，最大下探为首RTH分钟open至09:30—10:00最低low，不是窗口末收盘收益。阈值使用原始Decimal价格比较。

实际固定09:25触发每只2天：QQQ下探≥0.5%／1%／2%为2/2、1/2、1/2；SPY为1/2、1/2、0/2。完整盘前曾涨>2.5%触发QQQ4天、SPY3天：对应3/4、2/4、2/4及1/3、1/3、0/3。四种口径、所有事件／反例、同覆盖基线、分母漏斗、Wilson参考区间和来源指纹保存在本机报告。首30分钟、前收与全RTH均250日完整；曾触发组要求全盘前正成交量，QQQ220日／SPY144日合格，其余因零成交量分钟保留未知，不填成未触发。独立逐日2×250日算法复核0差异；精确阈值修正后结果不变。

公司行动／除息与历史API实际交付时间未逐项重建；两只固定事件发生在相同两天，不池化为4个独立冲击。n=2—4不足以称稳定未来概率，未验证控制波动后的增量预测力、样本外可执行性或扣费收益。新数据、HTML／CSV／图留data／state，没有公开行情或新增HF发布，没有后台任务或账户／订单请求。

0.4盘前事件增量：按用户要求增加道指ETF DIA，以及可配置的盘前涨幅阈值；详见[专题SPEC第9节](specs/PREMARKET_OPENING_DRAWDOWN.md)。原QQQ／SPY源不变，新增DIA独立74页366841行，合计三ETF222页；同一365日、日历和不复权口径。三只各250个开盘窗口完整；DIA固定09:25有效236日，2.5%下2事件，下探≥0.5%为1/2、≥1%为0/2、最大0.8943%。DIA整段盘前正成交量合格窗为0，因此曾触发主概率不可估计，不写0%；3个不完整窗已知触发另列。

新增`analyze_symbol_thresholds()`及精确整数比值，Python／浏览器分别以Fraction／BigInt判断严格涨幅边界。CLI可重复`--capture`合并不重复标的，并输入`--premarket-threshold-pct`及预设网格；离线网页支持例如1.25%的自定义输入、应用后更新、非法值保留原结果、同覆盖基线／n／区间／幅度／全部日期、当前派生JSON下载和中英切换。默认主阈值2.5%，并列网格0.5／1／1.5／2／2.5／3%，不排序选择最优。网格是本年度探索性描述，若用于选交易条件须另留测试期。

最终本机报告为`state/premarket-365/20261127T200955569265Z/report.html`。70项相关测试通过；独立3ETF×6阈值的4500日、18000定义日及72组汇总0差异；实际浏览器72组与Python一致，1.25%另12组与独立算法一致，精确边界、6类非法输入、DIA无覆盖／无事件、派生JSON导出、中英与390px通过，无JS异常。数据与产物留本机；本轮未改公开HF应用版本或执行系统，也没有启动后台任务或性能优化项目。

## 0.12.0：HF盘前涨幅与开盘半小时下探

用户随后授权将上述三ETF统计公开到HF，并添加应用直达／HF项目页两个明确入口。[专题SPEC升为0.5](specs/PREMARKET_OPENING_DRAWDOWN.md)。新增独立`hf_space/premarket.py`与`premarket_ui.py`，第七研究入口，选择QQQ／SPY／DIA、自定义盘前涨幅阈值、四种观察定义和显式运行；显示n、覆盖、最大下探分布、阈值频率／区间、同覆盖基线、全部触发日与派生JSON。上次结果、已应用参数和新输入分开，语言切换不重算。

唯一新增公开参考集是`hf_space/assets/premarket_reference_365.json`（750标的日、1005380字节，SHA256 `1b93af7a00e7c241ca9e2c76a9ae6234475c77c12170ba2d2ca086ed6cee7b60`），只含无量纲日级充分统计与净化来源指纹，不含分钟OHLCV、绝对价格、成交量、路径、游标或账户凭据。构建前核验原10份产物与222源页；应用严格schema／SHA校验，打包器固定此一个派生JSON的审计hash。其他原始data／state仍不发布，不改private snapshot权限。

观察范围仍2025-11-27至2026-11-26、不含今天，不是自动更新的实时feed。DIA完整盘前无合格窗时不可估计，已观察部分触发另列；n=0不填成0%预测。阈值探索不能称最佳收益策略，历史交付时钟、公司行动及成本限制保留。程序验证、源码上传、runtime运行及公网UI分别验收；实际结果追加在下文。

0.12.0实际验收：应用代码提交`9e6cbbb080a73b9de1580c12af07c887ec203c95`，Docker上下文清单补齐提交`48f6ba03f508780520cbe7dfc99207a4997d21d2`；[最终HF工作流46065758842](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/46065758842)成功。HF仓库／runtime同为`25ebe7014fcc5f331aff99872183314812367394`，RUNNING／CPU Basic。30份允许源码与派生资源逐字一致，MANIFEST逐项hash一致，总包31文件；原始分钟OHLCV和本机报告未进入包。

115项相关测试通过；后续新增Docker允许清单一致性用例，打包组3项通过（覆盖116个不同用例，未重跑全项目历史测试）。独立数据审计72网格组及1.25%的12组无差异。公开应用实际验证English默认、两个访问入口、1.25%样本18／4／5、原生下载与纯计算一致、改参数未提交不重算、中英JSON同字节（SHA `735b5a2b8a96a8403cbd3e8da53cbacef4dc3052b74aea5a286855b5f1cdff38`）、DIA无合格窗／partial3、390px和JS异常0。证据位于`state/hf-premarket-review/`，包括最终包核验及public-custom／public-dia。应用直达与HF项目页显示同一版本；备用Cloud／Pages本轮未单独验收。


入口文案（2026-11-27）：独立应用按钮现命名为“Launch Research Lab／进入研究平台”，替代原“Open app／打开应用”；旁侧仍为“Hugging Face project／Hugging Face项目页”。README、Space说明及个人网站Projects对应入口同步采用新的名称，网址、研究参数和已生成报告格式保持原契约。文案部署另做实际中英文入口与目标URL验收。


入口文案已实际验收：应用源码提交73b51bf98ac45056c5933ca84e3d5e95fdde3748，HF工作流46091637479成功；仓库与runtime同为9853568652b19f2847929cf3aec9ffcd7f6a0a4b、RUNNING。新访客English显示Launch Research Lab，中文显示进入研究平台，两个目标URL正确，旧按钮名消失，390px正常且JS异常0；未提交研究表单。个人网站以50e31afd4c9f2fe7476caab45d97e56099edff7c同步入口，格式、源链接、部署、编译站链接四项检查均成功，Projects卡片及详情页均读到新标签。证据为本机量化准备/native-label-qa/public-20261128T011213Z-b00503/qa.json（UTC文件名对应纽约2026-11-27）及personal-website-native-entry-50e31afd/acceptance.json。

## 0.12.1（已发布）：研究工作台界面

只改呈现层；模型、策略、时间定义、样本筛选、成本、精度、统计方法、公开参考集及其SHA均不变。

- 共享主题：`.streamlit/config.toml`新增`[theme]`、`[theme.light]`、`[theme.dark]`（深蓝文字、青绿小面积强调、0.5rem圆角、统一边框与图表分类色），原`server.maxUploadSize=12`与`browser.gatherUsageStats=false`保留。新增纯呈现模块`hf_space/ui_theme.py`：一次注入的样式只使用`st-key-*`、`data-testid`和自有`alpha-*`类，不依赖随机emotion类或nth-child；颜色用半透明色，浅／深主题均可读。
- 页首：品牌与说明、语言切换、两个访问入口（Launch Research Lab／进入研究平台、Hugging Face project／Hugging Face项目页，名称和网址不变）改为同一行次级按钮；七个专题以`hf_study`单选的胶囊样式置于主内容区。
- 首页：英雄说明七个专题及数据边界（真实／冻结派生、访客CSV云端临时处理、合成／TOY教学、不连接券商），下设七张专题卡（分类、简介、来源徽章、“打开专题”按钮仅切换页面）。AI四模型改为首页下方的01专题；已有AI结果时目录收入折叠区。
- 各专题标题下统一显示来源徽章；参数在侧栏的专题提示侧栏位置（手机左上角箭头展开）且修改参数不自动运行。AI与盘前页的“上次运行”条显示已执行设置；表单内未提交的编辑不会进入会话，只有提交后输入与展示结果不一致（例如提交失败、旧结果保留）时才标记“输入已修改，尚未应用”。
- 盘前页：参数放入三列表单（手机自动单列），主按钮；每只ETF一张结果卡，先列事件n与合格交易日，再列平均／中位／P90／最差最大下探，并以状态徽章区分“有事件样本”“小样本（n<10）”“当前阈值无事件”“不可估计·覆盖不足”；后两种仍保留原说明，不显示为0%概率；覆盖不足时卡内注明部分窗口触发数。原汇总表（新增状态列）、图表、频率／同覆盖基线、全部事件日、定义／公式／来源与下载均保留。
- 修复既有问题：真实浏览器中切换语言会重建译名导航单选并回报空值，原逻辑把专题重置为AI页；现仅接受有效专题写入路由记忆，空值回退到已记住专题。
- 响应式：主体最大宽1280px；641–1100px专题卡两列，≤640px单列；KaTeX公式与代码在自身容器内横向滚动。

打包：`scripts/package_hf_space.py`白名单新增`.streamlit/config.toml`（仅允许server／browser／theme表并做TOML校验）与`hf_space/ui_theme.py`，预期总包33文件（32源码＋MANIFEST）；`.dockerignore`同步放行，Dockerfile新增`COPY .streamlit/config.toml ./.streamlit/config.toml`（Streamlit从工作目录读取），工作流路径触发加入该配置。本机在临时副本完成打包（33文件，包含两新文件）；Dropbox目录内直接打包会因同步改变文件元数据而被稳定性检查拒绝，属环境限制，未放宽检查。

本机验证：导航、盘前UI与打包测试及Beta／5分钟／期权／日频／S&R界面测试共49项中48项通过；`test_intraday_ui.py::test_snapshot_not_configured_is_friendly_and_cannot_train_or_fall_back`在未改动的远端main上同样失败（测试仍假设首屏中文，与English默认冲突），未在本增量修改。为运行测试按`deploy/huggingface/requirements.txt`补装本机`state/space-venv`缺失的exchange-calendars等固定依赖。真实浏览器核验：首次English、中文切换与专题保持、七个入口与两个链接、1.25%＋09:25样例QQQ 18／SPY 4／DIA 5（DIA 236/250）、`ever_before_open`下DIA 0/250不可估计并另列部分窗口触发（1.25%阈值11次、2.5%阈值3次，与纯计算一致）、1366／820／390px无页面横向溢出。截图在`docs/ui_screenshots/`（本机，未提交）。

0.12.1实际发布与公网验收：发布提交`6f945ca7b54b67bdf3e147a8958fad12515915d9`（父提交`5e56e716680064127cd46de9144df4610bd8b185`，正常快进，无强制覆盖；含16个UI、打包与说明文件，包括`docs/STREAMLIT_CLOUD_DEPLOYMENT.md`的配置说明更正）。[HF工作流46099673415](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/46099673415)成功；HF Space仓库revision `cd62184c9e8c21d39da1eec3ed884e89027547f4`，RUNNING／CPU Basic，未改变硬件、计费或凭据范围。2026-11-27公网实测：新访客English、新版页首与主题生效；两个入口文案与URL正确；七个专题齐全；盘前1.25%＋09:25为QQQ 18／SPY 4／DIA 5（DIA 236/250），上次运行条显示已执行设置；切换中文仍在盘前页且数字不变，切回English正常；390px无页面横向溢出，浏览器控制台无错误。未在公网重复验证DIA覆盖不足、错误状态与下载字节一致性（本机测试覆盖），备用Cloud／Pages未单独验收。

发布包逐文件核对：Space revision `cd62184`的MANIFEST共32个源码条目，逐一与提交`6f945ca`对应源文件SHA256一致（0差异），加MANIFEST共33文件；盘前参考集SHA仍为`1b93af7a…6cee7b60`。语言偏好：公网三次“中文后重新打开”中两次正确恢复中文；首次重新打开却显示English，浏览器存储被写为`en`，之后同顺序未能复现，原因未定，因此语言偏好记忆暂不记为已完全验证，后续需在新浏览器档案中重测。

0.12.1后续修正：首页AI专题卡原来只有“↓ Continue below on this page”说明文字，不可点击；现改为页内链接“Go to the AI study below ↓／前往本页下方的 AI 专题 ↓”，指向AI专题标题锚点`#ai-study`，仅滚动页面，不触发计算或切换数据。其余六张卡仍为“Open study →／打开专题”按钮。本机浏览器验证点击后滚动到AI标题且无图表或训练被触发；公网结果以下一次HF工作流与页面检查为准。该修正随提交`865c0d2`发布，HF工作流46100570784成功、Space revision `c87cbcb`运行；公网点击后滚动到AI标题，无图表或计算被触发。

## 0.12.2（已发布）：首屏与交互动效

仍只改呈现层，计算、数据、默认值、widget key与会话状态不变；新增动效全部为CSS／内联SVG，不加载外部脚本、字体或图片。

- 首屏改为自带配色的深色横幅（深蓝至青绿渐变），背景为缓慢漂移的极光光晕与渐隐点阵；标题为白至青绿渐变字，仍是原生`st.title`。右侧为确定性装饰示意图：净值线逐步绘出、基准虚线、成交量柱依次升起、扫描线与终点脉动环，以及“只在点击运行后计算／来源逐项标注”两枚浮动标签；图下固定标注“示意图 · 非市场数据或回测结果”，SVG `aria-hidden`，不得被描述为回测或真实收益。
- 首屏数字：7个研究专题、250个冻结盘前交易日、0个券商连接，以CSS `@property`计数动画显示（另含屏幕阅读器文本）；`@property`的syntax写作CSS转义`\3C integer\3E`，因为字面尖括号会被`st.html`清洗器当成标签而整段丢弃样式。
- 专题卡依次淡入上浮；悬停时上移、边框转青绿并亮起渐变顶线。导航胶囊选中态为渐变底与柔光；主按钮悬停轻微上浮发光；页面标题、徽章、上次运行条与盘前结果卡淡入。
- `prefers-reduced-motion: reduce`下关闭循环动画、入场动画直接到终态。首屏在浅色与深色应用主题下都使用自身深色配色；≤640px隐藏示意图列，三项数字同行。
- 本机验证：相关UI测试33项通过（导航、盘前UI与打包、期权、Beta）；1366px浅色／深色与390px中文浏览器检查无横向溢出，卡片悬停与示意图动画生效。减少动态效果偏好仅按CSS规则实现，未在浏览器中模拟验证。截图新增`docs/ui_screenshots/desktop-home-hero-en.jpg`、`desktop-home-hero-dark-en.jpg`、`desktop-cards-hover-en.jpg`、`mobile-home-hero-zh.jpg`（本机，未提交）。
- 发布记录：提交`d967678`快进推送main（父`865c0d2`），HF工作流46106735998成功，Space revision `7d363c7`运行，远端`hf_space/ui_theme.py` SHA256与本机一致（`7a18d788…0196b7a`）。公网检查：首屏极光动画、示意图与三项计数生效，7张专题卡，无横向溢出；切English后盘前09:25、阈值1.25仍为QQQ 18、SPY 4、DIA 5（DIA合格236/250）；390px隐藏示意图、标题26px、入场动画结束后文案与数字完整显示。减少动态效果仍未在浏览器模拟验证。

0.12.3（已发布）：英文界面的页面标题、小节标题（subheader／header）、侧栏小节标题、展开区标题与“Study Settings”粗体小标题统一为Title Case（虚词and／the／of／at／a／with小写，如“Understand the Four Strategies”“Strategy Data and Settings”）；“5-minute”标题改为“5-Minute”。七个专题名（导航胶囊与首页专题卡共用，如“Daily Momentum & Trend”“Premarket & Opening Downside”）同样改为Title Case，README与HF部署说明中的入口名同步。浅色主题改为冷灰蓝画布＋白色面板：`.streamlit/config.toml`浅色背景`#F5F7FA`、次背景`#EBF0F5`、边框`#D3DCE6`、表头`#E9EFF5`、侧栏`#EDF1F6`；专题卡、盘前结果卡、表单、展开区、Tab面板与未选中导航胶囊用CSS `light-dark()`在浅色下取白底与轻阴影，深色主题保持透明不变（依据Streamlit在`.stApp`上设置的color-scheme；不支持`light-dark()`的旧浏览器退回透明）。Dataframe画布与图表随主题背景，不单独设白。本机1366px浅色首页与盘前结果页、深色首页已检查。中文文案、正文、按钮、字段标签、表头与下载JSON不变。相关测试断言同步更新；UI测试48项通过，另1项`test_snapshot_not_configured_is_friendly_and_cannot_train_or_fall_back`为既有的中文首屏假设失败（发布版同样失败）。发布记录：提交`2c249eb`快进推送main（父`34288bb`），HF工作流46108435077成功，Space revision `76c9aaf`运行，远端`ui_theme.py`、`streamlit_app.py`与`.streamlit/config.toml` SHA256与本机一致。公网检查：画布`#F5F7FA`、专题卡／表单／盘前结果卡白底，七个专题名与小节标题为Title Case，无横向溢出；盘前09:25、阈值1.25仍为QQQ 18、SPY 4、DIA 5（DIA合格236/250）。

0.12.4（已发布）：品牌标志由“α”方块改为内联SVG标志（深蓝至青绿圆角底、四根上升成交量柱、青绿净值线与终点亮点；进场时线条绘出，悬停微转，减少动态效果下直接到终态；`aria-hidden`装饰，不代表任何数据）；字标“Alpha Trading Lab”中“Lab”为青绿至蓝渐变。顶部品牌区改为白底圆角顶栏（深色主题为半透明），主区顶部留白由3.75rem减为3.25rem。侧栏改为白色导轨：浅色侧栏背景`#FFFFFF`、次背景`#EEF2F6`，右侧细分隔线；侧栏小节标题带渐变方点与下分隔线，字段标签加粗，说明文字改为左侧青绿细线的缩进注释，侧栏内表单／展开区／上传区为`#F7F9FC`无阴影面板。文案、widget key与计算不变。本机1366px浅色、390px检查无横向溢出；导航、盘前UI与打包测试15项通过。发布记录：提交`9e748a8`快进推送main（父`fe8df2a`），HF工作流46109524200成功，Space revision `99f5127`运行，远端`ui_theme.py`与`.streamlit/config.toml` SHA256与本机一致；公网确认SVG标志线条绘出、白色顶栏与白色侧栏生效、7张专题卡、无横向溢出。本次只改样式，未在公网重跑盘前计算。

0.12.5（已发布）：同一HF Space已绑定自定义域名`alphalab.levyquant.ai`（HF API `runtime.domains`显示READY，HTTPS返回200）。顶部“Launch Research Lab／进入研究平台”、README、Docker模板README、GitHub Pages主按钮、部署说明与盘前规格中的应用直达链接改为`https://alphalab.levyquant.ai/`；“Hugging Face project／Hugging Face项目页”仍指向`huggingface.co/spaces/Rexymiao/alpha-trading-lab`。旧`rexymiao-alpha-trading-lab.hf.space`仍可访问，是同一部署；历史验收记录中的旧链接保留原样。只改链接，不改部署、Secret或计算。发布记录：提交`59762a7`快进推送main（父`a441978`），HF工作流46127274267与Pages工作流46127274293成功，Space revision `3ad923a`运行，远端`ui_theme.py` SHA256与本机一致；公网在`https://alphalab.levyquant.ai/`打开应用，Launch Research Lab指向新域名、Hugging Face project仍指向HF项目页；GitHub Pages主按钮指向新域名。

0.12.6（本机已改，未发布）：顶栏语言选项右侧新增日间／夜间切换图标按钮（日间显示月亮，夜间显示太阳；`aria-label`／title随语言为“Switch to night mode／切换到夜间模式”等）。Streamlit 1.67没有Python端设置访客主题的API，按钮由`st.html(unsafe_allow_javascript=True)`中的前端脚本点击Streamlit自带主菜单的`stMainMenuItem-theme-Light／Dark`项，再收起菜单（切换期间菜单透明）。主题当场切换，不重跑脚本、不刷新页面，现有报告、session_state、widget key与下载JSON不变；选择由Streamlit自身保存在浏览器`stActiveTheme-/-v2`，刷新与再访保留。未选择前仍跟随系统；⋮菜单中的System／Light／Dark仍可用。主菜单不可用时按钮不做任何事，不刷新页面。`st.html`会去除内联SVG，图标由脚本插入（脚本内尖括号转义）。本机1366px：盘前报告运行后切夜间／切回日间，报告保留，菜单自动收起；夜间下切中文，按钮文案与报告保留；375px刷新后夜间与中文保留、无横向溢出。导航、盘前UI与打包测试16项通过。
