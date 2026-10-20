<script setup lang="ts">
// A part of a help window with a heading, the way the editor's guide (EditorHelpModal) lays them out.
// tone: a plain section, "tips" in the accent box, or "note" (limits, caveats) in the amber one.
defineProps<{ title?: string; intro?: string; tone?: 'plain' | 'tips' | 'note' }>()
</script>

<template>
  <section
    :class="{
      'rounded-lg border border-accent1/25 bg-accent1/[0.06] p-3': tone === 'tips',
      'rounded-lg border border-status-queued/30 bg-status-queued/[0.05] p-3': tone === 'note',
    }"
  >
    <h4 v-if="title" class="mb-1.5 text-sm font-semibold text-text">{{ title }}</h4>
    <p v-if="intro" class="mb-2.5">{{ intro }}</p>
    <slot />
  </section>
</template>
