import { useState } from 'react'

interface Props {
  initialEmail?: string
  onClose: () => void
  onComplete: (email: string) => void  // 완료 시 로그인 폼에 이메일 채워넣을 수 있도록
}

type Step = 'request' | 'verify'

export default function ForgotPasswordModal({ initialEmail = '', onClose, onComplete }: Props) {
  const [step, setStep] = useState<Step>('request')
  const [email, setEmail] = useState(initialEmail)
  const [code, setCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')

  const requestCode = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(''); setInfo(''); setLoading(true)
    try {
      const res = await fetch('/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      let data: Record<string, unknown> = {}
      try { data = await res.json() } catch { /* ignore */ }

      if (!res.ok) {
        const msg = (data.error || data.message) as string | undefined
        setError(msg || `오류가 발생했습니다 (HTTP ${res.status})`)
        return
      }
      setInfo((data.message as string) || '인증번호가 발송되었습니다.')
      setStep('verify')
    } catch (e) {
      console.error('[forgot-password]', e)
      setError('네트워크 오류입니다. 인터넷 연결을 확인해주세요.')
    } finally {
      setLoading(false)
    }
  }

  const submitReset = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(''); setInfo(''); setLoading(true)
    try {
      const res = await fetch('/api/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code, new_password: newPassword }),
      })
      let data: Record<string, unknown> = {}
      try { data = await res.json() } catch { /* ignore */ }

      if (!res.ok) {
        const msg = (data.error || data.message) as string | undefined
        setError(msg || `오류가 발생했습니다 (HTTP ${res.status})`)
        return
      }
      onComplete(email)
    } catch (e) {
      console.error('[reset-password]', e)
      setError('네트워크 오류입니다. 인터넷 연결을 확인해주세요.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center px-4">
      <div className="w-full max-w-md bg-gray-900 border border-gray-800 rounded-2xl p-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold text-white">비밀번호 찾기</h3>
            <p className="text-xs text-gray-500 mt-1">
              {step === 'request' ? '가입 시 사용한 이메일로 인증번호를 보냅니다' : '이메일로 받은 6자리 인증번호를 입력하세요'}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-600 hover:text-gray-400 text-lg leading-none">✕</button>
        </div>

        {step === 'request' ? (
          <form onSubmit={requestCode} className="space-y-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">이메일</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                autoFocus
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500"
                placeholder="example@email.com"
              />
            </div>
            {error && <p className="text-red-400 text-xs">{error}</p>}
            {info && <p className="text-green-400 text-xs">{info}</p>}
            <button
              type="submit"
              disabled={loading || !email}
              className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 text-white py-2.5 rounded-lg text-sm font-medium"
            >
              {loading ? '발송 중...' : '인증번호 받기'}
            </button>
          </form>
        ) : (
          <form onSubmit={submitReset} className="space-y-4">
            <div className="bg-gray-800/50 rounded-lg px-3 py-2 text-xs text-gray-400">
              📧 <strong className="text-gray-200">{email}</strong> 로 인증번호를 보냈습니다. 메일이 안 보이면 스팸함도 확인해주세요.
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">인증번호 (6자리)</label>
              <input
                type="text"
                value={code}
                onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                required
                autoFocus
                inputMode="numeric"
                maxLength={6}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-xl tracking-[0.3em] text-center font-mono focus:outline-none focus:border-purple-500"
                placeholder="000000"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">새 비밀번호</label>
              <input
                type="password"
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                required
                minLength={4}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500"
                placeholder="4자 이상"
              />
            </div>
            {error && <p className="text-red-400 text-xs">{error}</p>}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => { setStep('request'); setCode(''); setNewPassword(''); setError('') }}
                className="flex-1 bg-gray-800 hover:bg-gray-700 text-gray-300 py-2.5 rounded-lg text-sm"
              >
                다시 받기
              </button>
              <button
                type="submit"
                disabled={loading || code.length !== 6 || newPassword.length < 4}
                className="flex-1 bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500 text-white py-2.5 rounded-lg text-sm font-medium"
              >
                {loading ? '변경 중...' : '비밀번호 변경'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
