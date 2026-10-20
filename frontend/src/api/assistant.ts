// The prompt assistant (RFC 0002, backend/app/assistant.py): a local language model that turns an idea into an
// engine's prompt. It runs next to the GPU engines and starts on the first request.
import { apiFetch, apiJson } from './http'

export type AssistantTask = 'sa3' | 'yue2-song' | 'ace-song' | 'ace-instrumental'

export interface AssistantSettings {
  model: string
  /** auto: the GPU when about 6 GB are free there, else the CPU. */
  device: 'auto' | 'cpu' | 'cuda'
  /** 0 = PyTorch's default (one per physical core). */
  threads: number
  /** Minutes without use before it stops; 0 = never. */
  idle_minutes: number
}

export interface AssistantModel {
  id: string
  bytes: number
  installed: boolean
  on_disk: number
  download: { status: 'running' | 'done' | 'failed' | 'cancelled'; done: number; total: number; error: string | null } | null
}

export interface AssistantState {
  settings: AssistantSettings
  status: 'stopped' | 'starting' | 'running' | 'error'
  error: string | null
  /** Its environment is installed. */
  ready: boolean
  models: AssistantModel[]
  downloading: string | null
  on_disk: number
  cpu_count: number
  /** Where it runs now ("auto" resolved), while it runs. */
  device: 'cpu' | 'cuda' | 'mps' | null
  loaded: boolean
  restart_pending: boolean
}

export interface AssistantResult {
  task: AssistantTask
  fields: Record<string, string | number | null>
  tokens: number
  took_ms: number
  device: string
  model: string
}

const owner = (id: string) => id.split('/').map(encodeURIComponent).join('/')

export const getAssistant = () => apiFetch<AssistantState>('/api/assistant/state')
export const saveAssistant = (s: AssistantSettings) => apiJson<AssistantState>('/api/assistant/settings', s, 'PUT')
export const startAssistant = () => apiFetch<AssistantState>('/api/assistant/start', { method: 'POST' })
export const stopAssistant = () => apiFetch<AssistantState>('/api/assistant/stop', { method: 'POST' })
export const downloadAssistantModel = (id: string) => apiFetch<AssistantState>(`/api/assistant/models/${owner(id)}/download`, { method: 'POST' })
export const cancelAssistantModel = (id: string) => apiFetch<AssistantState>(`/api/assistant/models/${owner(id)}/cancel`, { method: 'POST' })
export const deleteAssistantModel = (id: string) => apiFetch<AssistantState>(`/api/assistant/models/${owner(id)}`, { method: 'DELETE' })

/** Writes a prompt; starts the assistant first when it is not running (a few seconds more). */
export const writePrompt = (task: AssistantTask, idea: string, extra: { language?: string; kind?: string; seed?: number } = {}) =>
  apiJson<AssistantResult>('/api/assistant/v1/write', { task, idea, ...extra })
