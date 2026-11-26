# 模拟账户API接入入口

更新2026-11-26。桌面moomoo已登录并能读行情；这不自动提供新REST模拟交易认证。当前本机执行器无已配置的paper账户，实际委托和成交均为0。HF令牌只用于研究数据，不用于券商接口。

## 当前授权页已经确认的情况

用户本次截图已确认：AppKey表单的授权账户选择只列出实盘现金／保证金账户，没有模拟账户。本页不记录任何账户号或尾号。**AppKey能够绑定paper-only账户尚未证实，REST后端保持NOT_CONFIGURED。** 用户只授权模拟接入，没有授权选择、读取实盘资产／持仓／订单或执行实盘写入；不能拿实盘账户替代模拟账户来完成表单。

匿名静态审计已核到正常前端流程的限制：AppKey与OAuth都将`trade:read`和`trade:write`列为需要账户的权限。服务端返回的可选账户列表为空时，两项交易权限被禁用；列表非空、选了任一交易权限却没有选账户时，正常提交处理会提示先选择授权交易账户并返回。仅行情权限的前端流程允许账户留空，但**没有实际创建、批准或调用过这种凭据**，不能推断服务器一定接受，更不能认定它能调用模拟API。现阶段不勾选实盘账户、不创建宽授权Key、不安装或登录默认宽scope的新CLI。

[官方认证说明](https://open.moomoo.com/zh-cn/api/overview/getting-started)公开了AppKey／签名及OAuth scope，但没有充分说明本次表单的实盘账户绑定与独立模拟业务账户之间的关系。[2026-10-27更新日志](https://open.moomoo.com/zh-cn/changelog)说明模拟交易使用交易读写权限，因此不能假定行情权限就能进行paper查询，也不能把交易权限本身称为paper-only权限。

### 公开前端与MCP审计的证据边界

上述限制来自2026-11-26匿名读取的[官方公开前端脚本](https://open.moomoo.com/assets/chunks/theme.DJor68Up.js)，SHA256为`dc05f718ff065b516ffe5cfc1d988b183faa07312a28d33067813139e991885a`。AppKey的正常提交处理为`N()`，OAuth为`wg()`；两者都检查空账户选择，交易权限流程还可能进入所选券商的交易密码验证。没有进入用户登录会话、填写交易密码、创建AppKey／OAuth Client或批准授权，结论是**前端静态约束，不是服务端认证实测**。网页升级后需重新核对，不能修改页面或请求字段绕过限制。

前端账户选择使用`univsAccountId`；OAuth交易选项还检查服务端提供的`accid:*`范围。模拟账户接口则按当前登录用户取得独立的`account_id`。公开脚本没有证明这两类ID可以互换，也没有证明授权账户列表会提供paper-only条目。当前四项通用scope中未见单独的paper／sim权限；这不等于服务端绝无其他正式方案，仍需官方明确。

[官方MCP公开工具目录](https://open.moomoo.com/api/biz/mcp/tools)在本次匿名读取中列出8项`sim_trade_*`工具，包括模拟账户列表、资金、持仓、下单、改单及撤单，并映射到`/api/v1.0/sim-trade/...`。下单说明返回`order_id`且非幂等，描述的是服务器模拟业务，不是只有本地预览；但目录没有scope／security说明，**工具存在不证明quote-only凭据可调用**。[MCP认证说明](https://open.moomoo.com/mcp-docs/authentication)只列四项通用scope，[工具使用说明](https://open.moomoo.com/mcp-docs/available-tools)仍将账户查询与交易读权限、交易操作与交易写权限及交易密码关联。

公开脚本的翻译编号`387822`包含未授交易权限时MCP走模拟盘的旧文案，但本次只找到中／英／繁翻译字典中的三处记录，未找到直接渲染引用。不能据此声称当前授权页提供有效fallback，也不能将MCP工具说明替代REST权限验证。scope变更日期为**2026-10-27**；11月9日条目是另一轮参数、市场与返回结构对齐。

本机已准备签名材料，目录为`C:\Users\Rexy\Documents\ChatGPT\量化准备\alpha-paper-runtime\rest-paper`：公钥`ed25519-public.pem`、私钥`ed25519-private.pem`、占位配置`config.example.json`。仅当前Windows用户和SYSTEM有访问权限；官方AppKey路线使用公钥，当前适配器支持Ed25519／RSA-SHA256，不上传私钥。若后续确认可用的模拟授权路线，名称示例用`alpha_trading_lab_paper`：本次表单要求字母开头，之后只允许字母、数字、下划线，不使用连字符。名称只作标识，不会缩小服务端权限；`authorization_confirmed`继续保持false。

## APP初始化与本机只读发现结果

用户已进入**US Margin Paper**界面并看到虚拟资金，APP模拟账户初始化已确认，不需要重复初始化。APP账户存在与API能否返回可绑定paper ID是两个不同验收点。[官方客户端入口](https://openapi.moomoo.com/moomoo-api-doc/en/qa/trade.html#q1-how-to-use-paper-trading)

随后完成3次有界桌面Host元信息GET，仅保留安全聚合，不记录账户号、卡号或完整REAL账户行：

| 次数 | 可采用的结论 |
| --- | --- |
| 第1次 | 过滤器错误假定环境为数值枚举，且原始响应已丢弃；该次结果不能用于判断是否存在模拟账户。 |
| 第2次 | 实际schema为snake_case，`trd_env`是字符串；返回1条`REAL`、市场列表含`US`，没有`SIMULATE`条目。 |
| 第3次 | 在相同证券`category=1`范围明确加`need-general-sec-account`后，仍返回1条`REAL／US`，没有`SIMULATE`条目。 |

结论是**桌面通信成功，但此查询路径尚未暴露可绑定的paper ID**，不能据此否认APP内美股模拟账户存在。没有读取任何账户的资产、持仓或订单，没有下单；活动数据库只读复核仍为`ALERT_ONLY／NONE`，broker_states／intents／executions均为0，主数据库文件哈希未变。不选择实盘账户替代，REST继续NOT_CONFIGURED。

官方moomoo SDK包为`moomoo-api==10.12.7208`。同版离线源码比对显示，它与futu包的关键握手、schema及`FT` magic一致，不能把当前现象归因于SDK品牌差异；本轮未安装或执行新moomoo SDK，也未发出新SDK握手。当前只确认OpenAPIHost运行，尚无已注册独立OpenD的元数据证据；11111／22222的桌面TCP连接不能代替OpenD协议验证。

## 最小下一步：独立OpenD或官方新模拟认证路线

官方提供独立的`GET /api/v1.0/sim-trade/accounts`。返回的`account_id`是模拟业务账户字符串ID；美股正股／ETF使用`market_id=100`的US模拟账户。它不是授权表单里实盘资金账户的ID，也不能转换成旧SDK整数ID。[官方模拟账户列表](https://open.moomoo.com/zh-cn/api/sim-trade/account-list)

先向官方核对：该只读接口认可哪种认证、AppKey／OAuth的账户绑定是否覆盖模拟业务账户、如何只授权模拟范围。规则明确且用户同意对应模拟认证后，才只读获取列表并筛选US paper ID；不能为了调用这个GET接口去勾选实盘账户或扩大实盘权限。上述桌面元信息发现没有建立REST认证，尚未执行该REST列表请求。

另一条待验证路线是真正独立OpenD与官方SDK的`SIMULATE＋US`只读账户发现。先确认独立进程与协议，再核验返回的模拟身份；不继续猜环境字段类型或盲加参数。只保留模拟账户信息，REAL条目在输出与持久化前丢弃，不读取其资产、持仓或订单，不解锁真实交易。官方[交易QA的Q1／Q17](https://openapi.moomoo.com/moomoo-api-doc/en/qa/trade.html)说明旧路径的paper与账户筛选；同页**Q16**明确旧美股paper服务逐步下线并推荐新API。能否接通本用户的美股paper须实测，不能承诺安装OpenD或换SDK后即可成功。

当前桌面CLI帮助包含账户元信息与模拟订单只读查询，但本轮只执行上述元信息GET，没有调用订单查询。主帮助没有下单、改单或撤单方法，不能将此工具称为完整执行通道；桌面返回的ID／market枚举不得直接用于REST。当前阻点是尚未取得可用paper ID与已核验的模拟接入路线，不是APP未初始化。

### 可复制给moomoo官方客服的问题

以下由用户自行发送；本项目没有代发，也不需要向客服发送私钥、令牌或交易密码：

> 我已在moomoo APP初始化US Margin Paper，能看到虚拟资金。我只希望通过API使用美国模拟交易，明确不授权实盘账户查询或交易；目前开发者控制台的授权账户下拉只显示实盘现金／保证金账户。
>
> 1. 当前moomoo US的新REST API，能否在不选择任何实盘账户的情况下，为AppKey或OAuth授权模拟交易所需的最小权限？若标准表单不支持，请提供正式的paper-only授权入口、scope及操作文档。
> 2. `GET /api/v1.0/sim-trade/accounts`按登录用户返回的`account_id`，与控制台的`grantedUnivsAccountIds`／OAuth的`accid:<id>`分别是什么关系？如何只绑定我的US模拟业务账户，而不绑定实盘账户？
> 3. 2026-10-27文档将模拟交易改为交易读写权限。只读发现模拟账户究竟需要什么scope？能否取得仅对`/sim-trade`有效、对实盘`/accounts`无效的凭据？请确认是否需要真实账户的交易密码验证；本次不接受通过授权实盘来完成模拟接入。
> 4. MCP目录里的`sim_trade_*`是否对应同一服务器Paper账户、订单及成交？仅行情权限能否调用这些工具？请提供现行权限契约，区分真正模拟委托与dry-run预览，避免依赖旧翻译文案。

## 本机接入与验收顺序

以下为模拟认证规则明确、可用模拟账户已经核验之后的验收顺序，**不是当前已经具备的前提**。按[执行SPEC的显式配置](../specs/VEIGHNA_MOOMOO_SYSTEM.md#rest显式配置与授权边界)在本机非同步目录保存配置；管理者只在核实模拟授权后设置authorization_confirmed，精确account_id必须来自官方模拟账户列表，不能使用真实资金账户ID或默认首账户。

1. **授权门槛**：先取得并核实不涉及实盘账户的正式模拟授权方式，确认实际获授权限。不能用应用名称、`authorization_confirmed=true`或本机sim路径白名单代替服务端权限证明；无法满足时仍为`NOT_CONFIGURED`。不勾实盘、不输入真实交易密码、不采用默认宽scope的CLI。
2. **账户门槛**：在该认证下只读获取模拟账户列表，显式选择`account_type=1`、`market_id=100`、`broker_id=0`的US个人模拟账户。精确字符串`account_id`来自该返回；不取默认首账户，不换成实盘资金账户、`univsAccountId`或旧SDK整数ID。
3. **只读对账门槛**：显式reconcile只核对选定模拟账户的资金、持仓、订单及持久状态；错账号、缺字段、权限错误或未知提交均阻止新委托。已有手工模拟持仓不自动归属策略，缺数据不解释为清仓，不补发旧提醒。初始`ALERT_ONLY／NONE`状态不会因保存凭据自行升级。
4. **行情和执行契约门槛**：核对实时行情权限与供方事件时间，报价须严格小于5秒且非未来；历史bar-close不能充当即时价格。先确认REST订单期限默认、RTH与隔夜退出政策，本地DAY意图不冒充接口已保证DAY。
5. **券商模拟闭环门槛**：在已授权的模拟范围与可撮合RTH时段，以最多1张1股限价单验证受理、撤单、累计成交、重复回报及重启对账。响应超时不盲重发，受理或撤单ACK不当作成交；没有真实模拟回报时保持该项未验收。
6. **证据门槛**：分别记录授权、US paper身份、只读对账、受理、撤单与成交结果，并证明没有实盘调用。离线假响应、影子回放、HF研究收益、HTTP连通或APP虚拟资金不能替代这些证据。凭据、账户号与完整账户响应留在受控本机，不进入公开记录。

2026-11-26为感恩节休市，不能以今天的本地影子回放代替券商成交。11月27日13:00美东提前收市。[NYSE交易日历](https://www.nyse.com/markets/hours-calendars)

配置文件、私钥、令牌、账户ID与数据库不提交GitHub或聊天。公开HF继续只提供研究，不增加订单操作入口。
