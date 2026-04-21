interface Props {
  userName: string
  onLogout: () => void
  onGuide: () => void
}

// GitHub Releases 의 최신 exe (installer.yml 워크플로우가 매 태그마다 갱신)
const INSTALLER_URL =
  'https://github.com/Eileen42/music-outo/releases/latest/download/music-outo-setup.exe'

export default function DownloadPage({ userName, onLogout, onGuide }: Props) {
  const handleDownload = () => {
    const link = document.createElement('a')
    link.href = INSTALLER_URL
    link.download = 'music-outo-setup.exe'
    link.click()
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
      <header className="px-6 py-4 flex items-center justify-between border-b border-gray-800">
        <div className="text-lg font-bold text-purple-400">🎬 Music Outo</div>
        <div className="flex items-center gap-3">
          <button
            onClick={onGuide}
            className="text-xs text-gray-400 hover:text-purple-300 transition-colors"
          >
            📖 사용 가이드
          </button>
          <span className="text-sm text-gray-400">{userName} 님</span>
          <button
            onClick={onLogout}
            className="text-xs text-gray-500 hover:text-red-400 transition-colors"
          >
            로그아웃
          </button>
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-lg">
          <div className="text-center mb-8">
            <div className="inline-flex items-center gap-2 bg-green-900/30 border border-green-800 rounded-full px-4 py-1 mb-4">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              <span className="text-xs text-green-300 font-medium">가입 승인 완료</span>
            </div>
            <h1 className="text-2xl md:text-3xl font-bold mb-3">프로그램을 설치하세요</h1>
            <p className="text-gray-400 text-sm">
              아래 버튼으로 설치 파일을 받아 PC 에 설치하면 바로 사용할 수 있습니다.
            </p>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 space-y-5">
            <button
              onClick={handleDownload}
              className="w-full bg-purple-600 hover:bg-purple-500 text-white font-semibold py-4 rounded-xl text-lg transition-colors"
            >
              ⬇ 설치 파일 다운로드 (Windows)
            </button>

            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-gray-300">설치 방법</h3>
              <ol className="space-y-2 text-sm text-gray-400">
                <li className="flex gap-3">
                  <span className="shrink-0 w-6 h-6 rounded-full bg-gray-800 flex items-center justify-center text-xs text-purple-400 font-bold">1</span>
                  <span>위 버튼을 클릭해 <code className="text-purple-300 bg-gray-800 px-1 rounded">music-outo-setup.exe</code> 를 받습니다</span>
                </li>
                <li className="flex gap-3">
                  <span className="shrink-0 w-6 h-6 rounded-full bg-gray-800 flex items-center justify-center text-xs text-purple-400 font-bold">2</span>
                  <span>파일을 더블클릭 → 설치 마법사의 "다음" 을 눌러 진행합니다</span>
                </li>
                <li className="flex gap-3">
                  <span className="shrink-0 w-6 h-6 rounded-full bg-gray-800 flex items-center justify-center text-xs text-purple-400 font-bold">3</span>
                  <span>최초 설치 시 Docker Desktop 이 함께 설치됩니다 (5~10분)</span>
                </li>
                <li className="flex gap-3">
                  <span className="shrink-0 w-6 h-6 rounded-full bg-gray-800 flex items-center justify-center text-xs text-purple-400 font-bold">4</span>
                  <span>설치 완료 후 바탕화면의 <strong className="text-purple-300">Music Outo</strong> 아이콘을 더블클릭하면 브라우저가 열립니다</span>
                </li>
              </ol>
            </div>

            <div className="bg-gray-800/50 rounded-xl px-4 py-3 text-xs text-gray-400 leading-relaxed">
              이미 설치하셨다면{' '}
              <a href="http://localhost:3000" className="text-purple-400 hover:text-purple-300 underline">
                http://localhost:3000
              </a>
              {' '}으로 접속해 작업을 시작할 수 있습니다.
              <br />
              프로그램은 한 번 설치한 뒤에는 자동으로 최신 버전으로 업데이트됩니다.
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
