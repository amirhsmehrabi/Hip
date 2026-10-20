<script setup lang="ts">
// "From an idea" (RFC 0002, phase 2): one field for the idea, song or instrumental, and ACE-Step's prompt written
// for it by the prompt assistant, or by ACE-Step's own language model when the engine runs and that is picked. The
// assistant is the default: ACE-Step's own model is faster but strays from the idea (RFC 0002, section 8).
// The prompt is shown as editable cards; "Generate" starts ACE-Step if needed and sends the same request its page's
// custom mode sends, then opens that page, where the track lands in the feed.
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import * as aceApi from '../../api/aceStep'
import type { GenerateMusicRequest } from '../../api/aceStep'
import { writePrompt } from '../../api/assistant'
import { MODEL_LABELS } from '../../composables/useModelSwitch'
import { useAceStepStore } from '../../stores/aceStep'
import { useEnginesStore } from '../../stores/engines'
import { useOrchestratorStore } from '../../stores/orchestrator'
import { guessVocalLanguage, VOCAL_LANGUAGES } from '../../utils/vocalLanguages'
import ChipGroup from '../../components/shared/ChipGroup.vue'
import SparklesIcon from '../../components/shared/icons/SparklesIcon.vue'
import WaveIcon from '../../components/shared/icons/WaveIcon.vue'

const { t } = useI18n()
const router = useRouter()
const orchestrator = useOrchestratorStore()
const ace = useAceStepStore()
const engines = useEnginesStore()

// ---- the idea (kept in this browser, so a reload does not lose it) ----
const STORE_KEY = 'remiqora.idea'
type Kind = 'song' | 'instrumental'
type Writer = 'assistant' | 'ace'
const idea = ref('')
const kind = ref<Kind>('song')
/** '' = from the idea's letters. */
const language = ref('')
const writerPref = ref<Writer>('assistant')
try {
  const saved = JSON.parse(localStorage.getItem(STORE_KEY) || '{}')
  if (typeof saved.idea === 'string') idea.value = saved.idea
  if (saved.kind === 'song' || saved.kind === 'instrumental') kind.value = saved.kind
  if (typeof saved.language === 'string') language.value = saved.language
  if (saved.writer === 'assistant' || saved.writer === 'ace') writerPref.value = saved.writer
} catch {
  // a private window or blocked storage: start empty
}
watch([idea, kind, language, writerPref], () => {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify({ idea: idea.value, kind: kind.value, language: language.value, writer: writerPref.value }))
  } catch {
    // not saved; nothing else depends on it
  }
})
const instrumental = computed(() => kind.value === 'instrumental')
const effectiveLanguage = computed(() => language.value || (idea.value.trim() ? guessVocalLanguage(idea.value) : 'en'))
const kindOptions = computed(() => [
  { value: 'song', label: t('idea.song') },
  { value: 'instrumental', label: t('idea.instrumental') },
])

// ---- who writes the prompt ----
const aceStatus = computed(() => orchestrator.statuses.ace_step?.status ?? 'stopped')
const aceRunning = computed(() => orchestrator.activeModel === 'ace_step' && aceStatus.value === 'running')
/** The assistant can stand in while ACE-Step is not running (a downloaded model is enough). */
const assistantReady = computed(() => !!engines.assistant?.ready && !!engines.assistant?.models.some((m) => m.installed))
/** The picked writer when it can write now, else the other one, else none. */
const writer = computed<Writer | null>(() => {
  const can = { assistant: assistantReady.value, ace: aceRunning.value }
  if (can[writerPref.value]) return writerPref.value
  return can.assistant ? 'assistant' : can.ace ? 'ace' : null
})
const writerOptions = computed(() => [
  { value: 'assistant', label: t('idea.writerAssistant'), disabled: !assistantReady.value },
  { value: 'ace', label: t('idea.writerAce'), disabled: !aceRunning.value },
])
/** ACE-Step holds the GPU: the assistant writes on the CPU, so it takes longer. */
const assistantOnCpu = computed(() => !!orchestrator.activeModel)

// ---- the prompt, editable ----
interface Draft {
  caption: string
  lyrics: string
  bpm: number | null
  keyscale: string
  duration: number
  timesignature: string
  language: string
  writtenBy: 'ace' | 'assistant'
  seconds: number
}
const draft = ref<Draft | null>(null)
const writing = ref(false)
const error = ref<string | null>(null)

async function write() {
  const text = idea.value.trim()
  if (!text) {
    error.value = t('idea.needIdea')
    return
  }
  if (!writer.value) {
    error.value = t('idea.noWriter')
    return
  }
  writing.value = true
  error.value = null
  const t0 = performance.now()
  try {
    if (writer.value === 'ace') {
      const s = await aceApi.createSample(text, instrumental.value, instrumental.value ? undefined : effectiveLanguage.value)
      draft.value = {
        caption: s.caption,
        lyrics: instrumental.value ? '' : s.lyrics,
        bpm: s.bpm ?? null,
        keyscale: s.keyscale || '',
        duration: Math.round(s.duration || 120),
        timesignature: s.timesignature || '',
        language: instrumental.value ? '' : s.vocal_language && s.vocal_language !== 'unknown' ? s.vocal_language : effectiveLanguage.value,
        writtenBy: 'ace',
        seconds: (performance.now() - t0) / 1000,
      }
    } else {
      const r = await writePrompt(instrumental.value ? 'ace-instrumental' : 'ace-song', text, { language: effectiveLanguage.value })
      const f = r.fields
      draft.value = {
        caption: String(f.caption ?? ''),
        lyrics: instrumental.value ? '' : String(f.lyrics ?? ''),
        bpm: typeof f.bpm === 'number' ? f.bpm : null,
        keyscale: String(f.keyscale ?? ''),
        duration: typeof f.duration === 'number' ? f.duration : 120,
        timesignature: '',
        language: instrumental.value ? '' : effectiveLanguage.value,
        writtenBy: 'assistant',
        seconds: (performance.now() - t0) / 1000,
      }
      void engines.load()
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    writing.value = false
  }
}

const durationLabel = computed(() => {
  const d = draft.value?.duration ?? 0
  return `${Math.floor(d / 60)}:${String(Math.round(d % 60)).padStart(2, '0')}`
})

// ---- generate ----
const variants = ref<1 | 2 | 4>(1)
const variantOptions = [1, 2, 4].map((n) => ({ value: n, label: String(n) }))
const starting = ref(false)

function request(): GenerateMusicRequest | null {
  const d = draft.value
  if (!d || !d.caption.trim()) return null
  const req: GenerateMusicRequest = {
    prompt: d.caption.trim(),
    lyrics: instrumental.value ? '' : d.lyrics,
    audio_duration: Math.max(10, Math.min(600, Math.round(d.duration))),
    batch_size: variants.value,
    audio_format: 'mp3',
    use_random_seed: true,
  }
  if (d.bpm) req.bpm = Math.round(d.bpm)
  if (d.keyscale.trim()) req.key_scale = d.keyscale.trim()
  if (d.timesignature) req.time_signature = d.timesignature
  if (!instrumental.value && d.language) req.vocal_language = d.language
  return req
}

/** The idea as the track's title, cut at a word near 60 characters (a cut at the first comma left "a song about"). */
function titleOf(text: string): string {
  const one = text.trim().replace(/\s+/g, ' ')
  if (one.length <= 60) return one
  const cut = one.slice(0, 60)
  const space = cut.lastIndexOf(' ')
  return `${(space > 30 ? cut.slice(0, space) : cut).replace(/[,.;:!?\s]+$/, '')}…`
}

async function generate() {
  const req = request()
  if (!req) {
    error.value = t('idea.needCaption')
    return
  }
  error.value = null
  starting.value = true
  try {
    if (!aceRunning.value) await orchestrator.switchModel('ace_step')
    await ace.submit(req, null, titleOf(idea.value || req.prompt || ''))
    await router.push({ name: 'ace-step' })
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    starting.value = false
  }
}

/** The ACE-Step page's form with this prompt in its custom mode, for the settings this page leaves out. */
async function openInForm() {
  const req = request()
  if (!req) return
  ace.requestInsertParams({
    prompt: req.prompt,
    lyrics: req.lyrics,
    instrumental: instrumental.value,
    duration: req.audio_duration,
    bpm: req.bpm ?? null,
    key_scale: req.key_scale ?? '',
    time_signature: req.time_signature ?? '',
    vocal_language: req.vocal_language ?? '',
  })
  await router.push({ name: 'ace-step' })
}

async function startAce() {
  try {
    await orchestrator.switchModel('ace_step')
  } catch {
    // orchestrator.switchError is shown in the header
  }
}

onMounted(() => {
  void engines.load()
})
</script>

<template>
  <div class="mx-auto max-w-3xl">
    <header>
      <h1 class="text-2xl font-semibold text-text">{{ t('idea.title') }}</h1>
      <p class="mt-1 text-sm leading-relaxed text-text-dim">{{ t('idea.lead') }}</p>
    </header>

    <!-- the idea -->
    <section class="mt-5 rounded-xl border border-border bg-panel p-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <ChipGroup v-model="kind" :options="kindOptions" />
        <label v-if="!instrumental" class="flex items-center gap-2 text-xs text-text-dim">
          {{ t('idea.language') }}
          <select v-model="language" class="rounded-lg border border-border bg-panel-2 px-2 py-1.5 text-sm text-text focus:border-accent1 focus:outline-none">
            <option value="">{{ t('idea.languageAuto', { lang: VOCAL_LANGUAGES.find((l) => l.code === effectiveLanguage)?.label ?? effectiveLanguage }) }}</option>
            <option v-for="l in VOCAL_LANGUAGES" :key="l.code" :value="l.code">{{ l.label }}</option>
          </select>
        </label>
      </div>
      <textarea
        v-model="idea"
        rows="3"
        :aria-label="t('idea.ideaLabel')"
        :placeholder="t(instrumental ? 'idea.placeholderInstrumental' : 'idea.placeholderSong')"
        class="mt-3 w-full resize-y rounded-lg border border-border bg-panel-2 px-3 py-2.5 text-base leading-relaxed text-text placeholder:text-text-dim/70 focus:border-accent1 focus:outline-none"
        @keydown.ctrl.enter="write"
      ></textarea>

      <!-- the engine: ACE-Step in this phase -->
      <div class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <span class="inline-flex items-center gap-2 rounded-lg border border-accent1/50 bg-accent1/10 px-3 py-1.5 text-sm text-text">
          <WaveIcon class="h-4 w-4 text-accent1" />{{ MODEL_LABELS.ace_step }}
          <span class="h-1.5 w-1.5 rounded-full" :class="aceRunning ? 'bg-status-done' : 'bg-text-dim/50'"></span>
        </span>
        <button
          type="button"
          class="accent-gradient ml-auto inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          :disabled="writing || !idea.trim() || !writer"
          @click="write"
        >
          <SparklesIcon class="h-4 w-4" />{{ t(writing ? 'idea.writing' : draft ? 'idea.rewrite' : 'idea.write') }}
        </button>
      </div>
      <div v-if="assistantReady || aceRunning" class="mt-3 flex flex-wrap items-center gap-2 text-xs text-text-dim">
        {{ t('idea.writer') }}
        <ChipGroup v-model="writerPref" small :options="writerOptions" />
      </div>
      <p class="mt-2 text-xs leading-relaxed" :class="writer ? 'text-text-dim' : 'text-status-queued'">
        <template v-if="writer === 'ace'">{{ t('idea.byAce') }}</template>
        <template v-else-if="writer === 'assistant'">{{ t(assistantOnCpu ? 'idea.byAssistantCpu' : 'idea.byAssistant') }}</template>
        <template v-else>
          {{ t('idea.noWriter') }}
          <button type="button" class="text-accent1 underline disabled:opacity-50" :disabled="orchestrator.switching" @click="startAce">{{ t('idea.startAce') }}</button>
          · <RouterLink to="/models#assistant" class="text-accent1 underline">{{ t('idea.setupAssistant') }}</RouterLink>
        </template>
        <span v-if="writing" class="ml-1">{{ t(writer === 'ace' ? 'idea.writingAce' : 'idea.writingAssistant') }}</span>
      </p>
      <p v-if="error" class="mt-3 rounded-lg bg-status-failed/10 p-3 text-xs text-status-failed" role="alert">{{ error }}</p>
    </section>

    <!-- the prompt -->
    <section v-if="draft" class="mt-4 overflow-hidden rounded-xl border border-border bg-panel">
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-panel-2/60 px-4 py-2.5">
        <h2 class="text-sm font-semibold text-text">{{ t('idea.promptTitle') }}</h2>
        <span class="text-xs text-text-dim">{{ t(draft.writtenBy === 'ace' ? 'idea.writtenByAce' : 'idea.writtenByAssistant', { s: draft.seconds.toFixed(1) }) }}</span>
      </div>
      <div class="space-y-4 p-4">
        <label class="flex flex-col gap-1 text-xs">
          <span class="font-medium text-text">{{ t('idea.caption') }}</span>
          <textarea v-model="draft.caption" rows="2" class="resize-y rounded-lg border border-border bg-panel-2 px-3 py-2 text-sm leading-relaxed text-text focus:border-accent1 focus:outline-none"></textarea>
        </label>
        <label v-if="!instrumental" class="flex flex-col gap-1 text-xs">
          <span class="font-medium text-text">{{ t('idea.lyrics') }}</span>
          <textarea v-model="draft.lyrics" rows="12" class="resize-y rounded-lg border border-border bg-panel-2 px-3 py-2 font-mono text-[13px] leading-relaxed text-text focus:border-accent1 focus:outline-none"></textarea>
        </label>
        <div class="grid gap-3 sm:grid-cols-4">
          <label class="flex flex-col gap-1 text-xs">
            <span class="font-medium text-text">{{ t('idea.bpm') }}</span>
            <input v-model.number="draft.bpm" type="number" min="30" max="300" class="rounded-lg border border-border bg-panel-2 px-2.5 py-2 text-sm text-text focus:border-accent1 focus:outline-none" />
          </label>
          <label class="flex flex-col gap-1 text-xs">
            <span class="font-medium text-text">{{ t('idea.key') }}</span>
            <input v-model="draft.keyscale" type="text" placeholder="A minor" class="rounded-lg border border-border bg-panel-2 px-2.5 py-2 text-sm text-text focus:border-accent1 focus:outline-none" />
          </label>
          <label class="flex flex-col gap-1 text-xs">
            <span class="font-medium text-text">{{ t('idea.duration', { label: durationLabel }) }}</span>
            <input v-model.number="draft.duration" type="number" min="10" max="600" step="5" class="rounded-lg border border-border bg-panel-2 px-2.5 py-2 text-sm text-text focus:border-accent1 focus:outline-none" />
          </label>
          <label v-if="!instrumental" class="flex flex-col gap-1 text-xs">
            <span class="font-medium text-text">{{ t('idea.vocalLanguage') }}</span>
            <select v-model="draft.language" class="rounded-lg border border-border bg-panel-2 px-2 py-2 text-sm text-text focus:border-accent1 focus:outline-none">
              <option v-for="l in VOCAL_LANGUAGES" :key="l.code" :value="l.code">{{ l.label }}</option>
            </select>
          </label>
        </div>

        <div class="flex flex-wrap items-center gap-3 border-t border-border pt-4">
          <span class="text-xs text-text-dim">{{ t('idea.variants') }}</span>
          <ChipGroup v-model="variants" small :options="variantOptions" />
          <button type="button" class="ml-auto rounded-lg border border-border px-3 py-2 text-xs text-text-dim hover:border-text-dim hover:text-text" @click="openInForm">{{ t('idea.openInForm') }}</button>
          <button type="button" class="accent-gradient inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" :disabled="starting || orchestrator.switching || !draft.caption.trim()" @click="generate">
            {{ t(starting ? (aceRunning ? 'idea.sending' : 'idea.startingAce') : 'idea.generate') }}
          </button>
        </div>
        <p v-if="!aceRunning && orchestrator.activeModel && orchestrator.activeModel !== 'ace_step'" class="-mt-2 text-right text-[11px] text-text-dim">{{ t('aiPart.engineSwitchNote', { running: MODEL_LABELS[orchestrator.activeModel] }) }}</p>
      </div>
    </section>
  </div>
</template>
