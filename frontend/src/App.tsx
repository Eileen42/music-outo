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
import RegisterForm from './components/RegisterForm'
import PendingApproval from './components/PendingApproval'
import AdminPage from './components/AdminPage'
import GeminiSetup from './components/GeminiSetup'
import LandingPage from './components/LandingPage'
import DownloadPage from './components/DownloadPage'
import GuidePage from './components/GuidePage'

type AuthState = 'loading' | 'landing' | 'register' | 'pending' | 'rejected' | 'approved'

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
  const [step, setStep] = useState<StepId>(() => (localStorage.getItem('step') as StepId) || 'setup')
  const [showProjectList, setShowProjectList] = useState(() => !localStorage.getItem('projectId'))
  const [restored, setRestored] = useState(false)
  const [serverOnline, setServerOnline] = useState<boolean | null>(null) // null = 아직 확인 안 됨
  const [authState, setAuthState] = useState<AuthState>('loading')
  const [authToken, setAuthToken] = useState(() => localStorage.getItem('auth_token') || sessionStorage.getItem('auth_token') || '')
  const [userName, setUserName] = useState('')
  const [geminiConfigured, setGeminiConfigured] = useState<boolean | null>(null)
  const [showAdmin, setShowAdmin] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('admin') === 'true'
  })
  const [showGuide, setShowGuide] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('guide') === 'true'
  })

  const backendUrl = localStorage.getItem('backend_url') || import.meta.env.VITE_API_URL || 'http://localhost:8000'

  const handleLogout = () => {
    localStorage.removeItem('auth_token')
    sessionStorage.removeItem('auth_token')
    setAuthToken('')
    setUserName('')
    setAuthState('register')
  }

  // 실행 환경 감지
  // - localhost:3000 → 설치된 앱(작업 UI 전용)
  // - *.vercel.app 등 → 공개 웹(랜딩·가입·승인·다운로드 전용)
  const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  const isVercel = !isLocal

  // 인증 상태 확인
  useEffect(() => {
    // 로컬 환경에서는 인증 없이 바로 사용
    if (isLocal) {
      setAuthState('approved')
      setUserName('로컬 사용자')
      return
    }

    // Vercel 환경에서 토큰이 없으면 랜딩 페이지부터
    if (!authToken) {
      setAuthState('landing')
      return
    }

    const checkAuth = async () => {
      try {
        const res = await fetch(`/api/auth/status?token=${authToken}`)
        const data = await res.json()
        if (data.name) setUserName(data.name)
        if (data.status === 'approved') setAuthState('approved')
        else if (data.status === 'pending') setAuthState('pending')
        else if (data.status === 'rejected' || data.status === 'blocked') setAuthState('rejected')
        else setAuthState('register')
      } catch {
        setAuthState('register')
      }
    }
    checkAuth()
  }, [authToken, isLocal])

  // 서버 연결 상태 체크 (5초마다) — 로컬(설치된 앱)에서만 의미 있음
  useEffect(() => {
    if (authState !== 'approved') return
    if (isVercel) return  // Vercel 은 로컬 백엔드 체크 대상 아님

    const check = async () => {
      try {
        const res = await fetch(backendUrl + '/health')
        if (res.ok) {
          setServerOnline(true)
          localStorage.setItem('connected_before', 'true')
          // Gemini 키 설정 여부 확인
          try {
            const gRes = await fetch(backendUrl + '/api/settings/gemini')
            const gData = await gRes.json()
            setGeminiConfigured(gData.configured)
          } catch {
            setGeminiConfigured(null)
          }
          return
        }
      } catch {
        try {
          await fetch(backendUrl + '/health', { mode: 'no-cors' })
          setServerOnline(true)
          localStorage.setItem('connected_before', 'true')
          return
        } catch {
          // 서버 미연결
        }
      }
      setServerOnline(false)
    }
    check()
    const id = setInterval(check, 5000)
    return () => clearInterval(id)
  }, [authState, backendUrl, isVercel])

  // 프로젝트 활성화 — 항상 full 데이터 로드 후 표시
  const activateProject = useCallback(async (id: string, targetStep?: StepId) => {
    const full = await api.projects.get(id)
    setActiveProject(full)
    setProjects(prev => prev.some(p => p.id === id) ? prev.map(p => p.id === id ? full : p) : [full, ...prev])
    setShowProjectList(false)
    if (targetStep) setStep(targetStep)
  }, [])

  const loadProjects = useCallback(async () => {
    const list = await api.projects.list()
    setProjects(list)
    // 새로고침 시 이전 프로젝트+단계 복원 (1회만)
    if (!restored) {
      const savedId = localStorage.getItem('projectId')
      const savedStep = localStorage.getItem('step') as StepId
      if (savedId && list.find(p => p.id === savedId)) {
        if (savedStep) setStep(savedStep)
        setRestored(true)
        await activateProject(savedId)
        return
      }
      setRestored(true)
    }
  }, [restored, activateProject])

  const refreshProject = useCallback(async (id: string) => {
    const updated = await api.projects.get(id)
    setActiveProject(updated)
    setProjects(prev => prev.map(p => p.id === id ? updated : p))
  }, [])

  // 상태 변경 시 localStorage에 저장 (초기 null은 무시)
  useEffect(() => {
    if (activeProject) localStorage.setItem('projectId', activeProject.id)
    // null일 때 삭제하지 않음 — 초기 로드 시 복원 방해됨
    // 삭제는 handleBackToList에서만 수행
  }, [activeProject])

  useEffect(() => { localStorage.setItem('step', step) }, [step])

  const handleBackToList = () => {
    setShowProjectList(true)
    setActiveProject(null)
    localStorage.removeItem('projectId')
    localStorage.setItem('step', 'setup')
  }

  useEffect(() => { loadProjects() }, [loadProjects])

  const handleSelectProject = async (p: Project) => {
    await activateProject(p.id, 'tracks')
  }

  const handleCreateProject = async (name: string, playlistTitle: string, channelId: string) => {
    const p = await api.projects.create(name, playlistTitle)
    if (channelId) {
      await api.projects.update(p.id, { channel_id: channelId })
    }
    await activateProject(p.id, 'tracks')
  }

  const handleDeleteProject = async (id: string) => {
    await api.projects.delete(id)
    await loadProjects()
    if (activeProject?.id === id) {
      handleBackToList()
    }
  }

  const stepProps = { project: activeProject!, onRefresh: () => refreshProject(activeProject!.id) }
  const currentStep = STEPS.find(s => s.id === step)
  const completedCount = activeProject ? getCompletedCount(activeProject) : 0

  // 인증 흐름 — 가입/대기/거절 화면
  if (authState === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950">
        <div className="text-gray-500 text-sm">로딩 중...</div>
      </div>
    )
  }

  if (showGuide) {
    return <GuidePage onBack={() => {
      setShowGuide(false)
      const url = new URL(window.location.href)
      url.searchParams.delete('guide')
      window.history.replaceState({}, '', url.toString())
    }} />
  }

  if (showAdmin) {
    return <AdminPage onBack={() => setShowAdmin(false)} />
  }

  // Vercel 방문자 첫 화면 (비로그인)
  if (authState === 'landing') {
    return (
      <LandingPage
        onStart={() => setAuthState('register')}
        onAdmin={() => setShowAdmin(true)}
        onGuide={() => setShowGuide(true)}
      />
    )
  }

  if (authState === 'register') {
    return (
      <RegisterForm onRegistered={(token) => {
        setAuthToken(token)
        setAuthState('pending')
      }} />
    )
  }

  if (authState === 'pending') {
    return (
      <PendingApproval
        token={authToken}
        onApproved={() => setAuthState('approved')}
        onRejected={() => setAuthState('rejected')}
      />
    )
  }

  if (authState === 'rejected') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950 px-4">
        <div className="w-full max-w-md text-center bg-gray-900 rounded-xl border border-gray-800 p-8">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-red-900/30 flex items-center justify-center">
            <span className="text-3xl">❌</span>
          </div>
          <h2 className="text-xl font-bold text-white mb-2">가입이 거절되었습니다</h2>
          <p className="text-gray-400 text-sm mb-4">관리자에게 문의해주세요.</p>
          <button
            onClick={() => { localStorage.removeItem('auth_token'); setAuthToken(''); setAuthState('register') }}
            className="text-sm text-purple-400 hover:text-purple-300"
          >
            다른 계정으로 가입
          </button>
        </div>
      </div>
    )
  }

  // Vercel 에서 승인된 사용자 → 다운로드 안내 화면 (작업 UI 접근 X)
  if (authState === 'approved' && isVercel) {
    return (
      <DownloadPage
        userName={userName}
        onLogout={handleLogout}
        onGuide={() => setShowGuide(true)}
      />
    )
  }

  // 승인됨 + 서버 확인 중 → 연결 중 화면
  if (authState === 'approved' && serverOnline === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-purple-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <div className="text-gray-400 text-sm">서버 연결 중...</div>
          <div className="text-gray-600 text-xs mt-1">5초마다 자동 재시도</div>
        </div>
      </div>
    )
  }

  // 승인됨 + 백엔드 미연결 → 로그인된 사용자는 항상 "연결 중..." 표시
  // (로그인 자체가 등록된 사용자라는 증거 → 설치 안내 불필요)
  if (authState === 'approved' && serverOnline === false) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950 px-4">
        <div className="w-full max-w-md text-center">
          <div className="w-12 h-12 border-2 border-yellow-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <h2 className="text-lg font-bold text-white mb-2">로컬 서버 연결 중...</h2>
          <p className="text-gray-400 text-sm mb-4">
            서버가 아직 시작되지 않았습니다.<br />
            자동 시작이 설정되어 있다면 잠시 기다려주세요.
          </p>
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 text-left mb-4">
            <p className="text-xs text-gray-500 mb-2">서버가 시작되지 않나요?</p>
            <p className="text-xs text-gray-400">
              프로젝트 폴더의 <code className="text-purple-300 bg-gray-800 px-1 rounded">start.bat</code>을 더블클릭하거나,<br />
              <code className="text-purple-300 bg-gray-800 px-1 rounded">install_autostart.bat</code>으로 자동 시작을 등록하세요.
            </p>
          </div>
          <p className="text-gray-600 text-xs">5초마다 자동 재연결 시도 중</p>
          <button
            onClick={() => setShowAdmin(true)}
            className="fixed bottom-2 right-3 text-[10px] text-gray-700 hover:text-gray-500 transition-colors"
          >
            관리자
          </button>
        </div>
      </div>
    )
  }

  // 승인됨 + 서버 연결 + Gemini 미설정 → Gemini 설정 화면
  if (authState === 'approved' && serverOnline && geminiConfigured === false) {
    return (
      <div className="min-h-screen bg-gray-950">
        <GeminiSetup onComplete={() => setGeminiConfigured(true)} />
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col bg-gray-950">
      {/* ── 헤더 ── */}
      <header className="bg-gray-900 border-b border-gray-800 px-5 py-3 flex items-center gap-4 shrink-0">
        <button
          onClick={() => handleBackToList()}
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

        {/* 사용자 정보 + 로그아웃 */}
        <div className={`${activeProject && !showProjectList ? '' : 'ml-auto'} flex items-center gap-2`}>
          {userName && (
            <span className="text-xs text-gray-500 hidden sm:inline">{userName}</span>
          )}
          <button
            onClick={handleLogout}
            className="text-xs text-gray-600 hover:text-gray-400 transition-colors px-2 py-1 rounded hover:bg-gray-800"
          >
            로그아웃
          </button>
        </div>
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
                onClick={() => handleBackToList()}
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

      {/* 관리자 링크 — 눈에 잘 안 띄게 */}
      <button
        onClick={() => setShowAdmin(true)}
        className="fixed bottom-2 right-3 text-[10px] text-gray-700 hover:text-gray-500 transition-colors"
      >
        관리자
      </button>
    </div>
  )
}
