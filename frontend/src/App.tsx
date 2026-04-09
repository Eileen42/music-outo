import { useState, useEffect, useCallback } from 'react'
import { api } from './api/client'
import type { Project, StepId } from './types'
import ChannelSetup from './components/ChannelSetup'
import SongMaker from './components/SongMaker'
import ImageSelector from './components/ImageSelector'
import MetadataPreview from './components/MetadataPreview'
import LayerPreview from './components/LayerPreview'
import BuildDownload from './components/BuildDownload'
import YouTubeUpload from './components/YouTubeUpload'

interface Step {
  id: StepId
  num: number
  icon: string
  label: string
  desc: string
  isDone: (p: Project) => boolean
}

const STEPS: Step[] = [
  {
    id: 'setup',
    num: 1,
    icon: '📺',
    label: '채널 설정',
    desc: '채널 선택 및 프로젝트 생성',
    isDone: () => true,
  },
  {
    id: 'tracks',
    num: 2,
    icon: '🎵',
    label: '노래 만들기',
    desc: 'AI 자동생성 또는 파일 업로드',
    isDone: (p) => p.tracks.length > 0 || (p.designed_tracks?.length ?? 0) > 0,
  },
  {
    id: 'images',
    num: 3,
    icon: '🖼️',
    label: '이미지 설정',
    desc: '썸네일·배경 이미지 업로드',
    isDone: (p) => !!(p.images?.thumbnail || p.images?.background),
  },
  {
    id: 'metadata',
    num: 4,
    icon: '✍️',
    label: '메타데이터',
    desc: 'AI로 제목·설명·태그 자동 생성',
    isDone: (p) => !!p.metadata?.title,
  },
  {
    id: 'layers',
    num: 5,
    icon: '🎬',
    label: '레이어 설정',
    desc: '파형·텍스트 오버레이 설정 (선택)',
    isDone: (p) => !!p.layers?.waveform_layer,
  },
  {
    id: 'build',
    num: 6,
    icon: '⚙️',
    label: '빌드 & 다운로드',
    desc: '영상 합성 후 MP4 다운로드',
    isDone: (p) => p.build?.status === 'done',
  },
  {
    id: 'youtube',
    num: 7,
    icon: '▶️',
    label: 'YouTube 업로드',
    desc: 'Google 계정 연결 후 업로드',
    isDone: (p) => !!p.youtube?.video_id,
  },
]

function getCompletedCount(p: Project) {
  return STEPS.filter(s => s.isDone(p)).length
}

export default function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [activeProject, setActiveProject] = useState<Project | null>(null)
  const [step, setStep] = useState<StepId>(() => (sessionStorage.getItem('step') as StepId) || 'setup')
  const [showProjectList, setShowProjectList] = useState(() => !sessionStorage.getItem('projectId'))

  const loadProjects = useCallback(async () => {
    const list = await api.projects.list()
    setProjects(list)
    // 새로고침 시 이전 프로젝트 복원
    const savedId = sessionStorage.getItem('projectId')
    if (savedId && !activeProject) {
      const saved = list.find(p => p.id === savedId)
      if (saved) {
        setActiveProject(saved)
        setShowProjectList(false)
      }
    }
  }, [])

  const refreshProject = useCallback(async (id: string) => {
    const updated = await api.projects.get(id)
    setActiveProject(updated)
    setProjects(prev => prev.map(p => p.id === id ? updated : p))
  }, [])

  // 상태 변경 시 sessionStorage에 저장
  useEffect(() => {
    if (activeProject) sessionStorage.setItem('projectId', activeProject.id)
    else sessionStorage.removeItem('projectId')
  }, [activeProject])

  useEffect(() => { sessionStorage.setItem('step', step) }, [step])

  useEffect(() => { loadProjects() }, [loadProjects])

  const handleSelectProject = (p: Project) => {
    setActiveProject(p)
    setShowProjectList(false)
    setStep('tracks')
  }

  const handleCreateProject = async (name: string, playlistTitle: string, channelId: string) => {
    // 프로젝트 생성 후 channel_id 연결
    const p = await api.projects.create(name, playlistTitle)
    if (channelId) {
      const updated = await api.projects.update(p.id, { channel_id: channelId })
      setProjects(prev => [updated, ...prev])
      setActiveProject(updated)
    } else {
      setProjects(prev => [p, ...prev])
      setActiveProject(p)
    }
    setShowProjectList(false)
    setStep('tracks')
  }

  const handleDeleteProject = async (id: string) => {
    await api.projects.delete(id)
    await loadProjects()
    if (activeProject?.id === id) {
      setActiveProject(null)
      setShowProjectList(true)
    }
  }

  const stepProps = { project: activeProject!, onRefresh: () => refreshProject(activeProject!.id) }
  const currentStep = STEPS.find(s => s.id === step)
  const completedCount = activeProject ? getCompletedCount(activeProject) : 0

  return (
    <div className="min-h-screen flex flex-col bg-gray-950">
      {/* ── 헤더 ── */}
      <header className="bg-gray-900 border-b border-gray-800 px-5 py-3 flex items-center gap-4 shrink-0">
        <button
          onClick={() => { setShowProjectList(true); setActiveProject(null) }}
          className="flex items-center gap-2 text-purple-400 hover:text-purple-300 transition-colors font-bold text-sm"
        >
          🎬 <span className="hidden sm:inline">YouTube 플레이리스트 자동화</span>
          <span className="sm:hidden">YPA</span>
        </button>

        {activeProject && !showProjectList && (
          <>
            <span className="text-gray-700">/</span>
            <span className="text-gray-300 text-sm font-medium truncate max-w-[180px]">
              {activeProject.name}
            </span>
            {/* 진행률 */}
            <div className="ml-auto flex items-center gap-3">
              <span className="text-xs text-gray-500 hidden sm:block">
                {completedCount}/{STEPS.length} 완료
              </span>
              <div className="w-24 h-1.5 bg-gray-800 rounded-full hidden sm:block">
                <div
                  className="h-1.5 bg-purple-500 rounded-full transition-all duration-500"
                  style={{ width: `${(completedCount / STEPS.length) * 100}%` }}
                />
              </div>
            </div>
          </>
        )}
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* ── 사이드바 ── */}
        {activeProject && !showProjectList && (
          <aside className="w-56 bg-gray-900 border-r border-gray-800 flex flex-col shrink-0 overflow-y-auto">
            <div className="px-3 pt-4 pb-2">
              <p className="text-xs text-gray-600 uppercase tracking-widest font-semibold px-1">작업 단계</p>
            </div>

            <nav className="flex-1 px-2 space-y-0.5">
              {STEPS.map((s) => {
                const done = activeProject ? s.isDone(activeProject) : false
                const active = step === s.id
                return (
                  <button
                    key={s.id}
                    onClick={() => setStep(s.id)}
                    className={`w-full flex items-start gap-3 px-3 py-2.5 rounded-lg text-left transition-colors group ${
                      active
                        ? 'bg-purple-700/80 text-white'
                        : 'text-gray-400 hover:bg-gray-800 hover:text-white'
                    }`}
                  >
                    <span className={`shrink-0 mt-0.5 w-5 h-5 flex items-center justify-center rounded-full text-[10px] font-bold border ${
                      done
                        ? 'bg-green-600 border-green-500 text-white'
                        : active
                        ? 'bg-purple-500 border-purple-400 text-white'
                        : 'border-gray-700 text-gray-600'
                    }`}>
                      {done ? '✓' : s.num}
                    </span>
                    <div className="min-w-0">
                      <div className={`text-sm font-medium leading-tight ${active ? 'text-white' : ''}`}>
                        {s.icon} {s.label}
                      </div>
                      <div className={`text-[11px] leading-tight mt-0.5 truncate ${
                        active ? 'text-purple-200' : 'text-gray-600 group-hover:text-gray-500'
                      }`}>
                        {s.desc}
                      </div>
                    </div>
                  </button>
                )
              })}
            </nav>

            <div className="p-3 border-t border-gray-800 mt-2">
              <button
                onClick={() => { setShowProjectList(true); setActiveProject(null) }}
                className="w-full text-xs text-gray-600 hover:text-gray-300 py-1.5 flex items-center justify-center gap-1 transition-colors"
              >
                ← 채널 목록으로
              </button>
            </div>
          </aside>
        )}

        {/* ── 메인 콘텐츠 ── */}
        <main className="flex-1 overflow-y-auto">
          {showProjectList || !activeProject ? (
            <ChannelSetup
              projects={projects}
              onSelect={handleSelectProject}
              onCreate={handleCreateProject}
              onDelete={handleDeleteProject}
            />
          ) : (
            <div className="max-w-3xl mx-auto p-6">
              {/* 현재 단계 헤더 */}
              {currentStep && step !== 'setup' && (
                <div className="mb-6">
                  <div className="flex items-center gap-2 text-xs text-gray-500 mb-1">
                    <span>단계 {currentStep.num}/{STEPS.length}</span>
                    <span>·</span>
                    <span>{currentStep.desc}</span>
                  </div>
                  <h1 className="text-xl font-bold text-white">
                    {currentStep.icon} {currentStep.label}
                  </h1>
                </div>
              )}

              {step === 'setup' && (
                <ChannelSetup
                  projects={projects}
                  onSelect={handleSelectProject}
                  onCreate={handleCreateProject}
                  onDelete={handleDeleteProject}
                />
              )}
              {step === 'tracks'   && <SongMaker {...stepProps} />}
              {step === 'images'   && <ImageSelector {...stepProps} />}
              {step === 'metadata' && <MetadataPreview {...stepProps} />}
              {step === 'layers'   && <LayerPreview {...stepProps} />}
              {step === 'build'    && <BuildDownload {...stepProps} />}
              {step === 'youtube'  && <YouTubeUpload {...stepProps} />}

              {/* 이전/다음 단계 네비게이션 */}
              {step !== 'setup' && (
                <div className="mt-8 pt-4 border-t border-gray-800 flex justify-between items-center">
                  {(() => {
                    const idx = STEPS.findIndex(s => s.id === step)
                    const prev = STEPS[idx - 1]
                    const next = STEPS[idx + 1]
                    return (
                      <>
                        {prev ? (
                          <button
                            onClick={() => setStep(prev.id)}
                            className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-300 transition-colors"
                          >
                            ← {prev.icon} {prev.label}
                          </button>
                        ) : <div />}
                        {next ? (
                          <button
                            onClick={() => setStep(next.id)}
                            className="flex items-center gap-2 text-sm bg-gray-800 hover:bg-gray-700 text-gray-300 px-4 py-2 rounded-lg transition-colors"
                          >
                            다음: {next.icon} {next.label} →
                          </button>
                        ) : <div />}
                      </>
                    )
                  })()}
                </div>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
