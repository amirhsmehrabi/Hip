<script setup lang="ts">
// Stable Audio 3 checkpoints: which are downloaded, a button to fetch the others, and the Hugging Face token the
// gated ones need. The download runs in the backend, so leaving the page does not stop it; coming back shows it.
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Sa3WeightModel } from '../../api/sa3Weights'
import { useSa3WeightsStore } from '../../stores/sa3Weights'
import CheckIcon from './icons/CheckIcon.vue'
import DownloadIcon from './icons/DownloadIcon.vue'

const props = defineProps<{ /** No model downloaded yet: say so first. */ first?: boolean }>()
const { t, locale } = useI18n()
const store = useSa3WeightsStore()

const state = computed(() => store.weights)
const loadError = computed(() => store.loadError)
const actionError = ref<string | null>(null)
const showBase = ref(false)

const main = computed(() => state.value?.models.filter((m) => !m.base) ?? [])
const base = computed(() => state.value?.models.filter((m) => m.base) ?? [])
const running = computed(() => store.running)
const baseInstalled = computed(() => base.value.filter((m) => m.installed).length)

const HF_TOKENS = 'https://huggingface.co/settings/tokens'
const pageUrl = (m: Sa3WeightModel) => `https://huggingface.co/${m.repo}`

function gb(bytes: number): string {
  return new Intl.NumberFormat(locale.value, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(bytes / 1e9)
}

function percent(m: Sa3WeightModel): number {
  const d = m.download
  return d && d.total > 0 ? Math.min(100, Math.round((d.done / d.total) * 100)) : 0
}

async function download(m: Sa3WeightModel) {
  actionError.value = null
  try {
    await store.download(m.id)
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e)
  }
}

async function cancel(m: Sa3WeightModel) {
  try {
    await store.cancel(m.id)
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e)
  }
}

// ---- the Hugging Face token ----
const tokenInput = ref('')
const tokenOpen = ref(false)
const tokenBusy = ref(false)
const tokenMessage = ref<{ ok: boolean; text: string } | null>(null)
const askToken = computed(() => !!state.value && (!state.value.token || tokenOpen.value))

async function submitToken() {
  const value = tokenInput.value.trim()
  if (!value || tokenBusy.value) return
  tokenBusy.value = true
  tokenMessage.value = null
  try {
    const r = await store.saveToken(value)
    if (r.ok) {
      tokenInput.value = ''
      tokenOpen.value = false
      tokenMessage.value = { ok: true, text: t('sa3Weights.token.saved', { user: r.user || '?' }) }
    } else {
      tokenMessage.value = { ok: false, text: t(r.code === 'network' ? 'sa3Weights.errors.network' : 'sa3Weights.token.bad') }
    }
  } catch (e) {
    tokenMessage.value = { ok: false, text: e instanceof Error ? e.message : String(e) }
  } finally {
    tokenBusy.value = false
  }
}

// Fresh state each time it is shown; while a download runs the store keeps following it, on any page.
onMounted(() => void store.load())
</script>

<template>
  <section class="rounded-xl border border-border bg-panel p-4 text-sm" :aria-label="t('sa3Weights.title')">
    <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h2 class="text-base font-semibold text-text">{{ t(props.first ? 'sa3Weights.titleFirst' : 'sa3Weights.title') }}</h2>
      <p class="text-xs text-text-dim">{{ t('sa3Weights.where') }}</p>
    </div>
    <p class="mt-1.5 max-w-3xl text-xs leading-relaxed text-text-dim">{{ t('sa3Weights.lead') }}</p>

    <p v-if="loadError" class="mt-3 rounded-lg bg-status-failed/10 p-3 text-xs text-status-failed">{{ loadError }}</p>
    <p v-else-if="!state" class="mt-3 text-xs text-text-dim">{{ t('sa3Weights.loading') }}</p>
    <template v-else>
      <!-- The token: needed for the three gated checkpoints -->
      <div class="mt-3 rounded-lg border border-border bg-panel-2 p-3 text-xs">
        <template v-if="askToken">
          <label for="sa3-hf-token" class="font-medium text-text">{{ t('sa3Weights.token.label') }}</label>
          <p class="mt-0.5 leading-relaxed text-text-dim">
            {{ t('sa3Weights.token.hint') }}
            <a :href="HF_TOKENS" target="_blank" rel="noopener" class="text-accent1 underline">{{ t('sa3Weights.token.create') }}</a>
          </p>
          <form class="mt-2 flex flex-wrap items-center gap-2" @submit.prevent="submitToken">
            <input
              id="sa3-hf-token"
              v-model="tokenInput"
              type="password"
              autocomplete="off"
              spellcheck="false"
              placeholder="hf_…"
              class="min-w-[14rem] flex-1 rounded-lg border border-border bg-panel px-2.5 py-1.5 font-mono text-xs text-text outline-none focus:border-accent1"
            />
            <button type="submit" class="rounded-lg border border-border px-3 py-1.5 font-medium text-text hover:border-accent1 disabled:opacity-50" :disabled="!tokenInput.trim() || tokenBusy">
              {{ t(tokenBusy ? 'sa3Weights.token.checking' : 'sa3Weights.token.save') }}
            </button>
            <button v-if="state.token" type="button" class="px-1 text-text-dim hover:text-text" @click="tokenOpen = false">{{ t('sa3Weights.token.keep') }}</button>
          </form>
        </template>
        <p v-else class="flex flex-wrap items-center gap-x-3 gap-y-1 text-text-dim">
          <span class="inline-flex items-center gap-1.5 text-text"><CheckIcon class="h-3.5 w-3.5 text-status-done" />{{ t('sa3Weights.token.present') }}</span>
          <button type="button" class="text-accent1 underline" @click="tokenOpen = true">{{ t('sa3Weights.token.replace') }}</button>
        </p>
        <p v-if="tokenMessage" class="mt-2" :class="tokenMessage.ok ? 'text-status-done' : 'text-status-failed'" role="status">{{ tokenMessage.text }}</p>
      </div>

      <p v-if="actionError" class="mt-3 rounded-lg bg-status-failed/10 p-3 text-xs text-status-failed">{{ actionError }}</p>

      <ul class="mt-3 divide-y divide-border">
        <li v-for="m in [...main, ...(showBase ? base : [])]" :key="m.id" class="flex flex-wrap items-center gap-x-4 gap-y-2 py-2.5">
          <div class="min-w-[12rem] flex-1">
            <p class="font-medium text-text">
              {{ m.id }}
              <span class="ml-1 text-xs font-normal text-text-dim">{{ t('sa3Weights.size', { gb: gb(m.bytes) }) }}</span>
            </p>
            <p class="mt-0.5 text-xs leading-relaxed text-text-dim">{{ t(`sa3Weights.models.${m.id}`) }}</p>
          </div>

          <!-- downloaded -->
          <span v-if="m.installed" class="inline-flex items-center gap-1.5 text-xs text-status-done">
            <CheckIcon class="h-3.5 w-3.5" />{{ t('sa3Weights.installed') }}
          </span>

          <!-- downloading -->
          <div v-else-if="m.download?.status === 'running'" class="flex min-w-[16rem] flex-1 items-center gap-3">
            <div class="flex-1">
              <div class="h-1.5 overflow-hidden rounded-full bg-panel-2">
                <div class="accent-gradient h-full rounded-full transition-[width] duration-700" :style="{ width: `${percent(m)}%` }"></div>
              </div>
              <p class="mt-1 text-[11px] tabular-nums text-text-dim">{{ t('sa3Weights.progress', { done: gb(m.download.done), total: gb(m.download.total), pct: percent(m) }) }}</p>
            </div>
            <button type="button" class="rounded-lg border border-border px-2.5 py-1 text-xs text-text-dim hover:text-text" @click="cancel(m)">{{ t('sa3Weights.cancel') }}</button>
          </div>

          <!-- not there yet (maybe after a failed or stopped try) -->
          <div v-else class="flex max-w-md flex-col items-end gap-1.5">
            <button
              type="button"
              class="accent-gradient inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
              :disabled="!!running || !state.env"
              :title="running ? t('sa3Weights.oneAtATime', { model: running.id }) : undefined"
              @click="download(m)"
            >
              <DownloadIcon class="h-3.5 w-3.5" />
              {{ t(m.download?.status === 'failed' || m.download?.status === 'cancelled' ? 'sa3Weights.resume' : 'sa3Weights.download') }}
            </button>
            <p v-if="m.download?.status === 'failed'" class="text-right text-[11px] leading-relaxed text-status-failed" role="alert">
              <template v-if="m.download.code === 'access'">
                {{ t('sa3Weights.errors.access') }}
                <a :href="pageUrl(m)" target="_blank" rel="noopener" class="underline">{{ t('sa3Weights.modelPage') }}</a>
              </template>
              <template v-else-if="m.download.code === 'login'">{{ t(state.token ? 'sa3Weights.errors.badToken' : 'sa3Weights.errors.login') }}</template>
              <template v-else-if="m.download.code === 'network'">{{ t('sa3Weights.errors.network') }}</template>
              <template v-else>{{ m.download.error || t('sa3Weights.errors.unknown') }}</template>
            </p>
            <p v-else-if="m.download?.status === 'cancelled'" class="text-[11px] text-text-dim">{{ t('sa3Weights.stopped') }}</p>
            <p v-else-if="m.gated" class="text-right text-[11px] text-text-dim">
              {{ t('sa3Weights.licence') }}
              <a :href="pageUrl(m)" target="_blank" rel="noopener" class="text-accent1 underline">{{ t('sa3Weights.modelPage') }}</a>
            </p>
          </div>
        </li>
      </ul>

      <button type="button" class="mt-1 text-xs text-text-dim hover:text-text" :aria-expanded="showBase" @click="showBase = !showBase">
        {{ t(showBase ? 'sa3Weights.baseHide' : 'sa3Weights.baseShow', { n: baseInstalled }) }}
      </button>
    </template>
  </section>
</template>
