; Reverie Studio v32 - Inno Setup Script
; Inno Setup 6.x 이상 필요
; 빌드 전 필수: dist 폴더에 Nuitka 빌드 결과물이 있어야 함

#define MyAppName "Reverie Studio"
#define MyAppVersion "32.0"
#define MyAppPublisher "Reverie Studio"
#define MyAppURL "https://reverie.studio"
#define MyAppExeName "ReverieAutomation.exe"
#define MyAppCopyright "Copyright 2024-2026 Reverie Studio"

[Setup]
; 고유 앱 ID (변경하지 마세요)
AppId={{B2C3D4E5-F6A7-8901-BCDE-F23456789012}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
AppCopyright={#MyAppCopyright}

; 설치 경로 설정
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; 출력 설정
OutputDir=..\dist_installer
OutputBaseFilename=Reverie_Studio_v{#MyAppVersion}_Setup
; SetupIconFile=..\assets\icon.ico
Compression=lzma2/fast
SolidCompression=no
LZMANumBlockThreads=2

; 디스크 스패닝 (대용량 설치 파일용)
DiskSpanning=no

; 권한 설정
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; 설치 마법사 스타일
WizardStyle=modern
WizardSizePercent=120,120
WizardResizable=yes

; 언어 선택 다이얼로그
ShowLanguageDialog=auto

; 설치 정보
InfoBeforeFile=..\INSTALL_INFO.txt
; LicenseFile=..\LICENSE.txt

; 최소 Windows 버전 (Windows 10)
MinVersion=10.0

; 설치 로그
SetupLogging=yes

; 압축 해제 진행률 표시
ShowUndisplayableLanguages=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
korean.BeveledLabel=Reverie Studio v32 - AI 영상 자동 제작
english.BeveledLabel=Reverie Studio v32 - AI Video Automation
korean.WelcomeLabel1=Reverie Studio v32 설치 마법사
korean.WelcomeLabel2=AI 기반 유튜브 영상 자동 제작 프로그램을 설치합니다.%n%n설치 전 다른 프로그램을 모두 종료하는 것을 권장합니다.
english.WelcomeLabel1=Reverie Studio v32 Setup Wizard
english.WelcomeLabel2=This will install the AI-powered YouTube video automation tool.%n%nIt is recommended to close all other applications before continuing.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode

[Files]
; ============================================================================
; 메인 실행 파일 및 DLL (Nuitka standalone 빌드 결과물)
; ============================================================================
Source: "..\dist\main_gui.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; ============================================================================
; TTS 음성 모델 (필수 - 약 1.4GB)
; ============================================================================
; Horror 나레이터 모델
Source: "..\assets\models\horror\narrator\*"; DestDir: "{app}\assets\models\horror\narrator"; Flags: ignoreversion recursesubdirs createallsubdirs

; Senior 시리즈 모델 (5개 캐릭터)
Source: "..\assets\models\senior\grandma\*"; DestDir: "{app}\assets\models\senior\grandma"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\assets\models\senior\grandpa\*"; DestDir: "{app}\assets\models\senior\grandpa"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\assets\models\senior\man\*"; DestDir: "{app}\assets\models\senior\man"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\assets\models\senior\woman\*"; DestDir: "{app}\assets\models\senior\woman"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\assets\models\senior\narrator\*"; DestDir: "{app}\assets\models\senior\narrator"; Flags: ignoreversion recursesubdirs createallsubdirs

; 음성 메타데이터
Source: "..\assets\models\senior\voice_metadata.json"; DestDir: "{app}\assets\models\senior"; Flags: ignoreversion

; ============================================================================
; BGM 파일 (약 254MB)
; ============================================================================
Source: "..\assets\bgm\horror\*"; DestDir: "{app}\assets\bgm\horror"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\assets\bgm\senior\*"; DestDir: "{app}\assets\bgm\senior"; Flags: ignoreversion recursesubdirs createallsubdirs

; ============================================================================
; 유저 매뉴얼
; ============================================================================
Source: "..\USER_MANUAL_DIST.txt"; DestDir: "{app}"; DestName: "사용자 매뉴얼.txt"; Flags: ignoreversion

; ============================================================================
; 제외 항목 (설치에 포함하지 않음)
; ============================================================================
; - assets\intro\      (채널 전용 인트로)
; - assets\outro\      (채널 전용 아웃트로)
; - assets\fonts\      (저작권 이슈)
; - firebase_credentials.json (관리자 전용)
; - license_generator*.py (관리자 전용)
; - .env 파일 (API 키)

[Dirs]
; 런타임에 필요한 폴더 구조 생성
Name: "{app}\data"
Name: "{app}\data\outputs"
Name: "{app}\data\scripts"
Name: "{app}\data\temp_audio"
Name: "{app}\data\temp_images"
Name: "{app}\data\thumbnails"
Name: "{app}\config"
Name: "{app}\logs"

[Icons]
; 시작 메뉴
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "AI 영상 자동 제작"
Name: "{group}\사용자 매뉴얼"; Filename: "{app}\사용자 매뉴얼.txt"; Comment: "사용 설명서"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

; 바탕화면
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "AI 영상 자동 제작"

; 빠른 실행
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
; 설치 후 실행 옵션
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\사용자 매뉴얼.txt"; Description: "사용자 매뉴얼 열기"; Flags: nowait postinstall skipifsilent shellexec unchecked

[UninstallDelete]
; 삭제 시 제거할 항목 (사용자 데이터는 유지)
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\data\temp_audio"
Type: filesandordirs; Name: "{app}\data\temp_images"
Type: dirifempty; Name: "{app}\data"
Type: dirifempty; Name: "{app}"

[Code]
// ============================================================================
// 설치 초기화
// ============================================================================
function InitializeSetup(): Boolean;
var
  OldVersion: String;
begin
  Result := True;

  // 기존 버전 확인 (업그레이드 안내)
  if RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1',
    'DisplayVersion', OldVersion) then
  begin
    if MsgBox('Reverie Studio ' + OldVersion + ' 버전이 이미 설치되어 있습니다.' + #13#10 +
              '새 버전으로 업그레이드하시겠습니까?', mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
    end;
  end;
end;

// ============================================================================
// 설치 단계별 처리
// ============================================================================
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // 설치 완료 후 처리
    // 예: 초기 설정 파일 생성
  end;
end;

// ============================================================================
// 설치 취소 확인
// ============================================================================
procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if CurPageID = wpInstalling then
  begin
    Confirm := True;
  end;
end;

// ============================================================================
// 필요 디스크 공간 계산 (약 2GB)
// ============================================================================
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  // 디스크 공간은 Inno Setup이 자동으로 확인합니다
end;
