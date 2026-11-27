# 动量与趋势：日频基线和分钟研究边界

更新：2026-11-26。**已取得SPY／NVDA三日468行真实5分钟行情，确认供方结束标签并规范化；样本仅用于工程验证，没有策略有效性结论。** 四种日频规则与独立5分钟研究的发布状态见[SPEC](../SPEC.md)；本机执行试点见[VeighNa＋moomoo规格](../specs/VEIGHNA_MOOMOO_SYSTEM.md)。

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

## 5分钟研究入口与时间契约

HF主站侧栏增加独立的“5分钟动量与趋势”，与四种日频规则及AI模型对照分开。上传UTC开盘时间标记的5分钟CSV，或明确选择合成教学数据；不在公开服务连接本机moomoo。固定输入七列：

```text
timestamp,symbol,open,high,low,close,volume
2026-11-24T14:30:00Z,SPY,100,101,99,100.5,10000
```

此行是格式示例，不是真实SPY行情。`timestamp`表示bar开始；信号可用时间是开始后5分钟。输入使用UTC并以`Z`或`+00:00`结尾；不将日期字符串、无时区时间、本地时间或结束时间标签自动改成开盘时间。价格、时间格点、重复、OHLC关系、行数和大小均需校验；未来或尚未完成的bar拒绝，未收市的交易日排除。

只做美股RTH、多头与现金，首版三条规则如下；参数是工程基线，不是论文完整复现或验证过的最优值：

| 规则 | 资格／状态 | 初始参数 |
| --- | --- | --- |
| 时间序列动量 | 同日`close[t]/close[t-L]-1>0`才参与 | L=6根，即30分钟 |
| 均线趋势 | `close>SMA12`且`SMA3>SMA12` | 3／12根，即15／60分钟 |
| 开盘区间突破 | 前6根完成后冻结高低区间；其后收盘突破上沿进入候选，跌破下沿退出 | 观察30分钟；日终清零 |

三条策略共用输入、完整交易日、初始资金和费用；每个交易日窗口从头预热，不跨隔夜。XNYS日历由固定`exchange-calendars==4.11.2`提供，处理DST、休市与提前收市，不能固定假设每天78根。股票与基准必须在某日都有全部预期bar，该日才进入共同评价；缺失日逐股列入覆盖报告，不填价、不补假数据。共同预热和额外延迟后也须留有执行窗口；例如半日市42根配慢均线60根不算有效日。少于两个完整且可执行的共同日不造净值；少于20个有效日不展示夏普或年化波动。完整日筛选利用事后覆盖信息，可能引入样本选择偏差，不能直接当作实盘实时筛选。

目标仓位先采用等权，`w_i=min((1-cash_floor)/N,max_weight)`，余下现金保留；仓位与现金约束作用于调仓目标，实际权重会随价格漂移。此次不把日频EWMA或252直接套到5分钟bar，也不加入未经验证的日内年化风险预算。信号为规则资格及排序值，不冒充未来收益预测或Rank IC。

执行价使用下一根K线开盘的OHLC代理：默认延迟0时，上一根结束与下一根开盘共享边界，必须标明零延迟假设；可额外延迟一根完整K线作敏感性对照。日历预先确定最后一根bar开盘强制平仓，取消待执行目标并禁止再入，无隔夜头寸。整数股、买卖方向各扣实际成交费用；佣金类bps、半点差和滑点分别记录，不重复计费。基准为SPY每日首bar开盘全额买入、最后bar开盘退出，并扣同样费用；它与单股仓位封顶的策略风险暴露不同，不是等风险对照。

权益曲线保留UTC分钟时点，收益及年化统计先聚合到每日末权益，再按252描述；分钟bar数不是独立交易日样本数。结果同时展示每日收益、交易数量、成本分项、信号与成交时间、参考目标和实际现金，并下载JSON来源／版本／数据hash。无历史买卖报价和逐笔顺序，不能验证盘口深度、排队、冲击或真实成交。

真实本机采集入口为独立只读脚本：

```powershell
node scripts/collect-moomoo-intraday.mjs --symbols SPY,NVDA --start 2026-11-24 --end 2026-11-25
```

沿用已安装桌面CLI／Host22222、进程内密钥及本机DPAPI方式；不改变旧日K采集器或manifest。默认未核时间标签时只留raw；本版本经78组5分钟与1分钟聚合对齐后，使用`--timestamp-label bar-end --verification-source "核验依据"`导出，减5分钟得到UTC bar-start；可用时点仍是原bar-end。已取得11月23–25日SPY／NVDA各234根，合计468行；end日期为排他边界。原始页、整数volume差异审计及来源清单只留`data/intraday/`，不进入公开包。HF已从固定私有Dataset服务端实际读取该快照并运行三规则研究；没有常驻同步任务，也不提供原始行情下载。[接口边界](MOOMOO_API.md)、[私有同步](MOOMOO_CLOUD_SYNC.md)。

## 其他分钟数据候选，尚未接入

- **moomoo传统OpenD／SDK**：官方提供K_1M、K_5M、K_15M及历史K线分页；本机桌面CLI的独立5分钟采集适配与本路线分开，不能混用认证或参数。实际历史长度、订阅和权限需按账户核实。[历史K线](https://openapi.moomoo.com/moomoo-api-doc/quote/request-history-kline.html)、[K线类型](https://openapi.moomoo.com/moomoo-api-doc/quote/quote.html)、[本项目接口边界](MOOMOO_API.md)。
- **Alpaca Basic**：实时IEX和历史SIP应分开理解；Basic查询历史SIP时，end需至少早于当前15分钟。它可以作为历史分钟候选，不等于免费实时全市场报价；请求还需遵守feed、分页与权限要求。[官方FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)、[数据服务范围](https://docs.alpaca.markets/us/docs/about-market-data-api)、[Stock Bars](https://docs.alpaca.markets/us/reference/stockbars)。
- **Massive Basic**：可研究分钟聚合历史；免费Basic取得前一交易日数据需跨过美东午夜，不能当作当日盘中实时服务。窗口、调整方式及当前计划范围应随快照记录。[分钟聚合接口](https://massive.com/docs/rest/stocks/aggregates/custom-bars)、[Basic可用时点](https://massive.com/knowledge-base/article/on-the-free-basic-plan-when-can-i-pull-the-previous-trading-days-data)、[计划范围](https://massive.com/pricing?product=stocks)。

分钟研究需另定UTC时间戳、交易时段、半日市、缺bar、收盘竞价及信号可见时间；只凭OHLC不能知道同根K线内高低点先后。实际执行还需报价、延迟和滑点检验。当前不会因此自动开通订阅、读取账户或提交订单。

论文仅提供原文链接，不下载或重新分发全文。相关方法与原始三篇论文的区别见 [论文索引](papers/README.md)；真实日K入口和冻结快照原则见 [历史数据说明](HISTORICAL_DATA.md)。

## SNR支撑／阻力的量化研究

核对日期2026-11-26。用户已确认SNR指Support & Resistance。本节是研究和候选设计，**没有实现新的SNR策略或部署新页面**。现有开盘区间突破只是相关基线，不能代表完整的支撑／阻力系统。

### 先定义价位，再定义如何交易

| 方法 | 怎样形成候选价位 | 实时使用的关键约束 |
| --- | --- | --- |
| 前日／前期固定水平 | 前一完整RTH高低；传统Pivot用`P=(H+L+C)/3`、`R1=2P-L`、`S1=2P-H` | 前期完成后才可用，统一RTH／扩展时段与复权口径。[TradingView公式与时段](https://www.tradingview.com/support/solutions/43000521824-pivot-points-standard/) |
| 历史滚动通道 | `R_t=max(H[t-N:t])`、`S_t=min(L[t-N:t])`，切片上限排除当前根 | 用本根收盘判断突破时，必须读上一根通道；LEAN默认更新会纳入当前High／Low，不能误称库已自动shift。[LEAN源码](https://github.com/QuantConnect/Lean/blob/master/Indicators/DonchianChannel.cs) |
| 已确认的swing高低点 | 以左、右指定根数判断局部高低 | 右侧r根结束后才知道pivot，分别保留pivot_at和available_at；不按画回历史的标签提前交易。[TradingView重绘说明](https://www.tradingview.com/pine-script-docs/concepts/repainting/#plotting-in-the-past) |
| 多价位合并／聚类 | 历史转折点中距离接近的价格合为区域，中心可用中位数 | 作者开源例子采用AgglomerativeClustering及ZigZag／高低点；属于找线工具，完整样本fit或未确认ZigZag不能直接作历史信号。[作者仓库](https://github.com/day0market/support_resistance) |
| Volume Profile | 根据价位成交量分布得到POC和价值区间 | 官方工具使用更低周期数据；单根5分钟总量无法唯一还原价位成交量，近似需标明假设。当日最终POC不能提前用于早盘。[官方方法](https://www.tradingview.com/support/solutions/43000502040-volume-profile-indicators-basic-concepts/) |

SciPy的`find_peaks`可筛选突出程度和峰间距，但不是现成的实时交易信号；prominence会向左右寻找基底，wlen也不会自动消除未来依赖。若使用此类工具，须在当时可见的前缀数据上确认，并冻结已经发布的结果，不能全样本计算再回填。[find_peaks](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html)、[prominence](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.peak_prominences.html)

### 原始研究提供了什么证据

- [Osler，2000，纽约联储原文](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf)：用机构事先公布的价位与随机价位比较反弹频率；这是外汇事件预测检验，不提供统一自动找线算法，也不是扣成本策略验收。
- [Chung与Bellotti，2021](https://arxiv.org/html/2101.07410v1)：滚动极值加减宽度形成区域，价格进入后冻结至反弹／穿透完成，研究历史反弹次数与时间衰减。样本为2018年EURUSD、LLOY和BRENT的一分钟价格。原文带宽使用全序列平均绝对增量；交易研究应改为训练期固定或截至当时估计，并记录这一偏离，不能借未来波动。
- [Garzarelli等，2014，Scientific Reports](https://pmc.ncbi.nlm.nih.gov/articles/PMC3967202/)：用伦敦股票逐笔价格研究已有反弹次数与再次反弹的关系；其统计记忆证据不等于费用、延迟与流动性之后可获利。
- [Osler，2001／2003，纽约联储](https://www.newyorkfed.org/research/staff_reports/sr125)：订单在特定价位聚集，为区域附近反转及穿越后加速提供外汇微观结构解释，不能直接外推成美股5分钟优势。

### 三种事件应分别实现和评价

下面是候选规则，属于本项目研究设计，参数和收益均未验证：

1. **支撑反弹**：价位已知，价格从上方进入支撑带；后续已完成bar收盘重新站到上沿之上才确认。跌破的失效标准、等待期限、独立触碰之间须离开多远，均需预先规定。
2. **阻力突破**：已有阻力带被收盘越过上沿及预设缓冲才确认；若加成交量条件，比较对象只能来自当时已知历史，跨时段比较还需处理日内成交量季节性。下一可执行时点入场，不把盘中影线触碰直接当收盘突破。
3. **突破后回踩**：顺序为`等待突破 → 收盘确认 → 限期等待后续bar回踩 → 收盘守住原区域 → 下一可执行时点`。同一bar不能凭OHLC自行断定先突破再回踩；跌破失效边界或超时则取消，突破时冻结所用level版本。

一个研究示例可将价格100附近设为99.8–100.2的区域，分别观察反弹、收盘越过和后续回踩。该数值纯为解释规则，不是真实证券价格、下单建议或验证过的区间宽度。

### 我们建议的实施顺序与验收

先比较前一完整RTH高低与冻结开盘区间的反弹、直接突破和突破回踩；这些来源较容易审核已知时点。随后再试已确认swing的区域合并。带宽可比较固定bps、tick与历史ATR尺度，但只在训练／验证窗口选取；不因测试收益漂亮反复调参。ATR是波动尺度，不证明区域会生效。

每个区域拟记录`level_id／source／pivot_at／available_at／lower／upper／version／独立触碰次数／失效时刻`。同一次停留五根bar不计五次反弹，必须完成离开与重新进入的独立事件；不将某次反弹事后作为该次交易前已知的区域强度。事件开始后不能追着价格移动边界。

先评价触碰后反弹／穿透概率、事件数量和不确定性，并设随机价位对照；再评价扣成本收益、回撤、换手、延迟敏感性，与现有ORB／动量采用同输入和成本。前者是事件预测，后者才是交易策略，不可互代。滚动留出按交易日进行，防止重叠事件／标签跨界；追加未来bar后，历史已发布level、signal与成交记录应不变。

现有5分钟框架可复用XNYS、完成bar时点、next-open代理、额外一根延迟及费用。它没有通用盘中止损／止盈／OCO或按止损距离分配仓位；若增加这些，须另定同bar先后、跳空、未成交和风险预算规则，不能用OHLC挑有利路径。已有三日SPY／NVDA快照只够检验工程，不能评价SNR稳定性。

后续DL可使用距最近区域的ATR标准化距离、区域年龄、此前独立反弹次数、突破幅度等**当时已知特征**，检验是否改善预测。GenAI仍须只在训练期增强，效果看真实留出期；目前没有将SNR特征接入模型，也没有通过公开研究页向券商下单。
