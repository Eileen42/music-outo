import { useState } from 'react'

interface Props {
  onRegistered: (token: string) => void
}

type Mode = 'login' | 'register'

export default function RegisterForm({ onRegistered }: Props) {
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [referralSource, setReferralSource] = useState('')
  const [autoLogin, setAutoLogin] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // HTTP 응답을 에러 메시지로 변환 — 서버가 error 필드 안 내려줘도 안내
  const friendlyError = async (res: Response, fallback: string): Promise<string> => {
    let data: Record<string, unknown> = {}
    try { data = await res.json() } catch { /* 본문이 JSON 이 아닐 수 있음 */ }
    const explicit = (data.error || data.message) as string | undefined
    if (explicit) return explicit
    if (res.status >= 500) return '서버에 일시적인 문제가 있습니다. 잠시 후 다시 시도해주세요.'
    if (res.status === 409) return '이미 가입된 이메일입니다.'
    if (res.status === 401) return '이메일 또는 비밀번호가 올바르지 않습니다.'
    if (res.status === 400) return '입력값을 확인해주세요.'
    return `${fallback} (HTTP ${res.status})`
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })

      if (!res.ok) {
        const msg = await friendlyError(res, '로그인 실패')
        console.error('[login] failed', res.status, msg)
        setError(msg)
        return
      }

      const data = await res.json()
      if (autoLogin) {
        localStorage.setItem('auth_token', data.token)
      } else {
        sessionStorage.setItem('auth_token', data.token)
      }
      onRegistered(data.token)
    } catch (e) {
      console.error('[login] network error', e)
      setError('네트워크 오류입니다. 인터넷 연결을 확인해주세요.')
    } finally {
      setLoading(false)
    }
  }

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password, phone, referral_source: referralSource }),
      })

      if (!res.ok) {
        const msg = await friendlyError(res, '가입 실패')
        console.error('[register] failed', res.status, msg)
        setError(msg)
        return
      }

      const data = await res.json()
      if (autoLogin) {
        localStorage.setItem('auth_token', data.token)
      } else {
        sessionStorage.setItem('auth_token', data.token)
      }
      onRegistered(data.token)
    } catch (e) {
      console.error('[register] network error', e)
      setError('네트워크 오류입니다. 인터넷 연결을 확인해주세요.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950 px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white mb-2">YouTube Playlist Automator</h1>
          <p className="text-gray-400 text-sm">음악 영상 자동 생성 도구</p>
        </div>

        {mode === 'login' ? (
          <form onSubmit={handleLogin} className="bg-gray-900 rounded-xl border border-gray-800 p-6 space-y-4">
            <h2 className="text-lg font-semibold text-white mb-2">로그인</h2>

            <div>
              <label className="block text-sm text-gray-400 mb-1">이메일</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500"
                placeholder="example@email.com"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-1">비밀번호</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500"
                placeholder="비밀번호 입력"
              />
            </div>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={autoLogin}
                onChange={e => setAutoLogin(e.target.checked)}
                className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-purple-500 focus:ring-purple-500"
              />
              <span className="text-sm text-gray-400">자동 로그인</span>
            </label>

            {error && <p className="text-red-400 text-sm">{error}</p>}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-medium py-2.5 rounded-lg transition-colors text-sm"
            >
              {loading ? '로그인 중...' : '로그인'}
            </button>

            <div className="pt-2 border-t border-gray-800 text-center">
              <button
                type="button"
                onClick={() => { setMode('register'); setError('') }}
                className="text-sm text-gray-500 hover:text-purple-400 transition-colors"
              >
                계정이 없으신가요? <span className="text-purple-400">가입 신청</span>
              </button>
            </div>
          </form>
        ) : (
          <form onSubmit={handleRegister} className="bg-gray-900 rounded-xl border border-gray-800 p-6 space-y-4">
            <h2 className="text-lg font-semibold text-white mb-2">가입 신청</h2>

            <div>
              <label className="block text-sm text-gray-400 mb-1">이름 <span className="text-red-400">*</span></label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                required
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500"
                placeholder="홍길동"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-1">이메일 <span className="text-red-400">*</span></label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500"
                placeholder="example@email.com"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-1">비밀번호 <span className="text-red-400">*</span></label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                minLength={4}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500"
                placeholder="4자 이상"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-1">연락처</label>
              <input
                type="tel"
                value={phone}
                onChange={e => setPhone(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500"
                placeholder="010-1234-5678"
              />
            </div>

            <div>
              <label className="block text-sm text-gray-400 mb-1">유입 경로</label>
              <select
                value={referralSource}
                onChange={e => setReferralSource(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500"
              >
                <option value="">선택해주세요</option>
                <option value="지인 소개">지인 소개</option>
                <option value="SNS">SNS (인스타, 트위터 등)</option>
                <option value="유튜브">유튜브</option>
                <option value="블로그/카페">블로그/카페</option>
                <option value="검색">검색 (구글, 네이버 등)</option>
                <option value="기타">기타</option>
              </select>
            </div>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={autoLogin}
                onChange={e => setAutoLogin(e.target.checked)}
                className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-purple-500 focus:ring-purple-500"
              />
              <span className="text-sm text-gray-400">자동 로그인</span>
            </label>

            {error && <p className="text-red-400 text-sm">{error}</p>}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-medium py-2.5 rounded-lg transition-colors text-sm"
            >
              {loading ? '처리 중...' : '가입 신청'}
            </button>

            <div className="pt-2 border-t border-gray-800 text-center">
              <button
                type="button"
                onClick={() => { setMode('login'); setError('') }}
                className="text-sm text-gray-500 hover:text-purple-400 transition-colors"
              >
                이미 계정이 있으신가요? <span className="text-purple-400">로그인</span>
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
