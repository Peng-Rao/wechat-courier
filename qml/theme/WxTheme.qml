pragma Singleton
import QtQuick

QtObject {
    property bool isDark: false
    property bool glassEnabled: true
    property int glassOpacity: 72

    readonly property real glassRatio: Math.max(45, Math.min(90, glassOpacity)) / 100.0
    readonly property real glassAlpha: glassEnabled ? glassRatio : 1.0

    // ═══════════════════════════════
    //  颜色 — 微信风格
    // ═══════════════════════════════
    readonly property color clPrimary: isDark ? "#00d261" : "#07c160"
    readonly property color clPrimaryHover: isDark ? "#00b553" : "#06ad56"
    readonly property color clPrimaryPress: isDark ? "#009845" : "#059a4c"
    readonly property color clBubbleBg: isDark ? "#2b6a38" : "#95ec69"
    readonly property color clFileCardBg: isDark ? "#24292e" : "#f5f5f5"
    readonly property color clLogOk: isDark ? "#388e3c" : "#2e7d32"
    readonly property color clLogErr: isDark ? "#e53935" : "#c62828"
    readonly property color clTextPrimary: isDark ? "#f0f3f6" : "#191919"
    readonly property color clTextSecondary: isDark ? "#9faab5" : "#666666"
    readonly property color clTextHint: isDark ? "#62707d" : "#999999"
    readonly property color clBgPrimary: isDark ? "#16191c" : "#ffffff"
    readonly property color clBgSecondary: isDark ? "#1f2328" : "#f7f7f7"
    readonly property color clBorder: isDark ? "#2d333b" : "#e5e5e5"
    readonly property color clDivider: isDark ? "#252a30" : "#ededed"
    readonly property color clWarningBg: isDark ? "#332211" : "#fff3e0"
    readonly property color clTooltipBg: isDark ? "#333311" : "#ffffe0"
    readonly property color clDanger: isDark ? "#d9534f" : "#d9534f"
    readonly property color clDangerHover: isDark ? "#c9302c" : "#c9302c"

    // ═══════════════════════════════
    //  Phase 2 新增 — 扩展色彩
    // ═══════════════════════════════
    readonly property color clPrimaryDisabled: isDark ? "#205035" : "#a0e6b9"
    readonly property color clBgWindow: isDark ? "#0d0f12" : "#f5f5f5"
    readonly property color clBgHover: isDark ? "#24292e" : "#f7f7f7"
    readonly property color clBgSelected: isDark ? "#1a3528" : "#e6f7ed"
    readonly property color clBgInput: isDark ? "#202428" : "#f5f5f5"
    readonly property color clBorderFocus: isDark ? "#00d261" : "#07c160"
    readonly property color clBubbleTail: isDark ? "#2b6a38" : "#95ec69"
    readonly property color clTextLink: isDark ? "#6e85b7" : "#576b95"
    readonly property color clToastBg: isDark ? "#2c2d30" : "#4c4c4c"
    readonly property color clToastText: "#ffffff"
    readonly property color clDangerNew: isDark ? "#ff5252" : "#fa5151"
    readonly property color clDangerNewHover: isDark ? "#ff7373" : "#f13e3a"
    readonly property color clWarning: isDark ? "#ffd600" : "#ffc300"
    readonly property color clShadow: isDark ? "#000000" : "#000000"
    readonly property color clInfo: isDark ? "#66aee8" : "#347fba"
    readonly property color clInfoSoft: isDark ? "#1b3040" : "#eaf4fb"
    readonly property color clInfoBorder: isDark ? "#315b78" : "#a9cee7"
    readonly property color clSuccessSoft: isDark ? "#173528" : "#e8f7ef"
    readonly property color clSuccessBorder: isDark ? "#2c6b4b" : "#9bd7b5"
    readonly property color clSuccessText: isDark ? "#68d89a" : "#237a49"
    readonly property color clWarningSoft: isDark ? "#3a2d18" : "#fff5df"
    readonly property color clWarningBorder: isDark ? "#725825" : "#e8c778"
    readonly property color clWarningText: isDark ? "#e7bd62" : "#9b6914"
    readonly property color clDangerSoft: isDark ? "#3a2024" : "#fff0f1"
    readonly property color clNeutralSoft: isDark ? "#293139" : "#edf1f4"
    readonly property color clRowAlternate: isDark ? "#172027" : "#f7fafb"

    // ═══════════════════════════════
    //  Window glass shell tokens
    // ═══════════════════════════════
    readonly property color clWindowTint: glassEnabled
        ? (isDark ? Qt.rgba(0.086, 0.098, 0.110, glassAlpha)
                  : Qt.rgba(1.0, 1.0, 1.0, glassAlpha))
        : clBgWindow
    readonly property color clTitleBarBg: glassEnabled
        ? (isDark ? Qt.rgba(0.095, 0.118, 0.137, Math.max(0.62, glassAlpha - 0.06))
                  : Qt.rgba(1.0, 1.0, 1.0, Math.max(0.58, glassAlpha - 0.10)))
        : clBgPrimary
    readonly property color clSurface: glassEnabled
        ? (isDark ? Qt.rgba(0.086, 0.098, 0.110, 0.40)
                  : Qt.rgba(1.0, 1.0, 1.0, 0.34))
        : clBgPrimary
    readonly property color clSurfaceStrong: glassEnabled
        ? (isDark ? Qt.rgba(0.086, 0.098, 0.110, 0.82)
                  : Qt.rgba(1.0, 1.0, 1.0, 0.78))
        : clBgPrimary
    readonly property color clInputBg: glassEnabled
        ? (isDark ? Qt.rgba(0.055, 0.071, 0.082, 0.88)
                  : Qt.rgba(1.0, 1.0, 1.0, 0.86))
        : clBgInput
    readonly property color clGlassDivider: glassEnabled
        ? (isDark ? Qt.rgba(1.0, 1.0, 1.0, 0.08)
                  : Qt.rgba(0.0, 0.0, 0.0, 0.09))
        : clDivider
    readonly property real panelMaterialAlpha: glassEnabled
        ? Math.max(isDark ? 0.76 : 0.72, Math.min(0.90, glassRatio + 0.08))
        : 1.0
    readonly property real fieldMaterialAlpha: glassEnabled
        ? Math.max(isDark ? 0.88 : 0.87, Math.min(0.96, glassRatio + 0.18))
        : 1.0
    readonly property real toolbarMaterialAlpha: glassEnabled
        ? Math.max(isDark ? 0.80 : 0.79, Math.min(0.94, glassRatio + 0.12))
        : 1.0
    readonly property real dropZoneMaterialAlpha: glassEnabled
        ? Math.max(isDark ? 0.74 : 0.73, Math.min(0.90, glassRatio + 0.10))
        : 1.0
    readonly property color clPanelFill: glassEnabled
        ? (isDark ? Qt.rgba(0.074, 0.086, 0.098, panelMaterialAlpha)
                  : Qt.rgba(1.0, 1.0, 1.0, panelMaterialAlpha))
        : clBgPrimary
    readonly property color clFieldFill: glassEnabled
        ? (isDark ? Qt.rgba(0.050, 0.063, 0.074, fieldMaterialAlpha)
                  : Qt.rgba(1.0, 1.0, 1.0, fieldMaterialAlpha))
        : clBgInput
    readonly property color clToolbarFill: glassEnabled
        ? (isDark ? Qt.rgba(0.070, 0.082, 0.094, toolbarMaterialAlpha)
                  : Qt.rgba(1.0, 1.0, 1.0, toolbarMaterialAlpha))
        : clBgPrimary
    readonly property color clDropZoneFill: glassEnabled
        ? (isDark ? Qt.rgba(0.062, 0.074, 0.086, dropZoneMaterialAlpha)
                  : Qt.rgba(1.0, 1.0, 1.0, dropZoneMaterialAlpha))
        : clBgInput
    readonly property color clSurfaceBorder: glassEnabled
        ? (isDark ? Qt.rgba(1.0, 1.0, 1.0, 0.11)
                  : Qt.rgba(0.0, 0.0, 0.0, 0.10))
        : clBorder
    readonly property color clSurfaceHighlight: glassEnabled
        ? (isDark ? Qt.rgba(1.0, 1.0, 1.0, 0.07)
                  : Qt.rgba(1.0, 1.0, 1.0, 0.55))
        : Qt.rgba(1.0, 1.0, 1.0, 0.0)
    readonly property color clFocusRing: isDark
        ? Qt.rgba(0.0, 0.824, 0.380, 0.12)
        : Qt.rgba(0.027, 0.757, 0.376, 0.14)

    // ═══════════════════════════════
    //  字体
    // ═══════════════════════════════
    readonly property string fontFamily: "Microsoft YaHei"
    readonly property string fontFamilyLog: "Consolas, Cascadia Code, monospace"
    readonly property int fontSizeNormal: 13
    readonly property int fontSizeSmall: 12
    readonly property int fontSizeTiny: 11
    readonly property int fontSizeLog: 12

    // ═══════════════════════════════
    //  圆角
    // ═══════════════════════════════
    readonly property int radiusSmall: 4
    readonly property int radiusMedium: 6
    readonly property int radiusLarge: 8

    // ═══════════════════════════════
    //  间距
    // ═══════════════════════════════
    readonly property int spTiny: 4
    readonly property int spSmall: 8
    readonly property int spMedium: 12
    readonly property int spLarge: 16

    // ═══════════════════════════════
    //  Phase 2 新增 — 动画时长
    // ═══════════════════════════════
    readonly property int animFast: 80
    readonly property int animNormal: 120
    readonly property int animSlow: 200
    readonly property int animProgress: 300

    // ═══════════════════════════════
    //  Phase 2 新增 — 阴影参数（不透明度百分比）
    // ═══════════════════════════════
    readonly property real shadowOpacityLight: 0.04
    readonly property real shadowOpacityMedium: 0.06
    readonly property real shadowOpacityHeavy: 0.12
    readonly property int shadowOffsetY: 2
    readonly property int shadowBlurLight: 8
    readonly property int shadowBlurMedium: 12
    readonly property int shadowBlurHeavy: 16

    // ═══════════════════════════════
    //  Phase 1 (V4) 新增 — 扩展主题常量
    // ═══════════════════════════════
    readonly property color clChatBg: isDark ? "#0d0f12" : "#ebebeb"
    readonly property color clTabActive: isDark ? "#00d261" : "#07c160"
    readonly property color clTabInactive: isDark ? "#7a8b9a" : "#999999"
    readonly property color clProgressTrack: isDark ? "#262b32" : "#e9e9e9"
    readonly property color clSwitchTrackOff: isDark ? "#353c45" : "#dcdfe6"
    readonly property color clSwitchThumb: isDark ? "#f0f3f6" : "#ffffff"

    readonly property int fontSizeXSmall: 10
    readonly property int fontSizeTitle: 15

    readonly property int controlHeight: 28
    readonly property int tabHeight: 36
    readonly property int statusBarHeight: 24
    readonly property int actionBarHeight: 40
    readonly property int chatBubbleMaxWidth: 260
    readonly property int chatFileCardMaxWidth: 220
    readonly property int chatFileCardHeight: 44

    readonly property int spXLarge: 20
}
