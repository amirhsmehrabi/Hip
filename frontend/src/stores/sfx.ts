import { acceptHMRUpdate, defineStore } from 'pinia'
import * as sa3Api from '../api/stableAudio'
import type { Sa3ModelId } from '../api/stableAudio'
import * as tracksApi from '../api/tracks'
import { i18n } from '../i18n'

const t = i18n.global.t

const POLL_MS = 1500

/** oneshot = a hit or a short sound; loop = bars at the project tempo; texture = an atmosphere or a bed. */
export const SFX_KINDS = ['oneshot', 'loop', 'texture'] as const
export type SfxKind = (typeof SFX_KINDS)[number]

export interface SfxRequest {
  kind: SfxKind
  /** What the user typed. */
  caption: string
  model: Sa3ModelId
  /** Seconds asked from the model (a loop: bars at the project tempo). */
  duration: number
  bpm: number
  bars: number
  count: number
}

export interface SfxVariant {
  url: string
  trackId: number | null
  title: string
  index: number
  durationSec: number | null
  /** Placed on a lane at least once: its library file stays when the job is dismissed. */
  used: boolean
}

export type SfxStatus = 'queued' | 'running' | 'saving' | 'done' | 'failed' | 'cancelled'

export interface SfxJob {
  id: string
  taskId: string | null
  /** editor store `session` the job belongs to; results only go into that project. */
  session: number
  status: SfxStatus
  progress: number
  error: string | null
  request: SfxRequest
  createdAt: number
  variants: SfxVariant[]
}

/** The text the model gets: Freesound-style tags around the user's words. */
export function sfxPrompt(r: SfxRequest): string {
  const text = r.caption.trim()
  if (r.kind === 'loop') return `TrackType: Instrument, ${text}, ${Math.round(r.bpm)} BPM, seamless loop`
  return `TrackType: SFX. ${text}`
}

export function sfxTitle(r: SfxRequest, index: number): string {
  const short = r.caption.trim().replace(/\s+/g, ' ').slice(0, 48)
  return `${t(`sfx.kinds.${r.kind}`)} · ${short} · ${index + 1}`
}

export const useSfxStore = defineStore('sfx', {
  state: () => ({
    jobs: [] as SfxJob[],
    _pollTimer: null as ReturnType<typeof setTimeout> | null,
  }),
  actions: {
    async submit(request: SfxRequest, session: number): Promise<SfxJob> {
      this.jobs.unshift({
        id: crypto.randomUUID(),
        taskId: null,
        session,
        status: 'queued',
        progress: 0,
        error: null,
        request,
        createdAt: Date.now(),
        variants: [],
      })
      const job = this.jobs[0] // the reactive proxy, so later writes re-render
      try {
        const res = await sa3Api.submitJob({
          task: 'text', model: request.model, prompt: sfxPrompt(request), duration: request.duration,
          steps: 8, cfg_scale: 1, seed: -1, batch_size: request.count,
        })
        job.taskId = res.job_id
        this._ensurePolling()
      } catch (e) {
        job.status = 'failed'
        job.error = e instanceof Error ? e.message : String(e)
      }
      return job
    },
    _ensurePolling() {
      if (this._pollTimer) return
      const tick = async () => {
        await this._poll()
        this._pollTimer = this.jobs.some((j) => (j.status === 'queued' || j.status === 'running') && j.taskId)
          ? setTimeout(tick, POLL_MS)
          : null
      }
      this._pollTimer = setTimeout(tick, POLL_MS)
    },
    async _poll() {
      const waiting = this.jobs.filter((j) => (j.status === 'queued' || j.status === 'running') && j.taskId)
      if (waiting.length === 0) return
      let states: sa3Api.Sa3JobState[]
      try {
        states = await sa3Api.queryJobs(waiting.map((j) => j.taskId as string))
      } catch {
        return // backend or engine restarting; next tick retries
      }
      for (const st of states) {
        const job = waiting.find((j) => j.taskId === st.job_id)
        if (!job || job.status === 'cancelled') continue
        if (st.status === 'done') {
          job.status = 'saving'
          job.progress = 100
          void this._persist(job, st.files.map((f) => sa3Api.audioUrl(f)), st.durations)
        } else if (st.status === 'failed' || st.status === 'cancelled') {
          job.status = st.status
          job.error = st.error || (st.status === 'failed' ? t('storeErrors.unknownError') : null)
        } else {
          job.status = st.status
          job.progress = st.progress
        }
      }
    },
    /** Copies each result from the engine into the library (origin "editor", marked sfx), so a clip's URL survives a restart. */
    async _persist(job: SfxJob, urls: string[], durations: number[]) {
      const r = job.request
      for (const [i, url] of urls.entries()) {
        const title = sfxTitle(r, i)
        const durationSec = durations[i] ?? null
        try {
          const resp = await fetch(url)
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
          const saved = await tracksApi.saveTrack(
            {
              model: 'editor',
              title,
              lyrics: '',
              duration_ms: durationSec != null ? Math.round(durationSec * 1000) : undefined,
              params: {
                sfx: true, kind: r.kind, caption: r.caption, prompt: sfxPrompt(r), engine: 'sa3', model: r.model,
                bpm: r.bpm, bars: r.kind === 'loop' ? r.bars : undefined, duration: r.duration, index: i,
              },
            },
            await resp.blob(),
            'wav',
          )
          job.variants.push({ url: saved.audio_url, trackId: saved.id, title, index: i, durationSec, used: false })
        } catch {
          // Library save failed: still offer the (temporary) engine URL.
          job.variants.push({ url, trackId: null, title, index: i, durationSec, used: false })
        }
      }
      job.status = job.variants.length ? 'done' : 'failed'
      if (!job.variants.length) job.error = t('sfx.noResults')
    },
    async cancel(jobId: string) {
      const job = this.jobs.find((j) => j.id === jobId)
      if (!job) return
      if (job.taskId) {
        try {
          await sa3Api.cancelJob(job.taskId)
        } catch {
          // already finished or the engine is gone; the local state below still applies
        }
      }
      if (job.status === 'queued' || job.status === 'running') job.status = 'cancelled'
    },
    /** Drops the job; results never placed on a lane leave the library with it. */
    async removeJob(jobId: string) {
      const job = this.jobs.find((j) => j.id === jobId)
      this.jobs = this.jobs.filter((j) => j.id !== jobId)
      if (!job) return
      for (const v of job.variants) {
        if (v.used || v.trackId == null) continue
        try {
          await tracksApi.deleteTrack(v.trackId)
        } catch {
          // already gone
        }
      }
    },
  },
})

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useSfxStore, import.meta.hot))
}
