import { useState, useEffect } from 'react'

interface Props {
  onConnected: () => void
  backendUrl: string
}

export default function SetupGuide({ onConnected, backendUrl }: Props) {
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    const check = async () => {
      setChecking(true)
      try {
        const res = await fetch(`${backendUrl}/health`)
        if (res.ok) {
          onConnected()
          return
        }
      } catch {
        // 연결 실패
      }
      try {
        await fetch(`${backendUrl}/health`, { mode: 'no-cors' })
        onConnected()
        return
      } catch {
        // 서버 미연결
      }
      setChecking(false)
    }

    check()
    const id = setInterval(check, 5000)
    return () => clearInterval(id)
  }, [backendUrl, onConnected])

  // 최신 GitHub Release 의 installer 링크
  // 태그 push 시 GitHub Actions 가 music-outo-setup.exe 를 업로드한다.
  const INSTALLER_URL =
    'https://github.com/Eileen42/music-outo/releases/latest/download/music-outo-setup.exe'

  const handleDownload = () => {
    const link = document.createElement('a')
    link.href = INSTALLER_URL
    link.download = 'music-outo-setup.exe'
    link.click()
  }

  // Vercel 웹앱에서 접속한 경우
  const isVercel = window.location.hostname.includes('vercel.app')

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950 px-4">
      <div className="w-full max-w-lg">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white mb-2">시작하기</h1>
          <p className="text-gray-400 text-sm">이 PC에서 처음 사용하시나요? 아래 버튼을 눌러 설치해주세요.</p>
        </div>

        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 space-y-6">
          {/* 설치 버튼 */}
          <button
            onClick={handleDownload}
            className="w-full bg-purple-600 hover:bg-purple-500 text-white font-medium py-4 rounded-xl transition-colors text-lg"
          >
            프로그램 설치하기
          </button>

          {/* 설치 가이드 */}
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-gray-300">설치 방법</h3>
            <ol className="space-y-2 text-sm text-gray-400">
              <li className="flex gap-3">
                <span className="shrink-0 w-6 h-6 rounded-full bg-gray-800 flex items-center justify-center text-xs text-purple-400 font-bold">1</span>
                <span>위 버튼을 클릭하여 설치 파일을 다운로드합니다</span>
              </li>
              <li className="flex gap-3">
                <span className="shrink-0 w-6 h-6 rounded-full bg-gray-800 flex items-center justify-center text-xs text-purple-400 font-bold">2</span>
                <span>다운로드된 <code className="text-purple-300 bg-gray-800 px-1 rounded">music-outo-setup.exe</code> 파일을 더블클릭합니다</span>
              </li>
              <li className="flex gap-3">
                <span className="shrink-0 w-6 h-6 rounded-full bg-gray-800 flex items-center justify-center text-xs text-purple-400 font-bold">3</span>
                <span>설치 마법사가 열리면 "다음" 을 눌러 진행합니다 (첫 설치 시 Docker Desktop 자동 설치, 5~10분 소요)</span>
              </li>
              <li className="flex gap-3">
                <span className="shrink-0 w-6 h-6 rounded-full bg-gray-800 flex items-center justify-center text-xs text-purple-400 font-bold">4</span>
                <span>
                  설치 완료 후 바탕화면의 <strong className="text-purple-300">Music Outo</strong> 아이콘으로 실행합니다
                </span>
              </li>
            </ol>
          </div>

          {/* Vercel에서 접속한 경우 안내 */}
          {isVercel && (
            <div className="bg-blue-900/20 border border-blue-800/50 rounded-lg p-3">
              <p className="text-xs text-blue-300">
                설치 완료 후에는{' '}
                <a href="http://localhost:3000" className="underline font-medium">
                  http://localhost:3000
                </a>
                {' '}에서 프로그램을 사용하세요.
              </p>
            </div>
          )}

          {/* 연결 상태 */}
          <div className="pt-4 border-t border-gray-800 flex items-center justify-center gap-2">
            {checking ? (
              <>
                <span className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" />
                <span className="text-xs text-gray-500">연결 확인 중...</span>
              </>
            ) : (
              <>
                <span className="w-2 h-2 rounded-full bg-gray-600" />
                <span className="text-xs text-gray-600">프로그램 설치 후 자동으로 연결됩니다</span>
              </>
            )}
          </div>

          {/* 이미 설치된 경우 */}
          <div className="text-center">
            <p className="text-xs text-gray-600">
              이미 설치하셨나요? 프로그램이 실행 중인지 확인해주세요.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
