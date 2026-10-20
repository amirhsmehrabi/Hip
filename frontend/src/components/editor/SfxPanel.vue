<script setup lang="ts">
// "Samples": one-shots, loops and textures from Stable Audio 3, auditioned in a strip of results and
// placed on the timeline by hand (a new lane, or the selected lane at the playhead). Same shell as the
// AI arranger: a docked, single-root panel with a grip, a top row that keeps the action in view.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { decodeStem } from '../../audio/mixerEngine'
import type { Clip } from '../../audio/timelineTypes'
import * as tracksApi from '../../api/tracks'
import { audioBufferToWavFile, renderContext } from '../../utils/aiParts'
import { shortLaneNames } from '../../utils/laneNames'
import { TRACK_COLORS } from '../../utils/trackColors'
import { claimPlayback, fetchAndComputePeaks, releasePlaybackIfCurrent } from '../../composables/audioPlayback'
import { useEditorStore } from '../../stores/editor'
import { useEnginesStore } from '../../stores/engines'
import { useFeaturesStore } from '../../stores/features'
import { useOrchestratorStore } from '../../stores/orchestrator'
import { SFX_KINDS, useSfxStore } from '../../stores/sfx'
import type { SfxJob, SfxKind, SfxVariant } from '../../stores/sfx'
import { useStableAudioStore } from '../../stores/stableAudio'
import type { Sa3ModelId } from '../../api/stableAudio'
import { MODEL_LABELS } from '../../composables/useModelSwitch'
import type { DockSide } from '../../utils/dock'
import ChipGroup from '../shared/ChipGroup.vue'
import HelpIconButton from '../shared/HelpIconButton.vue'
import HelpModal from '../shared/HelpModal.vue'
import HelpBody from '../shared/help/HelpBody.vue'
import HelpSection from '../shared/help/HelpSection.vue'
import HelpList from '../shared/help/HelpList.vue'
import HelpExamples from '../shared/help/HelpExamples.vue'
import PauseIcon from '../shared/icons/PauseIcon.vue'
import PlayIcon from '../shared/icons/PlayIcon.vue'
import PlusIcon from '../shared/icons/PlusIcon.vue'
import SampleIcon from '../shared/icons/SampleIcon.vue'

const props = defineProps<{ buffers: Map<string, AudioBuffer>; dock?: DockSide }>()
const narrow = computed(() => props.dock === 'right')
const emit = defineEmits<{ close: []; 'play-from': [sec: number] }>()

const { t, tm } = useI18n()
const store = useEditorStore()
const sfxStore = useSfxStore()
const sa3Store = useStableAudioStore()
const orchestrator = useOrchestratorStore()
const features = useFeaturesStore()
const engines = useEnginesStore()

// ---- Form ----
const kind = ref<SfxKind>('oneshot')
const captions = ref<Record<SfxKind, string>>({ oneshot: '', loop: '', texture: '' })
const oneshotSec = ref(2)
const loopBars = ref(2)
const textureSec = ref(15)
const count = ref(2)
const target = ref<'new' | 'selected'>('new')
/** Loop: crossfade the tail into the head when placing, so it repeats without a click. */
const seamless = ref(false)
/** One-shot: the server drops the quiet run before the attack. */
const trimSilence = ref(true)
const SEAM_SEC = 0.03

/**
 * Equal-power crossfade of the last SEAM_SEC into the first: the clip's end then matches its start, so a
 * loop of it joins cleanly. Returns a new buffer shorter by the seam (the overlapped tail is folded in).
 */
function seamLoop(buf: AudioBuffer): AudioBuffer {
  const n = Math.min(Math.floor(SEAM_SEC * buf.sampleRate), Math.floor(buf.length / 4))
  if (n < 8) return buf
  const out = new AudioBuffer({ numberOfChannels: buf.numberOfChannels, length: buf.length - n, sampleRate: buf.sampleRate })
  for (let c = 0; c < buf.numberOfChannels; c++) {
    const src = buf.getChannelData(c)
    const dst = out.getChannelData(c)
    dst.set(src.subarray(0, out.length))
    for (let i = 0; i < n; i++) {
      const w = (i / n) * Math.PI / 2
      // the head fades in while the tail fades out, folded onto the head
      dst[i] = src[i] * Math.sin(w) + src[out.length + i] * Math.cos(w)
    }
  }
  return out
}
const model = ref<Sa3ModelId>('small-sfx')
const preparing = ref(false)
const formError = ref<string | null>(null)
const helpOpen = ref(false)

const PLACEHOLDERS: Record<SfxKind, string> = {
  oneshot: 'punchy 808 kick, short decay, slight saturation',
  loop: 'dusty boom-bap drums, swung hi-hats, vinyl crackle',
  texture: 'rain on a tin roof, distant thunder, soft wind',
}
const kindOptions = computed(() => SFX_KINDS.map((k) => ({ value: k, label: t(`sfx.kinds.${k}`) })))
const barOptions = [1, 2, 4, 8].map((n) => ({ value: n, label: String(n) }))
const countOptions = [1, 2, 4].map((n) => ({ value: n, label: String(n) }))
const bpm = computed(() => store.project.bpm || 120)
const barSec = computed(() => (4 * 60) / bpm.value)
const duration = computed(() => (kind.value === 'loop' ? loopBars.value * barSec.value : kind.value === 'oneshot' ? oneshotSec.value : textureSec.value))
function fmtSec(s: number): string {
  return s < 10 ? `${s.toFixed(1)} ${t('common.secondsUnit')}` : `${Math.round(s)} ${t('common.secondsUnit')}`
}
function fmtPos(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${s < 10 ? '0' : ''}${s.toFixed(1)}`
}

// ---- Listening to the timeline ----
// The ticked lanes, mixed over a span as long as the sample (from the loop start, else the playhead),
// go to the model as audio-to-audio: the sample then follows their rhythm and colour, as close as asked.
const listen = ref(false)
// At 0.5 the result is still the source (its timbre survives); from about 0.3 down the words win.
const closeness = ref(0.3)
const candidateLanes = computed(() => store.project.lanes.filter((l) => l.clips.some((c) => c.type !== 'midi' && c.sourceUrl)))
/** Chip labels: stems of one track differ only after the colon, so the shared start is dropped. */
const laneLabels = computed(() => {
  const short = shortLaneNames(candidateLanes.value.map((l) => l.name))
  return Object.fromEntries(candidateLanes.value.map((l, i) => [l.id, short[i]]))
})
const listenIds = ref<string[]>([])
const knownLanes = new Set<string>()
let knownSession = -1
watch([() => store.session, candidateLanes], ([session, lanes]) => {
  if (session !== knownSession) {
    knownSession = session
    knownLanes.clear()
    listenIds.value = []
  }
  for (const l of lanes) {
    if (knownLanes.has(l.id)) continue
    knownLanes.add(l.id)
    if (!l.settings.muted) listenIds.value.push(l.id)
  }
  listenIds.value = listenIds.value.filter((id) => lanes.some((l) => l.id === id))
}, { immediate: true })
function laneColor(colorId?: string): string {
  return TRACK_COLORS.find((c) => c.id === colorId)?.baseHex ?? '#a855f7'
}
const loopRegion = computed(() => (store.project.loopRegion?.enabled ? store.project.loopRegion : null))
/** The timeline span the model hears, or why there is none. */
const listenSpan = computed<{ start: number; end: number } | { error: string }>(() => {
  if (candidateLanes.value.length === 0) return { error: t('sfx.listenEmpty') }
  const start = loopRegion.value ? loopRegion.value.start : store.playheadSec
  const end = Math.min(start + duration.value, store.totalDuration)
  if (end - start < 0.5) return { error: t('sfx.listenNothing') }
  return { start, end }
})
const listenError = computed(() => {
  if (!listen.value) return null
  if ('error' in listenSpan.value) return listenSpan.value.error
  return listenIds.value.length ? null : t('sfx.listenNeedLanes')
})

// ---- Engine ----
const sa3Status = computed(() => orchestrator.statuses.stable_audio?.status ?? 'stopped')
const sa3Running = computed(() => orchestrator.activeModel === 'stable_audio' && sa3Status.value === 'running')
const engineLabel = MODEL_LABELS.stable_audio
/**
 * Samples on the CPU (Models page): when switched on, the panel sends its jobs to a second sa3-server on the CPU, so
 * the engine on the GPU stays as it is. With route "auto" a Stable Audio already running on the GPU is used instead.
 */
const cpu = computed(() => engines.cpu)
const useCpu = computed(() => !!cpu.value?.settings.enabled && cpu.value.available && (cpu.value.settings.route === 'cpu' || !sa3Running.value))
const cpuStarting = ref(false)
onMounted(() => { void engines.refreshCpu().catch(() => {}) })
/** Checkpoints to offer: what the running engine reports, else what is on the disk (features). */
const modelChoices = computed<{ id: Sa3ModelId; label: string }[]>(() => {
  if (useCpu.value) return (cpu.value?.models ?? []).map((id) => ({ id, label: id }))
  const reported = sa3Store.models.filter((m) => m.available)
  if (reported.length) return reported.map((m) => ({ id: m.id, label: `${m.label} · ${m.params}` }))
  return (features.features.stable_audio_models as Sa3ModelId[]).map((id) => ({ id, label: id }))
})
const modelLoaded = computed(() => sa3Store.models.find((m) => m.id === model.value)?.loaded ?? true)
watch(sa3Running, (running) => { if (running) void sa3Store.refreshModels() }, { immediate: true })
// small-sfx is the sound model; medium does sounds too and stands in when small-sfx is not downloaded.
watch(modelChoices, (list) => {
  if (list.some((m) => m.id === model.value)) return
  model.value = list.find((m) => m.id === 'small-sfx')?.id ?? list.find((m) => m.id === 'medium')?.id ?? list[0]?.id ?? 'medium'
}, { immediate: true })
async function startEngine() {
  try {
    await orchestrator.switchModel('stable_audio')
  } catch {
    // orchestrator.switchError is shown in the header
  }
}

// ---- Generate ----
const canGenerate = computed(() => (sa3Running.value || useCpu.value) && !preparing.value && !!captions.value[kind.value].trim() && modelChoices.value.length > 0 && !listenError.value)
async function generate() {
  formError.value = null
  const caption = captions.value[kind.value].trim()
  if (!caption) {
    formError.value = t('sfx.needCaption')
    return
  }
  if (listenError.value) {
    formError.value = listenError.value
    return
  }
  preparing.value = true
  try {
    let reference = null
    let audio: File | null = null
    if (listen.value && !('error' in listenSpan.value)) {
      const { start, end } = listenSpan.value
      reference = { laneIds: [...listenIds.value], start, end, closeness: closeness.value }
      audio = audioBufferToWavFile(renderContext(store.project, props.buffers, listenIds.value, start, end).buffer, 'reference.wav')
    }
    const device = useCpu.value ? 'cpu' : 'gpu'
    if (device === 'cpu' && cpu.value?.status !== 'running') {
      // the CPU server starts on the first sample (about 10 s) and stops again after a while without use
      cpuStarting.value = true
      try {
        await engines.startCpu()
      } finally {
        cpuStarting.value = false
      }
    }
    await sfxStore.submit({
      kind: kind.value, caption, model: model.value, duration: duration.value, bpm: bpm.value, bars: loopBars.value, count: count.value,
      trimSilence: kind.value === 'oneshot' && trimSilence.value, reference,
    }, store.session, audio, device)
  } catch (e) {
    formError.value = e instanceof Error ? e.message : String(e)
  } finally {
    preparing.value = false
  }
}
function applyExample(ex: { kind: SfxKind; text: string }) {
  kind.value = ex.kind
  captions.value[ex.kind] = ex.text
  helpOpen.value = false
}

// ---- Results ----
const jobs = computed(() => sfxStore.jobs.filter((j) => j.session === store.session))
const peaks = ref<Record<string, number[]>>({})
watch(jobs, (list) => {
  for (const job of list) for (const v of job.variants) {
    if (peaks.value[v.url]) continue
    peaks.value[v.url] = []
    void fetchAndComputePeaks(v.url, 36).then((p) => { peaks.value[v.url] = p }).catch(() => {})
  }
}, { deep: true, immediate: true })

/** One <audio> for the whole strip: a click on another result switches to it. */
const audio = new Audio()
const playingUrl = ref<string | null>(null)
audio.addEventListener('ended', () => { playingUrl.value = null })
audio.addEventListener('pause', () => { if (audio.ended || audio.currentTime === 0) playingUrl.value = null })
function toggle(v: SfxVariant) {
  if (playingUrl.value === v.url) {
    audio.pause()
    playingUrl.value = null
    return
  }
  audio.src = v.url
  claimPlayback(audio)
  playingUrl.value = v.url
  void audio.play().catch(() => { playingUrl.value = null })
}
onBeforeUnmount(() => {
  audio.pause()
  releasePlaybackIfCurrent(audio)
})

const inserting = ref<string | null>(null)
async function insert(job: SfxJob, v: SfxVariant) {
  if (job.session !== store.session) return
  inserting.value = v.url
  try {
    const r = job.request
    let key = v.url
    let buf = props.buffers.get(v.url)
    if (!buf) {
      buf = await decodeStem(v.url)
      props.buffers.set(v.url, buf)
    }
    // A seamed loop is new audio: it goes into the library as its own file, so the project can reload it.
    if (r.kind === 'loop' && seamless.value) {
      const seamed = seamLoop(buf)
      const saved = await tracksApi.saveTrack(
        { model: 'editor', title: `${v.title} ∞`, lyrics: '', duration_ms: Math.round(seamed.duration * 1000), params: { sfx: true, kind: 'loop', caption: r.caption, engine: 'sa3', model: r.model, bpm: r.bpm, bars: r.bars, seamed: true } },
        audioBufferToWavFile(seamed, 'loop.wav'),
        'wav',
      )
      key = saved.audio_url
      buf = seamed
      props.buffers.set(key, buf)
      v.copies.push({ url: key, trackId: saved.id })
    }
    const loop = store.project.loopRegion?.enabled ? store.project.loopRegion : null
    const clip: Clip = {
      id: crypto.randomUUID(),
      type: 'audio',
      sourceUrl: key,
      sourceLabel: v.title,
      timelineStart: loop ? loop.start : store.playheadSec,
      trimStart: 0,
      trimEnd: buf.duration,
      // A loop was made at the project tempo, so W (warp) later follows that; a sound keeps the project's.
      originalBpm: r.kind === 'loop' ? r.bpm : bpm.value,
      ...(r.kind === 'oneshot' ? { fadeInDuration: 0.005, fadeOutDuration: 0.005 } : {}),
    }
    const selected = store.project.lanes.find((l) => l.id === store.selectedLaneId)
    if (target.value === 'selected' && selected) {
      store.addClip(selected.id, clip)
    } else {
      store.insertLanes([{ name: v.title, colorId: r.kind === 'loop' ? 'cyan' : 'slate', clips: [clip] }])
    }
    v.used = true
  } catch (e) {
    formError.value = e instanceof Error ? e.message : String(e)
  } finally {
    inserting.value = null
  }
}
/** Dismisses the job; its files are deleted unless a clip on a lane still plays them. */
function dismiss(job: SfxJob) {
  const onLanes = new Set<string>()
  for (const lane of store.project.lanes) for (const c of lane.clips) if (c.sourceUrl) onLanes.add(c.sourceUrl)
  void sfxStore.removeJob(job.id, onLanes)
}
function statusKey(job: SfxJob): string {
  return job.status === 'saving' ? 'sfx.saving' : `jobStatus.${job.status}`
}
</script>

<template>
  <section
    class="flex flex-col gap-2.5 rounded-xl border border-border/60 bg-panel/70 p-3 shadow-sm backdrop-blur-md"
    :class="props.dock === 'right' ? 'shrink-0' : 'lg:max-h-[48svh] lg:min-h-[8rem] lg:overflow-y-auto'"
    :aria-label="t('sfx.title')"
  >
    <!-- Top row: the grip, the title, the kind, the hint, variants, the action, close. The comment sits inside
         <section> so the component stays single-root (v-show needs it). -->
    <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div class="flex items-center gap-1">
        <slot name="handle" />
        <h2 class="flex items-center gap-1.5 text-sm font-semibold text-text"><SampleIcon class="h-4 w-4 shrink-0 text-accent1" />{{ t('sfx.title') }}</h2>
        <HelpIconButton class="ml-0.5" @click="helpOpen = true" />
      </div>
      <div class="rounded-lg border border-border bg-panel-2 p-0.5" :class="narrow ? 'order-2 flex w-full' : 'inline-flex'" role="group" :aria-label="t('sfx.kindLabel')">
        <button
          v-for="o in kindOptions"
          :key="o.value"
          type="button"
          class="rounded-md py-1 transition-colors"
          :class="[narrow ? 'flex-auto px-2 text-xs' : 'px-3 text-sm', kind === o.value ? 'accent-gradient text-white shadow-sm' : 'text-text-dim hover:text-text']"
          :aria-pressed="kind === o.value"
          @click="kind = o.value"
        >
          {{ o.label }}
        </button>
      </div>
      <p class="min-w-[12rem] flex-1 text-xs text-text-dim" :class="narrow && 'order-3 basis-full'">{{ t(`sfx.kindHints.${kind}`) }}</p>
      <div class="flex items-center gap-2" :class="narrow && 'order-4'">
        <span class="text-[13px] font-medium text-text">{{ t('sfx.variants') }}</span>
        <ChipGroup v-model="count" small :options="countOptions" />
      </div>
      <button
        type="button"
        class="accent-gradient flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-sm font-medium text-white shadow-md shadow-accent1/20 transition-all hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:hover:scale-100"
        :class="narrow && 'order-5'"
        :disabled="!canGenerate"
        @click="generate"
      >
        <SampleIcon class="h-4 w-4 shrink-0" />
        {{ preparing ? t('sfx.generating') : t('sfx.generate') }}
      </button>
      <button type="button" class="rounded-lg border border-border px-2 py-1 text-xs text-text-dim hover:bg-panel-2" :class="narrow && 'order-1 ml-auto'" :aria-label="t('sfx.close')" @click="emit('close')">✕</button>
    </div>
    <p v-if="sa3Running && !useCpu && !modelLoaded" class="-mt-1 text-right text-[11px] text-text-dim">{{ t('sfx.firstLoadNote') }}</p>
    <p v-if="formError" class="rounded-lg bg-status-failed/10 p-2 text-xs text-status-failed">{{ formError }}</p>

    <!-- On the CPU: the GPU engine stays as it is -->
    <p v-if="useCpu" class="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border bg-panel-2 px-3 py-2 text-xs text-text-dim">
      <span v-if="cpuStarting || cpu?.status === 'starting'" class="inline-flex items-center gap-2">
        <span class="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent1 border-t-transparent"></span>{{ t('sfx.cpuStarting') }}
      </span>
      <span v-else>{{ t(orchestrator.activeModel && orchestrator.activeModel !== 'stable_audio' ? 'sfx.cpuOnBeside' : 'sfx.cpuOn', { running: orchestrator.activeModel ? MODEL_LABELS[orchestrator.activeModel] : '' }) }}</span>
      <RouterLink to="/models#samples-cpu" class="text-accent1 underline">{{ t('sfx.cpuSettings') }}</RouterLink>
    </p>

    <!-- Stable Audio 3 must be running (starting it stops the other engine) -->
    <div v-else-if="!sa3Running" class="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-panel-2 p-3 text-sm">
      <p v-if="sa3Status === 'starting'" class="flex items-center gap-2 text-text-dim">
        <span class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-accent1 border-t-transparent"></span>
        {{ t('aiPart.engineStarting', { engine: engineLabel }) }}
      </p>
      <template v-else-if="!features.has('stableAudio')">
        <p class="text-text-dim">{{ t(features.features.stable_audio_env ? 'sfx.needWeights' : 'notInstalled.stableAudio.text') }}</p>
        <RouterLink v-if="features.features.stable_audio_env" to="/stable-audio" class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-text hover:border-accent1">{{ t('sfx.openWeights') }}</RouterLink>
      </template>
      <template v-else>
        <p class="text-text-dim">{{ t('sfx.offline') }}</p>
        <button type="button" class="accent-gradient rounded-lg px-3 py-1.5 text-xs font-medium text-white" :disabled="orchestrator.switching" @click="startEngine">{{ t('aiPart.startEngine', { engine: engineLabel }) }}</button>
        <span v-if="orchestrator.activeModel && orchestrator.activeModel !== 'stable_audio'" class="text-[11px] text-text-dim">{{ t('aiPart.engineSwitchNote', { running: MODEL_LABELS[orchestrator.activeModel] }) }}</span>
        <RouterLink v-if="cpu?.available" to="/models#samples-cpu" class="basis-full text-[11px] text-accent1 underline">{{ t('sfx.cpuOffer') }}</RouterLink>
      </template>
    </div>

    <!-- The form: what the sound is, how long, which model, where it goes -->
    <div class="flex flex-wrap items-start gap-x-6 gap-y-3">
      <div class="flex min-w-[16rem] flex-[1.4] flex-col gap-1">
        <label for="sfx-caption" class="text-[13px] font-medium text-text">{{ t('sfx.caption') }}</label>
        <textarea id="sfx-caption" v-model="captions[kind]" rows="2" class="w-full rounded-lg border border-border bg-panel-2 p-2 text-sm text-text" :placeholder="PLACEHOLDERS[kind]"></textarea>
        <span class="text-[11px] text-text-dim">{{ t('sfx.captionHint') }}</span>
      </div>

      <div class="flex min-w-[12rem] flex-1 flex-col gap-2.5">
        <div v-if="kind === 'oneshot'" class="flex flex-col gap-1">
          <label class="flex flex-col gap-1">
            <span class="text-[13px] font-medium text-text">{{ t('sfx.length', { v: fmtSec(oneshotSec) }) }}</span>
            <input v-model.number="oneshotSec" type="range" min="0.5" max="5" step="0.5" class="w-full accent-accent1" />
          </label>
          <label class="flex items-center gap-1.5 text-xs text-text" :title="t('sfx.trimSilenceHint')">
            <input v-model="trimSilence" type="checkbox" class="rounded border-border" />
            {{ t('sfx.trimSilence') }}
          </label>
        </div>
        <div v-else-if="kind === 'loop'" class="flex flex-col gap-1">
          <span class="text-[13px] font-medium text-text">{{ t('sfx.bars', { v: fmtSec(duration) }) }}</span>
          <ChipGroup v-model="loopBars" small :options="barOptions" />
          <label class="flex items-center gap-1.5 text-xs text-text" :title="t('sfx.seamlessHint')">
            <input v-model="seamless" type="checkbox" class="rounded border-border" />
            {{ t('sfx.seamless') }}
          </label>
          <span class="text-[11px] text-text-dim">{{ t('sfx.loopCaveat', { bpm }) }}</span>
        </div>
        <label v-else class="flex flex-col gap-1">
          <span class="text-[13px] font-medium text-text">{{ t('sfx.length', { v: fmtSec(textureSec) }) }}</span>
          <input v-model.number="textureSec" type="range" min="5" max="30" step="1" class="w-full accent-accent1" />
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-[13px] font-medium text-text">{{ t('sfx.model') }}</span>
          <select v-model="model" class="rounded-lg border border-border bg-panel-2 px-2 py-1.5 text-sm text-text" :disabled="modelChoices.length === 0">
            <option v-for="m in modelChoices" :key="m.id" :value="m.id">{{ m.label }}</option>
          </select>
        </label>
      </div>

      <div class="flex min-w-[12rem] flex-1 flex-col gap-1">
        <span class="text-[13px] font-medium text-text">{{ t('sfx.target') }}</span>
        <div class="inline-flex self-start rounded-lg border border-border bg-panel-2 p-0.5" role="group" :aria-label="t('sfx.target')">
          <button type="button" class="rounded-md px-2.5 py-1 text-xs transition-colors" :class="target === 'new' ? 'bg-panel text-text shadow-sm ring-1 ring-border' : 'text-text-dim hover:text-text'" :aria-pressed="target === 'new'" @click="target = 'new'">{{ t('sfx.targetNew') }}</button>
          <button type="button" class="rounded-md px-2.5 py-1 text-xs transition-colors" :class="target === 'selected' ? 'bg-panel text-text shadow-sm ring-1 ring-border' : 'text-text-dim hover:text-text'" :aria-pressed="target === 'selected'" @click="target = 'selected'">{{ t('sfx.targetSelected') }}</button>
        </div>
        <span class="text-[11px] text-text-dim">{{ t('sfx.targetHint') }}</span>
      </div>

      <!-- What the model hears from the timeline (audio-to-audio) -->
      <div class="flex min-w-[14rem] flex-1 flex-col gap-1.5">
        <label class="flex items-center gap-1.5 text-[13px] font-medium text-text" :title="t('sfx.listenHint')">
          <input v-model="listen" type="checkbox" class="rounded border-border" :disabled="candidateLanes.length === 0" />
          {{ t('sfx.listen') }}
        </label>
        <p v-if="candidateLanes.length === 0" class="text-[11px] text-text-dim">{{ t('sfx.listenEmpty') }}</p>
        <template v-else-if="listen">
          <!-- lanes as toggles in their own colours: a filled dot is heard, a hollow one is not -->
          <div class="flex max-h-20 flex-wrap gap-1.5 overflow-y-auto" role="group" :aria-label="t('sfx.listen')">
            <label
              v-for="lane in candidateLanes"
              :key="lane.id"
              class="flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent1"
              :class="listenIds.includes(lane.id) ? 'border-text-dim/50 bg-panel-2 text-text' : 'border-border/60 text-text-dim hover:text-text'"
            >
              <input v-model="listenIds" type="checkbox" :value="lane.id" class="sr-only" />
              <span
                class="h-2 w-2 shrink-0 rounded-full border"
                :style="{ borderColor: laneColor(lane.colorId), backgroundColor: listenIds.includes(lane.id) ? laneColor(lane.colorId) : 'transparent' }"
                aria-hidden="true"
              ></span>
              <span class="max-w-[10rem] truncate" :title="lane.name">{{ laneLabels[lane.id] }}</span>
            </label>
          </div>
          <p class="text-[11px]" :class="'error' in listenSpan ? 'text-status-failed' : 'text-text-dim'">
            {{ 'error' in listenSpan ? listenSpan.error : t('sfx.listenRange', { range: `${fmtPos(listenSpan.start)}–${fmtPos(listenSpan.end)}` }) }}
          </p>
          <label class="flex flex-col gap-1" :title="t('sfx.closenessHint')">
            <span class="text-xs text-text">{{ t('sfx.closeness', { v: Math.round(closeness * 100) }) }}</span>
            <input v-model.number="closeness" type="range" min="0.1" max="0.9" step="0.05" class="w-full accent-accent1" />
            <span class="flex justify-between text-[10px] text-text-dim"><span>{{ t('sfx.closenessLoose') }}</span><span>{{ t('sfx.closenessClose') }}</span></span>
          </label>
        </template>
        <p v-else class="text-[11px] text-text-dim">{{ t('sfx.listenHint') }}</p>
      </div>
    </div>

    <!-- Results, newest first: audition, then place. Cards fill the width and wrap; in the right dock they stack. -->
    <div v-if="jobs.length" class="grid gap-3" :class="narrow ? 'grid-cols-1' : 'grid-cols-[repeat(auto-fill,minmax(22rem,1fr))]'">
      <article v-for="job in jobs" :key="job.id" class="flex min-w-0 flex-col gap-2 rounded-lg border border-border/60 bg-panel-2/60 p-2.5 text-xs">
        <div class="flex items-center gap-2">
          <span class="h-2 w-2 shrink-0 rounded-full" :class="job.request.kind === 'loop' ? 'bg-cyan-400' : 'bg-slate-400'" aria-hidden="true"></span>
          <p class="min-w-0 flex-1 truncate font-medium text-text" :title="job.request.caption">{{ t(`sfx.kinds.${job.request.kind}`) }} · {{ job.request.caption }}</p>
          <span v-if="job.request.reference" class="shrink-0 rounded border border-accent1/40 px-1 text-[10px] text-accent1" :title="t('sfx.listenRange', { range: `${fmtPos(job.request.reference.start)}–${fmtPos(job.request.reference.end)}` })">{{ t('sfx.byTracks') }}</span>
          <span class="shrink-0 text-text-dim">{{ fmtSec(job.request.duration) }}</span>
          <button v-if="job.status === 'queued' || job.status === 'running'" type="button" class="shrink-0 text-text-dim hover:text-status-failed" @click="sfxStore.cancel(job.id)">{{ t('aiPart.cancel') }}</button>
          <button v-else type="button" class="shrink-0 text-text-dim hover:text-text" :title="t('sfx.dismissTitle')" @click="dismiss(job)">{{ t('aiPart.dismiss') }}</button>
        </div>
        <div v-if="job.status === 'queued' || job.status === 'running' || job.status === 'saving'" class="space-y-1">
          <div class="h-1.5 w-full overflow-hidden rounded-full bg-panel">
            <div class="h-full accent-gradient transition-[width]" :class="job.status === 'queued' && 'w-1/5 animate-pulse'" :style="job.status !== 'queued' ? { width: `${Math.max(5, job.progress)}%` } : undefined"></div>
          </div>
          <p class="text-text-dim">{{ t(statusKey(job)) }}</p>
        </div>
        <p v-else-if="job.status === 'failed'" class="rounded bg-status-failed/10 p-1.5 text-status-failed">{{ job.error }}</p>
        <p v-else-if="job.status === 'cancelled'" class="text-text-dim">{{ t('aceJob.cancelled') }}</p>
        <ul v-else class="flex flex-col gap-1.5">
          <li v-for="v in job.variants" :key="v.url" class="flex items-center gap-2">
            <button type="button" class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-border text-text hover:border-accent1" :aria-label="playingUrl === v.url ? t('sfx.pause') : t('sfx.play')" @click="toggle(v)">
              <PauseIcon v-if="playingUrl === v.url" class="h-3 w-3" />
              <PlayIcon v-else class="h-3 w-3" />
            </button>
            <!-- a tiny waveform: enough to tell a hit from a wash -->
            <span class="flex h-6 min-w-0 flex-1 items-end gap-px" aria-hidden="true">
              <span v-for="(p, i) in (peaks[v.url] || [])" :key="i" class="w-full rounded-sm bg-text-dim/70" :style="{ height: `${Math.max(8, p * 100)}%` }"></span>
            </span>
            <span class="w-10 shrink-0 text-right tabular-nums text-text-dim">{{ v.durationSec != null ? fmtSec(v.durationSec) : '' }}</span>
            <button
              type="button"
              class="flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 font-medium transition-colors disabled:opacity-50"
              :class="v.used ? 'border-border text-text-dim' : 'border-accent1/50 text-accent1 hover:bg-accent1/10'"
              :disabled="inserting === v.url"
              @click="insert(job, v)"
            >
              <PlusIcon class="h-3 w-3" />
              {{ v.used ? t('sfx.addAgain') : t('sfx.add') }}
            </button>
          </li>
        </ul>
      </article>
    </div>

    <!-- The help window, in the editor guide's look -->
    <HelpModal :open="helpOpen" :title="t('sfx.help.title')" wide @close="helpOpen = false">
      <HelpBody :lead="t('sfx.help.intro')">
        <HelpSection :title="t('sfx.help.tipsTitle')" tone="tips">
          <HelpList :items="tm('sfx.help.tips') as string[]" />
        </HelpSection>
        <HelpSection :title="t('sfx.help.examplesTitle')">
          <HelpExamples
            :items="(tm('sfx.help.examples') as { kind: SfxKind; text: string }[]).map((x) => ({ label: t(`sfx.kinds.${x.kind}`), text: x.text }))"
            pickable
            @pick="(i) => applyExample((tm('sfx.help.examples') as { kind: SfxKind; text: string }[])[i])"
          />
        </HelpSection>
      </HelpBody>
    </HelpModal>
  </section>
</template>
