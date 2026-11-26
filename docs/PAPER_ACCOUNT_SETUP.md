# 模拟账户API接入入口

更新2026-11-26。桌面moomoo已登录并能读行情；这不自动提供新REST模拟交易认证。当前本机执行器无已配置的paper账户，实际委托和成交均为0。HF令牌只用于研究数据，不用于券商接口。

## 当前授权页已经确认的情况

用户本次截图已确认：AppKey表单的授权账户选择只列出实盘现金／保证金账户，没有模拟账户。本页不记录任何账户号或尾号。**AppKey能够绑定paper-only账户尚未证实，REST后端保持NOT_CONFIGURED。** 用户只授权模拟接入，没有授权选择、读取实盘资产／持仓／订单或执行实盘写入；不能拿实盘账户替代模拟账户来完成表单。

表单是否允许完全不选账户创建AppKey，以及这样创建后能否调用模拟API，均未证实；不将空选账户当作已经可行的接入步骤。现阶段只在[官方控制台](https://open.moomoo.com/dashboard)核对规则，不创建宽授权Key、不使用默认CLI宽scope登录。

[官方认证说明](https://open.moomoo.com/zh-cn/api/overview/getting-started)公开了AppKey／签名及OAuth scope，但没有充分说明本次表单的实盘账户绑定与独立模拟业务账户之间的关系。[2026-10-27更新日志](https://open.moomoo.com/zh-cn/changelog)说明模拟交易使用交易读写权限，因此不能假定行情权限就能进行paper查询，也不能把交易权限本身称为paper-only权限。

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

## 本机接入与验收顺序

以下为模拟认证规则明确、可用模拟账户已经核验之后的验收顺序，**不是当前已经具备的前提**。按[执行SPEC的显式配置](../specs/VEIGHNA_MOOMOO_SYSTEM.md#rest显式配置与授权边界)在本机非同步目录保存配置；管理者只在核实模拟授权后设置authorization_confirmed，精确account_id必须来自官方模拟账户列表，不能使用真实资金账户ID或默认首账户。

1. 只读获取模拟账户列表，选择明确US模拟账户。REST账号为字符串，不能转换成旧SDK整数ID。
2. 显式reconcile核对该模拟账户资金、持仓、订单及持久状态，不提交旧提醒。
3. 核对实时行情权限和供方事件时间；过期报价不提交。
4. 在可撮合的RTH时段，以最多1张1股限价单验证受理、撤单、累计成交、重复回报和重启对账。还需先核对REST DAY默认与隔夜退出政策。

2026-11-26为感恩节休市，不能以今天的本地影子回放代替券商成交。11月27日13:00美东提前收市。[NYSE交易日历](https://www.nyse.com/markets/hours-calendars)

配置文件、私钥、令牌、账户ID与数据库不提交GitHub或聊天。公开HF继续只提供研究，不增加订单操作入口。
