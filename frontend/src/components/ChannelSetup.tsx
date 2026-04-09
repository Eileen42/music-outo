'use client'
import { useState, useEffect, type FormEvent } from 'react'
import type { Project, Channel, UploadSettings } from '../types'
import { api } from '../api/client'

interface Props {
  projects: Project[]
  onSelect: (p: Project) => void
  onCreate: (name: string, playlistTitle: string, channelId: string) => void
  onDelete: (id: string) => void
}

// ── 헬퍼 ──────────────────────────────────────────────────────────────────────

const GENRE_ICON: Record<string, string> = {
  meditation: '🧘', sleep: '😴', ambient: '🌙',
  jazz: '🎷', lofi: '☕', cafe: '🏠',
  pop: '🎵', 'indie pop': '🎸', default: '🎼',
}
function genreIcon(genre: string[]): string {
  for (const g of genre) if (GENRE_ICON[g]) return GENRE_ICON[g]
  return GENRE_ICON.default
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('ko-KR', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

const STATUS_KO: Record<string, { label: string; color: string }> = {
  setup:      { label: '초기 설정', color: 'bg-gray-600 text-gray-200' },
  ready:      { label: '준비 완료', color: 'bg-green-700 text-green-100' },
  processing: { label: '처리 중',   color: 'bg-yellow-700 text-yellow-100' },
  uploading:  { label: '업로드 중', color: 'bg-blue-700 text-blue-100' },
  uploaded:   { label: '업로드 완료', color: 'bg-purple-700 text-purple-100' },
  error:      { label: '오류',      color: 'bg-red-700 text-red-100' },
}

const PRIVACY_LABEL: Record<string, string> = {
  private: '비공개', unlisted: '일부 공개', public: '공개',
}

// ── 채널 생성 폼 기본값 ─────────────────────────────────────────────────────

interface NewChannelForm {
  channel_id: string
  name: string
  genre: string
  has_lyrics: boolean
  subtitle_type: 'none' | 'affirmation' | 'lyrics'
  suno_base_prompt: string
  // 업로드 설정
  default_privacy: 'private' | 'unlisted' | 'public'
  default_tags: string        // 쉼표 구분
  default_description: string
}

const EMPTY_FORM: NewChannelForm = {
  channel_id: '', name: '', genre: '', has_lyrics: false,
  subtitle_type: 'none', suno_base_prompt: '',
  default_privacy: 'private', default_tags: '', default_description: '',
}

// ── 컴포넌트 ──────────────────────────────────────────────────────────────────

export default function ChannelSetup({ projects, onSelect, onCreate, onDelete }: Props) {
  const [channels, setChannels]             = useState<Channel[]>([])
  const [selectedChannel, setSelectedChannel] = useState<Channel | null>(null)
  const [projectName, setProjectName]       = useState('')
  const [playlistTitle, setPlaylistTitle]   = useState('')
  const [projLoading, setProjLoading]       = useState(false)
  const [chLoading, setChLoading]           = useState(true)

  // 채널 만들기 폼
  const [showChannelForm, setShowChannelForm] = useState(false)
  const [form, setForm]                       = useState<NewChannelForm>(EMPTY_FORM)
  const [formLoading, setFormLoading]         = useState(false)
  const [formError, setFormError]             = useState('')
  const [showUploadSection, setShowUploadSection] = useState(false)

  // 기존 프로젝트 채널 연결
  const [linkingProjectId, setLinkingProjectId] = useState<string | null>(null)
  const [linkChannelId, setLinkChannelId]        = useState('')
  const [linkLoading, setLinkLoading]            = useState(false)

  useEffect(() => { loadChannels() }, [])

  const loadChannels = async () => {
    setChLoading(true)
    try { setChannels(await api.channels.list()) }
    catch { setChannels([]) }
    finally { setChLoading(false) }
  }

  // 채널명 → ID 자동 슬러그
  const setName = (name: string) =>
    setForm(f => ({
      ...f,
      name,
      channel_id: f.channel_id || name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, ''),
    }))

  const handleCreateChannel = async (e: FormEvent) => {
    e.preventDefault()
    if (!form.name.trim() || !form.channel_id.trim()) return
    setFormLoading(true); setFormError('')
    try {
      await api.channels.create({
        channel_id:    form.channel_id.trim(),
        name:          form.name.trim(),
        genre:         form.genre.split(',').map(g => g.trim()).filter(Boolean),
        has_lyrics:    form.has_lyrics,
        subtitle_type: form.subtitle_type,
        mood_keywords: [],
        image_style:   [],
        suno_base_prompt: form.suno_base_prompt.trim(),
        upload_settings: {
          default_privacy:     form.default_privacy,
          default_tags:        form.default_tags.split(',').map(t => t.trim()).filter(Boolean),
          default_description: form.default_description.trim(),
          auto_add_playlist:   false,
        } as UploadSettings,
      })
      await loadChannels()
      setShowChannelForm(false)
      setForm(EMPTY_FORM)
      setShowUploadSection(false)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '채널 생성 실패'
      setFormError(String(msg))
    } finally {
      setFormLoading(false)
    }
  }

  const handleCreateProject = async (e: FormEvent) => {
    e.preventDefault()
    if (!projectName.trim() || !selectedChannel) return
    setProjLoading(true)
    try {
      await onCreate(projectName.trim(), playlistTitle.trim(), selectedChannel.channel_id)
      setProjectName(''); setPlaylistTitle('')
    } finally { setProjLoading(false) }
  }

  // 기존 프로젝트 → 채널 연결
  const handleLinkChannel = async (projectId: string) => {
    if (!linkChannelId) return
    setLinkLoading(true)
    try {
      await api.projects.update(projectId, { channel_id: linkChannelId })
      setLinkingProjectId(null)
      setLinkChannelId('')
      // 프로젝트 목록 리프레시 (간단히 페이지 새로고침 대신 부모 상태 업데이트)
      window.location.reload()
    } finally { setLinkLoading(false) }
  }

  const filteredProjects = selectedChannel
    ? projects.filter(p => p.channel_id === selectedChannel.channel_id)
    : projects
  const unlinkedProjects = projects.filter(p => !p.channel_id)

  return (
    <div className="max-w-3xl mx-auto p-6">
      {/* 타이틀 */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white mb-1">🎬 YouTube 플레이리스트 자동화</h1>
        <p className="text-sm text-gray-500">채널을 선택하고 프로젝트를 만들면 AI가 곡을 설계하고 영상을 제작합니다.</p>
      </div>

      {/* ── 채널 선택 섹션 ───────────────────────────────────────────── */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">채널 선택</h2>
          <button
            onClick={() => { setShowChannelForm(v => !v); setFormError('') }}
            className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors px-3 py-1 rounded-lg border border-indigo-800 hover:border-indigo-600"
          >
            {showChannelForm ? '✕ 취소' : '+ 채널 만들기'}
          </button>
        </div>

        {/* ── 채널 만들기 폼 ── */}
        {showChannelForm && (
          <div className="bg-gray-900 rounded-2xl p-5 mb-4 border border-indigo-800/60">
            <h3 className="text-sm font-semibold text-white mb-4">새 채널</h3>
            <form onSubmit={handleCreateChannel} className="space-y-4">

              {/* 기본 정보 */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">채널 이름 <span className="text-red-500">*</span></label>
                  <input
                    value={form.name}
                    onChange={e => setName(e.target.value)}
                    placeholder="예: Serenity M"
                    className="w-full bg-gray-800 text-white rounded-xl px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">채널 ID <span className="text-red-500">*</span></label>
                  <input
                    value={form.channel_id}
                    onChange={e => setForm(f => ({ ...f, channel_id: e.target.value.replace(/[^a-z0-9_]/g, '') }))}
                    placeholder="예: serenity_m"
                    className="w-full bg-gray-800 text-white rounded-xl px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600 font-mono"
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs text-gray-500 mb-1">장르 <span className="text-gray-600">(쉼표로 구분)</span></label>
                <input
                  value={form.genre}
                  onChange={e => setForm(f => ({ ...f, genre: e.target.value }))}
                  placeholder="예: meditation, sleep, ambient"
                  className="w-full bg-gray-800 text-white rounded-xl px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">자막 방식</label>
                  <select
                    value={form.subtitle_type}
                    onChange={e => setForm(f => ({ ...f, subtitle_type: e.target.value as NewChannelForm['subtitle_type'] }))}
                    className="w-full bg-gray-800 text-white rounded-xl px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="none">자막 없음</option>
                    <option value="affirmation">확언 자막</option>
                    <option value="lyrics">가사 자막</option>
                  </select>
                </div>
                <div className="flex items-center gap-3 pt-5">
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      checked={form.has_lyrics}
                      onChange={e => setForm(f => ({ ...f, has_lyrics: e.target.checked }))}
                      className="sr-only peer"
                    />
                    <div className="w-9 h-5 bg-gray-700 rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600" />
                    <span className="ml-2 text-xs text-gray-400">가사 포함</span>
                  </label>
                </div>
              </div>

              <div>
                <label className="block text-xs text-gray-500 mb-1">Suno 기본 프롬프트 <span className="text-gray-600">(선택)</span></label>
                <input
                  value={form.suno_base_prompt}
                  onChange={e => setForm(f => ({ ...f, suno_base_prompt: e.target.value }))}
                  placeholder="예: ambient meditation music, soft piano, no lyrics, peaceful"
                  className="w-full bg-gray-800 text-white rounded-xl px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
                />
              </div>

              {/* ── 업로드 설정 (접이식) ── */}
              <div className="border border-gray-800 rounded-xl overflow-hidden">
                <button
                  type="button"
                  onClick={() => setShowUploadSection(v => !v)}
                  className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-800/50 hover:bg-gray-800 transition-colors text-left"
                >
                  <span className="text-xs font-semibold text-gray-400">▶ 업로드 설정 <span className="text-gray-600 font-normal">(YouTube 기본값)</span></span>
                  <span className="text-gray-600 text-xs">{showUploadSection ? '▲' : '▼'}</span>
                </button>

                {showUploadSection && (
                  <div className="p-4 space-y-3 border-t border-gray-800">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs text-gray-500 mb-1">기본 공개 설정</label>
                        <select
                          value={form.default_privacy}
                          onChange={e => setForm(f => ({ ...f, default_privacy: e.target.value as NewChannelForm['default_privacy'] }))}
                          className="w-full bg-gray-800 text-white rounded-xl px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500"
                        >
                          <option value="private">비공개</option>
                          <option value="unlisted">일부 공개</option>
                          <option value="public">공개</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs text-gray-500 mb-1">기본 태그 <span className="text-gray-600">(쉼표 구분)</span></label>
                        <input
                          value={form.default_tags}
                          onChange={e => setForm(f => ({ ...f, default_tags: e.target.value }))}
                          placeholder="예: meditation, sleep music"
                          className="w-full bg-gray-800 text-white rounded-xl px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">기본 설명 템플릿</label>
                      <textarea
                        value={form.default_description}
                        onChange={e => setForm(f => ({ ...f, default_description: e.target.value }))}
                        placeholder="예: 🧘 편안한 명상 음악입니다. 수면, 집중, 휴식에 적합합니다.&#10;&#10;#meditation #sleepmusic"
                        rows={3}
                        className="w-full bg-gray-800 text-white rounded-xl px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600 resize-none"
                      />
                    </div>
                  </div>
                )}
              </div>

              {formError && <p className="text-red-400 text-xs">{formError}</p>}

              <button
                type="submit"
                disabled={formLoading || !form.name.trim() || !form.channel_id.trim()}
                className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white px-5 py-2 rounded-xl text-sm font-semibold transition-colors"
              >
                {formLoading ? '생성 중...' : '채널 만들기'}
              </button>
            </form>
          </div>
        )}

        {/* 채널 카드 목록 */}
        {chLoading ? (
          <div className="text-center py-8 text-gray-600 text-sm">채널 로딩 중...</div>
        ) : channels.length === 0 ? (
          <div className="text-center py-10 bg-gray-900 rounded-2xl border border-gray-800">
            <div className="text-3xl mb-2">📺</div>
            <p className="text-sm text-gray-500 mb-4">채널이 없습니다.</p>
            <button
              onClick={() => setShowChannelForm(true)}
              className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-xl text-sm font-semibold transition-colors"
            >
              + 채널 만들기
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-3">
            {channels.map(ch => {
              const active = selectedChannel?.channel_id === ch.channel_id
              const us = ch.upload_settings
              return (
                <button
                  key={ch.channel_id}
                  onClick={() => setSelectedChannel(active ? null : ch)}
                  className={`text-left p-4 rounded-2xl border transition-all ${
                    active
                      ? 'bg-indigo-900/60 border-indigo-500 ring-1 ring-indigo-500'
                      : 'bg-gray-900 border-gray-800 hover:border-gray-600'
                  }`}
                >
                  <div className="text-2xl mb-2">{genreIcon(ch.genre)}</div>
                  <div className="font-semibold text-white text-sm mb-1 truncate">{ch.name}</div>
                  <div className="text-[11px] text-gray-500 truncate mb-2">
                    {ch.genre.slice(0, 2).join(' · ')}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {ch.has_lyrics && (
                      <span className="text-[10px] bg-purple-900/50 text-purple-300 border border-purple-800 px-1.5 py-0.5 rounded-full">가사</span>
                    )}
                    {ch.subtitle_type !== 'none' && (
                      <span className="text-[10px] bg-blue-900/50 text-blue-300 border border-blue-800 px-1.5 py-0.5 rounded-full">
                        {ch.subtitle_type === 'affirmation' ? '확언' : '가사자막'}
                      </span>
                    )}
                    {us && (
                      <span className="text-[10px] bg-gray-800 text-gray-500 border border-gray-700 px-1.5 py-0.5 rounded-full">
                        {PRIVACY_LABEL[us.default_privacy] ?? us.default_privacy}
                      </span>
                    )}
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {/* ── 프로젝트 생성 (채널 선택 후) ─────────────────────────────── */}
      {selectedChannel && (
        <div className="bg-gray-900 rounded-2xl p-5 mb-8 border border-indigo-800/50">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-lg">{genreIcon(selectedChannel.genre)}</span>
            <div>
              <h2 className="text-sm font-semibold text-white">{selectedChannel.name} 프로젝트 만들기</h2>
              <p className="text-xs text-gray-500">{selectedChannel.genre.join(', ')}</p>
            </div>
          </div>
          <form onSubmit={handleCreateProject} className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">프로젝트 이름 <span className="text-red-500">*</span></label>
                <input
                  value={projectName}
                  onChange={e => setProjectName(e.target.value)}
                  placeholder="예: 명상 플레이리스트 vol.1"
                  className="w-full bg-gray-800 text-white rounded-xl px-3 py-2.5 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
                  required
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">YouTube 플레이리스트 제목</label>
                <input
                  value={playlistTitle}
                  onChange={e => setPlaylistTitle(e.target.value)}
                  placeholder="예: Healing Sleep Music 🌙"
                  className="w-full bg-gray-800 text-white rounded-xl px-3 py-2.5 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={projLoading || !projectName.trim()}
              className="w-fit bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white px-5 py-2.5 rounded-xl text-sm font-semibold transition-colors"
            >
              {projLoading ? '생성 중...' : '+ 프로젝트 생성'}
            </button>
          </form>
        </div>
      )}

      {/* ── 프로젝트 목록 ─────────────────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
            {selectedChannel ? `${selectedChannel.name} 프로젝트` : '전체 프로젝트'} ({filteredProjects.length})
          </h2>
          {selectedChannel && projects.length !== filteredProjects.length && (
            <button
              onClick={() => setSelectedChannel(null)}
              className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
            >
              전체 보기 ({projects.length})
            </button>
          )}
        </div>

        {filteredProjects.length === 0 ? (
          <div className="text-center py-12 text-gray-700">
            <div className="text-4xl mb-3">📂</div>
            <div className="text-sm">
              {selectedChannel ? `${selectedChannel.name} 채널 프로젝트가 없습니다.` : '아직 프로젝트가 없습니다.'}
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            {filteredProjects.map(p => {
              const si = STATUS_KO[p.status] || { label: p.status, color: 'bg-gray-700 text-gray-200' }
              const ch = channels.find(c => c.channel_id === p.channel_id)
              const isUnlinked = !p.channel_id
              const tracksDone = p.tracks.length > 0 || (p.designed_tracks?.length ?? 0) > 0
              const imageDone  = !!(p.images?.thumbnail || p.images?.background)
              const metaDone   = !!p.metadata?.title
              const buildDone  = p.build?.status === 'done'
              const ytDone     = !!p.youtube?.video_id
              const isLinking  = linkingProjectId === p.id

              return (
                <div key={p.id} className="bg-gray-900 border border-gray-800 rounded-2xl p-4 hover:border-gray-700 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="flex-1 min-w-0 cursor-pointer" onClick={() => onSelect(p)}>
                      <div className="flex items-center gap-2 mb-1">
                        {ch && <span className="text-sm">{genreIcon(ch.genre)}</span>}
                        <span className="font-semibold text-white truncate">{p.name}</span>
                        <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium shrink-0 ${si.color}`}>{si.label}</span>
                        {isUnlinked && (
                          <span className="text-[11px] px-2 py-0.5 rounded-full bg-yellow-900/50 text-yellow-400 border border-yellow-800 shrink-0">채널 미연결</span>
                        )}
                      </div>
                      {ch && <div className="text-[11px] text-indigo-400 mb-1">{ch.name}</div>}
                      {p.playlist_title && <div className="text-xs text-gray-500 truncate mb-2">{p.playlist_title}</div>}
                      <div className="flex gap-1.5 flex-wrap">
                        {[
                          { ok: tracksDone, label: tracksDone ? `트랙 ${p.tracks.length || p.designed_tracks?.length}개` : '트랙' },
                          { ok: imageDone,  label: '이미지' },
                          { ok: metaDone,   label: '메타데이터' },
                          { ok: buildDone,  label: '빌드' },
                          { ok: ytDone,     label: 'YouTube' },
                        ].map(item => (
                          <span key={item.label} className={`text-[11px] px-2 py-0.5 rounded-full ${
                            item.ok ? 'bg-green-900/50 text-green-400 border border-green-800' : 'bg-gray-800 text-gray-600 border border-gray-700'
                          }`}>
                            {item.ok ? '✓ ' : ''}{item.label}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="shrink-0 flex flex-col items-end gap-2">
                      <span className="text-xs text-gray-600">{formatDate(p.updated_at)}</span>
                      <div className="flex gap-1.5 flex-wrap justify-end">
                        {/* 채널 연결 버튼 (미연결 프로젝트만) */}
                        {isUnlinked && !isLinking && (
                          <button
                            onClick={e => { e.stopPropagation(); setLinkingProjectId(p.id); setLinkChannelId('') }}
                            className="text-xs text-yellow-500 hover:text-yellow-300 px-2 py-1.5 rounded-lg border border-yellow-800 hover:border-yellow-600 transition-colors"
                          >
                            📺 채널 연결
                          </button>
                        )}
                        <button
                          onClick={() => onSelect(p)}
                          className="text-xs bg-purple-700 hover:bg-purple-600 text-white px-3 py-1.5 rounded-lg transition-colors font-medium"
                        >
                          열기 →
                        </button>
                        <button
                          onClick={() => { if (confirm(`"${p.name}" 프로젝트를 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.`)) onDelete(p.id) }}
                          className="text-xs text-gray-600 hover:text-red-400 px-2 py-1.5 transition-colors"
                        >
                          삭제
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* 채널 연결 인라인 UI */}
                  {isLinking && (
                    <div className="mt-3 pt-3 border-t border-gray-800 flex items-center gap-2">
                      <select
                        value={linkChannelId}
                        onChange={e => setLinkChannelId(e.target.value)}
                        className="flex-1 bg-gray-800 text-white rounded-xl px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500"
                      >
                        <option value="">채널 선택...</option>
                        {channels.map(c => (
                          <option key={c.channel_id} value={c.channel_id}>{c.name} ({c.channel_id})</option>
                        ))}
                      </select>
                      <button
                        onClick={() => handleLinkChannel(p.id)}
                        disabled={!linkChannelId || linkLoading}
                        className="text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white px-4 py-2 rounded-xl font-semibold transition-colors whitespace-nowrap"
                      >
                        {linkLoading ? '연결 중...' : '연결'}
                      </button>
                      <button
                        onClick={() => setLinkingProjectId(null)}
                        className="text-xs text-gray-600 hover:text-gray-400 px-3 py-2 transition-colors"
                      >
                        취소
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {/* 미연결 프로젝트 요약 (전체 보기 시) */}
        {!selectedChannel && unlinkedProjects.length > 0 && (
          <p className="text-xs text-yellow-600 mt-3 text-center">
            ⚠ 채널 미연결 프로젝트 {unlinkedProjects.length}개 — "📺 채널 연결" 버튼으로 연결하세요.
          </p>
        )}
      </div>
    </div>
  )
}
