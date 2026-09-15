; ═══════════════════════════════════════════
;  五阿哥微信助手 NSIS 安装脚本
; ═══════════════════════════════════════════

!include "MUI2.nsh"
!include "FileFunc.nsh"

; ── 基本信息 ──
!define PRODUCT_NAME "五阿哥微信助手"
!define PRODUCT_VERSION "0.3.3"
!define OLD_PRODUCT_NAME "五阿哥群发助手"
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

Function .onInit
    ; Close both product generations before replacing binaries.
    nsExec::ExecToLog 'taskkill /F /IM "${PRODUCT_NAME}.exe"'
    nsExec::ExecToLog 'taskkill /F /IM "${OLD_PRODUCT_NAME}.exe"'
    nsExec::ExecToLog 'taskkill /F /IM "wechat-agent.exe"'
FunctionEnd

; ── 安装区段 ──
Section "Install"
    ; Remove the previous product shell without touching HKCU wx4py settings.
    Delete "$DESKTOP\${OLD_PRODUCT_NAME}.lnk"
    Delete "$SMPROGRAMS\${OLD_PRODUCT_NAME}\${OLD_PRODUCT_NAME}.lnk"
    Delete "$SMPROGRAMS\${OLD_PRODUCT_NAME}\卸载.lnk"
    RMDir "$SMPROGRAMS\${OLD_PRODUCT_NAME}"
    RMDir /r "$PROGRAMFILES\${OLD_PRODUCT_NAME}"
    DeleteRegKey HKLM "${OLD_PRODUCT_UNINST_KEY}"
    DeleteRegKey HKLM "${OLD_PRODUCT_DIR_REGKEY}"

    SetOutPath "$INSTDIR"

    ; 拷贝 PyInstaller 打包后的全部文件
    File /r "..\dist\${PRODUCT_NAME}\*.*"

    ; 桌面快捷方式
    CreateShortCut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\${PRODUCT_NAME}.exe" "" "$INSTDIR\${PRODUCT_NAME}.exe"

    ; 开始菜单
    CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" "$INSTDIR\${PRODUCT_NAME}.exe" "" "$INSTDIR\${PRODUCT_NAME}.exe"
    CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\卸载.lnk" "$INSTDIR\uninst.exe"

    ; 注册表
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninst.exe"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\${PRODUCT_NAME}.exe"
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
