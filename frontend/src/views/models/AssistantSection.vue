<script setup lang="ts">
// The prompt assistant on the Models page: where it runs, its settings, its models, and a box to
// try it: an idea in, the prompt an engine would get out.
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AssistantResult, AssistantSettings, AssistantTask } from '../../api/assistant'
import { writePrompt } from '../../api/assistant'
import { useEnginesStore } from '../../stores/engines'
import { gb } from '../../utils/bytes'
import PartRow from '../../components/shared/PartRow.vue'
import SparklesIcon from '../../components/shared/icons/SparklesIcon.vue'

const { t, locale } = useI18n()
const store = useEnginesStore()
const state = computed(() => store.assistant)

const STATUS_DOT: Record<string, string> = { running: 'bg-status-done', starting: 'bg-status-queued', error: 'bg-status-failed', stopped: 'bg-text-dim/50' }
const STATUS_PILL: Record<string, string> = { running: 'bg-status-done/15 text-status-done', starting: 'bg-status-queued/15 text-status-queued', error: 'bg-status-failed/15 text-status-failed', stopped: 'bg-panel-2 text-text-dim' }

const actionError = ref<string | null>(null)
async function run(action: () => Promise<unknown>) {
  actionError.value = null
  try {
    await action()
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e)
  }
}

// ---- settings ----
const form = ref<AssistantSettings | null>(null)
watch(() => state.value?.settings, (s) => { if (s) form.value = { ...s } }, { immediate: true })
const installedModels = computed(() => state.value?.models.filter((m) => m.installed).map((m) => m.id) ?? [])
const threadChoices = computed(() => {
  const n = state.value?.cpu_count || 8
  return [0, ...[2, 4, 6, 8, 12, 16, 24, 32, 48, 64].filter((x) => x <= n)]
})
async function save() {
  if (form.value) await run(() => store.saveAssistant(form.value as AssistantSettings))
}
const shortName = (id: string) => id.split('/').pop() ?? id
const modelKey = (id: string) => shortName(id).replace(/\./g, '_')

// ---- try it ----
const TASKS: AssistantTask[] = ['sa3', 'yue2-song', 'ace-song', 'ace-instrumental']
const idea = ref('')
const task = ref<AssistantTask>('sa3')
const writing = ref(false)
const result = ref<AssistantResult | null>(null)
const tryError = ref<string | null>(null)
async function tryIt() {
  if (!idea.value.trim() || writing.value) return
  writing.value = true
  tryError.value = null
  result.value = null
  try {
    result.value = await writePrompt(task.value, idea.value.trim())
    await store.load()
  } catch (e) {
    tryError.value = e instanceof Error ? e.message : String(e)
  } finally {
    writing.value = false
  }
}
/** Fields shown in a fixed order; long texts (lyrics) as a block. */
const FIELD_ORDER = ['prompt', 'caption', 'style', 'lyrics', 'category', 'bpm', 'keyscale', 'duration', 'language']
const resultFields = computed(() => {
  const f = result.value?.fields ?? {}
  return FIELD_ORDER.filter((k) => f[k] != null && f[k] !== '').map((k) => ({ key: k, value: String(f[k]), long: k === 'lyrics' }))
})
</script>

<template>
  <section class="min-w-0 overflow-hidden rounded-xl border border-border bg-panel">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border bg-panel-2/60 px-4 py-3">
      <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent1/15 text-accent1">
        <SparklesIcon class="h-[18px] w-[18px]" />
      </span>
      <div class="min-w-0 flex-1">
        <h2 class="truncate text-base font-semibold text-text">{{ t('models.assistant.title') }}</h2>
        <p v-if="state" class="text-xs text-text-dim">{{ t('models.onDisk', { gb: gb(state.on_disk, locale) }) }}</p>
      </div>
      <template v-if="state">
        <span class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs" :class="STATUS_PILL[state.status]">
          <span class="h-1.5 w-1.5 rounded-full" :class="STATUS_DOT[state.status]"></span>
          {{ t(`models.status.${state.status}`) }}<template v-if="state.device"> · {{ t(`models.assistant.on.${state.device}`) }}</template>
        </span>
        <template v-if="state.ready">
          <button v-if="state.status === 'running'" type="button" class="rounded-lg border border-border px-3 py-1.5 text-xs text-text-dim hover:border-text-dim hover:text-text" @click="run(() => store.assistantDo('stop'))">{{ t('models.stop') }}</button>
          <button v-else-if="state.status !== 'starting'" type="button" class="accent-gradient rounded-lg px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50" :disabled="!installedModels.length" @click="run(() => store.assistantDo('start'))">{{ t('models.start') }}</button>
        </template>
      </template>
    </div>

    <div class="px-4 pb-4">
      <p class="mt-4 max-w-3xl text-sm leading-relaxed text-text-dim">{{ t('models.assistant.lead') }}</p>
      <p v-if="actionError" class="mt-3 rounded-lg bg-status-failed/10 p-3 text-xs text-status-failed" role="alert">{{ actionError }}</p>
      <p v-if="state?.error" class="mt-3 whitespace-pre-line rounded-lg bg-status-failed/10 p-3 text-xs text-status-failed">{{ state.error }}</p>
      <p v-if="state && !state.ready" class="mt-3 rounded-lg bg-status-queued/10 p-3 text-xs text-status-queued">{{ t('models.assistant.notInstalled') }}</p>

      <template v-if="state && state.ready && form">
        <h3 class="mt-4 text-[11px] font-semibold tracking-wider text-text-dim uppercase">{{ t('models.settings') }}</h3>
        <form class="mt-2 grid gap-4 sm:grid-cols-2" @change="save" @submit.prevent>
          <label class="flex flex-col gap-1 text-xs">
            <span class="font-medium text-text">{{ t('models.assistant.model') }}</span>
            <select v-model="form.model" class="rounded-lg border border-border bg-panel-2 px-2.5 py-2 text-sm text-text focus:border-accent1 focus:outline-none">
              <option v-for="m in state.models" :key="m.id" :value="m.id" :disabled="!m.installed">{{ shortName(m.id) }}{{ m.installed ? '' : ` — ${t('models.assistant.notDownloaded')}` }}</option>
            </select>
            <span class="leading-relaxed text-text-dim">{{ t('models.assistant.modelHint') }}</span>
          </label>
          <label class="flex flex-col gap-1 text-xs">
            <span class="font-medium text-text">{{ t('models.assistant.device') }}</span>
            <select v-model="form.device" class="rounded-lg border border-border bg-panel-2 px-2.5 py-2 text-sm text-text focus:border-accent1 focus:outline-none">
              <option v-for="d in ['auto', 'cpu', 'cuda']" :key="d" :value="d">{{ t(`models.assistant.devices.${d}`) }}</option>
            </select>
            <span class="leading-relaxed text-text-dim">{{ t('models.assistant.deviceHint') }}</span>
          </label>
          <label class="flex flex-col gap-1 text-xs">
            <span class="font-medium text-text">{{ t('models.cpu.threads') }}</span>
            <select v-model.number="form.threads" class="rounded-lg border border-border bg-panel-2 px-2.5 py-2 text-sm text-text focus:border-accent1 focus:outline-none">
              <option v-for="n in threadChoices" :key="n" :value="n">{{ n === 0 ? t('models.cpu.threadsAuto') : n }}</option>
            </select>
          </label>
          <label class="flex flex-col gap-1 text-xs">
            <span class="font-medium text-text">{{ t('models.cpu.idle') }}</span>
            <select v-model.number="form.idle_minutes" class="rounded-lg border border-border bg-panel-2 px-2.5 py-2 text-sm text-text focus:border-accent1 focus:outline-none">
              <option v-for="m in [5, 10, 30, 60, 0]" :key="m" :value="m">{{ m === 0 ? t('models.cpu.idleNever') : t('models.cpu.idleMin', { n: m }) }}</option>
            </select>
          </label>
        </form>
        <p v-if="state.restart_pending" class="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-status-queued/10 px-3 py-2 text-xs text-status-queued">
          {{ t('models.assistant.restartPending') }}
          <button type="button" class="rounded-lg border border-status-queued/40 px-2.5 py-1 text-status-queued hover:bg-status-queued/10" @click="run(async () => { await store.assistantDo('stop'); await store.assistantDo('start') })">{{ t('models.restart') }}</button>
        </p>

        <h3 class="mt-5 border-t border-border pt-4 text-[11px] font-semibold tracking-wider text-text-dim uppercase">{{ t('models.weights') }}</h3>
        <ul class="mt-1">
          <PartRow
            v-for="m in state.models"
            :key="m.id"
            :name="shortName(m.id)"
            :hint="t(`models.assistant.models.${modelKey(m.id)}`)"
            :bytes="m.bytes"
            :on-disk="m.on_disk"
            :installed="m.installed"
            :download="m.download"
            :deletable="true"
            :blocked="!!state.downloading"
            :blocked-title="state.downloading ? t('models.oneAtATime') : undefined"
            @download="run(() => store.assistantDo('download', m.id))"
            @cancel="run(() => store.assistantDo('cancel', m.id))"
            @delete="run(() => store.assistantDo('delete', m.id))"
          />
        </ul>

        <!-- try it -->
        <h3 class="mt-5 border-t border-border pt-4 text-[11px] font-semibold tracking-wider text-text-dim uppercase">{{ t('models.assistant.tryTitle') }}</h3>
        <form class="mt-2 space-y-2" @submit.prevent="tryIt">
          <textarea
            v-model="idea"
            rows="2"
            :placeholder="t('models.assistant.ideaPlaceholder')"
            :aria-label="t('models.assistant.idea')"
            class="w-full resize-y rounded-lg border border-border bg-panel-2 px-3 py-2 text-sm text-text placeholder:text-text-dim/70 focus:border-accent1 focus:outline-none"
          ></textarea>
          <div class="flex flex-wrap items-center gap-2">
            <select v-model="task" :aria-label="t('models.assistant.task')" class="rounded-lg border border-border bg-panel-2 px-2.5 py-1.5 text-sm text-text focus:border-accent1 focus:outline-none">
              <option v-for="k in TASKS" :key="k" :value="k">{{ t(`models.assistant.tasks.${k}`) }}</option>
            </select>
            <button type="submit" class="accent-gradient inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50" :disabled="!idea.trim() || writing || !installedModels.length">
              <SparklesIcon class="h-3.5 w-3.5" />{{ t(writing ? 'models.assistant.writing' : 'models.assistant.write') }}
            </button>
            <span v-if="writing" class="text-xs text-text-dim">{{ t(state.status === 'running' ? 'models.assistant.writingHint' : 'models.assistant.startingHint') }}</span>
          </div>
        </form>
        <p v-if="tryError" class="mt-2 rounded-lg bg-status-failed/10 p-2 text-xs text-status-failed">{{ tryError }}</p>
        <div v-if="result" class="mt-3 rounded-lg border border-border bg-panel-2/60 p-3">
          <p class="text-[11px] text-text-dim">{{ t('models.assistant.took', { s: (result.took_ms / 1000).toFixed(1), tokens: result.tokens, device: t(`models.assistant.on.${result.device}`) }) }}</p>
          <dl class="mt-2 space-y-2 text-sm">
            <div v-for="f in resultFields" :key="f.key" :class="f.long ? '' : 'flex flex-wrap gap-x-2'">
              <dt class="text-xs font-medium text-text-dim">{{ t(`models.assistant.fields.${f.key}`) }}</dt>
              <dd class="text-text" :class="f.long && 'mt-1 max-h-64 overflow-y-auto whitespace-pre-line rounded-md bg-panel p-2 text-xs leading-relaxed'">{{ f.value }}</dd>
            </div>
          </dl>
        </div>
      </template>
    </div>
  </section>
</template>
