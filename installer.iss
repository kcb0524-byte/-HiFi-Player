; ═══════════════════════════════════════════════════════════════
;  니콘 친게 HiFi Music Player — Inno Setup 6 스크립트
;  build_windows.bat 에서 자동 호출됨
;  또는 Inno Setup IDE에서 직접 컴파일 가능
; ═══════════════════════════════════════════════════════════════

#define AppName    "니콘 친게 HiFi Player"
#define AppNameKor "니콘 친게 HiFi Player"
#define AppVersion "1.0.0"
#define AppPublisher "TW Semicon"
#define AppURL     "https://github.com/kcb0524/nikon-chinge-hifi-player"
#define AppExeName "니콘 친게 HiFi Player.exe"
#define SourceDir  "dist\니콘 친게 HiFi Player"

[Setup]
AppId={{A8F3D241-7C2E-4B9F-83A1-5E6C9D0B2F4E}
AppName={#AppNameKor}
AppVersion={#AppVersion}
AppVerName={#AppNameKor} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppNameKor}
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=니콘_친게_HiFi_Player_Setup_{#AppVersion}
SetupIconFile=icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Windows 10/11 이상 필요
MinVersion=10.0
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startmenuicon"; Description: "시작 메뉴에 추가"; GroupDescription: "아이콘 설정"; Flags: checkedonce

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppNameKor}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppNameKor}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppNameKor}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppNameKor}}"; Flags: nowait postinstall skipifsilent

[Registry]
; 오디오 파일 연결 (선택)
Root: HKCU; Subkey: "Software\Classes\.flac\OpenWithProgids"; ValueType: string; ValueName: "HiFiPlayer.flac"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\HiFiPlayer.flac"; ValueType: string; ValueName: ""; ValueData: "FLAC Audio File"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\HiFiPlayer.flac\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\HiFiPlayer"
