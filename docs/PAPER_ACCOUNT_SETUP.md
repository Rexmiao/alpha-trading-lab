# 模拟账户API接入入口

更新2026-11-26。桌面moomoo已登录并能读行情；这不自动提供新REST模拟交易认证。当前本机执行器无已配置的paper账户，实际委托和成交均为0。HF令牌只用于研究数据，不用于券商接口。

## 当前授权页已经确认的情况

用户本次截图已确认：AppKey表单的授权账户选择只列出实盘现金／保证金账户，没有模拟账户。本页不记录任何账户号或尾号。**AppKey能够绑定paper-only账户尚未证实，REST后端保持NOT_CONFIGURED。** 用户只授权模拟接入，没有授权选择、读取实盘资产／持仓／订单或执行实盘写入；不能拿实盘账户替代模拟账户来完成表单。

表单是否允许完全不选账户创建AppKey，以及这样创建后能否调用模拟API，均未证实；不将空选账户当作已经可行的接入步骤。现阶段只在[官方控制台](https://open.moomoo.com/dashboard)核对规则，不创建宽授权Key、不使用默认CLI宽scope登录。

[官方认证说明](https://open.moomoo.com/zh-cn/api/overview/getting-started)公开了AppKey／签名及OAuth scope，但没有充分说明本次表单的实盘账户绑定与独立模拟业务账户之间的关系。[2026-10-27更新日志](https://open.moomoo.com/zh-cn/changelog)说明模拟交易使用交易读写权限，因此不能假定行情权限就能进行paper查询，也不能把交易权限本身称为paper-only权限。

本机已准备签名材料，目录为`C:\Users\Rexy\Documents\ChatGPT\量化准备\alpha-paper-runtime\rest-paper`：公钥`ed25519-public.pem`、私钥`ed25519-private.pem`、占位配置`config.example.json`。仅当前Windows用户和SYSTEM有访问权限；官方AppKey路线使用公钥，当前适配器支持Ed25519／RSA-SHA256，不上传私钥。若后续确认可用的模拟授权路线，名称示例用`alpha_trading_lab_paper`：本次表单要求字母开头，之后只允许字母、数字、下划线，不使用连字符。名称只作标识，不会缩小服务端权限；`authorization_confirmed`继续保持false。

## 最小下一步：先确认模拟账户发现与认证规则

用户已确认尚未进入过客户端模拟交易。先在桌面端左侧Paper／模拟交易入口，或手机端“我的→模拟交易”，选择美股并按提示初始化，直到能看到明确模拟标记和虚拟资金。这只用于确认模拟账户已经存在，不保证它会出现在网页AppKey的实盘账户下拉中；不选择实盘账户代替。[官方客户端入口](https://openapi.moomoo.com/moomoo-api-doc/en/qa/trade.html#q1-how-to-use-paper-trading)

官方提供独立的`GET /api/v1.0/sim-trade/accounts`。返回的`account_id`是模拟业务账户字符串ID；美股正股／ETF使用`market_id=100`的US模拟账户。它不是授权表单里实盘资金账户的ID，也不能转换成旧SDK整数ID。[官方模拟账户列表](https://open.moomoo.com/zh-cn/api/sim-trade/account-list)

先向官方核对：该只读接口认可哪种认证、AppKey／OAuth的账户绑定是否覆盖模拟业务账户、如何只授权模拟范围。规则明确且用户同意对应模拟认证后，才只读获取列表并筛选US paper ID；不能为了调用这个GET接口去勾选实盘账户或扩大实盘权限。本次文档更新没有发出认证或账户查询。

备用方向是验证本机原生模拟入口，或真正独立OpenD与官方SDK的`SIMULATE＋US`账户路径。只保留模拟账户信息；列表若混有REAL条目，应在输出与持久化前丢弃，不读取其资产、持仓或订单，不解锁真实交易。当前11111与22222属于同一桌面Host，SDK握手曾超时，不能直接当作独立OpenD已连接。官方[交易QA的Q1／Q17](https://openapi.moomoo.com/moomoo-api-doc/en/qa/trade.html)说明旧路径的paper与账户筛选；同页**Q16**明确旧美股paper服务逐步下线并推荐新API，因此备用路径必须实际验证，不能承诺本账户仍可用。

当前桌面CLI只读帮助已核：get-acc-list会列实盘／模拟账户元信息，没有只模拟过滤参数；order-list-query支持显式header-trd-env=0（模拟）和US市场2。主帮助没有下单、改单或撤单方法，因此不能把该只读工具称为完整执行通道。本轮未发账户请求，模拟账户数量尚未知。初始化完成后再有界验证；桌面CLI的ID和market枚举也不得直接用于新REST路径。

## 本机接入与验收顺序

以下为模拟认证规则明确、可用模拟账户已经核验之后的验收顺序，**不是当前已经具备的前提**。按[执行SPEC的显式配置](../specs/VEIGHNA_MOOMOO_SYSTEM.md#rest显式配置与授权边界)在本机非同步目录保存配置；管理者只在核实模拟授权后设置authorization_confirmed，精确account_id必须来自官方模拟账户列表，不能使用真实资金账户ID或默认首账户。

1. 只读获取模拟账户列表，选择明确US模拟账户。REST账号为字符串，不能转换成旧SDK整数ID。
2. 显式reconcile核对该模拟账户资金、持仓、订单及持久状态，不提交旧提醒。
3. 核对实时行情权限和供方事件时间；过期报价不提交。
4. 在可撮合的RTH时段，以最多1张1股限价单验证受理、撤单、累计成交、重复回报和重启对账。还需先核对REST DAY默认与隔夜退出政策。

2026-11-26为感恩节休市，不能以今天的本地影子回放代替券商成交。11月27日13:00美东提前收市。[NYSE交易日历](https://www.nyse.com/markets/hours-calendars)

配置文件、私钥、令牌、账户ID与数据库不提交GitHub或聊天。公开HF继续只提供研究，不增加订单操作入口。
