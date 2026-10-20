// Stable Audio 3 weights fetched from the app (backend/app/sa3_weights.py): the backend runs sa3-server's own
// downloader in the background, so the engine does not have to be running.
import { apiFetch, apiJson } from './http'
import type { Sa3ModelId } from './stableAudio'

export type Sa3DownloadStatus = 'running' | 'done' | 'failed' | 'cancelled'
/** login: no or a bad Hugging Face token; access: the licence is not accepted on the model page. */
export type Sa3DownloadError = 'login' | 'access' | 'network' | 'unknown'

export interface Sa3WeightModel {
  id: Sa3ModelId
  /** Approximate download size. */
  bytes: number
  /** The licence has to be accepted on Hugging Face first (the -base checkpoints are open). */
  gated: boolean
  base: boolean
  repo: string
  installed: boolean
  /** What its cache folder takes on disk now. */
  on_disk: number
  /** The last download from the app since the backend started, if any. */
  download: { status: Sa3DownloadStatus; done: number; total: number; error: string | null; code: Sa3DownloadError | null } | null
}

export interface Sa3Weights {
  /** The sa3-server environment is installed (without it nothing can be downloaded). */
  env: boolean
  /** A Hugging Face token is saved (or HF_TOKEN is set). */
  token: boolean
  models: Sa3WeightModel[]
}

export interface Sa3TokenResult {
  ok: boolean
  user: string | null
  code: Sa3DownloadError | null
  error: string | null
}

export function getWeights(): Promise<Sa3Weights> {
  return apiFetch<Sa3Weights>('/api/sa3-weights')
}

export function startDownload(model: Sa3ModelId): Promise<Sa3Weights> {
  return apiFetch<Sa3Weights>(`/api/sa3-weights/${model}/download`, { method: 'POST' })
}

export function cancelDownload(model: Sa3ModelId): Promise<Sa3Weights> {
  return apiFetch<Sa3Weights>(`/api/sa3-weights/${model}/cancel`, { method: 'POST' })
}

/** Removes the checkpoint from the Hugging Face cache; refused while Stable Audio 3 runs. */
export function deleteModel(model: Sa3ModelId): Promise<Sa3Weights> {
  return apiFetch<Sa3Weights>(`/api/sa3-weights/${model}`, { method: 'DELETE' })
}

export function saveToken(token: string): Promise<Sa3TokenResult> {
  return apiJson<Sa3TokenResult>('/api/sa3-weights/token', { token })
}
