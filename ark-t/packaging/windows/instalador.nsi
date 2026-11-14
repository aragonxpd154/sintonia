; Instalador do Ark-T para Windows (NSIS 3).
; Instala por usuário, sem pedir administrador, em %LOCALAPPDATA%\Programs\Ark-T.
; Gerado por construir-windows.sh: makensis -DVERSAO=x.y.z -DORIGEM=<pasta> -DSAIDA=<exe> instalador.nsi

Unicode true
SetCompressor /SOLID lzma
RequestExecutionLevel user

!include "MUI2.nsh"

!ifndef VERSAO
  !define VERSAO "0.0.0"
!endif
!define NOME "Ark-T"
!define CHAVE "Software\Microsoft\Windows\CurrentVersion\Uninstall\io.github.aragonxpd154.ArkT"

Name "${NOME} ${VERSAO}"
OutFile "${SAIDA}"
InstallDir "$LOCALAPPDATA\Programs\${NOME}"
InstallDirRegKey HKCU "${CHAVE}" "InstallLocation"
BrandingText "${NOME} ${VERSAO}"

VIProductVersion "${VERSAO}.0"
VIAddVersionKey /LANG=1046 "ProductName" "${NOME}"
VIAddVersionKey /LANG=1046 "FileDescription" "Instalador do ${NOME}"
VIAddVersionKey /LANG=1046 "FileVersion" "${VERSAO}"
VIAddVersionKey /LANG=1046 "ProductVersion" "${VERSAO}"
VIAddVersionKey /LANG=1046 "CompanyName" "Marcos Santos"
VIAddVersionKey /LANG=1046 "LegalCopyright" "MIT"

!define MUI_ICON "${ORIGEM}\Ark-T.ico"
!define MUI_UNICON "${ORIGEM}\Ark-T.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\Ark-T.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Abrir o Ark-T agora"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${ORIGEM}\LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

Section "Ark-T" SecPrincipal
  SectionIn RO
  ; remove a versão anterior do runtime para não misturar DLLs
  RMDir /r "$INSTDIR\runtime"
  SetOutPath "$INSTDIR"
  File /r "${ORIGEM}\*.*"
  WriteUninstaller "$INSTDIR\Desinstalar.exe"

  CreateDirectory "$SMPROGRAMS\${NOME}"
  CreateShortcut "$SMPROGRAMS\${NOME}\${NOME}.lnk" "$INSTDIR\Ark-T.exe" "" "$INSTDIR\Ark-T.ico"

  CreateShortcut "$SMPROGRAMS\${NOME}\Desinstalar ${NOME}.lnk" "$INSTDIR\Desinstalar.exe"
  CreateShortcut "$DESKTOP\${NOME}.lnk" "$INSTDIR\Ark-T.exe" "" "$INSTDIR\Ark-T.ico"

  WriteRegStr HKCU "${CHAVE}" "DisplayName" "${NOME}"
  WriteRegStr HKCU "${CHAVE}" "DisplayVersion" "${VERSAO}"
  WriteRegStr HKCU "${CHAVE}" "Publisher" "Marcos Santos"
  WriteRegStr HKCU "${CHAVE}" "URLInfoAbout" "https://github.com/aragonxpd154/sintonia/tree/main/ark-t"
  WriteRegStr HKCU "${CHAVE}" "DisplayIcon" "$INSTDIR\Ark-T.ico"
  WriteRegStr HKCU "${CHAVE}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${CHAVE}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegDWORD HKCU "${CHAVE}" "NoModify" 1
  WriteRegDWORD HKCU "${CHAVE}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${NOME}.lnk"
  RMDir /r "$SMPROGRAMS\${NOME}"
  RMDir /r "$INSTDIR\runtime"
  Delete "$INSTDIR\Ark-T.exe"
  Delete "$INSTDIR\Ark-T.ico"
  Delete "$INSTDIR\Ark-T-depuracao.bat"
  Delete "$INSTDIR\LICENSE.txt"
  Delete "$INSTDIR\NOTICE.txt"
  Delete "$INSTDIR\LEIA-ME.txt"
  Delete "$INSTDIR\Desinstalar.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${CHAVE}"
SectionEnd
