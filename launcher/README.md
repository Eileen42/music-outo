# Music Outo Launcher

사용자 PC에서 **로컬 백엔드를 백그라운드로 실행**하고 **기본 브라우저로 웹앱을 여는** 런처.

## 동작 흐름

```
[바탕화면 아이콘 더블클릭]
        │
        ▼
    launch.vbs  ─┬─ .env 파싱 (APP_URL / BACKEND_URL / BACKEND_PORT)
                 ├─ /health 체크 — 이미 켜져 있으면 스킵
                 ├─ start_server.bat 을 창 없이 백그라운드 실행
                 ├─ /health 가 200 뜰 때까지 최대 15초 폴링
                 └─ 기본 브라우저로 APP_URL 열기
```

웹 북마크로 접속하는 시나리오에서도 끊김이 없도록, `install.ps1` 은 **시작프로그램에 등록**한다. 사용자가 PC 를 켜는 순간 서버가 이미 상주.

## 파일

| 파일 | 역할 |
|------|------|
| `.env` | APP_URL, BACKEND_URL, BACKEND_PORT (도메인은 여기서만 바꾸면 됨) |
| `.env.example` | 배포용 예시 |
| `launch.vbs` | 진입점. 콘솔 창 없이 서버 기동 + 브라우저 오픈 |
| `start_server.bat` | uvicorn 실행 (launch.vbs 가 hidden 으로 호출) |
| `install.ps1` | 바탕화면 바로가기 + 시작프로그램 등록 |
| `icon.ico` | (선택) 바로가기 아이콘 — 없으면 기본 아이콘 |

## 설치 / 제거

```powershell
# 설치
powershell -ExecutionPolicy Bypass -File launcher\install.ps1

# 제거 (바로가기만 삭제)
powershell -ExecutionPolicy Bypass -File launcher\install.ps1 -Uninstall
```

## 배포 후 할 일

1. `.env` 의 `APP_URL` 을 실제 도메인으로 교체 (예: `https://musicouto.com/app`)
2. 설치 파일에 `launcher/` 폴더 전체를 포함시키고, 설치 후 `install.ps1` 자동 실행
