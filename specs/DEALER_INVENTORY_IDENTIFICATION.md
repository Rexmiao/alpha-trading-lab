# 做市商净持仓方向识别研究规格

版本0.3，2026-11-27，America/New_York。此专题优先回答“谁持有期权多头／空头”，不是先给OI设正负再画图。它补充[期权研究SPEC](OPTIONS_RESEARCH.md)，不会改变当前交易模式或使研究信号获得执行资格。本次实现免费样本的本机会计验证、方法目录及独立TOY初仓敏感性，没有训练或校准真实库存模型。公开方法页的发布另验。

## 1 实际状态和研究对象

最新[本机审计](../docs/MOOMOO_DEALER_INVENTORY_AUDIT.md)已取得SPY／QQQ两个到期日静态记录2118份、其中8份所选合约的动态字段，以及4份近到期合约各100笔成交。该moomoo窗口仍缺盘口源时间、MM买卖侧身份、完整成交和初始库存。另已取得外部Cboe旧日期部分capacity样本，不等于moomoo同期标签；当前跨源同日匹配、可训练的跨日期留出面板及历史全链留出结果仍未完成。实际来源、免费资格、费用及许可见[MM分类数据研究](../docs/MM_CLASSIFIED_DATA_SOURCES.md)。

逐合约、逐时点、在明确参与者群体和交易所范围内定义：

```text
q_i,t = MM_long_contracts_i,t − MM_short_contracts_i,t
delta_q_trade = MM_buys − MM_sells
q_next = q_previous + delta_q_trade + nontrade_adjustments
G_call = 0.01*S²*sum_call(q_i*M_i*Gamma_i)
G_put  = 0.01*S²*sum_put(q_i*M_i*Gamma_i)
G_total = G_call + G_put
```

OI始终非负。普通vanilla多头Call／Put的Gamma均为正，各自净贡献的正负由q决定。一个标的不同Call可以分别净多或净空，Put亦然；Call、Put合计相抵时总GEX可接近0。方向研究分别报告合约q、Call贡献、Put贡献和总GEX，不能用一个总符号替代所有合约方向。

MM买平减少空仓，因此增加q；MM卖平减少多仓，因此减少q。**若MM买卖侧和数量已知，开平标签不是计算成交净变化的必要条件**；开平帮助重建多／空总账及核对OI，不能因只有open标签才累计。MM买卖双方都属于同一目标群体时净变化相抵。部分成交、撤销更正、到期、行权指派和交付调整另处理。

## 2 五层任务分别验收

| 层次 | 要预测或重建什么 | 独立标签与边界 |
| --- | --- | --- |
| 主动方 | 谁主动买或卖 | 可靠主动方标签；vendor BUY／SELL仅是另一分类器输出，不作独立真值 |
| MM侧身份 | 买方／卖方是否属于目标MM群体 | capacity或可核参与者标签；主动方与MM身份不等价 |
| 库存增量 | 区间内delta_q | 同范围真实MM买减卖及更正，不需要把开平再反号 |
| 库存存量 | q及净多／净空 | 已核q0、连续覆盖及非成交调整；增量准确不代表存量准确 |
| Gamma贡献 | Call、Put及总GEX | 同一时点、同范围q标签及已核Greeks／乘数；真q误差与定价误差分开 |

价格后来上涨／下跌、Max Pain、PCR、供应商GEX与模型预测收益都不是q的真值标签。预测用途与库存识别分别验收，不允许通过挑选最赚钱的正负假设来宣布真实持仓方向。

## 3 模型比较和启用条件

| 模型 | 方法 | 输出和启用条件 |
| --- | --- | --- |
| B 固定符号 | Squeeze Call正／Put负 | 仅基准假设；不是观测或拟合库存 |
| U 无符号 | 同链OI×Gamma×乘数 | 仅集中度，不参加q方向准确率排行 |
| F1 主动流代理 | 保存vendor dir；有历史同步报价后另做透明quote-rule | 当前可离线输出原生数量加权净主动流、neutral、覆盖和未知率；`q=null`，不命名为MM净流 |
| F2 MM侧分类器 | 在同范围capacity标签上，先研究逻辑回归等透明模型，再与非线性候选比较 | 必须有独立时间留出的MM侧标签和校准；没有标签不生成经校准概率 |
| R 已分类库存重建 | 累计真实MM买减卖，处理组合／更正／调整和起始仓 | 最先可验证的是delta_q；只有q0与覆盖同时通过才报告存量q |
| P 潜在状态模型 | 由分类误差、未知q0、缺失流和调整构成状态转移／观测模型 | 训练期估计分层参数；无标签时只可作假设敏感性，不能称已校准后验 |

“分层”指有数据支持的产品、DTE、价内外、流动性和交易条件差异，不是手动给每类设一个正负系数后改名为学习模型。现有`gex_scenarios.py`的`dealer_fraction/p_long`仍是教学情景，`advance_mm_inventory`只是声明输入下的会计函数，本次未升级为F2／R／P。

F2的标签保留买侧MM、卖侧MM，可用`buyer_only/seller_only/both/neither`四类；MM可能在两边，不能强迫买侧和卖侧概率之和等于1：

```text
E[delta_q_trade | X] = quantity * (P(MM_on_buy_side | X) − P(MM_on_sell_side | X))
```

概率由实际capacity标签训练与校准。标签没有到达或范围不匹配时，该式只定义未来任务，不代入主观概率产生“数据驱动q”。从报价推得aggressor概率不能替换MM侧概率。

R/P必须显式处理未知q0：从合约首次上市起完整观测可以采用上市前q0=0；任意抓取日或warm-up结束不能设0。重连缺口不能清零；买卖覆盖、参与者群体或交易所范围改变要传播为未知。到期清除的是对应到期合约，不自动解决其他长期合约初仓。

同一账本有效时间的全市场OI可约束`−OI<=q_MM<=OI`，不能决定符号。昨日或有效日期未知的OI不能硬截断今日盘中库存；后到OI也不能回填过去决策。情景区间跨0时保留`DIRECTION_UNKNOWN`。

## 4 数据契约

所有数据保存`source_id/source_version/schema_version/request_scope/raw_sha256`。不读取用户券商账户来充当全市场MM真值。原始市场响应留本机忽略目录，公开只用获准的安全聚合研究结果。

| 表 | 核心字段 |
| --- | --- |
| 合约参考 | contract_id、underlying、call_put、strike、expiry／settlement_at及timezone、exercise_style、settlement_type、multiplier及有效时间、standard／deliverable、venue_scope |
| 成交 | trade／sequence／exec_id、event_at、price、quantity及单位、buyer_capacity、seller_capacity、buy／sell_open_close、trade_condition、exchange、complex_exec_id／leg_id、cancel／correction_ref |
| 报价事件 | quote_id、bid／ask与size、venue／NBBO覆盖、quote_event_at及精度、received_at、available_at、有效标志、时钟和序列 |
| OI | contract_id、OI、oi_effective_at、oi_publication_at、vendor_updated_at、received_at、available_at、revision_ref、链覆盖证据 |
| Greeks／IV／标的 | snapshot_id、spot、IV及单位、各Greeks及单位、模型、乘数、各字段时间／有效标志、利率／股息来源、链覆盖 |
| 库存状态 | population／scope、as_of、available_at、q0_method、q／q_lower／q_upper、observed／estimated_delta_q、缺口／调整、model_version、identification_status、calibration_status、拒绝原因 |
| 真值标签 | label_type、target_scope、value、effective_at、first_available_at、revision_available_at、truth_quality、q0_identified、coverage_gaps、capacity_provenance、sampling_unit／sampling_known、counterparty_observed |

`capacity_provenance`区分exchange_reported、behavior_inferred与vendor_estimated；不能只因列名为dealer就归入真实MM标签。交易所capacity是其规则定义下的参与侧分类，不等于MM机构名称或最终受益人。合约键保留原始option root、精确Decimal strike、expiry、C/P、交付物／调整和venue；不得以stock symbol替代完整身份。

字段缺失保留null或unknown，不填0。0可能是合法OI或Greeks，须保留供方有效性，不能为消除缺口一律删除0或视为有效。只统计present／finite不构成经济验证。实际观察到的多个100不相乘，也不把100强填到未知交付物。CLI IV为百分数的路线只在定义核实后转换，供应商原值及单位同时保留。

当前桌面盘口没有返回源时间，不可通过本机接收时间伪造quote_event_at。保存“盘口前→最近100笔→盘口后”只能描述采样顺序，不能还原每笔发生前的历史NBBO。本轮三个逐笔窗口存在最大源时间比本机接收时间晚约65—279ms，时钟对齐尚未核实；必须保留、诊断并阻止严格时点推断，不能静默修复。旧REST归一化事件丢失过报价字段，未来原始私有归档须先保留实际收到字段再生成规范表。

## 5 采集和可得时间

当前提供前台有界审计器[scripts/audit_moomoo_option_data.py](../scripts/audit_moomoo_option_data.py)，不是持续采集器。只允许SPY／QQQ／NVDA中最多两个标的、每标的前两个到期日、每期近现价一组Call／Put；最近到期各100笔，盘口1档，每请求15秒、全轮最多30次。原始响应和哈希仅写`state/dealer-inventory-audit/`。错误只保存安全类别／数字，不保存可能含凭据的原stderr。

本次v1实际档为保留s2c的重序列化行情JSON，`sha256`是该文件哈希，不是原始传输字节证明。当前v2另在预期空消息成功信封中保存原stdout字节及独立哈希；归档格式和是否保留原字节明确记录。禁止回写旧文件或把规范表哈希改名为原始字节哈希。

每条观测区分市场event_at、供方更新时间、OI有效与公布时间、请求／实际接收、available_at。未知时间保留null；当前抓到的历史打印可以从收到时刻开始被本系统知道，不能作为更早预测特征。市场事件发生较早不等于程序当时已知。

后续连续流采集是未实现阶段：需要独立核验逐笔与报价推送、时钟、序列、乱序、更正、断流、覆盖和许可，预注册采样范围。当前`get-ticker`最近N笔窗口没有历史翻页，重复轮询可能重复或漏笔；不能把无跳号当跨所全覆盖证明。不得未经授权部署常驻进程、任务或付费订阅。

期权到期时钟单独核实，不能从标的XNYS常规／提前收盘自动推断每种期权／指数结算时刻。事件控制同样需要实际可得时间。

## 6 验证和失败条件

训练、标准化、分层和阈值只用训练期可得信息。标签必须在fit_at前真正到达；交易所T+1分类文件可作事后标签或之后的滞后特征，不能伪装成当天实时特征。最终修订标签和首次到达版本分别存，滤波仅用过去，未来平滑只作事后诊断。

采用时间推进的walk-forward，保留最终独立测试期；同标的／到期簇、同日相关样本不能随机跨折。报告独立日期／到期／标的／交易所数，不只报逐笔数量。跨产品单报，韩国账户行为不能直接校准美国MM概率。

| 验证任务 | 满足标签要求后的指标 |
| --- | --- |
| 主动方分类 | 混淆矩阵、MCC／平衡准确率、未知率及按交易条件分组；与vendor标签只能算一致率 |
| MM侧概率 | 买侧／卖侧或四类的Brier／log loss、校准曲线、拒绝率及覆盖 |
| 库存增量 | delta_q MAE、偏差、累计漂移和数量加权误差；不代替存量结果 |
| 库存存量 | 仅q0和覆盖通过者的q MAE、正负MCC／平衡准确率、区间覆盖与宽度 |
| Gamma贡献 | 同链／同Greeks下Call、Put及总GEX的误差与符号；零附近不判定带在训练期固定 |

没有相应真值时该层指标返回`NOT_ESTIMABLE`，不报告准确率或校准概率。共同Greeks仅用于隔离库存误差，仍不证明Greeks独立正确。组合／跨合约相关性必须保留，不把逐合约95%区间简单相加成市场95%置信区间。

状态及硬门槛：

- `STRUCTURE_ONLY`：只有链／OI／Greeks，不估计q。
- `VENDOR_AGGRESSOR_PROXY_ONLY`：保存供应商主动流，`q=null`、`mm_side_probability=null`，不是MM净库存。
- `HEURISTIC_FLOW_ONLY`：无真标签的独立主动方／身份启发式，必须说明假设，不能冒充已观测MM。
- `SAMPLED_CAPACITY_ONLY`：侧记录有真实capacity，但抽样／缺对侧或连续覆盖未核；报告观测侧标签与缺失率，不称完整区间delta_q，q保持null。
- `OBSERVED_CHANGE_STOCK_UNIDENTIFIED`：真实分类流增量已知，初仓／完整覆盖未过；可报告该范围内增量，不报告完整存量。
- `DIRECTION_UNKNOWN`：识别区间跨0、对初仓／误分／缺口敏感或先验主导，保留拒绝。
- `IDENTIFIED_WITHIN_SCOPE`：只有真实标签、q0、连续覆盖及调整同时有证据才可用；不是全市场或场外全账本。

没有真标签时不得以全多／全空、Squeeze、分层曲线多数票、未来涨跌或供应商GEX作代用真值。只有部分合约时不可称整个标的净GEX；无符号集中度没有q符号，始终排除方向准确率排名。

库存估计之后，才独立检验市场预测及成本后交易价值。方向估计正确也不保证未来价格方向、实际对冲量或期权交易盈利。当前所有期权研究`execution_eligible=false`，不接入S&R入场或券商委托。

## 7 原文依据与当前交付

- [Amaya等2026](https://algoseek.com/wp-content/uploads/2026/10/ssrn-7330098.pdf)：容量分类的库存会计与组合；保留未知旧初仓和ETF跨所缺口。
- [Demand-Based，实读2005稿／2009发表](https://users.nber.org/~confer/2005/URCs05/pedersen.pdf)：真实分类持仓研究需求；不是IV到q的一一逆映射。
- [Bollen／Whaley 2004](https://www.whaley.info/_files/ugd/1362e1_81f94ba850fb4ec4aea173770b355408.pdf)：报价买压为主动流特征，不是参与者标签。
- [Options Market Makers，实读2025稿](https://www.fma.org/assets/docs/Derivatives2025/Muravyev.pdf)：账户内净额化与对冲异质性；MM由作者行为筛选，不是公开美国逐笔真值。

阅读版本和方法边界统一见[24篇综述](../docs/GEX_MAXPAIN_DECISION_RESEARCH_2026-11-27.md)和[论文入口](../docs/papers/README.md)。F2／P是我们的拟实施设计，不声称原文已经验证该模型。

本轮已实现只读审计器、字段与来源归档、有限真实窗口的供应商主动流代理及20项离线安全／解释检查。数据驱动MM侧分类器、q0识别、潜在库存训练／校准、历史库存准确率、完整GEX方向预测和自动交易均未实现／未验收。HF界面仍为0.11.0原教学版本，没有将手动先验改名发布为真实模型。

## 8 外部分类数据接入计划与免费样本验收

本节为0.2数据研究增量，非已实现生产接入器。详情与下载文件哈希见[来源研究](../docs/MM_CLASSIFIED_DATA_SOURCES.md)。免费样本、付费连续交付、真实库存三个等级分开：

| 来源 | 本轮实测状态 | 允许用途／拒绝边界 |
| --- | --- | --- |
| C1 TBT 2025-03-28 3%样本 | 113,018参与者侧记录，58,293为MM；多数执行组仅一侧；有NBBO、side、capacity及exec／complex ID | 真实已观测侧标签和解析验证；采样机制未核，缺对侧unknown，不放大成全流，不做跨期校准 |
| C1 Open-Close样本 | 旧格式EOD及两个日内时点；另有2026-09-30单点新版示例 | MM买卖contract volume，非笔数；1m／10m累计须差分。单点／抽样不代表完整区间 |
| OCC SPY 2026-11-25 | 156行，55为M；root／C/P／venue／day，数量是参与侧数 | 无符号MM活动控制；没有strike和B/S，不生成delta_q或逐合约符号 |
| NYSE匿名旧演示 | 有MM买卖量列，日期均为周六2022-01-22，真实历史来源未核 | 仅格式验证，禁止作为真实交易日训练标签 |
| Nasdaq ISE／GEMX增强版 | 官方2026公告新增MM；未取得增强样本验列，旧历史不含MM | 待schema／覆盖验收，不假设整段历史标签可用 |
| MIAX Open-Close | 已查官方产品及现价，未取得capacity列样本 | 待验收，不将产品名称当已获得真实MM标签 |
| JFE 2024 Mendeley复现包 | 实读README明确pseudo datasets | 仅代码／结构参考，禁止作为真实MM真值 |

TBT解析拟按“日期＋完整合约＋exec_id”恢复已观测侧，复杂单再用complex_exec_id关联；单侧样本不能填`both/neither`。当前样本有69条未解释side=T，必须unknown／拒绝该层符号；open_close缺失不填0，不阻止已知MM B/S净流会计。学习与校准须审计抽样选择偏差，并按执行／组合、日期／到期隔离。

Open-Close观测层固定`y_i,venue,interval=mm_buy_vol−mm_sell_vol`，`qty`为笔数不代替数量。累计差分保留日／session重置和更正版本，负差不能直接截零。汇总只能验证同合约、同venue、同区间的净流，不将汇总标签分摊为每笔moomoo的真实MM侧。多MM对手侧在目标群体内相抵。

现有moomoo缺execution venue和可验证的跨供应商exec_id；sequence不是已知等价ID。价格／数量／相近时间配对必须经过重复与多对多歧义验收，未验通过不叫真值匹配。现有moomoo为2026-11-27，免费Cboe主要样本为2025-03-28／2026-09-30，当前跨源同日逐笔标签匹配N=0；不能拼今天Greeks或静态乘数生成历史GEX。

当以后取得连续同期完整分类流，先验delta_q；未知q0仍不得设零。已覆盖净变化乘同期Gamma仅为库存变化的Gamma贡献，不命名净存量GEX。其他venue、OTC、非成交调整、产品／MM群体差异进入缺口。T+1标签仅在到达后用于fit或滞后特征；保留首次版本和最终修订，未知历史首次获知时间不补造。

采购／试用的候选顺序为：现有$0样本→核对固定2022H2 Open-Close历史或TBT首次用户试用资格→必要时短区间历史。没有申请、购买、登记后台任务或改变券商scope。C2／GEMX较低的公开价不代表本项目标的覆盖最优；先验SPY／QQQ合约覆盖、MM版本、数量口径和时间可得性。

公开HF增加数据驱动结果之前须单独核许可：Cboe Open-Close原始数据限内部使用，派生外发也需批准／附加许可；TBT外部再分发受限。仅隐藏原始下载不能自动取得公开图表权。当前样本和原始文件均留本机ignored state，未发布新的数据驱动结果或改变应用0.11.0。

## 9 免费样本实现与方法目录（0.3）

当前用户授权只使用免费样本，不采购付费数据。本轮新增`research/cboe_mm_sample.py`及`scripts/run_cboe_mm_validation.py`；复跑、输入指纹及展示说明见[最小实验](../docs/CBOE_MM_SAMPLE_VALIDATION.md)。生产连续采集、完整分类流和库存训练仍未实现。

TBT解析显式隔离507条缺有效期权身份的非期权／未证腿；它们含234条MM及全部69条side=T。有效期权为112,511侧，其中58,059为MM。源文件总MM 58,293不能全部称为期权张数。未知side／capacity不强制分类，重复侧记录须拒绝或显式诊断，股票腿不乘期权乘数；时间无时区证据时保留原字符串与未知时区，不因交付时间为ET就认定逐笔事件时间为ET。

验证按目标群体和同合约side计算观察数量，不翻转开平符号；同MM群体双侧等量抵消。对比TBT与同日Open-Close仅用共同完整合约键，并报告抽样／未证覆盖、唯一性、截断和零值类别。观察到反号反映范围敏感性，不是净库存／Squeeze准确率。截断的展示合同表不允许代表全文件交集；完整匹配需单独通过计算上限及覆盖验证。

真实文件缺同期IV／Gamma／spot和乘数，不能得到真实存量GEX。另行声明的TOY Gamma贡献和q0范围仅验证单位、符号与假设传播；不同日期或scope拒绝拼接。q0未知或未声明缺失／其他变化假设时不给净库存范围；声明情景后仍`q=null`，区间不是统计置信区间。

九方法目录在`research/dealer_methods.py`，包括固定符号、先验、无符号、NBP代理、capacity流、需求驱动框架、潜在状态、组合重建和有限风险重定价。数据存在不启用尚未实现的估计器；每项列要求、缺口、来源和输出，`execution_eligible=false`。HF仅包含无行情的方法目录和TOY初仓页，不包括Cboe适配器、样本或数据驱动明细；本机双语HTML默认English。
