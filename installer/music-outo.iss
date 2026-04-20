; Music Outo 설치 스크립트 (Inno Setup)
; 빌드: GitHub Actions 가 v*.*.* 태그 push 시 자동 실행 (installer.yml 참조)

#define MyAppName "Music Outo"
#define MyAppVersion GetEnv("APP_VERSION")
#if MyAppVersion == ""
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppPublisher "Eileen42"
#define MyAppURL "https://github.com/Eileen42/music-outo"
#define MyAppExeName "start-music-outo.bat"

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
; 인스톨러에 포함할 실제 파일들 — Windows 빌드 러너에서 repo 체크아웃 후 이 경로에 위치
Source: "start-music-outo.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docker-compose.prod.yml"; DestDir: "{app}"; Flags: ignoreversion
Source: "env.template"; DestDir: "{app}"; DestName: ".env"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName} 실행"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: autostart

[Run]
; 1) Docker Desktop 없으면 winget 으로 설치
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Host 'Docker Desktop 설치 중... (몇 분 소요)'; winget install Docker.DockerDesktop --accept-package-agreements --accept-source-agreements --silent; Write-Host 'Docker Desktop 설치 완료. 완전 활성화를 위해 한번 재부팅이 필요할 수 있습니다.' }"""; \
  StatusMsg: "Docker Desktop 확인 및 설치 중... (최초 설치 시 5~10분 소요)"; \
  Flags: runhidden waituntilterminated

; 2) 설치 직후 실행 여부를 사용자가 선택
Filename: "{app}\{#MyAppExeName}"; Description: "지금 {#MyAppName} 실행"; \
  Flags: shellexec postinstall skipifsilent nowait

[UninstallRun]
; 제거 시 컨테이너 정리
Filename: "cmd.exe"; Parameters: "/c cd /d ""{app}"" && docker compose -f docker-compose.prod.yml down"; Flags: runhidden

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
