# nonebot-plugin-aichat

一个干净的 AI 对话插件：**只依赖 nonebot2 + httpx**，走通用 OpenAI 兼容接口（DeepSeek / 通义千问 / 其它中转都行），不引入 `fish-audio-sdk`、`aitalk` 之类的包，避免和现有插件抢 httpx 版本。

## 它做什么

| 能力 | 说明 |
|---|---|
| 触发 | 群聊 `@机器人 + 内容`；私聊直接发消息 |
| 上下文 | 每个用户独立会话，群聊按「群 + 用户」隔离 |
| 记忆限制 | 同时按 **轮数**（默认 10 轮）和 **token 预算**（默认 4000）裁剪，超了丢最早的 |
| CQ 码 | 只取纯文本段，图片/表情/@/回复一律忽略 |
| 日志 | 打印提问、回复摘要、耗时、token 用量，方便 `docker logs` 排错 |
| TTS | 不内置；对外暴露 `register_reply_hook()` 给独立插件挂 |

## 安装

把整个目录丢进 `plugins/` 即可（本仓库已经放好）：

```
plugins/
└── nonebot_plugin_aichat/
    ├── __init__.py
    ├── config.py
    ├── chat.py
    └── README.md
```

`pyproject.toml` 里已有 `plugin_dirs = ["plugins"]`，重启会自动加载，日志里应出现：

```
[SUCCESS] nonebot | Succeeded to load plugin "nonebot_plugin_aichat" from "plugins.nonebot_plugin_aichat"
```

> Docker 部署：`plugins/` 已经 COPY 进镜像，改完代码要 `docker compose up -d --build`。

## 配置（写在 `.env`）

最简只要填一个 Key：

```ini
AICHAT_API_KEY=sk-xxxxxxxx
AICHAT_API_ENDPOINT=https://api.deepseek.com/v1
AICHAT_MODEL_NAME=deepseek-chat
```

完整配置项：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `AICHAT_ENABLED` | `true` | 总开关，`false` 时只有 `/aichat on` 能重新打开 |
| `AICHAT_API_KEY` | 空 | API Key（必填，否则会提示"没有配置 API Key"） |
| `AICHAT_API_ENDPOINT` | `https://api.deepseek.com/v1` | base url，也可以直接写完整的 `.../chat/completions` |
| `AICHAT_MODEL_NAME` | `deepseek-chat` | 模型名 |
| `AICHAT_MAX_HISTORY` | `10` | 最多记忆多少轮（1 轮 = 1 问 + 1 答） |
| `AICHAT_MAX_TOKEN` | `4000` | 上下文 token 预算，超出丢最早的对话 |
| `AICHAT_MAX_REPLY_TOKENS` | `800` | 单条回复的 `max_tokens` |
| `AICHAT_TEMPERATURE` | `0.7` | 温度 |
| `AICHAT_TIMEOUT` | `60` | 单次请求超时（秒） |
| `AICHAT_TRIGGER_GROUP` | `true` | 群聊 @ 时是否回复 |
| `AICHAT_TRIGGER_PRIVATE` | `true` | 私聊是否回复 |
| `AICHAT_SYSTEM_PROMPT` | 内置人设 | 换人设就改这个 |

**不带前缀的写法也认**：`API_KEY` / `API_ENDPOINT` / `MODEL_NAME` / `MAX_HISTORY` / `MAX_TOKEN` 会被当成对应的 `AICHAT_*` 使用（两种同时存在时以 `AICHAT_*` 为准）。

### 常见服务商写法

```ini
# DeepSeek
AICHAT_API_ENDPOINT=https://api.deepseek.com/v1
AICHAT_MODEL_NAME=deepseek-chat

# 通义千问（阿里云 DashScope 的 OpenAI 兼容模式）
AICHAT_API_ENDPOINT=https://dashscope.aliyuncs.com/compatible-mode/v1
AICHAT_MODEL_NAME=qwen-plus

# 本地 Ollama
AICHAT_API_ENDPOINT=http://127.0.0.1:11434/v1
AICHAT_MODEL_NAME=qwen2.5:7b
```

## 使用

```
群聊：@机器人 你好，介绍一下你自己
私聊：你好，介绍一下你自己
```

管理命令：

| 命令 | 谁能用 | 作用 |
|---|---|---|
| `/aichat` 或 `/aichat status` | 所有人 | 看开关、模型、记忆上限、当前会话条数 |
| `/aichat reset` | 所有人 | 清空自己的上下文（换话题时用） |
| `/aichat on` / `/aichat off` | 超级用户 | 全局开关 |

## 怎么开启 / 关闭对话

三种方式，按需要选：

1. **永久关掉**：`.env` 里 `AICHAT_ENABLED=false`，重启生效（不影响其它插件）。
2. **临时关掉**：先配 `SUPERUSERS=["你的QQ号"]`，然后聊天里发 `/aichat off`，重启后自动恢复为 `.env` 的值。
3. **只关某个场景**：`AICHAT_TRIGGER_GROUP=false`（群里不响应，只留私聊）或 `AICHAT_TRIGGER_PRIVATE=false`。

> 没配 `SUPERUSERS` 时 `/aichat on|off` 会直接提示你去改 `.env`，不会静默失败。

## 日志长这样

```
[aichat] 提问 user=3119704272 key=g:1131474365:3119704272 轮数=2 上下文≈58tok 内容='你还记得我刚说什么吗'
[aichat] 回复 user=3119704272 耗时=2.3s prompt_tok=214 completion_tok=37 字数=42 摘要='你刚才问我 DeepSeek 和 Qwen 的区别...'
```

失败时：

```
[aichat] 调用失败 user=3119704272 key=p:3119704272: 模型返回 401：{"error":...}
```

## TTS 怎么接（独立插件，不在本插件内）

本插件只提供钩子，不绑定任何 TTS 服务：

```python
# plugins/my_tts/__init__.py
from nonebot import require
from nonebot.adapters.onebot.v11 import MessageSegment

aichat = require("nonebot_plugin_aichat")


async def tts_hook(bot, event, text: str) -> None:
    audio = await call_your_tts(text)          # 返回 bytes 或 URL
    await bot.send(event, MessageSegment.record(audio))


aichat.register_reply_hook(tts_hook)
```

钩子拿不到回复、抛异常都不影响主流程，只在日志里留一条 warning。

## 注意事项

- **上下文在内存里**，重启 bot 就清空（故意的：不引入数据库依赖）。要持久化得自己换成 localstore。
- **token 是估算的**（中文 1 字≈1 token，英文 4 字符≈1 token），只用于控制上下文长度，不追求和真实分词器一致。
- 群里必须 **@机器人** 才会触发，普通聊天不会打扰。
- 命令消息（以 `COMMAND_START` 开头、或 `aichat` 开头）不会被当成聊天内容。
- 单条消息超过 2000 字会被截断，避免把上下文撑爆。
