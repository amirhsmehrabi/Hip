<script setup lang="ts">
// Models and settings: a list of engines on the left (with their state and what their models take on disk) and the
// chosen one on the right: its settings first, then the weights it can download or delete. Engine settings apply
// on the engine's next start; the page says when a running engine still has the old ones and offers a restart.
// The chosen engine is the URL hash (#ace-step, #yue2, #stable-audio, #samples-cpu, #demucs), so the panels can
// link straight to a section.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import type { CpuSamplerSettings, EngineId, EnginePart } from '../../api/engines'
import type { Sa3WeightModel } from '../../api/sa3Weights'
import { MODEL_LABELS } from '../../composables/useModelSwitch'
import { useEnginesStore } from '../../stores/engines'
import { useOrchestratorStore } from '../../stores/orchestrator'
import { useSa3WeightsStore } from '../../stores/sa3Weights'
import { gb } from '../../utils/bytes'
import HfTokenField from '../../components/shared/HfTokenField.vue'
import NotInstalled from '../../components/shared/NotInstalled.vue'
import PartRow from '../../components/shared/PartRow.vue'

const { t, locale } = useI18n()
const store = useEnginesStore()
const sa3 = useSa3WeightsStore()
const orchestrator = useOrchestratorStore()
const route = useRoute()
const router = useRouter()

type SectionId = 'ace-step' | 'yue2' | 'stable-audio' | 'samples-cpu' | 'demucs'
const SECTIONS: { id: SectionId; engine: EngineId; sub?: boolean }[] = [
  { id: 'ace-step', engine: 'ace_step' },
  { id: 'yue2', engine: 'yue2' },
  { id: 'stable-audio', engine: 'stable_audio' },
  { id: 'samples-cpu', engine: 'stable_audio', sub: true },
  { id: 'demucs', engine: 'demucs' },
]
const isSection = (s: string): s is SectionId => SECTIONS.some((x) => x.id === s)
const current = ref<SectionId>(isSection(route.hash.slice(1)) ? (route.hash.slice(1) as SectionId) : 'ace-step')
watch(() => route.hash, (h) => { if (isSection(h.slice(1))) current.value = h.slice(1) as SectionId })
function select(id: SectionId) {
  current.value = id
  void router.replace({ hash: `#${id}` })
}
const section = computed(() => SECTIONS.find((s) => s.id === current.value)!)
const engineId = computed(() => section.value.engine)
const engines = computed(() => store.state?.engines ?? null)
const engine = computed(() => engines.value?.[engineId.value] ?? null)
const sectionTitle = computed(() => current.value === 'samples-cpu' ? t('models.cpu.title') : current.value === 'demucs' ? t('models.demucs.title') : MODEL_LABELS[engineId.value as 'ace_step' | 'yue2' | 'stable_audio'])

const totalBytes = computed(() => Object.values(engines.value ?? {}).reduce((a, e) => a + (e.on_disk ?? 0), 0))
const actionError = ref<string | null>(null)
async function run(action: () => Promise<unknown>) {
  actionError.value = null
  try {
    await action()
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e)
  }
}

// ---- the engine's process ----
const status = computed(() => engine.value?.status ?? null)
const STATUS_DOT: Record<string, string> = { running: 'bg-status-done', starting: 'bg-status-queued', stopping: 'bg-status-queued', error: 'bg-status-failed', stopped: 'bg-gray-500' }
function dotFor(id: EngineId): string {
  if (id === 'demucs') return ''
  return STATUS_DOT[engines.value?.[id]?.status ?? 'stopped']
}
async function startEngine() {
  if (engineId.value === 'demucs') return
  await run(async () => {
    await orchestrator.switchModel(engineId.value as 'ace_step' | 'yue2' | 'stable_audio')
    await store.load()
  })
}
async function stopEngine() {
  await run(async () => {
    await orchestrator.stopActive()
    await store.load()
  })
}

// ---- settings ----
const pendingRestart = computed(() => {
  const e = engine.value
  if (!e?.started || e.status !== 'running' || !e.settings) return false
  return Object.entries(e.settings).some(([k, v]) => e.started?.[k] !== v)
})
async function setSetting(key: string, value: string) {
  await run(() => store.saveSettings(engineId.value, { [key]: value }))
}
async function restart() {
  await run(async () => {
    await orchestrator.stopActive()
    await orchestrator.switchModel(engineId.value as 'ace_step' | 'yue2' | 'stable_audio')
    await store.load()
  })
}

// ---- weights ----
/** vue-i18n reads a dot as a path separator: "lm-0.6B" is kept as "lm-0_6B" in the texts. */
const partKey = (id: string) => id.replace(/\./g, '_')
/** Rarely wanted parts stay folded until one is downloaded or downloading. */
const SECONDARY = new Set(['acestep-v15-xl-turbo', 'acestep-v15-xl-sft', 'acestep-v15-xl-base', 'acestep-5Hz-lm-0.6B', 'acestep-5Hz-lm-4B'])
const showAll = ref(false)
const parts = computed(() => engine.value?.parts ?? [])
const isSecondary = (p: EnginePart) => SECONDARY.has(p.id) && !p.installed && !p.download
const visibleParts = computed(() => showAll.value ? parts.value : parts.value.filter((p) => !isSecondary(p)))
const hiddenCount = computed(() => parts.value.filter(isSecondary).length)
const blockedTitle = computed(() => store.state?.downloading ? t('models.oneAtATime') : undefined)

// Stable Audio 3: its own store (the gated weights and the token)
const sa3Models = computed(() => sa3.weights?.models ?? [])
const sa3Visible = computed(() => showAll.value ? sa3Models.value : sa3Models.value.filter((m) => !m.base || m.installed || m.download))
const sa3Hidden = computed(() => sa3Models.value.filter((m) => m.base && !m.installed && !m.download).length)
const pageUrl = (m: Sa3WeightModel) => `https://huggingface.co/${m.repo}`
const optionLabel = (key: string, value: string) => (key === 'preload' && value === '' ? t('models.sa3.preloadNone') : value)
watch(current, () => { showAll.value = false })

// ---- samples on the CPU ----
const cpuForm = ref<CpuSamplerSettings | null>(null)
watch(() => store.cpu?.settings, (s) => { if (s) cpuForm.value = { ...s } }, { immediate: true })
const threadChoices = computed(() => {
  const n = store.cpu?.cpu_count || 8
  return [0, ...[2, 4, 6, 8, 12, 16, 24, 32, 48, 64].filter((x) => x <= n)]
})
async function saveCpu() {
  if (cpuForm.value) await run(() => store.saveCpu(cpuForm.value as CpuSamplerSettings))
}

onMounted(() => {
  store.watch()
  void store.load()
  void sa3.load()
})
onBeforeUnmount(() => store.unwatch())
</script>

<template>
  <div class="mx-auto max-w-5xl">
    <header class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <h1 class="text-2xl font-semibold text-text">{{ t('models.title') }}</h1>
      <p v-if="engines" class="text-sm text-text-dim">{{ t('models.total', { gb: gb(totalBytes, locale) }) }}</p>
    </header>
    <p class="mt-1 max-w-3xl text-sm leading-relaxed text-text-dim">{{ t('models.lead') }}</p>

    <p v-if="store.loadError" class="mt-4 rounded-lg bg-status-failed/10 p-3 text-sm text-status-failed">{{ store.loadError }}</p>
    <p v-else-if="!engines" class="mt-4 text-sm text-text-dim">{{ t('models.loading') }}</p>

    <div v-if="engines" class="mt-5 grid gap-6 lg:grid-cols-[13rem_minmax(0,1fr)]">
      <!-- the engines: a column on a wide screen, a row of chips on a narrow one -->
      <nav :aria-label="t('models.nav')" class="-mx-4 flex gap-1 overflow-x-auto px-4 lg:sticky lg:top-20 lg:mx-0 lg:flex-col lg:self-start lg:overflow-visible lg:px-0">
        <button
          v-for="s in SECTIONS"
          :key="s.id"
          type="button"
          class="flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors lg:w-full"
          :class="[current === s.id ? 'bg-panel text-text ring-1 ring-border' : 'text-text-dim hover:bg-panel/60 hover:text-text', s.sub && 'lg:pl-8']"
          :aria-current="current === s.id ? 'page' : undefined"
          @click="select(s.id)"
        >
          <span v-if="!s.sub && dotFor(s.engine)" class="h-2 w-2 shrink-0 rounded-full" :class="dotFor(s.engine)"></span>
          <span class="min-w-0 flex-1 truncate">{{ s.id === 'samples-cpu' ? t('models.cpu.navTitle') : s.id === 'demucs' ? t('models.demucs.navTitle') : MODEL_LABELS[s.engine as 'ace_step' | 'yue2' | 'stable_audio'] }}</span>
          <span v-if="!s.sub && engines[s.engine].on_disk != null" class="hidden text-xs tabular-nums text-text-dim lg:inline">{{ t('models.size', { gb: gb(engines[s.engine].on_disk ?? 0, locale) }) }}</span>
        </button>
      </nav>

      <section :id="current" class="min-w-0">
        <!-- header: the name, the state, start / stop -->
        <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h2 class="text-lg font-semibold text-text">{{ sectionTitle }}</h2>
          <span v-if="status && !section.sub" class="inline-flex items-center gap-1.5 text-xs text-text-dim">
            <span class="h-2 w-2 rounded-full" :class="STATUS_DOT[status]"></span>{{ t(`models.status.${status}`) }}
          </span>
          <template v-if="status && !section.sub && engine?.ready">
            <button v-if="status === 'running'" type="button" class="ml-auto rounded-lg border border-border px-3 py-1.5 text-xs text-text-dim hover:text-text" :disabled="orchestrator.switching" @click="stopEngine">{{ t('models.stop') }}</button>
            <button v-else-if="status === 'stopped' || status === 'error'" type="button" class="ml-auto rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text hover:border-accent1 disabled:opacity-50" :disabled="orchestrator.switching" @click="startEngine">{{ t('models.start') }}</button>
          </template>
        </div>
        <p v-if="status === 'error' && engine && orchestrator.statuses[engineId]?.error" class="mt-2 whitespace-pre-line rounded-lg bg-status-failed/10 p-3 text-xs text-status-failed">{{ orchestrator.statuses[engineId]?.error }}</p>
        <p v-if="actionError" class="mt-3 rounded-lg bg-status-failed/10 p-3 text-xs text-status-failed" role="alert">{{ actionError }}</p>

        <NotInstalled v-if="engine && !engine.ready" :feature="engineId === 'ace_step' ? 'aceBase' : engineId === 'yue2' ? 'yue2' : engineId === 'demucs' ? 'demucs' : 'stableAudio'" compact class="mt-4" />

        <!-- ================= ACE-Step / YuE2 ================= -->
        <template v-else-if="engine && (engineId === 'ace_step' || engineId === 'yue2') && !section.sub">
          <div class="mt-4 rounded-xl border border-border bg-panel p-4">
            <h3 class="text-sm font-semibold text-text">{{ t('models.settings') }}</h3>
            <p v-if="engineId === 'yue2'" class="mt-1 text-xs leading-relaxed text-text-dim">{{ t('models.yue2.noSettings') }}</p>
            <div v-else class="mt-3 grid gap-4 sm:grid-cols-2">
              <label v-for="key in ['dit_model', 'lm_model']" :key="key" class="flex flex-col gap-1 text-xs">
                <span class="font-medium text-text">{{ t(`models.ace.${key}`) }}</span>
                <select class="rounded-lg border border-border bg-panel-2 px-2 py-1.5 text-sm text-text" :value="engine.settings?.[key]" @change="setSetting(key, ($event.target as HTMLSelectElement).value)">
                  <option v-for="v in engine.choices?.[key] ?? []" :key="v" :value="v">{{ v }}</option>
                </select>
                <span class="leading-relaxed text-text-dim">{{ t(`models.ace.${key}Hint`) }}</span>
              </label>
            </div>
            <p v-if="pendingRestart" class="mt-3 flex flex-wrap items-center gap-3 text-xs text-status-queued">
              {{ t('models.restartNote', { engine: sectionTitle }) }}
              <button type="button" class="rounded-lg border border-border px-2.5 py-1 text-text hover:border-accent1" @click="restart">{{ t('models.restart') }}</button>
            </p>
          </div>

          <div class="mt-4 rounded-xl border border-border bg-panel p-4">
            <div class="flex items-baseline justify-between gap-3">
              <h3 class="text-sm font-semibold text-text">{{ t('models.weights') }}</h3>
              <span class="text-xs text-text-dim">{{ t('models.onDisk', { gb: gb(engine.on_disk ?? 0, locale) }) }}</span>
            </div>
            <ul class="mt-1 divide-y divide-border">
              <PartRow
                v-for="p in visibleParts"
                :key="p.id"
                :name="t(`models.parts.${partKey(p.id)}.name`)"
                :hint="t(`models.parts.${partKey(p.id)}.text`)"
                :bytes="p.bytes"
                :on-disk="p.on_disk"
                :installed="p.installed"
                :download="p.download"
                :required="p.required"
                :deletable="p.deletable"
                :blocked="!!store.state?.downloading"
                :blocked-title="blockedTitle"
                @download="run(() => store.download(p.id))"
                @cancel="run(() => store.cancel(p.id))"
                @delete="run(() => store.remove(p.id))"
              >
                <template v-if="p.required" #note>{{ t('models.required') }}</template>
              </PartRow>
            </ul>
            <button v-if="hiddenCount" type="button" class="mt-2 text-xs text-text-dim hover:text-text" :aria-expanded="showAll" @click="showAll = !showAll">
              {{ t(showAll ? 'models.showLess' : 'models.showMore', { n: hiddenCount }) }}
            </button>
          </div>
        </template>

        <!-- ================= Stable Audio 3 ================= -->
        <template v-else-if="engine && engineId === 'stable_audio' && !section.sub">
          <div class="mt-4 rounded-xl border border-border bg-panel p-4">
            <h3 class="text-sm font-semibold text-text">{{ t('models.settings') }}</h3>
            <div class="mt-3 grid gap-4 sm:grid-cols-2">
              <label class="flex flex-col gap-1 text-xs">
                <span class="font-medium text-text">{{ t('models.sa3.preload') }}</span>
                <select class="rounded-lg border border-border bg-panel-2 px-2 py-1.5 text-sm text-text" :value="engine.settings?.preload" @change="setSetting('preload', ($event.target as HTMLSelectElement).value)">
                  <option v-for="v in engine.choices?.preload ?? []" :key="v" :value="v">{{ optionLabel('preload', v) }}</option>
                </select>
                <span class="leading-relaxed text-text-dim">{{ t('models.sa3.preloadHint') }}</span>
              </label>
              <HfTokenField class="rounded-lg border border-border bg-panel-2 p-3" />
            </div>
            <p v-if="pendingRestart" class="mt-3 flex flex-wrap items-center gap-3 text-xs text-status-queued">
              {{ t('models.restartNote', { engine: sectionTitle }) }}
              <button type="button" class="rounded-lg border border-border px-2.5 py-1 text-text hover:border-accent1" @click="restart">{{ t('models.restart') }}</button>
            </p>
          </div>

          <div class="mt-4 rounded-xl border border-border bg-panel p-4">
            <div class="flex items-baseline justify-between gap-3">
              <h3 class="text-sm font-semibold text-text">{{ t('models.weights') }}</h3>
              <span class="text-xs text-text-dim">{{ t('models.onDisk', { gb: gb(engine.on_disk ?? 0, locale) }) }}</span>
            </div>
            <p class="mt-1 text-xs leading-relaxed text-text-dim">{{ t('sa3Weights.lead') }}</p>
            <p v-if="sa3.loadError" class="mt-2 text-xs text-status-failed">{{ sa3.loadError }}</p>
            <ul class="mt-1 divide-y divide-border">
              <PartRow
                v-for="m in sa3Visible"
                :key="m.id"
                :name="m.id"
                :hint="t(`sa3Weights.models.${m.id}`)"
                :bytes="m.bytes"
                :on-disk="m.on_disk"
                :installed="m.installed"
                :download="m.download"
                deletable
                :blocked="!!sa3.running || !sa3.weights?.env"
                :blocked-title="sa3.running ? t('sa3Weights.oneAtATime', { model: sa3.running.id }) : undefined"
                @download="run(() => sa3.download(m.id))"
                @cancel="run(() => sa3.cancel(m.id))"
                @delete="run(() => sa3.remove(m.id))"
              >
                <template #error>
                  <template v-if="m.download?.code === 'access'">
                    {{ t('sa3Weights.errors.access') }}
                    <a :href="pageUrl(m)" target="_blank" rel="noopener" class="underline">{{ t('sa3Weights.modelPage') }}</a>
                  </template>
                  <template v-else-if="m.download?.code === 'login'">{{ t(sa3.weights?.token ? 'sa3Weights.errors.badToken' : 'sa3Weights.errors.login') }}</template>
                  <template v-else-if="m.download?.code === 'network'">{{ t('sa3Weights.errors.network') }}</template>
                  <template v-else>{{ m.download?.error || t('sa3Weights.errors.unknown') }}</template>
                </template>
                <template v-if="m.gated" #note>
                  {{ t('sa3Weights.licence') }}
                  <a :href="pageUrl(m)" target="_blank" rel="noopener" class="text-accent1 underline">{{ t('sa3Weights.modelPage') }}</a>
                </template>
              </PartRow>
            </ul>
            <button v-if="sa3Hidden" type="button" class="mt-2 text-xs text-text-dim hover:text-text" :aria-expanded="showAll" @click="showAll = !showAll">
              {{ t(showAll ? 'models.showLess' : 'models.showMoreBase', { n: sa3Hidden }) }}
            </button>
          </div>
        </template>

        <!-- ================= samples on the CPU ================= -->
        <template v-else-if="engine && section.sub">
          <p class="mt-2 max-w-3xl text-sm leading-relaxed text-text-dim">{{ t('models.cpu.lead') }}</p>
          <div class="mt-4 rounded-xl border border-border bg-panel p-4">
            <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h3 class="text-sm font-semibold text-text">{{ t('models.settings') }}</h3>
              <span v-if="store.cpu" class="inline-flex items-center gap-1.5 text-xs text-text-dim">
                <span class="h-2 w-2 rounded-full" :class="STATUS_DOT[store.cpu.status]"></span>{{ t(`models.status.${store.cpu.status}`) }}
              </span>
              <template v-if="store.cpu && cpuForm?.enabled">
                <button v-if="store.cpu.status !== 'running'" type="button" class="ml-auto rounded-lg border border-border px-3 py-1.5 text-xs text-text hover:border-accent1 disabled:opacity-50" :disabled="store.cpu.status === 'starting'" @click="run(() => store.startCpu())">{{ t('models.cpu.start') }}</button>
                <button v-else type="button" class="ml-auto rounded-lg border border-border px-3 py-1.5 text-xs text-text-dim hover:text-text" @click="run(() => store.stopCpu())">{{ t('models.cpu.stop') }}</button>
              </template>
            </div>
            <p v-if="store.cpu && !store.cpu.available" class="mt-2 text-xs text-status-queued">{{ t('models.cpu.notAvailable') }}</p>
            <form v-else-if="cpuForm" class="mt-3 space-y-4" @change="saveCpu" @submit.prevent>
              <label class="flex items-center gap-2 text-sm text-text">
                <input v-model="cpuForm.enabled" type="checkbox" class="h-4 w-4 accent-accent1" />
                {{ t('models.cpu.enabled') }}
              </label>
              <fieldset class="grid gap-4 sm:grid-cols-2" :disabled="!cpuForm.enabled">
                <div class="flex flex-col gap-1.5 text-xs sm:col-span-2">
                  <span class="font-medium text-text">{{ t('models.cpu.route') }}</span>
                  <label class="flex items-start gap-2 text-text"><input v-model="cpuForm.route" type="radio" value="auto" class="mt-0.5 accent-accent1" />{{ t('models.cpu.routeAuto') }}</label>
                  <label class="flex items-start gap-2 text-text"><input v-model="cpuForm.route" type="radio" value="cpu" class="mt-0.5 accent-accent1" />{{ t('models.cpu.routeCpu') }}</label>
                </div>
                <label class="flex flex-col gap-1 text-xs">
                  <span class="font-medium text-text">{{ t('models.cpu.threads') }}</span>
                  <select v-model.number="cpuForm.threads" class="rounded-lg border border-border bg-panel-2 px-2 py-1.5 text-sm text-text">
                    <option v-for="n in threadChoices" :key="n" :value="n">{{ n === 0 ? t('models.cpu.threadsAuto') : n }}</option>
                  </select>
                  <span class="leading-relaxed text-text-dim">{{ t('models.cpu.threadsHint', { n: store.cpu?.cpu_count ?? '?' }) }}</span>
                </label>
                <label class="flex flex-col gap-1 text-xs">
                  <span class="font-medium text-text">{{ t('models.cpu.model') }}</span>
                  <select v-model="cpuForm.model" class="rounded-lg border border-border bg-panel-2 px-2 py-1.5 text-sm text-text">
                    <option v-for="m in store.cpu?.models ?? []" :key="m" :value="m">{{ m }}</option>
                  </select>
                </label>
                <label class="flex flex-col gap-1 text-xs">
                  <span class="font-medium text-text">{{ t('models.cpu.idle') }}</span>
                  <select v-model.number="cpuForm.idle_minutes" class="rounded-lg border border-border bg-panel-2 px-2 py-1.5 text-sm text-text">
                    <option v-for="m in [5, 15, 30, 60, 0]" :key="m" :value="m">{{ m === 0 ? t('models.cpu.idleNever') : t('models.cpu.idleMin', { n: m }) }}</option>
                  </select>
                  <span class="leading-relaxed text-text-dim">{{ t('models.cpu.idleHint') }}</span>
                </label>
              </fieldset>
              <p class="text-xs leading-relaxed text-text-dim">{{ t('models.cpu.speed') }}</p>
              <p v-if="store.cpu?.restart_pending" class="text-xs text-status-queued">{{ t('models.cpu.restartPending') }}</p>
              <p v-if="store.cpu?.error" class="whitespace-pre-line rounded-lg bg-status-failed/10 p-2 text-xs text-status-failed">{{ store.cpu.error }}</p>
            </form>
          </div>
        </template>

        <!-- ================= Demucs ================= -->
        <template v-else-if="engine && engineId === 'demucs'">
          <div class="mt-4 rounded-xl border border-border bg-panel p-4">
            <div class="flex items-baseline justify-between gap-3">
              <h3 class="text-sm font-semibold text-text">{{ t('models.demucs.model') }}</h3>
              <span class="text-xs text-text-dim">{{ t('models.onDisk', { gb: gb(engine.on_disk ?? 0, locale) }) }}</span>
            </div>
            <div class="mt-3 flex flex-col gap-2 text-sm" role="radiogroup" :aria-label="t('models.demucs.model')">
              <label v-for="m in engine.choices?.model ?? []" :key="m" class="flex items-start gap-2 text-text">
                <input type="radio" name="demucs-model" :value="m" :checked="engine.settings?.model === m" class="mt-1 accent-accent1" @change="setSetting('model', m)" />
                <span><b class="font-medium">{{ m }}</b><span class="block text-xs leading-relaxed text-text-dim">{{ t(`models.demucs.models.${m}`) }}</span></span>
              </label>
            </div>
          </div>
        </template>
      </section>
    </div>
  </div>
</template>
