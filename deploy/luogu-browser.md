# 洛谷持久化浏览器代理

部署在现有国内 FRP 客户端机器上，替代旧 urllib 代理。主站继续通过 FRP 访问 8787；浏览器自己保存并更新登录 Cookie，忽略主站转发的固定 Cookie。浏览器版本固定，升级需重新构建镜像。

## 部署

把 `deploy/` 下的 `Dockerfile.luogu-browser`、`luogu_proxy.py`、`luogu_browser.py`、`luogu_browser_relay.py`、`luogu-browser-entrypoint.sh` 和 `docker-compose.luogu-browser.yml` 放入国内机器 `/opt/luogu-browser`。在此目录的 `.env` 中设置与主站一致的 `LUOGU_PROXY_TOKEN`，文件权限设为 600。不要把凭据写入仓库。

没有国内机器 SSH 权限时，可使用 [主站浏览器 + 国内中继](luogu-browser-main.md)。国内维护者只需升级一次小代理，后续登录在主站控制台完成。

```bash
cd /opt/luogu-browser
docker compose -f docker-compose.luogu-browser.yml build
# 镜像构建成功后再停止旧代理；FRP 客户端无需改动。
systemctl stop luogu-proxy
docker compose -f docker-compose.luogu-browser.yml up -d
curl -fsS http://127.0.0.1:8787/health
```

代理启动时浏览器自动打开并检查会话。首次启动显示 `login_required` 属正常现象。也可以在国内机器发送带 Bearer token 的 `{"action":"session"}` POST 请求检查会话。

## 首次登录

在自己的电脑建立 SSH 隧道：

```bash
ssh -N -L 6080:127.0.0.1:6080 <国内代理SSH地址>
```

打开 `http://127.0.0.1:6080/vnc.html`，连接后在浏览器中登录洛谷，完成必要验证。会话保存在 Docker 命名卷中，不随容器重建丢失。不要执行 `docker compose down -v`。浏览器控制台没有额外密码，必须保持 6080 只绑定服务器回环地址，通过 SSH 访问。

浏览器在空闲时定期检测会话。主站每分钟检查代理健康状态，会话恢复后自动排队补抓，每批最多三个账号，无需等待整站的小时级自动同步或再次复制 Cookie。主站 `.env` 中的旧 `LUOGU_COOKIE` / `LUOGU_CSRF_TOKEN` 可在验证迁移成功后清空。代理 token 继续保留。

## 失效与补抓

- 会话失效时停止记录页请求，60 秒后检测浏览器是否重新登录；403 风控时退避 15 分钟。
- 主站同一轮只进行一次会话失败探测，其他账号复用退避状态。
- 新数据超过单轮页数上限时保存断档扫描页码与原始时间边界，下轮继续；只有连续扫描到旧边界后才推进增量时间戳。
- 非零增量页数至少按两页执行，确保同时检查最新页和推进断档游标；CLI 的 `--recent-pages 0` 纯历史回填仍受支持。
- 记录同步失败或断档未补完，不推进最后成功同步时间；已抓到的提交立即保存。
- 程序不会自动填写账号密码或处理验证码。Cookie 更新能延续有效会话，但服务端主动撤销登录时仍需要在该浏览器验证一次。

## 回退

```bash
cd /opt/luogu-browser
docker compose -f docker-compose.luogu-browser.yml stop
systemctl start luogu-proxy
```

保留浏览器卷即可随时恢复新代理，主站数据不需要回滚。
