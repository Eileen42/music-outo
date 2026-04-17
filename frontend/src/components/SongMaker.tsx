'use client'
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import type { Project, DesignedTrack, Channel, ProjectConcept, SunoTrack } from '../types'
import { api } from '../api/client'
import TrackEditor from './TrackEditor'

interface Props {
  project: Project
  onRefresh: () => void
}

type Tab = 'auto' | 'upload'

const CATEGORY_ICON: Record<string, string> = {
  morning: '🌅', sleep: '😴', drive: '🚗', focus: '💡',
  relax: '☁️', meditation: '🧘', workout: '💪', cafe: '☕',
  night: '🌙', default: '🎵',
}

function categoryIcon(cat: string): string {
  return CATEGORY_ICON[cat] || CATEGORY_ICON.default
}

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
function resolveAudioUrl(url: string): string {
  if (!url) return ''
  if (url.startsWith('http')) return url
  return API_BASE + url
}

export default function SongMaker({ project, onRefresh }: Props) {
  const [tab, setTab] = useState<Tab>('auto')
  const [channel, setChannel] = useState<Channel | null>(null)
  const [tracks, setTracks] = useState<DesignedTrack[]>(project.designed_tracks ?? [])
  const [concept, setConcept] = useState<ProjectConcept | null>(null)
  const [benchmarkUrl, setBenchmarkUrl] = useState(project.benchmark_url || '')
  const [count, setCount] = useState(20)
  const [designing, setDesigning] = useState(false)
  const [designError, setDesignError] = useState('')
  const [editIdx, setEditIdx] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState<Partial<DesignedTrack>>({})
  const [regenIdx, setRegenIdx] = useState<number | null>(null)
  const [batchStatus, setBatchStatus] = useState<{
    status: string; phase?: string; round?: number;
    total_designed?: number; total_batches: number;
    completed_batches?: number; completed?: number;
    tracks_collected: number; current_song?: string;
    errors?: string[];
  } | null>(null)
  const [expandIdx, setExpandIdx] = useState<number | null>(null)
  const [dragTrackIdx, setDragTrackIdx] = useState<number | null>(null)
  const [dragOverTrackIdx, setDragOverTrackIdx] = useState<number | null>(null)
  const [showBenchmarks, setShowBenchmarks] = useState(false)
  const [editingBenchmarkIdx, setEditingBenchmarkIdx] = useState(-1)
  const [editingBenchmarkUrl, setEditingBenchmarkUrl] = useState('')
  const [qaStatus, setQaStatus] = useState<{ status: string; tracks: { index: number; title: string; v1_exists: boolean; v2_exists: boolean; status: string }[] } | null>(null)
  const [userKeywords, setUserKeywords] = useState('')
  const [userMood, setUserMood] = useState('')
  const [userLyricsHint, setUserLyricsHint] = useState('')
  const [userExtra, setUserExtra] = useState('')
  const [sunoTracks, setSunoTracks] = useState<SunoTrack[]>([])

  // 재생 상태
  const [playingKey, setPlayingKey] = useState<string | null>(null) // "index-slot"
  const [loadingKey, setLoadingKey] = useState<string | null>(null)
  const audioRefs = useRef<Map<string, HTMLAudioElement>>(new Map())
  const [retryingAll, setRetryingAll] = useState(false)
  const [activeSet, setActiveSet] = useState<string | null>(null)
  const [registeringSlot, setRegisteringSlot] = useState<number | null>(null)

  // suno 트랙을 designed_track index로 그룹핑
  const sunoByIndex = useMemo(() => {
    const map = new Map<number, SunoTrack[]>()
    for (const st of sunoTracks) {
      const arr = map.get(st.index) || []
      arr.push(st)
      arr.sort((a, b) => (a.slot || 0) - (b.slot || 0))
      map.set(st.index, arr)
    }
    return map
  }, [sunoTracks])

  const togglePlay = useCallback((key: string, url: string) => {
    const audio = audioRefs.current.get(key)
    if (!audio) return
    if (playingKey === key) {
      audio.pause()
      setPlayingKey(null)
    } else {
      if (playingKey) audioRefs.current.get(playingKey)?.pause()
      setLoadingKey(key)
      audio.src = resolveAudioUrl(url)
      audio.play()
        .then(() => { setPlayingKey(key); setLoadingKey(null) })
        .catch(() => setLoadingKey(null))
    }
  }, [playingKey])

  const [scanningStr, setScanningStr] = useState('')
  const handleRetryAll = async () => {
    setRetryingAll(true)
    try {
      const res = await api.trackDesign.retryDownload(project.id)
      setSunoTracks(res.tracks)
    } catch { /* ignore */ }
    finally { setRetryingAll(false) }
  }

  const handleScanSiblings = async () => {
    setScanningStr('스캔 중... Suno 브라우저가 열립니다')
    try {
      await api.trackDesign.scanSiblings(project.id)
      setScanningStr('스캔 진행 중... 완료되면 새로고침하세요')
      // 10초 후 트랙 갱신 시도
      setTimeout(async () => {
        try {
          const r = await api.trackDesign.sunoTracks(project.id)
          setSunoTracks(r.tracks)
          setScanningStr(`완료! ${r.tracks.length}곡`)
        } catch { /* ignore */ }
      }, 15000)
    } catch { setScanningStr('스캔 실패') }
  }

  const [registerMsg, setRegisterMsg] = useState('')
  const handleRegisterSet = async (slot: number) => {
    setRegisteringSlot(slot)
    setRegisterMsg('')
    try {
      const res = await api.trackDesign.registerSunoSet(project.id, slot)
      setActiveSet(res.set)
      if (res.skipped_duplicates > 0) {
        setRegisterMsg(`⚠ 중복 음원 ${res.skipped_duplicates}곡 제외됨 (동일 파일). 고유 ${res.tracks_count}곡만 등록했습니다. 새로 Suno 배치를 돌리면 해결됩니다.`)
      } else {
        setRegisterMsg(`✓ 세트 ${res.set} — ${res.tracks_count}곡 등록 완료`)
      }
      onRefresh()
    } catch { setRegisterMsg('등록 실패') }
    finally { setRegisteringSlot(null) }
  }

  // 세트별 통계
  const setStats = useMemo(() => {
    const s1 = sunoTracks.filter(t => (t.slot || 0) === 1 || (t.slot === 0 && sunoTracks.every(x => !x.slot || x.slot === 0)))
    const s2 = sunoTracks.filter(t => (t.slot || 0) === 2)
    return {
      a: { total: s1.length, completed: s1.filter(t => t.status === 'completed').length },
      b: { total: s2.length, completed: s2.filter(t => t.status === 'completed').length },
    }
  }, [sunoTracks])

  // Suno 세션 상태
  const [sunoSession, setSunoSession] = useState<{ session_exists: boolean; login_status: string } | null>(null)
  const [sunoLoginLoading, setSunoLoginLoading] = useState(false)
  const [sunoLoginMsg, setSunoLoginMsg] = useState('')

  // 레시피 녹화 상태
  const [recipe, setRecipe] = useState<{ exists: boolean; action_count?: number; recorded_at?: string } | null>(null)
  const [recipeRecording, setRecipeRecording] = useState(false)
  const [recipeActionCount, setRecipeActionCount] = useState(0)
  const [recipeMsg, setRecipeMsg] = useState('')

  // 초기 데이터 병렬 로드 (채널 + Suno 세션 + 레시피)
  useEffect(() => {
    const loads: Promise<void>[] = [
      api.suno.status().then(setSunoSession).catch(() => setSunoSession(null)),
      api.suno.getRecipe().then(setRecipe).catch(() => setRecipe(null)),
    ]
    if (project.channel_id) {
      loads.push(api.channels.get(project.channel_id).then(setChannel).catch(() => setChannel(null)))
    }
    Promise.all(loads)
  }, [project.channel_id])

  const handleSunoLogin = async () => {
    setSunoLoginLoading(true)
    setSunoLoginMsg('')
    try {
      const res = await api.suno.openLogin()
      setSunoLoginMsg(res.message)
      setSunoSession(prev => ({ ...prev!, login_status: 'waiting' }))
    } catch (e: unknown) {
      setSunoLoginMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '브라우저 열기 실패')
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
      setSunoLoginMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '세션 저장 실패')
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

  // 초기 suno 트랙 + 활성 세트 + QA 병렬 로드
  useEffect(() => {
    Promise.all([
      api.trackDesign.sunoTracks(project.id).then(r => setSunoTracks(r.tracks)).catch(() => {}),
      api.trackDesign.getActiveSet(project.id).then(r => setActiveSet(r.active_set)).catch(() => {}),
      api.qa.verify(project.id).then(setQaStatus).catch(() => {}),
    ])
  }, [project.id])

  // Suno 진행 폴링 — progress.json에서 직접 읽음
  useEffect(() => {
    if (batchStatus?.status !== 'running') return
    let tick = 0
    const timer = setInterval(async () => {
      tick++
      try {
        const s = await api.trackDesign.sunoStatus(project.id)
        setBatchStatus(s)

        // 매 폴링마다 sunoTracks 갱신 → 다운된 곡 바로 재생 가능
        api.trackDesign.sunoTracks(project.id).then(r => setSunoTracks(r.tracks)).catch(() => {})

        // 10초마다 QA도 갱신
        if (tick % 3 === 0) {
          api.qa.verify(project.id).then(setQaStatus).catch(() => {})
        }

        if (s.status !== 'running') {
          clearInterval(timer)
          api.qa.verify(project.id).then(setQaStatus).catch(() => {})
        }
      } catch { clearInterval(timer) }
    }, 3000)
    return () => clearInterval(timer)
  }, [batchStatus?.status, project.id])

  const handleDesign = async () => {
    if (!project.channel_id) return
    setDesigning(true)
    setDesignError('')
    try {
      const result = await api.trackDesign.design(
        project.channel_id,
        project.id,
        {
          benchmarkUrl: benchmarkUrl.trim() || undefined,
          count,
          keywords: userKeywords.trim(),
          mood: userMood.trim(),
          lyricsHint: userLyricsHint.trim(),
          extra: userExtra.trim(),
        },
      )
      setTracks(result.tracks)
      setConcept(result.concept ?? null)
      onRefresh()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '곡 설계 실패'
      setDesignError(msg)
    } finally {
      setDesigning(false)
    }
  }

  const handleDelete = async (idx: number) => {
    await api.trackDesign.delete(project.id, idx)
    const updated = tracks.filter((_, i) => i !== idx).map((t, i) => ({ ...t, index: i + 1 }))
    setTracks(updated)
  }

  const handleSaveEdit = async () => {
    if (editIdx === null) return
    const updated = await api.trackDesign.update(project.id, editIdx, editDraft)
    setTracks(prev => prev.map((t, i) => i === editIdx ? updated : t))
    setEditIdx(null)
    setEditDraft({})
  }

  const handleRegen = async (idx: number) => {
    if (!project.channel_id) return
    setRegenIdx(idx)
    try {
      const updated = await api.trackDesign.regenerate(project.id, idx, project.channel_id)
      setTracks(prev => prev.map((t, i) => i === idx ? updated : t))
    } finally {
      setRegenIdx(null)
    }
  }

  const handleRecordStart = async () => {
    setRecipeMsg('')
    try {
      await api.suno.record.start()
      setRecipeRecording(true)
      setRecipeActionCount(0)
      setRecipeMsg('브라우저가 열렸습니다. 가사→스타일→제목→Create 순서로 시연하세요.')
    } catch (e: unknown) {
      setRecipeMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '녹화 시작 실패')
    }
  }

  const handleRecordStop = async () => {
    try {
      const res = await api.suno.record.stop()
      setRecipeRecording(false)
      setRecipeMsg(`✅ 레시피 저장 완료 (${res.action_count}개 동작)`)
      const r = await api.suno.getRecipe()
      setRecipe(r)
    } catch (e: unknown) {
      setRecipeMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '녹화 완료 실패')
    }
  }

  const handleRecordCancel = async () => {
    await api.suno.record.cancel().catch(() => {})
    setRecipeRecording(false)
    setRecipeMsg('')
  }

  const handleDeleteRecipe = async () => {
    await api.suno.deleteRecipe()
    setRecipe({ exists: false })
    setRecipeMsg('')
  }

  // 녹화 중 폴링
  useEffect(() => {
    if (!recipeRecording) return
    const timer = setInterval(async () => {
      try {
        const s = await api.suno.record.status()
        setRecipeActionCount(s.action_count)
        if (s.auto_done) {
          clearInterval(timer)
          await handleRecordStop()
        }
      } catch { clearInterval(timer) }
    }, 2000)
    return () => clearInterval(timer)
  }, [recipeRecording])

  const handleBatchStop = async () => {
    try {
      await api.trackDesign.batchStop(project.id)
      setBatchStatus(null)
    } catch { /* ignore */ }
  }

  const handleBatchCreate = async () => {
    if (!project.channel_id) return
    try {
      await api.trackDesign.batchCreate(project.id, project.channel_id)
      const s = await api.trackDesign.sunoStatus(project.id)
      setBatchStatus(s)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Suno 시작 실패'
      setDesignError(msg)
    }
  }

  const hasDesigned = tracks.length > 0

  return (
    <div>
      {/* ── 탭 헤더 ── */}
      <div className="flex gap-1 mb-6 bg-gray-900 p-1 rounded-xl border border-gray-800 w-fit">
        <button
          onClick={() => setTab('auto')}
          className={`px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${
            tab === 'auto'
              ? 'bg-indigo-600 text-white'
              : 'text-gray-400 hover:text-white'
          }`}
        >
          ✨ 자동생성
        </button>
        <button
          onClick={() => setTab('upload')}
          className={`px-4 py-2 rounded-lg text-sm font-semibold transition-colors ${
            tab === 'upload'
              ? 'bg-purple-600 text-white'
              : 'text-gray-400 hover:text-white'
          }`}
        >
          📁 트랙 추가
        </button>
      </div>

      {/* ── 자동생성 탭 ── */}
      {tab === 'auto' && (
        <div>
          {/* 채널 없음 경고 */}
          {!project.channel_id && (
            <div className="bg-yellow-900/30 border border-yellow-700/50 rounded-xl p-4 mb-6 text-sm text-yellow-300">
              ⚠️ 채널이 연결되지 않았습니다. 홈으로 돌아가 채널을 선택하고 프로젝트를 만들어주세요.
            </div>
          )}

          {/* 채널 정보 */}
          {channel && (<>
            <div className="bg-gray-900 rounded-xl p-4 mb-3 border border-gray-800 flex items-center gap-3">
              <div className="text-2xl">
                {channel.genre[0] === 'meditation' ? '🧘' : channel.genre[0] === 'jazz' ? '🎷' : '🎵'}
              </div>
              <div>
                <div className="text-sm font-semibold text-white">{channel.name}</div>
                <div className="text-xs text-gray-500">
                  {channel.genre.join(' · ')} ·
                  {channel.has_lyrics ? ' 가사 있음' : ' Instrumental'} ·
                  {channel.subtitle_type === 'affirmation' ? ' 확언자막' : channel.subtitle_type === 'lyrics' ? ' 가사자막' : ' 자막없음'}
                </div>
              </div>
              {channel.benchmark_history.length > 0 && (
                <button
                  onClick={() => setShowBenchmarks(v => !v)}
                  className="ml-auto text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
                >
                  벤치마크 {channel.benchmark_history.length}개 {showBenchmarks ? '▲' : '▼'}
                </button>
              )}
            </div>

            {/* 벤치마크 목록 */}
            {showBenchmarks && channel.benchmark_history.length > 0 && (
              <div className="mb-6 space-y-2">
                {channel.benchmark_history.map((b: { url: string; video_id: string; title?: string }, idx: number) => (
                  <div key={idx} className="flex items-center gap-2 bg-gray-800/50 rounded-lg px-3 py-2">
                    <span className="text-xs text-gray-500 shrink-0">#{idx + 1}</span>
                    <a
                      href={b.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-blue-400 hover:text-blue-300 truncate flex-1"
                      title={b.url}
                    >
                      {b.title && b.title !== b.video_id ? b.title : b.url}
                    </a>
                    {editingBenchmarkIdx === idx ? (
                      <div className="flex items-center gap-1">
                        <input
                          value={editingBenchmarkUrl}
                          onChange={e => setEditingBenchmarkUrl(e.target.value)}
                          className="bg-gray-700 text-white text-xs rounded px-2 py-1 w-64 border border-gray-600 focus:outline-none focus:border-indigo-500"
                        />
                        <button
                          onClick={async () => {
                            const updated = [...channel.benchmark_history]
                            updated[idx] = { ...updated[idx], url: editingBenchmarkUrl }
                            await api.channels.update(channel.channel_id, { benchmark_history: updated } as Partial<Channel>)
                            setEditingBenchmarkIdx(-1)
                            onRefresh()
                          }}
                          className="text-xs text-green-400 hover:text-green-300 px-1"
                        >✓</button>
                        <button
                          onClick={() => setEditingBenchmarkIdx(-1)}
                          className="text-xs text-gray-500 hover:text-gray-300 px-1"
                        >✕</button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          onClick={() => { setEditingBenchmarkIdx(idx); setEditingBenchmarkUrl(b.url) }}
                          className="text-xs text-gray-500 hover:text-yellow-400 px-1"
                          title="수정"
                        >✏️</button>
                        <button
                          onClick={async () => {
                            if (!confirm('이 벤치마크를 삭제하시겠습니까?')) return
                            const updated = channel.benchmark_history.filter((_: unknown, i: number) => i !== idx)
                            await api.channels.update(channel.channel_id, { benchmark_history: updated } as Partial<Channel>)
                            onRefresh()
                          }}
                          className="text-xs text-gray-500 hover:text-red-400 px-1"
                          title="삭제"
                        >🗑️</button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>)}

          {/* 설계 폼 */}
          {!hasDesigned && project.channel_id && (
            <div className="bg-gray-900 rounded-2xl p-5 mb-6 border border-gray-800">
              <h3 className="text-sm font-semibold text-gray-300 mb-4">AI 곡 설계</h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    키워드 <span className="text-gray-600">(쉼표로 구분. 예: 봄, 산책, 카페)</span>
                  </label>
                  <input
                    value={userKeywords}
                    onChange={e => setUserKeywords(e.target.value)}
                    placeholder="봄, 산책, 따뜻한 오후, 카페..."
                    className="w-full bg-gray-800 text-white rounded-xl px-3 py-2.5 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    원하는 분위기
                  </label>
                  <input
                    value={userMood}
                    onChange={e => setUserMood(e.target.value)}
                    placeholder="밝고 경쾌한, 잔잔하고 포근한..."
                    className="w-full bg-gray-800 text-white rounded-xl px-3 py-2.5 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
                  />
                </div>
                {channel?.has_lyrics && (
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">
                      가사/주제 힌트 <span className="text-gray-600">(선택)</span>
                    </label>
                    <textarea
                      value={userLyricsHint}
                      onChange={e => setUserLyricsHint(e.target.value)}
                      placeholder="새로운 시작에 대한 설렘, 여행을 떠나는 기분..."
                      rows={2}
                      className="w-full bg-gray-800 text-white rounded-xl px-3 py-2.5 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600 resize-none"
                    />
                  </div>
                )}
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    추가 요청 <span className="text-gray-600">(선택. 예: 피아노 중심으로)</span>
                  </label>
                  <input
                    value={userExtra}
                    onChange={e => setUserExtra(e.target.value)}
                    placeholder="피아노 중심으로, BPM 느리게..."
                    className="w-full bg-gray-800 text-white rounded-xl px-3 py-2.5 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
                  />
                </div>
                <div className="flex items-center gap-4 pt-1">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">곡 수</label>
                    <select
                      value={count}
                      onChange={e => setCount(Number(e.target.value))}
                      className="bg-gray-800 text-white rounded-xl px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500"
                    >
                      {[10, 15, 20, 25, 30].map(n => (
                        <option key={n} value={n}>{n}곡</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex-1" />
                  <button
                    onClick={handleDesign}
                    disabled={designing}
                    className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white px-6 py-2.5 rounded-xl text-sm font-semibold transition-colors flex items-center gap-2"
                  >
                    {designing ? (
                      <>
                        <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        설계 중...
                      </>
                    ) : '✨ AI 곡 설계 시작'}
                  </button>
                </div>
              </div>
              {designError && (
                <p className="text-red-400 text-xs mt-3">{designError}</p>
              )}
            </div>
          )}

          {/* 설계된 곡 갤러리 */}
          {hasDesigned && (
            <div>
              {/* 프로젝트 컨셉 카드 */}
              {concept && (
                <div className="mb-5 bg-gray-900/80 border border-indigo-900/50 rounded-2xl p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <span className="text-indigo-400 text-xs font-semibold uppercase tracking-widest">프로젝트 컨셉</span>
                    <span className="text-gray-600 text-xs">— 모든 곡에 공통 적용</span>
                  </div>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
                    {[
                      { label: 'Genre',           value: concept.genre },
                      { label: 'Tempo',           value: `${concept.tempo} (${concept.bpm_range} BPM)` },
                      { label: 'Instrumentation', value: concept.instrumentation },
                      { label: 'Mood',            value: concept.core_mood },
                      { label: 'Atmosphere',      value: concept.atmosphere },
                    ].map(({ label, value }) => value ? (
                      <div key={label} className="flex gap-2">
                        <span className="text-gray-600 shrink-0 w-28">{label}</span>
                        <span className="text-gray-300">{value}</span>
                      </div>
                    ) : null)}
                  </div>
                  {concept.base_additional && (
                    <p className="mt-2 text-xs text-gray-500 italic border-t border-gray-800 pt-2">{concept.base_additional}</p>
                  )}
                </div>
              )}

              {/* 상단 액션 바 */}
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <span className="text-sm font-semibold text-white">{tracks.length}곡 설계 완료</span>
                  {sunoTracks.length > 0 && (
                    <span className="text-xs text-gray-400 bg-gray-800 px-2 py-0.5 rounded-full">
                      🎵 {sunoTracks.filter(t => t.status === 'completed').length}곡 고유 / {sunoTracks.filter(t => t.status === 'duplicate').length > 0 ? `${sunoTracks.filter(t => t.status === 'duplicate').length}곡 중복` : `${sunoTracks.length}곡`}
                    </span>
                  )}
                  {channel && (
                    <span className="text-xs text-gray-500">{channel.name}</span>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => { setTracks([]); setDesignError('') }}
                    className="text-xs text-gray-500 hover:text-gray-300 px-3 py-1.5 rounded-lg border border-gray-700 hover:border-gray-600 transition-colors"
                  >
                    다시 설계
                  </button>
                  {project.channel_id && (() => {
                    const hasAnySuno = sunoTracks.length > 0 || (qaStatus && qaStatus.tracks.some(t => t.status !== 'missing'))
                    const allComplete = qaStatus?.status === 'pass'
                    const completeCount = qaStatus?.tracks.filter(t => t.status === 'complete').length || 0
                    const missingCount = qaStatus?.tracks.filter(t => t.status !== 'complete').length || 0
                    const downloadFailedCount = sunoTracks.filter(t => t.status === 'download_failed').length
                    const isRunning = batchStatus?.status === 'running'

                    if (allComplete) return <span className="text-xs text-green-400 px-3 py-1.5">✅ 전곡 완료</span>

                    return (
                      <div className="flex gap-2">
                        {/* 생성된 곡 다운로드 (Suno에 있지만 로컬에 없는 곡) */}
                        {!allComplete && (
                          <button
                            onClick={async () => {
                              console.log('[다운로드] 1. 버튼 클릭')
                              setScanningStr('📡 Suno 피드 조회 중...')
                              try {
                                console.log('[다운로드] 2. API 호출')
                                const res = await api.trackDesign.scanSiblings(project.id)
                                console.log('[다운로드] 3. API 응답:', res)
                                setScanningStr(`📥 ${(res as { missing_count?: number }).missing_count || '?'}곡 다운로드 중...`)

                                // 5초마다 폴링 — 다운 완료될 때까지
                                let prevCount = sunoTracks.filter(t => t.status === 'completed').length
                                const poll = setInterval(async () => {
                                  try {
                                    const r = await api.trackDesign.sunoTracks(project.id)
                                    const nowCount = r.tracks.filter((t: { status: string }) => t.status === 'completed').length
                                    setSunoTracks(r.tracks)
                                    console.log(`[다운로드] 폴링: ${nowCount}곡 완료`)
                                    setScanningStr(`📥 다운로드 중... (${nowCount}곡 완료)`)

                                    if (nowCount > prevCount) prevCount = nowCount

                                    // QA도 갱신
                                    const qa = await api.qa.verify(project.id)
                                    setQaStatus(qa)
                                    const complete = qa.tracks?.filter((t: { status: string }) => t.status === 'complete').length || 0
                                    if (complete >= tracks.length) {
                                      clearInterval(poll)
                                      setScanningStr(`✅ ${complete}곡 다운로드 완료!`)
                                      setTimeout(() => setScanningStr(''), 3000)
                                    }
                                  } catch { /* ignore */ }
                                }, 5000)

                                // 최대 3분 후 자동 종료
                                setTimeout(() => {
                                  clearInterval(poll)
                                  if (scanningStr.includes('다운로드 중')) {
                                    setScanningStr('⏱ 시간 초과 — 새로고침 후 확인')
                                    setTimeout(() => setScanningStr(''), 5000)
                                  }
                                }, 180000)
                              } catch (err) {
                                console.error('[다운로드] 에러:', err)
                                setScanningStr('❌ 다운로드 실패')
                                setTimeout(() => setScanningStr(''), 3000)
                              }
                            }}
                            disabled={isRunning || !!scanningStr}
                            className="bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors"
                          >
                            {scanningStr || `📥 생성된 곡 다운로드`}
                          </button>
                        )}
                        {/* 미완료곡 생성 (아직 Suno에서 안 만든 곡) */}
                        <button
                          onClick={handleBatchCreate}
                          disabled={isRunning || !sunoSession?.session_exists}
                          title={!sunoSession?.session_exists ? 'Suno 로그인 필요' : ''}
                          className="bg-green-700 hover:bg-green-600 disabled:opacity-40 text-white px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors"
                        >
                          {hasAnySuno
                            ? `🎵 미완료 ${missingCount}곡 생성`
                            : `🎵 Suno 일괄 생성 (${tracks.length}곡)`}
                        </button>
                      </div>
                    )
                  })()}
                </div>
              </div>

              {/* Suno 진행 상태 */}
              {batchStatus && (
                <div className={`mb-4 p-3 rounded-xl border text-sm ${
                  batchStatus.status === 'running'
                    ? 'bg-green-900/20 border-green-700/50 text-green-300'
                    : batchStatus.status === 'completed'
                    ? 'bg-blue-900/20 border-blue-700/50 text-blue-300'
                    : 'bg-red-900/20 border-red-700/50 text-red-300'
                }`}>
                  {batchStatus.status === 'running' && (() => {
                    const done = batchStatus.completed_batches ?? batchStatus.completed ?? 0
                    const total = batchStatus.total_batches || 1
                    const pct = Math.round((done / total) * 100)
                    const phaseLabel = {
                      checking: '파일 확인 중',
                      collecting: 'Suno에서 다운로드 중',
                      creating: '곡 생성 중',
                      waiting: 'Suno 처리 대기 중',
                      verifying: '검수 중',
                    }[batchStatus.phase || ''] || '진행 중'

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
                            onClick={handleBatchStop}
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
              )}

              {/* QA 상태 요약 카드 */}
              {qaStatus && batchStatus?.status !== 'running' && (
                <div className={`mb-4 p-4 rounded-xl border text-sm ${
                  qaStatus.status === 'pass'
                    ? 'bg-green-900/20 border-green-700/50'
                    : 'bg-gray-900 border-gray-700'
                }`}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-semibold text-white">
                      {qaStatus.status === 'pass' ? '✅ 전곡 완료' : '📋 곡 생성 현황'}
                    </span>
                    <span className="text-xs text-gray-400">
                      {qaStatus.tracks.filter(t => t.status === 'complete').length}/{qaStatus.tracks.length}곡 완성
                    </span>
                  </div>
                  <div className="w-full bg-gray-800 rounded-full h-2 mb-3">
                    <div
                      className={`h-2 rounded-full transition-all ${qaStatus.status === 'pass' ? 'bg-green-500' : 'bg-indigo-500'}`}
                      style={{ width: `${(qaStatus.tracks.filter(t => t.status === 'complete').length / qaStatus.tracks.length) * 100}%` }}
                    />
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {qaStatus.tracks.map(t => (
                      <span
                        key={t.index}
                        className={`text-[10px] w-7 h-5 flex items-center justify-center rounded ${
                          t.status === 'complete'
                            ? 'bg-green-900/60 text-green-400'
                            : t.status === 'partial'
                            ? 'bg-yellow-900/60 text-yellow-400'
                            : 'bg-gray-800 text-gray-600'
                        }`}
                        title={`${t.index}. ${t.title} — ${t.status === 'complete' ? 'v1+v2 완료' : t.status === 'partial' ? (t.v1_exists ? 'v1만' : 'v2만') : '미생성'}`}
                      >
                        {t.index}
                      </span>
                    ))}
                  </div>
                  {qaStatus.status !== 'pass' && (
                    <div className="mt-3 flex items-center gap-2">
                      <button
                        onClick={handleBatchCreate}
                        disabled={batchStatus?.status === 'running' || !sunoSession?.session_exists}
                        className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white px-4 py-2 rounded-lg text-xs font-semibold transition-colors"
                      >
                        🔄 미완료 {qaStatus.tracks.filter(t => t.status !== 'complete').length}곡 재생성
                      </button>
                      <button
                        onClick={async () => {
                          await api.qa.fix(project.id)
                          const qa = await api.qa.verify(project.id)
                          setQaStatus(qa)
                          api.trackDesign.sunoTracks(project.id).then(r => setSunoTracks(r.tracks)).catch(() => {})
                        }}
                        className="text-xs text-gray-500 hover:text-gray-300 px-3 py-2 rounded-lg border border-gray-700 hover:border-gray-600 transition-colors"
                      >
                        🔗 연결 수정
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Suno 다운로드 실패 재시도 바 */}
              {sunoTracks.length > 0 && sunoTracks.some(t => t.status === 'download_failed' || t.status === 'duplicate') && (
                <div className="mb-4 space-y-2">
                  {sunoTracks.some(t => t.status === 'duplicate') && (
                    <div className="flex items-center justify-between bg-yellow-900/20 border border-yellow-800/50 rounded-xl px-4 py-2.5">
                      <span className="text-xs text-yellow-300">
                        ⚠ 중복 {sunoTracks.filter(t => t.status === 'duplicate').length}개 / 누락 곡이 Suno에 있을 수 있습니다
                      </span>
                      <button
                        onClick={handleScanSiblings}
                        disabled={!!scanningStr}
                        className="text-xs bg-yellow-800 hover:bg-yellow-700 disabled:opacity-40 text-white px-3 py-1.5 rounded-lg font-semibold transition-colors whitespace-nowrap"
                      >
                        {scanningStr || '🔍 Suno에서 누락 곡 찾기'}
                      </button>
                    </div>
                  )}
                  {sunoTracks.some(t => t.status === 'download_failed') && (
                <div className="flex items-center justify-between bg-red-900/20 border border-red-800/50 rounded-xl px-4 py-2.5">
                  <span className="text-xs text-red-300">
                    ⚠ 다운로드 실패 {sunoTracks.filter(t => t.status === 'download_failed').length}개
                    — CDN 지연으로 인한 실패일 수 있습니다
                  </span>
                  <button
                    onClick={handleRetryAll}
                    disabled={retryingAll}
                    className="text-xs bg-red-800 hover:bg-red-700 disabled:opacity-40 text-white px-3 py-1.5 rounded-lg font-semibold transition-colors whitespace-nowrap"
                  >
                    {retryingAll ? '재시도 중...' : '🔄 전체 재다운로드'}
                  </button>
                </div>
                  )}
                </div>
              )}

              {/* 곡 카드 목록 (드래그 순서 변경) */}
              <div className="space-y-2">
                {tracks.map((t, idx) => (
                  <div
                    key={idx}
                    draggable
                    onDragStart={() => setDragTrackIdx(idx)}
                    onDragOver={(e) => { e.preventDefault(); setDragOverTrackIdx(idx) }}
                    onDragEnd={async () => {
                      if (dragTrackIdx !== null && dragOverTrackIdx !== null && dragTrackIdx !== dragOverTrackIdx) {
                        const newTracks = [...tracks]
                        const [moved] = newTracks.splice(dragTrackIdx, 1)
                        newTracks.splice(dragOverTrackIdx, 0, moved)
                        // index 재할당
                        const reindexed = newTracks.map((tr, i) => ({ ...tr, index: i + 1 }))
                        setTracks(reindexed)
                        // 백엔드 저장
                        try {
                          await api.projects.update(project.id, { designed_tracks: reindexed } as Partial<Pick<Project, 'name' | 'playlist_title' | 'status' | 'channel_id'>>)
                        } catch { /* ignore */ }
                      }
                      setDragTrackIdx(null)
                      setDragOverTrackIdx(null)
                    }}
                    onDrop={() => {}}
                    className={`bg-gray-900 border rounded-xl overflow-hidden transition-all ${
                      dragOverTrackIdx === idx ? 'border-purple-500 ring-1 ring-purple-500' : 'border-gray-800'
                    }`}
                  >
                    {/* 카드 헤더 */}
                    <div
                      className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-800/50 transition-colors"
                      onClick={() => setExpandIdx(expandIdx === idx ? null : idx)}
                    >
                      <span className="text-gray-500 cursor-grab active:cursor-grabbing mr-1 select-none" title="드래그하여 순서 변경">⠿</span>
                      <span className="text-gray-600 text-xs w-5 text-center shrink-0">{t.index}</span>
                      {/* 생성 중 로딩 / QA 상태 표시 */}
                      {batchStatus?.status === 'running' && batchStatus?.current_song === t.title ? (
                        <span className="shrink-0 flex items-center gap-1.5">
                          <span className="w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
                          <span className="text-[10px] text-indigo-400 font-medium">
                            {batchStatus.phase === 'creating' ? '생성중' : batchStatus.phase === 'collecting' ? '다운로드중' : '처리중'}
                          </span>
                        </span>
                      ) : (() => {
                        const qa = qaStatus?.tracks.find(q => q.index === t.index)
                        if (!qa || qa.status === 'missing') return <span className="text-base shrink-0">{categoryIcon(t.category)}</span>
                        return (
                          <span className={`text-[10px] shrink-0 px-1.5 py-0.5 rounded-full font-medium ${
                            qa.status === 'complete'
                              ? 'bg-green-900/50 text-green-400'
                              : 'bg-yellow-900/50 text-yellow-400'
                          }`}>
                            {qa.status === 'complete' ? '✓' : qa.v1_exists ? 'v1' : 'v2'}
                          </span>
                        )
                      })()}

                      {/* 재생 버튼 1, 2 */}
                      {(() => {
                        const clips = sunoByIndex.get(t.index) || []
                        if (clips.length === 0) return null
                        return (
                          <div className="flex gap-1 shrink-0" onClick={e => e.stopPropagation()}>
                            {clips.map((st) => {
                              const key = `${st.index}-${st.slot || 0}`
                              const isPlaying = playingKey === key
                              const isLoading = loadingKey === key
                              const ok = st.status === 'completed' && st.audio_url
                              const isDup = st.status === 'duplicate'
                              return (
                                <span key={key}>
                                  {ok ? (
                                    <button
                                      onClick={() => togglePlay(key, st.audio_url)}
                                      className={`w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold transition-colors ${
                                        isPlaying ? 'bg-indigo-600 text-white' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
                                      }`}
                                      title={`버전 ${st.slot || '?'} 재생`}
                                    >
                                      {isLoading ? (
                                        <span className="w-2.5 h-2.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                      ) : isPlaying ? '⏸' : st.slot || '▶'}
                                    </button>
                                  ) : isDup ? (
                                    <span
                                      className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] bg-yellow-900/50 text-yellow-500 border border-yellow-800/50"
                                      title={`곡 ${st.duplicate_of}번과 동일한 음원 (중복)`}
                                    >
                                      =
                                    </span>
                                  ) : (
                                    <span
                                      className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] bg-gray-800 text-red-400 border border-red-900/50"
                                      title={st.status === 'download_failed' ? '다운로드 실패' : '생성 실패'}
                                    >
                                      {st.slot || '✗'}
                                    </span>
                                  )}
                                  <audio
                                    ref={el => {
                                      if (el) audioRefs.current.set(key, el)
                                      else audioRefs.current.delete(key)
                                    }}
                                    onEnded={() => { if (playingKey === key) setPlayingKey(null) }}
                                    preload="none"
                                  />
                                </span>
                              )
                            })}
                          </div>
                        )
                      })()}

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-white truncate">{t.title_ko || t.title}</span>
                          {t.title_ko && t.title && (
                            <span className="text-xs text-gray-600 truncate hidden sm:block">{t.title}</span>
                          )}
                        </div>
                        <div className="text-xs text-gray-500 truncate mt-0.5">{t.mood}</div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className="text-xs text-gray-600">{t.duration_hint}</span>
                        <span className="text-xs bg-gray-800 text-gray-500 px-2 py-0.5 rounded-full border border-gray-700">
                          {t.category}
                        </span>
                      </div>
                      <span className="text-gray-600 text-xs ml-1">{expandIdx === idx ? '▲' : '▼'}</span>
                    </div>

                    {/* 펼침: 상세 정보 + 편집 */}
                    {expandIdx === idx && (
                      <div className="px-4 pb-4 border-t border-gray-800 pt-3">
                        {editIdx === idx ? (
                          /* 편집 모드 */
                          <div className="space-y-3">
                            <div className="grid grid-cols-2 gap-3">
                              <div>
                                <label className="block text-xs text-gray-500 mb-1">제목 (한국어)</label>
                                <input
                                  value={editDraft.title_ko ?? t.title_ko}
                                  onChange={e => setEditDraft(d => ({ ...d, title_ko: e.target.value }))}
                                  className="w-full bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500"
                                />
                              </div>
                              <div>
                                <label className="block text-xs text-gray-500 mb-1">제목 (영어)</label>
                                <input
                                  value={editDraft.title ?? t.title}
                                  onChange={e => setEditDraft(d => ({ ...d, title: e.target.value }))}
                                  className="w-full bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500"
                                />
                              </div>
                            </div>
                            <div>
                              <label className="block text-xs text-gray-500 mb-1">Suno 프롬프트</label>
                              <textarea
                                value={editDraft.suno_prompt ?? t.suno_prompt}
                                onChange={e => setEditDraft(d => ({ ...d, suno_prompt: e.target.value }))}
                                rows={2}
                                className="w-full bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 resize-none"
                              />
                            </div>
                            {t.lyrics && (
                              <div>
                                <label className="block text-xs text-gray-500 mb-1">가사</label>
                                <textarea
                                  value={editDraft.lyrics ?? t.lyrics}
                                  onChange={e => setEditDraft(d => ({ ...d, lyrics: e.target.value }))}
                                  rows={4}
                                  className="w-full bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 resize-none font-mono text-xs"
                                />
                              </div>
                            )}
                            <div className="flex gap-2">
                              <button
                                onClick={handleSaveEdit}
                                className="text-xs bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded-lg transition-colors"
                              >
                                저장
                              </button>
                              <button
                                onClick={() => { setEditIdx(null); setEditDraft({}) }}
                                className="text-xs text-gray-500 hover:text-gray-300 px-3 py-1.5 rounded-lg border border-gray-700 transition-colors"
                              >
                                취소
                              </button>
                            </div>
                          </div>
                        ) : (
                          /* 보기 모드 */
                          <div className="space-y-2">
                            <div className="bg-gray-800/60 rounded-lg px-3 py-2">
                              <div className="text-xs text-gray-500 mb-1">Suno 프롬프트</div>
                              <div className="text-xs text-gray-300 font-mono leading-relaxed">{t.suno_prompt}</div>
                            </div>
                            {t.lyrics && (
                              <div className="bg-gray-800/60 rounded-lg px-3 py-2">
                                <div className="text-xs text-gray-500 mb-1">가사</div>
                                <pre className="text-xs text-gray-300 whitespace-pre-wrap font-mono leading-relaxed max-h-32 overflow-y-auto">{t.lyrics}</pre>
                              </div>
                            )}
                            <div className="flex gap-2 pt-1">
                              <button
                                onClick={() => { setEditIdx(idx); setEditDraft({}) }}
                                className="text-xs text-gray-400 hover:text-white px-3 py-1.5 rounded-lg border border-gray-700 hover:border-gray-600 transition-colors"
                              >
                                ✏️ 편집
                              </button>
                              <button
                                onClick={() => handleRegen(idx)}
                                disabled={regenIdx === idx}
                                className="text-xs text-indigo-400 hover:text-indigo-300 disabled:opacity-40 px-3 py-1.5 rounded-lg border border-indigo-800 hover:border-indigo-600 transition-colors"
                              >
                                {regenIdx === idx ? '재생성 중...' : '🔄 재생성'}
                              </button>
                              <button
                                onClick={() => {
                                  if (confirm(`"${t.title_ko}" 곡을 삭제하시겠습니까?`)) handleDelete(idx)
                                }}
                                className="text-xs text-gray-600 hover:text-red-400 px-3 py-1.5 transition-colors ml-auto"
                              >
                                삭제
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* ── 세트 A/B 등록 패널 ── */}
              {sunoTracks.length > 0 && (
                <div className="mt-6 pt-4 border-t border-gray-800">
                  <div className="flex items-center gap-2 mb-3">
                    <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">플레이리스트 세트</span>
                    {activeSet && (
                      <span className="text-xs bg-indigo-900/50 text-indigo-300 border border-indigo-700 px-2 py-0.5 rounded-full">
                        현재: 세트 {activeSet}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mb-3">
                    Suno가 곡당 2버전을 생성합니다. 세트 A(버전 1) 또는 세트 B(버전 2)를 트랙으로 등록하면 이후 단계(이미지·메타데이터·빌드·업로드)를 진행할 수 있습니다.
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    {/* 세트 A */}
                    <button
                      onClick={() => handleRegisterSet(1)}
                      disabled={registeringSlot !== null || setStats.a.completed === 0}
                      className={`p-4 rounded-xl border text-left transition-all ${
                        activeSet === 'A'
                          ? 'bg-indigo-900/40 border-indigo-500 ring-1 ring-indigo-500'
                          : 'bg-gray-900 border-gray-800 hover:border-gray-600'
                      } disabled:opacity-40 disabled:cursor-not-allowed`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-sm font-bold text-white">세트 A</span>
                        <span className="text-xs text-gray-500">버전 1</span>
                        {project.uploaded_set === 'A' && <span className="text-[9px] bg-green-800 text-green-300 px-1.5 py-0.5 rounded-full ml-auto">업로드 완료</span>}
                      </div>
                      <div className="text-xs text-gray-400">
                        {setStats.a.completed > 0
                          ? `${setStats.a.completed}곡 준비됨`
                          : '생성된 곡 없음'}
                      </div>
                      {registeringSlot === 1 && <span className="text-xs text-indigo-400 mt-1 block">등록 중...</span>}
                    </button>

                    {/* 세트 B */}
                    <button
                      onClick={() => handleRegisterSet(2)}
                      disabled={registeringSlot !== null || setStats.b.completed === 0}
                      className={`p-4 rounded-xl border text-left transition-all ${
                        activeSet === 'B'
                          ? 'bg-purple-900/40 border-purple-500 ring-1 ring-purple-500'
                          : 'bg-gray-900 border-gray-800 hover:border-gray-600'
                      } disabled:opacity-40 disabled:cursor-not-allowed`}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-sm font-bold text-white">세트 B</span>
                        <span className="text-xs text-gray-500">버전 2</span>
                        {project.uploaded_set === 'B' && <span className="text-[9px] bg-green-800 text-green-300 px-1.5 py-0.5 rounded-full ml-auto">업로드 완료</span>}
                      </div>
                      <div className="text-xs text-gray-400">
                        {setStats.b.completed > 0
                          ? `${setStats.b.completed}곡 준비됨`
                          : '생성된 곡 없음'}
                      </div>
                      {registeringSlot === 2 && <span className="text-xs text-purple-400 mt-1 block">등록 중...</span>}
                    </button>
                  </div>
                  {registerMsg && (
                    <p className={`mt-3 text-xs ${registerMsg.startsWith('⚠') ? 'text-yellow-400' : registerMsg.startsWith('✓') ? 'text-green-400' : 'text-red-400'}`}>
                      {registerMsg}
                    </p>
                  )}

                  {/* 반복 설정 */}
                  {activeSet && (() => {
                    const repeat = project.repeat || { mode: 'count' as const, count: 1, target_minutes: 60 }
                    const totalDur = project.tracks.reduce((s, t) => s + (t.duration || 0), 0)
                    const finalCount = repeat.mode === 'count' ? repeat.count : (totalDur > 0 ? Math.max(1, Math.ceil((repeat.target_minutes * 60) / totalDur)) : 1)
                    const finalMin = Math.round((totalDur * finalCount) / 60)
                    const hours = Math.floor(finalMin / 60)
                    const mins = finalMin % 60
                    const durLabel = hours > 0 ? `${hours}시간 ${mins}분` : `${mins}분`
                    const fmtDur = (s: number) => { const m = Math.floor(s/60); const ss = Math.floor(s%60); return `${m}:${String(ss).padStart(2,'0')}` }

                    return (
                      <div className="mt-4 pt-3 border-t border-gray-800">
                        <h4 className="text-xs font-semibold text-gray-400 mb-3">반복 설정</h4>
                        <div className="flex gap-2 mb-3">
                          {([
                            { value: 'count' as const, label: '🔁 반복 횟수' },
                            { value: 'duration' as const, label: '⏱ 목표 시간' },
                          ]).map(opt => (
                            <button key={opt.value}
                              onClick={() => api.projects.updateRepeat(project.id, { ...repeat, mode: opt.value }).then(onRefresh)}
                              className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                                repeat.mode === opt.value ? 'bg-purple-700 border-purple-500 text-white' : 'bg-gray-800 border-gray-700 text-gray-400'
                              }`}>{opt.label}</button>
                          ))}
                        </div>

                        {repeat.mode === 'count' ? (
                          <div className="flex items-center gap-2 mb-3">
                            <span className="text-xs text-gray-500 w-16">반복 횟수</span>
                            <button onClick={() => api.projects.updateRepeat(project.id, { ...repeat, count: Math.max(1, repeat.count - 1) }).then(onRefresh)}
                              className="w-7 h-7 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-bold flex items-center justify-center">−</button>
                            <span className="w-8 text-center text-white font-mono font-bold">{repeat.count}</span>
                            <button onClick={() => api.projects.updateRepeat(project.id, { ...repeat, count: repeat.count + 1 }).then(onRefresh)}
                              className="w-7 h-7 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-bold flex items-center justify-center">+</button>
                            <span className="text-xs text-gray-600">회</span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 mb-3">
                            <span className="text-xs text-gray-500 w-16">목표 시간</span>
                            <input type="number" min={1} value={repeat.target_minutes}
                              onChange={e => api.projects.updateRepeat(project.id, { ...repeat, target_minutes: Math.max(1, parseInt(e.target.value) || 1) }).then(onRefresh)}
                              className="w-16 bg-gray-800 text-white text-center rounded-lg px-2 py-1 text-sm border border-gray-700 font-mono" />
                            <span className="text-xs text-gray-600">분</span>
                          </div>
                        )}

                        <div className="bg-gray-800 rounded-xl px-3 py-2 flex items-center gap-3 text-xs">
                          <div><span className="text-gray-500">반복</span> <span className="text-white font-bold">{finalCount}회</span></div>
                          <span className="text-gray-700">×</span>
                          <div><span className="text-gray-500">1회</span> <span className="text-white font-mono">{fmtDur(totalDur)}</span></div>
                          <span className="text-gray-700">=</span>
                          <div><span className="text-gray-500">총</span> <span className="text-purple-300 font-bold">{durLabel}</span></div>
                        </div>
                      </div>
                    )
                  })()}
                </div>
              )}

              {/* Suno 로그인 패널 */}
              <div className="mt-6 pt-4 border-t border-gray-800">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">Suno 세션</span>
                  {sunoSession?.session_exists ? (
                    <div className="flex items-center gap-2">
                      <span className="flex items-center gap-1 text-xs text-green-400">
                        <span className="w-1.5 h-1.5 bg-green-400 rounded-full inline-block" />
                        로그인됨
                      </span>
                      <button
                        onClick={handleSunoLogout}
                        className="text-xs text-gray-600 hover:text-red-400 transition-colors"
                      >
                        세션 삭제
                      </button>
                    </div>
                  ) : (
                    <span className="flex items-center gap-1 text-xs text-yellow-500">
                      <span className="w-1.5 h-1.5 bg-yellow-500 rounded-full inline-block" />
                      미로그인
                    </span>
                  )}
                </div>

                {!sunoSession?.session_exists && (
                  <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
                    {sunoSession?.login_status === 'waiting' ? (
                      /* 로그인 창 열려있는 상태 */
                      <div className="space-y-3">
                        <div className="space-y-1">
                          <p className="text-xs text-yellow-300">🌐 Edge가 열렸습니다. Suno에 로그인해주세요.</p>
                          <p className="text-xs text-gray-400">Google 로그인 또는 이메일 모두 가능합니다.</p>
                        </div>
                        <div className="flex gap-2">
                          <button
                            onClick={handleSunoConfirm}
                            disabled={sunoLoginLoading}
                            className="bg-green-700 hover:bg-green-600 disabled:opacity-40 text-white px-4 py-2 rounded-xl text-xs font-semibold transition-colors"
                          >
                            {sunoLoginLoading ? '저장 중...' : '✓ 로그인 완료 — 세션 저장'}
                          </button>
                          <button
                            onClick={handleSunoLogout}
                            className="text-xs text-gray-500 hover:text-gray-300 px-3 py-2 rounded-xl border border-gray-700 transition-colors"
                          >
                            취소
                          </button>
                        </div>
                      </div>
                    ) : (
                      /* 로그인 전 */
                      <div className="flex items-center gap-3">
                        <p className="text-xs text-gray-500 flex-1">Suno 일괄 생성을 사용하려면 먼저 로그인하세요.</p>
                        <button
                          onClick={handleSunoLogin}
                          disabled={sunoLoginLoading}
                          className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white px-4 py-2 rounded-xl text-xs font-semibold transition-colors whitespace-nowrap"
                        >
                          {sunoLoginLoading ? '브라우저 여는 중...' : '🌐 Suno 로그인'}
                        </button>
                      </div>
                    )}
                    {sunoLoginMsg && (
                      <p className="mt-2 text-xs text-gray-400">{sunoLoginMsg}</p>
                    )}
                  </div>
                )}
              </div>

              {/* 레시피 녹화 패널 */}
              {sunoSession?.session_exists && (
                <div className="mt-4 pt-4 border-t border-gray-800">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-gray-500 uppercase tracking-widest">자동화 레시피</span>
                    {recipe?.exists ? (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-emerald-400">✅ 레시피 있음 ({recipe.action_count}개)</span>
                        <button onClick={handleDeleteRecipe} className="text-xs text-gray-600 hover:text-red-400 transition-colors">삭제</button>
                      </div>
                    ) : (
                      <span className="text-xs text-yellow-600">레시피 없음 — 불안정할 수 있음</span>
                    )}
                  </div>

                  {recipeRecording ? (
                    /* 녹화 중 */
                    <div className="bg-red-950/30 border border-red-800/50 rounded-xl p-4 space-y-3">
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse inline-block" />
                        <span className="text-xs text-red-300 font-semibold">녹화 중 — {recipeActionCount}개 동작 기록됨</span>
                      </div>
                      <p className="text-xs text-gray-400">브라우저에서 가사 → 스타일 → 제목 → Create 순서로 진행 후<br/>오버레이의 ✅ 버튼 또는 아래 완료 버튼을 누르세요.</p>
                      <div className="flex gap-2">
                        <button
                          onClick={handleRecordStop}
                          className="bg-emerald-700 hover:bg-emerald-600 text-white px-4 py-2 rounded-xl text-xs font-semibold transition-colors"
                        >
                          ✅ 녹화 완료
                        </button>
                        <button
                          onClick={handleRecordCancel}
                          className="text-xs text-gray-500 hover:text-gray-300 px-3 py-2 rounded-xl border border-gray-700 transition-colors"
                        >
                          취소
                        </button>
                      </div>
                    </div>
                  ) : (
                    /* 녹화 시작 */
                    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
                      <p className="text-xs text-gray-500 mb-3">
                        {recipe?.exists
                          ? 'Suno UI가 바뀌면 재녹화하세요. 한 번만 시연하면 이후 일괄 생성에 자동 적용됩니다.'
                          : 'Suno 브라우저를 열어 한 번만 직접 시연하면, 그 동작을 기억해 일괄 생성에 자동 재생합니다.'}
                      </p>
                      <button
                        onClick={handleRecordStart}
                        className="bg-rose-800 hover:bg-rose-700 text-white px-4 py-2 rounded-xl text-xs font-semibold transition-colors"
                      >
                        🔴 {recipe?.exists ? '재녹화' : '레시피 녹화 시작'}
                      </button>
                    </div>
                  )}

                  {recipeMsg && (
                    <p className={`mt-2 text-xs ${recipeMsg.startsWith('✅') ? 'text-emerald-400' : 'text-gray-400'}`}>
                      {recipeMsg}
                    </p>
                  )}
                </div>
              )}

              {/* 재설계 폼 (하단) */}
              <div className="mt-4 pt-4 border-t border-gray-800 space-y-2">
                <div className="flex items-center gap-3">
                  <input
                    value={userKeywords}
                    onChange={e => setUserKeywords(e.target.value)}
                    placeholder="키워드 (쉼표 구분)"
                    className="flex-1 bg-gray-800 text-white rounded-xl px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
                  />
                  <input
                    value={userMood}
                    onChange={e => setUserMood(e.target.value)}
                    placeholder="분위기"
                    className="flex-1 bg-gray-800 text-white rounded-xl px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
                  />
                  <button
                    onClick={handleDesign}
                    disabled={designing || !project.channel_id}
                    className="bg-indigo-700 hover:bg-indigo-600 disabled:opacity-40 text-white px-4 py-2 rounded-xl text-sm font-semibold transition-colors whitespace-nowrap"
                  >
                    {designing ? '설계 중...' : '✨ 전체 재설계'}
                  </button>
                </div>
                {designError && <p className="text-red-400 text-xs mt-2">{designError}</p>}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── 트랙 추가 탭 ── */}
      {tab === 'upload' && (
        <TrackEditor project={project} onRefresh={onRefresh} />
      )}
    </div>
  )
}
