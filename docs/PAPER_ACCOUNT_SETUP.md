# 模拟账户API接入入口

更新2026-11-26。桌面moomoo已登录并能读行情；这不自动提供新REST模拟交易认证。当前本机执行器无已配置的paper账户，实际委托和成交均为0。HF令牌只用于研究数据，不用于券商接口。

## 管理者先在官方网页核对

1. 打开[moomoo OpenAPI控制台](https://open.moomoo.com/dashboard)，登录个人账户。
2. 查找 **AppKey管理**。官方API-key路线需创建AppKey、选择权限及签名算法，并上传公钥；对应私钥只保存在本机非同步目录。当前适配器支持Ed25519／RSA-SHA256，不上传私钥。
3. 先核对是否有仅模拟交易与所选模拟账户的权限。官方公开材料尚不足以证明所有账户均提供paper-only授权，不能把“本程序只调用sim-trade”当成凭据本身已经限制为paper。如果控制台只给全账户／实盘写权限，先保留未配置，不使用默认CLI宽scope登录。

这些是已核对的[官方认证说明](https://open.moomoo.com/zh-cn/api/overview/getting-started)，具体权限以本人控制台实际提供为准。不需要重装或退出当前桌面moomoo。

## 本机接入与验收顺序

按[执行SPEC的显式配置](../specs/VEIGHNA_MOOMOO_SYSTEM.md#rest显式配置与授权边界)在本机非同步目录保存配置。管理者核实授权后才设置authorization_confirmed；精确account_id必须来自官方模拟账户列表，不能使用真实资金账户ID或默认首账户。

1. 只读获取模拟账户列表，选择明确US模拟账户。REST账号为字符串，不能转换成旧SDK整数ID。
2. 显式reconcile核对该模拟账户资金、持仓、订单及持久状态，不提交旧提醒。
3. 核对实时行情权限和供方事件时间；过期报价不提交。
4. 在可撮合的RTH时段，以最多1张1股限价单验证受理、撤单、累计成交、重复回报和重启对账。还需先核对REST DAY默认与隔夜退出政策。

2026-11-26为感恩节休市，不能以今天的本地影子回放代替券商成交。11月27日13:00美东提前收市。[NYSE交易日历](https://www.nyse.com/markets/hours-calendars)

配置文件、私钥、令牌、账户ID与数据库不提交GitHub或聊天。公开HF继续只提供研究，不增加订单操作入口。
