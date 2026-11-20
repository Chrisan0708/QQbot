"""会话存储 + OpenAI 兼容接口调用。

只依赖 httpx，不引入任何 SDK，避免和别的插件抢 httpx 版本。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from nonebot.log import logger

from .config import Config

# 单条用户消息的字符上限，防止有人贴一整篇小说把上下文撑爆
MAX_MESSAGE_CHARS = 2000
# 会话空闲多久后被回收（秒）
SESSION_IDLE_SECONDS = 6 * 3600
# 超过这个数量的会话时，触发一次过期清理
SESSION_PRUNE_THRESHOLD = 200


class AIChatError(Exception):
    """调用模型失败时抛出，message 可以直接回给用户。"""


@dataclass
class ChatSession:
    """一个用户/群的对话上下文（不含 system prompt）。"""

    messages: list[dict[str, str]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


# 会话表：key = "p:<user_id>" 或 "g:<group_id>:<user_id>"
SESSIONS: dict[str, ChatSession] = {}
# 每个会话一把锁，避免同一个人连发两条时上下文交错
LOCKS: dict[str, asyncio.Lock] = {}

# 全局开关（运行时可被 /aichat on|off 修改，重启后回到 .env 的值）
RUNTIME_ENABLED: bool = True


def session_key(event: Any) -> str:
    """给每个用户生成独立的会话 key。

    私聊：一个人一个会话。
    群聊：同一个人在同一个群里一个会话（换个群就是新会话）。
    """
    user_id = str(event.get_user_id())
    group_id = getattr(event, "group_id", None)
    if group_id:
        return f"g:{group_id}:{user_id}"
    return f"p:{user_id}"


def get_lock(key: str) -> asyncio.Lock:
    lock = LOCKS.get(key)
    if lock is None:
        lock = LOCKS[key] = asyncio.Lock()
    return lock


def get_session(key: str) -> ChatSession:
    session = SESSIONS.get(key)
    if session is None:
        session = SESSIONS[key] = ChatSession()
    session.updated_at = time.time()
    _prune_if_needed()
    return session


def reset_session(key: str) -> int:
    """清空上下文，返回被清掉的条数。"""
    session = SESSIONS.pop(key, None)
    return len(session.messages) if session else 0


def _prune_if_needed() -> None:
    if len(SESSIONS) <= SESSION_PRUNE_THRESHOLD:
        return
    deadline = time.time() - SESSION_IDLE_SECONDS
    for key in [k for k, v in SESSIONS.items() if v.updated_at < deadline]:
        SESSIONS.pop(key, None)
        LOCKS.pop(key, None)
    logger.debug(f"[aichat] 会话清理后剩余 {len(SESSIONS)} 个")


# ---------------------------------------------------------------- token 估算


def estimate_tokens(text: str) -> int:
    """粗略估算 token：中日韩字符按 1 token，其它按 4 字符 1 token。

    只是用来控制上下文长度，不需要和真实分词器完全一致。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff"
              or "\u3040" <= ch <= "\u30ff"
              or "\uac00" <= ch <= "\ud7af")
    return cjk + max(1, (len(text) - cjk) // 4)


def _messages_tokens(messages: list[dict[str, str]]) -> int:
    # 每条消息额外算 4 个 token 的角色/分隔开销
    return sum(estimate_tokens(m["content"]) + 4 for m in messages)


def trim_history(session: ChatSession, max_rounds: int, max_tokens: int) -> None:
    """同时按「轮数」和「token 预算」裁剪历史，从最早的开始丢。"""
    if max_rounds <= 0:
        session.messages.clear()
        return

    # 1. 先按轮数裁：1 轮 = user + assistant 两条
    max_messages = max_rounds * 2
    if len(session.messages) > max_messages:
        session.messages = session.messages[-max_messages:]

    # 2. 再按 token 预算裁，注意保持 user/assistant 成对
    while len(session.messages) > 1 and _messages_tokens(session.messages) > max_tokens:
        session.messages.pop(0)
    # 如果裁剪后第一条是 assistant（孤儿回复），继续丢
    while session.messages and session.messages[0]["role"] != "user":
        session.messages.pop(0)


# ---------------------------------------------------------------- 模型调用


def build_endpoint(endpoint: str) -> str:
    """把 base url 补成 /chat/completions 完整地址。"""
    url = (endpoint or "").strip().rstrip("/")
    if not url:
        raise AIChatError("没有配置 API 地址（AICHAT_API_ENDPOINT）")
    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


async def chat_completion(
    config: Config,
    history: list[dict[str, str]],
    user_text: str,
) -> tuple[str, dict[str, Any]]:
    """调用 OpenAI 兼容接口，返回 (回复文本, usage 信息)。"""
    if not config.aichat_api_key:
        raise AIChatError("没有配置 API Key（AICHAT_API_KEY）")

    payload: dict[str, Any] = {
        "model": config.aichat_model_name,
        "messages": [
            {"role": "system", "content": config.aichat_system_prompt},
            *history,
            {"role": "user", "content": user_text},
        ],
        "temperature": config.aichat_temperature,
        "max_tokens": config.aichat_max_reply_tokens,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {config.aichat_api_key}",
        "Content-Type": "application/json",
    }
    url = build_endpoint(config.aichat_api_endpoint)

    try:
        async with httpx.AsyncClient(timeout=config.aichat_timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as e:
        raise AIChatError(f"模型响应超时（{config.aichat_timeout:.0f}s）") from e
    except httpx.HTTPError as e:
        raise AIChatError(f"请求模型失败：{type(e).__name__}") from e

    if resp.status_code != 200:
        snippet = (resp.text or "").strip().replace("\n", " ")[:200]
        raise AIChatError(f"模型返回 {resp.status_code}：{snippet}")

    try:
        data = resp.json()
        content = (data["choices"][0]["message"].get("content") or "").strip()
    except Exception as e:  # noqa: BLE001
        raise AIChatError("模型返回的格式不是 OpenAI 兼容格式") from e

    if not content:
        raise AIChatError("模型返回了空内容")

    usage = data.get("usage") or {}
    return content, usage
