# 免费Cboe样本：MM方向与库存变化的最小实验

日期2026-11-27，America/New_York。只用已下载免费样本，不购买数据。来源与哈希见[来源清单](MM_CLASSIFIED_DATA_SOURCES.md)，正式门槛见[库存识别SPEC](../specs/DEALER_INVENTORY_IDENTIFICATION.md)。这是分类侧会计与抽样完整性实验，没有真实库存恢复或交易收益回测。

## 1 本次实现

- `research/cboe_mm_sample.py`：有界ZIP／CSV解析、精确合约键、真实capacity及B/S观测侧会计；未知侧／非期权腿隔离，不把整个文件统一当期权张数。
- `scripts/run_cboe_mm_validation.py`：在本机读取固定免费文件，生成带来源指纹的JSON与可离线打开的中英文HTML。原始样本和派生结果都位于ignored `state/`，不进入HF发布包。
- `research/dealer_methods.py`：九种方法的双语目录、能力门槛和显式初仓情景；不把数据能力声明当模型训练或校准。
- 公开期权页新增Inventory methods／持仓方向方法Tab及独立TOY初仓敏感性。原GEX／Max Pain教学计算保留；真实Cboe逐合约流量不放上公网。

## 2 样本隔离后的实际观测

官方[免费TBT样本](https://datashop.cboe.com/enhanced-us-options-trade-by-trade-execution-detail)对应2025-03-28 C1，113,018条参与者侧记录。初步来源审计中的58,293条MM包括非期权／未证腿，不能全部视为期权张数。

严格保留有效C/P、root、到期及正行权价的期权行后：

本机JSON／HTML按全部有效期权、SPY／QQQ及Call／Put分别提供侧记录、MM买入／卖出数量及抽样数量差。详细数据驱动结果留本机，不在公开源码文档重复发布。

另507行没有正常期权C/P／root，expiry为3006-01-01、strike为0，可能与组合中的股票腿有关，但类型尚未独立确认；全部隔离。69条side=T均在其中，不强行归入SELL。不能把这些行乘100或算进期权Gamma。

本机结果中的抽样净数量仅是**已采样、已观测期权MM侧的数量代数和**；跨合约未作风险加权，不是完整区间净流、真实库存或看涨看跌指标。绝大多数执行组缺少另一侧，缺侧保留unknown；不把3%样本放大。MM买平同样加q，卖平同样减q；两侧均为目标MM的同合约交易净额相抵。未知初仓q0不默认为0。

## 3 抽样能够翻转流量符号：必须展示的反例

将TBT中观测到MM的有效期权合约与**同日期**免费EOD文件按root、expiry、C/P、Decimal strike匹配；检查唯一性后，分别统计两者非零同号、严格反号、仅一方为0和双0。提供的EOD文件本身也标注样本，不能在未核实前称为全市场或完整链。

本机实际运行发现抽样净流与提供的EOD行存在严格反号的合约，完整计数、合约及原始量只在本机结果展示。这里验证的是**采样范围改变会改变观测净流符号**，没有证明哪一份能代表全市场库存。也不能据此判SqueezeMetrics“预测错”：Squeeze的Call正／Put负是存量假设，而此处比较成交变化。更不能说这些数值就是当时的净GEX。

公开的纯假设手算例子：TOY同合约样本买8、卖3，差+5；另一个假设较广范围买20、卖30，差−10。它仅说明两个覆盖范围的代数和可以反号，不是实际Cboe数值。

## 4 怎样配合moomoo改善估计

第一步已从手动OI正负推进到**直接观察MM买卖侧及数量**，能够校验会计和未来分类器的目标；仍需分开三个问题：

```text
观测层：MM买侧、MM卖侧、数量和缺失范围
状态层：q_t = q0 + 累积净变化 + 非成交调整 + 未覆盖活动
风险层：GEX_1pct = .01 * S² * Σ(q * multiplier * Gamma)
```

普通长Call、长Put的Gamma都为正。真实MM买Put增加q，但旧仓可能仍净空。只有流量，没有初仓，净GEX正负可能继续未知。

本轮Cboe 2025-03-28样本缺少同期Gamma、IV、spot和乘数；Open-Close也不能用一个期权last_trade_price替代同步报价去硬解IV。现有moomoo有2026-11-27所选合约Greeks／IV／OI，不与该样本同期，**真实同期逐笔MM标签匹配数仍为0**。今天Greeks不能回填旧成交。

后续同日期、同合约、同信息可得时间采集时，moomoo可提供标的行情和Greeks，交易所标签验证MM侧或区间净流。当前moomoo缺执行venue／跨供应商exec_id，逐笔匹配须先验唯一性；Open-Close仅能校验聚合，不能给每笔moomoo成交硬分标签。未知库存／跨所活动和调整不靠滤波器自动消失。

脚本中如展示GEX曲线或初仓区间，使用**另行标记的TOY数据及声明Greeks**，仅用于验证单位、正负传播和假设敏感性；与真实Cboe观测不混合。没有声称改善真实GEX误差、触发价、收益或尾部预测。真实增量价值仍NOT_ESTIMABLE。

## 5 此前方法统一进入目录

按当前讨论范围整理九种方法；这里不声称精确恢复聊天的逐条时间戳。

| 方法 | 本轮可以看什么 | 保留的门槛 |
| --- | --- | --- |
| SqueezeMetrics固定符号 | 现有TOY Call正／Put负基线 | 符号与OI归属为假设 |
| 分层库存路线 | 现有Call／Put先验与MM占比情景 | 完整asset／DTE／moneyness分层与校准尚未实现 |
| 无符号集中度 | 现有TOY OI×Gamma聚集 | 无库存方向 |
| 净买压NBP | moomoo已有vendor主动流代理 | 不等于MM身份；报价规则尚未验证 |
| 真实capacity MM流 | 本次免费样本观测侧会计 | 部分流，不是完整q |
| Demand-Based定价 | 原始框架与所需数据 | 未实现可识别库存估计器 |
| Bayesian／State-Space | 状态／观测设计与q0情景 | 没有拟合或校准 |
| 组合腿重建 | 保留exec／complex分组与缺腿警示 | 完整腿覆盖及组合库存未验 |
| Shadow Gamma／全情景风险 | 现有BSM股价／IV／时间情景 | 有限数学情景，不冒充原论文完整模型或库存识别 |

公开页面的目录按云端实际能力报告状态；本机运行器可以另声明本轮样本能力。声明数据存在不会把未实现模型变为可用。所有方法`execution_eligible=false`，没有券商订单或新后台任务。

## 6 复跑和交付边界

在项目根目录、现有独立研究环境运行：

```powershell
& '.\state\space-venv\Scripts\python.exe' '.\scripts\run_cboe_mm_validation.py'
```

输入为已有`state/mm-data-sources/cboe-samples/`免费ZIP；不请求网络、账户、令牌或付费接口。结果写入新的`state/cboe-mm-validation/`运行目录，记录实际输入及代码指纹。HTML默认英文，提供中文按钮；本机结果不自动上传、共享或发往HF。

程序测试、真实运行和公开方法页部署分别验收，测试通过不等于真实GEX准确或交易有利。后续如果不能获得连续覆盖、q0及同期Greeks，应保留为“观测流／期权结构研究”，不能升级成确定性仓位或支撑阻力信号。
