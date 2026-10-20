<script setup lang="ts">
// A quick start in a help window: a real sequence, so the steps are numbered cards, as in the editor's guide.
defineProps<{ steps: { title: string; text: string }[] }>()
</script>

<template>
  <ol class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
    <li v-for="(s, i) in steps" :key="i" class="flex gap-3 rounded-lg border border-border/60 bg-panel-2/50 p-3">
      <span class="accent-gradient flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white" aria-hidden="true">{{ i + 1 }}</span>
      <div class="min-w-0">
        <p class="font-medium text-text">{{ s.title }}</p>
        <p class="mt-0.5 text-xs leading-relaxed">{{ s.text }}</p>
      </div>
    </li>
  </ol>
</template>
