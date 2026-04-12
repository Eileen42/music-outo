import { useState } from 'react'

interface Props {
  onClose: () => void
}

export default function OAuthGuideModal({ onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="bg-gray-900 rounded-xl border border-gray-800 w-full max-w-2xl max-h-[85vh] overflow-y-auto mx-4 p-6"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-white">YouTube 업로드 설정 가이드</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-white text-xl leading-none">&times;</button>
        </div>

        <p className="text-sm text-gray-400 mb-6">
          YouTube에 영상을 업로드하려면 Google OAuth 인증 정보가 필요합니다. 아래 단계를 따라 설정해주세요.
        </p>

        <div className="space-y-6 text-sm">
          {/* Step 1 */}
          <div className="space-y-2">
            <h3 className="font-semibold text-white flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-purple-600 flex items-center justify-center text-xs font-bold">1</span>
              Google Cloud Console 프로젝트 생성
            </h3>
            <div className="pl-8 text-gray-400 space-y-1">
              <p>
                <a href="https://console.cloud.google.com/" target="_blank" rel="noopener noreferrer"
                   className="text-purple-400 hover:text-purple-300 underline">
                  Google Cloud Console
                </a>
                에 접속하여 새 프로젝트를 만듭니다.
              </p>
              <p>프로젝트 이름은 자유롭게 입력하세요 (예: "Music Outo")</p>
            </div>
          </div>

          {/* Step 2 */}
          <div className="space-y-2">
            <h3 className="font-semibold text-white flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-purple-600 flex items-center justify-center text-xs font-bold">2</span>
              YouTube Data API v3 활성화
            </h3>
            <div className="pl-8 text-gray-400 space-y-1">
              <p>
                <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" rel="noopener noreferrer"
                   className="text-purple-400 hover:text-purple-300 underline">
                  YouTube Data API v3
                </a>
                페이지에서 <strong>"사용"</strong> 버튼을 클릭합니다.
              </p>
            </div>
          </div>

          {/* Step 3 */}
          <div className="space-y-2">
            <h3 className="font-semibold text-white flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-purple-600 flex items-center justify-center text-xs font-bold">3</span>
              OAuth 동의 화면 설정
            </h3>
            <div className="pl-8 text-gray-400 space-y-1">
              <p>
                <a href="https://console.cloud.google.com/apis/credentials/consent" target="_blank" rel="noopener noreferrer"
                   className="text-purple-400 hover:text-purple-300 underline">
                  OAuth 동의 화면
                </a>
                에서 "외부(External)" 선택 후 기본 정보를 입력합니다.
              </p>
              <p>앱 이름, 이메일만 입력하면 됩니다. 나머지는 빈 칸으로 두세요.</p>
              <p><strong>"테스트 사용자"</strong> 탭에서 본인 Gmail 주소를 추가합니다.</p>
            </div>
          </div>

          {/* Step 4 */}
          <div className="space-y-2">
            <h3 className="font-semibold text-white flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-purple-600 flex items-center justify-center text-xs font-bold">4</span>
              OAuth 2.0 클라이언트 ID 생성
            </h3>
            <div className="pl-8 text-gray-400 space-y-1">
              <p>
                <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer"
                   className="text-purple-400 hover:text-purple-300 underline">
                  사용자 인증 정보
                </a>
                {' '}페이지에서 <strong>"+ 사용자 인증 정보 만들기"</strong> → <strong>"OAuth 클라이언트 ID"</strong>를 선택합니다.
              </p>
              <p>애플리케이션 유형: <strong>"웹 애플리케이션"</strong></p>
              <p>승인된 리디렉션 URI에 다음을 추가:</p>
              <code className="block bg-gray-800 text-purple-300 px-3 py-1.5 rounded mt-1 select-all">
                http://localhost:8000/api/youtube/callback
              </code>
            </div>
          </div>

          {/* Step 5 */}
          <div className="space-y-2">
            <h3 className="font-semibold text-white flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-purple-600 flex items-center justify-center text-xs font-bold">5</span>
              Client ID / Secret 입력
            </h3>
            <div className="pl-8 text-gray-400 space-y-1">
              <p>생성된 <strong>클라이언트 ID</strong>와 <strong>클라이언트 보안 비밀번호</strong>를 아래에 입력하세요.</p>
            </div>
          </div>

          {/* 입력 폼 */}
          <OAuthForm onClose={onClose} />
        </div>
      </div>
    </div>
  )
}

function OAuthForm({ onClose }: { onClose: () => void }) {
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const backendUrl = localStorage.getItem('backend_url') || import.meta.env.VITE_API_URL || 'http://localhost:8000'

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const res = await fetch(`${backendUrl}/api/settings/google-oauth`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
      })
      const data = await res.json()
      if (data.error) {
        setError(data.error)
        return
      }
      setSuccess(true)
      setTimeout(onClose, 1500)
    } catch {
      setError('서버에 연결할 수 없습니다')
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="bg-green-900/30 border border-green-700 rounded-lg p-4 text-center">
        <p className="text-green-300 font-medium">설정이 완료되었습니다!</p>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 pt-2 border-t border-gray-800">
      <div>
        <label className="block text-xs text-gray-500 mb-1">Client ID</label>
        <input
          type="text"
          value={clientId}
          onChange={e => setClientId(e.target.value)}
          required
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500 font-mono text-xs"
          placeholder="123456789-xxxxx.apps.googleusercontent.com"
        />
      </div>
      <div>
        <label className="block text-xs text-gray-500 mb-1">Client Secret</label>
        <input
          type="password"
          value={clientSecret}
          onChange={e => setClientSecret(e.target.value)}
          required
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500 font-mono text-xs"
          placeholder="GOCSPX-..."
        />
      </div>
      {error && <p className="text-red-400 text-xs">{error}</p>}
      <button
        type="submit"
        disabled={loading}
        className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 text-white font-medium py-2 rounded-lg text-sm"
      >
        {loading ? '저장 중...' : '저장'}
      </button>
    </form>
  )
}
