export interface Track {
  id: string
  title: string
  artist: string
  order: number
  filename: string
  stored_path: string
  duration: number
  sample_rate: number
  channels: number
  waveform_file: string | null
  lyrics: string | null
  lyrics_sync_file: string | null
}

export interface ProjectImages {
  thumbnail: string | null
  background: string | null
  additional: string[]
}

export interface ProjectMetadata {
  title: string | null
  description: string | null
  tags: string[]
  comment: string | null
}

export interface WaveformLayerConfig {
  enabled: boolean
  style: 'bar' | 'line' | 'circle'
  color: string
  opacity: number
  position_x: number      // 중심 X (0~1)
  position_y: number      // 중심 Y (0~1)
  bar_count: number       // 막대 개수
  bar_width: number       // 개별 막대 너비 (px)
  bar_gap: number          // 막대 간격 (px)
  bar_height: number      // 막대 최대 높이 (px 기준 1920)
  bar_min: number          // 최소 높이 비율 (0~1)
  bar_align: 'center' | 'bottom' | 'top'
  scale: number            // 전체 스케일 (1.0 = 100%)
  circle_radius: number
}

export interface TextShadow {
  enabled: boolean
  color: string        // hex
  alpha: number        // 0~1
  angle: number        // degrees
  distance: number     // px
  blur: number         // px (smoothing)
}

export interface TextAnimation {
  type: 'fade_in' | 'fade_out' | 'slide_up' | 'slide_down' | 'typewriter' | 'none'
  duration: number     // seconds
}

export interface TextLayerConfig {
  id: string
  text: string
  font_size: number
  font_family: string
  color: string
  alpha: number         // 텍스트 불투명도 0~1
  position_x: number
  position_y: number
  scale_x: number       // 가로 스케일 0~2
  scale_y: number       // 세로 스케일 0~2
  bold: boolean
  italic: boolean
  letter_spacing: number // px
  line_spacing: number   // 비율
  alignment: 'left' | 'center' | 'right'
  shadow: TextShadow
  animation_in: TextAnimation
  animation_out: TextAnimation
  // 역할 구분
  role: 'title' | 'subtitle' | 'description' | 'custom'
}

export interface EffectLayerConfig {
  enabled: boolean
  name: string               // 표시명 (예: 반딧불이)
  effect_id: string          // CapCut resource ID
  params: Record<string, number>  // {animation: 0.46, speed: 0.14}
}

export interface ImageLayerConfig {
  id: string
  name: string
  stored_path: string
  position_x: number
  position_y: number
  scale: number
  opacity: number
}

export interface ProjectLayers {
  background_video: string | null
  waveform_layer: WaveformLayerConfig | null
  text_layers: TextLayerConfig[]
  effect_layers: EffectLayerConfig[]
  image_layers?: ImageLayerConfig[]
  subtitle_style?: Partial<TextLayerConfig>
  subtitle_enabled?: boolean
}

export interface LayerTemplate {
  name: string
  waveform_layer: WaveformLayerConfig | null
  text_layers: Omit<TextLayerConfig, 'id'>[]
  effect_layers: EffectLayerConfig[]
  subtitle_style?: Omit<TextLayerConfig, 'id' | 'text' | 'position_x' | 'position_y'>  // 자막 기본 스타일
}

export interface BuildStatus {
  status: 'pending' | 'processing' | 'done' | 'error' | null
  output_file: string | null
  capcut_file: string | null
  error: string | null
  progress: number
}

export interface YouTubeInfo {
  video_id: string | null
  url: string | null
  uploaded_at: string | null
}

export interface RepeatConfig {
  mode: 'count' | 'duration'
  count: number          // mode=count: 전체 반복 횟수
  target_minutes: number // mode=duration: 목표 총 재생 시간(분)
}

export interface ImageMood {
  mood: string
  atmosphere: string
  colors: { dominant: string[]; tone: string; warmth: string }
  style: string
  lighting: string
  elements: string[]
  time_of_day: string
  season: string
  emotion: string
  music_genre_fit: string
  image_prompt: string
  thumbnail_prompt: string
  background_prompt: string
}

export interface Project {
  id: string
  user_id: string
  name: string
  playlist_title: string
  created_at: string
  updated_at: string
  status: string
  channel_id?: string
  benchmark_url?: string
  benchmark_data?: Record<string, unknown>
  subtitle_srt_path?: string
  subtitle_entries?: { start: number; end: number; text: string }[]
  tracks: Track[]
  images: ProjectImages
  metadata: ProjectMetadata
  layers: ProjectLayers
  build: BuildStatus
  youtube: YouTubeInfo
  repeat: RepeatConfig
  image_mood: ImageMood | null
  uploaded_set?: string
  active_suno_set?: string
  designed_tracks?: DesignedTrack[]
}

export interface UploadSettings {
  default_privacy: 'private' | 'unlisted' | 'public'
  default_tags: string[]
  default_description: string
  auto_add_playlist: boolean
}

export interface Channel {
  channel_id: string
  name: string
  genre: string[]
  has_lyrics: boolean
  subtitle_type: 'none' | 'affirmation' | 'lyrics'
  mood_keywords: string[]
  image_style: string[]
  suno_base_prompt: string
  upload_settings?: UploadSettings
  layer_templates?: LayerTemplate[]
  benchmark_history: BenchmarkResult[]
  created_at: string
  updated_at: string
}

export interface BenchmarkResult {
  url: string
  video_id: string
  title: string
  ai_analysis: {
    music_style: string
    mood: string[]
    estimated_track_count: number
    target_audience: string
  }
  analyzed_at: string
}

export interface ProjectConcept {
  project_name: string
  genre: string
  core_mood: string
  tempo: string
  bpm_range: string
  instrumentation: string
  atmosphere: string
  base_additional: string
}

export interface DesignedTrack {
  index: number
  title: string
  title_ko: string
  suno_prompt: string
  lyrics: string
  mood: string
  duration_hint: string
  category: string
}

export interface SunoTrack {
  index: number
  title: string
  suno_id: string
  file_path: string
  audio_url: string
  status: 'completed' | 'failed' | 'download_failed' | 'duplicate'
  slot: number  // 1 or 2 — Suno가 1회 생성 시 2곡 출력
  duplicate_of?: number  // 중복인 경우, 원본 곡 index
}

export type StepId =
  | 'setup'
  | 'tracks'
  | 'images'
  | 'metadata'
  | 'layers'
  | 'build'
  | 'youtube'
