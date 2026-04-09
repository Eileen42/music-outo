# 설치 및 실행 가이드

## 1. 필수 조건

- Python 3.11+
- Node.js 20+
- Docker & Docker Compose (선택)
- FFmpeg (로컬 실행 시 필수)

### FFmpeg 설치

**Windows:**
```bash
winget install Gyan.FFmpeg
# 또는 https://ffmpeg.org/download.html 에서 다운로드 후 PATH 등록
```

**macOS:**
```bash
brew install ffmpeg
```

**Linux:**
```bash
sudo apt-get install ffmpeg
```

---

## 2. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일 편집:

```env
# Gemini API 키 (여러 개 권장 - 무료 티어 RPM 분산)
GEMINI_API_KEYS=["키1","키2","키3"]

# Google OAuth (YouTube 업로드 시 필요)
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/youtube/callback
```

### Gemini API 키 발급
1. https://aistudio.google.com/app/apikey 접속
2. "Create API key" 클릭
3. 무료 티어: 분당 15회 요청 제한 → 키 여러 개 권장

### Google OAuth 설정 (YouTube 업로드용)
1. https://console.cloud.google.com 접속
2. 새 프로젝트 생성
3. "YouTube Data API v3" 활성화
4. OAuth 2.0 클라이언트 ID 생성
   - 애플리케이션 유형: 웹 애플리케이션
   - 승인된 리디렉션 URI: `http://localhost:8000/api/youtube/callback`

---

## 3. Docker로 실행 (권장)

```bash
docker-compose up --build
```

- 백엔드: http://localhost:8000
- 프론트엔드: http://localhost:3000
- API 문서: http://localhost:8000/docs

---

## 4. 로컬 실행

### 백엔드

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

---

## 5. 사용 방법 (7단계)

### Step 1: 프로젝트 생성
- 프로젝트 이름과 플레이리스트 제목 입력
- "프로젝트 생성" 클릭

### Step 2: 트랙 추가
- MP3, WAV, FLAC 등 오디오 파일 업로드
- 제목/아티스트 편집
- 🎤 버튼으로 가사 자동 추출 (faster-whisper)

### Step 3: 이미지 설정
- 썸네일 (1280×720) 업로드
- 배경 이미지 (1920×1080) 업로드

### Step 4: 메타데이터 생성
- "AI 생성" 버튼 클릭 → Gemini가 제목/설명/태그/댓글 자동 생성
- 수동 편집 후 저장

### Step 5: 레이어 설정
- 파형 스타일, 색상, 위치 설정
- 텍스트 레이어 추가 (플레이리스트 제목 등)

### Step 6: 빌드
- "빌드 시작" 클릭
- FFmpeg로 영상 합성 + CapCut 파일 생성
- MP4 / CapCut 파일 다운로드

### Step 7: YouTube 업로드
- Google 계정 연결 (OAuth)
- 공개 설정 선택 (비공개/미등록/공개)
- "YouTube 업로드" 클릭

---

## 6. 트러블슈팅

### faster-whisper 오류
```bash
# CUDA 없는 환경
pip install faster-whisper
# 첫 실행 시 모델 자동 다운로드 (~150MB for base model)
```

### pyJianYingDraft 설치 실패
```bash
pip install pyjianying
# 실패 시 CapCut 기능 없이도 MP4 빌드는 정상 동작
```

### FFmpeg not found
```bash
# FFmpeg PATH 확인
ffmpeg -version
```
