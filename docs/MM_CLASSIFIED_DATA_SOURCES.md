# 真实MM分类数据：免费入口、付费比较与moomoo配合方案

核对日期：2026-11-27，America/New_York。此文记录公开官方文档和实际下载的免费样本；没有购买、注册、申请试用、联系供应商、改变券商授权或发布行情。研究契约见[库存识别SPEC](../specs/DEALER_INVENTORY_IDENTIFICATION.md)，现有moomoo字段见[本机审计](MOOMOO_DEALER_INVENTORY_AUDIT.md)。

**结论：找到了带交易所MM分类及买卖侧的免费Cboe样本，适合先做零成本的字段与方法验证；未找到可直接免费持续获得的全市场、逐合约、带方向的MM完整库存。** OCC的免费MM日成交量也已实取，但缺少买卖侧和行权价。付费的Open-Close可观察指定交易所的MM净流量；C1 TBT更细到参与者侧及执行ID。它们仍不是完整持仓账本。

## 1 先区分我们究竟买到了什么

| 数据 | 实际观测 | 能否回答净多／净空 |
| --- | --- | --- |
| OI | 合约未平仓数量，非负 | 不能识别哪类参与者持哪边 |
| OPRA或moomoo逐笔／报价 | 价量、报价；主动方向可能来自推断 | 主动买方不等于客户，另一方也不一定是MM |
| OCC分类成交量 | MM／客户／Firm参与侧数量，日级汇总 | 没有买减卖，不能恢复库存变化 |
| 交易所Open-Close | 合约、交易所、区间内，按capacity拆分的买卖量 | 可识别覆盖范围内的成交净变化；初仓另缺 |
| C1 TBT | 每条参与者侧的capacity、B/S、数量、执行及组合ID | 比汇总更适合研究身份和多腿，但仍缺完整初仓和其他场所 |
| 完整分类仓位账本 | 指定MM群体逐合约多头减空头存量 | 本次没有获得，也未发现免费公开全市场版本 |

这里的“真实分类”是交易所数据中的参与者／订单capacity字段，不是按Ask成交或事后价格变化猜出来的身份；它也不披露MM机构名称、最终受益人或全部场外头寸。Firm、BrokerDealer不自动并入MarketMaker。不同交易所和历史版本须按各自字典解析。

## 2 免费优先：已经核验与尚待申请分开

### 2.1 Cboe TBT：最有价值的逐笔分类样本

[官方产品及下载入口](https://datashop.cboe.com/enhanced-us-options-trade-by-trade-execution-detail)、[直接样本](https://datashop.cboe.com/download/sample/289)、[当前v1.1规范](https://datashop.cboe.com/documents/TBT_Spec_v1.1.pdf)。产品当前为C1、T+1；NBBO覆盖多个场所不意味着成交标签覆盖全美。C2／BZX／EDGX TBT在产品页为后续计划，不能提前算作已供货。历史标称从2019-10-07开始，Greeks是另一个配套产品，不能假设TBT自带历史Gamma。

实际解包的是`C1_TBT_2025-03-28_sample_3pct.csv`：

| 实测元信息 | 结果 |
| --- | --- |
| 参与者侧记录 | 113,018；不是113,018笔完整双边成交 |
| capacity为MarketMaker的记录 | 58,293 |
| SPY／QQQ／NVDA／AMD／MU侧记录 | 7,678／5,005／2,986／469／234 |
| 日期＋完整合约＋exec_id组 | 111,333组；109,648组仅一条侧记录；1,685组具有B/S双侧 |
| 未解释的side值 | `T`共69条，不能强制映射为卖方 |
| open_close为空 | 20,180条，其中MM 19,907条；保留未知 |
| complex_exec_id非空 | 49,332条；必须保留组合关联 |

实际列包括`transact_time/trading_dt/osi_root/expire_date/call_put_flag/strike_price/size/price/side/capacity/open_close/exec_id/complex_exec_id/nbbo_bid/nbbo_ask`等。样本压缩包带旧v1.0说明，生产规范已为v1.1，解析器需要版本化。

这是**真实分类样本**，可以验证“这条观测侧是MM买方还是MM卖方”及报价特征。但抽样机制未核，缺失的对侧身份必须unknown，不能标成非MM；不能乘33.3恢复库存，也不足以做跨日期校准。按同exec／complex事件分组隔离训练与测试，不能把同一成交两侧随机拆开。当前尚未用它训练MM身份模型或报告样本外准确率。

后续实现补充：113,018侧中有507条缺有效期权C/P及root，疑似股票／未证组合腿；包括234条MM及全部69条side=T，必须隔离。有效期权为112,511侧、其中58,059为MM。上述最初58,293是源文件全部MM侧计数，不能全当期权张数。[可复跑的本机验证](CBOE_MM_SAMPLE_VALIDATION.md)已实现，真实逐合约流和反例仅留本机；没有变成已校准模型或历史净GEX。

### 2.2 Cboe Open-Close：真实MM买减卖的合约汇总样本

[官方产品](https://datashop.cboe.com/cboe-options-open-close-volume-summary)、[直接样本](https://datashop.cboe.com/download/sample/218)、[EOD规范v1.3](https://datashop.cboe.com/documents/Open_Close_EOD_Spec_v1.3.pdf)、[1分钟规范v1.8](https://datashop.cboe.com/documents/Open_Close_1m_Spec_v1.8.pdf)。按购买的C1／C2／BZX／EDGX分别供文件，不是默认包含四所。

已解析免费包中的2025-03-28 C1样本：EOD 23,179行、12:30的10分钟文件78,468行、13:16的1分钟文件87,322行。EOD标注20pct，另两个是单时点累计文件；三者完整性均未验证，不是完整连续交易日。EOD中SPY 638行、QQQ 583行。另核验[新版2026-09-30 15:20格式样本](https://datashop.cboe.com/documents/Cboe_OpenClose_2026-09-30_15_20_1.csv.gz)，123,022行、88列，也只有一个快照。

关键字段有`mm_buy_qty/mm_buy_vol/mm_sell_qty/mm_sell_vol`。**qty是笔数，vol是成交数量；净变化使用vol。1m／10m是日内累计值，须差分，不可把每个文件再次相加。** 更正可能使相邻累计差值为负，应按修订处理，不能一律截成0。样本的“20%”抽样单位没有核实，不按20%成交量放大。

历史范围：C1 EOD从2005-01-03，10m从2011-01-03，1m从2019-10-07；其他三所EOD从2018-01-02，日内从2019-03-01。旧OI和总量曾有口径变化，不能用一套解释覆盖所有年份。EOD是隔夜到达；日内数据到达也晚于区间结束。

### 2.3 需要申请、尚未获得的免费历史／试用

当前[C1费表](https://cdn.cboe.com/resources/membership/Cboe_FeeSchedule.pdf)及[C2费表](https://www.cboe.com/us/options/membership/fee_schedule/ctwo)列出符合首次采购／未领取条件者可申请的**固定2022-07-01至2022-12-31** Open-Close EOD／10m／1m历史样本；不是任意选择最近六个月。C1 TBT还有首次用户最多一个月试用条款，具体可选日期、交付及资格需要确认。

这些是可申请路径，不是已获批的免费连续订阅。本轮没有提交申请。若后续取得完整固定历史，先验收SPY／QQQ覆盖、实际capacity及时间字段，再决定是否有足够的跨日期留出实验。

### 2.4 OCC：免费持续活动信息，但不是带符号库存

[Volume Query](https://www.theocc.com/market-data/market-data-reports/volume-and-open-interest/volume-query)、[批量查询说明](https://www.theocc.com/market-data/market-data-reports/other-market-data-info/batch-processing/volume-query-batch-processing)、[字段布局](https://www.theocc.com/getcontentasset/50cf357d-6ec6-436e-a96b-c4710313a472/dfc3d011-8f63-43f6-9ed8-4b444333a1d0/options-volume-query-record-layout.pdf)。`accountType=M`是真实MM分类，C是Customer、F是Firm。

实际匿名获取SPY 2026-11-25 CSV：156行、其中55行M，出现20个交易所代码。字段只有数量、标的／期权root、C/P、账户类别、交易所、活动日及空的合约日期；没有行权价、买卖、开平。`SPY/1SPY/2SPY/4SPY`是root，不能冒充完整OSI合约；表头七列、数据另有第八个空日期尾列，导入时须审计。

[OCC旗下OIC的官方说明](https://www.optionseducation.org/referencelibrary/faq/general-information)明确此类量按contract sides计数。MM侧数占比不能直接当一笔成交的MM对手方概率，也不能与OPRA单计成交量原样比较。适合作为**滞后日级MM活动控制变量**，不能给逐行权价OI分配正负。本次只实测上述单日SPY请求，更长历史、修订、确切发布时间及再分发许可未完成验收。

### 2.5 免费样本／复现包中的两个陷阱

- [NYSE官方样本目录](https://ftp.nyse.com/Historical%20Data%20Samples/NYSE%20OPT%20OPEN%20CLOSE%20SUM%20VOLUME/)下载的EOD为14,355行，具有规范定义的MM买卖量字段；但所有日期标为**周六2022-01-22**，早于说明里的Pillar上线。将其列为**格式演示、历史真实性未核**，不作真实交易日标签。日内例子也同样有此问题。[旧版字段规范](https://www.nyse.com/publicdocs/nyse/data/NYSE_Options_Exchange_Open-Close_Client_Specification_v1.0a.pdf)
- [JFE 2024公开复现包](https://data.mendeley.com/datasets/t6cs4m68df/3)确实有以Cboe等来源命名的数据文件，但实际阅读README后确认提供的是**pseudo datasets**，原始专有数据不能共享。可参考代码，不能作为真实MM训练／验证标签。没有因为文件名或论文免费就认定数据免费。

## 3 付费比较：先核覆盖，后看价格

美元公开价，截至上述核对日；月订阅与购买一个历史数据月是不同计价。下表均为**指定交易所**，不是每只股票价格，也不是全美组合价。最低采购、税费、资格折扣及公开展示权需另核；没有用2027费率提前替代2026费率。

| 来源及证据 | 持续EOD／月 | 持续10m／月 | 持续1m／月 | 历史数据月：EOD／10m／1m | 数据验收状态 |
| --- | ---: | ---: | ---: | --- | --- |
| [Cboe C2现行费表](https://www.cboe.com/us/options/membership/fee_schedule/ctwo) | $500 | $1,000 | $5,000 | $400／$500／$1,500 | 同Open-Close产品；本轮实际样本为C1，不代表C2覆盖已验 |
| [Cboe C1，2026-11-20](https://cdn.cboe.com/resources/membership/Cboe_FeeSchedule.pdf) | $600 | $3,000 | $12,000 | $300–600／$1,000／$2,500–4,000 | MM字段已实测；EOD／1m历史价有多年档位，具体适用条件需报价确认 |
| [Nasdaq GEMX，2026列](https://www.nasdaqtrader.com/content/ProductsServices/PriceList/Nasdaq_US_Options_Price_List_2025_2026_2027.pdf) | $575 | $1,500 | — | $400／$750／— | 2026增强版新增MM；未取得增强样本验列 |
| [Nasdaq ISE，同上](https://www.nasdaqtrader.com/content/ProductsServices/PriceList/Nasdaq_US_Options_Price_List_2025_2026_2027.pdf) | $850 | $2,500 | — | $600／$1,000／— | 同样须区分增强前后，旧历史不自动带MM |
| [NYSE Arca，2026-10-01](https://www.nyse.com/publicdocs/nyse/data/NYSE_Arca_Options_Proprietary_Data_Fee_Schedule.pdf) | $750 | $2,000 | $8,000 | $600／$1,000／$4,000 | 当前产品有MM分类，所下载旧演示日期未核 |
| [NYSE American，2026-10-01](https://www.nyse.com/publicdocs/nyse/data/NYSE_American_Options_Market_Data_Fee_Schedule.pdf) | $750 | $2,000 | $8,000 | $600／$1,000／$4,000 | 与Arca分别收费，不是两所打包价 |
| [MIAX Options，2026-11-01](https://www.miaxglobal.com/sites/default/files/fee_schedule-files/MIAX_Options_Fee_Schedule_11012026_2.pdf) | $600 | $3,000 | $9,000 | $500／$1,000／$4,000 | 有origin／side产品说明，未取得MM列样本，不列为已验真标签 |

**C1逐笔TBT另计：$12,000／订阅月，$8,000／历史数据月。** 比Open-Close更适合逐侧身份与组合重建，但对当前个人项目明显昂贵。不把历史按月单价除以交易日数当保证的一日成交价；局部日期是否按比例、最低订单和symbol限制应由供应商确认。[C1费表](https://cdn.cboe.com/resources/membership/Cboe_FeeSchedule.pdf)

其他重要差异：

- [Nasdaq 2026-05-26迁移公告](https://www.nasdaqtrader.com/TraderNews.aspx?id=DTN2026-7)及[FAQ](https://assets.ctfassets.net/mx0rke14e5yt/71lokR7lXiJBnX49Nuvuur/741a4f9d4e0ab2625ced20003b0f3c9f/Trade_Outline_FAQ_-_Post_ISE_and_GEMX_TO_Migration__2_.pdf)：ISE／GEMX旧产品不包含MM，新增强表才加入；FAQ旧时间表与后续公告不一致，以较新公告和交付文件为验收依据。不能购买多年旧历史后声称有多年MM标签。10m为日内累计，EOD在T+1到达；MM可能没有开平标记，仍可计算买减卖。
- [NYSE现行产品说明](https://www.nyse.com/data-products/catalog/open-close-volume-summary)：按合约和MM等类别拆分买卖，1m／10m／EOD。当前日内交付和累计／区间口径必须按现行规范及样本验收，不能直接沿用旧演示。Arca／American的1m历史在现行费表中从2026-10开始，其他频率历史不同。
- [MIAX产品说明](https://www.miaxglobal.com/markets/us-options/all-options-exchanges/reports)：非会员可订Open-Close；给会员的自家清算报告“No Fee”不等于免费公共MM全市场报告。其TBT标价$10,000／月、历史$6,000／数据月，但capacity字段未验，不拿名称替代schema证据。
- [Databento OPRA规范](https://databento.com/docs/datasets/opra-pillar)：可补执行venue和交易时NBBO，但不提供客户／MM身份；OPRA原生没有主动方标记。普通行情商更便宜的逐笔套餐不等于便宜的真实MM标签。当前免费C1 TBT样本自身带NBBO，最小字段试验无需先买另一份报价。

### 公开Hugging Face展示的额外成本

Cboe Open-Close的[许可说明](https://datashop.cboe.com/cboe-options-open-close-volume-summary)要求原始数据内部使用；派生结果外发也要批准及额外许可。当前列明EOD／10m派生外发额外$5,000／月，1m额外$7,500／月。TBT产品明确禁止外部数据再分发；不能把Open-Close的外发条款自动套到TBT上。

因此“原始CSV不公开，只在HF显示GEX曲线”**不自动免除派生展示许可**。免费可下载也不等于开放许可证。本轮只将原始文件放Git忽略目录，不将样本、逐笔或数据驱动曲线上传HF。未来先做本机研究，再按拟公开内容核对许可；目前没有产生这些数据驱动的HF新结果。

## 4 怎么与现有moomoo配合

### 4.1 两种不同的观测路线

**逐侧路线TBT：** 用真实capacity学习买侧／卖侧的MM身份，先与简单逻辑回归等透明方法比较。可以使用当时NBBO中的成交位置、价差、数量、C/P、DTE、价内外、时段和组合标志；不能将未来价格、迟到OI或待预测的capacity输入特征。侧记录采样和未知对侧要显式遮罩，不伪造完整四类标签。MM可同时在两侧，`P(MM买侧)+P(MM卖侧)`不必等于1。

**汇总路线Open-Close：** 在完整、可审计的合约×交易所×区间上计算：

```text
observed_delta_q = MM_buy_contract_volume − MM_sell_contract_volume
```

累计文件先差分并处理重置、更正。这可以校验模型**区间净流**，不能把一格汇总倒推成每笔moomoo成交的真标签。没有完整区间时，只报告“抽样已观测侧记录之和”，不命名为完整delta_q。MM买平同样增加净库存、卖平同样减少；开平不是净成交变化的必要条件。

有连续标签后的潜在库存设计为：

```text
q_t = q_0 + 累积已覆盖MM净流 + 非成交调整 + 未覆盖净流
```

未知q0、跨所遗漏、组合／修订、行权指派、到期、合约调整分别进入误差或情景，不能任意设q0=0再命名真实库存。用真实标签估计分层流量及分类误差，再考察净多／净空区间，是比手动给OI正负更合理的候选；没有可识别标签时只作敏感性，不宣称已校准。

### 4.2 moomoo负责什么，当前还不能拼什么

现有moomoo可供所选合约OI、IV、Greeks、乘数、标的日K／5m及有限最近成交。外部交易所提供capacity买卖观测。只在**相同日期、合约及信息可得时点**配合：

- 合约键保存原root、expiry、C/P、精确Decimal行权价、标准／调整交付物、乘数及venue。OSI空格和moomoo代码须显式映射，不把调整root直接并入标准SPY。
- 现有moomoo逐笔未返回执行venue或可与Cboe核对的exec_id；它的sequence不等于Cboe执行ID。相近毫秒、价格和数量可能多对多，未经唯一性验收的匹配不能作真值。
- 现有moomoo审计为2026-11-27；Cboe主要免费样本为2025-03-28，另一个单点为2026-09-30。**当前跨来源同日逐笔标签匹配样本为0**；不拿今天Gamma给旧成交重定价。先用Cboe自己的NBBO做离线字段验证。
- 将来若有完整同期净流与moomoo Greeks，可以算同一范围的**库存变化所对应的Gamma敞口贡献**；它仍不是包含未知旧仓的净GEX。重新定价到不同S时，还需明确同期IV曲面、利率、股息和产品行权模型。
- T+1标签用于到达后的训练／评价或次日滞后特征；不能回填当天实时输入。10m到达的观测在5m策略中仅能到达后使用，保留stale-age。保存event_at、区间、供方版本、first_received_at、available_at；历史首次获知时间未知就保持未知。

Call、Put普通多头Gamma均为正。真正需要估计的是各合约q的符号和数量，不是期权类型本身。即便已知当日MM净买Put，也只能说这部分成交增加Put库存，不能据此断定其原先空仓已经转成净多，更不能直接推出标的看涨／看跌。库存识别、未来方向预测和成本后交易价值分三个实验。

## 5 推荐的最小路线和验收门槛

1. **现在$0阶段：** 已完成Cboe／OCC实际下载与字段审计。下一实现先做版本化解析、MM侧标签遮罩、执行／组合分组和更正检查；用C1自身报价检验特征是否可构造。NYSE异常日期只测导入；Mendeley伪数据只读代码。当前未训练，不报告准确率。
2. **扩展免费历史：** 在用户决定申请后，优先核对Cboe固定2022H2历史或TBT试用资格。需要连续多日、多个到期和产品，报告合约／venue覆盖，再做时间留出；单日113,018侧记录不当113,018独立证据。
3. **必要时小额历史而非长期订阅：** 先问C2／GEMX是否有足够SPY／QQQ同合约覆盖和可用MM历史。C2 EOD $400／数据月、10m $500／数据月可作为公开价参考；GEMX相应$400／$750。EOD用于日级净流与离线标签，不能检验日内每5m流量。可否更短日期采购及最低金额仍待确认。
4. **有标签之后再校准：** 对同期完整覆盖先验delta_q，再验F2概率、跨期稳定性和对q0／缺失流的敏感性。未识别存量继续`q=null`或方向未知。只有之后才能测GEX相对无GEX基线的增量、触发点和尾部风险；不从某个正负假设收益更好反推真实仓位。

采购前应核对：真实capacity字典及版本、是否逐买卖侧、各产品实际上市／缺失区间、参与侧或单计数量、累计／更正规则、复杂单覆盖、首次到达时间、原始／派生本机及公开HF许可、短期最低订单。没有书面覆盖和样本验收，不按低价直接选交易所。

## 6 可复核记录与当前交付

原始文件和完整工作笔记位于本机Git忽略的`state/mm-data-sources/`，不随源码发布。下列哈希为实际下载文件，不是重新生成内容的哈希：

| 文件／入口 | SHA256 |
| --- | --- |
| Cboe Open-Close sample/218 ZIP | `445cd9d658dc06028c286e09d4ac4818bd5884d7da8addd7509f3a0fa4840552` |
| Cboe TBT sample/289 ZIP | `6c99e69e43d259e81bc31334574579cf9c623f5e77ff596cacf268712cd3262c` |
| Cboe 2026-09-30新版1m gzip | `e8e969df08c85069c3916b54f5b5d20b1b6aa05b98a68173b90c15bc7aa31020` |
| OCC SPY 2026-11-25 CSV | `8ef4e92502fa3133a8d90573985553ffc8343ca3b47d430fcbb7dd61b5725e82` |

已完成：官方来源／当期费用比较，实际免费样本schema、分类及完整性审计，moomoo配合设计和SPEC更新。未完成：连续外部标签采购／申请、生产适配器、同期逐笔匹配、F2训练／校准、真实库存存量识别、样本外GEX增量结果或新HF发布。后续0.11.1已发布九方法目录和独立TOY初仓算术；没有把这些免费样本或其逐合约结果公开到HF，也没有真实GEX或预测验证结果。
