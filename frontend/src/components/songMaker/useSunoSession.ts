import { useEffect, useState } from 'react'
import { api } from '../../api/client'

export interface SunoSession {
  session_exists: boolean
  login_status: string
}

interface ApiError {
  response?: { data?: { detail?: string } }
}

/**
 * Suno 로그인 세션 상태 + 3개 핸들러를 관리.
 *
 * 사용처(SongMaker)는 반환값을 destructure 해 JSX 와 핸들러에 그대로 넘기면 된다.
 * 초기 mount 시 /api/suno/status 를 한 번 호출해 세션 존재 여부를 확인한다.
 */
export function useSunoSession() {
  const [sunoSession, setSunoSession] = useState<SunoSession | null>(null)
  const [sunoLoginLoading, setSunoLoginLoading] = useState(false)
  const [sunoLoginMsg, setSunoLoginMsg] = useState('')

  // mount 시 1회 — 세션 살아있는지 ping
  useEffect(() => {
    api.suno.status().then(setSunoSession).catch(() => setSunoSession(null))
  }, [])

  const handleSunoLogin = async () => {
    setSunoLoginLoading(true)
    setSunoLoginMsg('')
    try {
      const res = await api.suno.openLogin()
      setSunoLoginMsg(res.message)
      setSunoSession(prev => ({ ...prev!, login_status: 'waiting' }))
    } catch (e: unknown) {
      setSunoLoginMsg((e as ApiError)?.response?.data?.detail ?? '브라우저 열기 실패')
    } finally {
      setSunoLoginLoading(false)
    }
  }

  const handleSunoConfirm = async () => {
    setSunoLoginLoading(true)
    try {
      const res = await api.suno.confirmLogin()
      setSunoLoginMsg(res.message)
      const status = await api.suno.status()
      setSunoSession(status)
    } catch (e: unknown) {
      setSunoLoginMsg((e as ApiError)?.response?.data?.detail ?? '세션 저장 실패')
    } finally {
      setSunoLoginLoading(false)
    }
  }

  const handleSunoLogout = async () => {
    await api.suno.cancelLogin().catch(() => {})
    await api.suno.deleteSession()
    setSunoSession({ session_exists: false, login_status: 'idle' })
    setSunoLoginMsg('')
  }

  return {
    sunoSession,
    sunoLoginLoading,
    sunoLoginMsg,
    handleSunoLogin,
    handleSunoConfirm,
    handleSunoLogout,
  }
}
