<script setup lang="ts">
// The Hugging Face token the gated Stable Audio 3 checkpoints need: a field until one is saved, then a line
// with "replace". Saving goes through the sa3Weights store (the backend checks the token and keeps it in the
// Hugging Face cache, never in the database).
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSa3WeightsStore } from '../../stores/sa3Weights'
import CheckIcon from './icons/CheckIcon.vue'

const { t } = useI18n()
const store = useSa3WeightsStore()

const HF_TOKENS = 'https://huggingface.co/settings/tokens'
const input = ref('')
const open = ref(false)
const busy = ref(false)
const message = ref<{ ok: boolean; text: string } | null>(null)
const saved = computed(() => !!store.weights?.token)
const ask = computed(() => !!store.weights && (!saved.value || open.value))

async function submit() {
  const value = input.value.trim()
  if (!value || busy.value) return
  busy.value = true
  message.value = null
  try {
    const r = await store.saveToken(value)
    if (r.ok) {
      input.value = ''
      open.value = false
      message.value = { ok: true, text: t('sa3Weights.token.saved', { user: r.user || '?' }) }
    } else {
      message.value = { ok: false, text: t(r.code === 'network' ? 'sa3Weights.errors.network' : 'sa3Weights.token.bad') }
    }
  } catch (e) {
    message.value = { ok: false, text: e instanceof Error ? e.message : String(e) }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="text-xs">
    <template v-if="ask">
      <label for="sa3-hf-token" class="font-medium text-text">{{ t('sa3Weights.token.label') }}</label>
      <p class="mt-0.5 leading-relaxed text-text-dim">
        {{ t('sa3Weights.token.hint') }}
        <a :href="HF_TOKENS" target="_blank" rel="noopener" class="text-accent1 underline">{{ t('sa3Weights.token.create') }}</a>
      </p>
      <form class="mt-2 flex flex-wrap items-center gap-2" @submit.prevent="submit">
        <input
          id="sa3-hf-token"
          v-model="input"
          type="password"
          autocomplete="off"
          spellcheck="false"
          placeholder="hf_…"
          class="min-w-[14rem] flex-1 rounded-lg border border-border bg-panel px-2.5 py-1.5 font-mono text-xs text-text outline-none focus:border-accent1"
        />
        <button type="submit" class="rounded-lg border border-border px-3 py-1.5 font-medium text-text hover:border-accent1 disabled:opacity-50" :disabled="!input.trim() || busy">
          {{ t(busy ? 'sa3Weights.token.checking' : 'sa3Weights.token.save') }}
        </button>
        <button v-if="saved" type="button" class="px-1 text-text-dim hover:text-text" @click="open = false">{{ t('sa3Weights.token.keep') }}</button>
      </form>
    </template>
    <p v-else class="flex flex-wrap items-center gap-x-3 gap-y-1 text-text-dim">
      <span class="inline-flex items-center gap-1.5 text-text"><CheckIcon class="h-3.5 w-3.5 text-status-done" />{{ t('sa3Weights.token.present') }}</span>
      <button type="button" class="text-accent1 underline" @click="open = true">{{ t('sa3Weights.token.replace') }}</button>
    </p>
    <p v-if="message" class="mt-2" :class="message.ok ? 'text-status-done' : 'text-status-failed'" role="status">{{ message.text }}</p>
  </div>
</template>
