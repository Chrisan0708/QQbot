import asyncio
import httpx

from nonebot.log import logger
import os
from .config import capoo_pic_path, capoo_filename

capoo_list_len = 456
async def download_url(url: str) -> bytes:
    async with httpx.AsyncClient() as client:
        for i in range(3):
            try:
                resp = await client.get(url, timeout=20)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                logger.warning(f"Error downloading {url}, retry {i}/3: {e}")
                await asyncio.sleep(1)
    raise Exception(f"{url} 下载失败！")


def resource_url(path: str) -> str:
    return f"https://oss.huparry.cn/capoo/{path}"

async def download_resources(path: str) -> bytes:
    return await download_url(resource_url(path))

async def check_resources():
    logger.info(f'Checking {capoo_pic_path} ...')
    if not capoo_pic_path.exists():
        logger.info(f"未找到capoo文件夹，准备创建capoo/picture文件夹...")
        capoo_pic_path.mkdir(parents=True, exist_ok=True)

    # 按文件名逐个核对，而不是只数文件个数：
    # 原来的写法只要目录里有 456 个文件就认为完整，
    # 中途被打断/下载失败时会出现"数量够了但缺某几张"，之后一直补不上。
    missing = []
    for i in range(1, capoo_list_len + 1):
        file_name = capoo_filename.format(index=str(i).zfill(3))
        file_path = capoo_pic_path / file_name
        if not file_path.exists() or file_path.stat().st_size == 0:
            missing.append((i, file_name, file_path))

    if not missing:
        logger.info(f"资源文件完整，共 {capoo_list_len} 张")
        return

    logger.info(f"缺少/损坏 {len(missing)} 张图片，开始补下...")
    downloaded = 0
    for i, file_name, file_path in missing:
        try:
            data = await download_resources(file_name)
            if data:
                file_path.write_bytes(data)
                downloaded += 1
        except Exception as e:
            logger.warning(str(e))
        bar_filled = int(i / capoo_list_len * 30)
        bar = "█" * bar_filled + "░" * (30 - bar_filled)
        print(f"\r下载图片:  [{bar}] {i}/{capoo_list_len} ({file_name})", end="", flush=True)
    print()
    logger.info(f"下载完成，共下载 {downloaded} 张图片")
