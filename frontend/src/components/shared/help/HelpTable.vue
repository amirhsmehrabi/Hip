<script setup lang="ts" generic="Row extends Record<string, unknown>">
// A table in a help window, framed like the comparison in the app's help: a tinted header, rows parted by thin
// lines, the first column in the text colour. It scrolls sideways on a narrow window instead of squeezing.
export interface HelpColumn {
  key: string
  /** Left out on every column: no header row (a list of tags and what they do). */
  label?: string
  /** Tags, code and prompts. */
  mono?: boolean
  nowrap?: boolean
}
defineProps<{
  columns: HelpColumn[]
  rows: Row[]
  /** A row to mark, e.g. the mode the panel is in now. */
  current?: (row: Row) => boolean
  /** Wide tables keep their width and scroll on a phone. */
  minWidth?: string
}>()
</script>

<template>
  <div class="overflow-x-auto rounded-lg border border-border/60">
    <table class="w-full border-collapse text-left text-xs" :style="minWidth ? { minWidth } : undefined">
      <thead v-if="columns.some((c) => c.label)" class="bg-panel-2/60 text-text">
        <tr>
          <th v-for="c in columns" :key="c.key" scope="col" class="px-3 py-2 font-semibold">{{ c.label }}</th>
        </tr>
      </thead>
      <tbody class="align-top">
        <tr
          v-for="(row, i) in rows"
          :key="i"
          class="border-border/60"
          :class="[(i > 0 || columns.some((c) => c.label)) && 'border-t', current?.(row) && 'bg-accent1/10']"
        >
          <component
            :is="j === 0 ? 'th' : 'td'"
            v-for="(c, j) in columns"
            :key="c.key"
            :scope="j === 0 ? 'row' : undefined"
            class="px-3 py-2 leading-relaxed"
            :class="[j === 0 ? 'font-medium text-text' : 'font-normal', c.mono && 'font-mono', c.nowrap && 'whitespace-nowrap']"
          >{{ row[c.key] }}</component>
        </tr>
      </tbody>
    </table>
  </div>
</template>
