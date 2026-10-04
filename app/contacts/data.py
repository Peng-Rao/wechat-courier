from __future__ import annotations

import re


CONTACT_FIELDS = ("nick_name", "remark", "phone", "username", "alias", "description")
CONTACT_HEADERS = ("\u6635\u79f0", "\u5907\u6ce8", "\u624b\u673a\u53f7", "\u5fae\u4fe1 ID", "\u5fae\u4fe1\u53f7", "\u63cf\u8ff0")

_SYSTEM_IDS = frozenset({
    "filehelper", "weixin", "fmessage", "medianote", "floatbottle", "newsapp",
    "qqmail", "tmessage", "qmessage", "qqsync", "lbsapp", "shakeapp",
    "voiceinputapp", "officialaccounts", "notification_messages",
    "brandsessionholder", "notifymessage", "sysnotice",
})
_DELETION_FIELDS = ("is_del", "is_delete", "is_deleted", "delete_flag", "deleted", "deletion", "DelFlag")
_VERIFICATION_FIELDS = ("verify_flag", "verification_flag", "verification", "VerifyFlag")


def _integer(value: object) -> int | None:
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value.strip()):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _category(row: dict, username: str) -> str:
    account = username.casefold()
    if account.endswith("@chatroom"):
        return "group"
    if account.startswith("gh_"):
        return "official"
    if account in _SYSTEM_IDS:
        return "system"
    if account.endswith("@stranger"):
        return "cache"

    verification = [_integer(row[key]) for key in _VERIFICATION_FIELDS if key in row]
    if any(value is not None and value > 0 for value in verification):
        return "official"
    deletion = [_integer(row[key]) for key in _DELETION_FIELDS if key in row]
    if any(value != 0 for value in (*deletion, *verification)):
        return "other"

    # local_type is authoritative when present; unknown values cannot fall
    # back to a legacy type and accidentally enter the default friend view.
    if "local_type" in row:
        local_type = _integer(row["local_type"])
        return {0: "cache", 1: "friend", 3: "cache"}.get(local_type, "other")
    legacy_type = _integer(row.get("type", row.get("Type")))
    return {0: "cache", 1: "friend", 3: "friend"}.get(legacy_type, "other")


def normalize_contact(row: dict) -> dict[str, str]:
    """Copy decoded contact text and classify only recognized metadata/IDs."""
    contact = {
        field: "" if row.get(field) is None else str(row[field])
        for field in CONTACT_FIELDS
    }
    contact["category"] = _category(row, contact["username"])
    return contact
