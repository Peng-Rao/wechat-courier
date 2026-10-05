import QtQuick
import QtTest
import "../../qml/theme"

TestCase {
    name: "WxTheme"

    function init() {
        WxTheme.isDark = false
        WxTheme.glassEnabled = true
        WxTheme.glassOpacity = 72
    }

    function test_primary_color() {
        compare(WxTheme.clPrimary, "#f87c40")
    }

    function test_primary_hover_color() {
        compare(WxTheme.clPrimaryHover, "#fa8b54")
    }

    function test_bubble_bg_color() {
        compare(WxTheme.clBubbleBg, "#ffffff")
    }

    function test_bg_primary_color() {
        compare(WxTheme.clBgPrimary, "#ffffff")
    }

    function test_bg_secondary_color() {
        compare(WxTheme.clBgSecondary, "#f5f5f7")
    }

    function test_text_primary_color() {
        compare(WxTheme.clTextPrimary, "#25262a")
    }

    function test_text_hint_color() {
        compare(WxTheme.clTextHint, "#8c8d96")
    }

    function test_danger_color() {
        compare(WxTheme.clDanger, "#d9534f")
    }

    function test_font_family() {
        compare(WxTheme.fontFamily, "Microsoft YaHei UI")
    }

    function test_font_size_normal() {
        compare(WxTheme.fontSizeNormal, 14)
    }

    function test_font_size_tiny() {
        compare(WxTheme.fontSizeTiny, 12)
    }

    function test_radius_small() {
        compare(WxTheme.radiusSmall, 4)
    }

    function test_radius_large() {
        compare(WxTheme.radiusLarge, 8)
    }

    function test_spacing_small() {
        compare(WxTheme.spSmall, 8)
    }

    function test_spacing_large() {
        compare(WxTheme.spLarge, 16)
    }

    // Phase 2 新增常量测试
    function test_danger_new_color() {
        compare(WxTheme.clDangerNew, "#cc434b")
    }

    function test_bg_input_color() {
        compare(WxTheme.clBgInput, "#ffffff")
    }

    function test_toast_bg_color() {
        compare(WxTheme.clToastBg, "#4c4c4c")
    }

    function test_anim_fast() {
        compare(WxTheme.animFast, 80)
    }

    function test_anim_slow() {
        compare(WxTheme.animSlow, 200)
    }

    function test_shadow_opacity_medium() {
        compare(WxTheme.shadowOpacityMedium, 0.06)
    }

    // Phase 1 (V4) 新增常量测试
    function test_chat_bg_color() {
        compare(WxTheme.clChatBg, "#f5f5f7")
    }

    function test_tab_active_color() {
        compare(WxTheme.clTabActive, "#f87c40")
    }

    function test_progress_track_color() {
        compare(WxTheme.clProgressTrack, "#e9e9e9")
    }

    function test_switch_track_off_color() {
        compare(WxTheme.clSwitchTrackOff, "#dcdfe6")
    }

    function test_control_height() {
        compare(WxTheme.controlHeight, 36)
    }

    function test_tab_height() {
        compare(WxTheme.tabHeight, 36)
    }

    function test_status_bar_height() {
        compare(WxTheme.statusBarHeight, 24)
    }

    function test_action_bar_height() {
        compare(WxTheme.actionBarHeight, 40)
    }

    function test_chat_bubble_max_width() {
        compare(WxTheme.chatBubbleMaxWidth, 260)
    }

    function test_chat_file_card_max_width() {
        compare(WxTheme.chatFileCardMaxWidth, 220)
    }

    function test_sp_xlarge() {
        compare(WxTheme.spXLarge, 24)
    }

    function test_glass_defaults() {
        compare(WxTheme.glassEnabled, true)
        compare(WxTheme.glassOpacity, 72)
    }

    function test_glass_surface_tokens_exist() {
        verify(WxTheme.clWindowTint !== undefined)
        verify(WxTheme.clTitleBarBg !== undefined)
        verify(WxTheme.clSurface !== undefined)
        verify(WxTheme.clSurfaceStrong !== undefined)
        verify(WxTheme.clInputBg !== undefined)
        verify(WxTheme.clGlassDivider !== undefined)
        verify(WxTheme.clPanelFill !== undefined)
        verify(WxTheme.clFieldFill !== undefined)
        verify(WxTheme.clToolbarFill !== undefined)
        verify(WxTheme.clDropZoneFill !== undefined)
        verify(WxTheme.clSurfaceBorder !== undefined)
        verify(WxTheme.clSurfaceHighlight !== undefined)
        verify(WxTheme.clFocusRing !== undefined)
    }

    function test_glass_material_tokens_keep_readability_floor() {
        WxTheme.glassEnabled = true
        WxTheme.glassOpacity = 45
        WxTheme.isDark = true

        verify(WxTheme.clFieldFill.a >= 0.86)
        verify(WxTheme.clToolbarFill.a >= 0.78)
        verify(WxTheme.clDropZoneFill.a >= 0.72)

        WxTheme.isDark = false
        verify(WxTheme.clFieldFill.a >= 0.86)
        verify(WxTheme.clToolbarFill.a >= 0.78)
        verify(WxTheme.clDropZoneFill.a >= 0.72)
    }

    function test_glass_material_tokens_fallback_when_disabled() {
        WxTheme.glassEnabled = false
        WxTheme.glassOpacity = 45
        WxTheme.isDark = false

        compare(WxTheme.clPanelFill, WxTheme.clBgPrimary)
        compare(WxTheme.clFieldFill, WxTheme.clBgInput)
        compare(WxTheme.clToolbarFill, WxTheme.clBgPrimary)
        compare(WxTheme.clDropZoneFill, WxTheme.clBgSecondary)
    }
}
