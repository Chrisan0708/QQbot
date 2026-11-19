# Docker 运行说明（已验证可跑）

本目录已经从「Windows + .venv」迁到「Docker」，`docker compose up -d --build` 构建并启动即可。

镜像实测结果：**2.28 GB**，构建约 6~10 分钟（走国内镜像），启动后 `healthy`，
群/私聊命令、cs2radar 出图、hotsearch 合并转发均已实际验证通过。

## 文件清单

| 文件 | 作用 |
|---|---|
| `Dockerfile` | Python 3.12 + 依赖 + Chromium + 中文字体，并把 `patches/` 覆盖进 site-packages |
| `docker-compose.yml` | 复用 `.env`、覆盖 Windows 专用路径、挂载 `./data`、暴露 8080、健康检查 |
| `requirements.txt` | 钉死版本的依赖（**别随手升级**，`patches/` 是对着这些版本打的） |
| `.dockerignore` | 排除 `.venv/`、`data/`、备份和验证图 |
| `patches/` | 4 个改过的插件文件，构建时覆盖回 `site-packages` |

## 日常命令

```powershell
docker compose up -d --build     # 构建 + 启动（改代码/补丁后也用它）
docker compose logs -f qqbot     # 跟日志
docker compose restart qqbot     # 重启
docker compose down              # 停止并删除容器（./data 保留）
docker compose exec qqbot bash   # 进容器排查
```

看到下面这些就是起来了：

```
[SUCCESS] nonebot | Succeeded to load plugin "nonebot_plugin_cs2radar"
[SUCCESS] nonebot | Succeeded to load plugin "nonebot_plugin_hotsearch"
[SUCCESS] nonebot | Running NoneBot...
[INFO] uvicorn | Application startup complete.
[INFO] uvicorn | Uvicorn running on http://0.0.0.0:8080
```

`docker compose ps` 里应该是 `Up (healthy)`。

## NapCat 侧

bot 在容器里监听 8080，已映射到宿主机。NapCat 反向 WebSocket 填：

```
ws://127.0.0.1:8080/onebot/v11/ws
```

token 用 `.env` 里的 `ONEBOT_ACCESS_TOKEN`（NapCat 里必须一致）。
NapCat 若也在 Docker 里，放同一 network，地址换成 `ws://qqbot:8080/onebot/v11/ws`。

## 网络加速（默认已开）

`Dockerfile` 顶部三个 `ARG` 默认走国内镜像，构建快 5~20 倍：

| ARG | 默认值 |
|---|---|
| `DEBIAN_MIRROR` | `mirrors.aliyun.com` |
| `PIP_INDEX_URL` | `https://mirrors.aliyun.com/pypi/simple` |
| `PLAYWRIGHT_DOWNLOAD_HOST` | `https://cdn.npmmirror.com/binaries/playwright` |

海外网络想用官方源：

```powershell
docker compose build `
  --build-arg DEBIAN_MIRROR=deb.debian.org `
  --build-arg PIP_INDEX_URL=https://pypi.org/simple `
  --build-arg PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.playwright.dev
```

若你的网络必须走代理：

```powershell
docker compose build --build-arg HTTP_PROXY=http://host.docker.internal:7890 --build-arg HTTPS_PROXY=http://host.docker.internal:7890
```

## 数据

`./data` 挂到容器 `/app/data`（对应 `LOCALSTORE_DATA_DIR`），已迁移：

```
data/nonebot_plugin_cs2radar/user_bindings.db    # QQ ↔ 玩家绑定
data/nonebot-plugin-auto-sendlike/sub_user       # 超赞我 订阅列表
data/nonebot_plugin_capoo/                       # capoo 表情包（37MB，省得每次重启重下）
```

注意：容器和 Windows 那套用的是**两份**数据。以后以容器为主就别再跑 Windows 版，否则绑定会各记各的。

## 推到 GitHub 后在云服务器运行

可以。仓库里只放**代码和配置模板**，`.env` / `data/` 都不进仓库（`.gitignore` 已配好）。

### 1. 本地初始化仓库并推送

```powershell
git init
git add -A
git status            # 确认没有 .env、.venv/、data/ 被加进来
git commit -m "init: nonebot bot with docker"
git branch -M main
git remote add origin https://github.com/<你的账号>/<仓库名>.git
git push -u origin main
```

### 2. 云服务器上装 Docker（Debian/Ubuntu）

```bash
curl -fsSL https://get.docker.com | sh -s -- --mirror Aliyun
sudo usermod -aG docker $USER   # 重新登录后生效
docker compose version
```

### 3. 拉代码、生成 .env

```bash
git clone https://github.com/<你的账号>/<仓库名>.git qqbot
cd qqbot
cp .env.example .env
nano .env      # 至少改这三项：
               #   ONEBOT_ACCESS_TOKEN（换成随机长串）
               #   cs2radar_llm_api_key
               #   BOT_BIND（见下面第 5 点）
```

### 4. 启动

```bash
mkdir -p data          # 先建好，否则 Docker 会用 root 自动创建，之后 scp 放文件会没权限
docker compose up -d --build
docker compose logs -f
```

### 5. NapCat 怎么连（决定 `BOT_BIND`）

| NapCat 位置 | `BOT_BIND` | 说明 |
|---|---|---|
| 和 bot 同一台云服务器（同 Docker 或宿主机装） | `127.0.0.1` | 推荐，端口不暴露公网；同 compose 里还可改用服务名 `ws://qqbot:8080/...` |
| 家里的电脑 → 云服务器 | `0.0.0.0` | 必须安全组放行 8080，且**务必换强 token**，最好再加来源 IP 白名单 |

### 6. 数据不随仓库走

`data/` 被 `.gitignore` 排除，服务器首次启动会是空库（绑定要重新 `/bind`，capoo 还会重下 205 张图、启动变慢约 2 分钟）。

想保留现有绑定，单独把库传上去（本地在 `%LOCALAPPDATA%\nonebot2\`）：

```powershell
scp "data\nonebot_plugin_cs2radar\user_bindings.db" user@服务器:/home/user/qqbot/data/nonebot_plugin_cs2radar/
```

（先 `ssh` 到服务器 `mkdir -p ~/qqbot/data/nonebot_plugin_cs2radar`）

### 7. 云端额外注意

- **架构**：选 **x86_64** 最稳；ARM（部分轻量服务器）上 Chromium 是 arm64 包，能跑但要自己确认。
- **服务器配置**：构建阶段要下 ~200MB 依赖 + 装 Chromium，**1核1G 容易 OOM**，建议 2核2G 起；内存紧张就先加 swap，或本地构建后推到镜像仓库（`docker compose push` / 阿里云 ACR），服务器只 `pull`。
- **GitHub 慢**：服务器 `git clone` 卡的话用加速前缀，或本地打包 `scp` 上去。
- **安全组**：只开 22，8080 仅在 NapCat 异地时才开；token 用随机长串（`openssl rand -hex 16`）。
- **QQ 风控**：如果 NapCat 也搬到云服务器，腾讯对云 IP 登录 QQ 风控较严，可能频繁掉线，这是常见坑。
- **更新流程**：改完代码 `git push` → 服务器 `git pull && docker compose up -d --build`。

## 已知坑（都已处理，供以后排查）

1. **首次启动慢**：`capoo` 插件启动时会下载 205 张表情包（约 37MB），期间 8080 不监听、健康检查不过。已把本地资源放进 `data/`，现在秒起。
2. **`--no-sandbox`**：容器里 root 跑 Chromium 必须加，已在 compose 里配 `RENDER__PROVIDER_CONFIG__LAUNCH_ARGS`。
3. **`STORAGE_PATH`**：`.env` 里是 `C:\Users\zhang\...`，容器里无法用，compose 的 `environment` 已覆盖成 `/ms-playwright`。
4. **中文字体**：`python:3.12-slim` 默认没有 CJK 字体，Dockerfile 装了 `fonts-noto-cjk` + `fonts-noto-color-emoji`，否则卡片中文/emoji 全是方块。
5. **`libatomic1`**：Playwright 自带的 node 依赖它，缺了会 `libatomic.so.1: cannot open shared object file`。
6. **补丁覆盖**：`copy` 多文件到目录会保留原文件名，模板必须逐个写目标名（已在 Dockerfile 里写死并用 `cmp` 校验）。

## 排错

| 现象 | 处理 |
|---|---|
| 出图报 `Capability render_html is not available` | `RENDER__PROVIDER` 丢了，恢复成 `playwright` |
| 出图报 `Executable doesn't exist at /ms-playwright/...` | Chromium 没装进镜像，`--build` 重建 |
| 卡片中文方块 | 镜像缺 CJK 字体 |
| 绑定数据没了 | 检查 `LOCALSTORE_DATA_DIR=/app/data` 与 `./data:/app/data` 挂载 |
| `capoo` 报 `ENOENT ... /app/data/nonebot_plugin_capoo/...gif` | 已修：图片改为 base64 发送（协议端不再读本地文件）。还报就说明镜像没重建，`docker compose up -d --build` |
| 端口被占用 | Windows 版 bot 还开着，先关掉那套 |
| 容器反复重启 | `docker compose logs qqbot` 看 `nonebot.init()` 阶段报错（多半是 `.env` 配置项不合法） |
