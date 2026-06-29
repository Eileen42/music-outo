import { useState, useEffect } from 'react'
import { api } from '../api/client'

/**
 * 새 버전이 있으면 화면 맨 위에 보라색 알림 배너를 띄운다.
 * "지금 업데이트" 를 누르면 백엔드가 새 설치파일을 받아 조용히 설치하고
 * 프로그램을 자동으로 다시 시작한다. (설치본에서만 동작 — 개발모드면 거부됨)
 */
export default function UpdateBanner() {
  const [info, setInfo] = useState<{ latest: string; current: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  // 앱 로드 시 1회 최신버전 확인 (조용히 실패 — 인터넷 없거나 개발모드면 그냥 안 뜸)
  useEffect(() => {
    let alive = true
    api.update
      .check()
      .then(d => {
        if (alive && d.update_available && d.latest) {
          setInfo({ latest: d.latest, current: d.current })
        }
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  if (!info) return null

  const onUpdate = async () => {
    if (busy) return
    setBusy(true)
    setMsg('새 버전을 내려받아 설치하는 중입니다... 잠시 후 프로그램이 자동으로 다시 시작됩니다. (창을 닫지 마세요)')
    try {
      const r = await api.update.install()
      if (!r.ok) {
        setMsg('업데이트 실패: ' + (r.error || '알 수 없는 오류'))
        setBusy(false)
      }
      // 성공 시 앱이 곧 종료/재시작되므로 이 화면은 자연스럽게 사라진다.
    } catch {
      // 설치가 시작되면 앱이 종료되며 연결이 끊긴다 — 정상 동작이다.
      setMsg('설치를 진행 중입니다. 잠시 후 프로그램이 다시 열립니다...')
    }
  }

  return (
    <div className="w-full bg-violet-600 text-white text-sm px-4 py-2 flex items-center justify-center gap-3">
      {busy ? (
        <span>⏳ {msg}</span>
      ) : (
        <>
          <span>
            🎉 새 버전 <b>{info.latest}</b> 이 있습니다 (현재 {info.current})
          </span>
          <button
            onClick={onUpdate}
            className="bg-white text-violet-700 font-bold rounded px-3 py-1 hover:bg-violet-50"
          >
            지금 업데이트
          </button>
        </>
      )}
    </div>
  )
}
