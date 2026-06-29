; Music Outo 설치 스크립트 (Inno Setup)
; 빌드: GitHub Actions 가 v*.*.* 태그 push 시 PyInstaller 빌드 후 자동 실행 (installer.yml 참조)
;
; 새 구조:
;   - PyInstaller 가 dist/music-outo/ 안에 단일 실행 환경 생성 (music-outo.exe + 의존 dll)
;   - Inno Setup 이 그 폴더를 그대로 패키징
;   - Docker / WSL / Python / Node 의존 0개

#define MyAppName "Music Outo"
#define MyAppVersion GetEnv("APP_VERSION")
#if MyAppVersion == ""
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppPublisher "Eileen42"
#define MyAppURL "https://github.com/Eileen42/music-outo"
#define MyAppExeName "music-outo.exe"

[Setup]
AppId={{C7A6E7F1-3F8E-4E3B-9B2C-8A5F2A9D4E1C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={userpf}\music-outo
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=music-outo-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면 아이콘 만들기"; GroupDescription: "추가 아이콘:"
Name: "autostart"; Description: "PC 시작 시 자동 실행"; GroupDescription: "자동화:"; Flags: unchecked

[Files]
; PyInstaller 가 dist/music-outo/ 폴더에 EXE + 의존 dll/data 를 모두 풀어둔다.
; 여기서 그 폴더 통째로 설치 디렉토리에 복사.
; ★ Excludes: 사용자 데이터는 절대 덮어쓰지 않는다 (업데이트 안전성의 핵심).
;   - backend\storage\* : 프로젝트·채널·세션 등 실제 작업물
;   - .env             : 사용자가 입력한 Gemini 키 등
;   - *.log            : 실행 로그
;   이 항목들이 패키지에 섞여도 설치/업데이트 시 복사에서 제외되어 기존 데이터가 보존된다.
Source: "..\dist\music-outo\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs; \
  Excludes: "backend\storage\*,*.log,.env"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: autostart

[Run]
; 설치 직후 실행 여부를 사용자가 선택
Filename: "{app}\{#MyAppExeName}"; Description: "지금 {#MyAppName} 실행"; \
  Flags: shellexec postinstall skipifsilent nowait

[UninstallRun]
; 실행 중인 EXE 정리 (백엔드가 백그라운드에 떠 있을 수 있음)
Filename: "taskkill.exe"; Parameters: "/F /IM music-outo.exe /T"; Flags: runhidden; RunOnceId: "KillEXE"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
