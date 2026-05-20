; Reverie Automation - Inno Setup Script
; 이 파일은 Inno Setup 6.x용입니다

#define MyAppName "Reverie Automation"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Reverie Studio"
#define MyAppURL "https://reverie.studio"
#define MyAppExeName "ReverieAutomation.exe"

[Setup]
; 기본 설정
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; 설치 경로
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; 출력 설정
OutputDir=..\dist\installer
OutputBaseFilename=ReverieAutomation_Setup_{#MyAppVersion}
SetupIconFile=..\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes

; 권한
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; 언어
ShowLanguageDialog=yes

; 설치 마법사
WizardStyle=modern
WizardSizePercent=120

; 라이센스 (선택사항)
; LicenseFile=..\LICENSE.txt

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode

[Files]
; 메인 실행 파일 및 DLL
Source: "..\dist\ReverieAutomation\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; 설정 파일 (config 폴더)
; Source: "..\config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "firebase_credentials.json,*.pyc"

; 데이터 폴더 (빈 폴더 구조)
; Source: "..\data\*"; DestDir: "{app}\data"; Flags: ignoreversion recursesubdirs createallsubdirs onlyifdoesntexist

[Dirs]
; 사용자 데이터 폴더 생성
Name: "{app}\data"
Name: "{app}\data\logs"
Name: "{app}\config"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 설치 제거 시 로그 파일 삭제
Type: filesandordirs; Name: "{app}\data\logs"

[Code]
// 커스텀 코드 (필요시)

function InitializeSetup(): Boolean;
begin
  Result := True;
  // 이전 버전 확인 등
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // 설치 후 작업
  end;
end;

[Messages]
korean.BeveledLabel=Reverie Automation
english.BeveledLabel=Reverie Automation
