# 论文阅读与项目实现索引

这里整理最初讨论的三篇论文，以及后来补充的 ADNN 原始方法论文。两篇综述用于理解问题和设计检验；两篇方法研究提供可以拆分研究的机制。当前代码包含方法迁移与核心机制实验，不等于完整重现原论文或其收益数字。

实现范围见 [论文复现范围与模型选择](../../PAPER_REPLICATION.md)，数据、标签、模型与组合规则见 [项目规格](../../SPEC.md)。书目信息与原文入口核对日期：2026-11-25。

## 最初讨论的三篇论文

### 1. Reinforcement Learning for Quantitative Trading

- **作者**：Shuo Sun、Rundong Wang、Bo An。
- **年份与类型**：2023，*ACM Transactions on Intelligent Systems and Technology*，强化学习量化交易综述。较早的 arXiv 稿发表于 2021 年。
- **原文入口**：[出版商 DOI](https://doi.org/10.1145/3582560)；[NTU 作者站开放稿 PDF](https://personal.ntu.edu.sg/boan/papers/TIST23_RLFintech.pdf)；[2021 年 arXiv 书目及开放稿](https://arxiv.org/abs/2109.13851)。最初分享的 [ResearchGate 记录](https://www.researchgate.net/publication/367638397_Reinforcement_Learning_for_Quantitative_Trading) 对应同一题名的期刊论文。

**读什么**：先区分收益预测、单资产交易、组合配置、订单执行和做市。NTU 版本第 4 节讨论因子挖掘与监督预测；第 5 节分类介绍 RL 方法；第 6 节讨论数据、模拟和评价问题。

**本项目如何使用**：这篇文章帮助确定“预测分数 → 组合决策 → 模拟执行”的分层，并引导我们找到第 4.1 节引用的 ADNN。它不是一套给定数据与统一参数的新算法，也没有一个可直接重跑的统一收益排行榜。当前没有完整复建综述列举的 RL 交易、执行或做市系统；ADNN 的局部实现范围见下方补充方法。

### 2. Diffusion-Augmented Reinforcement Learning for Robust Portfolio Optimization under Stress Scenarios

- **作者**：Himanshu Choudhary、Arishi Orra、Manoj Thakur。
- **年份与类型**：2025，提出 DARL 的方法与历史回测实验，arXiv 预印本 v1 发布于 2025-10-08。
- **原文入口**：[arXiv v1 书目](https://arxiv.org/abs/2510.07099v1)；[v1 开放全文](https://arxiv.org/html/2510.07099v1)；[v1 PDF](https://arxiv.org/pdf/2510.07099v1)。

**读什么**：第 3 节将条件 DDPM 产生的压力情景用于增强 PPO 组合训练；第 4 节给出道指股票日频实验。这里的生成模型主要承担情景生成与训练增强，不能将论文的组合稳健性结果直接解释成 alpha 预测改善。

**已经可以复测的项目模块**：[research/models.py](../../research/models.py) 比较 Ridge、真实数据 MLP、重采样 MLP 和条件 DDPM 增强 MLP。生成器仅在训练期拟合，保留真实历史条件 X，生成与其配套的未来超额收益标签 y；三组 MLP 使用相同预测器训练预算，生成器计算量单独披露。增益须在真实留出期评价，生成损失和合成样本统计只作诊断。

**尚未覆盖**：本项目没有复建论文的 PPO、完整压力情景市场路径、组合权重正则化或原文基准实验。当前的标量标签条件生成是迁移设计。重现原文表格还需核对原数据、成分股时点、生成器训练边界和完整实验配置；我们的结果不替代论文结果。

### 3. The Evolution of Quantitative Equity Investing: Half a Century of Alpha Research and Institutional Adaptation

- **作者**：Xuan Feng、Julio P. Cardozo、Dehua Xia。
- **年份与类型**：2026，*Journal of Economic Surveys* 综述，出版商记录首次发表日期为 2026-10-05，页面标注 Open Access。
- **原文入口**：[Wiley 官方全文](https://onlinelibrary.wiley.com/doi/full/10.1111/joes.70178)；[DOI](https://doi.org/10.1111/joes.70178)。

**读什么**：量化研究的约束如何从预测扩展到信息时点、组合构建、成本、容量及执行；特别关注第 6 节关于泄漏、研究过拟合及预测与组合价值的区别。

**本项目如何使用**：[research/data.py](../../research/data.py) 的历史特征与标签边界、[research/portfolio.py](../../research/portfolio.py) 的成本和风险约束，以及 [research/pipeline.py](../../research/pipeline.py) 的预测、组合和审计记录，承接了这些研究原则。这属于评价与工程设计，不是对某个 Wiley 新算法的复现。

**尚未覆盖**：历史可投资股票池、全面退市处理、真实市场冲击与容量、借券约束、跨市场阶段验证等仍需独立完善。这篇综述自身不提供一套统一的新模型或固定实验数字。

## 补充方法：ADNN

这篇是从 RL 综述继续追溯的原始方法研究，**不属于最初三篇论文**。

- **书目页标题**：*Alpha Discovery Neural Network based on Prior Knowledge*。
- **作者**：Jie Fang、Shutao Xia、Jianwu Lin、Zhikang Xia、Xiang Liu、Yong Jiang。
- **年份与类型**：2019 年初稿；KDD 2020 Workshop on Machine Learning in Finance 方法研究；arXiv v8 日期为 2020-11-26。
- **原文入口**：[arXiv 书目与版本历史](https://arxiv.org/abs/1912.11761)；[v8 开放全文](https://arxiv.org/html/1912.11761v8)；[v8 PDF](https://arxiv.org/pdf/1912.11761v8)。v8 全文显示的标题是 *Alpha Discovery Neural Network, the Special Fountain of Financial Trading Signals*；它与书目页属于同一 arXiv 编号的版本链。

**读什么**：第 2.2 节的同日股票分组与平滑排序目标，第 2.3 节的先验预训练和剪枝，第 3 节的因子与策略实验。神经网络自动发现因子属于特征学习，不因“自动生成因子”的说法就等同于生成式市场数据模型。

**已经实现的核心机制**：[research/rank_experiment.py](../../research/rank_experiment.py) 将同一天股票作为一组，分别计算预测值和目标的 `g(z) = sigmoid(1.83 * (z - mean(z)) / (2 * std(z)))`，以分组平均的负相关为损失。原文式 6 的分母排版存在歧义，本实现明确解释为标准 Pearson 相关，`std` 使用总体标准差。与同架构 MSE 目标对照，并匹配初始化、日期抽样及更新次数；手写梯度由 [有限差分测试](../../tests/test_rank_experiment.py) 核查。

**收益单位与校准**：原始排名分数没有收益单位。当前实验只用独立验证期拟合非负斜率的分数到超额收益校准，再接成本门槛与相同组合规则；真实测试期不训练网络，也不拟合校准。原始分数和校准分数均保留。

**尚未覆盖及偏离**：未复建 GP、技术指标预训练、剪枝、多样性机制、完整因子池或下游 XGBoost 选因子流程。现有实验使用美股、41 个历史特征、两隐藏层 tanh 小网络，以及相对 SPY 的下一开盘至第 h+1 个开盘收益标签，区别于原文 A 股原始价量输入与未来收盘收益设定。因此应称“核心机制迁移实验”，不能称完整 ADNN 复现。

## 建议阅读顺序

新增的 [动量与趋势研究说明](../MOMENTUM_TREND.md) 汇总四种日频规则基线、三篇日内原始研究及分钟数据候选；这些是后续补充，不属于最初三篇论文。该文明确区分本轮实现中的日频功能与尚未接入、没有项目结果的分钟研究。

1. **Wiley 综述**：先理解预测正确与实际策略价值之间还有哪些环节。
2. **RL 综述**：理解预测、配置、执行各自回答的问题，并阅读第 4 节的因子研究入口。
3. **补充 ADNN**：理解同日横截面训练和平滑排序损失，再对照本项目的机制实验。
4. **DARL**：理解条件生成如何参与训练增强，区分风险稳健性与 alpha 预测增益。
5. 回到 [PAPER_REPLICATION.md](../../PAPER_REPLICATION.md) 和 [SPEC.md](../../SPEC.md)，以实际实现边界解释实验结果。

本目录只保存书目信息、原文链接与项目自己的阅读及实现说明，不收录论文全文文件。开放稿通过作者或出版平台链接访问；可在线阅读与可重新分发是不同权限，全文授权以原始来源为准。

## 后续专题：Support & Resistance

2026-11-26用户确认SNR为支撑／阻力。已补充Osler的机构价位／订单研究、Chung与Bellotti的区域发现和事件统计、Garzarelli等的价格记忆研究，以及官方通道／pivot／成交量分布和作者聚类源码。具体方法、可见时点、研究局限与候选实施顺序见[支撑／阻力研究](../MOMENTUM_TREND.md#snr支撑阻力的量化研究)。这些属于后续独立专题，不计入最初三篇论文，也不表示本项目已实现SNR策略或验证其收益。

## 后续专题 Beta策略

2026-11-26补充Beta研究：Frazzini与Pedersen的BAB、Baker等低风险解释、Novy-Marx与Velikov的BAB批评、Asness等相关性分解，以及Moreira与Muir、Cederburg等、Daniel与Moskowitz的动态风险证据。现行S&P／MSCI方法与French／AQR参考数据入口也一并记录。原文链接、版本差异、成本与实时可实施限制见[Beta策略研究](../BETA_STRATEGIES_RESEARCH.md)，项目变体与验收见[实验规格](../../specs/BETA_RESEARCH_PLAN.md)。这些是后续专题，不属于原始三篇论文，也不是新增策略已经上线的证明。

## 后续专题 做市商库存方向与GEX

2026-11-27补充[24个研究家族的原文核读综述](../GEX_MAXPAIN_DECISION_RESEARCH_2026-11-27.md)，逐篇区分实际阅读版本、数据标签、方法、预测与执行边界；直接Max Pain论文未取得完整稿者单列，不计全文数量。共享样本和同家族修订不当作独立复制。

库存识别重点对应Amaya等2026的容量分类递推、Demand-Based Option Pricing的真实分参与者持仓、Bollen／Whaley的主动买压、Options Market Makers的账户净额化。逐项数据可复现性见[moomoo实测与论文映射](../MOOMOO_DEALER_INVENTORY_AUDIT.md)，具体schema、q0、标签和误差验收见[库存方向SPEC](../../specs/DEALER_INVENTORY_IDENTIFICATION.md)。当前只实现安全数据审计与供应商主动流代理；不是复现私有容量数据、校准隐状态或恢复真实MM持仓。现有手动GEX先验仍属数学情景。
