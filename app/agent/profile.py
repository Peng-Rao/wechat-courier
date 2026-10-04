from __future__ import annotations

from dataclasses import dataclass


class UnsupportedWeixinVersion(RuntimeError):
    """Raised when no verified automation profile exists for a Weixin build."""


SUPPORTED_WEIXIN_VERSION = "4.1.13.65"


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
    chat_message_list_automation_id: str
    chat_message_classes: tuple[str, ...]
    add_friend_root_class: str
    verify_friend_root_class: str


_PROFILES = {
    SUPPORTED_WEIXIN_VERSION: WeixinProfile(
        version=SUPPORTED_WEIXIN_VERSION,
        gate_rva=0x0AE2B0C8,
        main_root_class="mmui::MainWindow",
        search_edit_name="搜索",
        search_edit_class="mmui::XValidatorTextEdit",
        search_popup_class="mmui::XPopover",
        search_list_automation_id="search_list",
        chat_input_automation_id="chat_input_field",
        chat_input_class="mmui::ChatInputField",
        chat_message_list_automation_id="chat_message_list",
        chat_message_classes=(
            "mmui::ChatTextItemView",
            "mmui::ChatBubbleItemView",
            "mmui::ChatFileItemView",
            "mmui::ChatBubbleReferItemView",
        ),
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
