# Hugging Face Docker 发布准备

最新0.8.1进度：Private Dataset已实际上传468行真实moomoo快照并核对hash，revision为`81acd7bef19dcfc890b71bc9a70ca7d5a7208c20`；Space的独立读取Variable／Secret尚未设置，访客仍NOT_CONFIGURED。这两个验收分开，自动watch未启动。设置入口为[本Space的Settings](https://huggingface.co/spaces/Rexymiao/alpha-trading-lab/settings)，在Variables and secrets添加ALPHA_SNAPSHOT_DATASET和ALPHA_SNAPSHOT_READ_TOKEN，详细值见[操作说明](MOOMOO_CLOUD_SYNC.md)。历史0.8.0验收保留文末。[新鲜测试展示与命令](ACCEPTANCE_DEMO.md)

这是云端 Python 研究界面的发布说明。Hugging Face是主要交互入口，GitHub Pages保留静态教学页，Streamlit Cloud是可选备用。0.8.0新增私有快照读取，最新验收见文末；前面版本的记录属于历史里程碑。容器启动、页面交互和源码上传分别核对，应用本身不包含发布凭据。

## 本次个人部署目标

个人PRO账号：`Rexymiao`。公开Docker / CPU Basic Space：[Rexymiao/alpha-trading-lab](https://huggingface.co/spaces/Rexymiao/alpha-trading-lab)。用户已创建Space并将细粒度发布令牌保存为GitHub仓库Secret `HF_TOKEN`；代码和聊天均不保存令牌。

2026-11-26已完成实际发布与公网验收：

- [Space页面](https://huggingface.co/spaces/Rexymiao/alpha-trading-lab)；[应用直达](https://rexymiao-alpha-trading-lab.hf.space)。
- GitHub应用源码commit：`b54637fb25eef7746a0ce2c93a97e18c672fcb62`；[成功的同步工作流](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/45774744781)。
- Space commit与runtime.sha：`24cdfa5c21ec02cf0ed4e7971c9716691c1d59f0`；状态RUNNING，当前及请求硬件均为CPU Basic。
- 真实浏览器主动执行四模型成功，表格、三张Plotly图、中英文切换、实际JSON下载及390px手机布局通过；JS异常0。下载报告确认PyArrow25.0.1 / NumPy1.26.4 / Streamlit1.67.0。
- 初次部署的PyArrow26/NumPy1.26导入错误已修复，Docker构建已增加真实表转换检查。公网测试使用明确标记的合成教学数据，不是策略市场有效性证据。

Streamlit Community Cloud也已通过真实在线来源、四模型、三类下载和双语验证。实际PyArrow为24.0.0，与本HF固定25.0.1不同；详见其部署说明。

自动同步默认目标为`Rexymiao/alpha-trading-lab`，`HF_SPACE_ID`保留为可选覆盖；不创建Space、购买服务或更改硬件。

## 账号和费用前提

当前官方要求：个人账号在 CPU Basic 上新建 Docker Space 需要 PRO 订阅；组织需要相应 Team 或 Enterprise 计划。CPU Basic 的硬件无小时费用，不等于所有免费账号都能新建 Docker Space。请在自己的 Hugging Face 页面确认账号资格和套餐；本项目不会代购套餐、添加支付方式或选择付费硬件。

Streamlit 的内置 Spaces SDK 已弃用；本包使用 Docker SDK。Space 根目录 README 的 YAML 已配置 `sdk: docker` 和 `app_port: 7860`，不要改为旧的 `sdk: streamlit`。运行服务监听 `0.0.0.0:7860`，使用非 root UID 1000，并将数值库线程限制为1。

官方来源：[Streamlit 部署建议](https://huggingface.co/docs/hub/spaces-sdks-streamlit)、[Docker Spaces](https://huggingface.co/docs/hub/spaces-sdks-docker)、[账号与硬件条件](https://huggingface.co/docs/hub/spaces-overview)、[CPU Basic 规格](https://huggingface.co/docs/hub/spaces-gpus)。实际创建时以账号界面的资格及费用说明为准。

## 先生成可检查的本地发布包

在项目根目录运行：

```sh
python scripts/package_hf_space.py
```

默认输出在项目父目录的 `outputs/hf-space-bundle/` 和 `outputs/hf-space-bundle.zip`。需要另一个名字时可加 `--name hf-space-review`；参数只接受简单目录名，不接受绝对路径或路径分隔符。发布包不是数据备份。

打包器只复制以下明确清单，不递归复制仓库：

- `deploy/huggingface/` 下四个模板：在包根目录成为 `Dockerfile`、`README.md`、`requirements.txt`、`.dockerignore`。
- `hf_space/__init__.py`、`engine.py`、`streamlit_app.py`、`history.py`、`strategies.py`、`strategy_ui.py`、`intraday.py`、`intraday_ui.py`、`snapshot_source.py`。
- `research/__init__.py`、`research/data.py`、`research/models.py`、`research/portfolio.py`。
- 根目录的 MIT `LICENSE`，以及自动生成的 `MANIFEST.json`。

不会复制 `data/`、`runs/`、`state/`、`execution_lab/`、`.git/`、本机配置、根目录研究界面、pipeline、coverage、moomoo CLI、凭据或模型。基础研究来源不需密钥；私有快照来源只需独立Dataset读取Secret，不使用moomoo凭据或GitHub发布令牌。

脚本在写出前检查文件存在、UTF-8与Python语法，拒绝符号链接及目录连接；读入后和写出后再次核对源文件，变化中的源程序会报错。`MANIFEST.json` 只含包内相对路径、字节数和SHA256，不含本机绝对路径。报错时不要上传产物，等源代码编辑完成后重试。

目标目录已经存在时，只允许覆盖清单内的已知文件；发现额外文件或目录会停止，不会递归删除它们。请先人工核对额外内容，或使用新的 `--name`。成功退出只代表本地打包与哈希检查完成，不代表Docker实际构建或云端发布通过。

## 可选的本地容器验证

如果本机已经安装Docker，在生成的包目录中运行：

```sh
docker build -t alpha-lab-simulator .
docker run --rm -p 7860:7860 alpha-lab-simulator
```

浏览器访问 `http://localhost:7860`。不要直接以整个研究仓库作为Docker构建上下文。没有Docker时可以先审阅发布包；不能把语法及哈希检查描述成容器已验证。

## 用户登录后创建并上传

1. 用户在自己的浏览器登录 Hugging Face，并先确认有权按当前套餐创建 Docker Space；不把令牌发到聊天或仓库。
2. 在个人用户名下创建专用 Space，选择 **Docker → Blank、Public、CPU Basic**，不复用其他项目。不要将套餐购买或付费硬件当作自动获得的授权。
3. 在 Space 的 Files 页面上传生成目录中的允许文件，保持 `hf_space/` 与 `research/` 结构，模板四个文件放在Space根目录。ZIP需要先解压；仅上传一个ZIP不会自动成为应用。
4. 等待构建与启动完成，检查真实日志和 App 页面，再测试中英文、主动点击模拟运行、输入校验及下载。只有服务实际启动后才能报告发布成功，并使用平台返回的真实地址。

## 通过 GitHub Actions 同步到现有个人 Space

用户已决定同时准备 Hugging Face 和 Streamlit Community Cloud 两个Python应用入口，GitHub Pages主教学站保持独立。两边的账号与实际发布状态分别核对；本节保留新机器部署步骤；本次账号、Space和GitHub Secret已由用户完成。

此同步流程只上传到用户已经亲自创建的 **公开、个人所有、Docker、CPU Basic** Space。不创建Space、不切换硬件、不设置计费、不修改公开范围，也不支持组织名下的Space。请创建专用的新Blank Docker Space，不复用含其他项目文件的仓库。

先由用户在自己的HF账号完成以下操作：

1. 确认当前PRO及创建资格，创建 **Docker → Blank** Space，公开范围选择 **Public**，硬件确认 **CPU Basic**。套餐或硬件付费须由用户单独决定。
2. 到 HF **Settings → Access Tokens** 创建细粒度发布令牌，只给这个目标Space的仓库内容写入权限。不要给其他Space、模型、数据集、组织或硬件管理扩大授权。
3. 到 GitHub 仓库 **Settings → Secrets and variables → Actions → Secrets → New repository secret**，名称填 **`HF_TOKEN`**，值只在GitHub的Secret页面输入。不发到聊天、不写源码、不放进应用本身的Space Secrets。
4. 默认目标已是 **`Rexymiao/alpha-trading-lab`**，不必再建变量。只有实际选择了另一个专用Space时，才在 **Variables → New repository variable** 设置 **`HF_SPACE_ID`** 为已有的 `owner/name`。owner必须与该HF令牌的个人用户名一致，不填写URL或组织空间。

`.github/workflows/huggingface.yml` 在main分支相关模拟源文件更新时触发，也可在 **Actions → Sync simulator source to existing Hugging Face Space → Run workflow** 手动运行。手动的 `space_id` 输入可覆盖仓库变量；目标仍须通过同样的个人所有权、公开范围和CPU Basic检查。输入不是额外授权，不能用来向其他人的Space发布。

工作流只有GitHub `contents: read`，使用Python3.12与`huggingface_hub==2.4.0`。缺少 `HF_TOKEN` 或最终Space ID时会给出notice并跳过打包和上传；绿色的“跳过”不表示已经部署。此配置不需要新的GitHub OAuth或组织登录。

上传前会检查：

- 当前本地包必须恰好是19个允许文件（18源码及MANIFEST），路径、字节数与所有SHA256一致；符号链接、额外内容、缺失或变动中的包均拒绝。
- `whoami`确认个人身份与目标owner一致；目标必须已存在、为Docker且公开。
- 从Space资料和最新runtime核对硬件：所有明确值只能是`cpu-basic`，至少一项明确为`cpu-basic`。首次构建允许current未知但requested为basic；未设置requested时允许current为basic。两项仍全未知或任何一项是其他硬件均停止，不自动改设置。
- 远端文件只能是同一发布包的白名单文件或平台生成的`.gitattributes`；发现其他项目文件时停止，不删除或覆盖它们。
- 使用明确的19个`CommitOperationAdd`和已读取的`parent_commit`提交，不使用全目录上传、不删除远端文件。若远端有并发提交，停止并重新核对，不强制覆盖。

完成后的输出包含 `code_uploaded`、Space仓库网址及commit。只有收到有效commit标识时，`code_uploaded`才为`true`；这仅证明代码上传，即使观察到runtime为RUNNING，也未证明新commit对应的应用已构建完成。实际上线仍须核对该commit的构建日志、App页面和交互功能。上传后读取runtime失败时会分别保留“代码已上传”和状态查询错误，不能误报为没有发生上传。提交请求报错、响应丢失或回应缺少有效commit标识时，`code_uploaded`为`null`，表示结果未确认；应先核对远端commit，不能认定没有写入或盲目重试。

脚本只从进程环境变量读取 `HF_TOKEN`，不调用登录、不读取本地HF凭据缓存，也不持久化令牌。错误日志只报告异常类名与HTTP状态码，不输出原始服务响应、异常消息或认证头。部署令牌不属于应用运行依赖；私有快照读取另用`ALPHA_SNAPSHOT_READ_TOKEN`，固定到同一个Private Dataset，不复用发布权限。

本地有明确授权且已经通过进程环境安全提供凭据时，可以运行：

```sh
python scripts/package_hf_space.py
python scripts/upload_hf_space.py --bundle ../outputs/hf-space-bundle --space-id owner/name
```

这里的`owner/name`仅是参数格式示例，不是已创建的服务地址。本次已通过GitHub Actions执行上传，实际记录见本文开头；下列接口链接用于说明同步实现。官方依据：[Space 管理接口](https://huggingface.co/docs/huggingface_hub/guides/manage-spaces)、[runtime硬件字段](https://huggingface.co/docs/huggingface_hub/package_reference/space_runtime)、[仓库提交API](https://huggingface.co/docs/huggingface_hub/package_reference/hf_api#huggingface_hub.HfApi.create_commit)。

## 会话、休眠和数据边界

界面只在用户明确操作后运行受限的模拟。教学生成数据有明确标记；主动上传的CSV会传到Space服务端Python进程处理，不是纯浏览器计算。请仅提供有意让该服务处理的标准OHLCV数据，不带账号、凭据或其他敏感字段。发布包本身不包含本机真实行情或研究结果。

CPU Basic 按官方当前规则闲置约48小时会休眠，访问时重新唤醒；重启或停止会丢失临时磁盘内容和会话状态。本模拟不依赖持久化结果，需保留的结果由当前用户主动下载。不要为了避免休眠自动调用保活请求或承诺全天在线。

未来若确有持久化需求，当前官方方案为 Storage Buckets，旧的persistent-storage配置不应被当作仍可直接启用的服务。本版本未开通存储桶或任何付费存储。参考[休眠规则](https://huggingface.co/docs/hub/spaces-gpus#set-a-custom-sleep-time)、[临时磁盘与存储](https://huggingface.co/docs/hub/spaces-storage)。

## 并行的 Streamlit Community Cloud 入口

Streamlit Community Cloud同样使用用户自己的账号，在GitHub仓库部署表单中选择入口 `hf_space/streamlit_app.py`，而不是本机结果查看入口 `app.py`；入口目录的`hf_space/requirements.txt`用于其依赖发现。它不使用HF令牌，也不受本HF同步工作流控制。仍须单独完成平台连接、实际构建与页面验证；两边都准备不能表述为两边都已上线。

## 依赖兼容与构建检查

云端两份requirements固定`pyarrow==25.0.1`与`numpy==1.26.4`、`pandas==2.2.2`。Docker安装后实际执行NumPy数组→pandas DataFrame→PyArrow Table；导入或转换失败会使构建失败。还需通过浏览器训练后表格、图表与JSON下载验收。版本依据：[Arrow v25依赖](https://arrow.apache.org/docs/25.0/python/install.html#dependencies)、[Arrow26的NumPy要求](https://arrow.apache.org/docs/python/install.html#dependencies)。

## 手动输入预测与调仓周期

周期输入支持1–20的整数、默认5。界面建议初期从5开始并在10个交易日以内研究，明确这是教学起点而非最优周期。该值共同控制未来开盘收益标签的持有期和调仓间隔；较长周期会减少标签与独立调仓观察。已发布并核对真实手填7日与调仓间隔，后续变更仍须重新验收。

## 在线历史来源与发布包

新增hf_space/history.py，包为14文件；默认CSV、在线历史、合成教学三来源分别标记。在线模式只访问固定Yahoo HTTPS端点，不需要HF或券商密钥；仅会话保存行情，下载CSV快照和来源JSON以复现。输入、截止日期、调整口径和失败处理见[真实历史数据说明](HISTORICAL_DATA.md)。新模式已在两个公网入口完成实际服务器取数、模型计算和三类下载验收。

## 三来源公网验收记录（2026-11-26）

两个入口默认CSV，访客无需券商登录即可上传；在线默认7股加SPY，另保留明确标记的合成教学。HF服务器实际获取Yahoo 2025-04-25至2026-11-25的400日，共3200行，四模型均success，CSV/来源JSON/模型结果三份下载一致，切English保留结果。

HF获取时间2026-11-26T07:28:49.292490+00:00；CSV SHA256 `450ddcf459441d4f17ec8164b4b444d2950bfe2284917b9ce94959a0459ef4ff`，实际依赖PyArrow25.0.1、Streamlit1.67.0、NumPy1.26.4。源码包14文件已按固定Space commit逐项核对长度、字节与SHA。

Cloud独立请求的CSV SHA256为`98680c14fbbe5ee5bbbb76ead6ea38bb35ddb1b920552d2f23288edb46270c72`，两次请求不是同一冻结输入；精确比较请在两站上传同一下载CSV。完整价格、截图及测试报告只留本机，不纳入公开源码。

## 0.7.0：独立5分钟模式实际发布

2026-11-26已用现有GitHub App发布应用源码`369d3208e82b63af86d05df35309aa802e7250df`，[同步工作流45813206990](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/45813206990)成功。HF仓库与runtime均为`6a73f09770868ef0ac645452a9b4dc832a6b6866`，RUNNING，当前与请求硬件均CPU Basic；没有调整账号或硬件。

包为18文件，其中17源码与本机逐字节／SHA一致；MANIFEST仅`created_at`不同，其余一致。默认访客CSV／上传控件经实际浏览器核对；侧栏第三项是独立5分钟模式，原AI和日频规则入口保留。CSV时间为UTC开盘标签，XNYS日历处理半日与DST；未来bar、缺日、长窗口无可执行日和输入限制按[策略契约](MOMENTUM_TREND.md)处理。

公网显式选择合成教学后运行一次，三策略success、5个有效日，权益4条／回撤3条，逐日汇总及信号、权重、成交可见。中英中三次JSON下载SHA相同：`50b56f5bfebbcc6cd5c7a53d8a708a51c9e5e7a6b25920ce8629378118daf095`。390px手机数学页15条短式全部可读、最大264px小于358px内容区，页面无横溢出，人工截图核对通过，JS异常0。这不是实际行情收益验证。

实际依赖来自下载JSON：Python3.12.16、NumPy1.26.4、pandas2.2.2、exchange-calendars4.11.2、Streamlit1.67.0、Plotly5.24.1、PyArrow25.0.1。独立本机QA Python3.12.7，不能据requirements宣称所有环境完全相同。原95回归、48分钟引擎、4页面测试和17采集器离线测试通过；本轮Cloud备用未重新验收。

私有证据在`state/intraday-qa/hf-package-verification.json`和`hf-20261126T064615/summary.json`，不推入公开仓库。本机moomoo分钟请求尚未取得行情；TCP能连接、历史请求超时、日K探针未返回结构化业务结果，原因未定。保持已登录桌面状态即可，不凭此错误要求用户重设密钥或开通付费行情。

## 0.8.0 私有快照读取与本机执行分工

本机后续已取得SPY／NVDA三个完整日共468行真实5分钟K线，并核实bar-end→UTC bar-start转换。原0.7.0的超时记录是早期状态，不再代表当前历史行情能力。新来源`已发布moomoo 5分钟快照`只读取固定Private Dataset，源文件／manifest／latest与revision必须通过路径、大小、hash、时点校验。原始CSV不开放下载；研究JSON可下载。完整账号设置见[私有同步说明](MOOMOO_CLOUD_SYNC.md)。

公开包新增snapshot_source.py后为19文件（18源码＋MANIFEST），没有execution_lab、collector、真实行情、账户或券商密钥。本机执行依赖与HF研究依赖分开；框架和paper适配的离线测试不代表公开网页能下单。用户将私有Dataset／本机写凭据／Space只读Secret配置交由其他协助者稍后处理，本轮不修改这些账号设置；首次真实上传与HF读取尚未验收，也没有启动自动同步任务。

本地独立浏览器已验证新增来源菜单、空CSV禁Run及说明、快照未配置时明确失败且无教学回退／raw下载。显式运行一次合成教学三策略success，权益4条／回撤3条；zh→en→zh JSON字节相同，SHA256为`389b71581cb36e3e8e13bc82725fac871c6649304e179edb94ade6f37e2301e2`。390px无横溢，15条数学短式可读，JS异常0。Python分钟／快照／界面／发布器124项及Node26项通过。本地证据保留`state/veighna-qa/snapshotlocal-20261126T074936/`；公网发布后另核对commit、runtime与实际浏览器结果，不以本地结果替代云端验收。

### 0.8.0 实际发布验收

应用源码commit为`a91cdc9043fc5909fbfd83c4451876b2879a3317`，[同步工作流45825078929](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/45825078929)成功。HF仓库与runtime.sha均为`72a793dd3c1cc77468818335b5dd5d916e6ad10a`、RUNNING、CPU Basic。18源码与本机逐字节／SHA一致；MANIFEST仅created_at不同，其余语义一致。

公网独立浏览器已核对新快照菜单、空CSV禁Run、快照当前NOT_CONFIGURED且无教学回退／raw下载。一次显式教学运行三策略success，权益4条／回撤3条；中英中三次JSON逐字节相同，SHA256为`221b103598ed7435c6624fce2b22c4699f68204f27f7c1df6eef0b1081259cc8`。390px页面与15条公式无横向溢出，JS异常0。实际Python3.12.16、NumPy1.26.4、pandas2.2.2、Streamlit1.67.0、PyArrow25.0.1；本地Python3.12.7，不声称两个运行环境或两个JSON内容相同。

证据位于本机`state/veighna-qa/hf-package-verification.json`与`hf-20261126T080241/summary.json`。这证明新版研究界面已上线，**不证明私有Dataset上传／读取已接通，也不证明券商模拟订单已成交**。Cloud备用入口本轮未重新验收。
