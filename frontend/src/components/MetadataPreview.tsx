import { useState, useMemo, useEffect } from 'react'
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
  const [instruction, setInstruction] = useState('')
  const meta = project.metadata || { title: null, description: null, tags: [], comment: null }

  // 곡 제목에서 넘버/버전/날짜/확장자 제거
  function cleanTitle(raw: string): string {
    return raw
      .replace(/^\d{1,3}[_.\-\s]+/, '')        // 앞쪽 넘버: "01_", "03. ", "1-"
      .replace(/_v\d+$/i, '')                   // 뒤쪽 버전: "_v1", "_v2"
      .replace(/\.\w{2,4}$/, '')                // 확장자: ".mp3", ".wav"
      .replace(/\d{4}[-_.]\d{2}[-_.]\d{2}/, '') // 날짜: "2026-04-17"
      .replace(/_/g, ' ')                       // 언더스코어 → 공백
      .trim()
  }

  // 타임스탬프 자동 계산 (편집 가능)
  const initialTimestamps = useMemo(() => {
    const tracks = project.tracks || []
    if (tracks.length === 0) return []
    let elapsed = 0
    return tracks.map(t => {
      const ts = fmtTime(elapsed)
      elapsed += t.duration || 0
      return { time: ts, title: cleanTitle(t.title) }
    })
  }, [project.tracks])

  const [editableTimestamps, setEditableTimestamps] = useState(initialTimestamps)

  // tracks 변경 시 초기화
  useMemo(() => {
    setEditableTimestamps(initialTimestamps)
  }, [initialTimestamps])

  const timestampText = editableTimestamps.map(t => `${t.time} ${t.title}`).join('\n')

  const [title, setTitle] = useState(meta.title || '')
  const [description, setDescription] = useState(meta.description || '')
  const [tags, setTags] = useState((meta.tags || []).join(', '))
  const [comment, setComment] = useState(meta.comment || '')
  const [thumbnailText, setThumbnailText] = useState('')
  const [readingThumb, setReadingThumb] = useState(false)

  // 썸네일이 있고 제목이 비어있으면 텍스트 OCR 시도
  useEffect(() => {
    if (project.images?.thumbnail && !meta.title) {
      setReadingThumb(true)
      api.metadata.readThumbnail(project.id)
        .then(r => { if (r.text) setThumbnailText(r.text) })
        .catch(() => {})
        .finally(() => setReadingThumb(false))
    }
  }, [project.images?.thumbnail, project.id, meta.title])

  const handleGenerate = async (regenerate = false) => {
    setGenerating(true)
    try {
      const result = await api.metadata.generate(project.id, regenerate, instruction)
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

      {/* AI 생성 지시사항 */}
      <div className="mb-5">
        <div className="flex items-center gap-2 mb-1.5">
          <label className="text-sm text-gray-400">AI 지시사항</label>
          <span className="text-[10px] text-gray-600">(선택) 벤치마크 제목, 채널 링크, 또는 자유롭게 작성</span>
        </div>
        <textarea
          value={instruction}
          onChange={e => setInstruction(e.target.value)}
          placeholder={"예시:\n- \"이 영상 스타일로 만들어줘: Best Relaxing Piano Music 2024\"\n- \"제목은 영어로, 설명은 한영 혼합으로\"\n- \"수면/명상 키워드 위주로 태그 작성\""}
          rows={3}
          className="w-full bg-gray-900/50 border border-gray-800 text-gray-300 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-purple-500/50 resize-y placeholder:text-gray-700"
        />
        {project.channel_id && (
          <p className="text-[10px] text-gray-600 mt-1">
            채널 연결됨 — YouTube 인증 시 기존 영상 스타일을 자동 참조합니다
          </p>
        )}
      </div>

      {project.tracks.length === 0 && (
        <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg p-3 mb-4 text-sm text-yellow-400">
          트랙을 먼저 추가해야 메타데이터 AI 생성이 가능합니다.
        </div>
      )}

      <div className="space-y-4">
        <div>
          <label className="block text-sm text-gray-400 mb-1">제목</label>
          <div className="relative">
            <input
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder={thumbnailText || 'YouTube 영상 제목'}
              maxLength={100}
              className="w-full bg-gray-900 border border-gray-800 text-white rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-purple-500"
            />
            {readingThumb && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-600">
                썸네일 읽는 중...
              </span>
            )}
          </div>
          <div className="flex items-center justify-between mt-1">
            {thumbnailText && !title ? (
              <button
                onClick={() => setTitle(thumbnailText.slice(0, 100))}
                className="text-[10px] text-purple-400/60 hover:text-purple-400 transition-colors"
              >
                썸네일 텍스트 사용: "{thumbnailText.length > 40 ? thumbnailText.slice(0, 40) + '...' : thumbnailText}"
              </button>
            ) : (
              <span />
            )}
            <span className="text-xs text-gray-600">{title.length}/100</span>
          </div>
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

        {editableTimestamps.length > 0 && (
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
            <div className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 font-mono text-xs text-gray-300 leading-relaxed">
              {editableTimestamps.map((t, i) => (
                <div key={i} className="flex items-center gap-2 py-0.5">
                  <span className="text-purple-400 shrink-0 w-12">{t.time}</span>
                  <input
                    value={t.title}
                    onChange={e => {
                      const updated = [...editableTimestamps]
                      updated[i] = { ...updated[i], title: e.target.value }
                      setEditableTimestamps(updated)
                    }}
                    className="flex-1 bg-transparent text-gray-200 border-b border-transparent hover:border-gray-700 focus:border-purple-500 focus:outline-none px-1 py-0.5 text-xs"
                  />
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
