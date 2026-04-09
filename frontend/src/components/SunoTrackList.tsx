'use client'
import { useState, useRef, useCallback } from 'react'
import type { SunoTrack } from '../types'
import { api } from '../api/client'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function resolveAudioUrl(url: string): string {
  if (!url) return ''
  if (url.startsWith('http')) return url
  return API_BASE + url
}

interface Props {
  projectId: string
  tracks: SunoTrack[]
  onChange: (tracks: SunoTrack[]) => void
}

export default function SunoTrackList({ projectId, tracks, onChange }: Props) {
  const [playingIdx, setPlayingIdx] = useState<number | null>(null)
  const [loadingIdx, setLoadingIdx] = useState<number | null>(null)
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null)
  const audioRefs = useRef<Map<number, HTMLAudioElement>>(new Map())

  const togglePlay = useCallback((idx: number, url: string) => {
    const audio = audioRefs.current.get(idx)
    if (!audio) return

    if (playingIdx === idx) {
      audio.pause()
      setPlayingIdx(null)
    } else {
      // 다른 재생 중인 것 멈춤
      if (playingIdx !== null) {
        audioRefs.current.get(playingIdx)?.pause()
      }
      setLoadingIdx(idx)
      audio.src = url
      audio.play()
        .then(() => { setPlayingIdx(idx); setLoadingIdx(null) })
        .catch(() => setLoadingIdx(null))
    }
  }, [playingIdx])

  const handleAudioEnded = (idx: number) => {
    if (playingIdx === idx) setPlayingIdx(null)
  }

  // ── 드래그앤드롭 ──────────────────────────────────────────────────────────

  const handleDragStart = (idx: number) => {
    setDragIdx(idx)
  }

  const handleDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault()
    setDragOverIdx(idx)
  }

  const handleDrop = async (e: React.DragEvent, targetIdx: number) => {
    e.preventDefault()
    if (dragIdx === null || dragIdx === targetIdx) {
      setDragIdx(null)
      setDragOverIdx(null)
      return
    }

    const newOrder = Array.from({ length: tracks.length }, (_, i) => i)
    newOrder.splice(dragIdx, 1)
    newOrder.splice(targetIdx, 0, dragIdx)

    setDragIdx(null)
    setDragOverIdx(null)

    try {
      const result = await api.trackDesign.reorderSunoTracks(projectId, newOrder)
      onChange(result.tracks)
    } catch {
      // 실패 시 원복
    }
  }

  // ── 위/아래 이동 ──────────────────────────────────────────────────────────

  const moveTrack = async (from: number, to: number) => {
    if (to < 0 || to >= tracks.length) return
    const newOrder = Array.from({ length: tracks.length }, (_, i) => i)
    newOrder.splice(from, 1)
    newOrder.splice(to, 0, from)

    try {
      const result = await api.trackDesign.reorderSunoTracks(projectId, newOrder)
      onChange(result.tracks)
      if (playingIdx === from) setPlayingIdx(to)
    } catch { /* 무시 */ }
  }

  // ── 삭제 ─────────────────────────────────────────────────────────────────

  const deleteTrack = async (idx: number) => {
    if (!confirm(`"${tracks[idx].title}" 트랙을 삭제하시겠습니까?`)) return
    if (playingIdx === idx) {
      audioRefs.current.get(idx)?.pause()
      setPlayingIdx(null)
    }
    await api.trackDesign.deleteSunoTrack(projectId, idx)
    onChange(tracks.filter((_, i) => i !== idx))
  }

  if (tracks.length === 0) {
    return (
      <div className="text-center py-8 text-gray-600 text-sm">
        생성된 트랙이 없습니다.
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-white">{tracks.length}개 트랙</span>
        <span className="text-xs text-gray-600">드래그하거나 ▲▼로 순서 변경</span>
      </div>

      {tracks.map((track, idx) => {
        const isPlaying = playingIdx === idx
        const isLoading = loadingIdx === idx
        const isDragging = dragIdx === idx
        const isDragOver = dragOverIdx === idx && dragIdx !== idx

        return (
          <div
            key={idx}
            draggable
            onDragStart={() => handleDragStart(idx)}
            onDragOver={e => handleDragOver(e, idx)}
            onDrop={e => handleDrop(e, idx)}
            onDragEnd={() => { setDragIdx(null); setDragOverIdx(null) }}
            className={`
              bg-gray-900 border rounded-xl px-4 py-3 flex items-center gap-3
              transition-all cursor-grab active:cursor-grabbing
              ${isDragging ? 'opacity-40 scale-95' : ''}
              ${isDragOver ? 'border-indigo-500 bg-indigo-900/20' : 'border-gray-800 hover:border-gray-700'}
            `}
          >
            {/* 번호 */}
            <span className="text-gray-600 text-xs w-5 text-center shrink-0 select-none">{idx + 1}</span>

            {/* 재생 버튼 */}
            {track.status === 'completed' && track.audio_url ? (
              <>
                <button
                  onClick={() => togglePlay(idx, resolveAudioUrl(track.audio_url))}
                  className={`
                    w-8 h-8 rounded-full flex items-center justify-center shrink-0 transition-colors
                    ${isPlaying ? 'bg-indigo-600 hover:bg-indigo-500' : 'bg-gray-700 hover:bg-gray-600'}
                  `}
                >
                  {isLoading ? (
                    <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  ) : isPlaying ? (
                    <span className="text-white text-xs">⏸</span>
                  ) : (
                    <span className="text-white text-xs ml-0.5">▶</span>
                  )}
                </button>
                <audio
                  ref={el => {
                    if (el) audioRefs.current.set(idx, el)
                    else audioRefs.current.delete(idx)
                  }}
                  onEnded={() => handleAudioEnded(idx)}
                  preload="none"
                />
              </>
            ) : (
              <div className="w-8 h-8 rounded-full bg-gray-800 flex items-center justify-center shrink-0">
                <span className="text-xs text-red-400">✗</span>
              </div>
            )}

            {/* 제목 + 상태 */}
            <div className="flex-1 min-w-0 select-none">
              <div className="text-sm text-white truncate">{track.title}</div>
              {track.status !== 'completed' && (
                <div className="text-xs text-red-400 mt-0.5">
                  {track.status === 'download_failed' ? '다운로드 실패' : '생성 실패'}
                </div>
              )}
            </div>

            {/* 순서 이동 버튼 */}
            <div className="flex gap-1 shrink-0">
              <button
                onClick={() => moveTrack(idx, idx - 1)}
                disabled={idx === 0}
                className="text-gray-600 hover:text-gray-300 disabled:opacity-20 disabled:cursor-not-allowed px-1 py-1 text-xs transition-colors"
                title="위로"
              >
                ▲
              </button>
              <button
                onClick={() => moveTrack(idx, idx + 1)}
                disabled={idx === tracks.length - 1}
                className="text-gray-600 hover:text-gray-300 disabled:opacity-20 disabled:cursor-not-allowed px-1 py-1 text-xs transition-colors"
                title="아래로"
              >
                ▼
              </button>
            </div>

            {/* 삭제 */}
            <button
              onClick={() => deleteTrack(idx)}
              className="text-gray-700 hover:text-red-400 text-xs px-2 py-1 transition-colors shrink-0"
              title="삭제"
            >
              ✕
            </button>
          </div>
        )
      })}
    </div>
  )
}
