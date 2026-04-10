import { useState, useMemo } from 'react'
import type { Project } from '../types'
import { api } from '../api/client'

function fmtTime(sec: number): string {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = Math.floor(sec % 60)
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`
}

interface Props {
  project: Project
  onRefresh: () => void
}

export default function MetadataPreview({ project, onRefresh }: Props) {
  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)
  const meta = project.metadata || { title: null, description: null, tags: [], comment: null }

  // 타임스탬프 자동 계산
  const timestamps = useMemo(() => {
    const tracks = project.tracks || []
    if (tracks.length === 0) return []
    let elapsed = 0
    return tracks.map(t => {
      const ts = fmtTime(elapsed)
      elapsed += t.duration || 0
      return { time: ts, title: t.title }
    })
  }, [project.tracks])

  const timestampText = timestamps.map(t => `${t.time} ${t.title}`).join('\n')

  const [title, setTitle] = useState(meta.title || '')
  const [description, setDescription] = useState(meta.description || '')
  const [tags, setTags] = useState((meta.tags || []).join(', '))
  const [comment, setComment] = useState(meta.comment || '')

  const handleGenerate = async (regenerate = false) => {
    setGenerating(true)
    try {
      const result = await api.metadata.generate(project.id, regenerate)
      setTitle(result.title || '')
      setDescription(result.description || '')
      setTags((result.tags || []).join(', '))
      setComment(result.comment || '')
      await onRefresh()
    } catch (err: any) {
      alert('생성 실패: ' + (err.response?.data?.detail || err.message))
    } finally {
      setGenerating(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.metadata.update(project.id, {
        title: title || null,
        description: description || null,
        tags: tags.split(',').map(t => t.trim()).filter(Boolean),
        comment: comment || null,
      })
      await onRefresh()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-end mb-5">
        <div className="flex gap-2">
          <button
            onClick={() => handleGenerate(false)}
            disabled={generating}
            className="bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium"
          >
            {generating ? '⏳ 생성 중...' : '✨ AI 생성'}
          </button>
          <button
            onClick={() => handleGenerate(true)}
            disabled={generating}
            className="bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium"
          >
            재생성
          </button>
        </div>
      </div>

      {project.tracks.length === 0 && (
        <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg p-3 mb-4 text-sm text-yellow-400">
          트랙을 먼저 추가해야 메타데이터 AI 생성이 가능합니다.
        </div>
      )}

      <div className="space-y-4">
        <div>
          <label className="block text-sm text-gray-400 mb-1">제목</label>
          <input
            value={title}
            onChange={e => setTitle(e.target.value)}
            placeholder="YouTube 영상 제목"
            maxLength={100}
            className="w-full bg-gray-900 border border-gray-800 text-white rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-purple-500"
          />
          <div className="text-xs text-gray-600 text-right mt-1">{title.length}/100</div>
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-1">설명</label>
          <textarea
            value={description}
            onChange={e => setDescription(e.target.value)}
            placeholder="YouTube 영상 설명"
            rows={8}
            maxLength={5000}
            className="w-full bg-gray-900 border border-gray-800 text-white rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-purple-500 resize-y font-mono"
          />
          <div className="text-xs text-gray-600 text-right mt-1">{description.length}/5000</div>
        </div>

        {timestamps.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-sm text-gray-400">타임스탬프</label>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(timestampText)
                }}
                className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
              >
                복사
              </button>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 font-mono text-xs text-gray-300 leading-relaxed whitespace-pre-wrap">
              {timestamps.map((t, i) => (
                <div key={i} className="flex gap-3">
                  <span className="text-purple-400 shrink-0">{t.time}</span>
                  <span>{t.title}</span>
                </div>
              ))}
            </div>
            <div className="flex gap-2 mt-1.5">
              <button
                onClick={() => {
                  const tsBlock = '\n\n🎵 Tracklist\n' + timestampText
                  setDescription(prev => prev.includes(timestampText) ? prev : prev + tsBlock)
                }}
                className="text-xs text-purple-400 hover:text-purple-300 transition-colors"
              >
                설명에 추가
              </button>
              <button
                onClick={() => {
                  const tsBlock = '\n\n🎵 Tracklist\n' + timestampText
                  setComment(prev => prev.includes(timestampText) ? prev : prev + tsBlock)
                }}
                className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
              >
                댓글에 추가
              </button>
            </div>
          </div>
        )}

        <div>
          <label className="block text-sm text-gray-400 mb-1">
            태그 <span className="text-gray-600">(쉼표로 구분)</span>
          </label>
          <input
            value={tags}
            onChange={e => setTags(e.target.value)}
            placeholder="태그1, 태그2, 태그3"
            className="w-full bg-gray-900 border border-gray-800 text-white rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-purple-500"
          />
          <div className="text-xs text-gray-600 mt-1">
            {tags.split(',').filter(t => t.trim()).length}/30 태그
          </div>
        </div>

        <div>
          <label className="block text-sm text-gray-400 mb-1">고정 댓글</label>
          <textarea
            value={comment}
            onChange={e => setComment(e.target.value)}
            placeholder="첫 번째 댓글로 고정할 내용"
            rows={4}
            maxLength={500}
            className="w-full bg-gray-900 border border-gray-800 text-white rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-purple-500 resize-y"
          />
          <div className="text-xs text-gray-600 text-right mt-1">{comment.length}/500</div>
        </div>

        <button
          onClick={handleSave}
          disabled={saving}
          className="w-full bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-white py-2.5 rounded-xl text-sm font-medium"
        >
          {saving ? '저장 중...' : '💾 저장'}
        </button>
      </div>
    </div>
  )
}
