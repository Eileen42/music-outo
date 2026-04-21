interface Props {
  onBack: () => void
}

interface Section {
  id: string
  title: string
  icon: string
}

const SECTIONS: Section[] = [
  { id: 'install', title: '설치와 실행', icon: '⚙️' },
  { id: 'gemini', title: 'Gemini API 키 등록', icon: '🔑' },
  { id: 'step1', title: '1. 채널 설정', icon: '📺' },
  { id: 'step2', title: '2. 노래 만들기', icon: '🎵' },
  { id: 'step3', title: '3. 이미지 설정', icon: '🖼️' },
  { id: 'step4', title: '4. 메타데이터', icon: '✍️' },
  { id: 'step5', title: '5. 레이어 설정', icon: '🎬' },
  { id: 'step6', title: '6. 빌드 & 다운로드', icon: '⚒️' },
  { id: 'step7', title: '7. YouTube 업로드', icon: '▶️' },
  { id: 'update', title: '자동 업데이트', icon: '🔄' },
  { id: 'faq', title: '자주 묻는 질문', icon: '❓' },
  { id: 'trouble', title: '문제 해결', icon: '🛠️' },
]

export default function GuidePage({ onBack }: Props) {
  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="sticky top-0 z-10 bg-gray-950/95 backdrop-blur border-b border-gray-800 px-6 py-3 flex items-center justify-between">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-purple-400 hover:text-purple-300 font-semibold text-sm"
        >
          ← 돌아가기
        </button>
        <div className="text-sm text-gray-500">📖 Music Outo 사용 가이드</div>
        <div className="w-24" />
      </header>

      <div className="max-w-6xl mx-auto px-6 py-10 grid md:grid-cols-[220px_1fr] gap-10">
        <aside className="md:sticky md:top-16 md:self-start space-y-1 text-sm">
          <div className="text-xs font-semibold text-gray-500 uppercase mb-2">목차</div>
          {SECTIONS.map(s => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className="block px-3 py-2 rounded-lg text-gray-400 hover:text-purple-300 hover:bg-gray-900 transition-colors"
            >
              <span className="mr-2">{s.icon}</span>{s.title}
            </a>
          ))}
        </aside>

        <main className="space-y-14 text-gray-300 leading-relaxed">
          <section className="text-center pb-6 border-b border-gray-800">
            <h1 className="text-3xl font-bold text-white mb-3">🎬 Music Outo 사용 가이드</h1>
            <p className="text-sm text-gray-500">
              설치부터 첫 영상 업로드까지 — 왼쪽 목차를 따라 순서대로 진행하세요.
            </p>
          </section>

          {/* 설치와 실행 */}
          <section id="install" className="scroll-mt-20">
            <h2 className="text-2xl font-bold text-white mb-4">⚙️ 설치와 실행</h2>
            <ol className="space-y-4">
              <GuideStep num={1} title="설치 파일 다운로드">
                메인 페이지의 <strong className="text-purple-300">"설치 파일 다운로드"</strong> 버튼을
                누르면 <code className="bg-gray-800 px-1 rounded">music-outo-setup.exe</code> 가
                내려받아집니다 (약 2MB).
              </GuideStep>
              <GuideStep num={2} title="설치 마법사 실행">
                다운로드한 exe 를 더블클릭하면 설치 마법사가 열립니다. "다음" 을 눌러
                진행하세요. 설치 경로는 기본값 그대로 두시면 됩니다.
              </GuideStep>
              <GuideStep num={3} title="Docker Desktop 자동 설치 (최초 1회)">
                PC 에 Docker Desktop 이 없으면 설치 중 자동으로 함께 설치됩니다.
                <strong className="text-yellow-300"> 5~10분 정도 걸리며</strong> "관리자 권한" 알림이 뜨면
                "예" 를 눌러주세요. 설치 후 PC 재부팅이 필요할 수 있습니다.
              </GuideStep>
              <GuideStep num={4} title='바탕화면의 "Music Outo" 아이콘 실행'>
                설치가 끝나면 바탕화면에 아이콘이 생깁니다. 더블클릭하면 검은색
                창이 잠깐 뜨고 자동으로 브라우저가 열립니다
                (<code className="bg-gray-800 px-1 rounded">http://localhost:3000</code>).
              </GuideStep>
              <Note tone="info">
                아이콘 한 번 누르면 <strong>Docker Desktop 자동 시작 → 최신 이미지 확인 → 백엔드/프론트엔드 실행 → 브라우저 오픈</strong>
                까지 한 번에. 처음에는 1~2분, 이후엔 20~30초면 준비됩니다.
              </Note>
            </ol>
          </section>

          {/* Gemini API 키 */}
          <section id="gemini" className="scroll-mt-20">
            <h2 className="text-2xl font-bold text-white mb-4">🔑 Gemini API 키 등록</h2>
            <p className="mb-4">
              가사·메타데이터·이미지 생성에 Google Gemini 를 사용합니다. 처음 실행하면
              키 등록 화면이 뜨는데 발급 방법은 아래와 같습니다:
            </p>
            <ol className="space-y-3">
              <GuideStep num={1} title="Google AI Studio 접속">
                <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" className="text-purple-400 hover:text-purple-300 underline">
                  https://aistudio.google.com/app/apikey
                </a>
                {' '}에서 로그인합니다.
              </GuideStep>
              <GuideStep num={2} title='"Create API key" 클릭'>
                새 키가 발급됩니다. <code className="bg-gray-800 px-1 rounded">AIzaSy...</code> 형식의
                문자열을 복사하세요.
              </GuideStep>
              <GuideStep num={3} title="프로그램에 붙여넣기">
                프로그램의 Gemini 설정 화면에 붙여넣기 → 저장. 여러 개 등록 가능합니다
                (무료 티어의 분당 15회 제한을 분산하려면 2~3개 권장).
              </GuideStep>
            </ol>
            <Note tone="info">
              키는 <strong>본인 PC 의 `.env` 파일</strong>에만 저장됩니다. 서버로 전송되지
              않으니 안전합니다.
            </Note>
          </section>

          {/* Step 1 */}
          <section id="step1" className="scroll-mt-20">
            <h2 className="text-2xl font-bold text-white mb-4">📺 1단계. 채널 설정</h2>
            <p className="mb-4">
              유튜브 채널 한 개마다 작업 프로필을 만듭니다. 같은 스타일의 영상을
              반복 생산할 때 기본값(장르, 가사 여부, Suno 프롬프트, 설명·태그 템플릿)이
              채널에 저장돼 매번 입력할 필요가 없습니다.
            </p>
            <ul className="space-y-2">
              <Bullet>새 채널 추가: 채널명, 장르, 기본 Suno 프롬프트, 기본 설명·태그 설정</Bullet>
              <Bullet>기존 채널 선택 후 "새 프로젝트 생성" → 이번 영상 한 편의 작업 시작</Bullet>
              <Bullet>프로젝트 목록에서 이전 작업 재진입 가능. localStorage 에 마지막 프로젝트 자동 기억</Bullet>
            </ul>
          </section>

          {/* Step 2 */}
          <section id="step2" className="scroll-mt-20">
            <h2 className="text-2xl font-bold text-white mb-4">🎵 2단계. 노래 만들기</h2>
            <p className="mb-4">
              Suno AI 로 곡을 직접 생성하거나, 이미 있는 MP3 를 업로드할 수 있습니다.
            </p>
            <div className="grid md:grid-cols-2 gap-4">
              <Card title="Suno 배치 생성 (추천)">
                <p>Gemini 가 가사·프롬프트를 자동 설계하고 Suno 가 곡을 만듭니다.</p>
                <ul className="mt-2 space-y-1 text-sm">
                  <Bullet>곡 수(3~30곡)와 곡당 시간 선택</Bullet>
                  <Bullet>Gemini 가 곡 제목·가사·Suno 프롬프트 자동 생성</Bullet>
                  <Bullet>쿠키 모드(HTTP 직접 호출)와 브라우저 폴백(Playwright) 모두 지원</Bullet>
                  <Bullet>다운로드 직후 MP3 헤더 자동 교정 (잘림 방지)</Bullet>
                </ul>
              </Card>
              <Card title="파일 직접 업로드">
                <p>이미 만든 MP3 / WAV / FLAC 를 드래그 & 드롭.</p>
                <ul className="mt-2 space-y-1 text-sm">
                  <Bullet>순서 드래그로 재정렬</Bullet>
                  <Bullet>제목·아티스트 인라인 편집</Bullet>
                  <Bullet>🎤 버튼으로 가사 자동 추출 (faster-whisper)</Bullet>
                </ul>
              </Card>
            </div>
            <Note tone="warn">
              Suno 계정이 필요합니다. 첫 사용 시 앱이 Suno 로그인 브라우저를 띄우니
              평소처럼 로그인하면 쿠키가 저장돼 이후 자동화됩니다.
            </Note>
          </section>

          {/* Step 3 */}
          <section id="step3" className="scroll-mt-20">
            <h2 className="text-2xl font-bold text-white mb-4">🖼️ 3단계. 이미지 설정</h2>
            <p className="mb-4">
              썸네일(1280×720)과 배경 이미지(1920×1080)를 각각 지정합니다.
            </p>
            <ul className="space-y-2">
              <Bullet>PC 에서 파일 업로드 — 가장 빠름</Bullet>
              <Bullet>AI 생성 — 채널 장르/주제 기반으로 Gemini 이미지 생성 호출</Bullet>
              <Bullet>카테고리 자동 분류 — 업로드 여러 장을 썸네일/배경으로 자동 분류·리사이즈</Bullet>
            </ul>
          </section>

          {/* Step 4 */}
          <section id="step4" className="scroll-mt-20">
            <h2 className="text-2xl font-bold text-white mb-4">✍️ 4단계. 메타데이터</h2>
            <p className="mb-4">
              YouTube 에 올라갈 제목·설명·태그·고정댓글을 Gemini 로 한 번에 생성합니다.
            </p>
            <ul className="space-y-2">
              <Bullet>"AI 생성" 클릭 한 번으로 제목 + 설명 + 태그(최대 30개) + 고정댓글 자동 작성</Bullet>
              <Bullet>재생성·수동 편집 가능. 채널 기본 템플릿이 자동으로 반영됨</Bullet>
              <Bullet>썸네일 이미지 위 텍스트는 Gemini Vision 으로 OCR 해 중복 방지</Bullet>
            </ul>
          </section>

          {/* Step 5 */}
          <section id="step5" className="scroll-mt-20">
            <h2 className="text-2xl font-bold text-white mb-4">🎬 5단계. 레이어 설정</h2>
            <p className="mb-4">
              영상에 올라갈 오버레이(파형·자막·텍스트)를 설정합니다. 전부 선택 항목.
            </p>
            <div className="grid md:grid-cols-2 gap-4">
              <Card title="파형(Waveform)">
                오디오에 맞춰 춤추는 막대 애니메이션. 스타일·색상·위치 선택.
              </Card>
              <Card title="자막 SRT">
                가사를 자동으로 타임코드화 — 20자 제한·간격 1초·최대 6초·단어 싱크.
              </Card>
              <Card title="텍스트 레이어">
                플레이리스트 제목, 채널명 등 고정 문구. 폰트·크기·위치 지정.
              </Card>
              <Card title="트랙 제목 타임스탬프">
                "00:00 첫 곡 / 03:24 두 번째 곡" 형태의 설명란용 타임스탬프 자동 생성.
              </Card>
            </div>
          </section>

          {/* Step 6 */}
          <section id="step6" className="scroll-mt-20">
            <h2 className="text-2xl font-bold text-white mb-4">⚒️ 6단계. 빌드 & 다운로드</h2>
            <p className="mb-4">
              두 가지 출력 모드가 있습니다:
            </p>
            <div className="grid md:grid-cols-2 gap-4 mb-4">
              <Card title="CapCut 프로젝트 (기본·추천)">
                <p>CapCut 에서 열어 세밀하게 편집 가능한 draft 파일 + Resources 폴더 생성.</p>
                <ul className="mt-2 space-y-1 text-sm">
                  <Bullet>빠름 (1~3분)</Bullet>
                  <Bullet>FFmpeg 렌더링 불필요</Bullet>
                  <Bullet>편집 후 CapCut 에서 최종 MP4 내보내기</Bullet>
                </ul>
              </Card>
              <Card title="MP4 직접 렌더링">
                <p>FFmpeg 로 영상을 그 자리에서 합성. 편집 필요 없으면 바로 업로드 가능.</p>
                <ul className="mt-2 space-y-1 text-sm">
                  <Bullet>긴 영상은 10분 이상 걸릴 수 있음</Bullet>
                  <Bullet>오디오·자막·배경 전부 포함된 완성본</Bullet>
                </ul>
              </Card>
            </div>
            <Note tone="info">
              빌드 결과물은{' '}
              <code className="bg-gray-800 px-1 rounded">storage/projects/{'{id}'}/outputs/</code>
              {' '}에 저장됩니다. 폴더 열기 버튼으로 바로 탐색 가능.
            </Note>
          </section>

          {/* Step 7 */}
          <section id="step7" className="scroll-mt-20">
            <h2 className="text-2xl font-bold text-white mb-4">▶️ 7단계. YouTube 업로드</h2>
            <p className="mb-4">
              YouTube API 대신 <strong className="text-purple-300">브라우저 자동화</strong> 방식을 씁니다.
              Google OAuth 연결 없이 평소 YouTube 로그인만으로 동작합니다.
            </p>
            <ol className="space-y-4">
              <GuideStep num={1} title='"브라우저 업로드 열기" 클릭'>
                Edge 가 CDP 모드로 시작돼 YouTube Studio 업로드 페이지가 열리고,
                영상 파일이 들어있는 outputs 폴더도 자동으로 열립니다.
              </GuideStep>
              <GuideStep num={2} title="MP4 드래그해 업로드 시작">
                outputs 폴더의 MP4 파일을 YouTube 창으로 드래그. 업로드가 시작되면
                기다리세요.
              </GuideStep>
              <GuideStep num={3} title='"메타데이터 자동 입력" 클릭'>
                Playwright 가 Studio 페이지를 조작해 제목·설명·태그·썸네일을
                채워 넣습니다. 진행 상황은 실시간으로 표시됩니다.
              </GuideStep>
              <GuideStep num={4} title="최종 게시 버튼만 본인이 클릭">
                공개 범위(비공개/일부공개/공개), 수익 창출 설정 등 민감 항목은
                본인이 직접 확인하고 "게시" 누르시는 게 안전합니다.
              </GuideStep>
            </ol>
            <Note tone="info">
              Edge 브라우저를 쓰는 이유는 CDP(Chrome DevTools Protocol) 제어가
              가능하고 Windows 기본 탑재라 설치가 필요 없어서입니다.
            </Note>
          </section>

          {/* 자동 업데이트 */}
          <section id="update" className="scroll-mt-20">
            <h2 className="text-2xl font-bold text-white mb-4">🔄 자동 업데이트</h2>
            <p className="mb-4">
              새 기능이나 버그 수정이 배포되면 <strong>자동으로 받아집니다</strong>. 따로
              뭘 하실 필요는 없습니다.
            </p>
            <ul className="space-y-2">
              <Bullet>바탕화면 아이콘을 누를 때마다 설정 파일과 Docker 이미지가 최신인지 확인</Bullet>
              <Bullet>변경점 있으면 자동 내려받아 다음 실행부터 반영</Bullet>
              <Bullet>오프라인이어도 이전 상태로 그대로 실행됨 (인터넷 필요 없음)</Bullet>
            </ul>
          </section>

          {/* FAQ */}
          <section id="faq" className="scroll-mt-20">
            <h2 className="text-2xl font-bold text-white mb-4">❓ 자주 묻는 질문</h2>
            <div className="space-y-5">
              <FAQ q="왜 설치가 필요한가요? 웹에서 바로 못 쓰나요?">
                영상 합성·CapCut 프로젝트 생성·Suno 자동화가 전부 각자 PC 의 CPU/디스크를
                쓰기 때문입니다. 웹에서 하려면 서버 비용이 월 수십만원 단위로 들어가서
                요금이 비싸집니다. 설치형이 운영비가 들지 않아요.
              </FAQ>
              <FAQ q="Mac/Linux 에서도 쓸 수 있나요?">
                현재는 Windows 전용입니다. Docker Desktop 과 Edge 브라우저(업로드 자동화용)에
                의존하는 부분이 있습니다. Mac 지원은 계획 중.
              </FAQ>
              <FAQ q="내 데이터는 어디에 저장되나요?">
                전부 본인 PC 의{' '}
                <code className="bg-gray-800 px-1 rounded">%LOCALAPPDATA%\Programs\music-outo</code>
                {' '}폴더. 프로젝트·음원·영상 모두 로컬 저장이라 외부 서버로 전송되지 않습니다.
                가입 정보(이메일 등)만 웹의 가입 DB 에 저장됩니다.
              </FAQ>
              <FAQ q="여러 대의 PC 에서 같은 계정을 쓸 수 있나요?">
                가입 계정은 공유되지만 작업 데이터(프로젝트·영상)는 PC 마다 따로 저장됩니다.
                한 PC 에서 만든 프로젝트는 다른 PC 에서 안 보여요. 필요하면 storage 폴더를
                수동 복사하시면 됩니다.
              </FAQ>
              <FAQ q="Gemini 무료 한도(분당 15회) 초과가 자주 나요. 어떻게 하죠?">
                Google AI Studio 에서 키를 2~3개 더 발급해 같이 등록해주세요. 앱이
                자동으로 순환 사용해 한도 초과를 분산시킵니다.
              </FAQ>
              <FAQ q="업데이트 후 오류가 나면?">
                대부분은 아이콘을 한 번 닫았다 다시 누르면 해결됩니다. 그래도 안 되면
                Docker Desktop 을 종료한 뒤 다시 아이콘을 실행해보세요.
              </FAQ>
            </div>
          </section>

          {/* 문제 해결 */}
          <section id="trouble" className="scroll-mt-20">
            <h2 className="text-2xl font-bold text-white mb-4">🛠️ 문제 해결</h2>
            <div className="space-y-5">
              <FAQ q='아이콘을 눌러도 브라우저가 안 열려요'>
                처음 실행엔 Docker Desktop 시작 → 이미지 pull 이 필요해 1~2분 걸립니다.
                검은 창이 떠있으면 정상 진행 중이니 잠시 기다려주세요.
                30초가 지나도 안 열리면 수동으로{' '}
                <a href="http://localhost:3000" className="text-purple-400 underline">
                  http://localhost:3000
                </a>
                {' '}을 열어보세요.
              </FAQ>
              <FAQ q="Docker Desktop 이 시작 실패로 뜨면">
                PC 를 재부팅해보세요. Windows 업데이트 직후엔 Docker 가 WSL2 초기화를
                다시 해야 할 때가 있습니다. 그래도 안 되면 Docker Desktop 을 재설치:
                설정 → 앱 → Docker Desktop → 수정 → Repair.
              </FAQ>
              <FAQ q="곡 생성 중 Suno 가 로그아웃됐다고 나오면">
                메뉴의 "Suno 로그인" 버튼을 눌러 다시 로그인하세요. 쿠키가 만료됐을
                뿐이라 로그인만 다시 하면 기존 프로젝트는 그대로 이어집니다.
              </FAQ>
              <FAQ q='"메타데이터 자동 입력" 버튼이 안 눌려요'>
                YouTube Studio 창이 열려있고 MP4 업로드가 시작된 상태여야 합니다. 업로드
                진행률이 보이는 창에서 버튼을 누르세요.
              </FAQ>
              <FAQ q="영상 빌드가 자꾸 실패해요">
                outputs 폴더의 이전 빌드를 삭제 후 재시도. Docker 디스크 용량이 가득 찬
                경우일 수 있으니 Docker Desktop → Troubleshoot → Clean / Purge data 도
                한 번 실행해보세요.
              </FAQ>
              <FAQ q="그래도 해결이 안 되면">
                프로그램의 로그를 받아 보내주시면 원인 파악이 빠릅니다: 바탕화면 아이콘
                우클릭 → 파일 위치 열기 → <code className="bg-gray-800 px-1 rounded">server.log</code> 를
                관리자에게 전달.
              </FAQ>
            </div>
          </section>

          <div className="py-10 text-center text-xs text-gray-600 border-t border-gray-800">
            이 가이드가 부족하면 관리자에게 문의하세요.
          </div>
        </main>
      </div>
    </div>
  )
}

function GuideStep({ num, title, children }: { num: number; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-4 items-start">
      <span className="shrink-0 w-8 h-8 rounded-full bg-purple-600 text-white text-sm font-bold flex items-center justify-center mt-0.5">
        {num}
      </span>
      <div className="flex-1">
        <h3 className="font-semibold text-white mb-1">{title}</h3>
        <div className="text-sm text-gray-400">{children}</div>
      </div>
    </li>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
      <h3 className="font-semibold text-white mb-2">{title}</h3>
      <div className="text-sm text-gray-400">{children}</div>
    </div>
  )
}

function Bullet({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex gap-2 text-sm text-gray-400">
      <span className="text-purple-400 mt-0.5">•</span>
      <span>{children}</span>
    </li>
  )
}

function Note({ tone, children }: { tone: 'info' | 'warn'; children: React.ReactNode }) {
  const toneClass = tone === 'warn'
    ? 'bg-yellow-950/40 border-yellow-800/60 text-yellow-200'
    : 'bg-blue-950/40 border-blue-800/60 text-blue-200'
  return (
    <div className={`mt-4 border rounded-xl px-4 py-3 text-sm ${toneClass}`}>
      {tone === 'warn' ? '⚠️ ' : '💡 '}{children}
    </div>
  )
}

function FAQ({ q, children }: { q: string; children: React.ReactNode }) {
  return (
    <details className="group bg-gray-900 border border-gray-800 rounded-xl">
      <summary className="cursor-pointer px-5 py-4 font-semibold text-white group-open:text-purple-300 list-none flex items-center justify-between">
        <span>{q}</span>
        <span className="text-gray-500 group-open:rotate-180 transition-transform">▾</span>
      </summary>
      <div className="px-5 pb-5 text-sm text-gray-400 leading-relaxed">{children}</div>
    </details>
  )
}
