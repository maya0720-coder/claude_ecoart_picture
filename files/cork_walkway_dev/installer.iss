; Inno Setup 6 설치 스크립트 (모듈 11). build_windows.bat가 iscc로 컴파일한다(사용자 검토 후).
; 사용자 단위 설치: 관리자 권한 불필요, %LOCALAPPDATA%\Programs\CorkWalkway 에 설치.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "시공 시뮬레이터"
#define AppExe "CorkWalkway.exe"

[Setup]
AppId={{6F1C2B7E-3D4A-4E8B-9C21-5B7A0D3E9F14}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=CorkWalkway
DefaultDirName={autopf}\CorkWalkway
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=CorkWalkway-{#AppVersion}-setup
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "dist\CorkWalkway\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} 제거"; Filename: "{uninstallexe}"
; 바탕화면 바로가기는 항상 만든다. {autodesktop}은 설치하는 PC·사용자의 실제 바탕화면 경로(OneDrive 리디렉션 포함)로 풀린다.
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "지금 실행"; Flags: nowait postinstall skipifsilent

; 사용자 설정·로그(%APPDATA%\CorkWalkway)와 저장한 결과물은 제거할 때 지우지 않는다.
; API 키는 Windows 자격 증명 관리자에 남으므로, 지우려면 앱 설정에서 [키 삭제]를 먼저 누른다.
