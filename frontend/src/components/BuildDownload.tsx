import { useEffect, useState } from 'react'
import type { Project } from '../types'
import { api } from '../api/client'

interface Props {
  project: Project
  onRefresh: () => void
}

type BuildMode = 'mp4' | 'capcut'

export default function BuildDownload({ project, onRefresh }: Props) {
  const [triggering, setTriggering] = useState(false)
  const [buildMode, setBuildMode] = useState<BuildMode>('capcut')
  const [installing, setInstalling] = useState(false)
  const build = project.build || { status: null, progress: 0, output_file: null, capcut_file: null, error: null }

  useEffect(() => {
    if (build.status !== 'processing') return
    setInstalling(false)
    const interval = setInterval(async () => {
      const status = await api.build.status(project.id)
      if (status.status !== 'processing') {
        clearInterval(interval)
        if (status.status === 'done' && buildMode === 'capcut') {
          setInstalling(true)
          // CapCut 폴더에 설치 완료 대기
          setTimeout(() => { setInstalling(false) }, 4000)
        }
        await onRefresh()
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [build.status, project.id, onRefresh, buildMode])

  const handleBuild = async () => {
    if (!confirm('빌드를 시작하시겠습니까?')) return
    setTriggering(true)
    setInstalling(false)
    try {
      await api.build.trigger(project.id, buildMode)
      await onRefresh()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })
      alert('빌드 실패: ' + (msg?.response?.data?.detail || msg?.message || '알 수 없는 오류'))
    } finally {
      setTriggering(false)
    }
  }

  const checks = [
    {
      label: '🎵 트랙',
      ok: project.tracks.length > 0,
      msg: project.tracks.length > 0 ? `${project.tracks.length}개 준비됨` : '트랙을 추가하세요 (필수)',
      required: true,
    },
    {
      label: '🖼️ 배경 이미지',
      ok: !!(project.images?.background || project.images?.thumbnail),
      msg: project.images?.background ? '배경 설정됨' : project.images?.thumbnail ? '썸네일 사용' : '없음 (검은 배경)',
      required: false,
    },
    {
      label: '🎬 레이어',
      ok: !!(project.layers?.waveform_layer || (project.layers?.text_layers?.length ?? 0) > 0),
      msg: [
        project.layers?.waveform_layer?.enabled ? '파형' : '',
        (project.layers?.text_layers?.length ?? 0) > 0 ? `텍스트 ${project.layers?.text_layers?.length}개` : '',
        (project.layers?.effect_layers?.length ?? 0) > 0 ? '효과' : '',
      ].filter(Boolean).join(' · ') || '없음',
      required: false,
    },
    {
      label: '💬 자막',
      ok: (project.subtitle_entries?.length ?? 0) > 0,
      msg: project.subtitle_entries?.length ? `${project.subtitle_entries.length}개 자막` : '없음',
      required: false,
    },
  ]

  const isProcessing = build.status === 'processing'
  const isDone = build.status === 'done'
  const isError = build.status === 'error'

  return (
    <div>
      {/* 빌드 모드 선택 */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 mb-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">빌드 방식 선택</h3>
        <div className="grid grid-cols-2 gap-3">
          {([
            { mode: 'mp4' as BuildMode, icon: '🎬', label: 'MP4 영상', desc: 'FFmpeg로 직접 영상 렌더링 (FFmpeg 필요)' },
            { mode: 'capcut' as BuildMode, icon: '✂️', label: 'CapCut 프로젝트', desc: 'CapCut에서 열어 편집 후 렌더링' },
          ]).map(opt => (
            <button
              key={opt.mode}
              onClick={() => setBuildMode(opt.mode)}
              className={`p-3 rounded-xl border text-left transition-all ${
                buildMode === opt.mode
                  ? 'bg-purple-900/40 border-purple-500 ring-1 ring-purple-500'
                  : 'bg-gray-800 border-gray-700 hover:border-gray-600'
              }`}
            >
              <div className="text-lg mb-1">{opt.icon}</div>
              <div className="text-xs font-semibold text-white">{opt.label}</div>
              <div className="text-[10px] text-gray-500 mt-0.5">{opt.desc}</div>
            </button>
          ))}
        </div>
        {buildMode === 'mp4' && (
          <p className="text-[10px] text-yellow-500 mt-2">
            MP4 빌드에는 FFmpeg 설치가 필요합니다.
          </p>
        )}
      </div>

      {/* 체크리스트 */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 mb-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">빌드 전 체크리스트</h3>
        <div className="space-y-2">
          {checks.map(c => (
            <div key={c.label} className="flex items-center gap-3">
              <span className={`shrink-0 w-5 h-5 flex items-center justify-center rounded-full text-xs font-bold ${
                c.ok ? 'bg-green-700 text-white' : c.required ? 'bg-red-900 text-red-400 border border-red-700' : 'bg-gray-800 text-gray-600 border border-gray-700'
              }`}>
                {c.ok ? '✓' : c.required ? '!' : '○'}
              </span>
              <span className={`text-sm ${c.ok ? 'text-gray-200' : 'text-gray-500'}`}>{c.label}</span>
              <span className={`text-xs ml-auto ${c.ok ? 'text-gray-500' : c.required ? 'text-red-400' : 'text-gray-600'}`}>{c.msg}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 빌드 상태 */}
      {build.status && (
        <div className={`rounded-2xl p-5 mb-4 border ${
          isError ? 'bg-red-950/30 border-red-800' :
          isDone  ? 'bg-green-950/30 border-green-800' :
                    'bg-yellow-950/30 border-yellow-800'
        }`}>
          {isProcessing && (
            <>
              <div className="flex items-center justify-between mb-3">
                <span className="text-yellow-400 font-semibold text-sm">⚙️ 빌드 진행 중...</span>
                <span className="text-yellow-300 text-sm font-mono">{build.progress}%</span>
              </div>
              <div className="w-full bg-gray-800 rounded-full h-2.5">
                <div className="bg-purple-500 h-2.5 rounded-full transition-all duration-500" style={{ width: `${build.progress}%` }} />
              </div>
            </>
          )}
          {isDone && buildMode === 'capcut' && installing && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="inline-block w-4 h-4 border-2 border-indigo-400/30 border-t-indigo-400 rounded-full animate-spin" />
                <span className="text-indigo-400 font-semibold text-sm">CapCut 프로젝트 폴더에 설치 중...</span>
              </div>
              <div className="w-full bg-gray-800 rounded-full h-2">
                <div className="bg-indigo-500 h-2 rounded-full animate-pulse" style={{ width: '70%' }} />
              </div>
              <p className="text-[10px] text-gray-500">CapCut을 열면 홈 화면에 프로젝트가 나타납니다.</p>
            </div>
          )}
          {isDone && (!installing || buildMode !== 'capcut') && (
            <div className="text-green-400 font-semibold text-sm">
              {buildMode === 'capcut' ? '✅ CapCut 프로젝트 설치 완료! CapCut을 열어 확인하세요.' : '✅ 빌드 완료!'}
            </div>
          )}
          {isError && (
            <>
              <div className="flex items-center justify-between mb-2">
                <span className="text-red-400 font-semibold text-sm">❌ 빌드 실패</span>
                <button onClick={async () => { await api.build.reset(project.id); await onRefresh() }}
                  className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded border border-gray-700 hover:border-gray-500">
                  초기화
                </button>
              </div>
              {build.error && (
                <div className="text-red-300 text-xs font-mono bg-gray-900 rounded-lg p-3 overflow-auto max-h-32">{build.error}</div>
              )}
            </>
          )}
        </div>
      )}

      {/* 다운로드 */}
      {isDone && (
        <div className="bg-gray-900 border border-green-800 rounded-2xl p-5 mb-4">
          <h3 className="text-sm font-semibold text-gray-200 mb-3">📥 결과물 다운로드</h3>
          <div className="flex gap-3 flex-wrap">
            {build.output_file && (
              <a href={api.build.downloadUrl(project.id)} download
                className="flex items-center gap-2 bg-green-700 hover:bg-green-600 text-white px-5 py-2.5 rounded-xl text-sm font-semibold transition-colors">
                🎬 MP4 영상 다운로드
              </a>
            )}
            {build.capcut_file && (
              <a href={api.build.downloadCapcutUrl(project.id)} download
                className="flex items-center gap-2 bg-indigo-700 hover:bg-indigo-600 text-white px-5 py-2.5 rounded-xl text-sm font-semibold transition-colors">
                ✂️ CapCut 프로젝트 다운로드
              </a>
            )}
            {!build.output_file && !build.capcut_file && (
              <p className="text-xs text-gray-500">다운로드할 파일이 없습니다.</p>
            )}
          </div>

          {/* CapCut 미디어 연결 경로 안내 */}
          {buildMode === 'capcut' && build.capcut_file && (
            <div className="mt-4 bg-gray-800 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-semibold text-gray-300">📂 CapCut 미디어 연결 경로</span>
                <button onClick={() => {
                  const path = build.capcut_file!.replace(/\\/g, '/').replace(/\/[^/]+\.zip$/, '/Resources')
                    .replace('/outputs/', '/').replace(/\/capcut_project\//, '/')
                  // CapCut 프로젝트 폴더 내 Resources
                  const capcut = `C:/Users/${path.includes('tofha') ? 'tofha' : 'user'}/AppData/Local/CapCut/User Data/Projects/com.lveditor.draft/${project.name}/Resources`
                  navigator.clipboard.writeText(capcut)
                }} className="text-[10px] text-indigo-400 hover:text-indigo-300 ml-auto">복사</button>
              </div>
              <p className="text-[10px] text-gray-500 mb-2">CapCut에서 "미디어 연결" 팝업이 나타나면 아래 경로로 지정하세요:</p>
              <div className="bg-gray-900 rounded-lg px-3 py-2 text-xs text-gray-300 font-mono break-all select-all">
                C:\Users\tofha\AppData\Local\CapCut\User Data\Projects\com.lveditor.draft\{project.name}\Resources
              </div>
            </div>
          )}
        </div>
      )}

      {/* 빌드 버튼 */}
      <button
        onClick={handleBuild}
        disabled={triggering || isProcessing || project.tracks.length === 0}
        className={`w-full py-3.5 rounded-2xl font-bold text-base transition-colors ${
          isProcessing || triggering ? 'bg-gray-700 text-gray-400 cursor-not-allowed'
          : project.tracks.length === 0 ? 'bg-gray-800 text-gray-600 cursor-not-allowed'
          : isDone ? 'bg-gray-700 hover:bg-gray-600 text-white'
          : 'bg-purple-600 hover:bg-purple-500 text-white'
        }`}
      >
        {isProcessing ? '⏳ 빌드 중...' :
         triggering   ? '⏳ 시작 중...' :
         isDone       ? '🔄 다시 빌드' :
         isError      ? '🔄 재시도' :
                        '🚀 빌드 시작'}
      </button>
    </div>
  )
}
