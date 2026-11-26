# 动量与趋势：日频基线和分钟研究边界

更新：2026-11-26。**四种日频规则、双语界面与回测代码已实现；发布和验收状态见主SPEC。分钟行情与分钟策略尚未接入，没有本项目分钟结果。** 本文定义研究对照，不提供收益保证。最终实现和验收状态以 [SPEC](../SPEC.md) 为准；每日采集与实盘阶段见 [每日系统规格](../specs/DAILY_SIGNAL_SYSTEM.md)。

## 四种日频基线

本机初始研究池为8只主题研究股加SPY；网页按上传／在线／教学数据的实际名单运行。四类均使用完整日K，只做多并保留现金。下表中T是信号交易日，C是同一研究口径收盘价；均线包含当日已完成收盘，通道明确排除当日。**60日只是示例参数，不是经验证的最优周期。**

| ID | 定义与候选选择 | 怎样理解 |
| --- | --- | --- |
| cross_sectional_momentum | 计算C(T)/C(T−60)−1，按历史收益排序取前4只；排名可为负 | 股票之间比强弱；市场下跌时也可能选中下跌股票 |
| time_series_momentum | 要求60日收益>0，全部符合条件的股票参与风险分配 | 每只股票先和自身过去比较；没有合格股票时保留现金 |
| moving_average_trend | 要求C(T)>SMA200且SMA50>SMA200，全部符合条件的股票参与风险分配 | 以价格和均线判断趋势，不预测趋势何时反转 |
| channel_breakout | C(T)>此前55日high最大值时进入多头候选状态；C(T)<此前20日low最小值时退出，否则保持状态；全部符合条件的股票参与风险分配 | 观察区间突破并保持状态，避免每天重新把突破误当新入场 |

四类共用逆波动初始分配、EWMA组合风险缩放、调仓目标仓位上限和20%目标现金下限；非调仓日持仓和现金比例随价格漂移。状态可以逐日计算，组合按固定锚点每5个交易日调仓，在下一交易日开盘模拟执行；通道退出状态不表示当日收盘已经成交。交易和费用沿用 [组合模块](../research/portfolio.py) 的整数股、真实换手口径。

四组比较应统一最长预热窗口和评价区间，并公开实际有效股票数。SMA200不足200个完整收盘时不能改成较短均线冒充；上市前及缺失行情不填补。具体并列排序和缺失处理以实现审计记录为准。

## 分数、风险和评价

- **排名不是预期收益。** 60日历史收益有历史收益单位，却不是未来5日收益预测；均线、通道和排名也不能直接接0.002等预期收益成本门槛。规则对照应走明确的资格构仓路径（仅横截面策略取Top4，其余使用全部合格股票）；若另做收益校准，只能用独立历史验证期，并单列这个实验。
- **多头／现金与多空论文不同。** 本实现没有空头、借券或期货杠杆；不能把论文的多空收益直接标成这里的预期表现。
- **行业集中会影响解释。** 当前主题股相关性高，可能主要暴露于半导体、AI和市场beta。同日各股减去同一个SPY收益不会改变排序；正Rank IC不代表已剔除这些暴露，也不保证绝对收益为正。
- **短历史和反复试参数会误导。** IPO、重组和股票池起点须先处理；400日快照经过长均线预热后，可检验的市场阶段有限。窗口、阈值与股票池不应按测试净值反复挑选。
- **时点和成本必须保留。** 收盘信号不能按同一收盘价假装成交；next-open也只是模拟政策。费用、价差、滑点、开盘跳空和公司行动会改变结果。复权研究价不能直接充当原始报单价。
- **预测和组合价值分开。** 同时报Rank IC、含成本净值、回撤、换手、持仓与现金；重叠五日标签不能相加成为净值。先和统一规则基线比较，再判断DL或生成增强是否有增量。

## 三篇分钟级原始研究

这些论文研究日内信号；使用分钟数据不表示每分钟都交易，也不是把日频参数缩小就能复现。

### Gao、Han、Li、Zhou：Market Intraday Momentum，2018，JFE

对应早稿《Intraday Momentum: The First Half-Hour Return Predicts the Last Half-Hour Return》的研究线。SPY样本为1993–2013，使用TAQ逐笔价格构造半小时收益。核心预测变量从**前一日收盘到当日10:00，包含隔夜跳空**；按方向在15:30进入多头或空头，16:00平仓。正式版报告考虑交易成本，但不能据此保证当前账户能取得同样净收益。

原文：[发表DOI](https://doi.org/10.1016/j.jfineco.2018.05.009)、[作者机构记录](https://profiles.wustl.edu/en/publications/market-intraday-momentum/)。

### Baltussen、Da、Lammers、Martens：Hedging Demand and Market Intraday Momentum，2021，JFE

以60余个股指、国债、商品和外汇期货的分钟数据研究尾盘30分钟；样本覆盖1974–2020的不同区段。主要信号为前一收盘至尾盘30分钟前的累计收益。作者明确主策略结果未普遍扣除交易成本，另讨论标普期货1 tick假设；不能将期货条件直接外推为主题股结果。

原文：[作者开放PDF](https://academicweb.nd.edu/~zda/intramom.pdf)，数据见§2，策略和成本限制见§3.5。

### Tsai等：Assessing the Profitability of Timely Opening Range Breakout on Index Futures Markets，2019，IEEE Access

使用DJIA、S&P500、Nasdaq、恒指和台指期货的1分钟数据，历史范围依市场而异。先确定活跃时段和观察窗口，之后价格越过窗口高／低点触发，活跃时段结束平仓。假设整体交易成本0.01% per trade；不能擅自将其解释成已覆盖本账户全部双边费用与滑点。窗口选优和触发后可成交性仍须独立检验。

原文：[发表DOI](https://doi.org/10.1109/ACCESS.2019.2899177)、[作者上传稿](https://www.researchgate.net/profile/Jia-Hao-Syu/publication/331076454_Assessing_the_Profitability_of_Timely_Opening_Range_Breakout_on_Index_Futures_Markets/links/6285e8a6247e622c2efb5839/Assessing-the-Profitability-of-Timely-Opening-Range-Breakout-on-Index-Futures-Markets.pdf)。

## 分钟数据候选，尚未接入

- **moomoo传统OpenD／SDK**：官方提供K_1M、K_5M、K_15M及历史K线分页；当前本机22222桌面CLI仍只采日K，不能套用另一接口的认证或参数。实际历史长度、订阅和权限需按账户核实。[历史K线](https://openapi.moomoo.com/moomoo-api-doc/quote/request-history-kline.html)、[K线类型](https://openapi.moomoo.com/moomoo-api-doc/quote/quote.html)、[本项目接口边界](MOOMOO_API.md)。
- **Alpaca Basic**：实时IEX和历史SIP应分开理解；Basic查询历史SIP时，end需至少早于当前15分钟。它可以作为历史分钟候选，不等于免费实时全市场报价；请求还需遵守feed、分页与权限要求。[官方FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)、[数据服务范围](https://docs.alpaca.markets/us/docs/about-market-data-api)、[Stock Bars](https://docs.alpaca.markets/us/reference/stockbars)。
- **Massive Basic**：可研究分钟聚合历史；免费Basic取得前一交易日数据需跨过美东午夜，不能当作当日盘中实时服务。窗口、调整方式及当前计划范围应随快照记录。[分钟聚合接口](https://massive.com/docs/rest/stocks/aggregates/custom-bars)、[Basic可用时点](https://massive.com/knowledge-base/article/on-the-free-basic-plan-when-can-i-pull-the-previous-trading-days-data)、[计划范围](https://massive.com/pricing?product=stocks)。

分钟研究需另定UTC时间戳、交易时段、半日市、缺bar、收盘竞价及信号可见时间；只凭OHLC不能知道同根K线内高低点先后。实际执行还需报价、延迟和滑点检验。当前不会因此自动开通订阅、读取账户或提交订单。

论文仅提供原文链接，不下载或重新分发全文。相关方法与原始三篇论文的区别见 [论文索引](papers/README.md)；真实日K入口和冻结快照原则见 [历史数据说明](HISTORICAL_DATA.md)。
