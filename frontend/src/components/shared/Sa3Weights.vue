<script setup lang="ts">
// The Stable Audio 3 page before any checkpoint is there: the token the gated ones need and the three main models
// with a Download button, so the first run takes no detour. The full list, the base checkpoints and the settings
// are on the Models page.
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Sa3WeightModel } from '../../api/sa3Weights'
import { useSa3WeightsStore } from '../../stores/sa3Weights'
import HfTokenField from './HfTokenField.vue'
import PartRow from './PartRow.vue'

const { t } = useI18n()
const store = useSa3WeightsStore()

const main = computed(() => store.weights?.models.filter((m) => !m.base) ?? [])
const pageUrl = (m: Sa3WeightModel) => `https://huggingface.co/${m.repo}`

async function act(action: () => Promise<unknown>) {
  try {
    await action()
  } catch {
    // the row shows the download's own error; a refused request is rare here
  }
}

onMounted(() => void store.load())
</script>

<template>
  <section class="rounded-xl border border-border bg-panel p-4 text-sm" :aria-label="t('sa3Weights.titleFirst')">
    <h2 class="text-base font-semibold text-text">{{ t('sa3Weights.titleFirst') }}</h2>
    <p class="mt-1.5 max-w-3xl text-xs leading-relaxed text-text-dim">{{ t('sa3Weights.lead') }}</p>

    <p v-if="store.loadError" class="mt-3 rounded-lg bg-status-failed/10 p-3 text-xs text-status-failed">{{ store.loadError }}</p>
    <p v-else-if="!store.weights" class="mt-3 text-xs text-text-dim">{{ t('sa3Weights.loading') }}</p>
    <template v-else>
      <HfTokenField class="mt-3 rounded-lg border border-border bg-panel-2 p-3" />
      <ul class="mt-2 divide-y divide-border">
        <PartRow
          v-for="m in main"
          :key="m.id"
          :name="m.id"
          :hint="t(`sa3Weights.models.${m.id}`)"
          :bytes="m.bytes"
          :on-disk="m.on_disk"
          :installed="m.installed"
          :download="m.download"
          :blocked="!!store.running || !store.weights.env"
          :blocked-title="store.running ? t('sa3Weights.oneAtATime', { model: store.running.id }) : undefined"
          @download="act(() => store.download(m.id))"
          @cancel="act(() => store.cancel(m.id))"
        >
          <template #error>
            <template v-if="m.download?.code === 'access'">
              {{ t('sa3Weights.errors.access') }}
              <a :href="pageUrl(m)" target="_blank" rel="noopener" class="underline">{{ t('sa3Weights.modelPage') }}</a>
            </template>
            <template v-else-if="m.download?.code === 'login'">{{ t(store.weights?.token ? 'sa3Weights.errors.badToken' : 'sa3Weights.errors.login') }}</template>
            <template v-else-if="m.download?.code === 'network'">{{ t('sa3Weights.errors.network') }}</template>
            <template v-else>{{ m.download?.error || t('sa3Weights.errors.unknown') }}</template>
          </template>
          <template v-if="m.gated" #note>
            {{ t('sa3Weights.licence') }}
            <a :href="pageUrl(m)" target="_blank" rel="noopener" class="text-accent1 underline">{{ t('sa3Weights.modelPage') }}</a>
          </template>
        </PartRow>
      </ul>
      <RouterLink to="/models#stable-audio" class="mt-3 inline-block text-xs text-text-dim hover:text-text">{{ t('sa3Weights.allOnModels') }}</RouterLink>
    </template>
  </section>
</template>
