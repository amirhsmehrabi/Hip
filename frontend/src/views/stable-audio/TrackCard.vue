<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStableAudioStore } from '../../stores/stableAudio'
import type { Sa3Job } from '../../stores/stableAudio'
import { formatClock, formatCreated } from '../../composables/formatCreated'
import StatusBadge from '../../components/shared/StatusBadge.vue'
import WaveformPlayer from '../../components/shared/WaveformPlayer.vue'
import StemsPanel from '../../components/shared/StemsPanel.vue'
import EditableTitle from '../../components/shared/EditableTitle.vue'
import { friendlyTitle } from '../../utils/trackTitle'
import StyleChips from '../../components/shared/StyleChips.vue'
import CardMenu from '../../components/shared/CardMenu.vue'
import type { MenuItem } from '../../components/shared/CardMenu.vue'
import DownloadIcon from '../../components/shared/icons/DownloadIcon.vue'
import ChevronIcon from '../../components/shared/icons/ChevronIcon.vue'
import ReuseIcon from '../../components/shared/icons/ReuseIcon.vue'
import TrashIcon from '../../components/shared/icons/TrashIcon.vue'
import { downloadSavedTrack } from '../../composables/useTrackDownload'
import TrackDetails from '../../components/shared/TrackDetails.vue'

const props = defineProps<{ job: Sa3Job }>()
const store = useStableAudioStore()
const { t } = useI18n()
const expanded = ref(false)

const shortTitle = computed(() => friendlyTitle(props.job.title))
const created = computed(() => formatCreated(props.job.createdAt))
const inProgress = computed(() => props.job.status === 'queued' || props.job.status === 'running')
const menuItems = computed<MenuItem[]>(() => {
  const items: MenuItem[] = []
  if (props.job.status === 'done') items.push({ key: 'reuse', label: t('trackCard.reuse') })
  items.push({ key: 'delete', label: t('trackCard.deleteTrack'), danger: true, confirmLabel: t('trackCard.confirmDelete') })
  return items
})

function cancel() {
  void store.cancel(props.job.id)
}
async function remove() {
  await store.deleteJob(props.job)
}
// Deleting takes two clicks on the same button: the first one arms it for a few seconds.
const deleteArmed = ref(false)
let disarmTimer: ReturnType<typeof setTimeout> | null = null
function disarmDelete() {
  deleteArmed.value = false
  if (disarmTimer) clearTimeout(disarmTimer)
  disarmTimer = null
}
function onDeleteClick() {
  if (deleteArmed.value) {
    disarmDelete()
    void remove()
    return
  }
  deleteArmed.value = true
  disarmTimer = setTimeout(disarmDelete, 4000)
}
onBeforeUnmount(disarmDelete)
function onMenu(key: string) {
  if (key === 'reuse') copyParamsToForm()
  else if (key === 'delete') void remove()
}
function download() {
  if (!props.job.audioUrl) return
  const name = props.job.savedFilename || `stable_audio_${props.job.seed ?? 'x'}.wav`
  if (props.job.dbId != null) {
    void downloadSavedTrack(props.job.dbId, name)
    return
  }
  const a = document.createElement('a')
  a.href = props.job.audioUrl
  a.download = name
  a.click()
}
function copyParamsToForm() {
  const p = props.job.params
  store.requestInsertParams({
    kind: props.job.kind,
    model: props.job.model,
    prompt: props.job.prompt,
    negativePrompt: (p.negative_prompt as string) || '',
    duration: typeof p.duration === 'number' ? p.duration : undefined,
    steps: typeof p.steps === 'number' ? p.steps : undefined,
    cfgScale: typeof p.cfg_scale === 'number' ? p.cfg_scale : undefined,
    seed: props.job.seed ?? -1,
  })
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
</script>

<template>
  <article class="@container relative overflow-hidden rounded-xl border border-border bg-panel p-3">
    <header class="flex items-start">
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <EditableTitle
            class="min-w-0 flex-1"
            :model-value="job.title"
            :display-text="shortTitle"
            :placeholder="t('sa3Track.untitled')"
            :editable="job.dbId != null"
            @rename="(title) => store.renameJob(job, title)"
          />
          <div class="ms-auto flex shrink-0 items-center gap-1">
            <div v-if="job.status === 'done' && job.durationSec" class="me-1 hidden border-e border-border/60 pe-3 text-end @min-[640px]:block">
              <p class="text-sm font-semibold tabular-nums text-text" :title="`${Math.round(job.durationSec)} ${t('common.secondsUnit')}`">{{ formatClock(job.durationSec) }}</p>
            </div>
            <StatusBadge v-if="job.status !== 'done'" :status="job.status" class="me-1" />
            <button
              v-if="job.status === 'done' && job.audioUrl"
              type="button"
              class="flex h-8 w-8 items-center justify-center rounded-lg text-text-dim hover:bg-panel-2 hover:text-text"
              :aria-label="t('trackCard.downloadTagged')"
              :title="t('trackCard.downloadTagged')"
              @click="download"
            >
              <DownloadIcon class="h-4 w-4" />
            </button>
            <button v-if="inProgress" type="button" class="flex h-8 w-8 items-center justify-center rounded-lg text-text-dim hover:bg-panel-2 hover:text-status-failed" :title="t('aceJob.cancel')" :aria-label="t('aceJob.cancel')" @click="cancel">⏹</button>
            <button
              v-if="job.status === 'done'"
              type="button"
              class="hidden h-8 w-8 items-center justify-center rounded-lg text-text-dim hover:bg-panel-2 hover:text-text @min-[640px]:flex"
              :aria-label="t('trackCard.reuse')"
              :title="t('trackCard.reuse')"
              @click="copyParamsToForm"
            >
              <ReuseIcon class="h-4 w-4" />
            </button>
            <button
              v-if="!inProgress"
              type="button"
              class="hidden h-8 items-center justify-center rounded-lg @min-[640px]:flex"
              :class="deleteArmed ? 'bg-status-failed/15 px-2 text-xs font-medium text-status-failed' : 'w-8 text-text-dim hover:bg-panel-2 hover:text-status-failed'"
              :aria-label="deleteArmed ? t('trackCard.confirmDelete') : t('trackCard.deleteTrack')"
              :title="deleteArmed ? t('trackCard.confirmDelete') : t('trackCard.deleteTrack')"
              @click="onDeleteClick"
              @blur="disarmDelete"
            >
              <template v-if="deleteArmed">{{ t('trackCard.deleteShort') }}</template>
              <TrashIcon v-else class="h-4 w-4" />
            </button>
            <CardMenu v-if="!inProgress" class="@min-[640px]:hidden" :items="menuItems" :label="t('trackCard.moreActions')" @select="onMenu" />
            <button
              v-if="job.status === 'done'"
              type="button"
              class="flex h-8 w-8 items-center justify-center rounded-lg text-text-dim hover:bg-panel-2 hover:text-text"
              :aria-expanded="expanded"
              :aria-label="expanded ? t('trackCard.collapse') : t('trackCard.expand')"
              :title="expanded ? t('trackCard.collapse') : t('trackCard.expand')"
              @click="expanded = !expanded"
            >
              <ChevronIcon class="h-4 w-4 transition-transform" :class="expanded ? 'rotate-180' : ''" />
            </button>
          </div>
        </div>
        <div class="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
          <span class="rounded-md border border-border px-1.5 py-px text-xs font-medium leading-4 text-text-dim">Stable Audio 3 · {{ job.model }}</span>
          <span class="rounded-md border border-border px-1.5 py-px text-xs font-medium leading-4 text-text-dim">{{ t(`sa3Gen.kinds.${job.kind}`) }}</span>
          <!-- made from a reference track: which way, and from what -->
          <span v-if="job.params.ref_mode" class="rounded-md border border-accent1/40 px-1.5 py-px text-xs font-medium leading-4 text-accent1" :title="String(job.params.ref_name || '')">{{ t(`sa3Gen.ref.modes.${job.params.ref_mode}`) }}</span>
          <span class="text-xs text-text-dim" :title="created.full">{{ created.label }}</span>
          <span v-if="job.prompt" class="h-3.5 w-px bg-border" aria-hidden="true"></span>
          <StyleChips class="min-w-0" :max="4" :text="job.prompt" @more="expanded = true" />
        </div>

        <div v-if="inProgress" class="mt-2 space-y-1">
          <div class="h-2 w-full overflow-hidden rounded-full bg-panel-2">
            <div class="h-full accent-gradient transition-[width]" :class="job.status === 'queued' && 'w-1/5 animate-pulse'" :style="job.status === 'running' ? { width: `${Math.max(5, job.progress)}%` } : undefined"></div>
          </div>
          <p class="text-xs text-text-dim">{{ job.status === 'queued' ? t('jobStatus.queued') : t('sa3Track.progress', { pct: job.progress }) }}</p>
        </div>
        <div v-else-if="job.status === 'failed'" class="mt-2 rounded-lg bg-status-failed/10 p-2 text-xs text-status-failed">{{ job.error }}</div>
        <div v-else-if="job.status === 'cancelled'" class="mt-2 rounded-lg bg-panel-2 p-2 text-xs text-text-dim">{{ t('aceJob.cancelled') }}</div>
        <template v-else-if="job.status === 'done' && job.audioUrl">
          <WaveformPlayer class="mt-2" :src="job.audioUrl" :duration-hint="job.durationSec" total-class="@min-[640px]:hidden" />
          <p v-if="job.saveError && job.dbId == null" class="mt-1.5 text-xs text-status-failed" :title="job.saveError">{{ t('sa3Track.notSaved') }}</p>
        </template>
      </div>
    </header>

    <div v-if="expanded && job.status === 'done' && job.audioUrl" class="mt-3 space-y-3 border-t border-border/60 pt-3">
      <TrackDetails v-if="job.prompt" :style-text="job.prompt" />
      <StemsPanel v-if="job.dbId != null" :track-id="job.dbId" :title="job.title" lyrics="" model="stable_audio" />
      <p class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-dim">
        <span v-if="job.seed != null">{{ t('trackCard.seed') }} <span class="tabular-nums text-text">{{ job.seed }}</span></span>
        <span v-if="job.wallSec">{{ t('trackCard.generation') }} <span class="tabular-nums text-text">{{ job.wallSec.toFixed(1) }} {{ t('trackCard.secondsShort') }}</span></span>
        <span v-if="job.savedFilename" class="break-all">{{ t('trackCard.file') }} <span class="text-text">{{ job.savedFilename }}</span></span>
      </p>
      <button
        type="button"
        class="flex w-full items-center justify-center gap-1.5 rounded-lg border-t border-border/60 py-2 text-xs text-text-dim hover:bg-panel-2 hover:text-text"
        @click="expanded = false"
      >
        <ChevronIcon class="h-3.5 w-3.5 rotate-180" />
        {{ t('trackCard.collapse') }}
      </button>
    </div>
  </article>
</template>
