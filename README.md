# OJ Submission Wall

OJ Submission Wall 是一个给算法训练队、社团或小团队使用的做题统计墙。成员绑定自己的 OJ 账号后，系统会同步公开提交记录，生成类似 GitHub contributions 的训练绿墙，并展示最新提交、解题数、连续训练天数和参赛统计。

如果只是想直接使用，可以访问公开站点：[https://oj-train-wall.wannafly.cn](https://oj-train-wall.wannafly.cn)。

如果你想自建一套给自己的队伍使用，可以 fork 本仓库并按下面的说明部署。

## 功能

- 支持游客模式和用户名密码注册，注册不需要邮箱验证。
- 支持成员昵称、真实姓名、分组管理和成员详情页。
- 支持绑定 Codeforces、AtCoder、牛客、洛谷、VJudge、LOJ、QOJ。
- 支持按年或近 10 年查看训练绿墙。
- 支持最新提交列表、平台/用户/语言/状态/时间范围筛选和分页。
- 支持比赛统计，按平台和常见比赛类型聚合。
- 支持本地 SQLite 持久化和 HTTP 缓存，平台接口临时失败时保留上次成功数据。
- 无前端构建依赖，后端只使用 Python 标准库，适合 Docker 轻量部署。

## 快速开始

本地运行：

```bash
python3 app.py
```

打开 `http://localhost:8000`。

Docker 运行：

```bash
cp .env.example .env
docker compose up -d --build
```

数据默认保存在 `./data/ojwall.sqlite3`。升级时保留 `data/` 目录即可。

## 自部署

推荐生产环境放在 Nginx 或 Caddy 后面，并使用 HTTPS。

1. 准备域名解析

   在你的 DNS 服务商处添加一条 A 记录：

   | 主机记录 | 记录类型 | 记录值 |
   | --- | --- | --- |
   | `oj` 或你喜欢的子域名 | `A` | `<你的服务器公网 IP>` |

   例如你的域名是 `example.com`，可以把服务挂在 `https://oj.example.com`。

2. 拉取代码

   ```bash
   git clone https://github.com/<your-name>/oj-submission-wall.git
   cd oj-submission-wall
   cp .env.example .env
   ```

3. 修改 `.env`

   ```bash
   PUBLIC_BASE_URL=https://oj.example.com
   BIND_ADDRESS=127.0.0.1
   PORT=8000
   COOKIE_SECURE=true
   OJ_USER_AGENT=OJSubmissionWall/1.0 (+https://oj.example.com)
   LUOGU_USER_AGENT=OJSubmissionWall/1.0 (+https://oj.example.com)
   ```

4. 启动应用

   ```bash
   docker compose up -d --build
   docker compose ps
   ```

5. 配置反向代理

   仓库里提供了两份示例配置：

   - [deploy/nginx.oj-train-wall.conf](deploy/nginx.oj-train-wall.conf)：Nginx 示例
   - [deploy/Caddyfile.oj-train-wall](deploy/Caddyfile.oj-train-wall)：Caddy 示例

   这些文件使用公开站点域名作为示例。自部署时请把 `server_name`、站点域名和反代端口改成你自己的配置。

后续更新：

```bash
git pull --ff-only
docker compose up -d --build
```

## 账号绑定格式

- Codeforces：填写 handle，例如 `tourist`。
- AtCoder：填写用户名，例如 `tourist`。
- 牛客：填写竞赛个人页数字 ID，例如 `https://ac.nowcoder.com/acm/contest/profile/123456` 里的 `123456`。
- 洛谷：填写用户名、数字 UID 或用户主页链接。
- VJudge：填写 VJudge 用户名。
- LOJ：填写 LOJ 用户名。
- QOJ：填写 QOJ 用户名。QOJ 有 Cloudflare 校验，默认不会要求用户提供登录态，未配置时会提示无法精确同步。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PUBLIC_BASE_URL` | 当前 Host | 应用公网地址 |
| `BIND_ADDRESS` | `0.0.0.0` | Docker 对宿主机暴露的绑定地址；反向代理部署建议设为 `127.0.0.1` |
| `PORT` | `8000` | 宿主机端口 |
| `DATA_DIR` | `/data` | SQLite 数据目录 |
| `COOKIE_SECURE` | `false` | HTTPS 部署建议设为 `true` |
| `SYNC_INTERVAL_SECONDS` | `900` | 后台同步间隔，设为 `0` 可关闭后台同步 |
| `SYNC_MIN_AGE_SECONDS` | `120` | 同一账号最短同步间隔 |
| `FETCH_LOOKBACK_DAYS` | `3650` | 首次或强制同步时回看天数 |
| `FETCH_LIMIT` | `1000` | 支持分页的平台单页拉取数量上限 |
| `HTTP_TIMEOUT_SECONDS` | `15` | 外部 OJ 单次请求超时时间 |
| `HTTP_RETRY_COUNT` | `2` | 外部 OJ 超时或 5xx 时的额外重试次数 |
| `HTTP_RETRY_BACKOFF_SECONDS` | `0.8` | 外部 OJ 重试退避基准秒数 |
| `DISPLAY_TZ_OFFSET_HOURS` | `8` | 榜单日期、连续天数和提交时间展示的时区偏移 |
| `CACHE_DIR` | `DATA_DIR/cache` | HTTP 响应缓存和概览镜像目录 |
| `HISTORICAL_CACHE_AFTER_DAYS` | `30` | 距今超过多少天的历史页可直接使用缓存 |
| `HISTORICAL_CACHE_TTL_SECONDS` | `315360000` | 历史页缓存有效期，默认约 10 年 |
| `OVERVIEW_CACHE_TTL_SECONDS` | `20` | `/api/overview` 页面组装结果的内存缓存秒数 |
| `OJ_USER_AGENT` | `OJSubmissionWall/1.0` | 外部 OJ 请求的 User-Agent，生产环境建议包含你的站点地址 |
| `LUOGU_USER_AGENT` | `OJSubmissionWall/1.0` | 洛谷请求的 User-Agent，生产环境建议包含你的站点地址 |
| `LUOGU_CF_CLEARANCE` | 空 | 可选：服务器同出口浏览器合法通过 Cloudflare 后拿到的 `cf_clearance` 值，不是登录态 |
| `LUOGU_COOKIE` | 空 | 可选：管理员自己的洛谷 Cookie；公开部署不建议收集用户 Cookie |
| `LUOGU_PROXY_URL` | 空 | 可选：洛谷海外 403 时，把洛谷请求转发到可信的国内出口代理 |
| `LUOGU_PROXY_TOKEN` | 空 | 可选：访问洛谷私有代理的 Bearer token |
| `LUOGU_THIRD_PARTY_FALLBACK` | `true` | 洛谷主源失败时，是否尝试第三方公开统计源兜底 |
| `LUOGU_FALLBACK_URLS` | 内置公开卡片接口 | 可选：逗号分隔的洛谷降级 URL 模板，支持 `{uid}`、`{handle}`、`{name}` |
| `LUOGU_RECORD_SYNC` | `true` | 是否同步洛谷 `record/list` 逐条评测记录 |
| `LUOGU_RECORD_RECENT_PAGES_PER_SYNC` | `3` | 每次同步优先抓取洛谷最新记录页数 |
| `LUOGU_RECORD_BACKFILL_PAGES_PER_SYNC` | `8` | 洛谷历史记录每次额外回填页数 |
| `LUOGU_RECORD_SLEEP_MIN_SECONDS` | `0.4` | 洛谷记录页分页请求的最小间隔秒数 |
| `LUOGU_RECORD_SLEEP_MAX_SECONDS` | `1.4` | 洛谷记录页分页请求的最大间隔秒数 |
| `QOJ_COOKIE` | 空 | QOJ 管理员侧专用 Cookie；公开部署不建议收集用户登录态 |

## 洛谷海外访问

洛谷可能会拦截海外机房出口，表现为 `HTTP 403`、验证码或 `record/list` 返回登录页。项目提供三层处理：

1. 优先使用公开个人页和练习页数据。
2. 如果公开页失败，尝试第三方公开统计卡片接口兜底总题数。
3. 如果你需要更精确的洛谷逐条提交记录，可以部署一个只代理洛谷请求的国内出口。

国内出口代理脚本是 [deploy/luogu_proxy.py](deploy/luogu_proxy.py)，FRP 连接示例见 [deploy/luogu-frp.md](deploy/luogu-frp.md)。代理只允许访问 `https://www.luogu.com.cn` / `https://luogu.com.cn`，并要求 Bearer token。不要把代理无鉴权暴露到公网，也不要把 Cookie、token 或服务器 IP 提交到仓库。

慢速回填洛谷历史记录：

```bash
docker compose exec -T oj-submission-wall python app.py luogu-backfill \
  --pages-per-round 20 \
  --recent-pages 1 \
  --sleep-min 0.8 \
  --sleep-max 2.0
```

`--pages-per-round` 是每轮每个账号最多回填的历史页数，不是总页数上限。命令会持续按游标向后补，直到历史完成或某页失败暂停。

## 数据源说明

- Codeforces 使用官方 `user.status` API，并分页拉取历史提交；比赛统计使用 `contest.list` 的主站和 Gym 数据。
- AtCoder 使用 AtCoder Problems 公开 API；比赛统计使用 AtCoder 官方用户参赛历史 JSON。
- 洛谷优先读取公开个人页、练习页和 `record/list`，海外出口受限时可使用私有国内代理或第三方公开统计兜底。
- 牛客从公开竞赛个人页和参赛历史接口同步提交与比赛。
- VJudge 使用公开 `solveDetail2` 和 `status/data`。
- LOJ 使用公开 `submission/querySubmission` API。
- QOJ 受 Cloudflare 影响，未配置管理员侧专用 Cookie 时只给出明确提示。

如果平台接口改版、风控或临时不可用，系统会保留上次成功同步的数据。前端会先显示浏览器里的上次概览，再后台刷新最新数据，避免打开页面时闪成空列表。

## 生产建议

- 使用 HTTPS，并设置 `COOKIE_SECURE=true`。
- 把 `OJ_USER_AGENT` / `LUOGU_USER_AGENT` 改成你自己的站点地址或联系方式。
- 不要提交 `.env`、数据库、Cookie、token、服务器 IP 等敏感信息。
- 如果成员较多，适当调大 `SYNC_INTERVAL_SECONDS`，减少对 OJ 的请求压力。
- 定期备份 `data/ojwall.sqlite3`。

## License

MIT
