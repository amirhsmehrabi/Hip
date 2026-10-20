<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useOrchestratorStore } from '../../stores/orchestrator'
import { useFeaturesStore } from '../../stores/features'
import { MODEL_FEATURE, MODEL_LABELS, MODEL_ROUTES, useModelSwitch } from '../../composables/useModelSwitch'
import { setLocale, currentLocale, type LocaleCode } from '../../i18n'
import type { ModelId, ModelRuntimeStatus } from '../../types'
import AppHelpModal from './AppHelpModal.vue'
import EditorHelpModal from '../editor/EditorHelpModal.vue'
import EditorHotkeysModal from '../editor/EditorHotkeysModal.vue'
import AiArrangerGuide from '../editor/AiArrangerGuide.vue'
import ResourceMeters from './ResourceMeters.vue'
import MicIcon from './icons/MicIcon.vue'
import TimelineIcon from './icons/TimelineIcon.vue'
import WaveIcon from './icons/WaveIcon.vue'
import PulseIcon from './icons/PulseIcon.vue'
import SparklesIcon from './icons/SparklesIcon.vue'

const orchestrator = useOrchestratorStore()
const features = useFeaturesStore()
const route = useRoute()
const onEditor = computed(() => route.path.startsWith('/editor'))
const onIdea = computed(() => route.name === 'idea')
const { selectModel } = useModelSwitch()
const { t, locale } = useI18n()
const helpOpen = ref(false)
/** A guide opened from the help: the editor's, its shortcut sheet, or the AI arranger's. */
const guide = ref<'editor' | 'hotkeys' | 'arranger' | null>(null)
function openGuide(which: 'editor' | 'arranger') {
  helpOpen.value = false
  guide.value = which
}

function toggleLocale() {
  const next: LocaleCode = currentLocale() === 'ru' ? 'en' : 'ru'
  setLocale(next)
  locale.value = next
}

// The header's height (it wraps on a phone) as --header-h, so sticky bars below it know where to stop.
const headerEl = ref<HTMLElement | null>(null)
let observer: ResizeObserver | null = null
onMounted(() => {
  if (!headerEl.value || typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver(() => {
    document.documentElement.style.setProperty('--header-h', `${headerEl.value?.offsetHeight ?? 0}px`)
    updateNavMore()
  })
  observer.observe(headerEl.value)
  showCurrentTab()
})
onUnmounted(() => observer?.disconnect())

// On a narrow window the tabs scroll sideways: the right edge fades while more tabs hide past it, and the
// current section's tab is scrolled into view.
const navEl = ref<HTMLElement | null>(null)
const navMore = ref(false)
function updateNavMore() {
  const nav = navEl.value
  navMore.value = !!nav && nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 4
}
async function showCurrentTab() {
  await nextTick()
  navEl.value?.querySelector('[aria-current="page"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  updateNavMore()
}
watch(() => route.path, showCurrentTab)

function statusOf(id: ModelId): ModelRuntimeStatus {
  return orchestrator.statuses[id]?.status ?? 'stopped'
}

/** The status lights: a lit green dot runs, a hollow ring is stopped, amber pulses while it changes. */
const LED_CLASSES: Record<ModelRuntimeStatus, string> = {
  stopped: 'border border-text-dim/70',
  starting: 'bg-status-queued animate-pulse',
  running: 'bg-status-done shadow-[0_0_6px_var(--color-status-done)]',
  stopping: 'bg-status-queued animate-pulse',
  error: 'bg-status-failed shadow-[0_0_6px_var(--color-status-failed)]',
}
/** One engine runs on the GPU at a time, so the running one is named; a stopped one keeps just its hollow light. */
function statusShown(id: ModelId): boolean {
  return statusOf(id) !== 'stopped'
}
/** Left out at install (or, for Stable Audio, its weights not fetched yet): no light, it cannot run. */
function installed(id: ModelId): boolean {
  const feature = MODEL_FEATURE[id]
  return !feature || features.has(feature)
}
/** The engines, one group in the header: one of them holds the GPU at a time. */
const ENGINES: { id: ModelId; icon: typeof MicIcon }[] = [
  { id: 'ace_step', icon: WaveIcon },
  { id: 'yue2', icon: MicIcon },
  { id: 'stable_audio', icon: PulseIcon },
]
/** An engine's tab is current on its page and on the pages under it (ACE-Step's LoRA training). */
function onEngine(id: ModelId): boolean {
  return route.name === MODEL_ROUTES[id] || (id === 'ace_step' && route.name === 'ace-step-lora')
}
const STATUS_TEXT_CLASSES: Record<ModelRuntimeStatus, string> = {
  stopped: 'text-text-dim',
  starting: 'text-status-queued',
  running: 'text-status-done',
  stopping: 'text-status-queued',
  error: 'text-status-failed',
}
const DESC_KEYS: Record<ModelId, string> = { ace_step: 'header.desc.ace', yue2: 'header.desc.yue', stable_audio: 'header.desc.sa3' }
/** The tab's tooltip: what the engine is for, its state, and, unless it runs, that a click starts it. */
function engineTitle(id: ModelId): string {
  if (!installed(id)) return t(`notInstalled.${MODEL_FEATURE[id]}.title`)
  const title = t('header.engineTitle', { model: MODEL_LABELS[id], desc: t(DESC_KEYS[id]), status: t(STATUS_LABEL_KEYS[statusOf(id)]) })
  return statusOf(id) === 'running' ? title : `${title}
${t('header.engineStart')}`
}

const STATUS_LABEL_KEYS: Record<ModelRuntimeStatus, string> = {
  stopped: 'modelStatus.stopped',
  starting: 'modelStatus.starting',
  running: 'modelStatus.running',
  stopping: 'modelStatus.stopping',
  error: 'modelStatus.error',
}

async function onSelect(id: ModelId) {
  try {
    await selectModel(id)
  } catch {
    // orchestrator.switchError already holds the message, rendered below.
  }
}
</script>

<template>
  <header ref="headerEl" class="sticky top-0 z-40 border-b border-border bg-bg/90 backdrop-blur">
    <!-- One row over the whole window: the brand, the sections centred on the window, the tools. As the window
         narrows, things drop out in order (the tagline, the memory numbers, the brand name; below 1280 px the memory
         meters turn into two rings) rather than wrapping. On a phone the tabs get a row of their own and scroll sideways. -->
    <div class="flex flex-wrap items-stretch gap-x-4 px-4 sm:h-[4.75rem] sm:flex-nowrap sm:px-6 lg:grid lg:grid-cols-[1fr_auto_1fr] lg:gap-4 xl:gap-6">
      <!-- the mark is as tall as the two lines next to it (24 + 16 px); the R is drawn, not set in a
           font - an SVG <text> falls back to a different face and looks uneven -->
      <router-link to="/" class="flex h-14 shrink-0 items-center gap-2.5 self-center justify-self-start text-text sm:h-auto">
        <span class="accent-gradient flex h-10 w-10 shrink-0 items-center justify-center rounded-xl shadow-md shadow-accent1/20">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="white" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M7 19V5h5.5a3.75 3.75 0 0 1 0 7.5H7M12.5 12.5 17 19" />
          </svg>
        </span>
        <span class="hidden flex-col min-[1440px]:flex">
          <span class="text-lg leading-6 font-semibold">Remiqora</span>
          <!-- 12px, not 10: at 10px grey on dark Windows' smoothing made it look blurred -->
          <span class="hidden text-xs leading-4 font-medium tracking-wide whitespace-nowrap text-text/70 min-[1680px]:block">{{ t('header.tagline') }}</span>
        </span>
      </router-link>

      <!-- The sections: the idea, the engines as one group, the editor. The current page is underlined (the idea,
           the editor) or raised in the group (an engine). LoRA training is a tab inside ACE-Step's page. -->
      <nav
        ref="navEl"
        class="order-last flex h-12 min-w-0 basis-full items-stretch overflow-x-auto [scrollbar-width:none] sm:order-none sm:h-auto sm:basis-auto [&::-webkit-scrollbar]:hidden"
        :class="navMore && '[mask-image:linear-gradient(to_right,#000_calc(100%-3rem),transparent)]'"
        :aria-label="t('header.navLabel')"
        @scroll.passive="updateNavMore"
      >
        <!-- the simplest way in comes first: an idea in words, the prompt is written for whichever engine -->
        <router-link
          to="/idea"
          class="relative flex shrink-0 items-center gap-2 px-2 transition-colors xl:px-3"
          :class="onIdea ? 'text-text' : 'text-text-dim hover:text-text'"
          :title="t('header.desc.idea')"
          :aria-current="onIdea ? 'page' : undefined"
        >
          <SparklesIcon class="h-[18px] w-[18px] shrink-0" :class="onIdea && 'text-accent1'" />
          <span class="text-[15px] leading-5 whitespace-nowrap" :class="onIdea ? 'font-semibold' : 'font-medium'">{{ t('header.idea') }}</span>
          <span v-if="onIdea" class="accent-gradient absolute inset-x-2 bottom-0 h-0.5 rounded-full xl:inset-x-3" aria-hidden="true"></span>
        </router-link>

        <!-- the engines as one group: a light tells whether each runs, a click opens its page and starts it on the
             GPU (the running one stops). What each is for and its state are in the tooltip. -->
        <div role="group" :aria-label="t('header.engines')" class="mx-1 flex shrink-0 items-center gap-0.5 self-center rounded-xl border border-border bg-panel-2/40 p-1">
          <button
            v-for="engine in ENGINES"
            :key="engine.id"
            type="button"
            class="flex h-9 items-center gap-2 rounded-lg px-2 text-left transition-colors xl:px-3"
            :class="onEngine(engine.id) ? 'bg-panel text-text shadow-sm shadow-black/20' : 'text-text-dim hover:bg-panel/60 hover:text-text'"
            :title="engineTitle(engine.id)"
            :aria-current="onEngine(engine.id) ? 'page' : undefined"
            @click="onSelect(engine.id)"
          >
            <component :is="engine.icon" class="h-[17px] w-[17px] shrink-0" :class="onEngine(engine.id) && 'text-accent1'" />
            <span class="text-[14px] leading-5 whitespace-nowrap" :class="onEngine(engine.id) ? 'font-semibold' : 'font-medium'">{{ MODEL_LABELS[engine.id] }}</span>
            <!-- left out at install: no light, it cannot run -->
            <span v-if="installed(engine.id)" class="h-2 w-2 shrink-0 rounded-full" :class="LED_CLASSES[statusOf(engine.id)]" aria-hidden="true"></span>
            <span v-if="installed(engine.id) && statusShown(engine.id)" class="hidden text-[11px] font-medium 2xl:inline" :class="STATUS_TEXT_CLASSES[statusOf(engine.id)]">{{ t(STATUS_LABEL_KEYS[statusOf(engine.id)]) }}</span>
          </button>
        </div>

        <router-link
          to="/editor"
          class="relative flex shrink-0 items-center gap-2 px-2 transition-colors xl:px-3"
          :class="onEditor ? 'text-text' : 'text-text-dim hover:text-text'"
          :title="t('header.desc.editor')"
          :aria-current="onEditor ? 'page' : undefined"
        >
          <TimelineIcon class="h-[18px] w-[18px] shrink-0" :class="onEditor && 'text-accent1'" />
          <span class="text-[15px] leading-5 whitespace-nowrap" :class="onEditor ? 'font-semibold' : 'font-medium'">{{ t('header.editor') }}</span>
          <span v-if="onEditor" class="accent-gradient absolute inset-x-2 bottom-0 h-0.5 rounded-full xl:inset-x-3" aria-hidden="true"></span>
        </router-link>
      </nav>

      <div class="ml-auto flex shrink-0 items-center gap-1 self-center lg:ml-0 lg:justify-self-end">
        <!-- RAM above video memory, always in sight (two rings on a narrow window); a click opens the details and
             the button that unloads the model -->
        <ResourceMeters stacked class="mr-1 sm:mr-3" />
        <button
          type="button"
          class="h-9 rounded-lg px-2.5 text-xs font-semibold text-text-dim transition-colors hover:bg-panel-2 hover:text-text"
          :title="t('header.language')"
          @click="toggleLocale"
        >
          {{ locale === 'ru' ? 'EN' : 'RU' }}
        </button>
        <!-- Models and settings: a settings page, so a gear beside the help rather than a tab next to the engines -->
        <router-link
          to="/models"
          :title="t('header.models')"
          :aria-label="t('header.models')"
          class="flex h-9 w-9 items-center justify-center rounded-lg text-text-dim transition-colors hover:bg-panel-2 hover:text-text"
          active-class="bg-panel-2 text-text"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        </router-link>
        <button
          type="button"
          :title="t('header.help')"
          :aria-label="t('header.help')"
          class="flex h-9 w-9 items-center justify-center rounded-lg text-text-dim transition-colors hover:bg-panel-2 hover:text-text"
          @click="helpOpen = true"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M9.5 9a2.5 2.5 0 1 1 3.4 2.33c-.77.32-1.4.98-1.4 1.92V14" />
            <circle cx="12" cy="17.5" r=".8" fill="currentColor" stroke="none" />
            <circle cx="12" cy="12" r="10" />
          </svg>
        </button>
      </div>
    </div>
    <p v-if="orchestrator.switchError" class="border-t border-status-failed/30 bg-status-failed/10 px-4 py-2 text-xs whitespace-pre-line text-status-failed sm:px-6">
      {{ orchestrator.switchError }}
    </p>

    <AppHelpModal :open="helpOpen" @close="helpOpen = false" @open-guide="openGuide" />
    <EditorHelpModal :show="guide === 'editor'" @close="guide = null" @open-guide="guide = 'arranger'" @open-hotkeys="guide = 'hotkeys'" />
    <EditorHotkeysModal :show="guide === 'hotkeys'" @close="guide = null" />
    <AiArrangerGuide :open="guide === 'arranger'" @close="guide = null" />
  </header>
</template>
