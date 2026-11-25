# 主题研究股票池与日K数据

2026年11月25日配置为45只股票，加SPY基准。使用现有moomoo本机只读API读取日K，没有购买或开通新的付费数据服务。普通股行情当前官方存在免费推广政策，具体权限、额度和政策变化仍以平台实际为准。[官方说明](https://openapi.moomoo.com/moomoo-api-doc/en/qa/quote.html)

## 当前分组

| 研究主题 | 股票代码 |
| --- | --- |
| 半导体与封测 | NVDA、AMD、AVGO、TSM、ARM、MRVL、QCOM、INTC、TXN、ADI、NXPI、MCHP、ON、ASX |
| 存储与控制器 | MU、SNDK、WDC、STX、SIMO |
| 半导体设备 | AMAT、LRCX、KLAC、ASML、TER |
| AI云服务 | CRWV、NBIS |
| AI机房与混合业务 | IREN、APLD、CORZ |
| 服务器 网络与供电配套 | VRT、ANET、DELL、SMCI、HPE |
| 大型平台与跨行业对照 | AAPL、MSFT、AMZN、GOOGL、META、JPM、XOM、JNJ、PG、WMT、KO |

这些是当前选定的研究主题，不代表正式行业分类，也不代表实际持仓。IREN、APLD、CORZ有矿业、机房托管或业务转型历史，整段价格不能解释成纯AI云业务历史。当前股票池仍受现时点选股偏差影响。

## 历史边界

| 股票 | 研究起点 | 处理 |
| --- | --- | --- |
| SNDK | 2025-02-24 | 从本次正式独立上市开始，不接旧SNDK生命周期；正式上市前when-issued阶段的记录目前另行排除。 |
| CRWV | 2025-03-28 | IPO前无公开交易历史，不回填。 |
| NBIS | 2024-10-21 | 从重组后恢复交易重新计算特征，排除旧Yandex业务期价格。 |

依据：[Sandisk上市公告](https://investor.sandisk.com/news-releases/news-release-details/sandisk-celebrates-nasdaq-listing-after-completing-separation)、[CoreWeave年报](https://www.sec.gov/Archives/edgar/data/1769628/000176962826000104/crwv-20251231.htm)、[Nebius年报](https://www.sec.gov/Archives/edgar/data/1513845/000155837025005991/nbis-20241231x20f.htm)。WDC的业务组合也在Sandisk拆分前后发生变化，已在配置中标记。

新股保留较短的真实历史，其他股票继续使用自己的较长历史。每只股票需要先积累特征回看期，再产生可用于训练的样本。训练期、验证期、测试期仍按同一市场交易日划分，不逐行随机拆分。

## 数据怎样进入训练

日K是原始输入。程序从已知历史计算动量、波动、价量变化等41项特征，用之后五个交易日的相对收益作为历史答案。模型只在训练期学习参数；验证期和测试期的用途分别记录，真实预测时不能使用尚未发生的答案。

得到预测后，再经过收益单位、成本门槛、逆波动权重、单股上限、相关性风险缩放和现金约束，形成可检查的模拟订单草稿。扩大股票池只是增加研究覆盖，不等于证明预测有效。

当前接口每只请求最近最多1000根日K；这不是moomoo全部历史能力的上限。更长历史需要另行核对历史接口、分页和额度，本轮保持现有可用接口。
