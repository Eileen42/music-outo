import { useState } from 'react'
import type { Project, WaveformLayerConfig, TextLayerConfig } from '../types'
import { api } from '../api/client'

interface Props {
  project: Project
  onRefresh: () => void
}

const DEFAULT_WAVEFORM: WaveformLayerConfig = {
  enabled: true,
  style: 'bar',
  color: '#FFFFFF',
  opacity: 0.8,
  position_y: 0.5,
}

export default function LayerPreview({ project, onRefresh }: Props) {
  const [saving, setSaving] = useState(false)
  const layers = project.layers || { background_video: null, waveform_layer: null, text_layers: [] }
  const wf = layers.waveform_layer || DEFAULT_WAVEFORM

  const [waveform, setWaveform] = useState<WaveformLayerConfig>(wf)
  const [newText, setNewText] = useState('')
  const [addingText, setAddingText] = useState(false)

  const handleSaveWaveform = async () => {
    setSaving(true)
    try {
      await api.layers.update(project.id, { ...layers, waveform_layer: waveform })
      await onRefresh()
    } finally {
      setSaving(false)
    }
  }

  const handleAddText = async () => {
    if (!newText.trim()) return
    setAddingText(true)
    try {
      await api.layers.addText(project.id, {
        text: newText.trim(),
        font_size: 48,
        color: '#FFFFFF',
        position_x: 0.5,
        position_y: 0.1,
        bold: true,
      })
      setNewText('')
      await onRefresh()
    } finally {
      setAddingText(false)
    }
  }

  const handleDeleteText = async (layerId: string) => {
    await api.layers.deleteText(project.id, layerId)
    await onRefresh()
  }

  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-5">🎬 레이어 설정</h2>

      {/* 파형 레이어 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-gray-300">파형 레이어</h3>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={waveform.enabled}
              onChange={e => setWaveform(w => ({ ...w, enabled: e.target.checked }))}
              className="w-4 h-4 accent-purple-600"
            />
            <span className="text-sm text-gray-400">활성화</span>
          </label>
        </div>

        {waveform.enabled && (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">스타일</label>
              <select
                value={waveform.style}
                onChange={e => setWaveform(w => ({ ...w, style: e.target.value as any }))}
                className="w-full bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-700"
              >
                <option value="bar">Bar (막대)</option>
                <option value="line">Line (선)</option>
                <option value="circle">Circle</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">색상</label>
              <div className="flex gap-2">
                <input
                  type="color"
                  value={waveform.color}
                  onChange={e => setWaveform(w => ({ ...w, color: e.target.value }))}
                  className="w-10 h-9 rounded bg-gray-800 border border-gray-700 cursor-pointer"
                />
                <input
                  value={waveform.color}
                  onChange={e => setWaveform(w => ({ ...w, color: e.target.value }))}
                  className="flex-1 bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-700"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">불투명도 ({Math.round(waveform.opacity * 100)}%)</label>
              <input
                type="range" min={0} max={1} step={0.05}
                value={waveform.opacity}
                onChange={e => setWaveform(w => ({ ...w, opacity: parseFloat(e.target.value) }))}
                className="w-full accent-purple-600"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Y 위치 ({Math.round(waveform.position_y * 100)}%)</label>
              <input
                type="range" min={0} max={1} step={0.05}
                value={waveform.position_y}
                onChange={e => setWaveform(w => ({ ...w, position_y: parseFloat(e.target.value) }))}
                className="w-full accent-purple-600"
              />
            </div>
          </div>
        )}

        <button
          onClick={handleSaveWaveform}
          disabled={saving}
          className="mt-4 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm"
        >
          {saving ? '저장 중...' : '저장'}
        </button>
      </div>

      {/* 텍스트 레이어 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-gray-300 mb-3">텍스트 레이어</h3>

        <div className="flex gap-2 mb-4">
          <input
            value={newText}
            onChange={e => setNewText(e.target.value)}
            placeholder="텍스트 내용"
            className="flex-1 bg-gray-800 text-white rounded-lg px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-purple-500"
            onKeyDown={e => { if (e.key === 'Enter') handleAddText() }}
          />
          <button
            onClick={handleAddText}
            disabled={addingText || !newText.trim()}
            className="bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm"
          >
            추가
          </button>
        </div>

        {layers.text_layers.length === 0 && (
          <div className="text-center py-6 text-gray-600 text-sm">텍스트 레이어 없음</div>
        )}

        <div className="space-y-2">
          {layers.text_layers.map(layer => (
            <div key={layer.id} className="flex items-center gap-3 bg-gray-800 rounded-lg p-3">
              <div
                className="w-4 h-4 rounded shrink-0"
                style={{ backgroundColor: layer.color }}
              />
              <span className="flex-1 text-sm text-white truncate">{layer.text}</span>
              <span className="text-xs text-gray-500">{layer.font_size}px</span>
              <span className="text-xs text-gray-500">
                ({Math.round(layer.position_x * 100)}%, {Math.round(layer.position_y * 100)}%)
              </span>
              <button
                onClick={() => handleDeleteText(layer.id)}
                className="text-gray-600 hover:text-red-400 text-xs"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
