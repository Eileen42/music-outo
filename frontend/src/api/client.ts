import axios from 'axios'
import type { Project, Track, ProjectImages, ProjectMetadata, ProjectLayers, BuildStatus, RepeatConfig, ImageMood, Channel, DesignedTrack, ProjectConcept, SunoTrack, LayerTemplate } from '../types'

function getBackendUrl() {
  return localStorage.getItem('backend_url') || import.meta.env.VITE_API_URL || 'http://localhost:8000'
}

const BASE = getBackendUrl()

const http = axios.create({ baseURL: BASE })

// ─── Projects ────────────────────────────────────────────────────────────────

export const api = {
  projects: {
    list: () => http.get<Project[]>('/api/projects').then(r => r.data),
    create: (name: string, playlist_title: string) =>
      http.post<Project>('/api/projects', { name, playlist_title }).then(r => r.data),
    get: (id: string) => http.get<Project>(`/api/projects/${id}`).then(r => r.data),
    update: (id: string, data: Partial<Pick<Project, 'name' | 'playlist_title' | 'status' | 'channel_id'>>) =>
      http.patch<Project>(`/api/projects/${id}`, data).then(r => r.data),
    delete: (id: string) => http.delete(`/api/projects/${id}`).then(r => r.data),
    updateRepeat: (id: string, repeat: RepeatConfig) =>
      http.patch<Project>(`/api/projects/${id}`, { repeat }).then(r => r.data),
  },

  tracks: {
    list: (projectId: string) =>
      http.get<Track[]>(`/api/projects/${projectId}/tracks`).then(r => r.data),
    upload: (projectId: string, file: File, title: string, lyrics: string) => {
      const form = new FormData()
      form.append('file', file)
      form.append('title', title)
      form.append('lyrics', lyrics)
      return http.post<Track>(`/api/projects/${projectId}/tracks`, form).then(r => r.data)
    },
    update: (projectId: string, trackId: string, data: Partial<Track>) =>
      http.patch<Track>(`/api/projects/${projectId}/tracks/${trackId}`, data).then(r => r.data),
    delete: (projectId: string, trackId: string) =>
      http.delete(`/api/projects/${projectId}/tracks/${trackId}`).then(r => r.data),
    reorder: (projectId: string, order: string[]) =>
      http.post(`/api/projects/${projectId}/tracks/${order[0]}/reorder`, { order }).then(r => r.data),
    transcribe: (projectId: string, trackId: string, language?: string) =>
      http.post(`/api/projects/${projectId}/tracks/${trackId}/transcribe`, null, {
        params: language ? { language } : {},
      }).then(r => r.data),
    buildSubtitle: (projectId: string, trackId: string) =>
      http.post<{ track_id: string; srt_path: string; project_srt_path: string; entries_count: number }>(
        `/api/projects/${projectId}/tracks/${trackId}/subtitle/build`
      ).then(r => r.data),
    subtitleUrl: (projectId: string, trackId: string) =>
      `${BASE}/api/projects/${projectId}/tracks/${trackId}/subtitle`,
  },

  images: {
    get: (projectId: string) =>
      http.get<ProjectImages>(`/api/projects/${projectId}/images`).then(r => r.data),
    upload: (projectId: string, file: File, category: string) => {
      const form = new FormData()
      form.append('file', file)
      form.append('category', category)
      return http.post(`/api/projects/${projectId}/images`, form).then(r => r.data)
    },
    assign: (projectId: string, path: string, category: string) =>
      http.put(`/api/projects/${projectId}/images/assign`, { path, category }).then(r => r.data),
    remove: (projectId: string, path: string, category: string) =>
      http.delete(`/api/projects/${projectId}/images`, { data: { path, category } }).then(r => r.data),
    analyzeMood: (projectId: string, file: File) => {
      const form = new FormData()
      form.append('file', file)
      return http.post<ImageMood>(`/api/projects/${projectId}/images/analyze`, form).then(r => r.data)
    },
    generate: (projectId: string, mood: ImageMood | null, target: string, count: number, saveAs?: string, customPrompt?: string) =>
      http.post(`/api/projects/${projectId}/images/generate`, { mood, target, count, save_as: saveAs, custom_prompt: customPrompt || undefined }).then(r => r.data),
    storageUrl: (storedPath: string) => {
      const rel = storedPath.replace(/\\/g, '/').split('storage/')[1]
      return `${BASE}/storage/${rel}`
    },
  },

  metadata: {
    get: (projectId: string) =>
      http.get<ProjectMetadata>(`/api/projects/${projectId}/metadata`).then(r => r.data),
    generate: (projectId: string, regenerate = false, instruction = '') =>
      http.post<ProjectMetadata>(`/api/projects/${projectId}/metadata/generate`, { regenerate, instruction }).then(r => r.data),
    readThumbnail: (projectId: string) =>
      http.get<{ text: string }>(`/api/projects/${projectId}/metadata/read-thumbnail`).then(r => r.data),
    update: (projectId: string, data: Partial<ProjectMetadata>) =>
      http.put<ProjectMetadata>(`/api/projects/${projectId}/metadata`, data).then(r => r.data),
  },

  layers: {
    get: (projectId: string) =>
      http.get<ProjectLayers>(`/api/projects/${projectId}/layers`).then(r => r.data),
    update: (projectId: string, layers: ProjectLayers) =>
      http.put(`/api/projects/${projectId}/layers`, { layers }).then(r => r.data),
    addText: (projectId: string, layer: Record<string, unknown>) =>
      http.post(`/api/projects/${projectId}/layers/text`, layer).then(r => r.data),
    updateText: (projectId: string, layerId: string, data: Partial<import('../types').TextLayerConfig>) =>
      http.put(`/api/projects/${projectId}/layers/text/${layerId}`, data).then(r => r.data),
    deleteText: (projectId: string, layerId: string) =>
      http.delete(`/api/projects/${projectId}/layers/text/${layerId}`).then(r => r.data),
    listFonts: (projectId: string) =>
      http.get<{ name: string; path: string }[]>(`/api/projects/${projectId}/layers/fonts`).then(r => r.data),
    uploadImage: (projectId: string, file: File) => {
      const form = new FormData()
      form.append('file', file)
      return http.post<import('../types').ImageLayerConfig>(`/api/projects/${projectId}/layers/image`, form).then(r => r.data)
    },
    deleteImage: (projectId: string, layerId: string) =>
      http.delete(`/api/projects/${projectId}/layers/image/${layerId}`).then(r => r.data),
    autoGenerateSrt: (projectId: string) =>
      http.post<{ status: string; message: string }>(`/api/projects/${projectId}/layers/srt/auto`).then(r => r.data),
    uploadSrt: (projectId: string, file: File) => {
      const form = new FormData()
      form.append('file', file)
      return http.post<{ filename: string; entries_count: number }>(`/api/projects/${projectId}/layers/srt`, form).then(r => r.data)
    },
  },

  build: {
    status: (projectId: string) =>
      http.get<BuildStatus>(`/api/projects/${projectId}/build/status`).then(r => r.data),
    trigger: (projectId: string, mode: 'mp4' | 'capcut' = 'capcut') =>
      http.post(`/api/projects/${projectId}/build`, { mode }).then(r => r.data),
    reset: (projectId: string) =>
      http.post(`/api/projects/${projectId}/build/reset`).then(r => r.data),
    downloadUrl: (projectId: string) => `${BASE}/api/projects/${projectId}/build/download`,
    downloadCapcutUrl: (projectId: string) => `${BASE}/api/projects/${projectId}/build/download-capcut`,
    openFolder: (projectId: string) =>
      http.post(`/api/projects/${projectId}/build/open-folder`).then(r => r.data),
  },

  youtube: {
    openStudio: (projectId: string) =>
      http.post<{ status: string }>(`/api/youtube/open-studio/${projectId}`).then(r => r.data),
    fillMetadata: (projectId: string) =>
      http.post<{ status: string }>(`/api/youtube/fill-metadata/${projectId}`).then(r => r.data),
    fillProgress: (projectId: string) =>
      http.get<{ step: string; current: number; total: number; done: boolean; error: string; updated_at?: string }>(
        `/api/youtube/fill-progress/${projectId}`
      ).then(r => r.data),
  },

  suno: {
    status: () =>
      http.get<{ session_exists: boolean; login_status: string }>('/api/suno/status').then(r => r.data),
    openLogin: () =>
      http.post<{ status: string; message: string }>('/api/suno/login/open').then(r => r.data),
    confirmLogin: () =>
      http.post<{ status: string; message: string }>('/api/suno/login/confirm').then(r => r.data),
    cancelLogin: () =>
      http.post('/api/suno/login/cancel').then(r => r.data),
    deleteSession: () =>
      http.delete('/api/suno/session').then(r => r.data),
    record: {
      start: () =>
        http.post<{ status: string; message: string }>('/api/suno/record/start').then(r => r.data),
      status: () =>
        http.get<{ status: string; message: string; action_count: number; auto_done: boolean }>('/api/suno/record/status').then(r => r.data),
      stop: () =>
        http.post<{ status: string; action_count: number }>('/api/suno/record/stop').then(r => r.data),
      cancel: () =>
        http.delete('/api/suno/record').then(r => r.data),
    },
    getRecipe: () =>
      http.get<{ exists: boolean; action_count?: number; recorded_at?: string }>('/api/suno/recipe').then(r => r.data),
    deleteRecipe: () =>
      http.delete('/api/suno/recipe').then(r => r.data),
  },

  qa: {
    verify: (projectId: string) => http.get<{
      status: string; total_designed: number; total_files: number; expected_files: number;
      tracks: { index: number; title: string; v1_exists: boolean; v2_exists: boolean; status: string }[];
      missing: { index: number; title: string; missing: string[] }[];
    }>(`/api/projects/${projectId}/qa`).then(r => r.data),
    fix: (projectId: string) => http.post<{ fixed: number; message: string }>(`/api/projects/${projectId}/qa/fix`).then(r => r.data),
  },

  waveform: {
    create: (projectId: string, config: Record<string, unknown>) =>
      http.post<{ status: string }>('/api/waveform/create', { project_id: projectId, ...config }).then(r => r.data),
    status: (projectId: string) =>
      http.get<{ ready: boolean; progress: number; file_size?: string; error?: string }>(`/api/waveform/status/${projectId}`).then(r => r.data),
  },

  agents: {
    skills: () => http.get<{ composer: { id: string; name: string; summary: string }[]; lyricist: { id: string; name: string; summary: string }[] }>('/api/agents/skills').then(r => r.data),
    skillContent: (agent: string, skillId: string) => http.get<{ id: string; agent: string; content: string }>(`/api/agents/skills/${agent}/${skillId}`).then(r => r.data),
  },

  channels: {
    list: () => http.get<Channel[]>('/api/channels').then(r => r.data),
    get: (id: string) => http.get<Channel>(`/api/channels/${id}`).then(r => r.data),
    create: (data: Omit<Channel, 'benchmark_history' | 'created_at' | 'updated_at'>) =>
      http.post<Channel>('/api/channels', data).then(r => r.data),
    update: (id: string, data: Partial<Channel>) =>
      http.put<Channel>(`/api/channels/${id}`, data).then(r => r.data),
    initDefaults: () =>
      http.post<{ created: number; channels: string[] }>('/api/channels/init-defaults').then(r => r.data),
    listTemplates: (channelId: string) =>
      http.get<LayerTemplate[]>(`/api/channels/${channelId}/templates`).then(r => r.data),
    saveTemplate: (channelId: string, template: LayerTemplate) =>
      http.post(`/api/channels/${channelId}/templates`, template).then(r => r.data),
    deleteTemplate: (channelId: string, name: string) =>
      http.delete(`/api/channels/${channelId}/templates/${encodeURIComponent(name)}`).then(r => r.data),
  },

  trackDesign: {
    design: (channelId: string, projectId: string, opts?: { benchmarkUrl?: string; count?: number; keywords?: string; mood?: string; lyricsHint?: string; extra?: string }) =>
      http.post<{ tracks: DesignedTrack[]; concept: ProjectConcept; benchmark_used: string; total: number }>(
        '/api/tracks/design',
        {
          channel_id: channelId,
          project_id: projectId,
          benchmark_url: opts?.benchmarkUrl ?? null,
          count: opts?.count ?? 20,
          keywords: opts?.keywords ?? '',
          mood: opts?.mood ?? '',
          lyrics_hint: opts?.lyricsHint ?? '',
          extra: opts?.extra ?? '',
        }
      ).then(r => r.data),
    list: (projectId: string) =>
      http.get<{ tracks: DesignedTrack[]; concept: ProjectConcept }>(`/api/tracks/${projectId}`).then(r => r.data),
    update: (projectId: string, idx: number, data: Partial<DesignedTrack>) =>
      http.put<DesignedTrack>(`/api/tracks/${projectId}/${idx}`, data).then(r => r.data),
    delete: (projectId: string, idx: number) =>
      http.delete(`/api/tracks/${projectId}/${idx}`).then(r => r.data),
    regenerate: (projectId: string, idx: number, channelId: string) =>
      http.post<DesignedTrack>(`/api/tracks/${projectId}/regenerate/${idx}`, { channel_id: channelId }).then(r => r.data),
    batchCreate: (projectId: string, channelId: string, mode: 'cookie' | 'browser' = 'cookie') =>
      http.post<{ status: string; mode?: string; total_batches: number }>(
        `/api/tracks/${projectId}/batch-create`,
        { channel_id: channelId, mode },
      ).then(r => r.data),
    batchStop: (projectId: string) =>
      http.post<{ reset: boolean }>(`/api/tracks/${projectId}/batch-reset`).then(r => r.data),
    sunoStatus: (projectId: string) =>
      http.get<{
        status: string; phase?: string; round?: number;
        total_designed?: number; total_batches: number;
        completed_batches?: number; completed?: number;
        tracks_collected: number; current_song?: string;
        errors?: string[];
        qa_report?: { status: string; total_files: number; expected_files: number; complete_count: number };
      }>(`/api/tracks/${projectId}/suno-status`).then(r => r.data),
    sunoTracks: (projectId: string) =>
      http.get<{ tracks: SunoTrack[]; total: number }>(`/api/tracks/${projectId}/suno-tracks`).then(r => r.data),
    reorderSunoTracks: (projectId: string, order: number[]) =>
      http.put<{ tracks: SunoTrack[] }>(`/api/tracks/${projectId}/suno-tracks/reorder`, { order }).then(r => r.data),
    deleteSunoTrack: (projectId: string, trackIndex: number) =>
      http.delete(`/api/tracks/${projectId}/suno-tracks/${trackIndex}`).then(r => r.data),
    retryDownload: (projectId: string, sunoId?: string) =>
      http.post<{ tracks: SunoTrack[]; retried: number }>(`/api/tracks/${projectId}/suno-tracks/retry-download`, sunoId ? { suno_id: sunoId } : { retry_all: true }).then(r => r.data),
    scanSiblings: (projectId: string) =>
      http.post<{ status: string; known_clips: number }>(`/api/tracks/${projectId}/suno-tracks/scan-siblings`).then(r => r.data),
    registerSunoSet: (projectId: string, slot: number) =>
      http.post<{ set: string; slot: number; tracks_count: number; skipped_duplicates: number }>(`/api/tracks/${projectId}/register-suno-set`, { slot }).then(r => r.data),
    getActiveSet: (projectId: string) =>
      http.get<{ active_set: string | null; tracks_count: number }>(`/api/tracks/${projectId}/active-set`).then(r => r.data),
  },
}
