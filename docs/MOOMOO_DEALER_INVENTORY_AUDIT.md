# moomoo数据能否识别做市商持仓方向

2026-11-27，America/New_York。本次实测窗口12:08:39—12:09:13美东，即17:08:39—17:09:13 UTC。只使用现有桌面行情连接，未查询账户、持仓、订单或交易，未新建认证、购买数据或启动常驻任务。

**结论：已取得部分真实动态期权行情、主动方向逐笔和当前盘口，但尚不能识别真实做市商净库存。** 本次解决了此前“小批动态快照超时是否等于没有动态数据”的问题：`subscribe basic → get-basic-qot`成功，`get-security-snapshot`小批仍超时。两条结果分别保留，不能由一个接口失败推断全部路线不支持。

同日后续已取得外部Cboe旧日期的部分真实MM侧样本，详见[分类数据来源与费用研究](MM_CLASSIFIED_DATA_SOURCES.md)。这不改变本页moomoo本身没有MM身份的结论；外部样本与本次moomoo日期不重合，当前同期跨源逐笔标签匹配仍为0，未恢复当前真实库存。

## 本次实际取得的数据

运行`scripts/audit_moomoo_option_data.py --symbols SPY QQQ`，CLI版本`16.40.27608.11182326`。共25次CLI调用，24次协议成功，其中3次是行情订阅；1次全量快照15秒有界超时。未自动重试或切换公网认证。

| 项目 | 本机实际观测 | 仍缺什么 |
| --- | --- | --- |
| 到期列表 | SPY、QQQ均成功返回 | 不是历史as-of列表 |
| 静态链 | SPY在11/27、11/30分别438、576份；QQQ分别514、590份，共2118份不同合约 | 只请求两个到期日，未证明所有到期日／全部有效链完整 |
| 动态期权报价 | 每标的、每到期选一组近现价Call／Put，共8份合约；前后两批均8行 | 是所选合约样本，不是2118份完整动态链，更不是历史链 |
| OI／IV／Greeks | 8/8有非空有限数值的OI、IV、Delta、Gamma、Theta、Vega、Rho；本样本这些字段均非0 | 非空／有限不等于独立经济有效性验证；OI有效日期、公布时间仍未披露 |
| 合约数量口径 | 本样本`lot_size`、`contract_size`、`contract_multiplier`分别观察到100；`option_area_type=AMERICAN` | 不把三个100相乘；正式计算仍要核对每个字段的经济定义、标准交付和有效日期，不能套给调整合约 |
| 逐笔 | 最近到期SPY／QQQ各Call、Put，共4份合约各100笔、合计400笔；有time、timestamp、price、volume、sequence、dir、type和type_sign | 各窗口约17—31秒，不同合约窗口不同；仅最近N笔，无完整交易日、历史分页或跨所完整性证明 |
| 成交分类 | dir实际出现BUY／SELL／NEUTRAL；本样本type均为AUTO_MATCH，type_sign均为32 | 不是客户／MM身份、不是开平标签，也不据此判定是否多腿组合 |
| 当前买卖盘 | 4份合约在逐笔读取前后各1次，共8个盘口，每次Bid／Ask各1档 | 本次响应没有盘口源时间字段；不能称历史同步NBBO，也不能给此前成交补配当前报价 |
| 时间 | 保存请求、实际接收、完整原始供应商时间；报价有update_time／update_timestamp；400笔均有trade timestamp | ticker recv_time仅9/400出现；不能拿它替代缺失报价时间；OI时间独立保持null |
| MM／客户／开平 | 所检字段未取得可靠参与者capacity、买卖侧MM标签、开平、complex执行关联或完整更正链 | 不能训练经验证的MM侧概率、恢复初仓或评价真实q符号准确率 |

本次不解释`type_sign=32`为MM身份或开仓标志。字段名相似也不构成语义证明。官方旧快照中的`option_net_open_interest`明确仅港股期权适用，并未定义为MM净多减净空；不能据此给美股库存赋值。[官方快照](https://openapi.moomoo.com/moomoo-api-doc/quote/get-market-snapshot.html)

另有时钟质量缺口：前三组逐笔最大供应商timestamp比本机记录的received_at分别晚约65、279、180毫秒。可能的供方／本机时钟或字段精度差异未核，不静默平移、截断或用接收时刻替换原时间。原生流量统计仍可复核，但严格quote-join、延迟和实时可得时点验收暂不通过；新审计器显式报告该诊断。

新REST与传统OpenD的能力、权限和字段不能自动等同本机桌面CLI。文档显示新REST逐笔最多最近750笔，传统OpenD最多最近1000笔；本次只请求每合约100笔。新REST异动有逐事件Bid／Ask，但选择性样本且未披露报价时刻；标的级历史OI为Call／Put汇总，不是逐合约历史OI，更不是MM库存。[新逐笔](https://open.moomoo.com/api/quote/realtime/rt-ticker)、[旧逐笔](https://openapi.moomoo.com/moomoo-api-doc/quote/get-ticker.html)、[异动](https://open.moomoo.com/api/quote/derivatives/option-event)、[标的OI历史](https://open.moomoo.com/api/quote/derivatives/option-underlying-his-statistic)

## 用实际400笔做的最小研究

先只计算供应商主动流代理，不作MM身份推断：

```text
vendor_signed_flow = sum(volume for dir=BUY) − sum(volume for dir=SELL)
NEUTRAL／未知单独保留，不强行归为卖出
q_MM = null
MM_side_probability = null
```

| 所选合约 | BUY／SELL／NEUTRAL笔数 | 原生volume加权净主动流 | 可得结论 |
| --- | --- | --- | --- |
| SPY近到期Call | 36／47／17 | −280 | 该抽样窗口供应商标记的卖方主动流较大；MM方向未知 |
| SPY近到期Put | 47／45／8 | +128 | 该抽样窗口供应商标记的买方主动流较大；MM方向未知 |
| QQQ近到期Call | 34／45／21 | +203 | 笔数偏卖而数量偏买，不能只数成交笔数；MM方向未知 |
| QQQ近到期Put | 33／57／10 | −14 | 有限窗口的流量代理，不能当净库存 |

以上数值保留供方原生volume单位，未独立证明“张／股”转换，不用于换算Gamma。四个窗口不同，不加总成全市场指标。供应商方向没有独立主动方真标签，本次没有分类准确率；不把400笔当400个独立库存验证样本。

如果额外假设“MM总是被动承接”，主动买入可对应MM卖出，但这又加了一层未验证身份假设。即便准确知道MM本窗口净买入，也可能只是减小原有空仓，不能直接判断当前q为正。**我们没有把上述净主动流乘−1写入MM库存。**

## 论文怎样指导持仓方向研究

| 研究依据 | 可以迁移的方法 | 本机数据现在能否复现 |
| --- | --- | --- |
| [Amaya等2026](https://algoseek.com/wp-content/uploads/2026/10/ssrn-7330098.pdf) | 真实参与者容量分类，累计MM买入减卖出，系列上市起点、组合腿和旧初仓分别处理 | 不能完整复现：moomoo本次未给MM侧标签及从上市起完整成交。能明确所需schema及净变化会计 |
| [Bollen／Whaley 2004](https://www.whaley.info/_files/ugd/1362e1_81f94ba850fb4ec4aea173770b355408.pdf) | 报价推断主动买卖与数量加权压力 | 只能先保留vendor dir；当前盘口无源时间，不能独立验证历史quote-rule，更不能把它当MM身份 |
| [Demand-Based Option Pricing，2005实读稿／2009发表](https://users.nber.org/~confer/2005/URCs05/pedersen.pdf) | 用真实分参与者持仓研究需求与价格，考虑产品差异 | 可指导分组，不支持手填分组符号后宣称方向被识别；不能从IV唯一反求q |
| [Options Market Makers，2025实读稿](https://www.fma.org/assets/docs/Derivatives2025/Muravyev.pdf) | 区分期权内库存净额化与标的对冲，研究MM行为异质性 | 不能把韩国行为筛选账户直接当美国MM标签；提醒我们不要强设“被动方全是MM” |

完整版本和24篇核读清单见[文献综述](GEX_MAXPAIN_DECISION_RESEARCH_2026-11-27.md)。无标签下的Bayesian隐状态设计属于我们的待验证方法，不是上述论文已经验证过的公开库存恢复器。

## 下一阶段及明确状态

1. 前瞻私有归档先保存实际收到的原始逐笔、报价及各自时间、序号、更正／组合字段和缺口，不只保存归一化异动摘要。现有旧NVDA归一化缓存丢失过部分报价字段，不能用来补造历史。
2. 建立主动方代理与历史quote-join质量层；有可靠历史报价和主动方真标签后才评分类准确率。没有报价时刻的样本保留unknown。
3. 若获得同覆盖的真实MM买卖侧标签，先训练透明的MM侧分类器；再评价库存增量，不立即声称恢复存量。分类数据来源、时延和许可须核实，本次未购买或接入。[Cboe分类数据](https://datashop.cboe.com/cboe-options-open-close-volume-summary)
4. 初仓、完整覆盖和调整已核后，才研究q的正负及数量；然后分别计算Call、Put和总GEX贡献。各层有独立标签、指标及拒绝条件。

当前结果：`data_capture=OBSERVED_PARTIAL`、`flow=VENDOR_AGGRESSOR_PROXY_ONLY`、`inventory=NOT_IDENTIFIABLE`、`inventory_accuracy=NOT_ESTIMABLE`、`q=null`、`estimated_GEX=null`、`execution_eligible=false`。没有MM标签样本；没有合格历史全链预测样本。动态字段成功不改变这两个样本数。

不把手动`p_long`参数或Squeeze固定符号升级成“已学习方向”；它们仅保留为明确标识的数学／敏感性基准。无符号集中度也不参加库存方向准确率排名。

## 复核与保存

可复用采集脚本为[scripts/audit_moomoo_option_data.py](../scripts/audit_moomoo_option_data.py)，严格行情命令白名单、loopback、最多两个已允许标的、两到期／每期一组Call与Put、每逐笔100条、每请求15秒、全轮最多30次。仅前台运行；没有上传、下载原始行情的公开入口、定时任务或账户功能。现有受保护Host AppKey只进内存及子进程环境，不写进参数或审计。

```powershell
# 在项目目录、已有依赖环境中运行；不要在命令中写密钥。
python scripts/audit_moomoo_option_data.py --probe
python scripts/audit_moomoo_option_data.py --symbols SPY QQQ
python tests/test_moomoo_option_audit.py -v
```

本次市场字段归档保存在Git忽略的`state/dealer-inventory-audit/20261127T170839607943Z/`。当时保存的是保留供应商s2c字段的重序列化成功响应，其哈希不是CLI原始stdout逐字节哈希；未保留的旧传输字节不能事后补造。原audit SHA256为`a7f27a8324ce3d28a925cdaa327b563b08fb3289022b788374bc037c379bd711`；实际采集脚本副本SHA256为`7dd9e444072e294dccf6c68442d1f0d4bb8ea400184b4e914f83c8ed81158f54`。后续v2在符合预期且ret_msg为空的成功行情信封上，另存原始stdout字节及其哈希；错误或未知顶层元数据不原样落盘。本次未重新采集，不把此改进描述为旧采样已保存逐字节原件。

采集后的解析防护和时钟诊断改进另有当前源码，不回写冒充当时版本；`flow-proxy-result.json`记录行情归档与分析源码哈希，完整离线重放没有新增网络请求。20项离线安全／解释检查通过，不代表已经验证真实库存方向。

公开文档仅含聚合研究观察，不携带原始OI表、逐笔价格、账户、凭据或本机绝对路径。本轮未更改HF应用或发布状态；在线期权页原0.11.0教学验收记录保留。后续接入须遵守[库存识别SPEC](../specs/DEALER_INVENTORY_IDENTIFICATION.md)。
