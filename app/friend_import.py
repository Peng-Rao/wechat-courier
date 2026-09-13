from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


ACCOUNT_HEADER = "账号"
GREETING_HEADER = "打招呼语"
REMARK_HEADER = "备注"
PHONE_PATTERN = re.compile(r"^(?:\+?86)?1[3-9]\d{9}$")
WEIXIN_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{5,31}$")


class FriendImportError(ValueError):
    pass


@dataclass
class FriendRecord:
    item_id: str
    account: str
    greeting: str = ""
    remark: str = ""
    valid: bool = True
    error: str = ""
    status: str = "pending"
    selected: bool = False


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_account(value: str) -> str:
    account = "".join(value.strip().split())
    if PHONE_PATTERN.fullmatch(account):
        if account.startswith("+86"):
            account = account[3:]
        elif account.startswith("86") and len(account) == 13:
            account = account[2:]
        return account
    return account.casefold()


def account_error(value: str) -> str:
    account = "".join(value.strip().split())
    if not account:
        return "账号不能为空"
    if PHONE_PATTERN.fullmatch(account) or WEIXIN_ID_PATTERN.fullmatch(account):
        return ""
    return "账号必须是微信号或手机号，不能使用昵称"


def validate_records(records: Sequence[FriendRecord]) -> None:
    seen: set[str] = set()
    for record in records:
        record.account = _cell_text(record.account)
        error = account_error(record.account)
        normalized = normalize_account(record.account)
        if not error and normalized in seen:
            error = "账号重复"
        if not error:
            seen.add(normalized)
        record.valid = not error
        record.error = error
        if error:
            record.selected = False


def _records_from_rows(rows: Iterable[Sequence[Any]]) -> list[FriendRecord]:
    materialized = [list(row) for row in rows]
    if not materialized:
        raise FriendImportError("导入文件为空")
    headers = [_cell_text(value) for value in materialized[0]]
    if ACCOUNT_HEADER not in headers:
        raise FriendImportError("首行必须包含“账号”列")
    index = {name: headers.index(name) for name in headers if name}

    def value_at(row: Sequence[Any], header: str) -> str:
        column = index.get(header)
        if column is None or column >= len(row):
            return ""
        return _cell_text(row[column])

    records = []
    for row_number, row in enumerate(materialized[1:], start=2):
        values = [value_at(row, name) for name in headers]
        if not any(values):
            continue
        records.append(
            FriendRecord(
                item_id=f"row-{row_number}",
                account=value_at(row, ACCOUNT_HEADER),
                greeting=value_at(row, GREETING_HEADER),
                remark=value_at(row, REMARK_HEADER),
            )
        )
    validate_records(records)
    selected = 0
    for record in records:
        if record.valid and selected < 20:
            record.selected = True
            selected += 1
    return records


def _csv_rows(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise FriendImportError("CSV 编码必须为 UTF-8 BOM 或 GB18030")
    return [list(row) for row in csv.reader(text.splitlines())]


def _xlsx_rows(path: Path) -> list[list[Any]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise FriendImportError("缺少 openpyxl，无法读取 XLSX") from exc
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise FriendImportError(f"无法读取 XLSX：{exc}") from exc
    try:
        worksheet = workbook.worksheets[0]
        return [list(row) for row in worksheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def load_friend_records(source) -> list[FriendRecord]:
    if isinstance(source, (str, Path)):
        path = Path(source)
        suffix = path.suffix.casefold()
        if suffix == ".csv":
            rows = _csv_rows(path)
        elif suffix == ".xlsx":
            rows = _xlsx_rows(path)
        else:
            raise FriendImportError("仅支持 CSV 或 XLSX 文件")
        return _records_from_rows(rows)
    return _records_from_rows(source)


__all__ = [
    "FriendImportError",
    "FriendRecord",
    "account_error",
    "load_friend_records",
    "normalize_account",
    "validate_records",
]
