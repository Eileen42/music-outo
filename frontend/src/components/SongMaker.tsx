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
  const [benchmarkUrl, setBenchmarkUrl] = useState('')
  const [count, setCount] = useState(20)
  const [designing, setDesigning] = useState(false)
  const [designError, setDesignError] = useState('')
  const [editIdx, setEditIdx] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState<Partial<DesignedTrack>>({})
  const [regenIdx, setRegenIdx] = useState<number | null>(null)
  const [batchStatus, setBatchStatus] = useState<{ status: string; completed: number; total_batches: number; tracks_collected: number } | null>(null)
  const [expandIdx, setExpandIdx] = useState<number | null>(null)
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

  // 채널 로드
  useEffect(() => {
    if (project.channel_id) {
      api.channels.get(project.channel_id).then(setChannel).catch(() => setChannel(null))
    }
  }, [project.channel_id])

  // Suno 세션 + 레시피 상태 로드
  useEffect(() => {
    api.suno.status().then(setSunoSession).catch(() => setSunoSession(null))
    api.suno.getRecipe().then(setRecipe).catch(() => setRecipe(null))
  }, [])

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

  // 초기 suno 트랙 + 활성 세트 로드
  useEffect(() => {
    api.trackDesign.sunoTracks(project.id)
      .then(r => setSunoTracks(r.tracks))
      .catch(() => {})
    api.trackDesign.getActiveSet(project.id)
      .then(r => setActiveSet(r.active_set))
      .catch(() => {})
  }, [project.id])

  // Suno 진행 폴링
  useEffect(() => {
    if (batchStatus?.status !== 'running') return
    const timer = setInterval(async () => {
      try {
        const s = await api.trackDesign.sunoStatus(project.id)
        setBatchStatus(s)
        if (s.status !== 'running') {
          clearInterval(timer)
          // 완료 시 트랙 목록 갱신
          api.trackDesign.sunoTracks(project.id)
            .then(r => setSunoTracks(r.tracks))
            .catch(() => {})
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
        benchmarkUrl.trim() || undefined,
        count,
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
          {channel && (
            <div className="bg-gray-900 rounded-xl p-4 mb-6 border border-gray-800 flex items-center gap-3">
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
                <div className="ml-auto text-xs text-indigo-400">
                  벤치마크 {channel.benchmark_history.length}개 저장됨
                </div>
              )}
            </div>
          )}

          {/* 설계 폼 */}
          {!hasDesigned && project.channel_id && (
            <div className="bg-gray-900 rounded-2xl p-5 mb-6 border border-gray-800">
              <h3 className="text-sm font-semibold text-gray-300 mb-4">AI 곡 설계</h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    벤치마크 YouTube URL <span className="text-gray-600">(선택 — 없으면 채널 히스토리 사용)</span>
                  </label>
                  <input
                    value={benchmarkUrl}
                    onChange={e => setBenchmarkUrl(e.target.value)}
                    placeholder="https://www.youtube.com/watch?v=..."
                    className="w-full bg-gray-800 text-white rounded-xl px-3 py-2.5 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
                  />
                </div>
                <div className="flex items-center gap-4">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">설계할 곡 수</label>
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
                  {project.channel_id && (
                    <button
                      onClick={handleBatchCreate}
                      disabled={batchStatus?.status === 'running' || !sunoSession?.session_exists}
                      title={!sunoSession?.session_exists ? 'Suno 로그인 필요' : ''}
                      className="bg-green-700 hover:bg-green-600 disabled:opacity-40 text-white px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors"
                    >
                      🎵 Suno 일괄 생성
                    </button>
                  )}
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
                  {batchStatus.status === 'running' && (
                    <div className="flex items-center gap-3">
                      <span className="inline-block w-3 h-3 border-2 border-green-400/30 border-t-green-400 rounded-full animate-spin shrink-0" />
                      <div className="flex-1">
                        <div className="font-semibold mb-1">
                          Suno 생성 중... {batchStatus.completed}/{batchStatus.total_batches} 배치
                        </div>
                        <div className="w-full bg-green-900/50 rounded-full h-1.5">
                          <div
                            className="bg-green-500 h-1.5 rounded-full transition-all"
                            style={{ width: `${(batchStatus.completed / batchStatus.total_batches) * 100}%` }}
                          />
                        </div>
                      </div>
                      <span className="text-xs text-green-400 shrink-0">
                        {batchStatus.tracks_collected}곡 수집됨
                      </span>
                      <button
                        onClick={handleBatchStop}
                        className="text-xs bg-red-800 hover:bg-red-700 text-white px-3 py-1.5 rounded-lg font-semibold transition-colors shrink-0"
                      >
                        ⏹ 중지
                      </button>
                    </div>
                  )}
                  {batchStatus.status === 'completed' && (
                    `✓ Suno 생성 완료 — ${batchStatus.tracks_collected}곡 수집됨`
                  )}
                  {batchStatus.status === 'failed' && '✗ Suno 생성 실패'}
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

              {/* 곡 카드 목록 */}
              <div className="space-y-2">
                {tracks.map((t, idx) => (
                  <div
                    key={idx}
                    className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden"
                  >
                    {/* 카드 헤더 */}
                    <div
                      className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-800/50 transition-colors"
                      onClick={() => setExpandIdx(expandIdx === idx ? null : idx)}
                    >
                      <span className="text-gray-600 text-xs w-5 text-center shrink-0">{t.index}</span>
                      <span className="text-base shrink-0">{categoryIcon(t.category)}</span>

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
              <div className="mt-4 pt-4 border-t border-gray-800">
                <div className="flex items-center gap-3">
                  <input
                    value={benchmarkUrl}
                    onChange={e => setBenchmarkUrl(e.target.value)}
                    placeholder="벤치마크 URL 변경 (선택)"
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
