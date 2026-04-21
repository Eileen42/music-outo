import { useState, useEffect, useCallback } from 'react'

interface User {
  id: number
  name: string
  email: string
  phone: string | null
  referral_source: string | null
  status: string
  created_at: string
  approved_at: string | null
}

interface Props {
  onBack: () => void
}

interface ResetResult {
  name: string
  email: string
  temporary_password: string
}

export default function AdminPage({ onBack }: Props) {
  const [users, setUsers] = useState<User[]>([])
  const [filter, setFilter] = useState<string>('')
  const [secret, setSecret] = useState(() => localStorage.getItem('admin_secret') || '')
  const [authenticated, setAuthenticated] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [resetResult, setResetResult] = useState<ResetResult | null>(null)

  const fetchUsers = useCallback(async () => {
    setLoading(true)
    try {
      const params = filter ? `?status=${filter}` : ''
      const res = await fetch(`/api/admin/users${params}`, {
        headers: { Authorization: `Bearer ${secret}` },
      })
      if (!res.ok) {
        if (res.status === 403) {
          setAuthenticated(false)
          setError('관리자 비밀번호가 올바르지 않습니다')
          return
        }
        throw new Error('API error')
      }
      const data = await res.json()
      setUsers(data.users)
      setAuthenticated(true)
      setError('')
    } catch {
      setError('사용자 목록을 불러올 수 없습니다')
    } finally {
      setLoading(false)
    }
  }, [secret, filter])

  useEffect(() => {
    if (secret) fetchUsers()
  }, [fetchUsers, secret])

  const updateStatus = async (id: number, status: string) => {
    await fetch(`/api/admin/users/${id}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${secret}`,
      },
      body: JSON.stringify({ status }),
    })
    fetchUsers()
  }

  const resetPassword = async (u: User) => {
    if (!confirm(`${u.name}(${u.email}) 계정의 비밀번호를 임시값으로 초기화할까요?`)) return
    try {
      const res = await fetch('/api/admin/reset-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${secret}`,
        },
        body: JSON.stringify({ user_id: u.id }),
      })
      const data = await res.json()
      if (!res.ok) {
        alert(data.error || '초기화에 실패했습니다')
        return
      }
      setResetResult({
        name: data.name,
        email: data.email,
        temporary_password: data.temporary_password,
      })
    } catch (e) {
      console.error('[reset-password]', e)
      alert('네트워크 오류로 실패했습니다')
    }
  }

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault()
    localStorage.setItem('admin_secret', secret)
    fetchUsers()
  }

  const statusBadge = (status: string) => {
    const styles: Record<string, string> = {
      pending: 'bg-yellow-900/50 text-yellow-300 border-yellow-700',
      approved: 'bg-green-900/50 text-green-300 border-green-700',
      rejected: 'bg-red-900/50 text-red-300 border-red-700',
      blocked: 'bg-gray-800 text-gray-400 border-gray-700',
    }
    const labels: Record<string, string> = {
      pending: '대기',
      approved: '승인',
      rejected: '거절',
      blocked: '차단',
    }
    return (
      <span className={`text-xs px-2 py-0.5 rounded-full border ${styles[status] || styles.pending}`}>
        {labels[status] || status}
      </span>
    )
  }

  if (!authenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950 px-4">
        <div className="w-full max-w-sm">
          <form onSubmit={handleLogin} className="bg-gray-900 rounded-xl border border-gray-800 p-6 space-y-4">
            <h2 className="text-lg font-semibold text-white">관리자 로그인</h2>
            <input
              type="password"
              value={secret}
              onChange={e => setSecret(e.target.value)}
              placeholder="관리자 비밀번호"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500"
            />
            {error && <p className="text-red-400 text-xs">{error}</p>}
            <div className="flex gap-2">
              <button type="button" onClick={onBack} className="flex-1 bg-gray-800 text-gray-300 py-2 rounded-lg text-sm hover:bg-gray-700">
                ���아가기
              </button>
              <button type="submit" className="flex-1 bg-purple-600 text-white py-2 rounded-lg text-sm hover:bg-purple-500">
                로그인
              </button>
            </div>
          </form>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-950 p-6">
      {resetResult && (
        <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center px-4">
          <div className="w-full max-w-md bg-gray-900 border border-purple-700 rounded-2xl p-6 space-y-4">
            <div className="flex items-start gap-3">
              <span className="text-3xl">🔐</span>
              <div>
                <h3 className="text-lg font-bold text-white">임시 비밀번호가 발급되었습니다</h3>
                <p className="text-xs text-gray-400 mt-1">
                  이 비밀번호는 <strong className="text-yellow-300">이 화면에서만</strong> 확인할 수 있습니다.
                  사용자에게 카톡·문자 등으로 전달해주세요.
                </p>
              </div>
            </div>

            <div className="bg-gray-800 rounded-xl p-4 space-y-2">
              <div className="flex justify-between text-xs text-gray-400">
                <span>이름</span>
                <span className="text-gray-200">{resetResult.name}</span>
              </div>
              <div className="flex justify-between text-xs text-gray-400">
                <span>이메일</span>
                <span className="text-gray-200">{resetResult.email}</span>
              </div>
              <div className="border-t border-gray-700 pt-2 mt-2">
                <div className="text-xs text-gray-400 mb-1">임시 비밀번호</div>
                <div className="flex items-center gap-2">
                  <code className="flex-1 bg-gray-950 text-purple-300 text-lg font-mono px-3 py-2 rounded select-all">
                    {resetResult.temporary_password}
                  </code>
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(resetResult.temporary_password)
                    }}
                    className="text-xs bg-purple-700 hover:bg-purple-600 text-white px-3 py-2 rounded"
                  >
                    복사
                  </button>
                </div>
              </div>
            </div>

            <div className="bg-yellow-950/40 border border-yellow-800 rounded-lg px-3 py-2 text-xs text-yellow-200">
              💡 사용자는 이 비밀번호로 로그인한 뒤 원하는 값으로 다시 변경할 수 있도록 안내해주세요.
            </div>

            <button
              onClick={() => setResetResult(null)}
              className="w-full bg-purple-600 hover:bg-purple-500 text-white font-medium py-2.5 rounded-lg text-sm"
            >
              확인
            </button>
          </div>
        </div>
      )}

      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-bold text-white">사용자 관리</h1>
          <button onClick={onBack} className="text-sm text-gray-500 hover:text-gray-300">
            ← 돌아가기
          </button>
        </div>

        {/* 필터 */}
        <div className="flex gap-2 mb-4">
          {[
            { value: '', label: '전체' },
            { value: 'pending', label: '대기' },
            { value: 'approved', label: '승인' },
            { value: 'rejected', label: '거절' },
            { value: 'blocked', label: '차단' },
          ].map(f => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={`text-xs px-3 py-1.5 rounded-lg transition-colors ${
                filter === f.value
                  ? 'bg-purple-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-white'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {loading && <p className="text-gray-500 text-sm">로딩 중...</p>}

        {/* 사용자 테이블 */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-500 text-xs">
                <th className="text-left px-4 py-3">이름</th>
                <th className="text-left px-4 py-3">이메일</th>
                <th className="text-left px-4 py-3">연락처</th>
                <th className="text-left px-4 py-3">유입경로</th>
                <th className="text-left px-4 py-3">상태</th>
                <th className="text-left px-4 py-3">가입일</th>
                <th className="text-left px-4 py-3">관리</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className="px-4 py-3 text-white">{u.name}</td>
                  <td className="px-4 py-3 text-gray-400">{u.email}</td>
                  <td className="px-4 py-3 text-gray-400">{u.phone || '-'}</td>
                  <td className="px-4 py-3 text-gray-400">{u.referral_source || '-'}</td>
                  <td className="px-4 py-3">{statusBadge(u.status)}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">
                    {new Date(u.created_at).toLocaleDateString('ko-KR')}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
                      {u.status !== 'approved' && (
                        <button
                          onClick={() => updateStatus(u.id, 'approved')}
                          className="text-xs px-2 py-1 rounded bg-green-800/50 text-green-300 hover:bg-green-700/50"
                        >
                          승인
                        </button>
                      )}
                      {u.status !== 'rejected' && u.status !== 'blocked' && (
                        <button
                          onClick={() => updateStatus(u.id, 'rejected')}
                          className="text-xs px-2 py-1 rounded bg-red-800/50 text-red-300 hover:bg-red-700/50"
                        >
                          거절
                        </button>
                      )}
                      {u.status === 'approved' && (
                        <button
                          onClick={() => updateStatus(u.id, 'blocked')}
                          className="text-xs px-2 py-1 rounded bg-gray-700 text-gray-400 hover:bg-gray-600"
                        >
                          차단
                        </button>
                      )}
                      <button
                        onClick={() => resetPassword(u)}
                        className="text-xs px-2 py-1 rounded bg-purple-900/50 text-purple-300 hover:bg-purple-800/50"
                        title="비밀번호를 임시값으로 초기화"
                      >
                        🔐 비번 초기화
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {users.length === 0 && !loading && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-600">
                    사용자가 없습니다
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
