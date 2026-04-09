import axios from 'axios'
import type { Project, Track, ProjectImages, ProjectMetadata, ProjectLayers, BuildStatus, RepeatConfig, ImageMood, Channel, DesignedTrack, ProjectConcept, SunoTrack, LayerTemplate } from '../types'

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

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
    generate: (projectId: string, regenerate = false) =>
      http.post<ProjectMetadata>(`/api/projects/${projectId}/metadata/generate`, { regenerate }).then(r => r.data),
    update: (projectId: string, data: Partial<ProjectMetadata>) =>
      http.put<ProjectMetadata>(`/api/projects/${projectId}/metadata`, data).then(r => r.data),
  },

  layers: {
    get: (projectId: string) =>
      http.get<ProjectLayers>(`/api/projects/${projectId}/layers`).then(r => r.data),
    update: (projectId: string, layers: ProjectLayers) =>
      http.put(`/api/projects/${projectId}/layers`, { layers }).then(r => r.data),
    addText: (projectId: string, layer: Omit<import('../types').TextLayerConfig, 'id'>) =>
      http.post(`/api/projects/${projectId}/layers/text`, layer).then(r => r.data),
    updateText: (projectId: string, layerId: string, data: Partial<import('../types').TextLayerConfig>) =>
      http.put(`/api/projects/${projectId}/layers/text/${layerId}`, data).then(r => r.data),
    deleteText: (projectId: string, layerId: string) =>
      http.delete(`/api/projects/${projectId}/layers/text/${layerId}`).then(r => r.data),
  },

  build: {
    status: (projectId: string) =>
      http.get<BuildStatus>(`/api/projects/${projectId}/build/status`).then(r => r.data),
    trigger: (projectId: string) =>
      http.post(`/api/projects/${projectId}/build`).then(r => r.data),
    downloadUrl: (projectId: string) => `${BASE}/api/projects/${projectId}/build/download`,
    downloadCapcutUrl: (projectId: string) => `${BASE}/api/projects/${projectId}/build/download-capcut`,
  },

  youtube: {
    status: () => http.get<{ authorized: boolean }>('/api/youtube/status').then(r => r.data),
    getAuthUrl: () => http.get<{ auth_url: string }>('/api/youtube/auth').then(r => r.data),
    revoke: () => http.post('/api/youtube/revoke').then(r => r.data),
    upload: (projectId: string, privacy_status: string) =>
      http.post(`/api/youtube/upload/${projectId}`, { privacy_status }).then(r => r.data),
    uploadStatus: (projectId: string) =>
      http.get(`/api/youtube/upload/${projectId}/status`).then(r => r.data),
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
    design: (channelId: string, projectId: string, benchmarkUrl?: string, count = 20) =>
      http.post<{ tracks: DesignedTrack[]; concept: ProjectConcept; benchmark_used: string; total: number }>(
        '/api/tracks/design',
        { channel_id: channelId, project_id: projectId, benchmark_url: benchmarkUrl ?? null, count }
      ).then(r => r.data),
    list: (projectId: string) =>
      http.get<{ tracks: DesignedTrack[]; concept: ProjectConcept }>(`/api/tracks/${projectId}`).then(r => r.data),
    update: (projectId: string, idx: number, data: Partial<DesignedTrack>) =>
      http.put<DesignedTrack>(`/api/tracks/${projectId}/${idx}`, data).then(r => r.data),
    delete: (projectId: string, idx: number) =>
      http.delete(`/api/tracks/${projectId}/${idx}`).then(r => r.data),
    regenerate: (projectId: string, idx: number, channelId: string) =>
      http.post<DesignedTrack>(`/api/tracks/${projectId}/regenerate/${idx}`, { channel_id: channelId }).then(r => r.data),
    batchCreate: (projectId: string, channelId: string) =>
      http.post<{ status: string; total_batches: number }>(`/api/tracks/${projectId}/batch-create`, { channel_id: channelId }).then(r => r.data),
    batchStop: (projectId: string) =>
      http.post<{ reset: boolean }>(`/api/tracks/${projectId}/batch-reset`).then(r => r.data),
    sunoStatus: (projectId: string) =>
      http.get<{ status: string; completed: number; total_batches: number; tracks_collected: number }>(`/api/tracks/${projectId}/suno-status`).then(r => r.data),
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
