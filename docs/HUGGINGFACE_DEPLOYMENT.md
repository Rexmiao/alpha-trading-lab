# Hugging Face Docker 发布准备

0.12.0盘前事件研究与双入口已发布并通过实际浏览器验收；0.12.1研究工作台界面已发布并通过公网验收（见下一节）。应用直达为[alphalab.levyquant.ai](https://alphalab.levyquant.ai/)，HF项目页为[Rexymiao/alpha-trading-lab](https://huggingface.co/spaces/Rexymiao/alpha-trading-lab)。它们显示同一套应用，不是两个独立部署。顶栏另有“Lévy Quant／Lévy Quant 主站”链接回总站[levyquant.ai](https://levyquant.ai/)。

## 0.12.1 研究工作台界面：实际发布与验收

只改呈现层，详见SPEC 0.12.1。发布包由31文件变为33文件，新增：

- `.streamlit/config.toml`：共享主题（浅／深）及原上传上限、统计关闭设置。Streamlit只从工作目录（容器内`/home/user/app`）读取`.streamlit/config.toml`，因此Dockerfile新增`COPY --chown=user:user .streamlit/config.toml ./.streamlit/config.toml`，`.dockerignore`放行`.streamlit/`及该文件；打包器只接受server／browser／theme三个TOML表。环境变量`STREAMLIT_SERVER_MAX_UPLOAD_SIZE=12`仍保留，与配置一致。
- `hf_space/ui_theme.py`：纯呈现模块（页首、专题目录、来源徽章、上次运行条及样式），不读数据、不联网。

工作流路径触发已加入`.streamlit/config.toml`。本机在非同步临时副本打包成功（33文件，含上述两个文件）。发布时仍按现有GitHub App提交、核对分支旧SHA、等待HF工作流，再以公网结果JSON核对运行时依赖与界面；发布后检查：首屏English与主题加载、中文切换保持专题、两个入口URL、盘前1.25%样例18／4／5、DIA覆盖不足显示、390px无横向溢出。

实际结果：发布提交`6f945ca7b54b67bdf3e147a8958fad12515915d9`（父`5e56e71`，正常快进）；[HF工作流46099673415](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/46099673415)成功；Space revision `cd62184c9e8c21d39da1eec3ed884e89027547f4`，RUNNING／CPU Basic。公网检查通过：English默认与新主题、两个入口URL、七个专题、1.25%样例18／4／5（DIA 236/250）、中英切换保持盘前页、390px无横向溢出、控制台无错误。DIA覆盖不足、错误状态与下载一致性以本机测试为准，未在公网重复。线上MANIFEST的32个源码条目与`6f945ca`逐文件SHA256一致。语言偏好重新打开测试3次中2次恢复中文、1次回到English且未复现，暂不记为完全验证。后续修正把首页AI卡的说明文字改为页内锚点链接（`#ai-study`），随下一次同步发布并另行公网核对。

## 0.12.0 盘前统计：实际发布与验收

2026-11-27，经现有GitHub App发布应用代码`9e6cbbb080a73b9de1580c12af07c887ec203c95`，并以`48f6ba03f508780520cbe7dfc99207a4997d21d2`补齐Docker构建上下文的显式允许文件。[最终同步工作流46065758842](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/46065758842)成功；HF仓库与runtime均为`25ebe7014fcc5f331aff99872183314812367394`，RUNNING，当前／请求硬件均CPU Basic。没有改变Space、付费配置或凭据范围。

入口为“Premarket & Opening Downside／盘前涨幅与开盘下探”。全局另有Launch Research Lab／进入研究平台及Hugging Face project／项目页两个链接，默认English，中文可切换。选择QQQ／SPY／DIA、自定义盘前涨幅（如1.25%）和观察口径，显式点击Compare historical events后查看n、最大下探分布、全部事件日、同覆盖基线与派生JSON。冻结范围2025-11-27至2026-11-26，不含今天，不是实时数据。

发布包为30份源码／派生资产加MANIFEST，共31文件；全部远端文件逐字与本机一致，MANIFEST逐项hash通过。唯一新增公开派生参考集SHA256为`1b93af7a00e7c241ca9e2c76a9ae6234475c77c12170ba2d2ca086ed6cee7b60`，750标的日，仅无量纲充分统计和净化指纹，不含分钟OHLCV、绝对价格、成交量、路径、游标或凭据。它作为公开文件可读取；原始行情和本机报告没有发布。

115项相关测试通过，随后新增Docker清单一致性用例，打包组3项通过（覆盖116个不同用例，未宣称全项目历史测试重跑）。本机同步盘metadata波动时，采用显式白名单复制到非同步临时stage，逐字复读核验后生成最终31文件包；GitHub Linux工作流又独立打包成功，没有移除稳定源校验。

公开应用实际浏览器验收通过：

- 新访客English、两个访问链接正确。
- 输入1.25%，QQQ／SPY／DIA事件数18／4／5，原生下载逐结构等于本机纯计算。
- 修改参数未提交不重算；切中文后原生JSON同字节，SHA256为`735b5a2b8a96a8403cbd3e8da53cbacef4dc3052b74aea5a286855b5f1cdff38`。
- DIA完整盘前无合格窗显示不可估计，并保留3个已观察部分窗口触发；不显示0%预测。
- 两次场景均通过390px无页面横溢出及JS异常0。

证据在ignored `state/hf-premarket-review/`：`reference-audit.json`、`hf-package-verification-final.json`、`public-custom-20261127T204637Z-f4b4f8/qa.json`和`public-dia-20261127T204637Z-a1b76d/qa.json`。部署、数据来源、计算一致性和预测用途分开；没有新增行情采集、券商连接、订单、后台任务或盈利声称。备用Cloud／Pages本轮未单独验收。

历史0.8.1进度（最新Beta见文末0.9.0）：Private Dataset已实际上传468行真实moomoo快照并核对hash，revision为`81acd7bef19dcfc890b71bc9a70ca7d5a7208c20`；用户完成Space独立读取配置后，新访客已读通并实际运行三种策略，来源／行数／hash／as_of全部一致，研究JSON可下载、无原始CSV下载。自动watch未启动。设置入口为[本Space的Settings](https://huggingface.co/spaces/Rexymiao/alpha-trading-lab/settings)，详细值见[操作说明](MOOMOO_CLOUD_SYNC.md)。历史0.8.0验收保留文末。[新鲜测试展示与命令](ACCEPTANCE_DEMO.md)

这是云端 Python 研究界面的发布说明。Hugging Face是主要交互入口，GitHub Pages保留静态教学页，Streamlit Cloud是可选备用。0.8.0新增私有快照读取，最新验收见文末；前面版本的记录属于历史里程碑。容器启动、页面交互和源码上传分别核对，应用本身不包含发布凭据。

## 本次个人部署目标

个人PRO账号：`Rexymiao`。公开Docker / CPU Basic Space：[Rexymiao/alpha-trading-lab](https://huggingface.co/spaces/Rexymiao/alpha-trading-lab)。用户已创建Space并将细粒度发布令牌保存为GitHub仓库Secret `HF_TOKEN`；代码和聊天均不保存令牌。

2026-11-26已完成实际发布与公网验收：

- [Space页面](https://huggingface.co/spaces/Rexymiao/alpha-trading-lab)；[应用直达](https://alphalab.levyquant.ai/)。
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

- 当前本地包必须恰好是22个允许文件（21源码及MANIFEST），路径、字节数与所有SHA256一致；符号链接、额外内容、缺失或变动中的包均拒绝。
- `whoami`确认个人身份与目标owner一致；目标必须已存在、为Docker且公开。
- 从Space资料和最新runtime核对硬件：所有明确值只能是`cpu-basic`，至少一项明确为`cpu-basic`。首次构建允许current未知但requested为basic；未设置requested时允许current为basic。两项仍全未知或任何一项是其他硬件均停止，不自动改设置。
- 远端文件只能是同一发布包的白名单文件或平台生成的`.gitattributes`；发现其他项目文件时停止，不删除或覆盖它们。
- 使用明确的22个`CommitOperationAdd`和已读取的`parent_commit`提交，不使用全目录上传、不删除远端文件。若远端有并发提交，停止并重新核对，不强制覆盖。

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

## 0.8.1 真实私有快照验收

应用源码`37e0304920eb1cd194250bab06d164c732888a40`，[同步工作流45886342499](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/45886342499)成功；HF仓库与runtime均为`33d83478f01e4cc5739fa7a3158b38304f27aab7`、RUNNING、CPU Basic。18源码一致，MANIFEST仅创建时点不同。

用户保存独立Dataset变量和只读Secret后，fresh访客实际从私有revision `81acd7bef19dcfc890b71bc9a70ca7d5a7208c20`取到468行／28908字节、截至2026-11-25T21:00:00Z的SPY／NVDA数据，SHA256与本机一致。source=moomoo_snapshot，没有教学回退，3个共同完整／可执行日、9条逐日结果，三规则均success。JSON原生下载并在英文切换后保持相同字节，SHA256为`7fb87ddb0fc521b29a25961458b893c0a544e9adb0aa6c3a7ba3311bd825002d`；无原始CSV下载。证据仅留本机`state/hf-real-qa/savedconfig-20261126T145207/`。

三日含成本总收益分别约−1.2467%（正动量）、−1.0642%（均线趋势）、−0.3407%（开盘区间突破）。这次用于链路与策略实现验证，短样本不展示夏普，不据此选最优策略或证明alpha。实际运行Python3.12.16／NumPy1.26.4／pandas2.2.2／Streamlit1.67.0／PyArrow25.0.1。真实行情研究、真实券商模拟成交及常驻同步是三种独立验收；后两项未完成，Cloud备用入口未重新验收。

## 0.9.0 Beta日频测量与五组对照

应用新增第四个独立页面「Beta测量与策略对照」，默认读取moomoo私有日K，也支持访客七列CSV。原AI、日频规则及5分钟页面保留；Beta研究没有接入账户或执行器。上传传输上限提高为12MiB以容纳Beta输入，各原页面的更小解析限制保留。Docker包为22文件（21源码＋MANIFEST），增加beta.py、beta_ui.py、daily_snapshot_source.py；本机准备／发布脚本不进入HF包。

真实采集46个成功响应、0错误。规范化43907行、45只主题股加SPY、1000个基准交易日，2022-12-01至2026-11-25；最后交易日为11月25日，11月26日美股假日。身份起点已应用，2093个股票缺行保留；27个超过30%的日变动保留告警。口径为moomoo前复权provider_daily价格收益，未验证为RTH原价或总收益，当前主题池并非历史完整可投资池。

日K单独发布到同一Private Dataset的daily/命名空间，revision为`3b4a403d9696cb2e690b3e2f9b39c8e7cd2c437b`。CSV为3186590字节，SHA256 `ceeb074914341a862c5c640f8d0ef8a3a9678a5ca98d1b17211f2e510a21f9bf`，as_of `2026-11-25T21:00:00Z`；实际上传后重新下载核对成功，旧5分钟latest指针字节未变。沿用现有Space独立只读Secret，不使用部署HF_TOKEN或券商凭据。没有启动自动采集／上传任务。

本地真实五组回测全部success：默认126日估计窗、252日评估（2025-11-25至2026-11-25），初始资本100000，单边10bps，股票篮子80%目标／20%现金、单股上限20%，整数股、月末信号下一开盘。默认13次目标形成均45只合格股；首日使用此前已知收盘初始化，之后按真实交易所月末。以下是该固定数据的研究结果，非券商成交或未来收益证明：

| 组合 | 含成本总收益 | 最大回撤 | 年化波动 | 实现Beta | 模拟成本 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 高Beta | 15.70% | -51.23% | 59.22% | 2.740 | 864.71 |
| 低Beta | 25.60% | -5.30% | 9.06% | 0.251 | 217.20 |
| 全池等权 | 34.32% | -27.73% | 31.91% | 1.712 | 233.89 |
| 80% SPY＋现金 | 6.65% | -9.17% | 11.84% | 0.794 | 84.42 |
| 100% SPY | 8.24% | -11.46% | 14.92% | 1.000 | 99.89 |

实现Beta使用251个净账户收盘至收盘收益，首个开盘至收盘片段不参与回归；收益本身包含该首日。SPY100实现Beta约0.999865，整数股与费用使其略偏离1。不是Jensen alpha；现金收益为0，未模拟盘口、冲击或供方数据交付延迟。

252日估计窗口独立敏感性运行也五组成功；初始43只、随后44／45只合格，不根据未来资格做统一交集。该窗高Beta／低Beta／等权总收益约8.11%／19.81%／30.49%，两SPY基准相同。两个窗口未按测试收益择优；没有匹配波动、行业归因、Beta-cap或BAB。软件修复了轮换调仓后零持仓残留被误要求提供价格的问题，回归测试覆盖三次不相交选股；真实持仓缺价仍明确失败。

应用源码`99cdb7236dd3b83cb3d398f374e2285bedfb441a`，[同步工作流45937075386](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/45937075386)成功；HF仓库与runtime均为`edf0847ef2951d2d26c19b8bdcf52d713d958921`，RUNNING、CPU Basic。21源码逐字节／SHA256相同；MANIFEST只有created_at不同，其余语义一致。新访客从私有日Krevision `3b4a403d9696cb2e690b3e2f9b39c8e7cd2c437b`读取43907行并完成默认五组；四张图实际渲染（净值／回撤／事前Beta各5条曲线，另有个股散点）。原生研究JSON下载成功，英文切换后保持相同字节，SHA256 `cb1359de94ed091b3568940fc01cbf042f649a3a6b9a400d91b7c38a553ba2d9`；没有原始行情下载。390px手机视口关闭侧栏后，6条短公式均在视口内、无页面横溢，JS异常0。本机与HF使用相同数值库版本；Windows／Linux少数回归统计有浮点尾数差异，最大约3.33e-16，均满足绝对／相对1e-12容差，不声称跨系统JSON完全相同。证据保留本机`state/beta-qa/hf-20261126T230258/summary.json`及`state/beta-qa/hf-package-verification.json`。

本轮研究相关345项Python测试通过，0失败／0跳过；其中Beta核心29、Beta UI 7、日K读取／发布60项为新增，原AI／规则／分钟／快照与数据／持仓测试同时回归。另有旧测试注入非法字段触发1个pandas FutureWarning，不影响断言。没有将此前执行器测试重新计为本轮已跑。备用Streamlit Cloud源码随同一GitHub仓库更新，但本轮未重新验收该备用站点。

## 0.10.0 支撑／阻力三规则与主内容导航

新增独立`hf_space/support_resistance.py`与`support_resistance_ui.py`，三策略为support_bounce、resistance_breakout、breakout_retest，第四组为同评估日的SPY RTH日内持有。价位仅取紧邻前一完整XNYS RTH高低，固定bps区域；不借未来pivot、不从同根OHLC推断突破回踩顺序。下一开盘／额外延迟、目标替代、收盘失效退出和日末预定清仓见[实施规格](../specs/SUPPORT_RESISTANCE.md)。原AI、日频动量、5分钟规则、Beta引擎均保留。

按用户界面反馈，中英文切换与五页研究导航移到主内容顶部；数据与运行留在可折叠侧栏，AI和新S&R的低频参数收进高级设置。换语言、页面或参数不重算旧结果；只点击运行才计算。新增区域／收盘／事件图和8条短数学式。JSON不提供完整OHLCV，也从逐bar信号中移除signal_close，避免直接重建全历史原始收盘序列；保留稀疏确认／成交参考价用于审计。图上的选定收盘路径来自服务端会话，原始CSV无下载入口。

真实行情已只读补取SPY／NVDA共10个完整日（2026-11-12至25），1560行／96516字节，未复权rehab0。CSV SHA256 `8a397cb2616b66c57c143dcdf34936231b4d0e7ffd30dedb8d2aaf285c51631e`，as_of `2026-11-25T21:00:00Z`。与旧快照重叠468行数值全同；时间口径沿用已验证CLI的bar-end减5分钟规则，没有重新对全部10日作1分钟聚合或独立第三方价格验证。实际私有上传及重读成功，Dataset revision `1166944d51191723e2b4f3ce428cb3f818cb1bd1`，daily/latest.json字节未变。

默认首日预热、9日评估（2026-11-13至25），资本100000，区域半宽10bps／缓冲0、确认期限12根，下一开盘零额外延迟，单边费用10＋半点差1＋滑点1bps。NVDA为唯一可交易股，20%上限使股票目标最多20%、现金至少80%；SPY基准近100%日内暴露，不能称为匹配风险的alpha比较。实际结果：

| 组别 | 含成本总收益 | 最大回撤 | 成交笔数 | 总成本（美元） |
| --- | ---: | ---: | ---: | ---: |
| 支撑反弹 | -0.6615% | -0.7617% | 6 | 141.85 |
| 阻力突破 | 0.2785% | -0.8820% | 4 | 95.83 |
| 突破后回踩 | 0.0000% | 0.0000% | 0 | 0.00 |
| SPY同日日内基准 | -9.1478% | -11.6834% | 18 | 2015.60 |

支撑反弹3次入场、阻力突破2次；回踩虽有等待事件，但没有满足完整确认的入场，0交易保持现金是实际结果，没有调参制造交易。18个冻结价位、2808条权益观测。所有逐笔费用、最终净盈亏和逐日空仓已对账；少于20个评估日不报告夏普或年化指标。没有盘中止损／OCO、券商下单或后台任务。

预先定义的额外等待一根5分钟对照也完成：支撑反弹−0.8845%、突破+0.7602%、回踩0；突破由4笔变2笔，因一项延迟入场已被后来已知的失效目标替代。该对照解释延迟和取消政策，不用于挑选收益较高的默认值。

0.10.0实际公网验收：应用源码`815ccdf0b6f9214118201b76076a8a165de9c95c`，[工作流45948835366](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/45948835366)成功；HF仓库／runtime均为`323bf775ed0480a29cd48816ba58a2b909260422`，RUNNING、CPU Basic，23源码逐字节相同，MANIFEST仅created_at不同。新访客独立读取相同私有10日快照，三策略及基准均成功；中英原生JSON下载字节相同，SHA256 `ed99dab6c8f126b528eedb509c35cbaa23997f57e3d48ab24b24c847119ce026`。无原始CSV下载、逐bar信号无signal_close；三图、390px主内容导航和8条短数学式实测通过，JS异常0。408项相关测试通过，其中S&R54、UI7、全局导航2项为新增；旧注入非法字段用例有一个pandas FutureWarning。本机与HF指标满足1e-12容差，HF Python3.12.16、本机3.12.7，不称跨OS完全相同。证据保存在本机state/sr-qa；Cloud备用本轮未重新验收。

## 0.11.0 期权结构研究

新增主内容第六个入口：真实数据可得性审计、GEX库存情景、独立Max Pain计算器与前瞻实验设计。当前真实库存不可识别，历史增量预测不可估计（有效样本0）；两类计算器仅由明确按钮运行虚构TOY数据，不自动取得真实期权链。源码／数学测试与公网验收分别记录，实际记录见下文。原始PCR存档、OI链、凭据和账户均不进入发布包。

### 0.11.0 已验证的发布与真实S&R

应用提交`9d208a85e656eb6f04bc338129b4b38b836e25cd`，HF工作流[45954780844](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/45954780844)及Pages工作流[45954780980](https://github.com/Rexmiao/alpha-trading-lab/actions/runs/45954780980)均成功。HF仓库／runtime同为`2daea2aeab31b573999c73160daaa9c253a4cce0`，RUNNING、CPU Basic；26源码逐字节一致，MANIFEST仅created_at不同。包为27文件；HF另有1519字节`.gitattributes`纯LFS仓库元数据，单独校验，不混入应用包计数。

实际新访客从English首页进入S&R，再显式切中文，用相同Private Dataset revision`1166944d51191723e2b4f3ce428cb3f818cb1bd1`及1560行、CSV SHA256`8a397cb2616b66c57c143dcdf34936231b4d0e7ffd30dedb8d2aaf285c51631e`跑出9日／四组结果。中英原生研究JSON字节相同，SHA256`1c27710a1867eb0f0061011b5ff2a0083bb3505d7d9b8c5e784c2e2025e64c8f`；与当前本机代码指标符合1e-12容差，无原始行情下载、无JS异常，390px导航与数学式通过。证据位于本机`state/sr-qa/sr011-20261127T020521/summary.json`；源包证据为`state/options-research/qa/hf-package-verification.json`。

GitHub Pages已实测全新English／英文媒体→中文／中文媒体→刷新仍中文→英文；第二新浏览器仍默认English。Community Cloud已实测English首页、六研究入口与双语切换保持S&R选择，本轮只验收语言／导航，没有在备用Cloud运行价格或模型。证据为`state/options-research/qa/hosteddefaultsbootstrap-20261127T070616634219Z/summary.json`。原有完整Cloud功能验收仍属历史记录，不与本轮新增期权／私有数据验收混为一谈。

522项完整优化后研究测试通过；随后English默认及首页文案变更的4项导航复测通过。新GEX48项、Max Pain53项、期权UI9项；这些验证数学／界面契约，不产生真实期权库存或样本外预测成绩。本机冷首屏各3次新进程的中位10.058→6.627秒，测量对应延迟依赖加载版本，之后另改了语言／首页文字；不能外推公网耗时。S&R真实1560行暖运行610.57→326.40ms（延迟0），Max Pain虚构5000合约计算＋62点曲线4.542→0.201秒；精确结果与最小集合保持。今后的性能增量仅在用户明确请求时集中执行。

### 期权页实际公网验收

同一HF版本的新访客已完成English首页→中文期权页→明确TOY GEX／Max Pain计算→English切换、原生下载、参数不重算与跨页保留。37条浏览器事件、130项检查全部通过，JS异常0；390px六入口与GEX2条／Max Pain3条短数学式通过。GEX原生JSON SHA256`84b4c55a00861d13135d8c75d333baaf2cafa4a988ee97421c0f99eb8d175b87`，Max Pain为`97474b1c48da5ce36e625ca1f74355488f64f8b3df3aa8afc21c09b04806f7f6`；中英下载各自同字节。

原生报告明确synthetic_demo／TOY；SPY438、QQQ514和未知OI时点只作真实固定审计，没有拿来生成行情曲线。现价变化后的Max Pain最小集合仍为冻结OI对应区间，距离另报；无原始行情／账户／下单入口。证据：`state/options-research/qa/hflive-20261127T020931/summary.json`及同目录browser-event-proof／events／checks／原生downloads。先前失败只涉及QA前端选择器假设，均保留失败证明，未据此改生产数学或冒称通过。真实做市商库存仍不可识别，历史增量预测有效样本仍为0。

### 旧Sites教学地址的独立更新

[原教学站](https://alpha-training-lab-guide.totalbluebell3.chatgpt.site/)保留原网址与PUBLIC访问范围，已单独发布版本3；源提交`156002b064b10f1eb3b15dbc8f82708f95d5d5a3`，部署`appgdep_6b092d8799f081918c9e501f4c0f2559`为SUCCEEDED。全新公网浏览器已核English首访、中文切换／刷新保留、双语GIF／封面／下载、EWMA／成本／阶段交互及390px布局；无runtime错误。这个版本独立于GitHub Pages的发布，证据已归档为本机`state/options-research/qa/legacy-site-defaults.json`，不将站点凭据放入源码。

发布收尾核对到并行界面增量a17603bfc459824c945fe2de002d75022468d1ec：浏览器保存手动语言选择，新访客仍默认English。已保留该提交，并核定本机主程序与发布版仅一处空行差异；现在已对齐发布版，原工作区快照保留。新增界面以6项导航增量测试及实际浏览器偏好刷新另验；原522项核心研究结果按未改变的计算源码指纹保留，不能宣称完整524项全部重跑。云端源码仍须固定revision逐字验证，Cloud只记录已实际观察的界面行为。

追加界面偏好版本已复验：发布提交a17603bfc459824c945fe2de002d75022468d1ec、HF工作流45956854531成功，当前HF仓库／runtime为c5f954328abb4af42e9bac36dfe3f69dd132d772，RUNNING／CPU Basic。26源码与新本机包逐字一致，MANIFEST仅created_at不同，纯LFS元数据单独核对。主程序SHA256为4d571abd4a3c8133786091297d459ffe3bea9dba7b2be1cfed19dc7be250dbb4。原9d208／2daea记录保留为核心研究功能验收基线；S&R／GEX／Max Pain计算及其独立UI源码未变，新增偏好另经6项导航和实际浏览器English→中文→document刷新保留中文→English→刷新保留English验收，无连续重跑或Run／取数动作。证据为state/options-research/qa/language-persistence-a176-browser-20261127T024037及当前hf-package-verification.json。
