import { useState } from 'react'
import { api } from '../api/client'

interface Props {
  onComplete: () => void
}

export default function GeminiSetup({ onComplete }: Props) {
  const [apiKey, setApiKey] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!apiKey.trim()) {
      setError('API 키를 입력해주세요')
      return
    }

    setLoading(true)
    try {
      const res = await fetch(
        (localStorage.getItem('backend_url') || import.meta.env.VITE_API_URL || 'http://localhost:8000') + '/api/settings/gemini',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ keys: [apiKey.trim()] }),
        }
      )
      const data = await res.json()
      if (data.error) {
        setError(data.error)
        return
      }
      onComplete()
    } catch {
      setError('서버에 연결할 수 없습니다')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto p-6">
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6">
        <h2 className="text-lg font-bold text-white mb-1">Gemini API 키 설정</h2>
        <p className="text-sm text-gray-400 mb-6">
          AI 기능(노래 생성, 메타데이터 등)을 사용하려면 Google Gemini API 키가 필요합니다.
        </p>

        {/* 가이드 */}
        <div className="bg-gray-800/50 rounded-lg p-4 mb-6 space-y-3 text-sm">
          <h3 className="font-semibold text-gray-300">API 키 발급 방법</h3>
          <ol className="space-y-2 text-gray-400">
            <li className="flex gap-2">
              <span className="shrink-0 text-purple-400 font-bold">1.</span>
              <span>
                <a
                  href="https://aistudio.google.com/apikey"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-purple-400 hover:text-purple-300 underline"
                >
                  Google AI Studio
                </a>
                에 접속합니다
              </span>
            </li>
            <li className="flex gap-2">
              <span className="shrink-0 text-purple-400 font-bold">2.</span>
              <span>Google 계정으로 로그인합니다</span>
            </li>
            <li className="flex gap-2">
              <span className="shrink-0 text-purple-400 font-bold">3.</span>
              <span><strong>"Create API Key"</strong> 버튼을 클릭합니다</span>
            </li>
            <li className="flex gap-2">
              <span className="shrink-0 text-purple-400 font-bold">4.</span>
              <span>생성된 키를 복사하여 아래에 붙여넣기 합니다</span>
            </li>
          </ol>
          <p className="text-xs text-gray-500 pt-1">
            * Gemini API는 무료 플랜으로 충분합니다 (분당 15회 요청)
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Gemini API Key</label>
            <input
              type="password"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500 font-mono"
              placeholder="AIzaSy..."
            />
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-medium py-2.5 rounded-lg transition-colors text-sm"
          >
            {loading ? '저장 중...' : '저장하고 시작하기'}
          </button>
        </form>
      </div>
    </div>
  )
}
