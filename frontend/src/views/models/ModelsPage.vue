<script setup lang="ts">
// Models and settings: per engine the weights it can download and the settings it starts with, plus the CPU sample
// server for the editor's Samples panel. Engine settings apply on the engine's next start; the page says when a
// running engine still has the old ones and offers a restart.
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import type { CpuSamplerSettings, EngineId, EngineInfo, EnginePart } from '../../api/engines'
import { MODEL_LABELS } from '../../composables/useModelSwitch'
import { useEnginesStore } from '../../stores/engines'
import { useOrchestratorStore } from '../../stores/orchestrator'
import NotInstalled from '../../components/shared/NotInstalled.vue'
import Sa3Weights from '../../components/shared/Sa3Weights.vue'
import CheckIcon from '../../components/shared/icons/CheckIcon.vue'
import DownloadIcon from '../../components/shared/icons/DownloadIcon.vue'

const { t, locale } = useI18n()
const store = useEnginesStore()
const orchestrator = useOrchestratorStore()
const route = useRoute()

const engines = computed(() => store.state?.engines ?? null)
const actionError = ref<string | null>(null)

function gb(bytes: number): string {
  return new Intl.NumberFormat(locale.value, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(bytes / 1e9)
}
function percent(p: EnginePart): number {
  const d = p.download
  return d && d.total > 0 ? Math.min(100, Math.round((d.done / d.total) * 100)) : 0
}

async function run(action: () => Promise<unknown>) {
  actionError.value = null
  try {
    await action()
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e)
  }
}

// ---- parts ----
const PART_GROUPS: Record<'ace_step' | 'yue2', EnginePart['kind'][]> = { ace_step: ['main', 'dit', 'lm'], yue2: ['common', 'precision'] }
/** vue-i18n reads a dot as a path separator: "lm-0.6B" is kept as "lm-0_6B" in the texts. */
const partKey = (id: string) => id.replace(/\./g, '_')
function partsOf(info: EngineInfo, kind: EnginePart['kind']): EnginePart[] {
  return (info.parts ?? []).filter((p) => p.kind === kind)
}

// ---- engine settings ----
function pendingRestart(id: EngineId): boolean {
  const e = engines.value?.[id]
  if (!e?.started || e.status !== 'running' || !e.settings) return false
  return Object.entries(e.settings).some(([k, v]) => e.started?.[k] !== v)
}
async function setSetting(id: EngineId, key: string, value: string) {
  await run(() => store.saveSettings(id, { [key]: value }))
}
async function restart(id: EngineId) {
  if (id === 'demucs') return
  await run(async () => {
    await orchestrator.stopActive()
    await orchestrator.switchModel(id)
    await store.load()
  })
}
const optionLabel = (key: string, value: string) => (key === 'preload' && value === '' ? t('models.sa3.preloadNone') : value)

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

const STATUS_DOT: Record<string, string> = { running: 'bg-status-done', starting: 'bg-status-queued', stopping: 'bg-status-queued', error: 'bg-status-failed', stopped: 'bg-gray-500' }

onMounted(async () => {
  await store.load()
  // /models#stable-audio and the like: the section asked for
  const id = route.hash.slice(1)
  if (id) document.getElementById(id)?.scrollIntoView({ block: 'start' })
})
</script>

<template>
  <div class="mx-auto max-w-5xl space-y-6">
    <header>
      <h1 class="text-2xl font-semibold text-text">{{ t('models.title') }}</h1>
      <p class="mt-1 max-w-3xl text-sm leading-relaxed text-text-dim">{{ t('models.lead') }}</p>
    </header>

    <p v-if="store.loadError" class="rounded-lg bg-status-failed/10 p-3 text-sm text-status-failed">{{ store.loadError }}</p>
    <p v-if="actionError" class="rounded-lg bg-status-failed/10 p-3 text-sm text-status-failed" role="alert">{{ actionError }}</p>
    <p v-if="!engines && !store.loadError" class="text-sm text-text-dim">{{ t('models.loading') }}</p>

    <template v-if="engines">
      <!-- ACE-Step and YuE2: parts fetched by the engines' own tools -->
      <section
        v-for="id in (['ace_step', 'yue2'] as const)"
        :id="id === 'ace_step' ? 'ace-step' : 'yue2'"
        :key="id"
        class="scroll-mt-20 rounded-xl border border-border bg-panel p-4"
      >
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h2 class="text-lg font-semibold text-text">{{ MODEL_LABELS[id] }}</h2>
          <span v-if="engines[id].status" class="inline-flex items-center gap-1.5 text-xs text-text-dim">
            <span class="h-2 w-2 rounded-full" :class="STATUS_DOT[engines[id].status ?? 'stopped']"></span>{{ t(`models.status.${engines[id].status}`) }}
          </span>
        </div>
        <NotInstalled v-if="!engines[id].ready" :feature="id === 'ace_step' ? 'aceBase' : 'yue2'" compact class="mt-3" />
        <template v-else>
          <div v-for="kind in PART_GROUPS[id]" :key="kind" class="mt-3">
            <h3 class="text-xs font-semibold tracking-wide text-text-dim uppercase">{{ t(`models.groups.${kind}`) }}</h3>
            <ul class="mt-1 divide-y divide-border">
              <li v-for="p in partsOf(engines[id], kind)" :key="p.id" class="flex flex-wrap items-center gap-x-4 gap-y-2 py-2.5">
                <div class="min-w-[14rem] flex-1">
                  <p class="text-sm font-medium text-text">
                    {{ t(`models.parts.${partKey(p.id)}.name`) }}
                    <span class="ml-1 text-xs font-normal text-text-dim">{{ t('models.size', { gb: gb(p.bytes) }) }}</span>
                  </p>
                  <p class="mt-0.5 text-xs leading-relaxed text-text-dim">{{ t(`models.parts.${partKey(p.id)}.text`) }}</p>
                </div>
                <span v-if="p.installed" class="inline-flex items-center gap-1.5 text-xs text-status-done"><CheckIcon class="h-3.5 w-3.5" />{{ t('models.installed') }}</span>
                <div v-else-if="p.download?.status === 'running'" class="flex min-w-[16rem] flex-1 items-center gap-3">
                  <div class="flex-1">
                    <div class="h-1.5 overflow-hidden rounded-full bg-panel-2">
                      <div class="accent-gradient h-full rounded-full transition-[width] duration-700" :style="{ width: `${percent(p)}%` }"></div>
                    </div>
                    <p class="mt-1 text-[11px] tabular-nums text-text-dim">{{ t('models.progress', { done: gb(p.download.done), total: gb(p.download.total), pct: percent(p) }) }}</p>
                  </div>
                  <button type="button" class="rounded-lg border border-border px-2.5 py-1 text-xs text-text-dim hover:text-text" @click="run(() => store.cancel(p.id))">{{ t('models.cancel') }}</button>
                </div>
                <div v-else class="flex max-w-sm flex-col items-end gap-1">
                  <button
                    type="button"
                    class="accent-gradient inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
                    :disabled="!!store.state?.downloading"
                    :title="store.state?.downloading ? t('models.oneAtATime') : undefined"
                    @click="run(() => store.download(p.id))"
                  >
                    <DownloadIcon class="h-3.5 w-3.5" />{{ t(p.download?.status === 'failed' || p.download?.status === 'cancelled' ? 'models.resume' : 'models.download') }}
                  </button>
                  <p v-if="p.download?.status === 'failed'" class="text-right text-[11px] text-status-failed">{{ p.download.error }}</p>
                  <p v-else-if="p.required" class="text-right text-[11px] text-text-dim">{{ t('models.required') }}</p>
                </div>
              </li>
            </ul>
          </div>

          <!-- settings -->
          <div class="mt-4 rounded-lg border border-border bg-panel-2 p-3">
            <h3 class="text-sm font-semibold text-text">{{ t('models.settings') }}</h3>
            <p v-if="id === 'yue2'" class="mt-1 text-xs leading-relaxed text-text-dim">{{ t('models.yue2.noSettings') }}</p>
            <div v-else class="mt-2 grid gap-3 sm:grid-cols-2">
              <label v-for="key in ['dit_model', 'lm_model']" :key="key" class="flex flex-col gap-1 text-xs">
                <span class="font-medium text-text">{{ t(`models.ace.${key}`) }}</span>
                <select
                  class="rounded-lg border border-border bg-panel px-2 py-1.5 text-sm text-text"
                  :value="engines.ace_step.settings?.[key]"
                  @change="setSetting('ace_step', key, ($event.target as HTMLSelectElement).value)"
                >
                  <option v-for="v in engines.ace_step.choices?.[key] ?? []" :key="v" :value="v">{{ v }}</option>
                </select>
                <span class="leading-relaxed text-text-dim">{{ t(`models.ace.${key}Hint`) }}</span>
              </label>
            </div>
            <p v-if="pendingRestart(id)" class="mt-3 flex flex-wrap items-center gap-3 text-xs text-status-queued">
              {{ t('models.restartNote', { engine: MODEL_LABELS[id] }) }}
              <button type="button" class="rounded-lg border border-border px-2.5 py-1 text-text hover:border-accent1" @click="restart(id)">{{ t('models.restart') }}</button>
            </p>
          </div>
        </template>
      </section>

      <!-- Stable Audio 3: the gated weights, the checkpoint warmed up at start, and samples on the CPU -->
      <section id="stable-audio" class="scroll-mt-20 rounded-xl border border-border bg-panel p-4">
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h2 class="text-lg font-semibold text-text">{{ MODEL_LABELS.stable_audio }}</h2>
          <span v-if="engines.stable_audio.status" class="inline-flex items-center gap-1.5 text-xs text-text-dim">
            <span class="h-2 w-2 rounded-full" :class="STATUS_DOT[engines.stable_audio.status ?? 'stopped']"></span>{{ t(`models.status.${engines.stable_audio.status}`) }}
          </span>
        </div>
        <NotInstalled v-if="!engines.stable_audio.ready" feature="stableAudio" compact class="mt-3" />
        <template v-else>
          <Sa3Weights class="mt-3 border-0 bg-transparent p-0" />

          <div class="mt-4 rounded-lg border border-border bg-panel-2 p-3">
            <h3 class="text-sm font-semibold text-text">{{ t('models.settings') }}</h3>
            <label class="mt-2 flex max-w-sm flex-col gap-1 text-xs">
              <span class="font-medium text-text">{{ t('models.sa3.preload') }}</span>
              <select
                class="rounded-lg border border-border bg-panel px-2 py-1.5 text-sm text-text"
                :value="engines.stable_audio.settings?.preload"
                @change="setSetting('stable_audio', 'preload', ($event.target as HTMLSelectElement).value)"
              >
                <option v-for="v in engines.stable_audio.choices?.preload ?? []" :key="v" :value="v">{{ optionLabel('preload', v) }}</option>
              </select>
              <span class="leading-relaxed text-text-dim">{{ t('models.sa3.preloadHint') }}</span>
            </label>
            <p v-if="pendingRestart('stable_audio')" class="mt-3 flex flex-wrap items-center gap-3 text-xs text-status-queued">
              {{ t('models.restartNote', { engine: MODEL_LABELS.stable_audio }) }}
              <button type="button" class="rounded-lg border border-border px-2.5 py-1 text-text hover:border-accent1" @click="restart('stable_audio')">{{ t('models.restart') }}</button>
            </p>
          </div>

          <!-- samples on the CPU -->
          <div id="samples-cpu" class="mt-4 scroll-mt-20 rounded-lg border border-border bg-panel-2 p-3">
            <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h3 class="text-sm font-semibold text-text">{{ t('models.cpu.title') }}</h3>
              <span v-if="store.cpu" class="inline-flex items-center gap-1.5 text-xs text-text-dim">
                <span class="h-2 w-2 rounded-full" :class="STATUS_DOT[store.cpu.status]"></span>{{ t(`models.status.${store.cpu.status}`) }}
              </span>
            </div>
            <p class="mt-1 max-w-3xl text-xs leading-relaxed text-text-dim">{{ t('models.cpu.lead') }}</p>
            <p v-if="store.cpu && !store.cpu.available" class="mt-2 text-xs text-status-queued">{{ t('models.cpu.notAvailable') }}</p>
            <form v-else-if="cpuForm" class="mt-3 space-y-3" @change="saveCpu" @submit.prevent>
              <label class="flex items-center gap-2 text-sm text-text">
                <input v-model="cpuForm.enabled" type="checkbox" class="h-4 w-4 accent-accent1" />
                {{ t('models.cpu.enabled') }}
              </label>
              <fieldset class="grid gap-3 sm:grid-cols-2" :disabled="!cpuForm.enabled">
                <div class="flex flex-col gap-1 text-xs sm:col-span-2">
                  <span class="font-medium text-text">{{ t('models.cpu.route') }}</span>
                  <label class="flex items-start gap-2 text-text"><input v-model="cpuForm.route" type="radio" value="auto" class="mt-0.5 accent-accent1" />{{ t('models.cpu.routeAuto') }}</label>
                  <label class="flex items-start gap-2 text-text"><input v-model="cpuForm.route" type="radio" value="cpu" class="mt-0.5 accent-accent1" />{{ t('models.cpu.routeCpu') }}</label>
                </div>
                <label class="flex flex-col gap-1 text-xs">
                  <span class="font-medium text-text">{{ t('models.cpu.threads') }}</span>
                  <select v-model.number="cpuForm.threads" class="rounded-lg border border-border bg-panel px-2 py-1.5 text-sm text-text">
                    <option v-for="n in threadChoices" :key="n" :value="n">{{ n === 0 ? t('models.cpu.threadsAuto') : n }}</option>
                  </select>
                  <span class="leading-relaxed text-text-dim">{{ t('models.cpu.threadsHint', { n: store.cpu?.cpu_count ?? '?' }) }}</span>
                </label>
                <label class="flex flex-col gap-1 text-xs">
                  <span class="font-medium text-text">{{ t('models.cpu.model') }}</span>
                  <select v-model="cpuForm.model" class="rounded-lg border border-border bg-panel px-2 py-1.5 text-sm text-text">
                    <option v-for="m in store.cpu?.models ?? []" :key="m" :value="m">{{ m }}</option>
                  </select>
                </label>
                <label class="flex flex-col gap-1 text-xs">
                  <span class="font-medium text-text">{{ t('models.cpu.idle') }}</span>
                  <select v-model.number="cpuForm.idle_minutes" class="rounded-lg border border-border bg-panel px-2 py-1.5 text-sm text-text">
                    <option v-for="m in [5, 15, 30, 60, 0]" :key="m" :value="m">{{ m === 0 ? t('models.cpu.idleNever') : t('models.cpu.idleMin', { n: m }) }}</option>
                  </select>
                  <span class="leading-relaxed text-text-dim">{{ t('models.cpu.idleHint') }}</span>
                </label>
              </fieldset>
              <p class="text-xs leading-relaxed text-text-dim">{{ t('models.cpu.speed') }}</p>
              <p v-if="store.cpu?.restart_pending" class="text-xs text-status-queued">{{ t('models.cpu.restartPending') }}</p>
              <p v-if="store.cpu?.error" class="whitespace-pre-line rounded-lg bg-status-failed/10 p-2 text-xs text-status-failed">{{ store.cpu.error }}</p>
              <div v-if="cpuForm.enabled" class="flex flex-wrap gap-2">
                <button v-if="store.cpu?.status !== 'running'" type="button" class="rounded-lg border border-border px-3 py-1.5 text-xs text-text hover:border-accent1 disabled:opacity-50" :disabled="store.cpu?.status === 'starting'" @click="run(() => store.startCpu())">{{ t('models.cpu.start') }}</button>
                <button v-else type="button" class="rounded-lg border border-border px-3 py-1.5 text-xs text-text-dim hover:text-text" @click="run(() => store.stopCpu())">{{ t('models.cpu.stop') }}</button>
              </div>
            </form>
          </div>
        </template>
      </section>

      <!-- Demucs: which separation model -->
      <section id="demucs" class="scroll-mt-20 rounded-xl border border-border bg-panel p-4">
        <h2 class="text-lg font-semibold text-text">{{ t('models.demucs.title') }}</h2>
        <NotInstalled v-if="!engines.demucs.ready" feature="demucs" compact class="mt-3" />
        <div v-else class="mt-3 rounded-lg border border-border bg-panel-2 p-3">
          <h3 class="text-sm font-semibold text-text">{{ t('models.settings') }}</h3>
          <div class="mt-2 flex flex-col gap-2 text-sm" role="radiogroup" :aria-label="t('models.demucs.model')">
            <label v-for="m in engines.demucs.choices?.model ?? []" :key="m" class="flex items-start gap-2 text-text">
              <input type="radio" name="demucs-model" :value="m" :checked="engines.demucs.settings?.model === m" class="mt-1 accent-accent1" @change="setSetting('demucs', 'model', m)" />
              <span><b class="font-medium">{{ m }}</b><span class="block text-xs leading-relaxed text-text-dim">{{ t(`models.demucs.models.${m}`) }}</span></span>
            </label>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
