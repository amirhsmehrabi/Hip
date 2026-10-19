import { acceptHMRUpdate, defineStore } from 'pinia'
import * as api from '../api/stableAudio'
import type { Sa3Model, Sa3ModelId } from '../api/stableAudio'
import * as tracksApi from '../api/tracks'
import type { JobStatus } from '../types'
import { i18n } from '../i18n'

const t = i18n.global.t

const POLL_MS = 1500
const MODELS_MS = 5000

export type Sa3Kind = 'music' | 'sfx'

/** One generated variant: a card in the feed. A batch of N makes N jobs sharing one server task. */
export interface Sa3Job {
  id: string
  status: JobStatus
  createdAt: number
  /** The name shown on the card and stored as the track title; the user can rename it. */
  title: string
  prompt: string
  kind: Sa3Kind
  model: Sa3ModelId
  seed: number | null
  durationSec: number | null
  wallSec: number | null
  progress: number
  error?: string
  audioUrl?: string
  savedFilename?: string | null
  saveError?: string | null
  dbId?: number | null
  finalized: boolean
  params: Record<string, unknown>
  /** Server task this variant belongs to, and its index in that task's batch. */
  taskId?: string
  index?: number
}

/** What to do with a reference track: remake it in a new style, redo a range, or carry it on. */
export type Sa3RefMode = 'cover' | 'repaint' | 'continue'

export interface Sa3Reference {
  file: Blob
  name: string
  durationSec: number
  /** The library track it came from, if any. */
  trackId: number | null
  mode: Sa3RefMode
  /** cover: 0 = loose, 1 = close to the original. */
  closeness: number
  /** cover: the result's length in seconds, or null for the source's own. */
  customSec: number | null
  /** repaint: the ranges to redo, seconds into the reference. */
  ranges: { start: number; end: number }[]
  /** continue: how many seconds to add after the end. */
  extendSec: number
}

export interface Sa3GenerateParams {
  kind: Sa3Kind
  model: Sa3ModelId
  prompt: string
  negativePrompt: string
  duration: number
  steps: number
  cfgScale: number
  seed: number
  count: number
  reference?: Sa3Reference | null
  /** One text per variant (as many as `count`); `prompt` then only names the run. */
  prompts?: string[] | null
  /** What the user typed, before the service tags were added. */
  caption?: string
  autoTags?: boolean
}

export const useStableAudioStore = defineStore('stableAudio', {
  state: () => ({
    jobs: [] as Sa3Job[],
    models: [] as Sa3Model[],
    modelsError: false,
    historyLoaded: false,
    pendingParamsInsert: null as Partial<Sa3GenerateParams> | null,
    _pollTimer: null as ReturnType<typeof setTimeout> | null,
    _modelsTimer: null as ReturnType<typeof setTimeout> | null,
    _started: {} as Record<string, number>,
  }),
  getters: {
    /** Checkpoints that can run here, in the server's order. */
    availableModels: (s) => s.models.filter((m) => m.available),
  },
  actions: {
    requestInsertParams(params: Partial<Sa3GenerateParams>) {
      this.pendingParamsInsert = { ...params }
    },
    clearPendingParamsInsert() {
      this.pendingParamsInsert = null
    },
    async loadHistory() {
      try {
        const tracks = await tracksApi.listTracks('stable_audio')
        const saved: Sa3Job[] = tracks.map((trk) => ({
          id: `saved_${trk.id}`,
          status: 'done',
          createdAt: new Date(trk.created_at).getTime() || Date.now(),
          title: trk.title,
          prompt: (trk.params.prompt as string) || trk.title,
          kind: ((trk.params.kind as Sa3Kind) || 'music'),
          model: ((trk.params.model as Sa3ModelId) || 'medium'),
          seed: trk.seed,
          durationSec: trk.duration_ms ? trk.duration_ms / 1000 : null,
          wallSec: trk.wall_ms ? trk.wall_ms / 1000 : null,
          progress: 100,
          audioUrl: trk.audio_url,
          savedFilename: trk.filename,
          dbId: trk.id,
          finalized: true,
          params: trk.params,
        }))
        const inFlight = new Set(this.jobs.filter((j) => !j.finalized).map((j) => j.id))
        this.jobs = [...this.jobs.filter((j) => inFlight.has(j.id)), ...saved].sort((a, b) => b.createdAt - a.createdAt)
      } finally {
        this.historyLoaded = true
      }
    },
    async refreshModels() {
      try {
        this.models = await api.models()
        this.modelsError = false
      } catch {
        this.modelsError = true
      }
    },
    startBackgroundTasks() {
      if (this._modelsTimer) return
      const tick = async () => {
        await this.refreshModels()
        this._modelsTimer = setTimeout(tick, MODELS_MS)
      }
      void tick()
    },
    stopBackgroundTasks() {
      if (this._modelsTimer) clearTimeout(this._modelsTimer)
      this._modelsTimer = null
    },
    async generate(p: Sa3GenerateParams) {
      const created = Date.now()
      const ref = p.reference ?? null
      // The reference decides the task and the length: a cover keeps the source length, a repaint too,
      // a continuation is the source plus the extension (the mask covers the part past the source).
      const prompts = p.prompts && p.prompts.length === p.count ? p.prompts : null
      const req: api.Sa3JobRequest = {
        task: 'text', model: p.model, prompt: prompts ?? p.prompt, negative_prompt: p.negativePrompt || undefined,
        duration: p.duration, steps: p.steps, cfg_scale: p.cfgScale, seed: p.seed, batch_size: p.count,
      }
      if (ref?.mode === 'cover') {
        req.task = 'a2a'
        req.init_noise_level = Math.min(1, Math.max(0, 1 - ref.closeness))
        req.duration = ref.customSec ?? ref.durationSec
      } else if (ref?.mode === 'repaint') {
        req.task = 'inpaint'
        req.mask_start = ref.ranges.map((r) => r.start)
        req.mask_end = ref.ranges.map((r) => r.end)
        req.duration = ref.durationSec
      } else if (ref?.mode === 'continue') {
        req.task = 'inpaint'
        req.mask_start = [ref.durationSec]
        req.mask_end = [ref.durationSec + ref.extendSec]
        req.duration = ref.durationSec + ref.extendSec
      }
      const params = {
        task: req.task, kind: p.kind, model: p.model, prompt: p.prompt, prompts: prompts ?? undefined, caption: p.caption,
        auto_tags: p.autoTags, negative_prompt: p.negativePrompt,
        duration: req.duration, steps: p.steps, cfg_scale: p.cfgScale, seed: p.seed, batch_size: p.count,
        ...(ref ? {
          ref_mode: ref.mode, ref_name: ref.name, ref_track_id: ref.trackId, ref_duration: ref.durationSec,
          closeness: ref.mode === 'cover' ? ref.closeness : undefined,
          custom_sec: ref.mode === 'cover' ? ref.customSec : undefined,
          mask: ref.mode === 'repaint' ? ref.ranges.map((r) => [r.start, r.end]) : undefined,
          extend_sec: ref.mode === 'continue' ? ref.extendSec : undefined,
        } : {}),
      }
      const ids: string[] = []
      for (let i = 0; i < p.count; i++) {
        const id = `g_${created}_${i}`
        ids.push(id)
        const text = prompts ? prompts[i] : p.prompt
        this.jobs.unshift({
          id, status: 'queued', createdAt: created, title: text, prompt: text, kind: p.kind, model: p.model,
          seed: p.seed >= 0 ? p.seed : null, durationSec: null, wallSec: null, progress: 0, finalized: false, params, index: i,
        })
      }
      try {
        const res = await api.submitJob(req, ref?.file ?? null)
        this._started[res.job_id] = performance.now()
        for (const id of ids) {
          const job = this.jobs.find((j) => j.id === id)
          if (job) job.taskId = res.job_id
        }
        this._ensurePolling()
      } catch (err) {
        for (const id of ids) {
          const job = this.jobs.find((j) => j.id === id)
          if (!job) continue
          job.status = 'failed'
          job.error = err instanceof Error ? err.message : String(err)
          job.finalized = true
        }
      }
    },
    _ensurePolling() {
      if (this._pollTimer) return
      const tick = async () => {
        this._pollTimer = null
        await this._poll()
        if (this.jobs.some((j) => !j.finalized && j.taskId)) this._pollTimer = setTimeout(tick, POLL_MS)
      }
      this._pollTimer = setTimeout(tick, POLL_MS)
    },
    async _poll() {
      const waiting = this.jobs.filter((j) => !j.finalized && j.taskId)
      const taskIds = [...new Set(waiting.map((j) => j.taskId as string))]
      if (!taskIds.length) return
      let states: api.Sa3JobState[]
      try {
        states = await api.queryJobs(taskIds)
      } catch {
        return
      }
      for (const st of states) {
        const mine = waiting.filter((j) => j.taskId === st.job_id)
        if (st.status === 'queued' || st.status === 'running') {
          for (const job of mine) {
            job.status = st.status
            job.progress = st.progress
          }
        } else if (st.status === 'done') {
          const wallMs = this._started[st.job_id] ? performance.now() - this._started[st.job_id] : null
          delete this._started[st.job_id]
          for (const job of mine) {
            const file = st.files[job.index ?? 0]
            if (!file) {
              job.status = 'failed'
              job.error = t('storeErrors.serverNoAudio')
              job.finalized = true
              continue
            }
            job.seed = st.seed
            job.durationSec = st.durations[job.index ?? 0] ?? null
            job.wallSec = wallMs != null ? wallMs / 1000 : null
            job.progress = 100
            job.status = 'done'
            job.finalized = true
            void this._persist(job, api.audioUrl(file))
          }
        } else {
          delete this._started[st.job_id]
          for (const job of mine) {
            job.status = st.status
            if (st.status === 'failed') job.error = st.error || t('storeErrors.serverNoAudio')
            job.finalized = true
          }
        }
      }
    },
    /** Copies the server's file into the library; the card plays the library copy from then on. */
    async _persist(job: Sa3Job, url: string) {
      try {
        const resp = await fetch(url)
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const blob = await resp.blob()
        const saved = await tracksApi.saveTrack(
          {
            model: 'stable_audio',
            title: job.title,
            lyrics: '',
            seed: job.seed ?? undefined,
            duration_ms: job.durationSec != null ? Math.round(job.durationSec * 1000) : undefined,
            wall_ms: job.wallSec != null ? Math.round(job.wallSec * 1000) : undefined,
            params: { ...job.params, prompt: job.prompt, seed: job.seed, index: job.index },
          },
          blob,
          'wav',
        )
        job.audioUrl = saved.audio_url
        job.savedFilename = saved.filename
        job.dbId = saved.id
        job.saveError = null
      } catch (err) {
        // Keep the server copy playable for this session; it is lost when the engine restarts.
        job.audioUrl = url
        job.savedFilename = null
        job.dbId = null
        job.saveError = err instanceof Error ? err.message : String(err)
      }
    },
    async cancel(jobId: string) {
      const job = this.jobs.find((j) => j.id === jobId)
      if (!job?.taskId) return
      try {
        await api.cancelJob(job.taskId)
      } catch {
        // the poll reports the final state either way
      }
    },
    async deleteJob(job: Sa3Job) {
      if (job.dbId != null) {
        try {
          await tracksApi.deleteTrack(job.dbId)
        } catch {
          // still remove locally so the card does not get stuck
        }
      }
      this.jobs = this.jobs.filter((j) => j.id !== job.id)
    },
    async renameJob(job: Sa3Job, title: string) {
      if (job.dbId == null) return
      await tracksApi.renameTrack(job.dbId, title)
      const target = this.jobs.find((j) => j.id === job.id)
      if (target) target.title = title
    },
  },
})

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useStableAudioStore, import.meta.hot))
}
