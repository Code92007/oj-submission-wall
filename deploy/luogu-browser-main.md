# 浏览器在主站、国内机只做请求出口

适用于国内出口由其他人维护、你没有国内机 SSH 权限的情况。登录会话和浏览器控制台放在主站，所有洛谷主站请求经原来的鉴权代理转发到国内。公共 CDN 静态资源由浏览器正常加载。沿用原有 FRP 与代理 token。

## 国内维护者的一次性操作

只需要替换新版 `luogu_proxy.py`，无需安装浏览器或改变 FRP：

```bash
cp /opt/luogu-proxy/luogu_proxy.py /opt/luogu-proxy/luogu_proxy.py.bak
# 把新版 deploy/luogu_proxy.py 上传并替换上面的脚本。
systemctl restart luogu-proxy
curl -fsS http://127.0.0.1:8787/health
```

健康响应应包含 `"browserRelay":true`。维护者应继续使用默认 `LUOGU_PROXY_BACKEND=urllib`，原有 token 和其他环境变量保持不变。旧 GET 协议继续兼容；新增浏览器中继协议支持 POST 请求体、Set-Cookie 和未自动跟随的重定向，保留浏览器自己的会话。

## 主站部署

使用 `Dockerfile.luogu-browser`、`docker-compose.luogu-browser.yml`、`docker-compose.luogu-main.yml`、`luogu_proxy.py`、`luogu_browser.py`、`luogu_browser_relay.py`、`luogu-browser-entrypoint.sh` 在独立目录构建浏览器服务。在该目录的私有 `.env` 中设置：

```dotenv
LUOGU_PROXY_TOKEN=<原有代理token>
LUOGU_BROWSER_RELAY_URL=http://host.docker.internal:18787/
LUOGU_BROWSER_RELAY_TOKEN=<原有代理token>
OJWALL_NETWORK=oj-submission-wall_default
```

```bash
docker compose -f docker-compose.luogu-browser.yml -f docker-compose.luogu-main.yml up -d --build
curl -fsS http://127.0.0.1:8787/health
```

命名卷持久保存浏览器会话。6080 只绑定回环地址，登录控制台通过主站 SSH 隧道访问：

```bash
ssh -N -L 6080:127.0.0.1:6080 <主站SSH地址>
```

打开 `http://127.0.0.1:6080/vnc.html`，在浏览器中完成一次登录。观察健康状态变为 `authenticated`，并确认记录页能返回实际记录后，才将主站应用的 `LUOGU_PROXY_URL` 改为 `http://luogu-browser-proxy:8787/`，等待原同步任务结束再重建主站应用容器。代理 token 继续保持原值。

此后主站的每分钟恢复检查会自动接续补抓。服务端撤销会话或要求验证码时，需要在这个控制台完成验证；无需复制 Cookie，也无需登录国内机器。

若验证失败，主站应用仍使用原来的 `http://host.docker.internal:18787/`，现有同步链路不会因准备新浏览器而切换。若已经切换，可改回旧 URL 并重建主站应用容器，浏览器卷保留供继续排查。
