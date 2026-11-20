"""nonebot-plugin-aichat

一个不依赖任何 SDK 的 AI 对话插件：
- 群聊：@机器人 + 内容（适配器会自动去掉开头的 @，这里拿到的就是正文）
- 私聊：直接发消息就回复
- 每个用户独立上下文，按「轮数 + token 预算」双限制记忆
- 只依赖 nonebot2 + httpx，走通用 OpenAI 兼容接口（DeepSeek / 通义千问等）
- 不内置 TTS，但对外暴露 `register_reply_hook()`，TTS 插件可以挂上来

配置见 `.env.example` 与 README.md。
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable

from nonebot import get_driver, get_plugin_config, logger, on_command, on_message
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from .chat import (
    MAX_MESSAGE_CHARS,
    SESSIONS,
    AIChatError,
    chat_completion,
    estimate_tokens,
    get_lock,
    get_session,
    reset_session,
    session_key,
    trim_history,
)
from .config import DEFAULT_SYSTEM_PROMPT, Config, resolve_config

__plugin_meta__ = PluginMetadata(
    name="AI 对话",
    description="基于 OpenAI 兼容接口的多轮 AI 对话，每用户独立上下文",
    usage=(
        "群聊：@机器人 + 内容\n"
        "私聊：直接发消息\n"
        "管理：/aichat status | reset | on | off"
    ),
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

driver = get_driver()
plugin_config = resolve_config(get_plugin_config(Config), driver.config)

# 运行时总开关，/aichat on|off 会改它（重启后回到 .env 里的值）
_enabled: bool = plugin_config.aichat_enabled

# 其它插件（比如 TTS）可以注册的回调：收到 (bot, event, 回复文本)
ReplyHook = Callable[[Bot, MessageEvent, str], Awaitable[None]]
_reply_hooks: list[ReplyHook] = []


def register_reply_hook(hook: ReplyHook) -> None:
    """注册一条「模型回复之后」的钩子，用来接 TTS 之类的外部能力。

    示例（在另一个插件里）::

        aichat = require("nonebot_plugin_aichat")
        aichat.register_reply_hook(my_tts_hook)

        async def my_tts_hook(bot, event, text):
            audio = await tts(text)          # 自己调用 TTS 服务
            await bot.send(event, MessageSegment.record(audio))
    """
    _reply_hooks.append(hook)


def _command_start() -> set[str]:
    """取 COMMAND_START，用来避开命令消息。"""
    start = getattr(driver.config, "command_start", None)
    return set(start) if start else {"/"}


def extract_text(event: MessageEvent) -> str:
    """只取纯文本段，天然过滤 CQ 码（图片、表情、@、回复等一律丢掉）。"""
    parts = [
        segment.data.get("text", "")
        for segment in event.get_message()
        if segment.type == "text"
    ]
    text = "".join(parts).strip()
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[:MAX_MESSAGE_CHARS]
    return text


def _looks_like_command(text: str) -> bool:
    """命令消息不交给 AI 处理，避免和 `aichat` / 其它插件抢同一条消息。"""
    for start in _command_start():
        if start and text.startswith(start):
            return True
    first = text.split(maxsplit=1)[0].lower()
    return first in {"aichat", "ai对话"}


async def _should_chat(event: MessageEvent) -> bool:
    """判断这条消息要不要交给 AI。"""
    if not _enabled or not isinstance(event, MessageEvent):
        return False

    if event.message_type == "private":
        if not plugin_config.aichat_trigger_private:
            return False
    else:
        # 群聊必须 @机器人；适配器解析时已去掉开头的 @ 并设置 to_me
        if not plugin_config.aichat_trigger_group or not event.is_tome():
            return False

    text = extract_text(event)
    return bool(text) and not _looks_like_command(text)


aichat = on_message(rule=Rule(_should_chat), priority=90, block=True)


@aichat.handle()
async def _handle_chat(bot: Bot, event: MessageEvent) -> None:
    question = extract_text(event)
    if not question:
        return

    key = session_key(event)
    who = str(event.get_user_id())

    # 同一个会话串行处理，避免用户连发两条时上下文交错
    async with get_lock(key):
        session = get_session(key)
        trim_history(session, plugin_config.aichat_max_history, plugin_config.aichat_max_token)
        history = list(session.messages)

        started = time.monotonic()
        logger.info(
            f"[aichat] 提问 user={who} key={key} 轮数={len(history) // 2} "
            f"上下文≈{sum(estimate_tokens(m['content']) for m in history)}tok "
            f"内容={question[:120]!r}"
        )

        try:
            reply, usage = await chat_completion(plugin_config, history, question)
        except AIChatError as e:
            logger.warning(f"[aichat] 调用失败 user={who} key={key}: {e}")
            await aichat.finish("AI 暂时不可用，请稍后再试一下~")
            return
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[aichat] 未预期异常 user={who} key={key}: {e!r}")
            await aichat.finish("AI 出了点问题，已经记到日志里了~")
            return

        logger.info(
            f"[aichat] 回复 user={who} 耗时={time.monotonic() - started:.1f}s "
            f"prompt_tok={usage.get('prompt_tokens', '?')} "
            f"completion_tok={usage.get('completion_tokens', '?')} "
            f"字数={len(reply)} 摘要={reply[:80]!r}"
        )

        # 先写回上下文再发消息，保证对话连贯（发送失败也不影响下一轮）
        session.messages.append({"role": "user", "content": question})
        session.messages.append({"role": "assistant", "content": reply})
        trim_history(session, plugin_config.aichat_max_history, plugin_config.aichat_max_token)

    await aichat.send(reply)

    # 外部钩子（TTS 等），出错不影响主流程
    for hook in list(_reply_hooks):
        try:
            await hook(bot, event, reply)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[aichat] 回复钩子执行失败: {e!r}")


manage = on_command("aichat", aliases={"ai对话"}, priority=5, block=True)


@manage.handle()
async def _handle_manage(event: MessageEvent, args: Message = CommandArg()) -> None:
    global _enabled

    tokens = args.extract_plain_text().strip().split()
    action = tokens[0].lower() if tokens else "status"

    if action in {"on", "off"}:
        superusers = {str(u) for u in (getattr(driver.config, "superusers", None) or set())}
        if not superusers:
            await manage.finish(
                "没有配置 SUPERUSERS，无法在聊天里开关。\n"
                '请在 .env 里加 SUPERUSERS=["你的QQ号"]，或者改 AICHAT_ENABLED 后重启。'
            )
        if str(event.get_user_id()) not in superusers:
            await manage.finish("只有超级用户能开关 AI 对话。")
        _enabled = action == "on"
        logger.info(f"[aichat] 总开关 -> {_enabled}（操作者 {event.get_user_id()}）")
        await manage.finish(f"AI 对话已{'开启' if _enabled else '关闭'}。")

    if action == "reset":
        removed = reset_session(session_key(event))
        await manage.finish(f"已清空当前会话上下文（{removed} 条消息）。")

    session = SESSIONS.get(session_key(event))
    await manage.finish(
        "\n".join(
            [
                f"状态：{'开启' if _enabled else '关闭'}",
                f"模型：{plugin_config.aichat_model_name}",
                f"记忆上限：{plugin_config.aichat_max_history} 轮 / {plugin_config.aichat_max_token} token",
                f"当前会话：{len(session.messages) if session else 0} 条消息",
                "人设：" + ("自定义" if plugin_config.aichat_system_prompt != DEFAULT_SYSTEM_PROMPT else "默认"),
                "用法：/aichat reset 清空上下文；/aichat on|off 开关（需超级用户）",
            ]
        )
    )
