# Beta 策略研究与实施建议

研究日期：2026-11-26，America/New_York。适用范围：Alpha Trading Lab 的美股日频研究、后续5分钟风险控制，以及moomoo执行路线。

Beta策略至少包含方向性高Beta、低Beta长仓、目标Beta配置、Beta中性与Betting Against Beta几类。它们对市场方向、融资和做空的要求不同。对本项目，优先次序应为测量暴露、比较无杠杆高低Beta长仓、检验现金减仓覆盖层，随后才研究多空与杠杆。当前项目未实现真实Beta估计或相关策略；本次交付为研究和待实现规格。

## 1 Beta策略分别在赚什么

| 路线 | 公开方法或学术例子 | 组合怎样形成 | 主要暴露和约束 |
| --- | --- | --- | --- |
| 高Beta长仓 | S&P 500 High Beta | 历史Beta较高股票构成多头组合 | 加大市场方向暴露；上涨和下跌均可能放大，不自动产生alpha |
| 低Beta长仓 | S&P Low Beta；Baker等研究 | 选择较低Beta股票并持有 | 防御性市场暴露；相对当前股票池排名低，不保证Beta低于1 |
| 最低波动组合 | MSCI Minimum Volatility | 用协方差模型和约束优化组合方差 | 低总波动与低Beta是不同目标，需要相关性／行业等输入 |
| 目标或动态Beta | S&P Low Volatility Target Beta | 按估计Beta调整股票、现金或杠杆规模 | 目标可能要求融资；现金减仓只能覆盖部分可实现目标 |
| Beta中性 | 股票组合加指数对冲 | 按股票组合Beta决定指数空头规模 | 做空、融资、估计漂移、多腿成交及行业残余风险 |
| Betting Against Beta，BAB | Frazzini与Pedersen | 低Beta多头与高Beta空头分别按Beta缩放 | 因子套利假说；涉及多空和通常较高总名义暴露 |

前两类主要改变持有什么，目标Beta主要改变持有多少，Beta中性处理市场对冲；BAB则同时改变选股与两腿规模。将它们放在同一回测里时，须分别披露现金、总名义暴露、融资和借券，不能只比较净值。

## 2 真实指数怎样实现

### 高Beta选股

2026年3月版S&P方法从历史S&P500成分股中，按过去252日日价格收益估计Beta，选最高100只并按Beta比例加权。1／4／7／10月末为参考日，2／5／8／11月第三周五收盘后调仓生效。它是方向性股票组合，不是每日倍数杠杆产品。[S&P当前方法，第5、7、9页](https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-high-beta-indices.pdf)

对我们的启示是先研究Beta排序是否有增量价值。当前45只主题池不能替代历史S&P500成分股，因此只可称项目变体，不能称官方指数复现。

### 低Beta选股和最低波动

S&P Low Beta按国家从低Beta端保留累计自由流通市值70%的股票，并使用缓冲及市值权重。其Beta估计包含长期日收益、半衰期、非同步价格修正与收缩，不能和简单252日OLS排序混为同一实验。[2026年9月GIVI方法，Low Beta章节和附录A](https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-givi-indices.pdf)

MSCI Minimum Volatility通过Barra风险模型，在个股、行业、国家和换手等约束下最小化组合方差；不是挑Beta最低的股票。缺少其模型与优化配置时，本项目只能实现自己的最小方差实验。[2025年7月方法](https://www.msci.com/indexes/documents/methodology/2_MSCI_Minimum_Volatility_Indexes_Methodology_20250725.pdf)

### 目标Beta可能需要杠杆

2026年11月版S&P Low Volatility Target Beta以相对S&P500的Beta约1为目标：按252日估计调整低波动指数暴露，范围1.2–2.0倍、单次变动最多25个百分点，月度调仓并计融资。边界和估计误差意味着实现Beta不会始终等于目标。该指数2015年上线之前的序列属于回测。[官方方法，第2–4页](https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-500-low-volatility-target-beta-indices.pdf)

我们目前的多头／现金执行器不支持该杠杆结构。较可行的首步是设Beta上限并只减仓；这与复制上述指数是两个目标。

## 3 BAB的原始规则及争论

### 原始构建

Frazzini与Pedersen的美股研究覆盖1926–2012年，采用一年日收益波动与五年重叠三日收益相关估Beta，最低数据量分别120／750日，再按`0.6×估计Beta+0.4`向1收缩。每月按Beta秩构成低／高两腿，腿内按秩距均值加权，两腿分别除以自身Beta。[2014年JFE作者版，第7–9页](https://pages.stern.nyu.edu/~afrazzin/pdf/Betting%20Against%20Beta%20-%20Frazzini%20and%20Pedersen.pdf)

核心回报结构为：

\[
r^{BAB}_{t+1}=\frac{r^L_{t+1}-r_f}{\hat\beta^L_t}-\frac{r^H_{t+1}-r_f}{\hat\beta^H_t}.
\]

这个结构意味着事前Beta相抵，但美元多空金额通常不相等。作为纯教学算例，低腿Beta0.5、高腿1.5时，相应暴露约为多2倍、空0.667倍，总名义约2.667倍；这不是我们的股票估计或下单方案。

### 反证改变了应做的检验

Novy-Marx与Velikov指出，原BAB的特殊权重与估计方式引入显著微盘及其他因子暴露；成本和盈利／投资因子会改变收益归因。不能只复刻原始夏普，再将结果全称为Beta溢价。下列开放稿为2018版本，正式期刊论文发表于2022年，数字不可跨版本拼接。[作者开放稿](https://mysimon.rochester.edu/novy-marx/research/BABAB.pdf)、[正式论文DOI](https://doi.org/10.1016/j.jfineco.2021.05.023)

Baker、Bradley、Wurgler以1968–2008年数据比较Beta／波动五分位组合，并讨论基准考核与杠杆限制为何可能阻碍低风险套利。该研究未扣交易成本，适合作为低Beta长仓机制背景，而非个人账户的收益承诺。链接为2010作者稿，正式论文发表于2011年。[作者稿](https://pages.stern.nyu.edu/~jwurgler/papers/wurgler_bradley_baker.pdf)

Asness等进一步把Beta拆成相关性与相对波动，构建Betting Against Correlation，以区分杠杆约束与个股彩票偏好等机制。这说明低Beta、低波动、低相关不应共用一个标签。[2020年作者接受稿](https://research-api.cbs.dk/ws/portalfiles/portal/65819802/lasse_heje_pedersen_et_al_betting_against_correlation_acceptedmanuscript.pdf)

项目应预先加入估计器、等权／市值权重、股票规模及行业控制等对照。无法满足750日相关估计门槛的年轻股票可以进入另一种短窗研究，但不能冒充原BAB复现。借券、融资、做空股息补偿、冲击及资金约束都应进入多空回测；参考因子不能替代可执行账户账本。

## 4 动态Beta和波动管理不能互代

Moreira与Muir按上一月日收益的实现方差倒数缩放下一月风险，核心为`c/σ²`，不是常见的`目标波动/σ`。原文定标方式若用于可执行净值，需要改成训练期或扩展历史估计，明确这一复现偏离。[2017年发表稿](https://amoreira2.github.io/alan-moreira.github.io/VolPortfolios_published.pdf)

Cederburg等研究103种股票策略，发现波动管理并不系统性改善直接表现；其样本外组合结果也弱于事后最优组合，提醒我们回归alpha不等于实时可实施收益。[2020年JFE作者稿](https://www.lehigh.edu/~xuy219/research/COWY.pdf)

Daniel与Moskowitz分析多空动量的崩溃及条件Beta，明确指出前瞻Beta对冲可制造不可实现的改善；基于过去信息的对冲不能照搬该收益。其动态动量包含条件均值／方差模型，不能直接外推为本项目5分钟多头动量规则。[2016年发表稿](https://kentdaniel.net/papers/published/jfe_16.pdf)

因此，本项目应将市场择时、波动目标与Beta上限分为独立消融实验。若使用“SPY高于长期均线时提高暴露”的规则，必须作为我们的趋势择时假说验证，不能将上述论文当作该规则已有效的证据。

## 5 Beta怎样估计才可用于研究

估计器、市场基准、收益频率和观察窗必须同时定义。研究用基本市场模型为：

\[
r_{i,s}-r_{f,s}=\alpha_i+\beta_i(r_{m,s}-r_{f,s})+\epsilon_{i,s}.
\]

首轮可固定126日与252日两个观察窗，比较OLS和明确参数的收缩估计。窗口是项目设计起点，不是文献证明的最优值。报告Beta、相关性、总波动、残差波动、R²、标准误及样本数，缺历史就不可用，不填上市前数据。

Lewellen与Nagel对条件Beta的研究提示，短窗变化包含抽样噪声；Scholes与Williams指出非同步成交会使市场模型估计出现偏差。对分钟数据尤其不能把多出来的bar数等同于独立信息。[条件CAPM作者稿](https://web.mit.edu/lewellen/www/Documents/ConditionalCapm.pdf)、[非同步数据论文摘要](https://www.sciencedirect.com/science/article/pii/0304405X77900411)

同一固定权重、同一基准和模型下，可用`Σw_iβ_i`描述事前组合敏感度；它不同于总股票仓位，也不同于以后实际实现的Beta。市场下跌、相关性改变、仓位漂移及整数股都会使预测与实现出现差异。事后实现Beta仅作评价，不能回填成过去的对冲输入。

## 6 对当前Alpha Trading Lab的判断

当前已知条件是45只主题股票、SPY基准、冻结日K研究和三日SPY／NVDA真实5分钟工程快照。历史股票池不是完整的历史可投资市场，年轻上市／业务重启边界须继续保留；主题集中会让行业暴露影响Beta排序。

现有模型目标是未来股票收益减同段SPY收益，系数固定为1。它不等于Beta调整残差，也不证明市场中性；同日减同一个市场收益还不会改变横截面排序。当前EWMA风险矩阵是选中股票的零均值二阶矩，不能直接当作带截距OLS的中心化市场协方差。标准Beta需要显式纳入SPY和一致的估计口径。

| 能力 | 当前状态 | Beta研究需要补充 |
| --- | --- | --- |
| 日K、基准共同日期、快照哈希 | 已有 | 对齐收益与无风险利率口径；分红／复权说明 |
| MLP／DDPM研究 | 已有 | Beta特征、风险调整标签作为独立新实验 |
| 仓位／现金／波动预算 | 已有 | Beta估计、Beta上限及实际暴露审计 |
| 5分钟信号及执行试点 | 代码已有，券商认证未完成 | 先考虑前一完整日Beta作为慢风险输入 |
| 指数空头／多腿／融资／借券 | 未实现 | 仅离线研究，不能直接交现有0／1股多头执行器 |

### 推荐的研究顺序

1. **暴露测量**：先显示个股与组合的预测／实现Beta、总波动、残差风险和行业集中度；检验估计是否稳定。
2. **无杠杆基线**：在共同数据、估计器和时点下，对比高Beta、低Beta、全池等权与SPY；再检查扣成本及匹配风险后的结果。
3. **现金覆盖层**：在同一信号和基础配置上开／关波动覆盖及Beta上限，形成无覆盖、仅波动、仅Beta、两者同时四组；共同保留现金／个股上限及费用。
4. **条件暴露**：单独检验趋势／波动状态是否改善仓位决策，保持样本外定标。
5. **中性与BAB**：先离线加入完整成本、做空及多腿账本；达到所需历史与执行条件后再讨论接入。

详细可复现实验契约见[Beta研究实施规格](../specs/BETA_RESEARCH_PLAN.md)。本轮没有计算实际股票Beta、下载参考因子数据、跑新回测、修改HF或启动交易。

## 7 公开参考数据怎样使用

Kenneth French提供Size×Beta的25组合：每年6月末分组，Beta用过去五年、至少两年的月收益估计。它适合检查规模与Beta效应，不是BAB算法。核对时页面月度序列显示至2026年9月，未下载数据文件。[官方构建说明](https://mba.tuck.dartmouth.edu/pages/Faculty/ken.french/Data_Library/tw_5_ports_me_BETA.html)

AQR提供BAB的美股及国际延伸参考因子，可将论文期与发表后时期分开研究；当前页面日期为2026-08-31，未核验文件最后月份。它是参考因子，不是moomoo个人账户净收益。[月度数据说明](https://www.aqr.com/Insights/Datasets/Betting-Against-Beta-Equity-Factors-Monthly)

参考数据只作为来源链接，不将文件或第三方论文全文复制进公开仓库。指数发布前回测、发布后指数、可投资产品与个人账户收益须分别标记；公开方法的当前版本也不能替代历史时点的成分与规则。

## 8 结果应回答的问题

- 高Beta组合的收益，是否只是更大的市场暴露？匹配波动或Beta后还剩什么差异？
- 低Beta效果是否由行业、规模、价值、盈利／投资等其他因子解释？
- Beta上限是否降低下行风险，同时付出多少上涨参与度和换手成本？
- 择时或对冲改善在真实留出期、危机反弹与不同估计窗下是否保留？
- 换成可得价格、整数股、融资及借券条件后，论文结构还有多少可执行部分？

这些问题比单次历史净值更适合决定下一步开发方向。当前优先选择测量与无杠杆实验，保持原日频DL／GenAI和5分钟策略结果不被新目标悄悄替换。
