from __future__ import annotations

from dataclasses import dataclass


class UnsupportedWeixinVersion(RuntimeError):
    """Raised when no verified automation profile exists for a Weixin build."""


@dataclass(frozen=True)
class WeixinProfile:
    version: str
    gate_rva: int
    main_root_class: str
    search_edit_name: str
    search_edit_class: str
    search_popup_class: str
    search_list_automation_id: str
    chat_input_automation_id: str
    chat_input_class: str
    add_friend_root_class: str
    verify_friend_root_class: str


_PROFILES = {
    "4.1.13.65": WeixinProfile(
        version="4.1.13.65",
        gate_rva=0x0AE2B0C8,
        main_root_class="mmui::MainWindow",
        search_edit_name="搜索",
        search_edit_class="mmui::XValidatorTextEdit",
        search_popup_class="mmui::XPopover",
        search_list_automation_id="search_list",
        chat_input_automation_id="chat_input_field",
        chat_input_class="mmui::ChatInputField",
        add_friend_root_class="mmui::AddFriendWindow",
        verify_friend_root_class="mmui::VerifyFriendWindow",
    )
}


def get_weixin_profile(version: str) -> WeixinProfile:
    try:
        return _PROFILES[version]
    except KeyError as exc:
        raise UnsupportedWeixinVersion(
            f"unsupported Weixin version: {version}"
        ) from exc

