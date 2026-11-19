# syntax=docker/dockerfile:1
#
# 国内网络默认走阿里云 / npmmirror 镜像，构建快很多。
# 如果你的网络本来就能直连海外，用 --build-arg 覆盖回官方源即可：
#   docker compose build \
#     --build-arg DEBIAN_MIRROR=deb.debian.org \
#     --build-arg PIP_INDEX_URL=https://pypi.org/simple \
#     --build-arg PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.playwright.dev
ARG DEBIAN_MIRROR=mirrors.aliyun.com
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright

FROM python:3.12-slim

ARG DEBIAN_MIRROR
ARG PIP_INDEX_URL
ARG PLAYWRIGHT_DOWNLOAD_HOST

# PLAYWRIGHT_BROWSERS_PATH 必须和运行时 render.provider_config.storage_path 一致
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# 1) apt 换成镜像源（debian 12+ 是 deb822 的 sources.list.d/debian.sources）
RUN set -eux; \
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
        if [ -f "$f" ]; then \
            sed -i "s|deb.debian.org|${DEBIAN_MIRROR}|g; s|security.debian.org|${DEBIAN_MIRROR}|g" "$f"; \
        fi; \
    done; \
    grep -r "URIs\|^deb " /etc/apt/sources.list.d/ /etc/apt/sources.list 2>/dev/null || true

# 2) 时区 + 中文字体 + emoji 字体
#    cs2radar 的卡片里全是中文和 👑🔥⚡ 之类的符号，缺字体会渲染成方块
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
        ca-certificates \
        curl \
        unzip \
        libatomic1 \
        fonts-noto-cjk \
        fonts-noto-color-emoji \
        fonts-dejavu-core \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 3) Python 依赖（钉死版本，见 requirements.txt）
COPY requirements.txt ./
RUN pip install -i "${PIP_INDEX_URL}" -r requirements.txt

# 4) Chromium：用 npmmirror 镜像下载，--with-deps 补齐 Linux 运行库
RUN PLAYWRIGHT_DOWNLOAD_HOST="${PLAYWRIGHT_DOWNLOAD_HOST}" \
    playwright install --with-deps chromium

# 5) 项目本体（.env 不进镜像，运行时由 compose 的 env_file 注入）
COPY bot.py pyproject.toml ./
COPY plugins ./plugins

# 6) 覆盖 site-packages 里的补丁：
#    - cs2radar：出图前把远程图片内联成 data URI（修 /cs查询 30s 超时）、模板 best_season 兜底
#    - hotsearch：微博/知乎数据源修复 + 私聊支持 + 异步请求
#    - capoo：图片按 bytes 发 base64（原来发 file:///app/data/... 路径，
#      NapCat 在另一个容器里读不到 -> ENOENT）；资源校验改成按文件名补下
# 注意：不能用 python -c "import nonebot_plugin_cs2radar" 定位路径，
# 这两个插件的 __init__ 会调用 require()，NoneBot 未初始化时会抛错。改用 find_spec。
COPY patches ./patches
RUN set -eux; \
    CS2="$(python -c 'import importlib.util as u, os; print(os.path.dirname(u.find_spec("nonebot_plugin_cs2radar").origin))')"; \
    HOT="$(python -c 'import importlib.util as u, os; print(os.path.dirname(u.find_spec("nonebot_plugin_hotsearch").origin))')"; \
    CAPOO="$(python -c 'import importlib.util as u, os; print(os.path.dirname(u.find_spec("nonebot_plugin_capoo").origin))')"; \
    test -f "$CS2/renderer.py"; \
    test -d "$CS2/templates"; \
    test -f "$CAPOO/download.py"; \
    cp patches/cs2radar_renderer.py "$CS2/renderer.py"; \
    cp patches/cs2radar_stats.html "$CS2/templates/stats.html"; \
    cp patches/cs2radar_player_detail.html "$CS2/templates/player_detail.html"; \
    cp patches/hotsearch_init.py "$HOT/__init__.py"; \
    cp patches/capoo_init.py "$CAPOO/__init__.py"; \
    cp patches/capoo_download.py "$CAPOO/download.py"; \
    cmp patches/cs2radar_renderer.py "$CS2/renderer.py"; \
    cmp patches/cs2radar_stats.html "$CS2/templates/stats.html"; \
    cmp patches/cs2radar_player_detail.html "$CS2/templates/player_detail.html"; \
    cmp patches/hotsearch_init.py "$HOT/__init__.py"; \
    cmp patches/capoo_init.py "$CAPOO/__init__.py"; \
    cmp patches/capoo_download.py "$CAPOO/download.py"; \
    rm -rf patches; \
    echo "patches applied ok"

# 7) localstore 数据目录（绑定库 / 缓存），由 compose 挂载
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8080

CMD ["python", "bot.py"]
