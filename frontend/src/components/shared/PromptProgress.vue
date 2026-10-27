<script setup lang="ts">
// A prompt being written by the assistant: the stage, an estimated percent, the text as it grows, and Stop.
import { nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { WriteProgress } from '../../api/assistant'

const props = defineProps<{ progress: WriteProgress; stopping?: boolean }>()
const emit = defineEmits<{ stop: [] }>()
const { t } = useI18n()

/** Before the writing starts there is nothing to count: the bar runs without a number. */
const counting = (stage: WriteProgress['stage']) => stage === 'writing' || stage === 'retrying'

const box = ref<HTMLElement | null>(null)
watch(() => props.progress.preview, async () => {
  await nextTick()
  if (box.value) box.value.scrollTop = box.value.scrollHeight
})
</script>

<template>
  <div class="rounded-lg border border-border bg-panel-2/60 p-3" role="status" aria-live="polite">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <span class="inline-flex items-center gap-2 font-medium text-text">
        <span class="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent1 border-t-transparent"></span>
        {{ t(`promptProgress.stage.${progress.stage}`) }}
      </span>
      <span v-if="counting(progress.stage)" class="tabular-nums text-text-dim">{{ t('promptProgress.tokens', { pct: progress.percent, n: progress.tokens }) }}</span>
      <button
        type="button"
        class="ms-auto rounded-lg border border-border px-2.5 py-1 text-xs text-text-dim hover:border-status-failed/60 hover:text-status-failed disabled:opacity-50"
        :disabled="stopping"
        @click="emit('stop')"
      >
        {{ t(stopping ? 'promptProgress.stopping' : 'promptProgress.stop') }}
      </button>
    </div>
    <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-panel">
      <div
        v-if="counting(progress.stage)"
        class="accent-gradient h-full rounded-full transition-[width] duration-500"
        :style="{ width: `${Math.max(2, progress.percent)}%` }"
      ></div>
      <div v-else class="accent-gradient indeterminate h-full w-1/3 rounded-full"></div>
    </div>
    <pre
      v-if="progress.preview"
      ref="box"
      class="mt-2 max-h-56 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-panel p-2 font-mono text-[12px] leading-relaxed text-text-dim"
    >{{ progress.preview }}<span class="animate-pulse text-accent1">▍</span></pre>
  </div>
</template>

<style scoped>
.indeterminate {
  animation: promptbar 1.4s ease-in-out infinite;
}
@keyframes promptbar {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(300%); }
}
</style>
