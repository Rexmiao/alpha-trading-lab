# GEX和Max Pain如何进入交易决策

研究日期：2026-11-27，America/New_York。

本研究要回答的是：在什么条件下看涨或看跌，在哪个区域等待什么确认，选股票还是哪种期权结构，以及预期收益能否覆盖成本和尾部损失。截图中的“超过某价格就做Put”属于待检验的规则示例，不是订单。

**建议把GEX作为价格反馈和风险状态，把Max Pain作为待验证的目标区域；方向由已发生的价格冲击、可用成交信息和事件状态共同判断。最后用具体工具的净损益分布决定交易或不交易。** 这是一项研究设计，尚无本项目的真实期权样本外收益或已校准胜率。

取得完整原文并核读数据、方法和主要结果的文献共24个独立研究家族，见下表。部分读到的是早期完整工作稿，已逐篇注明；不把期刊发表年份冒充实际阅读版本。不重复计算同一论文的改题、修订或合并稿。它们覆盖库存、反馈、到期和执行风险，不是24篇都验证Max Pain有效；多篇共享历史数据，也不是24份独立实证复制。另有直接Max Pain论文和2026年前沿研究只能核读摘要或部分正文，单独列出，不计入24篇。完整论文副本与逐页核读记录保存在本机Git忽略目录，不随项目公开。

## 从结构到方向再到具体工具

要分别回答四个问题，不能让一个GEX数字包办：

| 层次 | 要回答的问题 | 输出 |
| --- | --- | --- |
| 期权结构 | 已知链的敞口集中在哪些行权价、期限？库存符号有多不确定？ | 无符号集中区、各库存情景的GEX曲线、零点集合、Max Pain区间 |
| 价格预测 | 在已有上涨或下跌冲击之后，更可能延续、回落还是扩大振幅？ | 15／30／60分钟收益、波动、上下区域触及概率；只展示已验证的概率 |
| 工具选择 | 相同判断，买股、买Call、买Put或价差，哪个净边际更好？ | 实际合约、买卖方向、入场报价、持有期限及净损益情景 |
| 风险和执行 | 多少仓位？什么情况失效或不交易？ | 现金、组合风险预算、成交约束、退出规则与审计记录 |

例如，“未来可能大幅上涨”和“现在买Call划算”是两个不同判断。IV已经很贵、Theta损耗快、买卖价差宽时，即使方向看对，Call仍可能亏损。历史期权风险溢价、买压及执行研究都要求把这两层分开，见文献4、8、22和24。

## 核读的24篇文献

每行的结果只对应明确标出的版本和市场。这里的“可用”指能指导研究设计，不代表已经在我们的数据上复现或赚钱。

### 库存识别和方向信息

| 编号与原文 | 实际核读版本及数据方法 | 对本项目的用处和边界 |
| --- | --- | --- |
| 1. Pan、Poteshman — [The Information in Option Volume for Future Stock Prices](https://web.mit.edu/junpan/OldFiles/www/volume.pdf) | 2006期刊全文；1990—2001 CBOE分类成交，区分非MM、买卖、开平；检验开仓买入PCR与后续股票收益。 | 强信号需要专有开仓分类，普通OI／网页BUY标签不能替代；指数未给出同等方向证据。适合作为独立方向流研究。 |
| 2. Ni、Pan、Poteshman — [Volatility Information Trading in the Option Market](https://web.mit.edu/people/junpan/npp.pdf) | 2008期刊全文；分类买卖量按Vega加权，控制Delta流、RV及IV，研究未来实现波动。 | 区分“波动信息”和“涨跌信息”。原文年度全样本归一化须改为训练期或历史窗口；不能直接推出买跨式有利润。 |
| 3. Gârleanu、Pedersen、Poteshman — [Demand-Based Option Pricing](https://users.nber.org/~confer/2005/URCs05/pedersen.pdf) | 实读2005完整工作稿，2009发表；分参与者long／short OI，风险承受能力与不可对冲风险的均衡定价。 | 指数与个股的客户净持仓不同，支持分产品先验；不是从公开OI或IV唯一反推出库存的算法。 |
| 4. Bollen、Whaley — [Does Net Buying Pressure Affect the Shape of Implied Volatility Functions?](https://www.whaley.info/_files/ugd/1362e1_81f94ba850fb4ec4aea173770b355408.pdf) | 2004期刊全文；SPX及活跃个股成交报价，推断主动买压并研究IV曲面，另有交易模拟。 | 买压与IV有关，但主动方不等于MM身份；示例加入Vega对冲后收益可转负。工具价格与风险对冲必须单独核算。 |
| 5. Lakonishok等 — [Option Market Activity](https://www.business.kaist.ac.kr/faculty/inmoo/Articles/lakonishokLeePearsonPoteshman22May2006.pdf) | 实读2006完整工作稿，2007发表；分类持仓及成交，家庭券商数据核对策略动机。 | 个股卖期权与备兑Call重要；不能把指数保护性Put的先验套给每只股票。该研究是持仓描述，不是交易胜率。 |
| 6. Collin-Dufresne、Fos、Muravyev — [Informed Trading in the Stock Market and Option-Price Discovery](https://finance.unibocconi.eu/sites/default/files/files/media/attachments/Collin%2520Dufresne_Paper20181029100525.pdf) | 实读2018完整工作稿，2021发表；13D披露所识别的股票知情交易，结合期权报价及部分分类流。 | 期权也会从股票市场学习；必须先建强价格／股票流基线。后来披露的交易不能倒填为当时已知特征。 |
| 7. Hu、Kirilova、Muravyev、Ryu — [Options Market Makers](https://www.fma.org/assets/docs/Derivatives2025/Muravyev.pdf) | 实读2025-02完整稿；2010—2014韩国匿名可追踪账户，作者按行为筛选43个MM类账户；另作美国日度比较。 | 库存常在期权内部净额化，不是全部立即传导到股票／期货。MM身份是作者筛选，不能当交易所标签，也不能直接外推至2026美股。 |
| 8. Muravyev、Pearson、Pollet — [Why Does Options Market Information Predict Stock Returns?](https://fmai.memberclicks.net/assets/docs/Derivatives2022/MuravyevPearsonPollet.pdf) | 实读2022完整稿，2025发表；股票、期权和借券费用，检验IV价差及skew预测关系。 | 借券／套利约束解释部分表面信号；看跌预测不自动产生正的Put净收益。借券费用也不能直接当作未对冲多Put的现金扣款。 |

### Gamma反馈和近期0DTE研究

| 编号与原文 | 实际核读版本及数据方法 | 对本项目的用处和边界 |
| --- | --- | --- |
| 9. Barbon、Buraschi — [Gamma Fragility](https://alexandria.unisg.ch/server/api/core/bitstreams/25fec636-90a2-4735-a3a4-dfc0b68d3feb/content) | 2020-11完整稿；1996—2017 OI／Greeks和标的日内数据，固定符号代理、面板及流动性交互。 | 负代理Gamma与冲击延续、较高波动相关；库存未观测，因果仍有限。其premium加权／ADV单位不同，不能搬用本项目美元GEX阈值。 |
| 10. Baltussen、Da、Lammers、Martens — [Hedging demand and market intraday momentum](https://academicweb.nd.edu/~zda/intramom.pdf) | 2021期刊全文；多类期货的尾盘动量，扩展窗口预测；SPX子研究按滞后Gamma代理分组。 | 先前日内方向在负Gamma状态下更有延续性。正Gamma组不显著，不等于证明可以反向做。先让GEX模型战胜普通尾盘动量。 |
| 11. Beckmeyer、Moerke — [End-of-Day Momentum in the Cross-Section and Option Hedging](https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2021-Leeds/papers/EFMA%202021_stage-2049_question-Full%20Paper_id-237.pdf) | 2021完整工作稿；美国个股面板，对照Gamma水平及Gamma×此前收益。 | Gamma水平本身不预测有符号收益，交互项才有信息；示例毛收益接近其引用成本。不能把高毛Sharpe当零售可执行结果。 |
| 12. Anderegg、Ulmann、Sornette — [The impact of option hedging on the spot market volatility](https://www.research-collection.ethz.ch/server/api/core/bitstreams/e0950a86-3756-4e24-b5e9-344a7299a874/content) | 2022期刊全文；公开DTCC外汇期权流、推断主动方、假设MM承接，估计波动反馈。 | 机制关系存在，但附录交易尝试Sharpe接近0，点差后无利可图。覆盖不完整且无参与者标签；不是美股方向预测证明。 |
| 13. Amaya、Garcia-Ares、Pearson、Vasquez — [The Price Impact of Hedging Expiring Index Options](https://algoseek.com/wp-content/uploads/2026/10/ssrn-7330098.pdf) | 2026-08完整工作稿；2020—2023 Cboe真实容量分类成交，库存递推，多腿组合，区分到期Delta撤除与Gamma再平衡。 | 到期现金结算Delta对冲平仓可提供有符号压力；多腿结构会改变单腿暗示的Gamma。未知老合约初仓仍在；SPXW不能直接套QQQ／个股。2025同组稿不另计数。 |
| 14. Egebjerg — [Deep hedging 0DTE options](https://pure.au.dk/ws/files/457136710/1-s2.0-S1572308926000379-main.pdf) | 2026期刊全文；真实SPX／期货分钟报价，TD3成本与风险目标，时间留出2023测试。 | DL可研究已知期权仓位的对冲，不是估计全市场库存。部分ES更差；2020危机压力分析使用之后年份训练，不能声称当时可部署。 |

### 到期结构和尾部风险

| 编号与原文 | 实际核读版本及数据方法 | 对本项目的用处和边界 |
| --- | --- | --- |
| 15. Avellaneda、Lipkin — [A market-induced mechanism for stock pinning](https://math.nyu.edu/inmemoriam/avellaneda/qf3601.pdf) | 2003期刊全文；长Gamma对冲者、价格冲击弹性与外生波动的理论模型及案例。 | 钉住需库存方向与冲击参数；OI本身不能给已校准概率。案例不是样本外胜率，更不是Max Pain必然吸引价格的证明。 |
| 16. Stoll、Whaley — [Program Trading and Expiration-Day Effects](https://www.whaley.info/_files/ugd/1362e1_b2396cce6e3b4b7fbae1d74fb2567c58.pdf) | 1987期刊全文；早期指数／期货分钟数据，到期、非到期及反转比较。 | 到期效应与同时到期的期货、流动性有关；旧制度的反转幅度不等于今日可交易利润。须分离期货与期权到期。 |
| 17. Stoll、Whaley — [Expiration-Day Effects: What Has Changed?](https://www.whaley.info/_files/ugd/1362e1_046c549103944c719d7d688cf8325e3e.pdf) | 1991期刊全文；结算由收盘改开盘前后比较。 | 冲击可从收盘移往开盘。结算时点是模型变量，不能把AM／PM、指数现金结算、ETF实物交割混在一起。 |
| 18. Rockafellar、Uryasev — [Optimization of Conditional Value-at-Risk](https://sites.math.washington.edu/~rtr/papers/rtr179-CVaR1.pdf) | 实读1999作者完整稿，2000发表；情景优化与非线性期权组合示例。 | 将尾部平均损失纳入优化；不是GEX alpha证据。情景CVaR不是最大亏损保证，离散损失不能简单平均“严格超过VaR”的少数样本。 |
| 19. Israelov、Nielsen — [Covered Calls Uncovered](https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/Covered-Calls-Uncovered.pdf) | 2015期刊全文；备兑收益拆为股票、卖波动和动态Delta；研究日度对冲。 | 备兑仍保留股票下跌与卖波动风险。全样本平均Delta适合归因，生产应改历史估计；到期日成交口径会实质改变模拟收益。 |
| 20. Santa-Clara、Saretto — [Option strategies: Good deals and margin calls](https://www.anderson.ucla.edu/documents/areas/fac/finance/santa_clara_option.pdf) | 实读2004 UCLA完整稿，2009发表；买卖价差、保证金和强制平仓模拟。 | 漂亮的权利金回报可被资本约束与追保打掉。必须报告占用风险资本的收益；旧稿和终版范围不同，不能混用数字。 |

### 工具定价和风险决策

| 编号与原文 | 实际核读版本及数据方法 | 对本项目的用处和边界 |
| --- | --- | --- |
| 21. Terstegge — [Intermediary Option Pricing](https://www.fma.org/assets/docs/Derivatives2025/Terstegge.pdf) | 2025-11完整工作稿；分类库存、隔夜流动性变化、情景重定价和shadow gamma。 | 现价Gamma小不代表大跌后风险小，需全路径／全曲面压力测试。该稿表IV交互项符号与正文存在冲突，本研究不采用其系数方向。中价收益不等于成交利润。 |
| 22. Bakshi、Kapadia — [Delta-Hedged Gains and the Negative Market Volatility Risk Premium](https://people.umass.edu/~nkapadia/docs/Bakshi_and_Kapadia_2003_RFS.pdf) | 2003期刊全文；1988—1995 SPX、14—60天期权，日度Delta对冲及Vega检验。 | 长期权承担权利金、波动／跳跃风险溢价，预测大振幅不等于买期权划算。不是0DTE或本项目GEX规则验证。 |
| 23. Buehler、Gonon、Teichmann、Wood — [Deep Hedging](https://arxiv.org/abs/1802.03042) | 实读2018 arXiv v1完整稿，2019发表；Heston模拟、凸风险目标、交易成本和独立模拟测试路径。 | 学习对冲策略可优化指定风险目标；风险厌恶提高可牺牲平均收益。该实验不是实盘alpha，也没有恢复未知做市商库存。 |
| 24. Muravyev、Pearson — [Option Trading Costs Are Lower Than You Think](https://c.mql5.com/forextsd/forum/209/Option%20Trading%20Costs%20Are%20Lower%20than%20You%20Think.pdf) | 实读2015作者完整稿的公开副本；[2020正式发表题名](https://sfs.org/editors-choice-3311/)为Options Trading Costs Are Lower than You Think。用滞后IV与标的tick变化预测期权价值、检验成交时机。 | 合理价值基准不同会改变成本测量；不意味着我们能按中间价成交或自动打折成本。历史39个活跃标的样本不是今日全部期权；未读2020终版主文。 |

## SqueezeMetrics以外该比较什么

[SqueezeMetrics原始白皮书](https://squeezemetrics.com/monitor/download/pdf/white_paper.pdf)明确假设投资者卖Call、买Put，MM承接另一边，得到Call正、Put负代理；同时近似对冲行为。它不是实际库存查询。白皮书原生的`Gamma×OI×±100`与本项目每1%价格变化的名义美元口径不同。行业白皮书不计入上面的24篇学术文献。

没有证据表明一个库存模型在所有产品、期限、市场制度上都最好。建议保持同一预测和成交框架，只替换库存输入，公平比较：

| 模型 | 可做什么 | 识别边界 |
| --- | --- | --- |
| U 无符号集中度 | 使用完整链的OI×乘数×Gamma，标出集中区域和期限贡献 | 不声称MM多空，不把集中区自动称支撑／阻力 |
| B 固定Call正／Put负 | 低成本、透明、易复核的基准 | 净方向与全部OI归属是假设 |
| C 分层先验 | 指数／ETF／个股、DTE、价内外程度分别设库存倾向 | 没有标签时是敏感性情景，不是校准概率；文献3、5提示产品差异 |
| F 分类流更新 | 有真实MM买卖分类时递推库存，组合腿合并、撤销更正另处理 | 流量不等于完整存量；保留未知初仓、跨交易所及场外缺口，见文献13 |
| P 潜在库存模型 | 作为我们的候选设计，用有误差标签更新隐状态，比较训练期与未来表现 | 没有标签就不能称已校准Bayesian库存；复杂滤波也不能凭空识别q0 |
| T 部分／滞后对冲 | 对相同库存假设，不同对冲比例、延迟、工具替代做情景 | 文献7提示不能把所有GEX一比一当作股票订单；比例本身也须估计 |
| S 大幅变动重定价 | 在S、IV、skew、时间变化后重算全链及组合风险 | shadow gamma改进非线性风险表述，不会修复未知库存方向 |

正确的净库存会计为`q_MM=多头−空头`：MM买入增加q，包括买入平空；MM卖出减少q，包括卖出平多。到期、行权、指派和合约调整单独处理。不能只累计开仓，更不能把公开主动买直接填入“MM买入”。

分类数据必须带可得时间。交易所T+1交付的真实分类流可以用于事后诊断，不能假装为同日实时信号。若未来购买数据，还要核对所覆盖交易所、到期／行权调整及派生展示许可；本次没有购买。

## 用GEX判断延续或反转

在本项目的符号下，定义：

```text
q_i = MM多头合约数 − MM空头合约数
G(S,t) = 0.01 × S² × Σ q_i M_i Gamma_i(S,t)
H(S,t) = −Σ q_i M_i Delta_i(S,t)   # 理想化的标的Delta对冲股数
```

仅考虑小幅价格冲击时，按当前标的价格计价的对冲交易名义金额近似为`−G×(收益率/0.01)`。这是买卖流的近似，不是整个对冲持仓的市值变化；后者还包含价格对原持仓的影响。这说明正Gamma对冲者可能逆着已有冲击交易，负Gamma对冲者可能顺着已有冲击交易；**两者都没有直接给出冲击最初向上还是向下**。

实际还包含IV变化、时间推进、库存新流及对冲替代：

```text
dH ≈ −Σ qM Gamma dS
     −Σ qM Vanna dIV
     −Σ qM Charm dt
     −Σ M Delta dq
```

这里Charm明确采用对日历时间求导的约定；这只是局部近似。大跳空用全量重定价，不能依赖局部Greeks。模型对冲需求也不等于已经观察到的实际买卖。

研究特征应使用**已经发生且当时可知**的冲击，例如`G_t×过去15分钟收益`，而不能把未来价格变动代入再宣称预测成功。文献10、11支持检验这一交互，但没有证明所有正Gamma日必反转。

还有一种不同的方向机制：现金结算到期使相关期权Delta退出，原来的Delta对冲要撤除。文献13研究的是这类到期Delta压力与时钟，不能把它误叫“Gamma正就看涨”。本项目先研究SPY／QQQ，其实物交割和提前行权机制与SPXW不同，必须另做实验。

## Max Pain如何变成目标区域

对单一到期日、固定且完整的OI快照：

```text
L(x) = Σ Call_OI × M × max(x−K,0)
     + Σ Put_OI  × M × max(K−x,0)
MP_t = argmin_x L(x)
```

MP可以是区间。它是到期理论内在价值的最小点集，不含权利金、建仓成本和对冲，不是“实际MM利润最大点”。缺失OI不能填0，全0不发布有意义目标；完整链、乘数及非标准交割条件必须核实。不同到期日独立计算。

我们的候选特征是到**当时冻结**的MP区间的有符号距离，除以相应期限的预期价格波动。现价在区间内单列，平坦无界目标不伪装成精确价位。之后分别统计价格是否靠近、是否曾触及、最终是否留在附近，以及MP自己移动了多少。

强对照包括最近ATM行权价、附近整数、最大OI行权价、初始距离和区间宽度匹配的安慰剂，以及普通动量／反转模型。GEX、PCR和MP往往共享OI，三者一致不是三份独立证据。

直接相关工作[No Max Pain, No Max Gain: A Case of Predictable Reversal](https://ssrn.com/abstract=4140487)确实存在。本次未取得可合法读取的完整稿，不计入24篇。新版摘要把收益主要联系到此前大跌后的反转；[作者旧版页面](https://sites.google.com/view/iliasfilippou/working-papers)仍写与反转无关。完整版本、样本、成本和可得时间核对前，不引用其收益数字或宣称复现。

[Ni等2005到期聚集研究](https://www.sciencedirect.com/science/article/abs/pii/S0304405X05000577)和[Golez、Jackwerth2012](https://www.sciencedirect.com/science/article/abs/pii/S0304405X12001365)只取得部分原文，亦不计入24篇。后者的pinning／anti-cross-pinning比较尤其提醒：产品与结算机制可能改变方向。行权价附近聚集不是Max Pain独立有效性的证明。

## 把判断写成可执行的待检验规则

下表是**我们的实验假设**，不是这些论文原封不动提供的交易系统，也未在真实期权历史上验证。

| 场景 | 必须等到的价格行为 | 候选交易 | 失效或不交易 |
| --- | --- | --- | --- |
| 上方区域拒绝 | 触及预先冻结的上方集中区，完成的5分钟bar重新收回区内下方；部分正Gamma情景支持均值回复 | 研究买Put／Put借记价差，目标先比较冻结MP区间最近边界与价格支撑 | 有效站上区域、重大事件、库存情景敏感、净边际不足 |
| 下方区域反弹 | 触及预先冻结的下方集中区后收回，独立价格／流条件转强 | 研究买Call／Call借记价差 | 有效跌破、流动性恶化，或期权报价已经隐含过高反弹幅度 |
| 突破延续 | 收盘突破冻结区域，再回踩守住；已有同向冲击，部分负Gamma情景支持反馈放大 | 向上研究Call／向下研究Put或相应借记价差 | 假突破、无可执行报价、预期收益不足以覆盖成本／尾部预算 |
| 到期收敛 | 只在已验证的产品和到期窗口，冻结MP优于近ATM／普通反转后，才启用条件收敛模型 | 先比较标的交易与期权结构的净收益 | MP移动解释了表面收敛、事件冲击或样本外失效 |
| 不确定 | 来源陈旧、缺链、先验翻号、组合腿不明、未知结算或风险预算不足 | 不交易 | 等待新数据或取消该观察 |

**虚构手算规则示例**：假设标的100，上方集中区101.8—102.2，冻结MP为99.5—100.5。价格曾越过102.2，随后一根完成的5分钟bar收在101.8下方，才产生“研究回落”的候选；如果站稳102.2并回踩守住，则研究的是延续。不是“高于102就自动买Put”。以上数字不是任何真实证券的当前点位。

候选回落出现后，还要比较实际链中流动性合格的Put和Put借记价差。例如研究7天剩余期限、102／100的Put借记价差，必须明确为买102 Put、卖100 Put、相同到期日及乘数；其收益取决于真实入场净借记、退出时S／IV／剩余时间，不得只看到期内在价值。这里只定义一个可测试合约模板，不是推荐实际下单。不同期限和Delta的选择只在训练期完成。

每个信号必须生成交易卡：`as_of／available_at → 数据版本 → 库存情景 → 方向与触发区 → 确认条件 → 实际合约和买卖方向 → 可执行入场价 → 数量和风险资本 → 止盈／止损／时间退出 → 失效理由`。触发后只能使用信息实际可得之后的报价；触及止损不保证止损价成交。期权腿缺报价或无法同步成交时不得假设自动成套成交。

## 收益最大化应受哪些尾部约束

研究目标应是选择**预期净收益和尾部损失更合适**的动作，而非最大化回测最高收益：

```text
候选动作a包含不交易、标的交易及允许的期权结构
Pi_a = 按可执行价计算的退出价值 − 入场成本 − 手续费 − 对冲／执行成本
选择a使 E_P[Pi_a | 当时信息] − lambda × ES_alpha(−Pi_a) 较高
同时满足现金／保证金、单笔与组合风险、流动性及持仓集中度约束
```

这里的`P`是未来实际收益与IV的预测分布，不是直接把风险中性定价概率当成真实上涨概率。必须联合研究标的路径、IV水平／偏斜、时间和报价；止盈／止损还需要路径，而非仅终点。上式不保证找到未来全局最优收益。

尾部压力至少包含：跳空、IV暴涨／崩落、偏斜变化、报价变宽、停牌或无法平仓、组合腿错位、提前指派、到期产生股票、同产业股票一起下跌及保证金强平。半导体和AI股的风险预算按组合合并，不能每只都单独满仓。

GEX是市场结构风险的一种估计；**我们自己组合的Delta／Gamma／Vega、现金和尾部损失必须另算**。文献21支持大幅变动后重算曲率，文献18、20支持风险资本和尾部约束。理论限定损失的价差也要求匹配合约与到期、管理部分成交及行权，不能把到期payoff上界当作所有操作状态下的保证。

第一阶段优先比较标的和明确风险资本的买入／借记价差；没有证据前不把裸卖0DTE当默认。此项是研究顺序选择，不代表上述结构已经盈利。

## 2025和2026年值得跟踪的方向

1. **真实容量分类与多腿组合，而非只给OI换符号。** 文献13把交易者分类、系列上市起始库存和组合腿用于重建；仍保留老合约和跨所缺口。
2. **对冲到底发生在哪里、发生多少。** 文献7区分期权内净额化与期货Delta对冲；文献13区分Gamma再平衡与到期Delta撤除。
3. **局部Gamma之外的非线性尾部风险。** 文献21在大幅价格变化后重定价；这与“现价GEX正所以安全”不同。
4. **公开数据能否增加波动预测信息。** [Ardia、Vaudescal 2026](https://ssrn.com/abstract=7202999)是相关工作稿，但本次仅核摘要／作者版本信息；共享OI种子的高相关性不能证明恢复了真实库存。
5. **0DTE整体作用仍有分歧。** [Adams等2026合并稿](https://ssrn.com/abstract=5641974)摘要强调稳定作用；[Brogaard、Han、Won 2026修订稿](https://ssrn.com/abstract=4426358)摘要强调波动上升。一个研究Gamma渠道、另一个研究0DTE参与整体冲击时，估计对象可能不同。两篇完整识别设计本次未取得，不把摘要差异判成谁对谁错；合并前旧稿也不重复计数。
6. **风险目标明确的DL对冲。** 文献14、23提示损失函数、训练时期及交易频率会改变尾部结果。DL／GenAI可以研究分布和情景，但不能用合成路径充当真实历史OI或市场外样本证据。

另找到[Dealer Gamma Exposure and Overnight Gap Risk](https://ssrn.com/abstract=6650858)，只有摘要可核，未将其增量效果数字当成验证结果。隔夜跳空幅度预测也不等于涨跌方向。

## 结合现有项目的最小实验

现有结构与数据准入详见[期权研究SPEC](../specs/OPTIONS_RESEARCH.md)及[已有GEX模型审计](GEX_MODELS_RESEARCH.md)。当前实现有TOY情景数学、Max Pain计算和数据审计；现有标的历史5分钟数据不能替代逐时点历史期权链。**符合时点／完整链要求的真实GEX／Max Pain预测评价样本目前仍为0；本次未新增交易回测结果。**

建议按以下顺序实施，而不是先把截图规则上线：

1. **采集和冻结**：先SPY／QQQ，保存链覆盖、有效到期日、OI、乘数、IV／Greeks／报价及来源；分别记录数据时间和实际可得时间。OI未披露有效日期保持未知。只有快照就前瞻采集，不补造历史。
2. **标的方向与波动实验**：用15／30／60分钟标签，先比较价格／RV／IV／成交量／价差／时段／事件基线，再加U、B、C、MP和各交互。方向、振幅、目标触及分别预测。没有足够期权价格时只报告标的事件研究。
3. **库存和对冲敏感性**：同一日期、同一执行规则比较固定符号、分层情景、流更新及对冲延迟。真实分类流若仅T+1可得，只作当时可用滞后特征或事后诊断。无标签时不报告真实库存恢复误差。
4. **期权损益实验**：有同步PIT期权报价后，才能比较具体Call／Put／价差。以实际买卖价、延迟、费用和可成交量计算；限价成交须独立模型，不能总按mid成交。纳入IV路径、提前指派与期末处理。
5. **时间推进验收**：walk-forward，训练期选参数；隔离重叠15／30／60分钟标签，同一标的／到期日簇不能跨训练测试泄漏；最终测试期独立保留。按独立交易日和到期簇报告样本，不把每分钟当独立证据。
6. **增量和失败报告**：基线→GEX→MP→两者→流信息，报告校准／预测损失改善、净收益、换手、ES、最大回撤、最差跳空和不交易比例；同时展示失败日期及跨时期稳定性。多模型、多目标做多重检验控制。

淘汰规则：若GEX／MP不能稳定优于普通价格／反转及近ATM目标；若扣成本后优势消失；或方向完全依赖无法核实的库存先验，就保留为**期权敞口集中度与结构参考**，不发布“真实MM仓位”“必守墙位”或自动下单信号。

本次交付是文献和实验决策设计。未改动HF页面、预测算法、自动交易状态或券商授权。原文阅读记录、版本、页码与未取得全文的项目保留在本机，便于后续逐篇复核。
