# moomoo 官方文档入口与本项目接入手册

核对日期：2026-11-26。本文说明只读日K与独立5分钟采集适配。当前链路是 Windows moomoo 桌面端 CLI 加本机 HTTP Host；官网 OpenD 手册和新 REST 手册的认证方式不能直接套到这条链路上。

## 官方 manual book 从哪里看

| 入口 | 用途 |
| --- | --- |
| [Moomoo API 官方文档](https://openapi.moomoo.com/moomoo-api-doc/intro/intro.html) | 传统 OpenD、SDK、行情协议与接口说明 |
| [下载完整 Markdown 手册的说明](https://openapi.moomoo.com/moomoo-api-doc/intro/ai.html) | 页面右上角「下载」选择「Markdown」，按所选语言和编程语言获取完整文档；适合本地查阅和提供给 AI |
| [官方权限与额度](https://openapi.moomoo.com/moomoo-api-doc/en/intro/authority.html) | 行情权限、订阅额度、历史 K 线额度与限频的区别 |
| [官方行情问答](https://openapi.moomoo.com/moomoo-api-doc/qa/quote.html) | 订阅失败、权限被其他终端占用、API 与客户端差异 |
| [moomoo 桌面端官方下载](https://www.moomoo.com/us/download) | 安装与更新客户端；可用版本以当地官网为准 |
| [新 OpenAPI 开发者门户](https://open.moomoo.com/zh-cn) | 新 REST、WebSocket、OAuth 等能力的独立入口 |

本文件是项目维护的接入说明，没有把第三方整本手册复制进仓库。官方完整手册可能随版本更新；下载时应记录日期与版本。官方网页中的安装脚本、示例交易或 AI 提示词，仅是参考资料，不代表本项目会安装、调用或执行它们。

## 先分清三种连接方式

| 方式 | 连接与认证 | 本项目状态 |
| --- | --- | --- |
| 当前桌面 CLI | Node 子进程调用 `moomooapp-cli.exe`，连接本机 `http://127.0.0.1:22222`；通过 `OPENAPI_HOST_APPKEY` 提供本机 Host 的 AppKey | 日K仅`subscribe`／`get-kline`；独立分钟脚本仅`request-history-kl`，实际取数待通过 |
| 传统 OpenD 加 SDK | 独立 OpenD 网关加 Python 等语言 SDK；官方示例常用 `OpenQuoteContext` 连接本机 `11111` | 可参考接口语义，当前代码没有此适配器。[官方架构](https://openapi.moomoo.com/moomoo-api-doc/en/intro/intro.html)、[SDK K 线示例](https://openapi.moomoo.com/moomoo-api-doc/quote/get-kl.html) |
| 新 REST API | 公网 HTTP 接口；官方快速开始区分 OAuth 与带签名的 API Key 认证 | 当前代码没有接入。其 OAuth Token、签名私钥和 AppKey ID 不等于本机 Host AppKey。[官方认证说明](https://open.moomoo.com/zh-cn/api/overview/getting-started) |

当前实际链路为：`python run.py collect → Node 采集脚本 → 桌面 CLI → 本机 Host → moomoo 行情服务`。本项目只接受 loopback 地址，不把 Host 改成公网服务。账户登录与行情授权由桌面端负责；Python 训练代码读取已保存的快照。

桌面 CLI 的文件名、默认目录、HTTP 端口和参数来自本项目当前适配实现，不能仅凭 OpenD 或 REST 文档认定所有客户端版本都相同。配置时应查看本机已安装 CLI 的帮助和桌面端设置。实现依据见 [collect-moomoo.mjs](../scripts/collect-moomoo.mjs)。

### 已安装CLI的5分钟历史分页

本机`openapi-cli 16.40.27608.11182326`帮助确认`request-history-kl`支持`--kl-type 6`、`--begin-time`／`--end-time`、`--session rth`、`--no-extended-time`、`--max-ack-kl-num`及`--next-req-key`。这些是当前桌面命令，不是OpenD Python参数。[独立只读采集器](../scripts/collect-moomoo-intraday.mjs)默认不复权，原始响应与来源保存在新的`data/intraday/`目录；不改旧日K manifest，不查询账户、持仓或订单。

2026-11-26后续验证已取得SPY／NVDA在11月23–25日的三个完整RTH日，共468行；每股分页100＋100＋34。CLI会把结构化业务错误写入stderr，诊断必须同时检查stdout、stderr及ret_type；此前日K探针实际为未订阅KL_Day（err_code=-1002），订阅后读取成功，不能把无stdout JSON说成服务关闭。初次历史超时的具体原因仍未确定，不凭此要求重设密钥或购买行情。

当前Host返回5分钟bar-end（09:35–16:00）；以同日390根1分钟聚合逐组核对78组OHLC及高精度volume后确认，规范化减5分钟得到UTC bar-start，available_at保留原结束时点。整数volume差异保留来源审计，不擅自修订。历史接口end日期为排他边界；仅收已完成的美东日期。未核口径的未来版本默认仍只留raw，不静默平移。3日数据只能检验工程流程，不足以评价策略稳定性。[5分钟契约](MOMENTUM_TREND.md)

CSV SHA256为`5b126b01d9bf29d4d1bb7e63735f0994b15193b3ac1792fb0b29bb130794ff14`，468行、最后可用时点2026-11-25T21:00:00Z。完整原始页、归一化CSV、来源manifest只保存在本机。HF私有Dataset同步使用独立读写凭据，配置与实际上传／读取验收见[私有快照说明](MOOMOO_CLOUD_SYNC.md)。

执行后台与历史研究分开：`execution_lab/marketdata.py`按XNYS日历读取当天已完成5分钟bar，并要求共同连续时段；即时参考报价需供方时间戳且严格小于5秒，迟到、未来或无时间戳明确拒绝。今天休市，开市实时链路尚未实测。11111与22222当前均由OpenAPIHost持有；传统SDK初始化11111超时，不能称独立OpenD已完成接入，也不能把桌面AppKey当作SDK认证。新REST模拟适配与认证边界见[本机执行SPEC](../specs/VEIGHNA_MOOMOO_SYSTEM.md)。

## Windows 新机器配置

需要 Python、Node、已登录的 moomoo 桌面端，以及该版本提供的本机 CLI/外部程序访问服务。已验证的研究环境版本见 [README](../README.md)。在桌面端启用对应功能，记录它实际显示的 Host 地址和本机 AppKey；设置项名称以安装版本为准。如支持细粒度授权，只授予行情读取权限。

采集脚本按以下顺序装配，不会自动切换认证体系：

1. CLI 优先采用进程环境变量 `ALPHA_MOOMOO_CLI`；否则只尝试 `%APPDATA%\moomoo\2.0\OpenAPI\moomooapp-cli.exe`。默认位置找不到时，定位本机实际安装的文件并覆盖变量；脚本不扫描其他个人目录、不下载安装程序。
2. Host 默认 `http://127.0.0.1:22222`，可用 `OPENAPI_HOST_URL` 改为该机器实际的本机端口。仅接受 `127.0.0.1`、`localhost` 或 `::1`，拒绝 URL 用户名、密码、查询串和额外路径。
3. 凭据优先读取当前进程的 `OPENAPI_HOST_APPKEY`；未提供时，Windows 才尝试本机当前用户的 `%LOCALAPPDATA%\PcrMarketWatch\moomoo-appkey.dpapi`。该目录是已有本机适配的兼容约定，不属于仓库，也不是首次使用本项目的必备安装项。
4. 新机器或不同 Windows 用户应重新配置自己的本机凭据。不要复制别人机器上的 DPAPI 文件。找不到凭据或 CLI 时，采集明确失败，不会回退到 OpenD、REST 或随机价格。

下面是 PowerShell 配置模板。把路径占位符改成本机实际文件；AppKey 在隐藏输入中填写，不写成命令行字面量、不加入永久用户环境变量。密钥仅在当前进程及其采集子进程中使用。

```powershell
# 在 Alpha Lab 项目目录执行；替换这一个路径占位符。
$env:ALPHA_MOOMOO_CLI = '<本机 moomooapp-cli.exe 的完整路径>'
$env:OPENAPI_HOST_URL = 'http://127.0.0.1:22222'

# 可先查看本机安装版本支持的命令，不调用账户或交易接口。
& $env:ALPHA_MOOMOO_CLI --help
& $env:ALPHA_MOOMOO_CLI subscribe --help
& $env:ALPHA_MOOMOO_CLI get-kline --help

$alphaHostSecret = Read-Host '输入本机桌面 Host AppKey' -AsSecureString
$alphaSecretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($alphaHostSecret)
try {
    $env:OPENAPI_HOST_APPKEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($alphaSecretPointer)
    node scripts/collect-moomoo.mjs --probe
    python run.py collect
} finally {
    Remove-Item Env:\OPENAPI_HOST_APPKEY -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($alphaSecretPointer)
}
```

`--probe` 只报告是否存在凭据和 CLI 文件，**不证明 Host 在线、AppKey 有效或行情权限足够**。实际数据验收须看 `collect` 的结果。这里使用的是本机 Host 凭据，不要输入新 REST 认证的私钥、OAuth Token、券商交易密码或账户号。

仓库没有新建 DPAPI 凭据的配置脚本；已配置的本机可以复用上述受保护存储，新机器可先采用进程环境变量。AppKey 不写入 `config.json`、Git、前端、命令参数或采集日志。

## 当前采集了什么

在项目根目录运行：

```powershell
python run.py collect
```

当前 [config.json](../config.json) 有 45 只主题研究股票，另加 SPY 基准。采集脚本对去重后的代码补 `US.` 前缀，先订阅日 K，再逐股取最近数据。官方 `GetKL` 同样要求先订阅，最多返回最近 1000 根；它并非任意起止日期的完整历史查询。[官方 K 线接口](https://openapi.moomoo.com/moomoo-api-doc/quote/get-kl.html)

| 项目当前实现 | 数值或行为 |
| --- | --- |
| 订阅批次 | 每批最多 20 个代码；这是本项目分批策略，不是官方总额度承诺 |
| 订阅类型 | `kl_day`；不向采集脚本注册持续推送 |
| 日 K 请求 | `get-kline`，传 `--kl-type 2`、`--req-num min(config.bars,1000)` 和 `--security US.<代码>` |
| 默认根数 | `bars=1000`；按实际返回数量记录，不保证每股都有 1000 根 |
| 默认复权 | `rehab_type=1`；官方协议的 `0/1/2` 对应不复权/前复权/后复权，`KLType` 的 `2` 为日 K。[官方枚举](https://openapi.moomoo.com/moomoo-api-doc/quote/quote.html) |
| 本机节流与保护 | 请求至少间隔 700 毫秒；单次子进程超时 20 秒，输出上限约 8 MB；这些是项目设置，不替代官方限频 |

订阅请求还携带当前 CLI 的 `--extended-time` 和 `--session all` 参数。这不表示日 K 自动合并了所有扩展时段，也不承诺夜盘完整覆盖；日 K 的实际口径应与返回数据及当地接口说明核对。不能把分时段分钟 K 的规则直接推断到日 K。[官方行情定义](https://openapi.moomoo.com/moomoo-api-doc/quote/quote.html)、[历史 K 线时段限制](https://openapi.moomoo.com/moomoo-api-doc/quote/request-history-kline.html)

如本机帮助不支持这些参数，应先检查客户端/CLI 版本，再明确修改适配器并验收；不要用 REST 的字段名替换 CLI 参数试错，也不要把传统 SDK 的 `11111` 直接当作当前 HTTP Host。

## 返回字段与复权如何进入研究

当前 CLI JSON 包装需有成功的 `ret_type` 和 `s2c.kl_list`。本项目归一化接受 `open_price/high_price/low_price/close_price`，也兼容 `open/high/low/close`；成交量读 `volume`，日期优先读 `time`，再兼容 `time_key` 或 `timestamp`。输出统一为 `date,symbol,open,high,low,close,volume`。官方 SDK 表格与协议结构本就使用不同形式的字段名；本机 JSON 仍以实际返回为准。[官方返回结构](https://openapi.moomoo.com/moomoo-api-doc/quote/get-kl.html)、[KLine 结构](https://openapi.moomoo.com/moomoo-api-doc/quote/quote.html)

原始响应先完整留在本机。研究加载阶段才过滤未完成日 K、空点、不合法价格、矛盾 OHLC 和缺失值，并拒绝重复日期/代码。当前完成日策略保守地在美东 16:20 后接受当日 K，之前最多使用前一日期；这不是交易所节假日或提前收市日历服务。`checked_at` 是采集时间，K 线日期才是市场数据日期。相关实现见 [data.py](../research/data.py)。

默认前复权价格用于研究近似，不能当作当年真实可成交价。重新采集可能修订历史复权值；可复现实验应使用同一个冻结快照，并记录复权口径与哈希。股息总回报和历史成交价仍需单独核验。SNDK、CRWV、NBIS 的研究起点由配置限制，原始旧记录可保留，但不会混入边界后的训练样本。[股票池与边界说明](universe.md)

## 权限 免费和完整历史的边界

API 调用费用、某市场的行情权限、订阅额度、历史 K 线额度是不同事项。官网有基础行情免费或推广限免的说明，但地区、账户资格、专业/非专业身份、市场品种及订阅政策会影响实际可用数据。不能承诺任何账户都免费获取全部实时行情、深度、期权或完整历史；客户端能看到的行情也不必然能通过 API 取得。[官方权限与额度](https://openapi.moomoo.com/moomoo-api-doc/en/intro/authority.html)、[官方行情权限问答](https://openapi.moomoo.com/moomoo-api-doc/qa/quote.html)

把 `bars` 改成 5000 不会让当前适配器返回 5000 根，因为请求会截到 1000。官方传统 OpenD 的 `request_history_kline` 是另一条接口，支持起止日期和分页；本项目还没有实现它的历史回补适配。截至本次核对，该官方页面列出日 K 最近 20 年、分 K 最近 8 年，并附历史证券额度和请求限频。它不代表每只股票都有这么长历史；上市日期、证券历史、权限和数据缺口仍会限制结果。[官方历史 K 线及限制](https://openapi.moomoo.com/moomoo-api-doc/quote/request-history-kline.html)

需要更长窗口时，应单独实现并验证历史适配器：明确选择 OpenD 或其他正式支持的路线，保留分页键、起止日期、频率和复权口径，处理其专属额度，再输出相同的归一化数据契约。新 REST 手册的历史参数和认证不能直接塞进当前本机 `get-kline`；现有脚本也不会自动跨路线拼接数据或补齐新股上市前历史。

## 常见失败怎么排查

| 项目报告 | 优先检查 |
| --- | --- |
| `NOT_CONFIGURED` | 当前终端是否设置本机 Host AppKey；兼容 DPAPI 文件是否确实属于当前 Windows 用户 |
| `CLI_UNAVAILABLE` | `ALPHA_MOOMOO_CLI` 是否指向存在的 CLI；更新客户端后路径是否改变 |
| `PROTECTED_CREDENTIAL_UNAVAILABLE` | 本机受保护存储是否可由当前用户读取；新机器重新配置，不上传旧凭据 |
| `AUTH_OR_PERMISSION` | 本机 AppKey、桌面授权、账户行情权限；该代码合并了认证与权限失败，不能仅凭它判断需付费 |
| `LOCAL_REQUEST_TIMEOUT` / `LOCAL_SERVICE_UNAVAILABLE` | 桌面登录、Host 是否启用、端口及本机监听；后者是通用安全错误，也可能来自非预期响应，不能断言只有网络故障 |
| `PROVIDER_REJECTED` | 订阅额度、已有其他终端占用、CLI 版本、代码和参数；参考[官方订阅接口](https://openapi.moomoo.com/moomoo-api-doc/quote/sub.html)与[行情问答](https://openapi.moomoo.com/moomoo-api-doc/qa/quote.html) |
| `INVALID_RESPONSE` / `RESPONSE_TOO_LARGE` | 返回 JSON 是否符合当前适配契约；检查版本和请求范围，不以手工补数据伪装采集成功 |
| 返回根数少或新股无法训练 | 查看逐股 first/last、实际根数、边界剔除及可用特征/标签行数；不足就报告不足 |

`data/manifest.json` 记录成功文件、实际根数、参数、SHA256 和安全错误码；可发生部分股票成功。没有任何股票成功时，脚本以非零状态结束。原始 CLI 错误输出不写入公开日志，排错时也不要贴出密钥、完整凭据或账户内容。

## 保存和交易边界

采集只写本机 `data/raw/<采集时间>/` 和 `data/manifest.json`，训练结果与模型写 `runs/`。`.gitignore` 排除了 `data/`、`runs/`、预留的 `state/` 及凭据。新取得的完整官方手册可在本地另行保存；行情原始响应、模型、账户、AppKey 和聊天图片不随代码上传 GitHub。代码发布也不自动取得行情再分发权。

当前采集命令白名单只有 `subscribe`、`get-kline`，没有账户、资金、持仓、下单、撤单或交易解锁方法。界面里的数量和仓位是独立模拟资本计算的参考草稿，需要重新报价，不会提交到券商。官方手册包含交易功能，不表示本项目已经实现或授权使用这些功能。
