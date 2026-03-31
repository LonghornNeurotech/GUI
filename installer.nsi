; ── NeuroTechGUI NSIS Installer ──────────────────────────────────────────────
; Compile with:  makensis /DVERSION=<build_number> /DDIST_PATH=dist installer.nsi
; Example:       makensis /DVERSION=42 /DDIST_PATH=dist installer.nsi

!include "MUI2.nsh"
!include "FileFunc.nsh"

; ── Defaults for defines passed on the command line ─────────────────────────
!ifndef VERSION
  !define VERSION "0"
!endif
!ifndef DIST_PATH
  !define DIST_PATH "dist"
!endif

; ── Application metadata ───────────────────────────────────────────────────
Name "Longhorn Neural Interface Platform"
OutFile "LonghornNeuralInterface_Windows_Setup.exe"
InstallDir "$PROGRAMFILES\NeuroTechGUI"
InstallDirRegKey HKLM "Software\NeuroTechGUI" "InstallPath"
RequestExecutionLevel admin

; Version info embedded in the executable
VIProductVersion "1.${VERSION}.0.0"
VIAddVersionKey "ProductName" "NeuroTechGUI"
VIAddVersionKey "FileDescription" "Longhorn Neural Interface Platform Installer"
VIAddVersionKey "FileVersion" "1.${VERSION}.0.0"
VIAddVersionKey "LegalCopyright" "LonghornNeurotech"

; ── MUI settings ───────────────────────────────────────────────────────────
!define MUI_ABORTWARNING
; Use icon.ico if present; the CI step converts icon.png -> icon.ico
!if /FileExists "icon.ico"
  !define MUI_ICON "icon.ico"
  !define MUI_UNICON "icon.ico"
!endif

; Installer pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; Uninstaller pages
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ── Install section ────────────────────────────────────────────────────────
Section "MainProgram" SEC_MAIN
    SetOutPath "$INSTDIR"

    ; Remove old application executables to prevent version conflicts on upgrade
    Delete "$INSTDIR\LonghornNeuralInterface_*.exe"

    ; Copy the PyInstaller executable (and any other dist files)
    File "${DIST_PATH}\*.exe"

    ; Copy icon if available
    !if /FileExists "icon.ico"
      File "icon.ico"
    !endif

    ; Write uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"

    ; ── Start-menu shortcuts ──
    CreateDirectory "$SMPROGRAMS\NeuroTechGUI"
    ; Find the actual exe inside $INSTDIR (name varies by build number)
    FindFirst $0 $1 "$INSTDIR\LonghornNeuralInterface_*.exe"
    StrCmp $1 "" NoExeFound
        Delete "$DESKTOP\NeuroTechGUI.lnk"
        Delete "$SMPROGRAMS\NeuroTechGUI\NeuroTechGUI.lnk"
        CreateShortCut "$SMPROGRAMS\NeuroTechGUI\NeuroTechGUI.lnk" "$INSTDIR\$1"
        CreateShortCut "$DESKTOP\NeuroTechGUI.lnk" "$INSTDIR\$1"
        ; Store the exe name for the updater
        WriteRegStr HKLM "Software\NeuroTechGUI" "ExecutableName" "$1"
    NoExeFound:
    FindClose $0

    ; ── Registry: Add/Remove Programs ──
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NeuroTechGUI" \
        "DisplayName" "Longhorn Neural Interface Platform v1.${VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NeuroTechGUI" \
        "UninstallString" '"$INSTDIR\uninstall.exe"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NeuroTechGUI" \
        "DisplayVersion" "1.${VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NeuroTechGUI" \
        "Publisher" "LonghornNeurotech"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NeuroTechGUI" \
        "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NeuroTechGUI" \
        "NoRepair" 1
    !if /FileExists "icon.ico"
      WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NeuroTechGUI" \
          "DisplayIcon" "$INSTDIR\icon.ico"
    !endif

    ; App-specific registry
    WriteRegStr HKLM "Software\NeuroTechGUI" "InstallPath" "$INSTDIR"
    WriteRegStr HKLM "Software\NeuroTechGUI" "Version" "${VERSION}"

    ; Calculate and store install size
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NeuroTechGUI" \
        "EstimatedSize" $0
SectionEnd

; ── Uninstall section ──────────────────────────────────────────────────────
Section "Uninstall"
    ; Remove installed files
    RMDir /r "$INSTDIR"

    ; Remove shortcuts
    Delete "$DESKTOP\NeuroTechGUI.lnk"
    RMDir /r "$SMPROGRAMS\NeuroTechGUI"

    ; Remove registry entries
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\NeuroTechGUI"
    DeleteRegKey HKLM "Software\NeuroTechGUI"
SectionEnd

; ── .onInit: handle upgrades ───────────────────────────────────────────────
Function .onInit
    ; If already installed, offer to upgrade
    ReadRegStr $0 HKLM "Software\NeuroTechGUI" "InstallPath"
    StrCmp $0 "" done
        MessageBox MB_OKCANCEL|MB_ICONINFORMATION \
            "NeuroTechGUI is already installed at:$\n$\n$0$\n$\nClick OK to upgrade to v1.${VERSION}, or Cancel to abort." \
            IDOK done
        Abort
    done:
FunctionEnd
