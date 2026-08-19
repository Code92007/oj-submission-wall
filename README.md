# OJ Submission Wall

给算法集训队用的做题监控墙：队员绑定 OJ 账号后，系统定时拉取提交记录，按天生成类似 GitHub contributions 的绿墙，并展示最新提交流。

## 功能

- 游客模式：不注册也能临时进入，绑定 OJ 账号后查看自己的提交墙。游客会话默认保留 7 天。
- 账号注册：用户名 + 密码即可注册，注册后自动登录。
- OJ 绑定：支持 Codeforces、AtCoder、牛客、洛谷、VJudge、LOJ、QOJ。
- 训练监控：成员总览、今日解题、历史解题活跃天、连续训练天数、最新提交动态、参赛统计。
- 后台同步：默认每 15 分钟同步一次注册成员，也可以在页面手动刷新。
- 稳定缓存：历史提交页会本地缓存，平台临时不可用时仍可显示截至上次成功同步的全平台镜像。
- 零前端构建：纯 Python 标准库 + SQLite + 静态 HTML/CSS/JS，方便直接 Docker 部署。

## 本地运行

```bash
cd ~/Documents/oj-submission-wall
python3 app.py
```

打开 `http://localhost:8000`。

注册不需要邮箱验证；如果要限制访问，建议放到反向代理或内网入口后面。

## Docker 部署

```bash
cd ~/Documents/oj-submission-wall
cp .env.example .env
# 修改 .env 里的 PUBLIC_BASE_URL、COOKIE_SECURE
docker compose up -d --build
```

数据会保存在 `./data/ojwall.sqlite3`。升级时保留 `data/` 目录即可。

## GitHub 到开发机部署

本机推到 GitHub：

```bash
cd ~/Documents/oj-submission-wall
git init
git add .
git commit -m "init oj submission wall"
git branch -M main
git remote add origin git@github.com:你的用户名/oj-submission-wall.git
git push -u origin main
```

开发机服务器拉取并启动：

```bash
git clone git@github.com:你的用户名/oj-submission-wall.git
cd oj-submission-wall
cp .env.example .env
vim .env
docker compose up -d --build
```

后续更新：

```bash
cd oj-submission-wall
git pull
docker compose up -d --build
```

生产部署建议在 `.env` 里配置 `PUBLIC_BASE_URL`。

## wannafly.cn 域名部署

推荐把训练墙挂在 `https://oj-train-wall.wannafly.cn`，主域名 `wannafly.cn` 留给后续总入口。

DNSPod 添加解析：

| 主机记录 | 记录类型 | 记录值 |
| --- | --- | --- |
| `oj-train-wall` | `A` | `43.155.179.39` |

服务器 `.env` 建议：

```bash
PUBLIC_BASE_URL=https://oj-train-wall.wannafly.cn
BIND_ADDRESS=127.0.0.1
PORT=8017
COOKIE_SECURE=true
OJ_USER_AGENT=OJSubmissionWall/1.0 (+https://oj-train-wall.wannafly.cn)
LUOGU_USER_AGENT=OJSubmissionWall/1.0 (+https://oj-train-wall.wannafly.cn)
```

应用容器只监听本机 `127.0.0.1:8017`，公网入口交给反向代理的 `80/443`。已有 Nginx 时使用 `deploy/nginx.oj-train-wall.conf`；没有反向代理时也可以用 `deploy/Caddyfile.oj-train-wall` 让 Caddy 自动签证书。

## 账号绑定格式

- Codeforces：填写 handle，例如 `tourist`。
- AtCoder：填写用户名，例如 `tourist`。
- 牛客：填写竞赛个人页数字 ID，例如 `https://ac.nowcoder.com/acm/contest/profile/123456` 里的 `123456`。
- 洛谷：填写用户名、数字 UID 或用户主页链接。
- VJudge：填写 VJudge 用户名。
- LOJ：填写 LOJ 用户名。
- QOJ：填写 QOJ 用户名；服务端需要先配置 `QOJ_COOKIE`。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PUBLIC_BASE_URL` | 当前 Host | 应用公网地址 |
| `BIND_ADDRESS` | `0.0.0.0` | 容器外端口绑定地址；反向代理部署建议设为 `127.0.0.1` |
| `PORT` | `8000` | 容器外暴露端口由 compose 的 `${PORT}` 控制 |
| `DATA_DIR` | `/data` | SQLite 数据目录 |
| `APP_ENV` | `production` | 运行环境标记 |
| `COOKIE_SECURE` | `false` | HTTPS 部署建议设为 `true` |
| `SYNC_INTERVAL_SECONDS` | `900` | 后台同步间隔；设为 `0` 关闭后台同步 |
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
| `OJ_USER_AGENT` | `OJSubmissionWall/1.0` | 外部 OJ 请求的 User-Agent |
| `LUOGU_USER_AGENT` | `OJSubmissionWall/1.0` | 洛谷请求的 User-Agent |
| `LUOGU_COOKIE` | 空 | 可选：管理员自己的洛谷 Cookie；公开部署不建议收集用户 Cookie |
| `LUOGU_PROXY_URL` | 空 | 可选：洛谷海外 403 时，把洛谷请求转发到国内出口的私有代理 |
| `LUOGU_PROXY_TOKEN` | 空 | 可选：访问洛谷私有代理的 Bearer token |
| `QOJ_COOKIE` | 空 | QOJ 有 Cloudflare 校验；公开部署不建议收集用户登录态，留空时会提示无法精确同步 |

### 洛谷海外 403 代理

如果服务器在海外机房，洛谷可能直接返回 `HTTP 403`。这不是绑定的账号错了，而是出口 IP 被洛谷风控拦截。稳定做法是把 `deploy/luogu_proxy.py` 部署在一个能正常访问洛谷的国内出口上，并且只暴露给主站使用：

```bash
cd /root/oj-submission-wall
export LUOGU_PROXY_TOKEN='换成一段随机长密码'
HOST=127.0.0.1 PORT=8787 python3 deploy/luogu_proxy.py
```

主站 `.env` 里配置：

```bash
LUOGU_PROXY_URL=https://你的国内代理域名/
LUOGU_PROXY_TOKEN=同一段随机长密码
```

代理脚本只允许转发 `https://www.luogu.com.cn` / `https://luogu.com.cn`，并要求 Bearer token；不要把它无鉴权公开到公网。

## 数据源说明

- Codeforces 使用官方 `user.status` API，并分页拉取完整 10 年提交；比赛统计使用 `contest.list` 的主站 + Gym 名称，且只统计非 `PRACTICE` 的参赛/虚拟/打星记录。
- AtCoder 使用 AtCoder Problems 的公开 API，并按 `from_second` 分页拉取完整历史；比赛统计使用 AtCoder 官方用户参赛历史 JSON。
- 洛谷匿名访问无法读取逐条提交；本项目优先读取公开个人页 activity（日历）和练习页 `passed` 题目集合，首尔等海外出口 403 时可配置私有国内代理。
- 牛客从竞赛个人页公开练习记录分页解析历史提交，并从公开参赛历史接口同步比赛明细。
- VJudge 使用公开 `solveDetail2` 同步完整历史 AC 题目，并用 `status/data` 补最近提交；带 `contestId` 的记录会计入 VJudge 比赛。
- LOJ 使用公开 `submission/querySubmission` API 分页同步公开提交。
- QOJ 当前有 Cloudflare 校验；公开部署不建议向用户索要登录态。未配置管理员侧专用 Cookie 时会明确提示无法精确同步。

如果平台接口改版、风控或临时不可用，系统会保留上次成功同步的数据；`/api/overview` 还会写入脱敏概览镜像，数据库或接口异常时可以继续显示“数据截至 xx”的本地镜像。适配器都集中在 `app.py` 的 `OJAdapter` 子类里，后续替换接口时只需要改对应类。

## 生产建议

- 放到 Nginx/Caddy 后面，开启 HTTPS，并把 `COOKIE_SECURE=true`。
- 把 `OJ_USER_AGENT` 改成你自己的域名和联系方式。
- 如果队员很多，建议把 `SYNC_INTERVAL_SECONDS` 调大，减少对 OJ 的请求压力。
