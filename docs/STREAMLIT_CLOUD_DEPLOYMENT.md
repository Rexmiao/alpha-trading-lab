# Streamlit Community Cloud 免费部署

更新：2026-11-26。公开模拟入口是 `hf_space/streamlit_app.py`，与 Hugging Face Docker 发布包共用引擎。发布包已通过本地 11 项测试及 Streamlit 1.67 的实际计算 AppTest；这些验证不等于云端已上线。本次已完成托管连接和实际发布：[公网应用](https://alpha-trading-lab-rnb8nqgww7tgbdvgdcysxm.streamlit.app/)。三来源功能已实测，实际依赖差异见文末。Community Cloud 官方提供免费托管；应用仍受资源和休眠政策限制。[官方介绍](https://docs.streamlit.io/deploy/streamlit-community-cloud)

## 最短发布步骤

先确认下列代码已上传到个人公开仓库 `Rexmiao/alpha-trading-lab` 的 `main` 分支：

- [共同入口](../hf_space/streamlit_app.py)与 `hf_space/engine.py`、所需 `research/` 模块。
- [云端依赖](../hf_space/requirements.txt)：固定 `streamlit==1.67.0`，与 Docker 发布依赖一致。
- [根目录配置](../.streamlit/config.toml)：上传上限 12 MB（应用层另有逐专题文件大小校验），关闭 Streamlit 使用统计；0.12.1 起同时承载共享浅／深主题，HF 打包与 Cloud 读取同一文件。

然后在浏览器完成：

1. 打开 [share.streamlit.io](https://share.streamlit.io)，登录或创建 Community Cloud 账号，并进入个人 `Rexmiao` 工作区。
2. 如尚未连接 GitHub，按下一节仅连接个人公开仓库所需权限。
3. 点击 **Create app**，选择从 GitHub 仓库部署，再填写下表。也可选择 **Paste GitHub URL**，粘贴 [GitHub 入口文件链接](https://github.com/Rexmiao/alpha-trading-lab/blob/main/hf_space/streamlit_app.py)。
4. 打开 **Advanced settings**，明确选择 **Python 3.12**。本模拟不使用凭据，**Secrets 留空**。
5. 点击部署，等待依赖安装和页面启动；到管理界面查看构建与启动日志。
6. 启动成功后，复制平台实际分配的 `https://…streamlit.app` 地址，再完成下方验收。不要把示例域名或 GitHub 文件链接当作已上线应用地址。

| 部署字段 | 填写值 |
| --- | --- |
| Repository | `Rexmiao/alpha-trading-lab` |
| Branch | `main` |
| Main file path | `hf_space/streamlit_app.py` |
| Python version | `3.12` |
| Secrets | 留空 |

仓库、分支、入口文件、粘贴 GitHub 链接及 Python 版本的操作参见[官方部署步骤](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)。如果自动建议列表未显示目标，可手动填写。

## GitHub 连接只用于个人公开仓库

现有 Codex GitHub App 继续用于上传和维护源码；**它不能代替 Streamlit 托管服务自己的 GitHub 连接**。不要为了部署本模拟重新扩大 Codex App 的权限，也不需要把 GitHub Token、HF Token 或任何密钥发到聊天或填进应用 Secrets。

Streamlit 的首次 GitHub 连接支持公开仓库；访问私有仓库属于额外授权流程。本次只在个人公开仓库 `Rexmiao/alpha-trading-lab` 创建应用，不进入私有仓库授权流程。GitHub 授权页如列出组织，组织区域的 **Grant / Request 都不要点**。如果页面把私有仓库或组织权限变成必选条件，先核对授权范围，再继续，不能假定那是本项目必需权限。[官方 GitHub 连接及组织授权说明](https://docs.streamlit.io/deploy/streamlit-community-cloud/get-started/connect-your-github-account)

选择一个仓库作为应用来源，不等于平台的 OAuth 授权天然只覆盖这一个仓库；仍应以授权页列出的范围为准。本次不申请组织批准，不增加私有仓库权限。

## 依赖与配置已经分开准备

Community Cloud 会先查找入口所在目录的依赖文件，再查找仓库根目录。因此本入口采用 `hf_space/requirements.txt` 的 Streamlit 1.67 依赖，保留根目录原有本机研究环境。不要把主文件选成根目录 `app.py`。若构建日志显示安装了根目录的旧 Streamlit，先核对入口路径和 `hf_space/requirements.txt` 是否已进入 `main`。[官方依赖查找顺序](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies)

Cloud 从仓库根目录启动；项目配置放在根目录 `.streamlit/config.toml`，当前主要内容为：

```toml
[server]
maxUploadSize = 12

[browser]
gatherUsageStats = false

[theme]        # 圆角、字号层级、图表分类色
[theme.light]  # 深蓝文字、青绿强调
[theme.dark]   # 对应深色配色
```

主题只影响呈现；完整取值以该文件为准（SPEC 0.12.1）。该文件限制 CSV 上传大小并关闭 Streamlit 使用统计，不等于关闭托管平台所有运行日志。配置位置与参数分别见[官方文件组织说明](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization)和[配置参考](https://docs.streamlit.io/develop/api-reference/configuration/config.toml)。Community Cloud 直接运行 Python 入口，不需要使用 HF 的 Dockerfile，也不需要 moomoo 桌面端。

## 发布后的实际验收

先在 **Manage app** 的日志中确认依赖安装完成、入口启动成功、没有导入或资源错误。日志入口见[官方管理说明](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)。接着检查：

- 初次打开不自动训练；选择合成教学数据并点击 **Run** 后，四模型逐项显示状态，指标、净值、回撤、Rank IC 和目标权重能正常出现。若任何模型失败，应显示失败原因，不能把缺失结果视为四组成功。
- 切换中文 / English 保留本次结果；修改参数本身不启动训练，重新点击 **Run** 后才应用成本、仓位和风险设置。
- 下载 JSON 能保存本次结果，不包含训练模型。记录本次上线的真实 `streamlit.app` URL，并在新浏览器窗口打开核验。
- CSV 模式清楚提示数据会发送到运行该模拟的云端环境。用不含私密信息的测试文件检查：缺少规定列、重复日期与证券主键、不合法 OHLC 或超大小上传应明确拒绝；不要拿真实账户导出来做拒绝测试。
- 模拟页面没有 moomoo 登录、账户、下单或凭据输入。不要为本应用添加交易密码、AppKey 或 Token。

合成曲线是**假设教学数据，非市场收益**。上传 CSV 的结果也只是对所给数据的离线模拟，不代表实盘成交；本应用比较四种方法及成本、风险影响，不是相关论文的完整复现。CSV 处理发生在云端，不能描述为纯本机计算。

## 休眠 重启与保存结果

结果仅保存在当前用户的 `st.session_state`，代码不把上传文件、模型或模拟结果主动写入持久存储，也不跨会话缓存结果。切换界面语言可保留当前会话结果，但服务休眠重启、浏览器重载或连接重建可能清除它们；需要留存时应先下载 JSON。[Session State 的连接边界](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state)

免费托管并非永久常驻服务。官方当前说明无流量应用会休眠，访问者可唤醒；资源不足也可能导致运行失败，不能据此承诺全天在线。[官方休眠与资源说明](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)

## 实际发布与依赖核对（2026-11-26）

应用源码commit为`b54637fb25eef7746a0ce2c93a97e18c672fcb62`。公开浏览器验证默认moomoo/访客CSV；在线7股加SPY实际获取400日、3200行（2025-04-25至2026-11-25），四模型全部成功。CSV快照、来源JSON和模型结果实际下载一致；中文切English后模型报告逐字节不变。手填7日与持有/调仓周期一致也已验证。

本次取数时间2026-11-26T07:24:38.040985+00:00，CSV SHA256为`98680c14fbbe5ee5bbbb76ead6ea38bb35ddb1b920552d2f23288edb46270c72`。请下载快照后用同一CSV进行参数或跨站比较，不把两次独立在线获取视为相同输入。

实际JSON依赖记录中，Cloud PyArrow为`24.0.0`，虽然源码requirements要求`25.0.1`；HF Docker运行值为25.0.1。因此本次Cloud功能通过，不宣称依赖完全同步。其余已记录的NumPy1.26.4、pandas2.2.2、SciPy1.13.1、scikit-learn1.5.1、joblib1.4.2、threadpoolctl3.5.0、Streamlit1.67.0与Plotly5.24.1一致。精确复现优先使用HF Docker固定环境与同一CSV，保留实际依赖JSON；以后重装或重启需重新核对运行值。


## 共享模块更新后的运行刷新

0.6.0公网验收发现：新规则页已更新，但Cloud报告的research/portfolio.py仍为旧哈希，四组均报allocation_fn参数错误。界面新不等于所有Python模块已更新，先保存失败结果，不能标成功。

0.6.1在入口同目录requirements.txt加入运行代际标记，依赖版本保持不变。官方说明依赖文件变化会触发完整重新部署；若平台未响应，需在原应用管理页执行Reboot，而不是在共享活跃进程中reload模块。重验须同时核对策略、组合模块哈希及实际依赖，运行四组并下载JSON。[官方更新机制](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)、[重新启动说明](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/reboot-your-app)。

用户主要使用Hugging Face，Cloud作为备用服务；后续发布优先验收HF，Cloud的单独状态不阻塞主入口交付，也不能将失败或未验收标作最新可用。
