# Mac 本机持久化洛谷浏览器

浏览器与 SSH 隧道使用用户 LaunchAgent：`cn.wannafly.luogu-browser`、`cn.wannafly.luogu-tunnel`。登录 macOS 后自动启动，异常退出自动重启，隧道断线自动重连。

浏览器使用现有 Google Chrome，但配置目录独立，不读取日常 Chrome 的登录态。首次在弹出的洛谷窗口完成登录；后续由浏览器保存和使用会话，无需人工复制 Cookie。洛谷主动撤销登录或要求验证时，仍需要在该窗口重新登录，不能保证会话永久有效。

本机私有配置、浏览器目录与日志位于 `data/luogu-browser-local/`，被 Git 忽略；请勿提交或分享。备份时应将配置与浏览器目录视为凭据。

本机代理监听 `127.0.0.1:18788`，SSH 将主站 Docker 网关 `172.17.0.1:19787` 转发至该代理；主站配置 URL 为 `http://host.docker.internal:19787/`，鉴权 token 与本机私有配置一致。端口不监听公网。

Mac 必须开机、登录并联网，睡眠或离线期间无法抓取。连接恢复后主站每分钟检测会话并自动安排补抓，原有数据与成功时间保留。无需为了恢复连接而手动点击刷新。

查看日志：`data/luogu-browser-local/browser.log`、`data/luogu-browser-local/tunnel.log`。查看状态：`curl http://127.0.0.1:18788/health`。

停止服务：`launchctl bootout gui/$(id -u)/cn.wannafly.luogu-browser`、`launchctl bootout gui/$(id -u)/cn.wannafly.luogu-tunnel`。重新启动：`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/cn.wannafly.luogu-browser.plist`，隧道同理。修改配置后可用 `launchctl kill SIGTERM gui/$(id -u)/cn.wannafly.luogu-browser` 重启并保存会话。

代码与虚拟环境保留在当前仓库绝对路径，移动仓库后需更新两个 plist 的路径。独立浏览器窗口由后台服务管理，关闭窗口会重启浏览器；正常使用时可最小化。
