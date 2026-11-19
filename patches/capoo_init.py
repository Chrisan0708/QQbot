from .config import Config, capoo_path
from httpx import AsyncClient
from .download import *
import asyncio
from nonebot.adapters.onebot.v11 import MessageSegment
from nonebot.plugin import on_fullmatch
from nonebot.log import logger
from nonebot import get_driver
import random
import os
from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
	name = "猫猫虫咖波图片发送",
	description = "发送capoo指令后bot会随机发出一张capoo的可爱表情包",
	usage = "使用命令：capoo",
	type="application",
	homepage="https://github.com/HuParry/nonebot-plugin-capoo",
	config=Config,
	supported_adapters = {"nonebot.adapters.onebot.v11"},
)

driver = get_driver()
@driver.on_startup
async def _():
	logger.info("正在检查资源文件...")
	await check_resources()

picture = on_fullmatch('capoo', priority=1, block=True)

_IMAGE_SUFFIXES = ('.gif', '.png', '.jpg', '.jpeg', '.webp')

@picture.handle()
async def pic():
	# 一定要把图片读成 bytes 再发（适配器会转成 base64://）：
	# 直接传 Path 会被转成 file:///app/data/... 交给协议端去读，
	# 而 NapCat 跑在别的容器/机器上，根本没有这个路径 -> ENOENT。
	try:
		files = [
			name for name in os.listdir(capoo_pic_path)
			if name.lower().endswith(_IMAGE_SUFFIXES)
		]
	except OSError as e:
		logger.warning(f"读取 capoo 目录失败: {e}")
		await picture.send('capoo图库还没准备好，稍后再试试吧~')
		return

	if not files:
		await picture.send('capoo图库还没准备好，稍后再试试吧~')
		return

	random.shuffle(files)
	for name in files[:10]:
		img = capoo_pic_path / name
		try:
			data = img.read_bytes()
		except OSError as e:
			logger.warning(f"跳过 {name}: {e}")
			continue
		if not data:
			continue
		try:
			await picture.send(MessageSegment.image(data))
			return
		except Exception as e:
			logger.warning(f"发送 {name} 失败: {e}")
			continue

	await picture.send('capoo出不来了，稍后再试试吧~')
