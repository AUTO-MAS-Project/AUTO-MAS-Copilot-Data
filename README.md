# AUTO-MAS-Copilot-Data

为 MAS 的作业练度分析生成全站公开快照。覆盖全部公开作者和作业，只保留作业编号、标题、作者、关卡、干员与候选组要求，不保存游戏账号、森空岛凭据、战斗动作或评论。

流程参考 [AUTO-MAS-Maintenance](https://github.com/AUTO-MAS-Project/AUTO-MAS-Maintenance)：默认分支维护代码，独立 `data` 分支保留最近成功结果，随后上传 MAS 下载站并回读校验。同步失败不会发布半成品，也不会覆盖上一份完整快照。

## 手动和每日执行

每天北京时间 **05:17** 自动完整更新。GitHub 定时任务可能排队延迟。

打开 **Actions → 更新作业快照并上传下载站 → Run workflow**，选择默认分支 `dev`：

- `operation=update`：完整拉取全站作业，保存到 `data` 分支，再上传下载站。
- `operation=sync`：只重试上传 `data` 分支中最近的完整快照，不重新抓取，不更新时间。

PowerShell 7 也可以触发：

```powershell
gh workflow run update.yml --repo AUTO-MAS-Project/AUTO-MAS-Copilot-Data --ref dev -f operation=update
```

上传失败时，完整结果仍保留在 `data` 分支。首次运行没有 `data` 分支时必须先执行 `update`。并发运行串行排队，不强推任何分支。

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

`data` 分支只包含：

- `maa-copilot.json.gz`：gzip 压缩的 UTF-8 JSON，字段 `version=1`、`updatedAt`（Unix 秒）、`checkedAt`、`count`、`assignments`。
- `manifest.json`：协议版本、更新时间、作业数量和 gzip 文件的 SHA-256。

`assignments` 保留 `id`、`title`、`stage`、`author`、`authorId`、`opers`、`groups`。只分析作者实际填写的结构化练度要求，不会把缺失要求补成推荐满练。

MAS 优先下载站，GitHub `data` 分支作为备用，最后可从作业站完整拉取。作者、作业集和单份作业查询仍使用公开接口。

## 本地生成

需要 Python 3.12+、uv 和 PowerShell 7；上传命令还需系统 `curl`（Actions runner 已提供）：

```powershell
uv sync --locked
$env:PYTHONPATH = 'src'
uv run --no-sync python -m copilot_data build
```

许可证：AGPL-3.0-or-later。作业内容及其权利归原作者所有。
