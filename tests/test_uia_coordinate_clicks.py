from __future__ import annotations

import pytest

from src.core import uiautomation as uia


@pytest.mark.parametrize(
    ("action", "down", "up"),
    [
        (uia.Click, uia.MouseEventFlag.LeftDown, uia.MouseEventFlag.LeftUp),
        (uia.MiddleClick, uia.MouseEventFlag.MiddleDown, uia.MouseEventFlag.MiddleUp),
        (uia.RightClick, uia.MouseEventFlag.RightDown, uia.MouseEventFlag.RightUp),
    ],
)
def test_coordinate_clicks_do_not_reinterpret_negative_virtual_screen_positions(
    monkeypatch, action, down, up
):
    events = []
    monkeypatch.setattr(
        uia, "SetCursorPos", lambda x, y: events.append(("move", x, y)) or True
    )
    monkeypatch.setattr(uia, "GetCursorPos", lambda: (-684, 220))
    monkeypatch.setattr(
        uia,
        "mouse_event",
        lambda flags, dx, dy, data, extra: events.append(
            ("mouse", flags, dx, dy, data, extra)
        ),
    )
    monkeypatch.setattr(uia.time, "sleep", lambda _seconds: None)

    action(-684, 220, waitTime=0)

    assert events == [
        ("move", -684, 220),
        ("mouse", down, 0, 0, 0, 0),
        ("mouse", up, 0, 0, 0, 0),
    ]


def test_coordinate_click_refuses_to_press_when_cursor_move_fails(monkeypatch):
    events = []
    monkeypatch.setattr(uia, "SetCursorPos", lambda _x, _y: False)
    monkeypatch.setattr(
        uia,
        "mouse_event",
        lambda *args: events.append(args),
    )

    with pytest.raises(RuntimeError, match="cursor"):
        uia.Click(-684, 220, waitTime=0)

    assert events == []
