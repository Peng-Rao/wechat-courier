# -*- coding: utf-8 -*-
"""数据模型 + 称呼提取工具"""

# 常见家长称谓后缀，按长度倒序匹配避免短的吃掉长的
_PARENT_SUFFIXES = (
    "妈妈", "爸爸", "家长", "奶奶", "爷爷",
    "外公", "外婆", "姑姑", "舅舅", "阿姨", "叔叔",
)


def extract_greeting_name(remark: str) -> str:
    """从微信备注名中提取称呼。

    "25届初二-郑子轩妈妈" → "子轩妈妈"
    "王小明爸爸"         → "小明爸爸"
    "王小明"             → "王小明"
    """
    remark = remark.strip()
    if not remark:
        return ""
    if "-" in remark:
        name_part = remark.split("-")[-1].strip()
    elif "—" in remark:  # em dash
        name_part = remark.split("—")[-1].strip()
    else:
        name_part = remark
    suffix = ""
    student_name = name_part
    for s in sorted(_PARENT_SUFFIXES, key=len, reverse=True):
        if name_part.endswith(s) and len(name_part) > len(s):
            suffix = s
            student_name = name_part[: -len(s)]
            break
    if len(student_name) == 3 and all('\u4e00' <= c <= '\u9fff' for c in student_name):
        return student_name[1:] + suffix
    return name_part


class FriendItem:
    """单个好友的轻量数据类"""

    def __init__(self, remark: str):
        self.remark = remark.strip()
        self.greeting = extract_greeting_name(self.remark)

    def format_message(self, template: str) -> str:
        try:
            return template.format(name=self.greeting)
        except (KeyError, ValueError):
            return template


class SendResult:
    """单次发送结果"""

    def __init__(self, friend: str, greeting: str, status: str, detail: str):
        self.friend = friend
        self.greeting = greeting
        self.status = status  # "success" | "error"
        self.detail = detail
