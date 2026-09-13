# -*- coding: utf-8 -*-
"""Static checks for the QML window shell contract.

These tests complement qmltestrunner coverage: they guard the architectural
shape that prevents native titlebars and duplicate glass layers from returning.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_qml(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_main_window_uses_frameless_custom_titlebar():
    qml = read_qml("qml/main.qml")
    main_py = read_qml("main.py")

    assert "Qt.FramelessWindowHint" in qml
    assert "WxTitleBar" in qml
    assert "startSystemResize" in qml
    assert "install_frameless_window_hit_test" in main_py


def test_main_window_exposes_snap_and_fullscreen_contract():
    qml = read_qml("qml/main.qml")

    for token in (
        "function applySnapMode",
        "function centerAndRestore",
        "function toggleFullScreenPreview",
        "function enterFullScreenPreview",
        "Shortcut",
        "F11",
        "Esc",
    ):
        assert token in qml

    for unsafe_token in (
        "property string snapPreviewMode",
        "function beginTitleBarDrag",
        "function updateTitleBarDrag",
        "function finishTitleBarDrag",
        "WindowTransparentForInput",
        "snapPreviewWindow",
    ):
        assert unsafe_token not in qml


def test_titlebar_exposes_window_layout_controls():
    title_bar = read_qml("qml/components/WxTitleBar.qml")

    for token in (
        "startSystemMove",
        "layoutMenu",
        "applySnapMode(\"left\")",
        "applySnapMode(\"right\")",
        "centerAndRestore",
        "enterFullScreenPreview",
    ):
        assert token in title_bar

    for unsafe_token in (
        "DragHandler",
        "beginTitleBarDrag",
        "updateTitleBarDrag",
        "finishTitleBarDrag",
    ):
        assert unsafe_token not in title_bar


def test_titlebar_layout_menu_is_explicit_and_right_anchored():
    title_bar = read_qml("qml/components/WxTitleBar.qml")

    assert "layoutMenuOpen" in title_bar
    assert "mouse.button === Qt.RightButton" in title_bar
    assert "anchors.right: parent.right" in title_bar
    assert "maxButton.mapToItem(root" not in title_bar


def test_visual_controls_live_only_in_settings_dialog():
    tab_bar = read_qml("qml/components/WxTabBar.qml")
    title_bar = read_qml("qml/components/WxTitleBar.qml")
    settings = read_qml("qml/components/SettingsDialog.qml")

    assert "WxTheme.isDark = !WxTheme.isDark" not in tab_bar
    assert "glassControl" not in title_bar
    assert "themeToggleBtn" not in title_bar
    assert "毛玻璃" not in title_bar
    assert "颜色模式" in settings
    assert "毛玻璃背景" in settings
    assert "毛玻璃透明度" in settings
    assert "wheelEnabled: true" in settings


def test_theme_defines_single_glass_surface_tokens():
    theme = read_qml("qml/theme/WxTheme.qml")

    for token in (
        "glassEnabled",
        "glassOpacity",
        "clWindowTint",
        "clTitleBarBg",
        "clSurface",
        "clSurfaceStrong",
        "clInputBg",
        "clGlassDivider",
        "clPanelFill",
        "clFieldFill",
        "clToolbarFill",
        "clDropZoneFill",
        "clSurfaceBorder",
        "clSurfaceHighlight",
        "clFocusRing",
    ):
        assert token in theme


def test_glass_surface_component_exists_and_stays_lightweight():
    surface = read_qml("qml/components/WxGlassSurface.qml")

    for prop in (
        "property color fillColor",
        "property color borderColor",
        "property bool focused",
        "property bool highlightEnabled",
        "radius: WxTheme.radiusMedium",
    ):
        assert prop in surface

    assert "Qt5Compat.GraphicalEffects" not in surface
    assert "DropShadow" not in surface


def test_red_box_surfaces_use_role_based_material_tokens():
    input_panel = read_qml("qml/components/InputPanel.qml")
    chat_preview = read_qml("qml/components/ChatPreview.qml")
    action_bar = read_qml("qml/components/ActionBar.qml")
    status_bar = read_qml("qml/components/StatusBar.qml")

    assert "WxGlassSurface" in input_panel
    assert "clFieldFill" in input_panel
    assert "clDropZoneFill" in input_panel
    assert "clFocusRing" in input_panel

    assert "clToolbarFill" in chat_preview
    assert "clPanelFill" in chat_preview
    assert "clSurfaceBorder" in chat_preview

    assert "clToolbarFill" in action_bar
    assert "clSurfaceBorder" in action_bar
    assert "clToolbarFill" in status_bar

    assert "clSurfaceStrong" not in chat_preview
    assert "clSurfaceStrong" not in action_bar
    assert "clSurfaceStrong" not in status_bar
