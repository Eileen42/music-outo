import { useState, useEffect, useCallback } from 'react'

interface Props {
  backendUrl: string
  onConnected: () => void
}

export default function ServerOffline({ backendUrl, onConnected }: Props) {
  const [retryCount, setRetryCount] = useState(0)
  const [checking, setChecking] = useState(false)
  const [showManual, setShowManual] = useState(false)

  const checkHealth = useCallback(async () => {
    setChecking(true)
    try {
      const res = await fetch(`${backendUrl}/health`)
      if (res.ok) { onConnected(); return }
    } catch { /* 연결 실패 */ }
    try {
      await fetch(`${backendUrl}/health`, { mode: 'no-cors' })
      onConnected()
      return
    } catch { /* 서버 미연결 */ }
    setChecking(false)
    setRetryCount(c => c + 1)
  }, [backendUrl, onConnected])

  // 5초마다 자동 재연결
  useEffect(() => {
    checkHealth()
    const id = setInterval(checkHealth, 5000)
    return () => clearInterval(id)
  }, [checkHealth])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950 px-4">
      <div className="w-full max-w-lg">
        <div className="text-center mb-8">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-yellow-900/30 flex items-center justify-center">
            <span className="text-3xl">🔌</span>
          </div>
          <h1 className="text-2xl font-bold text-white mb-2">로컬 서버에 연결할 수 없습니다</h1>
          <p className="text-gray-400 text-sm">
            PC가 재시작되었거나 서버가 꺼져 있을 수 있습니다.
            <br />
            자동 시작이 설정되어 있다면 잠시 기다려주세요.
          </p>
        </div>

        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 space-y-5">
          {/* 재연결 상태 */}
          <div className="flex items-center justify-center gap-3">
            {checking ? (
              <>
                <span className="w-2.5 h-2.5 rounded-full bg-yellow-500 animate-pulse" />
                <span className="text-sm text-yellow-400">연결 시도 중...</span>
              </>
            ) : (
              <>
                <span className="w-2.5 h-2.5 rounded-full bg-red-500" />
                <span className="text-sm text-red-400">서버 응답 없음</span>
              </>
            )}
            <span className="text-xs text-gray-600 ml-2">
              (시도 {retryCount}회 · 5초마다 자동 재연결)
            </span>
          </div>

          {/* 재연결 시도 버튼 */}
          <button
            onClick={checkHealth}
            disabled={checking}
            className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-medium py-3 rounded-xl transition-colors"
          >
            {checking ? '확인 중...' : '지금 재연결 시도'}
          </button>

          {/* 수동 시작 안내 토글 */}
          <div className="border-t border-gray-800 pt-4">
            <button
              onClick={() => setShowManual(!showManual)}
              className="w-full flex items-center justify-between text-sm text-gray-400 hover:text-gray-300 transition-colors"
            >
              <span>서버 수동 시작 방법</span>
              <span className={`transition-transform ${showManual ? 'rotate-180' : ''}`}>▼</span>
            </button>

            {showManual && (
              <div className="mt-4 space-y-3">
                <div className="bg-gray-800 rounded-lg p-4 space-y-2">
                  <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide">방법 1: 바로가기 실행</h4>
                  <p className="text-xs text-gray-400">
                    프로젝트 폴더의 <code className="text-purple-300 bg-gray-700 px-1 rounded">start.bat</code>을 더블클릭하세요.
                  </p>
                </div>

                <div className="bg-gray-800 rounded-lg p-4 space-y-2">
                  <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide">방법 2: 자동 시작 등록</h4>
                  <p className="text-xs text-gray-400">
                    <code className="text-purple-300 bg-gray-700 px-1 rounded">install_autostart.bat</code>을 실행하면
                    PC 부팅 시 서버가 자동으로 시작됩니다.
                  </p>
                </div>

                <div className="bg-gray-800 rounded-lg p-4 space-y-2">
                  <h4 className="text-xs font-semibold text-gray-300 uppercase tracking-wide">방법 3: 터미널에서 직접 실행</h4>
                  <code className="block text-xs text-green-400 bg-gray-900 p-2 rounded font-mono">
                    cd D:\coding\music_outo\backend<br />
                    d:\coding\.venv\Scripts\uvicorn main:app --port 8000 --host 0.0.0.0
                  </code>
                </div>
              </div>
            )}
          </div>

          {/* 접속 URL 정보 */}
          <div className="text-center text-xs text-gray-600 pt-2 border-t border-gray-800">
            연결 대상: <code className="text-gray-500">{backendUrl}</code>
          </div>
        </div>
      </div>
    </div>
  )
}
