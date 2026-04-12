import { useEffect, useState } from 'react'

interface Props {
  token: string
  onApproved: () => void
  onRejected: () => void
}

export default function PendingApproval({ token, onApproved, onRejected }: Props) {
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    const check = async () => {
      setChecking(true)
      try {
        const res = await fetch(`/api/auth/status?token=${token}`)
        const data = await res.json()
        if (data.status === 'approved') onApproved()
        else if (data.status === 'rejected') onRejected()
      } catch {
        // 조용히 실패 — 다음 주기에 재시도
      } finally {
        setChecking(false)
      }
    }

    check()
    const id = setInterval(check, 15000) // 15초마다 체크
    return () => clearInterval(id)
  }, [token, onApproved, onRejected])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950 px-4">
      <div className="w-full max-w-md text-center">
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-8">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-yellow-900/30 flex items-center justify-center">
            <span className="text-3xl">⏳</span>
          </div>

          <h2 className="text-xl font-bold text-white mb-2">승인 대기 중</h2>
          <p className="text-gray-400 text-sm mb-6">
            가입 신청이 접수되었습니다.<br />
            관리자 승인 후 이용하실 수 있습니다.
          </p>

          <div className="flex items-center justify-center gap-2 text-xs text-gray-600">
            {checking && <span className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" />}
            <span>자동으로 확인 중...</span>
          </div>
        </div>
      </div>
    </div>
  )
}
