import { useState, useRef, useCallback, type DragEvent } from 'react'
import type { Project, Track, RepeatConfig } from '../types'
import { api } from '../api/client'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

interface Props {
  project: Project
  onRefresh: () => void
}

interface PendingFile {
  id: string
  file: File
  title: string
  lyrics: string
  status: 'waiting' | 'uploading' | 'done' | 'error'
  error?: string
}

function fmtDuration(sec: number) {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function stemName(filename: string) {
  return filename.replace(/\.[^.]+$/, '')
}

export default function TrackEditor({ project, onRefresh }: Props) {
  const [pending, setPending] = useState<PendingFile[]>([])
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [transcribing, setTranscribing] = useState<string | null>(null)
  const [editingLyrics, setEditingLyrics] = useState<string | null>(null)
  const [lyricsDraft, setLyricsDraft] = useState('')
  const [savingRepeat, setSavingRepeat] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null)

  const defaultRepeat: RepeatConfig = { mode: 'count', count: 1, target_minutes: 60 }
  const [repeat, setRepeat] = useState<RepeatConfig>(project.repeat ?? defaultRepeat)

  const tracks = [...(project.tracks || [])].sort((a, b) => a.order - b.order)

  const togglePlay = useCallback((trackId: string, storedPath: string) => {
    if (playingId === trackId) {
      audioRef.current?.pause()
      setPlayingId(null)
      return
    }
    if (audioRef.current) audioRef.current.pause()
    const url = storedPath.startsWith('http') ? storedPath : `${API_BASE}/storage/${storedPath.split('storage/')[1] || storedPath}`
    const audio = new Audio(url.replace(/\\/g, '/'))
    audio.onended = () => setPlayingId(null)
    audio.play().catch(() => {})
    audioRef.current = audio
    setPlayingId(trackId)
  }, [playingId])

  const handleReorder = async (fromIdx: number, toIdx: number) => {
    if (fromIdx === toIdx) return
    const ids = tracks.map(t => t.id)
    const [moved] = ids.splice(fromIdx, 1)
    ids.splice(toIdx, 0, moved)
    try {
      await api.tracks.reorder(project.id, ids)
      await onRefresh()
    } catch { /* ignore */ }
  }
  const totalDuration = tracks.reduce((s, t) => s + t.duration, 0)

  // 반복 설정 기반 계산
  const calcRepeat = () => {
    if (totalDuration === 0) return { finalCount: repeat.count, finalMinutes: 0 }
    if (repeat.mode === 'count') {
      return {
        finalCount: repeat.count,
        finalMinutes: Math.round((totalDuration * repeat.count) / 60),
      }
    } else {
      const targetSec = repeat.target_minutes * 60
      const count = Math.max(1, Math.ceil(targetSec / totalDuration))
      return {
        finalCount: count,
        finalMinutes: Math.round((totalDuration * count) / 60),
      }
    }
  }

  const handleSaveRepeat = async () => {
    setSavingRepeat(true)
    try {
      await api.projects.updateRepeat(project.id, repeat)
      await onRefresh()
    } finally {
      setSavingRepeat(false)
    }
  }

  const ACCEPTED = ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.opus']

  const addFiles = (files: File[]) => {
    const audioFiles = files.filter(f =>
      ACCEPTED.some(ext => f.name.toLowerCase().endsWith(ext))
    )
    if (audioFiles.length === 0) return
    const newItems: PendingFile[] = audioFiles.map(f => ({
      id: Math.random().toString(36).slice(2),
      file: f,
      title: stemName(f.name),
      lyrics: '',
      status: 'waiting',
    }))
    setPending(prev => [...prev, ...newItems])
  }

  const handleDragOver = (e: DragEvent) => { e.preventDefault(); setDragging(true) }
  const handleDragLeave = () => setDragging(false)
  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    addFiles(Array.from(e.dataTransfer.files))
  }
  const handleFileChange = () => {
    if (fileRef.current?.files) {
      addFiles(Array.from(fileRef.current.files))
      fileRef.current.value = ''
    }
  }

  const removePending = (id: string) =>
    setPending(prev => prev.filter(p => p.id !== id))

  const updatePending = (id: string, patch: Partial<PendingFile>) =>
    setPending(prev => prev.map(p => p.id === id ? { ...p, ...patch } : p))

  const handleUploadAll = async () => {
    const waiting = pending.filter(p => p.status === 'waiting')
    if (waiting.length === 0) return
    setUploading(true)

    for (const item of waiting) {
      updatePending(item.id, { status: 'uploading' })
      try {
        await api.tracks.upload(project.id, item.file, item.title, item.lyrics)
        updatePending(item.id, { status: 'done' })
      } catch (err: unknown) {
        const msg = err as { response?: { data?: { detail?: string } }; message?: string }
        updatePending(item.id, {
          status: 'error',
          error: msg?.response?.data?.detail || msg?.message || '업로드 실패',
        })
      }
    }

    await onRefresh()
    setUploading(false)
    // 완료된 항목만 제거
    setPending(prev => prev.filter(p => p.status !== 'done'))
  }

  const handleTranscribe = async (track: Track) => {
    setTranscribing(track.id)
    try {
      await api.tracks.transcribe(project.id, track.id)
      setTimeout(() => { onRefresh(); setTranscribing(null) }, 3000)
    } catch {
      setTranscribing(null)
    }
  }

  const handleUpdateTitle = async (trackId: string, value: string, original: string) => {
    if (value === original) return
    await api.tracks.update(project.id, trackId, { title: value })
    await onRefresh()
  }

  const handleDeleteTrack = async (trackId: string) => {
    if (!confirm('이 트랙을 삭제하시겠습니까?')) return
    await api.tracks.delete(project.id, trackId)
    await onRefresh()
  }

  const openLyricsEdit = (track: Track) => {
    setEditingLyrics(track.id)
    setLyricsDraft(track.lyrics || '')
  }

  const saveLyrics = async (trackId: string) => {
    await api.tracks.update(project.id, trackId, { lyrics: lyricsDraft })
    setEditingLyrics(null)
    await onRefresh()
  }

  const waitingCount = pending.filter(p => p.status === 'waiting').length

  return (
    <div>
      {/* ── 드래그앤드롭 업로드 영역 ── */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileRef.current?.click()}
        className={`flex flex-col items-center justify-center gap-3 border-2 border-dashed rounded-2xl px-6 py-10 cursor-pointer transition-all mb-4 ${
          dragging
            ? 'border-purple-500 bg-purple-900/20 scale-[1.01]'
            : 'border-gray-700 bg-gray-900/50 hover:border-gray-600 hover:bg-gray-900'
        }`}
      >
        <span className="text-4xl">{dragging ? '📂' : '🎵'}</span>
        <div className="text-center">
          <p className="text-sm font-semibold text-gray-300">
            {dragging ? '여기에 놓으세요!' : '파일을 드래그하거나 클릭해서 선택'}
          </p>
          <p className="text-xs text-gray-600 mt-1">여러 파일 한 번에 추가 가능 · MP3, WAV, FLAC, AAC, OGG, M4A, OPUS</p>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept=".mp3,.wav,.flac,.aac,.ogg,.m4a,.opus"
          multiple
          className="hidden"
          onChange={handleFileChange}
        />
      </div>

      {/* ── 업로드 대기 목록 ── */}
      {pending.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4 mb-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-200">
              추가 대기 중 <span className="text-gray-500 font-normal">({pending.length}개)</span>
            </h3>
            <div className="flex gap-2">
              <button
                onClick={() => setPending([])}
                className="text-xs text-gray-600 hover:text-red-400 px-2 py-1 transition-colors"
              >
                전체 취소
              </button>
              <button
                onClick={handleUploadAll}
                disabled={uploading || waitingCount === 0}
                className="text-xs bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white px-4 py-1.5 rounded-lg font-semibold transition-colors"
              >
                {uploading ? '업로드 중...' : `▶ 모두 추가 (${waitingCount}개)`}
              </button>
            </div>
          </div>

          <div className="space-y-2">
            {pending.map(item => (
              <div
                key={item.id}
                className={`rounded-xl p-3 border transition-colors ${
                  item.status === 'done'    ? 'bg-green-950/30 border-green-800' :
                  item.status === 'error'   ? 'bg-red-950/30 border-red-800' :
                  item.status === 'uploading' ? 'bg-purple-950/30 border-purple-800' :
                  'bg-gray-800 border-gray-700'
                }`}
              >
                <div className="flex items-center gap-3">
                  {/* 상태 아이콘 */}
                  <span className="text-base shrink-0">
                    {item.status === 'uploading' ? '⏳' :
                     item.status === 'done'      ? '✅' :
                     item.status === 'error'     ? '❌' : '🎵'}
                  </span>

                  {/* 제목 편집 */}
                  <input
                    value={item.title}
                    onChange={e => updatePending(item.id, { title: e.target.value })}
                    disabled={item.status !== 'waiting'}
                    className="flex-1 bg-transparent text-white text-sm border-b border-gray-700 focus:border-purple-500 focus:outline-none pb-0.5 disabled:text-gray-500"
                    placeholder="곡 제목"
                  />

                  <span className="text-xs text-gray-600 shrink-0">
                    {(item.file.size / 1024 / 1024).toFixed(1)} MB
                  </span>

                  {item.status === 'waiting' && (
                    <button
                      onClick={() => removePending(item.id)}
                      className="text-gray-600 hover:text-red-400 text-xs px-1 shrink-0"
                    >✕</button>
                  )}
                </div>

                {item.status === 'error' && (
                  <p className="text-xs text-red-400 mt-1.5 ml-8">{item.error}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 등록된 트랙 목록 ── */}
      {tracks.length === 0 && pending.length === 0 ? (
        <div className="text-center py-12 text-gray-700">
          <div className="text-4xl mb-3">🎵</div>
          <div className="text-sm">등록된 트랙이 없습니다.</div>
          <div className="text-xs mt-1">위에서 음악 파일을 추가해보세요.</div>
        </div>
      ) : tracks.length > 0 && (
        <>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
              등록된 트랙 ({tracks.length}개)
            </h3>
            <span className="text-xs text-gray-600">총 {fmtDuration(totalDuration)}</span>
          </div>

          <div className="space-y-2">
            {tracks.map((track, idx) => (
              <div
                key={track.id}
                draggable
                onDragStart={() => setDragIdx(idx)}
                onDragOver={(e) => { e.preventDefault(); setDragOverIdx(idx) }}
                onDragEnd={() => {
                  if (dragIdx !== null && dragOverIdx !== null && dragIdx !== dragOverIdx) {
                    handleReorder(dragIdx, dragOverIdx)
                  }
                  setDragIdx(null)
                  setDragOverIdx(null)
                }}
                className={`bg-gray-900 border rounded-2xl p-4 transition-all ${
                  dragOverIdx === idx ? 'border-purple-500 ring-1 ring-purple-500' : 'border-gray-800 hover:border-gray-700'
                }`}
              >
                <div className="flex items-start gap-3">
                  <div className="flex flex-col items-center gap-1 shrink-0 mt-0.5">
                    <span className="text-gray-500 cursor-grab active:cursor-grabbing select-none text-sm" title="드래그하여 순서 변경">⠿</span>
                    <span className="w-7 h-7 flex items-center justify-center rounded-full bg-gray-800 text-gray-500 font-mono text-xs">
                      {idx + 1}
                    </span>
                    {track.stored_path && (
                      <button
                        onClick={() => togglePlay(track.id, track.stored_path)}
                        className={`w-7 h-7 rounded-full flex items-center justify-center text-xs transition-colors ${
                          playingId === track.id ? 'bg-purple-600 text-white' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                        }`}
                        title="재생/정지"
                      >
                        {playingId === track.id ? '⏸' : '▶'}
                      </button>
                    )}
                  </div>

                  <div className="flex-1 min-w-0">
                    {/* 제목 */}
                    <input
                      defaultValue={track.title}
                      onBlur={e => handleUpdateTitle(track.id, e.target.value, track.title)}
                      className="w-full bg-transparent text-white rounded-lg px-2 py-1 text-sm border border-transparent hover:border-gray-700 focus:border-purple-500 focus:bg-gray-800 focus:outline-none mb-1"
                    />

                    {/* 메타 */}
                    <div className="flex items-center gap-2 flex-wrap px-2 mb-2">
                      <span className="text-xs text-gray-500 font-mono">{fmtDuration(track.duration)}</span>
                      <span className="text-gray-700">·</span>
                      <span className="text-xs text-gray-600 truncate max-w-[180px]">{track.filename}</span>
                      {track.waveform_file && (
                        <span className="text-[11px] bg-green-900/40 text-green-400 border border-green-800 px-1.5 py-0.5 rounded-full">파형 ✓</span>
                      )}
                      {track.lyrics && editingLyrics !== track.id && (
                        <span className="text-[11px] bg-blue-900/40 text-blue-400 border border-blue-800 px-1.5 py-0.5 rounded-full">가사 ✓</span>
                      )}
                    </div>

                    {/* 가사 편집 */}
                    {editingLyrics === track.id ? (
                      <div className="px-2">
                        <textarea
                          value={lyricsDraft}
                          onChange={e => setLyricsDraft(e.target.value)}
                          rows={5}
                          className="w-full bg-gray-800 text-gray-200 rounded-xl px-3 py-2 text-xs border border-purple-600 focus:outline-none resize-y font-mono leading-relaxed"
                          placeholder="가사를 입력하세요..."
                          autoFocus
                        />
                        <div className="flex gap-2 mt-2">
                          <button onClick={() => saveLyrics(track.id)} className="text-xs bg-purple-600 hover:bg-purple-500 text-white px-3 py-1.5 rounded-lg">저장</button>
                          <button onClick={() => setEditingLyrics(null)} className="text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 px-3 py-1.5 rounded-lg">취소</button>
                        </div>
                      </div>
                    ) : (
                      <div className="px-2">
                        {track.lyrics ? (
                          <div
                            onClick={() => openLyricsEdit(track)}
                            className="text-xs text-gray-400 bg-gray-800 rounded-xl p-3 max-h-16 overflow-y-auto cursor-pointer hover:bg-gray-750 transition-colors font-mono leading-relaxed whitespace-pre-wrap"
                            title="클릭해서 수정"
                          >
                            {track.lyrics}
                          </div>
                        ) : (
                          <button
                            onClick={() => openLyricsEdit(track)}
                            className="text-xs text-gray-600 hover:text-gray-400 border border-dashed border-gray-700 hover:border-gray-600 rounded-xl px-3 py-2 w-full text-left transition-colors"
                          >
                            + 가사 입력
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  {/* 액션 */}
                  <div className="flex flex-col gap-1 shrink-0">
                    <button
                      onClick={() => handleTranscribe(track)}
                      disabled={transcribing === track.id}
                      className="text-xs bg-gray-800 hover:bg-gray-700 disabled:opacity-40 text-gray-300 px-2.5 py-1.5 rounded-lg whitespace-nowrap"
                      title="Whisper AI로 가사 자동 추출"
                    >
                      {transcribing === track.id ? '⏳' : '🎤 AI 추출'}
                    </button>
                    <button
                      onClick={() => handleDeleteTrack(track.id)}
                      className="text-xs text-gray-600 hover:text-red-400 px-2 py-1.5 text-center transition-colors"
                    >
                      삭제
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* ── 반복 설정 ── */}
      {tracks.length > 0 && (() => {
        const { finalCount, finalMinutes } = calcRepeat()
        const hours = Math.floor(finalMinutes / 60)
        const mins  = finalMinutes % 60
        const durationLabel = hours > 0 ? `${hours}시간 ${mins}분` : `${mins}분`

        return (
          <div className="mt-6 bg-gray-900 border border-gray-800 rounded-2xl p-5">
            <h3 className="text-sm font-semibold text-gray-200 mb-0.5">반복 설정</h3>
            <p className="text-xs text-gray-600 mb-4">
              트랙 전체를 몇 번 반복할지 설정합니다. 빌드 및 CapCut 프로젝트 파일에 반영됩니다.
            </p>

            {/* 모드 선택 */}
            <div className="flex gap-2 mb-4">
              {([
                { value: 'count',    label: '🔁 반복 횟수로 설정' },
                { value: 'duration', label: '⏱ 목표 시간으로 설정' },
              ] as const).map(opt => (
                <button
                  key={opt.value}
                  onClick={() => setRepeat(r => ({ ...r, mode: opt.value }))}
                  className={`px-4 py-2 rounded-xl text-sm font-medium border transition-colors ${
                    repeat.mode === opt.value
                      ? 'bg-purple-700 border-purple-500 text-white'
                      : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            {/* 입력 */}
            {repeat.mode === 'count' ? (
              <div className="flex items-center gap-3 mb-4">
                <label className="text-xs text-gray-500 w-20 shrink-0">반복 횟수</label>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setRepeat(r => ({ ...r, count: Math.max(1, r.count - 1) }))}
                    className="w-8 h-8 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-bold text-lg flex items-center justify-center"
                  >−</button>
                  <span className="w-10 text-center text-white font-mono font-bold text-lg">
                    {repeat.count}
                  </span>
                  <button
                    onClick={() => setRepeat(r => ({ ...r, count: r.count + 1 }))}
                    className="w-8 h-8 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-bold text-lg flex items-center justify-center"
                  >+</button>
                  <span className="text-xs text-gray-600 ml-1">회</span>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-3 mb-4">
                <label className="text-xs text-gray-500 w-20 shrink-0">목표 시간</label>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min={1}
                    value={repeat.target_minutes}
                    onChange={e => setRepeat(r => ({ ...r, target_minutes: Math.max(1, parseInt(e.target.value) || 1) }))}
                    className="w-20 bg-gray-800 text-white text-center rounded-lg px-2 py-1.5 text-sm border border-gray-700 focus:outline-none focus:border-purple-500 font-mono"
                  />
                  <span className="text-xs text-gray-600">분</span>
                </div>
              </div>
            )}

            {/* 결과 미리보기 */}
            <div className="bg-gray-800 rounded-xl px-4 py-3 mb-4 flex items-center gap-4 text-sm">
              <div className="flex items-center gap-2">
                <span className="text-gray-500 text-xs">반복</span>
                <span className="text-white font-bold">{finalCount}회</span>
              </div>
              <span className="text-gray-700">×</span>
              <div className="flex items-center gap-2">
                <span className="text-gray-500 text-xs">1회 재생</span>
                <span className="text-white font-mono">{fmtDuration(totalDuration)}</span>
              </div>
              <span className="text-gray-700">=</span>
              <div className="flex items-center gap-2">
                <span className="text-gray-500 text-xs">총 길이</span>
                <span className="text-purple-300 font-bold">{durationLabel}</span>
              </div>
            </div>

            <button
              onClick={handleSaveRepeat}
              disabled={savingRepeat}
              className="bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white px-5 py-2 rounded-xl text-sm font-semibold transition-colors"
            >
              {savingRepeat ? '저장 중...' : '💾 반복 설정 저장'}
            </button>
          </div>
        )
      })()}
    </div>
  )
}
