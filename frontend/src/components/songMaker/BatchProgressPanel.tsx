import type { ReactNode } from 'react'

export interface BatchStatus {
  status: string
  phase?: string
  round?: number
  total_designed?: number
  total_batches: number
  completed_batches?: number
  completed?: number
  tracks_collected: number
  current_song?: string
  errors?: string[]
}

interface Props {
  batchStatus: BatchStatus | null
  onStop: () => void | Promise<void>
}

const PHASE_LABEL: Record<string, string> = {
  checking:   '파일 확인 중',
  collecting: 'Suno에서 다운로드 중',
  creating:   '곡 생성 중',
  waiting:    'Suno 처리 대기 중',
  verifying:  '검수 중',
}

/**
 * Suno 일괄 생성 진행 상황 표시.
 *
 * status 가 running / completed / failed 세 가지 케이스에 대한 시각화를
 * 한 곳에 모았다. SongMaker 의 거대한 return 에서 분리.
 */
export default function BatchProgressPanel({ batchStatus, onStop }: Props): ReactNode {
  if (!batchStatus) return null

  const wrapperColor =
    batchStatus.status === 'running'   ? 'bg-green-900/20 border-green-700/50 text-green-300'
    : batchStatus.status === 'completed' ? 'bg-blue-900/20 border-blue-700/50 text-blue-300'
    :                                       'bg-red-900/20 border-red-700/50 text-red-300'

  return (
    <div className={`mb-4 p-3 rounded-xl border text-sm ${wrapperColor}`}>
      {batchStatus.status === 'running' && (() => {
        const done  = batchStatus.completed_batches ?? batchStatus.completed ?? 0
        const total = batchStatus.total_batches || 1
        const pct   = Math.round((done / total) * 100)
        const phaseLabel = PHASE_LABEL[batchStatus.phase || ''] || '진행 중'

        return (
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="inline-block w-3 h-3 border-2 border-green-400/30 border-t-green-400 rounded-full animate-spin shrink-0" />
              <div className="flex-1">
                <div className="font-semibold">
                  {phaseLabel} {done}/{total}
                  {batchStatus.round && batchStatus.round > 1 && (
                    <span className="text-yellow-300 ml-2 text-xs font-normal">라운드 {batchStatus.round}</span>
                  )}
                </div>
                {batchStatus.current_song && (
                  <div className="text-xs text-green-200/70 mt-0.5">"{batchStatus.current_song}"</div>
                )}
              </div>
              <span className="text-xs text-green-400 shrink-0">
                {batchStatus.tracks_collected || 0}개 다운됨
              </span>
              <button
                onClick={onStop}
                className="text-xs bg-red-800 hover:bg-red-700 text-white px-3 py-1.5 rounded-lg font-semibold transition-colors shrink-0"
              >
                ⏹ 중지
              </button>
            </div>
            <div className="w-full bg-green-900/50 rounded-full h-2">
              <div
                className="bg-green-500 h-2 rounded-full transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
            <div className="text-[10px] text-green-500/60 text-right">{pct}%</div>
          </div>
        )
      })()}
      {batchStatus.status === 'completed' && (
        <div>
          ✓ Suno 생성 완료 — {batchStatus.tracks_collected || 0}개 다운로드
          {batchStatus.errors && batchStatus.errors.length > 0 && (
            <div className="text-xs text-yellow-400 mt-1">⚠ 에러 {batchStatus.errors.length}건</div>
          )}
        </div>
      )}
      {batchStatus.status === 'failed' && (
        <div>
          ✗ Suno 생성 실패
          {batchStatus.errors?.map((e, i) => (
            <div key={i} className="text-xs text-red-400/80 mt-1">{e}</div>
          ))}
        </div>
      )}
    </div>
  )
}
