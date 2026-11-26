# moomoo私有快照与公开研究结果

用户选择：公开研究结果，原始行情不开放下载。实际交易、券商凭据、账户与活动数据库留在本机；HF只运行研究界面。本机主动上传私有研究快照，HF用独立的只读凭据读取，不开放22222或11111到公网。

## 当前已经准备好的内容

- 本机桌面Host已验证可订阅、读取日K和历史5分钟分页；业务错误可能在stderr中返回，不能只看stdout。
- 已取得SPY／NVDA在2026-11-23至25的三个完整RTH日，共468行。原始5分钟为bar-end标签，规范化减5分钟得到UTC bar-start；同日78组5分钟OHLC与每组5根1分钟聚合全部匹配，高精度volume也匹配，供方整数volume差异保留在本机来源审计中。
- 私有发布器`sync_moomoo_snapshot.py`只允许三个文件：内容寻址的CSV、已净化manifest和latest指针。它拒绝公开数据集、哈希不符、未核时间口径和未来bar；不上传完整原始响应、账户、本机路径或密钥。
- HF新增“已发布moomoo 5分钟快照”来源，固定私有仓库与revision，核对文件路径／长度／hash；原始OHLCV只留服务端会话，不提供原始下载。访客仍可上传自己的CSV或选择教学数据。
- 2026-11-26私有Dataset与本机专用写凭据已实际验收，首次三文件上传成功；revision为`81acd7bef19dcfc890b71bc9a70ca7d5a7208c20`，468行与原CSV哈希一致。重复检查只读取现有快照。**Space的独立读取设置尚未完成**，访客刷新仍NOT_CONFIGURED，不能将本机上传描述为网页已读通。

## 管理者的一次性设置

1. 打开[新建Dataset](https://huggingface.co/new-dataset)，Owner选`Rexymiao`，名称`alpha-trading-snapshots`，设为 **Private**。保留初始README／数据卡，以便仓库有初始提交。本机发布器会再次验证private，不会自行切换公开范围。
2. 在[Access Tokens](https://huggingface.co/settings/tokens)创建细粒度令牌，名称可用`alpha-snapshot-local-write`，只选择这个Dataset并给Read／Write内容权限。不要扩大到全部仓库、组织或券商账户。
3. 在本机项目目录的PowerShell执行下面的配置命令；将刚才的写令牌输入隐藏提示框。令牌经Windows当前用户DPAPI加密保存在本机非同步运行目录，不写进源码或聊天。

```powershell
Set-Location -LiteralPath 'D:\Dropbox\量化反思总结\个人量化交易系统\alpha-lab'
& '.\scripts\configure_snapshot_sync.ps1' -RuntimeDir 'C:\Users\Rexy\Documents\ChatGPT\量化准备\alpha-paper-runtime'
```

4. 再创建只针对同一Dataset的 **Read** 令牌，名称可用`alpha-snapshot-space-read`。它供HF服务端读取，和本机写令牌分开。
5. 打开[Space设置](https://huggingface.co/spaces/Rexymiao/alpha-trading-lab/settings)，在Variables／Secrets设置：Variable `ALPHA_SNAPSHOT_DATASET`为`Rexymiao/alpha-trading-snapshots`；Secret `ALPHA_SNAPSHOT_READ_TOKEN`为第4步只读令牌。不要替换GitHub中的`HF_TOKEN`，后者仅负责发布源码；这里不需要moomoo密钥。

官方参考：[细粒度令牌](https://huggingface.co/docs/hub/security-tokens)、[Space变量与Secrets](https://huggingface.co/docs/hub/spaces-overview#managing-secrets-and-environment-variables)。

## 首次发布与验收

以下路径是已验证的本机快照，原始数据不进公开仓库。发布器默认只本机检查；加`--publish`才访问固定的私有Dataset。新机器先在独立环境安装`requirements-snapshot.txt`。

```powershell
& '.\state\snapshot-sync-venv\Scripts\python.exe' '.\scripts\sync_moomoo_snapshot.py' --csv '.\data\intraday\moomoo-5m-rth-2026-11-26T12-08-27-350Z-203720\moomoo-5m-rth.csv' --source-manifest '.\data\intraday\moomoo-5m-rth-2026-11-26T12-08-27-350Z-203720\manifest.json' --publish
```

另一个PowerShell会话需将`ALPHA_SNAPSHOT_TOKEN_DPAPI`指向上面运行目录中的`hf-snapshot-write-token.dpapi`；也可以在当前进程提供`ALPHA_SNAPSHOT_WRITE_TOKEN`，不保存为全局明文环境变量。缺少配置时明确失败，不尝试复用GitHub／Space部署令牌。

上传后在HF选择“5分钟动量与趋势 → 已发布moomoo 5分钟快照 → 运行”。同一会话的参数对比复用同一固定revision；刷新只获取新快照，不重算旧结果。核对来源为moomoo、468行、三天共同有效日、as_of为2026-11-25T21:00:00Z，CSV SHA256为`5b126b01d9bf29d4d1bb7e63735f0994b15193b3ac1792fb0b29bb130794ff14`。原始CSV不出现下载入口，研究JSON可以下载；该JSON包含策略结果与来源指纹，不包含整个原始OHLCV表。

## 配置验收后的窗口同步入口

`run_snapshot_sync.py`已提供前台运行器，默认只采集／准备，不上传；`--publish`才使用独立写凭据，`--watch`才在当前进程持续检查。窗口为美东今天之前的最近3个XNYS交易日，支持半日市，不是盘中实时推送。相同窗口与代码／版本复用检查点；缺凭据、标签版本变化或上传结果不明时明确停止，不盲重试。

```powershell
# 已完成首次真实私有上传／读取验收后再使用--publish。
$env:ALPHA_SNAPSHOT_TOKEN_DPAPI = 'C:\Users\Rexy\Documents\ChatGPT\量化准备\alpha-paper-runtime\hf-snapshot-write-token.dpapi'
& '.\state\veighna-venv\Scripts\python.exe' '.\scripts\run_snapshot_sync.py' --runtime-dir 'C:\Users\Rexy\Documents\ChatGPT\量化准备\alpha-paper-runtime' --symbols SPY,NVDA --sessions 3 --publish
```

若要持续检查，在同一命令末尾显式加`--watch`；停止不会修改交易模式或取消订单。目前真实私有上传已经完成，但Space独立读取尚待用户添加Variable与Secret；没有启动watch或创建任务。发布器SDK环境与本机执行环境分开安装。

Windows真实运行修复：若从PowerShell7启动，旧实现可能让Windows PowerShell5继承不兼容PSModulePath，从而报LOCAL_PROTECTED_TOKEN_UNAVAILABLE，即使DPAPI凭据有效。当前发布器对子进程使用绝对powershell.exe路径和仅系统模块环境，已通过真实凭据再读取。不要仅因该旧错误重新生成或转存明文令牌。

## 与本机交易的分工

本机交易运行器按交易日历在5分钟bar完成后采集、生成信号并记录状态；券商模拟委托在本机经独立风控与认证处理。HF读取的是有来源的历史研究快照，首版研究仍要求共同完整交易日，未完成当天不会被悄悄当作完整日加入收益评价。

自动发布须在首次私有上传／读取验收通过后接入本机任务；没有创建或启动后台同步任务时必须如实标记。HF休眠、网络故障或无访客不应影响本机风控、订单及对账，公开界面也不能作为下单指令来源。
