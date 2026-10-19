<script setup lang="ts">
// Text-to-audio with Stable Audio 3: a kind (music or a sound), a checkpoint, a description, a length. The
// prompts that work best read like Freesound / AudioSparx metadata, so the help repeats that advice.
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStableAudioStore } from '../../stores/stableAudio'
import type { Sa3Kind, Sa3RefMode, Sa3Reference } from '../../stores/stableAudio'
import type { Sa3ModelId } from '../../api/stableAudio'
import ChipGroup from '../../components/shared/ChipGroup.vue'
import HelpIconButton from '../../components/shared/HelpIconButton.vue'
import HelpModal from '../../components/shared/HelpModal.vue'
import LibraryPicker from '../../components/editor/LibraryPicker.vue'

const store = useStableAudioStore()
const { t, tm } = useI18n()

const kind = ref<Sa3Kind>('music')
const model = ref<Sa3ModelId>('medium')
const prompt = ref('')
const negativePrompt = ref('')
const duration = ref(30)
const count = ref(1)
const seed = ref(-1)
const steps = ref(8)
const cfgScale = ref(1)
const submitting = ref(false)
const formError = ref('')
const helpOpen = ref<false | 'prompt' | 'ref'>(false)

// ---- Reference track: a file or a library track, remade (cover), partly redone (repaint) or carried on ----
const useRef = ref(false)
const refFile = ref<Blob | null>(null)
const refName = ref('')
const refDurationSec = ref(0)
const refTrackId = ref<number | null>(null)
const refLoading = ref(false)
const refMode = ref<Sa3RefMode>('cover')
const closeness = ref(0.5)
const maskStart = ref(0)
const maskEnd = ref(10)
const extendSec = ref(15)
const pickerOpen = ref(false)
const refModeOptions = computed(() => (['cover', 'repaint', 'continue'] as Sa3RefMode[]).map((m) => ({ value: m, label: t(`sa3Gen.ref.modes.${m}`) })))

/** Reads the length through an <audio> element: no decoding, works for wav/mp3/flac alike. */
function audioDuration(blob: Blob): Promise<number> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob)
    const el = new Audio()
    el.preload = 'metadata'
    el.onloadedmetadata = () => {
      URL.revokeObjectURL(url)
      resolve(el.duration)
    }
    el.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('decode'))
    }
    el.src = url
  })
}
async function setReference(blob: Blob, name: string, trackId: number | null) {
  refLoading.value = true
  formError.value = ''
  try {
    const dur = await audioDuration(blob)
    if (!Number.isFinite(dur) || dur <= 0) throw new Error('decode')
    refFile.value = blob
    refName.value = name
    refDurationSec.value = dur
    refTrackId.value = trackId
    maskStart.value = 0
    maskEnd.value = Math.min(10, Math.floor(dur))
  } catch {
    formError.value = t('sa3Gen.ref.decodeError')
  } finally {
    refLoading.value = false
  }
}
function onRefFileChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) void setReference(file, file.name, null)
}
async function onPickFromLibrary(payload: { sourceUrl: string; sourceLabel: string }) {
  pickerOpen.value = false
  refLoading.value = true
  try {
    const resp = await fetch(payload.sourceUrl)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const m = /\/api\/tracks\/(\d+)\/audio/.exec(payload.sourceUrl)
    await setReference(await resp.blob(), payload.sourceLabel, m ? Number(m[1]) : null)
  } catch (err) {
    formError.value = err instanceof Error ? err.message : String(err)
    refLoading.value = false
  }
}
/** Seconds the result will have with a reference: the source's, or the source plus the extension. */
const resultSeconds = computed(() => (refMode.value === 'continue' ? refDurationSec.value + extendSec.value : refDurationSec.value))
const reference = computed<Sa3Reference | null>(() => (useRef.value && refFile.value
  ? { file: refFile.value, name: refName.value, durationSec: refDurationSec.value, trackId: refTrackId.value, mode: refMode.value, closeness: closeness.value, maskStart: maskStart.value, maskEnd: maskEnd.value, extendSec: extendSec.value }
  : null))

const kindOptions = computed(() => [
  { value: 'music', label: t('sa3Gen.kinds.music') },
  { value: 'sfx', label: t('sa3Gen.kinds.sfx') },
])
const countOptions = [1, 2, 4].map((n) => ({ value: n, label: String(n) }))

/** Checkpoints that can run here and are meant for this kind; medium does both. */
const modelOptions = computed(() => store.availableModels.filter((m) => m.kinds.includes(kind.value)))
const selected = computed(() => store.models.find((m) => m.id === model.value))
const maxSeconds = computed(() => selected.value?.max_seconds ?? 120)
const minSeconds = computed(() => (kind.value === 'sfx' ? 0.5 : 5))
const stepSeconds = computed(() => (kind.value === 'sfx' ? 0.5 : 1))

// A kind without its model: fall to the first that fits (small-sfx for sounds, medium otherwise).
watch([modelOptions, kind], () => {
  if (modelOptions.value.length && !modelOptions.value.some((m) => m.id === model.value)) model.value = modelOptions.value[0].id
  if (kind.value === 'sfx' && duration.value > 30) duration.value = 5
  if (kind.value === 'music' && duration.value < 5) duration.value = 30
}, { immediate: true })
watch(maxSeconds, (max) => {
  if (duration.value > max) duration.value = max
})

/** A card's "reuse" puts its parameters back here. */
watch(() => store.pendingParamsInsert, (p) => {
  if (!p) return
  if (p.kind) kind.value = p.kind
  if (p.model) model.value = p.model
  if (p.prompt != null) prompt.value = p.prompt
  if (p.negativePrompt != null) negativePrompt.value = p.negativePrompt
  if (p.duration != null) duration.value = p.duration
  if (p.steps != null) steps.value = p.steps
  if (p.cfgScale != null) cfgScale.value = p.cfgScale
  if (p.seed != null) seed.value = p.seed
  store.clearPendingParamsInsert()
})

const base = computed(() => (model.value.endsWith('-base')))
function formatClockShort(s: number): string {
  if (s < 60) return `${s % 1 ? s.toFixed(1) : s} ${t('common.secondsUnit')}`
  return `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`
}
const durationLabel = computed(() => formatClockShort(duration.value))

function randomSeed() {
  seed.value = Math.floor(Math.random() * 2147483647)
}

async function submit() {
  formError.value = ''
  const text = prompt.value.trim()
  if (!text) {
    formError.value = t('sa3Gen.needPrompt')
    return
  }
  if (!selected.value?.available) {
    formError.value = t('sa3Gen.noModel')
    return
  }
  if (useRef.value) {
    if (!refFile.value) {
      formError.value = t('sa3Gen.ref.needRef')
      return
    }
    if (refMode.value === 'repaint' && (maskStart.value < 0 || maskEnd.value > refDurationSec.value + 0.05 || maskEnd.value - maskStart.value < 1)) {
      formError.value = t('sa3Gen.ref.badRange')
      return
    }
    if (resultSeconds.value > maxSeconds.value) {
      formError.value = t('sa3Gen.ref.tooLong', { v: Math.round(resultSeconds.value), max: maxSeconds.value })
      return
    }
  }
  submitting.value = true
  try {
    await store.generate({
      kind: kind.value, model: model.value, prompt: text, negativePrompt: negativePrompt.value.trim(),
      duration: duration.value, steps: steps.value, cfgScale: cfgScale.value, seed: seed.value, count: count.value,
      reference: reference.value,
    })
  } catch (err) {
    formError.value = err instanceof Error ? err.message : String(err)
  } finally {
    submitting.value = false
  }
}

function applyExample(text: string) {
  prompt.value = text
  helpOpen.value = false
}
</script>

<template>
  <div class="lg:sticky lg:top-20 lg:self-start">
    <div class="space-y-4 rounded-xl border border-border bg-panel p-4">
      <button type="button" class="accent-gradient w-full rounded-lg py-2.5 text-sm font-semibold text-white disabled:opacity-50" :disabled="submitting" @click="submit">
        {{ submitting ? t('sa3Gen.submitting') : t('sa3Gen.submit') }}
      </button>
      <p v-if="formError" class="rounded-lg bg-status-failed/10 p-2 text-xs text-status-failed">{{ formError }}</p>

      <div class="flex items-center justify-between gap-3">
        <ChipGroup v-model="kind" :options="kindOptions" />
        <HelpIconButton :title="t('sa3Gen.help.title')" @click="helpOpen = 'prompt'" />
      </div>

      <div class="space-y-1.5">
        <label class="block text-sm font-medium text-text" for="sa3-prompt">{{ t('sa3Gen.promptLabel') }}</label>
        <textarea
          id="sa3-prompt"
          v-model="prompt"
          rows="4"
          class="w-full resize-y rounded-lg border border-border bg-panel-2 px-3 py-2 text-sm text-text placeholder:text-text-dim/70 focus:border-accent1 focus:outline-none"
          :placeholder="t(`sa3Gen.promptPlaceholder.${kind}`)"
        ></textarea>
        <p class="text-xs text-text-dim">{{ t('sa3Gen.promptHint') }}</p>
      </div>

      <!-- A reference track: the length then comes from it, so the slider steps aside -->
      <div class="space-y-2 rounded-lg border border-border bg-panel-2/50 p-3">
        <label class="flex items-center justify-between text-sm">
          <span class="flex items-center gap-2 font-medium text-text">
            <input v-model="useRef" type="checkbox" class="rounded border-border" />
            {{ t('sa3Gen.ref.toggle') }}
          </span>
          <HelpIconButton @click="helpOpen = 'ref'" />
        </label>
        <div v-if="useRef" class="space-y-3 pt-1">
          <div class="flex flex-wrap items-center gap-2">
            <label class="cursor-pointer rounded-md border border-border px-3 py-1.5 text-xs text-text hover:bg-panel">
              {{ t('sa3Gen.ref.chooseFile') }}
              <input type="file" accept="audio/*" class="sr-only" @change="onRefFileChange" />
            </label>
            <button type="button" class="rounded-md border border-border px-3 py-1.5 text-xs text-text hover:bg-panel" @click="pickerOpen = true">{{ t('sa3Gen.ref.fromLibrary') }}</button>
            <span v-if="refLoading" class="text-xs text-text-dim">{{ t('sa3Gen.ref.loading') }}</span>
            <span v-else-if="refFile" class="min-w-0 truncate text-xs text-text" :title="refName">{{ t('sa3Gen.ref.source', { name: refName, dur: formatClockShort(refDurationSec) }) }}</span>
            <span v-else class="text-xs text-text-dim">{{ t('sa3Gen.ref.none') }}</span>
          </div>
          <ChipGroup v-model="refMode" :options="refModeOptions" />
          <p class="text-xs text-text-dim">{{ t(`sa3Gen.ref.modeHints.${refMode}`) }}</p>
          <label v-if="refMode === 'cover'" class="block space-y-1">
            <span class="text-xs text-text">{{ t('sa3Gen.ref.closeness', { v: closeness.toFixed(2) }) }}</span>
            <input v-model.number="closeness" type="range" min="0" max="1" step="0.05" class="w-full accent-accent1" />
          </label>
          <div v-else-if="refMode === 'repaint'" class="grid grid-cols-2 gap-2">
            <label class="space-y-1">
              <span class="block text-xs text-text-dim">{{ t('sa3Gen.ref.rangeFrom') }}</span>
              <input v-model.number="maskStart" type="number" min="0" :max="refDurationSec" step="0.5" class="w-full rounded-lg border border-border bg-panel-2 px-2 py-1.5 text-sm text-text" />
            </label>
            <label class="space-y-1">
              <span class="block text-xs text-text-dim">{{ t('sa3Gen.ref.rangeTo') }}</span>
              <input v-model.number="maskEnd" type="number" min="0" :max="refDurationSec" step="0.5" class="w-full rounded-lg border border-border bg-panel-2 px-2 py-1.5 text-sm text-text" />
            </label>
          </div>
          <label v-else class="block space-y-1">
            <span class="text-xs text-text">{{ t('sa3Gen.ref.extend', { v: formatClockShort(extendSec) }) }}</span>
            <input v-model.number="extendSec" type="range" min="2" :max="Math.max(2, maxSeconds - Math.ceil(refDurationSec))" step="1" class="w-full accent-accent1" />
          </label>
          <p v-if="refFile" class="text-xs tabular-nums text-text-dim">{{ t('sa3Gen.ref.length', { v: formatClockShort(resultSeconds) }) }}</p>
        </div>
      </div>

      <div v-if="!useRef" class="space-y-1.5">
        <div class="flex items-baseline justify-between">
          <label class="text-sm font-medium text-text" for="sa3-duration">{{ t('sa3Gen.duration') }}</label>
          <span class="text-xs tabular-nums text-text-dim">{{ durationLabel }}</span>
        </div>
        <input id="sa3-duration" v-model.number="duration" type="range" :min="minSeconds" :max="maxSeconds" :step="stepSeconds" class="w-full accent-accent1" />
        <p class="text-xs text-text-dim">{{ t(`sa3Gen.durationHint.${kind}`) }}</p>
      </div>

      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1.5">
          <label class="block text-sm font-medium text-text" for="sa3-model">{{ t('sa3Gen.model') }}</label>
          <select id="sa3-model" v-model="model" class="w-full rounded-lg border border-border bg-panel-2 px-2.5 py-2 text-sm text-text">
            <option v-for="m in modelOptions" :key="m.id" :value="m.id">{{ m.label }} · {{ m.params }}</option>
            <option v-if="!modelOptions.length" value="medium" disabled>{{ t('sa3Gen.noModel') }}</option>
          </select>
          <p v-if="selected && !selected.loaded" class="text-xs text-text-dim">{{ selected.loading ? t('sa3Gen.modelLoading') : t('sa3Gen.modelCold') }}</p>
        </div>
        <div class="space-y-1.5">
          <span class="block text-sm font-medium text-text">{{ t('sa3Gen.variants') }}</span>
          <ChipGroup v-model="count" :options="countOptions" />
        </div>
      </div>

      <details class="rounded-lg border border-border bg-panel-2/40 p-3 text-sm">
        <summary class="cursor-pointer select-none text-sm font-medium text-text">{{ t('sa3Gen.advanced') }}</summary>
        <div class="mt-3 space-y-3">
          <div class="grid grid-cols-3 gap-3">
            <div class="space-y-1">
              <label class="block text-xs text-text-dim" for="sa3-seed">{{ t('sa3Gen.seed') }}</label>
              <div class="flex gap-1">
                <input id="sa3-seed" v-model.number="seed" type="number" class="w-full min-w-0 rounded-lg border border-border bg-panel-2 px-2 py-1.5 text-sm text-text" />
                <button type="button" class="shrink-0 rounded-lg border border-border px-2 text-xs text-text hover:bg-panel-2" :title="t('sa3Gen.randomSeed')" @click="randomSeed">🎲</button>
              </div>
            </div>
            <div class="space-y-1">
              <label class="block text-xs text-text-dim" for="sa3-steps">{{ t('sa3Gen.steps') }}</label>
              <input id="sa3-steps" v-model.number="steps" type="number" min="1" max="200" class="w-full rounded-lg border border-border bg-panel-2 px-2 py-1.5 text-sm text-text" />
            </div>
            <div class="space-y-1">
              <label class="block text-xs text-text-dim" for="sa3-cfg">{{ t('sa3Gen.cfg') }}</label>
              <input id="sa3-cfg" v-model.number="cfgScale" type="number" min="0" max="25" step="0.5" class="w-full rounded-lg border border-border bg-panel-2 px-2 py-1.5 text-sm text-text" />
            </div>
          </div>
          <p class="text-xs text-text-dim">{{ base ? t('sa3Gen.advancedHintBase') : t('sa3Gen.advancedHint') }}</p>
          <div class="space-y-1">
            <label class="block text-xs text-text-dim" for="sa3-negative">{{ t('sa3Gen.negative') }}</label>
            <input id="sa3-negative" v-model="negativePrompt" type="text" class="w-full rounded-lg border border-border bg-panel-2 px-2 py-1.5 text-sm text-text" :placeholder="t('sa3Gen.negativePlaceholder')" />
          </div>
        </div>
      </details>
    </div>

    <LibraryPicker v-if="pickerOpen" @pick="onPickFromLibrary" @close="pickerOpen = false" />

    <HelpModal :open="helpOpen === 'ref'" :title="t('sa3Gen.ref.help.title')" @close="helpOpen = false">
      <p>{{ t('sa3Gen.ref.help.text') }}</p>
    </HelpModal>
    <HelpModal :open="helpOpen === 'prompt'" :title="t('sa3Gen.help.title')" @close="helpOpen = false">
      <div class="space-y-4">
        <p>{{ t('sa3Gen.help.intro') }}</p>
        <section>
          <h4 class="mb-1.5 text-sm font-semibold text-text">{{ t('sa3Gen.help.tipsTitle') }}</h4>
          <ul class="list-disc space-y-1 pl-4">
            <li v-for="x in (tm('sa3Gen.help.tips') as string[])" :key="x">{{ x }}</li>
          </ul>
        </section>
        <section>
          <h4 class="mb-1.5 text-sm font-semibold text-text">{{ t('sa3Gen.help.examplesTitle') }}</h4>
          <ul class="space-y-1.5">
            <li v-for="x in (tm('sa3Gen.help.examples') as string[])" :key="x">
              <button type="button" class="w-full rounded-lg border border-border/60 bg-panel-2/50 px-3 py-2 text-left text-xs leading-relaxed hover:border-accent1/50" @click="applyExample(x)">{{ x }}</button>
            </li>
          </ul>
        </section>
      </div>
    </HelpModal>
  </div>
</template>
