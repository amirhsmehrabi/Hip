<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useOrchestratorStore } from '../../stores/orchestrator'
import { useStableAudioStore } from '../../stores/stableAudio'
import { useFeaturesStore } from '../../stores/features'
import ModelOfflineBanner from '../../components/shared/ModelOfflineBanner.vue'
import NotInstalled from '../../components/shared/NotInstalled.vue'
import GenerateForm from './GenerateForm.vue'
import TrackFeed from './TrackFeed.vue'

const orchestrator = useOrchestratorStore()
const store = useStableAudioStore()
const features = useFeaturesStore()

const modelStatus = computed(() => orchestrator.statuses.stable_audio?.status ?? 'stopped')
const modelError = computed(() => orchestrator.statuses.stable_audio?.error ?? null)
const isRunning = computed(() => modelStatus.value === 'running')

onMounted(() => {
  void store.loadHistory()
  store.startBackgroundTasks()
})
onBeforeUnmount(() => store.stopBackgroundTasks())
</script>

<template>
  <div class="space-y-6">
    <!-- left out at install, or the gated weights not fetched yet: say what to do; earlier tracks stay listed below -->
    <NotInstalled v-if="!features.has('stableAudio')" feature="stableAudio" />
    <ModelOfflineBanner v-else-if="!isRunning" model-id="stable_audio" :status="modelStatus" :error="modelError" />
    <div class="grid grid-cols-1 gap-6 lg:grid-cols-[480px_minmax(0,1fr)]">
      <GenerateForm v-if="isRunning" />
      <TrackFeed :class="{ 'lg:col-span-2': !isRunning }" />
    </div>
  </div>
</template>
