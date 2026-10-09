# OJ Wall 三工程联动说明

2026-10-09 · v4 首版。此文与本工程代码一同提交；后续调整保留 Git 历史，重大协议变更追加版本记录。

## 职责与统计口径

OJ Wall 负责现有线上提交、经过管理员核验的现场逐题成绩和区域赛覆盖。DLUT CPC 提供人员、逐场确认名单及真人认领审核；CF Bot 保存口胡，并读取本人区域赛进度。本工程不读取其他工程数据库，不接收口胡记录。

登录后访问 `/regionals`。默认覆盖为个人线上通过与现场所在队伍通过的并集，可勾选包含绑定的线上团队账号。按题去重，题格分别标记“个、团、现”；现场队伍通过不冒充个人独立 AC，不写入提交表，不影响线上训练热力图。历史未补齐时明确显示暂无证据。

## 配置与身份审核

`.env` 配置以下三项，Compose 会传入容器：

```dotenv
CPC_DLUT_URL=https://你的DLUT站点
CPC_DLUT_AUTHORITY_ID=DLUT运行库的发布方UUID
CPC_SYNC_TOKEN=管理员配置的服务凭据
```

同机可用私网地址，跨服务器使用 HTTPS；浏览器写操作要求 Origin 与 `PUBLIC_BASE_URL` 一致。用户登录正式账号后选择成员、填写核验说明；DLUT 管理员核验并批准。一个成员只有一个有效认证主账号，无需给 DLUT 成员新建密码系统。

```sh
docker compose exec -T oj-submission-wall python tools/cpc_admin.py sync
docker compose exec -T oj-submission-wall python tools/cpc_admin.py rosters
docker compose exec -T oj-submission-wall python tools/cpc_admin.py meta
```

每 5 分钟同步完整名单和审批快照，检查 schema、发布方、客户端、结构和数量后原子替换。失败不清空成功缓存；24 小时无法核验时停止现场归属。重新拉取自己的进度不会延长 DLUT 身份核验期限。

## 现场榜单导入

首版通过管理员核验文件导入，尚无 XCPCBoard/RankLand 自动适配器。先从 `rosters` 取得该场参赛 UUID，核对比赛、队伍行、题目目录及官方题序，再准备 JSON：

```json
{
  "participation_id": "从rosters取得的UUID",
  "contest_id": "icpc-2024-杭州",
  "team": "与参赛记录一致的队名",
  "source_url": "https://example.com/verified-final-scoreboard",
  "source_row": "稳定榜单行ID",
  "accepted": ["A", "C"],
  "raw_row": {"说明": "原始榜单行或核验记录"}
}
```

示例不是实际成绩。把文件放在持久卷 `data/onsite-row.json`，执行：

```sh
docker compose exec -T oj-submission-wall python tools/cpc_admin.py import /data/onsite-row.json
docker compose exec -T oj-submission-wall python tools/cpc_admin.py import /data/onsite-row.json --confirm
docker compose exec -T oj-submission-wall python tools/cpc_admin.py revoke 证据ID
```

无 `--confirm` 只预览。未知题号整批拒绝；同一来源/行/参赛记录重导替换该条证据并保留历史，重判或撤销按剩余证据重算。不能根据相似队名或总解题数猜逐题通过。

## 本人连接码及接口

用户在区域赛页生成只读连接码，在自己的 CF Bot 账号粘贴一次。码有效期 180 天，生成时仅显示一次；重生成或撤销使旧码立即失效，CF Bot 下次同步移除该投影。OJ Wall 只存摘要，CF Bot 服务端保存连接码；码不放 URL 或浏览器本地存储。线上进度不要求成员认证。

| 接口 | 访问方式 |
| --- | --- |
| GET `/api/cpc/me` | 本站正式用户会话，只查本人 |
| POST `/api/cpc/claim`、`token`、`token/revoke`、`refresh`、`handle-kind` | 本站会话及同源 Origin |
| GET `/api/integration/v1/me/progress/snapshot` | Bearer 本人只读连接码，不接收目标用户 ID |

进度发布 schema 1、本站发布方 UUID、主体 UUID、完整标识、记录数量及个人/团队/现场布尔值。CF Bot 合并到本地投影，不回写本工程。公共题目目录独立打包在 `catalog/regionals.json`，与 CF Bot 对齐；未知题号显示待映射。明显的 `ucup-team` 默认团队类型，其余由本人确认。

## 持久数据与迁移

新增 `cpc_ids`、`cpc_remote`、`cpc_read_tokens`、`cpc_handle_kinds`、`cpc_onsite`、`cpc_onsite_history`，保存稳定 ID、信源缓存、码摘要、账号类型、现场证据及审计历史。原用户、账号和提交表继续独立运行。

迁移保留整个运行 SQLite 库、原始榜单文件、公共目录、`.env` 与公开地址配置。用 SQLite 备份 API 或停写备份，包含 WAL 已提交事务。恢复后 `meta` 应输出原 UUID，CF Bot 更新地址并保留预期 UUID；未到期连接码和已认证关系继续有效。不能从 seed 重建后冒充原站点，同一发布方不能同时有两个生产写入端。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

跨工程流程、迁移与 HTTP 验收入口位于 qq-cf-bot 的 `scripts/test_cpc_flow.py`。

## 版本记录与相关方案

- v4 / 2026-10-09：首版采用人工核验榜单、本人只读连接码、完整快照及持久 UUID；不新增中心服务或外站运行依赖。

完整设计及版本快照：[三工程方案](https://github.com/Code92007/qq-cf-bot/blob/main/docs/cpc-cross-project-integration.md)、[迭代记录](https://github.com/Code92007/qq-cf-bot/blob/main/docs/cpc-integration/CHANGELOG.md)、[统一运维说明](https://github.com/Code92007/qq-cf-bot/blob/main/docs/cpc-integration-operations.md)。
