<script setup lang="ts">
// ACE-Step's two pages, generating and training a LoRA, as tabs at the top of each: LoRA is ACE-Step's own,
// so it lives under its engine rather than in the header.
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import WaveIcon from '../../components/shared/icons/WaveIcon.vue'
import TargetIcon from '../../components/shared/icons/TargetIcon.vue'

const { t } = useI18n()
const route = useRoute()
const TABS = [
  { name: 'ace-step', to: '/ace-step', icon: WaveIcon, label: 'acePage.tabs.generate', hint: 'header.desc.ace' },
  { name: 'ace-step-lora', to: '/ace-step/lora', icon: TargetIcon, label: 'acePage.tabs.lora', hint: 'acePage.tabs.loraHint' },
] as const
</script>

<template>
  <nav class="flex w-fit items-center gap-0.5 rounded-xl border border-border bg-panel-2/40 p-1" :aria-label="t('acePage.tabs.label')">
    <router-link
      v-for="tab in TABS"
      :key="tab.name"
      :to="tab.to"
      class="flex h-9 items-center gap-2 rounded-lg px-3.5 text-sm transition-colors"
      :class="route.name === tab.name ? 'bg-panel font-semibold text-text shadow-sm shadow-black/20' : 'font-medium text-text-dim hover:bg-panel/60 hover:text-text'"
      :title="t(tab.hint)"
      :aria-current="route.name === tab.name ? 'page' : undefined"
    >
      <component :is="tab.icon" class="h-4 w-4 shrink-0" :class="route.name === tab.name && 'text-accent1'" />
      {{ t(tab.label) }}
    </router-link>
  </nav>
</template>
