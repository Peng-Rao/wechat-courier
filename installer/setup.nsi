; ═══════════════════════════════════════════
;  福格微信助手 NSIS 安装脚本
; ═══════════════════════════════════════════

!include "MUI2.nsh"
!include "FileFunc.nsh"

; ── 基本信息 ──
!define PRODUCT_NAME "福格微信助手"
!define PRODUCT_VERSION "1.0.0"
!ifndef PRODUCT_ICON_NAME
!define PRODUCT_ICON_NAME "fuge-icon-${PRODUCT_VERSION}.ico"
!endif
!define OLD_PRODUCT_NAME "五阿哥群发助手"
!define OLD_ASSISTANT_NAME "五阿哥微信助手"
!define PRODUCT_PUBLISHER "wx4py"
!define PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\${PRODUCT_NAME}.exe"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
!define OLD_PRODUCT_DIR_REGKEY "Software\Microsoft\Windows\CurrentVersion\App Paths\${OLD_PRODUCT_NAME}.exe"
!define OLD_PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${OLD_PRODUCT_NAME}"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "..\dist\${PRODUCT_NAME}_Setup.exe"
InstallDir "$PROGRAMFILES\${PRODUCT_NAME}"
InstallDirRegKey HKLM "${PRODUCT_DIR_REGKEY}" ""
RequestExecutionLevel admin
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUnInstDetails show

; ── 界面设置 ──
!define MUI_ABORTWARNING
!define MUI_ICON "..\assets\app.ico"
!define MUI_UNICON "..\assets\app.ico"

; ── 安装页面 ──
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "license.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; ── 卸载页面 ──
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

; Only remove known binaries from a registered installation of this product.
!macro MigrateLegacyProduct LEGACY_NAME
    ReadRegStr $0 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${LEGACY_NAME}" "InstallLocation"
    ReadRegStr $1 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${LEGACY_NAME}" "DisplayName"
    StrCmp $1 "${LEGACY_NAME}" 0 migration_done_${LEGACY_NAME}
    StrCmp $0 "" migration_done_${LEGACY_NAME}
    IfFileExists "$0\${LEGACY_NAME}.exe" 0 migration_done_${LEGACY_NAME}
    Delete "$0\${LEGACY_NAME}.exe"
    Delete "$0\wechat-agent.exe"
    Delete "$0\uninst.exe"
    ; Preserve unrecognized files and HKCU settings in the old installation.
    RMDir "$0"
    Delete "$DESKTOP\${LEGACY_NAME}.lnk"
    Delete "$SMPROGRAMS\${LEGACY_NAME}\${LEGACY_NAME}.lnk"
    Delete "$SMPROGRAMS\${LEGACY_NAME}\卸载.lnk"
    RMDir "$SMPROGRAMS\${LEGACY_NAME}"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${LEGACY_NAME}"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\App Paths\${LEGACY_NAME}.exe"
    migration_done_${LEGACY_NAME}:
!macroend

Function .onInit
    ; Close both product generations before replacing binaries.
    nsExec::ExecToLog 'taskkill /F /IM "${PRODUCT_NAME}.exe"'
    nsExec::ExecToLog 'taskkill /F /IM "${OLD_PRODUCT_NAME}.exe"'
    nsExec::ExecToLog 'taskkill /F /IM "${OLD_ASSISTANT_NAME}.exe"'
    nsExec::ExecToLog 'taskkill /F /IM "wechat-agent.exe"'
FunctionEnd

; ── 安装区段 ──
Section "Install"
    !insertmacro MigrateLegacyProduct "${OLD_PRODUCT_NAME}"
    !insertmacro MigrateLegacyProduct "${OLD_ASSISTANT_NAME}"

    SetOutPath "$INSTDIR"

    ; 拷贝 PyInstaller 打包后的全部文件
    File /r "..\dist\${PRODUCT_NAME}\*.*"
    ; A content-addressed path avoids reusing the old executable icon cache.
    File "/oname=${PRODUCT_ICON_NAME}" "..\assets\app.ico"

    ; 桌面快捷方式
    CreateShortCut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\${PRODUCT_NAME}.exe" "" "$INSTDIR\${PRODUCT_ICON_NAME}" 0

    ; 开始菜单
    CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" "$INSTDIR\${PRODUCT_NAME}.exe" "" "$INSTDIR\${PRODUCT_ICON_NAME}" 0
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\卸载.lnk" "$INSTDIR\uninst.exe"
    System::Call 'shell32::SHChangeNotify(i 0x00002000, i 0x00001005, w "$DESKTOP\${PRODUCT_NAME}.lnk", p 0)'
    System::Call 'shell32::SHChangeNotify(i 0x00002000, i 0x00001005, w "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk", p 0)'
    System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0x00000000, p 0, p 0)'

    ; 注册表
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninst.exe"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\${PRODUCT_ICON_NAME}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoModify" 1
    WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoRepair" 1
    WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "" "$INSTDIR\${PRODUCT_NAME}.exe"

    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "EstimatedSize" "$0"

    WriteUninstaller "$INSTDIR\uninst.exe"
SectionEnd

; ── 卸载区段 ──
Section "Uninstall"
    RMDir /r "$INSTDIR"
    Delete "$DESKTOP\${PRODUCT_NAME}.lnk"
    Delete "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk"
    Delete "$SMPROGRAMS\${PRODUCT_NAME}\卸载.lnk"
    RMDir "$SMPROGRAMS\${PRODUCT_NAME}"
    DeleteRegKey HKLM "${PRODUCT_UNINST_KEY}"
    DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
SectionEnd
