<script setup lang="ts">
// The inside of a help window, as in the editor's guide: an optional lead in the text colour, then the sections
// with room between them.
defineProps<{ lead?: string }>()
</script>

<template>
  <div class="space-y-6">
    <p v-if="lead" class="text-[15px] leading-relaxed text-text">{{ lead }}</p>
    <slot />
  </div>
</template>
