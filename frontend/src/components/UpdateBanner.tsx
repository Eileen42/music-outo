import { useState, useEffect, useRef } from 'react'
import { api } from '../api/client'

type Phase = 'idle' | 'downloading' | 'installing' | 'restarting' | 'reconnect' | 'error'

/**
 * 새 버전 알림 + 원클릭 업데이트 배너.
 * 업데이트를 누르면 백엔드가 새 설치파일을 내려받아(진행률 폴링) 조용히 설치하고
 * 앱을 자동 재시작한다. 재시작이 끝나 서버가 다시 응답하면 화면을 새로고침해
 * 새 버전으로 전환한다. (설치본에서만 동작 — 개발모드면 배너 자체가 안 뜸)
 */
export default function UpdateBanner() {
  const [info, setInfo] = useState<{ latest: string; current: string } | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [percent, setPercent] = useState(0)
  const [mb, setMb] = useState<{ d: number; t: number }>({ d: 0, t: 0 })
  const [error, setError] = useState('')
  const timer = useRef<number | null>(null)

  useEffect(() => {
    let alive = true
    api.update.check()
      .then(d => { if (alive && d.update_available && d.latest) setInfo({ latest: d.latest, current: d.current }) })
      .catch(() => {})
    return () => { alive = false; if (timer.current) clearInterval(timer.current) }
  }, [])

  if (!info) return null

  const stop = () => { if (timer.current) { clearInterval(timer.current); timer.current = null } }

  const startPolling = () => {
    stop()
    timer.current = window.setInterval(async () => {
      try {
        const p = await api.update.progress()
        if (p.phase === 'error') { stop(); setPhase('error'); setError(p.error || '업데이트 실패'); return }
        setPercent(p.percent || 0)
        setMb({ d: p.downloaded_mb || 0, t: p.total_mb || 0 })
        if (p.phase === 'downloading' || p.phase === 'installing' || p.phase === 'restarting') setPhase(p.phase)
      } catch {
        // 서버가 응답 안 함 = 앱이 종료되고 설치·재시작 중.
        // /health 가 다시 뜨면(새 버전 기동 완료) 새로고침해서 갈아탄다.
        setPhase('reconnect')
        try {
          const r = await fetch(window.location.origin + '/health', { cache: 'no-store' })
          if (r.ok) { stop(); window.location.reload() }
        } catch { /* 아직 재시작 중 — 계속 시도 */ }
      }
    }, 700)
  }

  const onUpdate = async () => {
    if (phase !== 'idle' && phase !== 'error') return
    setPhase('downloading'); setError(''); setPercent(0)
    try {
      const r = await api.update.install()
      if (!r.ok) { setPhase('error'); setError(r.error || '업데이트를 시작할 수 없습니다'); return }
      startPolling()
    } catch {
      // install 요청 직후 끊겨도 설치는 진행 중일 수 있음 → 재접속 폴링
      startPolling()
    }
  }

  const Bar = ({ label, pct, sub }: { label: string; pct: number; sub?: string }) => (
    <div className="w-full max-w-xl flex flex-col gap-1">
      <div className="flex justify-between text-xs"><span>{label}</span><span>{sub}</span></div>
      <div className="w-full h-2 bg-violet-900/50 rounded overflow-hidden">
        <div className="h-full bg-white transition-[width] duration-300" style={{ width: `${Math.max(2, pct)}%` }} />
      </div>
    </div>
  )

  return (
    <div className="w-full bg-violet-600 text-white text-sm px-4 py-2 flex items-center justify-center gap-3">
      {phase === 'idle' && (
        <>
          <span>🎉 새 버전 <b>{info.latest}</b> 이 있습니다 (현재 {info.current})</span>
          <button onClick={onUpdate} className="bg-white text-violet-700 font-bold rounded px-3 py-1 hover:bg-violet-50">
            지금 업데이트
          </button>
        </>
      )}
      {phase === 'downloading' && (
        <Bar label="⬇️ 새 버전 다운로드 중..." pct={percent} sub={mb.t ? `${mb.d} / ${mb.t} MB (${percent}%)` : `${mb.d} MB`} />
      )}
      {phase === 'installing' && <Bar label="📦 설치 준비 중..." pct={100} sub="다운로드 완료" />}
      {(phase === 'restarting' || phase === 'reconnect') && (
        <span>🔄 설치 후 자동으로 다시 시작합니다... 창을 닫지 말고 잠시만 기다려주세요. (1~3분)</span>
      )}
      {phase === 'error' && (
        <>
          <span>⚠️ 업데이트 실패: {error}</span>
          <button onClick={onUpdate} className="bg-white text-violet-700 font-bold rounded px-3 py-1">다시 시도</button>
        </>
      )}
    </div>
  )
}
