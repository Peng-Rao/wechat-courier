"""Shared, side-effect-free rules for friend names and greeting templates."""
from __future__ import annotations

from string import Formatter

RELATIONSHIPS = (
    "爸爸", "妈妈", "哥哥", "姐姐", "弟弟", "妹妹", "爷爷", "奶奶", "外公", "外婆",
    "姥爷", "姥姥", "伯伯", "伯母", "叔叔", "婶婶", "姑姑", "姑父", "舅舅", "舅妈",
    "姨妈", "姨父", "阿姨",
)


def split_name(value: str) -> tuple[str, str | None]:
    """Strip at most one known suffix; None means follow the global relation."""
    value = value.strip()
    for suffix in sorted(RELATIONSHIPS, key=len, reverse=True):
        if value.endswith(suffix):
            return value[:-len(suffix)].strip(), suffix
    return value, None


def normalize_relationship(value: str) -> str:
    value = value.strip()
    return "" if value == "无" else value


def render_friend_content(name: str, relationship: str | None, greeting: str,
                          default_greeting: str, default_relationship: str) -> tuple[str | None, str]:
    effective = normalize_relationship(default_relationship if relationship is None else relationship)
    remark = name + effective if name else ""
    values = {"姓名": name, "后缀": effective, "关系": effective, "称呼": remark}
    template = greeting.strip() or default_greeting.strip()
    if not template:
        return None, remark
    try:
        parts = []
        for literal, field, spec, conversion in Formatter().parse(template):
            parts.append(literal)
            if field is not None:
                if field not in values:
                    raise ValueError(f"未知占位符 {{{field}}}；支持 {{姓名}}、{{后缀}}、{{称呼}}（兼容 {{关系}}）")
                if spec or conversion:
                    raise ValueError("占位符不支持格式说明或转换")
                parts.append(values[field])
        return "".join(parts), remark
    except ValueError as exc:
        raise ValueError(f"打招呼语模板错误：{exc}") from exc
