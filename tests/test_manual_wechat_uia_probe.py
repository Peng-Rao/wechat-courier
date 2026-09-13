# -*- coding: utf-8 -*-
"""Unit coverage for the manual WeChat 4.1 UIA probe."""

from dataclasses import dataclass
import sys

import pytest

from tests.manual_wechat_uia_probe import (
    GateResolutionError,
    ProbeError,
    REPO_ROOT,
    find_named_control,
    resolve_friend_form_fields,
    resolve_gate_rva,
    validate_request_values,
)


@dataclass
class FakeControl:
    Name: str
    ControlTypeName: str
    IsEnabled: bool = True


def test_direct_script_bootstrap_adds_the_repository_root_to_sys_path():
    assert str(REPO_ROOT) in sys.path


def test_resolve_gate_rva_rejects_unverified_wechat_versions():
    assert resolve_gate_rva("4.1.13.65") == 0x0AE2B0C8

    with pytest.raises(GateResolutionError, match="unsupported Weixin version"):
        resolve_gate_rva("4.1.14.1")


def test_find_named_control_requires_an_exact_navigation_label():
    unsafe_submit = FakeControl("发送添加朋友申请", "ButtonControl")
    exact_navigation = FakeControl("添加朋友", "ButtonControl")

    found = find_named_control(
        [(unsafe_submit, 3), (exact_navigation, 4)],
        ("添加朋友", "添加好友"),
    )

    assert found is exact_navigation


def test_find_named_control_ignores_disabled_and_noninteractive_matches():
    disabled = FakeControl("新的朋友", "ButtonControl", IsEnabled=False)
    text_only = FakeControl("新的朋友", "TextControl")
    clickable = FakeControl("新的朋友", "ListItemControl")

    found = find_named_control(
        [(disabled, 2), (text_only, 2), (clickable, 3)],
        ("新的朋友",),
    )

    assert found is clickable


def test_resolve_friend_form_fields_uses_exact_edit_names():
    unrelated = FakeControl("搜索", "EditControl")
    greeting = FakeControl("发送添加朋友申请", "EditControl")
    remark = FakeControl("修改备注", "EditControl")

    found_greeting, found_remark = resolve_friend_form_fields(
        [(unrelated, 2), (greeting, 4), (remark, 4)]
    )

    assert found_greeting is greeting
    assert found_remark is remark


def test_submit_requires_all_explicit_request_values():
    with pytest.raises(ProbeError, match="--wechat-id"):
        validate_request_values(None, "你好", "测试备注", submit=True)
    with pytest.raises(ProbeError, match="--greeting"):
        validate_request_values("wxid_test", None, "测试备注", submit=True)
    with pytest.raises(ProbeError, match="--remark"):
        validate_request_values("wxid_test", "你好", None, submit=True)

    validate_request_values("wxid_test", "你好", "测试备注", submit=True)
