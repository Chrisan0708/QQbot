# 以后怎么加插件

这个仓库是「代码进 Git、依赖钉死、镜像构建时装依赖」的结构，所以加插件的改动是固定的几处。

## 0. 先看要改哪些地方

| 位置 | 是否必须 | 作用 |
|---|---|---|
| `pyproject.toml` → `[tool.nonebot.plugins]` | **必须** | `bot.py` 用 `load_from_toml()` 加载，没登记就**装了也不加载** |
| `requirements.txt` | **必须** | 镜像构建只装这里列的包（Docker 的关键，漏了会 `ModuleNotFoundError`） |
| `.env`（服务器上） | 看插件 | 插件配置项、API key，只放服务器，不进仓库 |
| `.env.example` | 建议 | 补一行占位说明，方便下次部署 |
| `Dockerfile` | 看插件 | 需要额外系统依赖（ffmpeg / libGL / 字体 / 浏览器）时才改 |
| `patches/` + Dockerfile 覆盖 | 看插件 | 插件有 bug、或用不了容器环境（如硬编码 Windows 路径）时才加 |

## 1. 本地装下来试一下

```powershell
# Windows 本地开发环境
.\.venv\Scripts\pip.exe install nonebot-plugin-xxx

# 记下版本，待会儿要钉进 requirements.txt
.\.venv\Scripts\pip.exe show nonebot-plugin-xxx
```

插件的**模块名**（import 用的名字）通常就是包名把 `-` 换成 `_`；不确定就看：

```powershell
Get-ChildItem .venv\Lib\site-packages -Directory | Where-Object Name -match "xxx"
```

## 2. 改 `pyproject.toml`（两处都要）

```toml
[project]
dependencies = [
    ...
    "nonebot-plugin-xxx>=1.2.3",      # ← 加这行
]

[tool.nonebot.plugins]
nonebot-plugin-xxx = ["nonebot_plugin_xxx"]   # ← 再加这行，key 是发行包名，value 是模块名
```

## 3. 改 `requirements.txt`（钉死版本）

```
nonebot-plugin-xxx==1.2.3
```

> 为什么不直接让镜像 `pip install .`？因为钉版本能保证 `patches/` 一直对得上，
> 也避免某天上游发新版把现在的行为改坏。

## 4. 本地跑一遍容器

```powershell
docker compose up -d --build
docker compose logs -f qqbot
```

日志里出现下面这行才算真的加载成功（只是装上了不算）：

```
[SUCCESS] nonebot | Succeeded to load plugin "nonebot_plugin_xxx"
```

然后在 QQ 里真发一次命令验证。

## 5. 提交 → 服务器部署

```powershell
git add -A
git commit -m "feat: add nonebot-plugin-xxx"
git push
```

服务器：

```bash
cd ~/qqbot
git pull
sudo docker compose up -d --build
sudo docker compose logs -f qqbot
```

## 各种特殊情况

| 情况 | 怎么做 |
|---|---|
| 插件要系统库（ffmpeg、libgl1、libgomp1 等） | `Dockerfile` 的 `apt-get install` 列表里加，再重建 |
| 插件要自己下浏览器/字体 | 优先复用现成的 `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`；字体已在镜像里 |
| 插件要读写文件 | 用 `nonebot_plugin_localstore`（会自动落到 `/app/data`，随 volume 持久化）；要固定路径就自己加 volume |
| 插件硬编码了 Windows 路径 / 在容器里报 ENOENT | 抄现有做法：改好的文件放 `patches/`，Dockerfile 里 `cp` 覆盖 + `cmp` 校验 |
| 插件只支持群聊（`permission=GROUP`） | 想私聊也能用就去掉 permission，或改成按事件类型选发送方式（参考 `patches/hotsearch_init.py`） |
| 插件发图片报协议端找不到文件 | 把 `Path` 改成读 `bytes` 再 `MessageSegment.image()`（参考 `patches/capoo_init.py`） |
| 依赖和现有版本冲突 | 在 `requirements.txt` 里钉一个兼容版本，重建验证；实在不行降插件版本 |

## 自己写的小插件放哪

放 `plugins/` 目录，**不需要**改 `requirements.txt`：

```
plugins/
└── my_plugin/
    └── __init__.py
```

`pyproject.toml` 里已经有 `[tool.nonebot].plugin_dirs = ["plugins"]`，会被自动加载，
插件名就是目录名（如 `my_plugin`）。这类代码跟着 Git 走，服务器 `git pull` 就有。

## 加完插件的自查清单

- [ ] `logs` 里有 `Succeeded to load plugin "..."`
- [ ] QQ 里发命令有响应（群聊 / 私聊都试）
- [ ] 图片类命令能出图（验证 Chromium + 中文字体没问题）
- [ ] `docker compose restart` 后新插件的数据还在（说明写进 volume 了）
- [ ] `.env` 里的新配置没被提交进 Git
