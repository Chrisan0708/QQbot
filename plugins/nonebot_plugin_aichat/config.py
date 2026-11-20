"""nonebot-plugin-aichat 配置定义。

所有配置项都写在 `.env` 里，大小写不敏感。推荐统一用 `AICHAT_` 前缀，
避免和别的插件撞车；没写前缀的旧写法（API_KEY 等）也会被兜底识别，见
`resolve_config()`。
"""

from pydantic import BaseModel, Field

# 默认人设。想换成自己的，直接在 .env 里写 AICHAT_SYSTEM_PROMPT=...
# 或者改下面这个常量。
DEFAULT_SYSTEM_PROMPT = (
    "你是一个中文聊天助手，语气自然、简洁、有分寸。\n"
    "要求：\n"
    "1. 默认用中文回答，除非用户用了别的语言。\n"
    "2. 先给结论再补充细节，能一句话说清就不要写一段。\n"
    "3. 不确定的事直接说不确定，不要编造事实、链接或数据。\n"
    "4. 不要使用 Markdown 标题、表格、代码块等重排版格式，QQ 里很难看。\n"
    "5. 遇到违法、危险或明显有害的请求，简短拒绝并说明原因。"
)


class Config(BaseModel):
    """插件配置项（全部有默认值，最简只需要填 API Key）。"""

    # 总开关：false 时只有 /aichat on 才能重新打开（需要 SUPERUSERS）
    aichat_enabled: bool = Field(default=True, description="是否启用 AI 对话")

    # ---- 模型相关 ----
    aichat_api_key: str = Field(default="", description="API Key")
    aichat_api_endpoint: str = Field(
        default="https://api.deepseek.com/v1",
        description="OpenAI 兼容接口的 base url，也可以直接写完整的 /chat/completions",
    )
    aichat_model_name: str = Field(default="deepseek-chat", description="模型名")
    aichat_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    aichat_timeout: float = Field(default=60.0, gt=0, description="单次请求超时（秒）")

    # ---- 上下文 / 用量限制 ----
    aichat_max_history: int = Field(
        default=10, ge=0, le=100, description="最多记忆多少轮（1 轮 = 1 问 + 1 答）"
    )
    aichat_max_token: int = Field(
        default=4000, ge=200, description="上下文 token 预算，超出时丢弃最早的对话"
    )
    aichat_max_reply_tokens: int = Field(
        default=800, ge=16, description="单次回复的最大 token 数（max_tokens）"
    )

    # ---- 触发方式 ----
    aichat_trigger_group: bool = Field(
        default=True, description="群聊里 @机器人 时是否回复"
    )
    aichat_trigger_private: bool = Field(
        default=True, description="私聊是否直接回复"
    )

    # ---- 人设 ----
    aichat_system_prompt: str = Field(
        default=DEFAULT_SYSTEM_PROMPT, description="system prompt（人设）"
    )


def resolve_config(config: Config, driver_config: object) -> Config:
    """把没填的 AICHAT_* 项回退到不带前缀的写法。

    方便直接照需求里的 `API_KEY` / `API_ENDPOINT` / `MODEL_NAME` /
    `MAX_HISTORY` / `MAX_TOKEN` 来写 .env；两种写法同时存在时以
    `AICHAT_*` 为准。
    """
    fallbacks = {
        "aichat_api_key": "api_key",
        "aichat_api_endpoint": "api_endpoint",
        "aichat_model_name": "model_name",
        "aichat_max_history": "max_history",
        "aichat_max_token": "max_token",
    }
    for target, legacy in fallbacks.items():
        if getattr(config, target, None) not in (None, ""):
            continue
        value = getattr(driver_config, legacy, None)
        if value not in (None, ""):
            setattr(config, target, value)
    return config
