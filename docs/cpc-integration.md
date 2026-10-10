# OJ Wall 三工程联动说明

2026-10-09 · v4.2。此文与本工程代码一同提交；后续调整保留 Git 历史，重大协议变更追加版本记录。

## 职责与统计口径

OJ Wall 负责现有线上提交、按确认名单核验的现场逐题成绩和区域赛覆盖。DLUT CPC 提供人员、逐场确认名单及真人认领审核；CF Bot 保存口胡，并读取本人区域赛进度。本工程不读取其他工程数据库，不接收口胡记录。

登录后访问 `/regionals`。成员选择支持输入部分姓名、学校或校区筛选；筛选与已选成员在定时刷新后保留，筛选排除原成员时清空选择，避免误提交。默认覆盖为个人线上通过与现场所在队伍通过的并集，可勾选包含绑定的线上团队账号。按题去重，题格分别标记“个、团、现”；现场队伍通过不冒充个人独立 AC，不写入提交表，不影响线上训练热力图。历史未补齐时明确显示暂无证据。

## 配置与身份审核

`.env` 配置以下三项，Compose 会传入容器：

```dotenv
CPC_DLUT_URL=https://你的DLUT站点
CPC_DLUT_AUTHORITY_ID=DLUT运行库的发布方UUID
CPC_SYNC_TOKEN=管理员配置的服务凭据
```

同机可用私网地址，跨服务器使用 HTTPS；浏览器写操作要求 Origin 与 `PUBLIC_BASE_URL` 一致。用户登录正式账号后选择成员、填写核验说明；管理员登录 DLUT CPC 的 `/admin`，进入“成员认证”，查看申请账号及核验说明后批准、拒绝或撤销；原 Docker 审核命令继续可用。一个成员只有一个有效认证主账号，无需给 DLUT 成员新建密码系统。

```sh
docker compose exec -T oj-submission-wall python tools/cpc_admin.py sync
docker compose exec -T oj-submission-wall python tools/cpc_admin.py rosters
docker compose exec -T oj-submission-wall python tools/cpc_admin.py meta
```

每 5 分钟同步完整名单和审批快照，检查 schema、发布方、客户端、结构和数量后原子替换。失败不清空成功缓存；24 小时无法核验时停止现场归属。重新拉取自己的进度不会延长 DLUT 身份核验期限。

## 认证批准后自动同步

默认每 5 分钟检测认证结果，批准后遍历该成员在 DLUT 的全部已确认参赛名单。复用 DLUT 点击比赛名使用的榜单映射，通过快照可选 `ranklist_url` 获取，不访问或复制 DLUT 运行目录。已有来源链接和 CPC Finder 选手/比赛 ID 作补充；即使没有 CPC Finder 档案，也同步已有 RankLand/XCPCIO 榜单的老比赛。

XCPCIO 按固定 Git 提交保存 config/team/run，核对日期、队名、DLUT 校名别名、可用队员和完整题序，按赛中提交最终 verdict 计算 AC。RankLand 读取 general/static SRK 的完整逐题最终状态与首解，核对比赛时间及可用归档行 ID；封榜、未决、未知结果或匹配歧义拒绝当次导入。CPC Finder 总解题数不代替逐题证据。

正式和打星的真实赛中 AC 均计入，并与原有线上 AC 按题合并；不写入个人提交表。每场自动证据按参赛 UUID 唯一更新，重判可移除旧现场 AC，失败保留成功数据。成功每天复核、失败每 5 分钟重试；“更新认证状态”或上述 sync 命令可主动重试。已有认证首次升级即自动补刷。页面“现场比赛通过”显示比赛、题号、打星标记、原榜单及同步状态。

唯一 Gym 重现链接可建立逐题别名并与线上记录去重；尚未入公共区域赛目录的比赛保留原始成绩和现场历史，显示题目待映射。认证撤销或过期后停止该人员的现场归属，保留其真实线上提交。

外部榜单请求只访问允许的公开域名，不发送 CPC_SYNC_TOKEN、不跟随重定向，并限制超时与响应大小。原始榜单保存在持久卷 `/data/cpc_sources/`，证据保留哈希和选中行信息。

## 人工榜单导入（备用）

不支持的来源仍可通过管理员核验文件导入。先从 `rosters` 取得该场参赛 UUID，核对比赛、队伍行、题目目录及官方题序，再准备 JSON：

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

新增 `cpc_ids`、`cpc_remote`、`cpc_read_tokens`、`cpc_handle_kinds`、`cpc_onsite`、`cpc_onsite_history`、`cpc_onsite_sync`，保存稳定 ID、信源缓存、码摘要、账号类型、现场证据、审计历史及自动同步状态。原用户、账号和提交表继续独立运行。

迁移保留整个运行 SQLite 库、`data/cpc_sources/` 原始榜单文件、公共目录、`.env` 与公开地址配置。用 SQLite 备份 API 或停写备份，包含 WAL 已提交事务。恢复后 `meta` 应输出原 UUID，CF Bot 更新地址并保留预期 UUID；未到期连接码和已认证关系继续有效。不能从 seed 重建后冒充原站点，同一发布方不能同时有两个生产写入端。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

跨工程流程、迁移与 HTTP 验收入口位于 qq-cf-bot 的 `scripts/test_cpc_flow.py`。

## 版本记录与相关方案

- 2026-10-09 界面迭代：成员选择增加关键词筛选、匹配人数和无匹配提示；仍由 DLUT CPC 管理员审核认领。

- v4.2 / 2026-10-09：批准认证自动同步所有已有原榜单的确认场次，复用 DLUT 比赛映射；打星 AC、重判、失败重试与线上合并保持来源独立。

- v4.1 / 2026-10-09：DLUT CPC 增加网页成员认证审核入口，沿用原审批快照；本工程用户可点击“更新认证状态”取得结果。

- v4 / 2026-10-09：首版采用人工核验榜单、本人只读连接码、完整快照及持久 UUID；不新增中心服务或外站运行依赖。

完整设计及版本快照：[三工程方案](https://github.com/Code92007/qq-cf-bot/blob/main/docs/cpc-cross-project-integration.md)、[迭代记录](https://github.com/Code92007/qq-cf-bot/blob/main/docs/cpc-integration/CHANGELOG.md)、[统一运维说明](https://github.com/Code92007/qq-cf-bot/blob/main/docs/cpc-integration-operations.md)。

## 2026-10-10 区域赛页面和历史赛季

区域赛页采用宽松的逐题卡片表格，显示个人、团队和现场来源，不添加 rating。现场记录改为比赛、日期、参赛队伍、现场通过、榜单五列，长名称换行，打星及待映射保留独立标签。团队选项为小开关；年份为页面内 16px 字号、40px 行高的下拉菜单，支持键盘选择与 Escape 关闭。

公共目录与 CF Bot 一致，新增 2019–2022 年 42 场、528 题，合计 2019–2025 年 75 场、954 题；按赛季归档延期比赛。来源留在 `catalog/regional_history_sources.json`。新增 528 题中 488 题已核对平台题号；剩余 40 题的线上映射显式标为 pending，现场通过照常进入规范题目 ID，不能猜测线上题号。新增银川、南昌、徐州、广州、厦门及 haerbin 旧别名识别，修正 XCPCIO 2021/2022 归档届次路径。部署后对已有认证执行 sync，稳定参赛 UUID 会替换暂存题号并保留历史，不重复导入。

此迭代不改变 v4.2 的审批触发、每 5 分钟同步、个人 AC 合并或迁移协议。

生产验证（2026-10-10）：本工程 `8e21e32` 与 CF Bot `7ca496a` 已部署。已有认证强制补刷完成 9/9 场、36 道现场 AC，其中 31 道进入 2019/2020/2024 区域赛目录；打星保留，另外 5 道属于目录外比赛，仍保存在现场记录。114,160 条原线上提交无缺失；两个 CF Bot 连接刷新成功。备份、旧镜像和验证报告位于 `/root/backups/cpc-regional-history-20261010-004406/`；源站地址仍由环境变量配置，迁移规则不变。

目录并行更新对齐（2026-10-10）：沿用 CF Bot 已核对的最新 QOJ/Gym 题号和真实题名。待映射仅剩 2019 ICPC 沈阳/南昌、2022 ICPC 合肥共 39 题及 2020 CCPC 秦皇岛 C；Gym 102769 没有 C，不构造其别名。现场题序和通过仍完整保留；目录中的题号映射优先于榜单重现链接推导。CF Bot 的离线历史评级由该工程独立维护，本工程不展示 rating。


## 2026-10-10：Coach 私有补题与公开 VP 合并

济南 2022（Gym 104076）排查：匿名 `user.status`、按 handle 的 `contest.status`、完整 40007 条比赛提交均只能找到 Yzm007 的 31 条记录、A/E/K/M 四题 AC；截图中的 C/D/G/J 五条 AC 提交 ID 不在匿名结果中。用户确认开过 Coach。公开结果没有 MANAGER 类型，需使用本人授权进一步核验，不能把截图直接写成平台提交。

OJ Wall 可选使用 Codeforces 官方签名 API，读取配置账号的 `user.status`，再对该账号已知的 Gym 调用带 `handle` 与 `asManager=true` 的 `contest.status`，合并真实的 MANAGER/PRACTICE/VIRTUAL 提交；按原 remote_id 幂等去重。已知 Gym 来自该账号在十年窗口内已保存的个人/团队提交及本次新提交，不查询其他用户的完整榜单。Coach 的 AC 参与线上题目覆盖和训练记录，不生成参赛成绩，不参与赛中对战计算；已有团队 VP 与现场通过继续按题取并集。首次授权或更换 Key 自动回补 `FETCH_LOOKBACK_DAYS`（默认十年）内 user.status 历史，成功后恢复其增量同步；已知 Gym 的本人 Coach 历史每轮完整补查，避免早于全局增量时间戳的旧补题继续遗漏。任一网络/签名/格式错误不写入部分数据、不推进回补标记、不降级为匿名成功；平台明确拒绝某场 Coach 权限时保留其公开记录并提示该场私有补题待核验，下一轮继续重试。签名请求按 2.1 秒间隔执行，不写共享 HTTP 缓存，错误信息不回显 Key/签名。

管理员先核对 OJ Wall 正式用户 ID 与已绑定 CF handle，再让账号本人在 [CF API 设置](https://codeforces.com/settings/api) 生成自己的 Key/secret。在服务器交互输入（无回显，避免放进命令历史或聊天）：

```sh
cd /root/oj-submission-wall
docker compose exec oj-submission-wall python tools/configure_codeforces.py --owner-id 3 --handle Yzm007
```

默认文件 `/data/codeforces-auth.json`，对应宿主机 `data/codeforces-auth.json`，权限 0600；可以用 `CODEFORCES_AUTH_FILE` 改位置。支持多个内部用户，严格匹配 ownerId 和 handle，不给同名的其他 Wall 用户或游客使用该授权；Gym 响应逐条检查比赛 ID 和 author.members，拒绝混入他人提交。文件格式如下（占位示例）：

```json
{"accounts":[{"ownerId":"3","handle":"Yzm007","key":"本人API Key","secret":"本人API secret"}]}
```

配置后无需重启，下一轮自动同步会补拉，或在训练墙主动刷新。迁移时连同原 SQLite 和整个 data 卷复制，保留本地用户 ID、服务 UUID、授权文件权限；回补标记也随数据库迁移。撤销授权可删除对应配置并在 CF 设置撤销 Key，已保存的真实提交继续保留。此授权仅由 Wall 使用，CF Bot 仍只读 Wall 进度，DLUT CPC 仍只管理人员/队伍关系。

验证迭代：本人授权后实测，签名 user.status 返回 5320 条并新增 310 条私有记录，但仍遗漏 MANAGER；签名 contest.status 默认返回 31 条，显式 asManager=true 返回 49 条，含 18 条 MANAGER，其中五条 AC ID 与截图完全一致：226752209（J）、226715410（C）、226606542 / 226606494（G）、226567874（D）。因此修正同步通路；回归模型也改为 user.status 不返回 MANAGER，避免只验证理想化数据。12 项授权/Coach 回归、原有测试共 47 项通过，覆盖分页失败重试、权限拒绝警告和他人记录拒绝。官方协议参考：[API 授权](https://codeforces.com/apiHelp)、[user.status](https://codeforces.com/apiHelp/methods#user.status)。
