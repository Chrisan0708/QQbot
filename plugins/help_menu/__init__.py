"""扫描式帮助菜单插件。

为什么需要它：原 autohelp 的命令提取是"逐行正则找 `xxx = on_command("yyy")`"，
本机 16 个插件里只有 Hello_echo 和内置 echo 符合这一写法，所以旧菜单永远只有两条命令，
其余插件在输出里只留下一个个空行（看起来像"插件没装好"）。

本插件改为解析已加载插件的源码 AST，能认出：
on_command / on_fullmatch / on_startswith / on_keyword / on_regex / on_alconna / clovers 的 plugin.handle。
触发词：help / 帮助 / 菜单 / menu / caidan / info（前缀 / ! # 可有可无）。
优先级 0 且 block=True，用来顶掉优先级 1 的 autohelp，避免同一句话回两条菜单。
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from nonebot import get_loaded_plugins, logger, on_message
from nonebot.adapters.onebot.v11 import Bot, Event

TRIGGER = re.compile(r"^\s*[/!#]?\s*(?:help|menu|帮助|菜单|caidan|info)\s*$", re.I)

# 扫描不到命令、但确实存在触发方式的插件：人工补充（键为模块名）
MANUAL_NOTES: dict[str, list[str]] = {
    "nonebot_plugin_analysis_bilibili": [
        "整条消息里带 av号 / BV号 / b23.tv / bilibili.com 链接时自动解析（无需命令）",
    ],
    "clovers_setu_collection": [
        "来N张<标签>图（例：来3张猫娘图，必须 @机器人）",
        "色图 / 涩图（查看用法说明，必须 @机器人）",
        "设置api / 切换api / 指定api（15 秒内回 1 或 2 选择图站）",
    ],
    "nonebot_plugin_autohelp": [
        "help / 菜单 / 帮助 / /i（旧菜单，仍在运行，可通过删掉 pyproject 里对应条目关闭）",
    ],
    "nonebot_plugin_cs2match": [
        "以上命令需先在 .env 配置 PANDASCORE_TOKEN，否则不会响应（/monitor 仅群聊、需群管）",
    ],
}

REGISTRARS = {"on_command", "on_fullmatch", "on_startswith", "on_keyword"}
REGEX_MARKS = "()[]|.*+?\\^$"


def _callee(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _const_str(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _str_members(node: ast.expr | None) -> list[str]:
    if node is None:
        return []
    one = _const_str(node)
    if one is not None:
        return [one]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [x for e in node.elts if (x := _const_str(e)) is not None]
    return []


def _short(text: str, limit: int = 30) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _extract(node: ast.Call) -> list[tuple[str, str]]:
    """从单个调用节点抽取 (类型, 内容)，类型取值 cmd / regex。"""
    name = _callee(node.func)
    out: list[tuple[str, str]] = []

    if name in REGISTRARS and node.args:
        aliases: list[str] = []
        for kw in node.keywords:
            if kw.arg in {"aliases", "keyword", "keywords"}:
                aliases = _str_members(kw.value)
        for item in _str_members(node.args[0]):
            text = item if not aliases else f"{item}（别名：{'、'.join(aliases)}）"
            out.append(("cmd", text))

    elif name == "on_regex" and node.args:
        pattern = _const_str(node.args[0])
        if pattern:
            out.append(("regex", _short(pattern)))

    elif name in {"on_alconna", "Alconna"}:
        target = node.args[0] if node.args else None
        if isinstance(target, ast.Call):
            cmd = _const_str(target.args[0]) if target.args else None
        else:
            cmd = _const_str(target)
        if cmd:
            out.append(("cmd", cmd))

    elif name == "handle" and node.args:
        # clovers：plugin.handle(["涩图", "色图"]) 或 plugin.handle(r"来(.*)[张份](.+)$")
        for item in _str_members(node.args[0]):
            if any(ch in item for ch in REGEX_MARKS):
                out.append(("regex", _short(item)))
            else:
                out.append(("cmd", item))

    return out


def _source_files(module: Any) -> list[Path]:
    file = getattr(module, "__file__", None)
    if not file:
        return []
    path = Path(file)
    if path.name == "__init__.py":
        return [p for p in path.parent.rglob("*.py") if "__pycache__" not in p.parts]
    return [path]


def _collect(module: Any) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for file in _source_files(module):
        try:
            tree = ast.parse(file.read_text("utf-8", errors="replace"))
        except Exception as err:  # 源码异常不能让 help 挂掉
            logger.debug(f"help_menu 跳过 {file}：{err}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                found.extend(_extract(node))
    return list(dict.fromkeys(found))


def _module_available(name: str) -> bool:
    if name in sys.modules:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


@lru_cache(maxsize=1)
def build_menu() -> str:
    """生成菜单文本（缓存，重启后自动失效）。"""
    entries: list[tuple[str, list[tuple[str, str]]]] = []

    for plugin in sorted(get_loaded_plugins(), key=lambda p: p.name):
        if plugin.metadata is not None and plugin.metadata.type == "library":
            continue  # 库插件没有用户可用的指令
        items = _collect(plugin.module)
        items += [("note", note) for note in MANUAL_NOTES.get(plugin.name, [])]
        if items:
            entries.append((plugin.name, items))

    # clovers 内部加载的插件（如 clovers_setu_collection）不是 NoneBot 插件，需单独补进来
    known = {name for name, _ in entries}
    for name, notes in MANUAL_NOTES.items():
        if name in known or not _module_available(name):
            continue
        entries.append((name, [("note", note) for note in notes]))

    command_total = sum(1 for _, items in entries for kind, _ in items if kind == "cmd")

    lines = [
        "指令总览（读取已加载插件源码自动生成，改代码后重启即刷新）",
        f"共 {len(entries)} 个有交互能力的插件，其中 {command_total} 条是标准命令（/ 前缀）",
    ]

    for name, items in entries:
        lines.append("")
        lines.append(f"▸ {name}")
        for kind, text in items:
            if kind == "cmd":
                lines.append(f"   /{text}")
            elif kind == "regex":
                lines.append(f"   消息匹配：{text}")
            else:
                lines.append(f"   · {text}")

    lines.append("")
    lines.append("说明：/ 为项目默认命令前缀（COMMAND_START），消息匹配类不写命令名、直接说那句话即可。")
    return "\n".join(lines)


help_menu = on_message(
    rule=lambda event: bool(TRIGGER.match(event.get_plaintext() or "")),
    priority=0,
    block=True,
)


@help_menu.handle()
async def _(bot: Bot, event: Event):
    await help_menu.finish(build_menu())
