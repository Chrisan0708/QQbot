import json
import re
from urllib.parse import quote

import httpx
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="热搜查询",
    description="获取各个网站的热搜排行",
    usage=(
        "可选命令：\n"
        "/微博热搜  /百度热搜\n"
        "/知乎热搜  /贴吧热搜 /b站热搜\n"
        "（群聊、私聊都可以用）"
    ),
)

_TIMEOUT = 20.0
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
# 知乎的 Web 接口现在要登录态，App 接口只要 App UA
_ZHIHU_APP_UA = "ZhihuHybrid osee2unifiedRelease/8.0.0 (iPhone; iOS 15.0; Scale/3.00)"

# 热搜条数
cnt = 10


def render_forward_msg(msg_list: list, uid: str, name: str = "小白猫~"):
    forward_msg = []
    for msg in msg_list:
        forward_msg.append(
            {
                "type": "node",
                "data": {"name": str(name), "uin": str(uid), "content": msg},
            }
        )
    return forward_msg


async def _fetch(url: str, *, headers: dict | None = None) -> httpx.Response:
    merged = {"User-Agent": _UA}
    if headers:
        merged.update(headers)
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True, headers=merged
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp


async def _send_forward(bot: Bot, event: MessageEvent, msg_list: list[str]) -> None:
    """优先发合并转发；失败则退回纯文本。"""
    forward_msg = render_forward_msg(msg_list, bot.self_id)
    try:
        if isinstance(event, GroupMessageEvent):
            await bot.send_group_forward_msg(
                group_id=event.group_id, messages=forward_msg
            )
        else:
            await bot.send_private_forward_msg(
                user_id=event.user_id, messages=forward_msg
            )
    except Exception:
        await bot.send(event=event, message="\n\n".join(msg_list))


async def _reply_error(bot: Bot, event: MessageEvent, label: str, exc: Exception) -> None:
    reason = str(exc).strip() or type(exc).__name__
    await bot.send(event=event, message=f"{label}获取失败：{reason}")


# 触发器
weibo_hotsearch = on_command("微博热搜", priority=5, block=True)
baidu_hotsearch = on_command("百度热搜", priority=5, block=True)
zhihu_hotsearch = on_command("知乎热搜", priority=5, block=True)
tieba_hotsearch = on_command("贴吧热搜", priority=5, block=True)
bzhan_hotsearch = on_command("b站热搜", aliases={"B站热搜"}, priority=5, block=True)


# 微博热搜：必须带 Referer，否则 weibo.com 直接返回 403
@weibo_hotsearch.handle()
async def weiboresou(bot: Bot, event: MessageEvent):
    await bot.send(event=event, message="获取中……")
    try:
        resp = await _fetch(
            "https://weibo.com/ajax/side/hotSearch",
            headers={"Referer": "https://weibo.com/"},
        )
        items = resp.json()["data"]["realtime"][:cnt]
        msg_list = ["微博热搜榜"]
        for i, obj in enumerate(items):
            word = obj.get("note") or obj.get("word") or ""
            num = obj.get("num")
            hot = f"\nhot:{num}" if num else ""
            link = "https://s.weibo.com/weibo?q=" + quote(word)
            msg_list.append(f"{i + 1}、{word}{hot}\n链接:{link}")
        await _send_forward(bot, event, msg_list)
    except Exception as e:
        await _reply_error(bot, event, "微博热搜", e)


# 百度热搜
@baidu_hotsearch.handle()
async def baiduresou(bot: Bot, event: MessageEvent):
    await bot.send(event=event, message="获取中……")
    try:
        resp = await _fetch("https://top.baidu.com/board?tab=realtime")
        matched = re.search(r"(<!--s-data:)({.+})(-->)", resp.text)
        if not matched:
            raise ValueError("页面结构已变化，没有找到 s-data 数据块")
        items = json.loads(matched.groups()[1])["data"]["cards"][0]["content"][:cnt]
        msg_list = ["百度热搜榜"]
        for i, obj in enumerate(items):
            msg_list.append(
                f"{i + 1}、{obj['desc']}\nhot:{obj.get('hotScore', '')}\n链接:{obj.get('appUrl') or obj.get('url', '')}"
            )
        await _send_forward(bot, event, msg_list)
    except Exception as e:
        await _reply_error(bot, event, "百度热搜", e)


# 知乎热搜：改用 App 接口 api.zhihu.com（Web 版 /billboard 已需登录）
@zhihu_hotsearch.handle()
async def zhihuresou(bot: Bot, event: MessageEvent):
    await bot.send(event=event, message="获取中……")
    try:
        resp = await _fetch(
            "https://api.zhihu.com/topstory/hot-list",
            headers={"User-Agent": _ZHIHU_APP_UA},
        )
        feeds = resp.json()["data"][:cnt]
        msg_list = ["知乎热搜榜"]
        for i, feed in enumerate(feeds):
            target = feed.get("target") or {}
            title = target.get("title") or ""
            hot = feed.get("detail_text") or ""
            link = ""
            if target.get("id"):
                if target.get("type") == "article":
                    link = f"https://zhuanlan.zhihu.com/p/{target['id']}"
                else:
                    link = f"https://www.zhihu.com/question/{target['id']}"
            hot_line = f"\nhot:{hot}" if hot else ""
            msg_list.append(f"{i + 1}、{title}{hot_line}\n链接:{link}")
        await _send_forward(bot, event, msg_list)
    except Exception as e:
        await _reply_error(bot, event, "知乎热搜", e)


# 贴吧热搜
@tieba_hotsearch.handle()
async def tiebaresou(bot: Bot, event: MessageEvent):
    await bot.send(event=event, message="获取中……")
    try:
        resp = await _fetch("https://tieba.baidu.com/hottopic/browse/topicList")
        items = resp.json()["data"]["bang_topic"]["topic_list"][:cnt]
        msg_list = ["贴吧热议榜"]
        for i, obj in enumerate(items):
            msg_list.append(
                f"{i + 1}、{obj.get('topic_name', '')}\nhot:{obj.get('discuss_num', '')}\n链接:{obj.get('topic_url', '')}"
            )
        await _send_forward(bot, event, msg_list)
    except Exception as e:
        await _reply_error(bot, event, "贴吧热搜", e)


# b站热搜
@bzhan_hotsearch.handle()
async def bzhanresou(bot: Bot, event: MessageEvent):
    await bot.send(event=event, message="获取中……")
    try:
        resp = await _fetch("https://app.bilibili.com/x/v2/search/trending/ranking")
        items = resp.json()["data"]["list"][:cnt]
        msg_list = ["b站热搜"]
        for i, obj in enumerate(items):
            msg_list.append(f"{i + 1}、{obj.get('show_name', '')}")
        await _send_forward(bot, event, msg_list)
    except Exception as e:
        await _reply_error(bot, event, "b站热搜", e)
