# AUTO-MAS-Copilot-Data

为 MAS 的作业练度分析生成全站公开快照。覆盖全部公开作者和作业，只保留作业编号、标题、作者、关卡、干员与候选组要求，不保存游戏账号、森空岛凭据、战斗动作或评论。

同时生成一图流完整养成快照 `cultivate_dataset.json.gz`，包含 MAS 已使用的整理后材料数据和干员目录，不包含用户目标、库存或角色练度。

流程参考 [AUTO-MAS-Maintenance](https://github.com/AUTO-MAS-Project/AUTO-MAS-Maintenance)：默认分支维护代码，独立 `data` 分支保留最近成功结果，随后上传 MAS 下载站并回读校验。同步失败不会发布半成品，也不会覆盖上一份完整快照。

## 手动和每日执行

作业快照每天北京时间 **03:25** 自动完整更新。GitHub 定时任务可能排队延迟。

打开 **Actions → 更新作业快照并上传下载站 → Run workflow**，选择默认分支 `dev`：

- `operation=update`：完整拉取全站作业，保存到 `data` 分支，再上传下载站。
- `operation=sync`：只重试上传 `data` 分支中最近的完整快照，不重新抓取，不更新时间。

PowerShell 7 也可以触发：

```powershell
gh workflow run update.yml --repo AUTO-MAS-Project/AUTO-MAS-Copilot-Data --ref dev -f operation=update
```

上传失败时，完整结果仍保留在 `data` 分支。首次运行没有 `data` 分支时必须先执行 `update`。并发运行串行排队，不强推任何分支。

## 一图流养成快照

独立工作流 **Actions → 更新养成快照并上传下载站** 每天北京时间 **13:25** 运行，也支持 `operation=update` 和 `operation=sync`。GitHub 定时任务可能排队延迟。两类工作流超时均为 **45 分钟**，共用并发组串行更新 `data` 分支，各自保存时保留另一类快照。

`update` 完整读取干员需求表、掉落矩阵、关卡信息、合成配方和材料信息，按 MAS 的现有规则整理为 UTF-8 JSON，再以 gzip 压缩，而不是将五份源文件打包。干员目录从本轮同一份需求表生成；任何源失败、为空或结果缺少完整材料数据/目录时，不生成新快照，也不发布半成品。`sync` 只重传 `data` 分支已保存的完整压缩文件，不重新压缩、不修改其生成时间。

`cultivate_dataset.json.gz` 解压后的 `cultivate_dataset.json` 沿用 MAS 本地缓存结构：

| 字段 | 内容 |
| --- | --- |
| `saved_at` | 材料数据生成时间，Unix 秒 |
| `dataset` | `schema_version=2` 的需求、掉落、关卡、配方、材料分类及价值数据 |
| `operators` | 干员目录，含技能/模组名称、可达档位和原始技能序号 |
| `operators_saved_at` | 目录生成时间，Unix 秒；与本轮材料数据同时生成 |

配套 `cultivate_manifest.json` 记录协议版本、生成时间、干员数量和 **gzip 文件**的 SHA-256。两份文件都保存到 `data` 分支；下载站上传的是 **`cultivate_dataset.json.gz` 压缩文件**，MIME 类型为 `application/gzip`。压缩头不记录当前时间，保证同一份 JSON 重复压缩的字节一致。

先按下文配置独立的养成文件、密钥和两个变量。已有的明文 JSON v1 养成目标可沿用其文件 ID 和固定公开地址，无须再次手动上传或新建文件；运行一次 `update` 在 `data` 分支生成 gzip 快照并上传新版本，若上传失败，可在配置修复后运行 `sync` 重传已保存的 gzip。客户端读取时须先解压，再加载其中的 JSON。

整理规则摘录自 [AUTO-MAS 固定版本的养成数据层](https://github.com/AUTO-MAS-Project/AUTO-MAS/blob/2ac826c8cebad7725e9854b4c70f6c43f24d2712/app/task/MAA/tools/cultivate/yituliu.py)，独立保存在 `src/copilot_data/cultivate_source.py`，保留来源版本与署名。MAS 改变整理规则或快照格式时，应同步此模块并运行契约测试。上游数据来自[明日方舟一图流](https://ark.yituliu.cn)及其[公开数据仓库](https://github.com/Arknights-yituliu/frontend-v2-plus)；本仓库不改变原数据的权利归属。

本仓库负责生成和发布快照；MAS 客户端改为优先下载此文件的逻辑需在主程序仓库另行接入。

### 养成快照的下载站配置

先在下载站 AUTO-MAS → 客户端支持中创建一个**独立养成快照文件**，不要使用作业快照的文件 ID 或地址。配置：

| 类型 | 名称 | 含义 |
| --- | --- | --- |
| Secret | `AUTOMAS_CULTIVATE_TOKEN` | 养成快照独立的 Access Key，仅授权上传并自动发布养成快照文件 |
| Variable | `AUTOMAS_CULTIVATE_FILE_ID` | 新养成快照文件的数字 ID |
| Variable | `AUTOMAS_CULTIVATE_PUBLIC_URL` | 新文件固定的 `https://data.auto-mas.top/api/v1/files/.../download` 公开地址 |

工作流将独立 Secret 和两个变量映射为发布工具的 `AUTOMAS_TOKEN`、`AUTOMAS_FILE_ID` 和 `AUTOMAS_PUBLIC_URL`，复用上传、发布状态检查和公开回读校验。养成工作流只读取 `AUTOMAS_CULTIVATE_TOKEN`，不回退使用作业快照的 `AUTOMAS_TOKEN`。未配置新目标或独立密钥时上传步骤失败，完整生成结果仍保留在 `data` 分支，配置后可手动 `sync`。

本地生成及校验（不上传、不推送）：

```powershell
uv sync --locked
$env:PYTHONPATH = 'src'
uv run --no-sync python -m copilot_data build --dataset cultivate
uv run --no-sync python -m unittest discover -s tests -v
```

## 下载站配置

先在 `data.auto-mas.top` 的 AUTO-MAS 项目中建立独立快照文件，不覆盖维护状态文件。为该目标配置：

当前目标文件 ID 为 `106`，位于 AUTO-MAS → 客户端支持，固定公开下载地址：
<https://data.auto-mas.top/api/v1/files/auto-mas/Client/maa-copilot-json-gz/download>。

| 类型 | 名称 | 含义 |
| --- | --- | --- |
| Secret | `AUTOMAS_TOKEN` | 有权上传目标文件并自动发布的下载站 Access Key |
| Variable | `AUTOMAS_FILE_ID` | 目标文件的数字数据库 ID |
| Variable | `AUTOMAS_PUBLIC_URL` | 不带版本参数的公开下载 URL |

上传接口与维护状态仓库一致：`POST /api/v1/user/files/{file_id}/versions`，Bearer Access Key，multipart 字段 `file` 和 `change_note`。上传文件名为 `maa-copilot.json.gz`。根据[下载站文档](https://github.com/AUTO-MAS-Project/AUTO-MAS-data-center-backend/blob/main/docs/API_EXAMPLES.md)，GitHub runner 直接向境外入口 `https://data2.auto-mas.top` 上传，公开地址仍使用 `data.auto-mas.top`。凭证只允许发送到这两个已确认的数据中心 HTTPS 主机、当前文件的上传路径；不自动重试不确定的上传。已公开的内容一致时跳过重复上传，未审核、未发布或公开回读内容不一致都判定失败。

## 快照协议

作业快照在 `data` 分支保存：

- `maa-copilot.json.gz`：gzip 压缩的 UTF-8 JSON，字段 `version=2`、`updatedAt`（Unix 秒）、`checkedAt`、`count`、`assignments`。
- `manifest.json`：协议版本、更新时间、作业数量和 gzip 文件的 SHA-256。

`assignments` 保留 `id`、`title`、`stage`、`author`、`authorId`、`type`、`protocolVersion`、`opers`、`groups`。遇到 v2 作业的模组要求时，从 [ZOOT 官方干员目录](https://github.com/ZOOT-Plus/zoot-plus-frontend/blob/dev/src/models/generated/operators.json) 读取对应干员的模组顺序，并写入 `moduleOrders`；保留原始要求，供 MAS 按作业版本迁移，分析时不再联网读取模组目录。

快照版本与作业协议版本分开记录；旧版 `version=1` 快照缺少作业版本，必须运行 `operation=update` 重新生成，不能通过 `sync` 续传。只分析作者实际填写的结构化练度要求，不会把缺失要求补成推荐满练。

MAS 优先下载站，GitHub `data` 分支作为备用，最后可从作业站完整拉取。作者、作业集和单份作业查询仍使用公开接口。

## 本地生成

需要 Python 3.12+、uv 和 PowerShell 7；上传命令还需系统 `curl`（Actions runner 已提供）：

```powershell
uv sync --locked
$env:PYTHONPATH = 'src'
uv run --no-sync python -m copilot_data build
```

许可证：AGPL-3.0-or-later。作业内容及其权利归原作者所有。
