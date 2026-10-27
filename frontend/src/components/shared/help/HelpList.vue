<script setup lang="ts">
// A bulleted list in a help window. html: the items carry their own markup (a <b> or <code> in the locale text).
defineProps<{ items: string[]; html?: boolean; ordered?: boolean }>()
</script>

<template>
  <component :is="ordered ? 'ol' : 'ul'" class="space-y-1.5 ps-4" :class="ordered ? 'list-decimal' : 'list-disc'">
    <template v-for="(x, i) in items" :key="i">
      <li v-if="html" v-html="x"></li>
      <li v-else>{{ x }}</li>
    </template>
  </component>
</template>
