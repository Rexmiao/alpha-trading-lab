# GitHub 上传与后续维护

目标仓库：[Rexmiao/alpha-trading-lab](https://github.com/Rexmiao/alpha-trading-lab)。本项目沿用现有 GitHub App，不另起包含组织访问的登录流程。

## 授权方式

1. 通过现有连接器检查目标仓库和 App 可访问仓库列表。
2. 新建仓库若返回 `403 Resource not accessible by integration`，先检查 App 是否只授权了旧仓库。能够读取公开仓库，并不代表 App 已获得写入权限。
3. 在 [GitHub App 安装设置](https://github.com/settings/installations) 中进入已有 App 的配置，在 **Selected repositories** 加入本次目标个人仓库并保存。保留已有授权；不改成全部仓库，不申请组织范围。
4. 再检查目标仓库是否进入 App 列表，并以待上传的实际源文件验证写入。无需索取或保存个人访问令牌。

当前连接器可上传文件，但没有创建仓库的工具。需要新仓库时，由用户建立并初始化 README，再通过以上方式补充该目标仓库访问即可。本项目仓库已由用户建立，后续复用现有仓库。

## 上传范围与步骤

上传包括代码、SPEC、依赖、测试、论文索引、API 手册、教学 GIF/封面和 `web/` 静态网页源码。论文原文通过官方链接访问，全文是否可再分发需单独确认。

`data/`、`runs/`、`state/`、聊天截图、账户、凭据及本地模型权重不上传。上传使用明确源文件清单，不能把整个上级资料文件夹当作仓库。

1. 先更新 [SPEC](../SPEC.md)、[README](../README.md) 和对应手册，检查相对链接与依赖。
2. 读取远端分支当前提交和目录对象，保留用户初始化的 MIT License 与已有文件。
3. 对待上传文件计算内容哈希。使用 Git 数据接口创建 blob；GIF/PNG 等二进制以 base64 传输，核对返回 Git blob SHA 与本地文件一致。
4. 基于现有目录对象建立新 tree，再创建以当前提交为父提交的 commit。
5. 以预期旧提交号更新目标分支，拒绝强制覆盖。若分支在此期间变化，先读取新提交并核对差异。
6. 回读远端提交和文件，核对哈希、README 资料入口及中英文动画路径。确认成功后再报告上传完成。

## 与公开教学网站的关系

GitHub 保存研究代码、复现资料和 README 动图。量化教学页现采用 GitHub Pages 发布方案；原有[教学页链接](https://alpha-training-lab-guide.totalbluebell3.chatgpt.site)保留，待新站点部署与交互检查成功后，再将新地址标为主入口。上传源码本身不代表 Pages 已经启用或部署成功。

首次启用：在[本仓库 Pages 设置](https://github.com/Rexmiao/alpha-trading-lab/settings/pages)中将 Source 设为 **GitHub Actions**。使用现有 GitHub 登录，不新建 OAuth 流程，也不提供令牌。当前连接器只有源码与工作流相关操作，没有 Pages 管理设置接口。

[部署工作流](../.github/workflows/pages.yml)在 main 的 web/、校验脚本或工作流变化后自动运行，并提供 workflow_dispatch 手动入口。发布前运行 `python scripts/validate_public_site.py`，只将 `web/` 上传为静态产物；不上传整个仓库。部署所用临时 GITHUB_TOKEN 权限为 contents:read、pages:write、id-token:write，不能用它代替首次启用 Pages 的管理操作。

在 Actions 的 **Deploy teaching site to GitHub Pages** 中查看执行结果。工作流先检查首次设置：Pages未启用时给出notice并跳过发布，这种绿色检查不代表网站已上线；启用后重新运行任务。其他HTTP错误必须失败，不静默忽略。以实际部署步骤返回的page_url、成功状态和HTTP检查为准，不能仅按域名规则推断已经上线。

维护方式：网页源码以 main 的 web/ 为准，修改后提交触发发布。语言切换、五个滑块、GIF 播放/暂停和下载均由浏览器 JavaScript 执行，Pages 上保留这些交互；Python 训练及 moomoo 采集继续在本机运行。

网页导出文件位于 `web/`。在仓库根目录运行：

```powershell
python -m http.server 8512 --bind 127.0.0.1 --directory web
```

再打开 http://127.0.0.1:8512/ 。网页不依赖 moomoo 在线或本机研究结果。更新动画与网页后，需同步导出文件并按 [SPEC](../SPEC.md) 验证语言切换与交互。
