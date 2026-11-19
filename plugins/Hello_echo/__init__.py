from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, Event

# 当用户发送 "/hello" 时触发
hello = on_command("hello")

# 处理这个命令
@hello.handle()
async def handle_hello(bot: Bot, event: Event):
    # 回复用户
    await hello.finish("我喜欢你！")
