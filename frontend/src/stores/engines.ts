import { acceptHMRUpdate, defineStore } from 'pinia'
import * as api from '../api/engines'
import type { CpuSampler, CpuSamplerSettings, EngineId, EnginesState } from '../api/engines'
import { useFeaturesStore } from './features'

const TICK_MS = 1500
/** While the Models page is open and nothing downloads: a download or a deletion made elsewhere still shows up. */
const IDLE_TICK_MS = 10000

/**
 * The Models page's state: the engines' parts and settings, and the CPU sample server. A part download runs in the
 * backend; this store follows it on any page and refreshes the installed parts (features) when one lands.
 */
export const useEnginesStore = defineStore('engines', {
  state: () => ({
    state: null as EnginesState | null,
    cpu: null as CpuSampler | null,
    loadError: null as string | null,
    _timer: null as ReturnType<typeof setTimeout> | null,
    /** Pages that want the slow refresh (the Models page while it is open). */
    _watchers: 0,
  }),
  actions: {
    async load() {
      try {
        const [state, cpu] = await Promise.all([api.getEngines(), api.getCpuSampler()])
        this._apply(state)
        this.cpu = cpu
        this.loadError = null
      } catch (e) {
        this.loadError = e instanceof Error ? e.message : String(e)
      }
      this._follow()
    },
    async download(part: string) {
      this._apply(await api.downloadPart(part))
      this._follow()
    },
    async cancel(part: string) {
      this._apply(await api.cancelPart(part))
    },
    async remove(part: string) {
      this._apply(await api.deletePart(part))
      void useFeaturesStore().refresh()
    },
    async saveSettings(engine: EngineId, values: Record<string, string>) {
      this._apply(await api.saveEngineSettings(engine, values))
    },
    async saveCpu(settings: CpuSamplerSettings) {
      this.cpu = await api.saveCpuSampler(settings)
    },
    async refreshCpu() {
      this.cpu = await api.getCpuSampler()
      return this.cpu
    },
    async startCpu() {
      this.cpu = await api.startCpuSampler()
      return this.cpu
    },
    async stopCpu() {
      this.cpu = await api.stopCpuSampler()
    },
    _apply(next: EnginesState) {
      const before = new Set(this.state ? Object.values(this.state.engines).flatMap((e) => (e.parts ?? []).filter((p) => p.installed).map((p) => p.id)) : [])
      const prev = this.state
      this.state = next
      const landed = Object.values(next.engines).some((e) => (e.parts ?? []).some((p) => p.installed && !before.has(p.id)))
      if (prev && landed) void useFeaturesStore().refresh()
    },
    /** The Models page is open: keep the state fresh even when nothing downloads. */
    watch() {
      this._watchers++
      this._follow()
    },
    unwatch() {
      this._watchers = Math.max(0, this._watchers - 1)
    },
    _follow() {
      if (this._timer) return
      const downloading = !!this.state?.downloading
      if (!downloading && this._watchers === 0) return
      this._timer = setTimeout(async () => {
        this._timer = null
        await this.load()
      }, downloading ? TICK_MS : IDLE_TICK_MS)
    },
  },
})

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(useEnginesStore, import.meta.hot))
}
