<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useOrchestratorStore } from '../../stores/orchestrator'
import { useStableAudioStore } from '../../stores/stableAudio'
import { useFeaturesStore } from '../../stores/features'
import { useSa3WeightsStore } from '../../stores/sa3Weights'
import ModelOfflineBanner from '../../components/shared/ModelOfflineBanner.vue'
import NotInstalled from '../../components/shared/NotInstalled.vue'
import Sa3Weights from '../../components/shared/Sa3Weights.vue'
import ChevronIcon from '../../components/shared/icons/ChevronIcon.vue'
import GenerateForm from './GenerateForm.vue'
import TrackFeed from './TrackFeed.vue'

const orchestrator = useOrchestratorStore()
const store = useStableAudioStore()
const features = useFeaturesStore()
const { t } = useI18n()

/** The other checkpoints, folded away once one is there. */
const showModels = ref(false)
const modelCount = computed(() => features.features.stable_audio_models.length)

const modelStatus = computed(() => orchestrator.statuses.stable_audio?.status ?? 'stopped')
const modelError = computed(() => orchestrator.statuses.stable_audio?.error ?? null)
const isRunning = computed(() => modelStatus.value === 'running')

const weights = useSa3WeightsStore()

onMounted(() => {
  // also tells the installed parts about a checkpoint that arrived while the app was elsewhere
  if (features.features.stable_audio_env) void weights.load()
  void store.loadHistory()
  store.startBackgroundTasks()
})
onBeforeUnmount(() => store.stopBackgroundTasks())
</script>

<template>
  <div class="space-y-6">
    <!-- left out at install: say how to add it; the gated weights are fetched right here; earlier tracks stay listed below -->
    <NotInstalled v-if="!features.features.stable_audio_env" feature="stableAudio" />
    <Sa3Weights v-else-if="!features.has('stableAudio')" first />
    <template v-else>
      <ModelOfflineBanner v-if="!isRunning" model-id="stable_audio" :status="modelStatus" :error="modelError" />
      <div>
        <button type="button" class="inline-flex items-center gap-1.5 text-xs text-text-dim hover:text-text" :aria-expanded="showModels" @click="showModels = !showModels">
          {{ t('sa3Weights.toggle', { n: modelCount }) }}
          <ChevronIcon class="h-3.5 w-3.5 transition-transform" :class="showModels && 'rotate-180'" />
        </button>
        <Sa3Weights v-if="showModels" class="mt-2" />
      </div>
    </template>
    <div class="grid grid-cols-1 gap-6 lg:grid-cols-[480px_minmax(0,1fr)]">
      <GenerateForm v-if="isRunning" />
      <TrackFeed :class="{ 'lg:col-span-2': !isRunning }" />
    </div>
  </div>
</template>
