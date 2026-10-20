import { acceptHMRUpdate, defineStore } from 'pinia'
import * as api from '../api/sa3Weights'
import type { Sa3Weights } from '../api/sa3Weights'
import type { Sa3ModelId } from '../api/stableAudio'
import { useFeaturesStore } from './features'

const TICK_MS = 1000

/**
 * Stable Audio 3 weights downloaded from the app. The download runs in the backend; this store follows it for as long
 * as it runs, whichever page is open, and refreshes the installed parts (features) when a checkpoint arrives, so the
 * engine, the Samples panel and the arranger see it without a reload.
 */
export const useSa3WeightsStore = defineStore('sa3Weights', {
  state: () => ({
    weights: null as Sa3Weights | null,
    loadError: null as string | null,
    _timer: null as ReturnType<typeof setTimeout> | null,
  }),
  getters: {
    running: (s) => s.weights?.models.find((m) => m.download?.status === 'running') ?? null,
  },
  actions: {
    async load() {
      try {
        this._apply(await api.getWeights())
        this.loadError = null
      } catch (e) {
        this.loadError = e instanceof Error ? e.message : String(e)
      }
      this._follow()
    },
    async download(model: Sa3ModelId) {
      this._apply(await api.startDownload(model))
      this._follow()
    },
    async cancel(model: Sa3ModelId) {
      this._apply(await api.cancelDownload(model))
    },
    async saveToken(token: string): Promise<api.Sa3TokenResult> {
      const r = await api.saveToken(token)
      if (r.ok) await this.load()
      return r
    },
    _apply(next: Sa3Weights) {
      this.weights = next
      // What the backend counts as downloaded differs from what the app was told at start: a download finished
      // (here or elsewhere), or a checkpoint was fetched by hand.
      const features = useFeaturesStore()
      const known = [...features.features.stable_audio_models].sort().join()
      const now = next.models.filter((m) => m.installed).map((m) => m.id).sort().join()
      if (known !== now || features.features.stable_audio_env !== next.env) void features.refresh()
    },
    /** Polls once a second while a download runs; stops by itself when none does. */
    _follow() {
      if (this._timer || !this.running) return
      this._timer = setTimeout(async () => {
        this._timer = null
        await this.load()
      }, TICK_MS)
    },
  },
})

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useSa3WeightsStore, import.meta.hot))
}
