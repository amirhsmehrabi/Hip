import { clipBuffer } from '../audio/timelineTypes'
import type { TimelineProject } from '../audio/timelineTypes'
import { encodeWav } from '../audio/wavEncoder'
import { getSharedAudioCtx } from '../composables/audioPlayback'
import type { ModelId } from '../types'

/**
 * lego = add a part over the chosen lanes; repaint = redo a selected range; continue = extend past a
 * point; cover = a new version of a range in another style.
 */
export const AI_MODES = ['lego', 'repaint', 'continue', 'cover'] as const
export type AiMode = (typeof AI_MODES)[number]

/** ACE-Step task type a mode needs from the model (`supported_task_types` in the model inventory). */
export const AI_MODE_TASK: Record<AiMode, string> = { lego: 'lego', repaint: 'repaint', continue: 'repaint', cover: 'cover' }

/** Part classes ACE-Step's lego task was trained on (acestep/constants.py TRACK_NAMES). */
export const AI_TRACKS = [
  'drums', 'bass', 'guitar', 'keyboard', 'synth', 'strings',
  'brass', 'woodwinds', 'percussion', 'fx', 'vocals', 'backing_vocals',
] as const
export type AiTrack = (typeof AI_TRACKS)[number]

/** Lane color (utils/trackColors id) for each part class. */
export const AI_TRACK_COLOR: Record<AiTrack, string> = {
  drums: 'orange', bass: 'blue', guitar: 'red', keyboard: 'yellow', synth: 'purple', strings: 'emerald',
  brass: 'yellow', woodwinds: 'green', percussion: 'cyan', fx: 'slate', vocals: 'pink', backing_vocals: 'pink',
}

export const VOCAL_TRACKS: ReadonlySet<AiTrack> = new Set(['vocals', 'backing_vocals'])

/** "C major" .. "B minor" - the keyscale strings ACE-Step accepts. */
export const KEY_SCALES: string[] = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
  .flatMap((n) => [`${n} major`, `${n} minor`])

/** ACE-Step 1.5 renders at most 600 s per task. */
export const MAX_CONTEXT_SEC = 600

/**
 * Which engine renders a job: ACE-Step (every mode) or Stable Audio 3, whose inpainting and
 * audio-to-audio cover repaint, continue and cover; it cannot write a part over a mix (lego).
 */
export const AI_ENGINES = ['ace', 'sa3'] as const
export type AiEngine = (typeof AI_ENGINES)[number]
export const ENGINE_MODES: Record<AiEngine, readonly AiMode[]> = { ace: AI_MODES, sa3: ['repaint', 'continue', 'cover'] }
/** The longest audio each engine takes in one task (Stable Audio 3 medium: 380 s). */
export const ENGINE_MAX_CONTEXT_SEC: Record<AiEngine, number> = { ace: MAX_CONTEXT_SEC, sa3: 380 }
/** The orchestrator's model id behind each engine. */
export const ENGINE_MODEL_ID: Record<AiEngine, ModelId> = { ace: 'ace_step', sa3: 'stable_audio' }
/** Stable Audio 3 checkpoints the arranger may pick, with the ones it prefers first. */
export const SA3_ARRANGER_MODELS = ['medium', 'small-music', 'small-sfx'] as const

/** One value of the "engine · model" select: `ace:acestep-v15-turbo`, `sa3:medium`. */
export function modelKey(engine: AiEngine, model: string): string {
  return `${engine}:${model}`
}
export function parseModelKey(key: string): { engine: AiEngine; model: string } {
  const i = key.indexOf(':')
  const engine = (i > 0 ? key.slice(0, i) : 'ace') as AiEngine
  return { engine: AI_ENGINES.includes(engine) ? engine : 'ace', model: i > 0 ? key.slice(i + 1) : key }
}

/**
 * Mixes the chosen lanes between `start` and `end` into the audio the model hears as context.
 * Mixed straight from the clip buffers (lane volume, clip fades and warp as the engine plays them),
 * not through the effect graph: its compressors and limiter delay the signal by ~18 ms, and the model
 * writes its part in time with what it hears, so a delayed context would put the part late.
 * Lane mute/solo is ignored (the user picked the lanes explicitly); effects are left out.
 */
export function renderContext(
  project: TimelineProject,
  buffers: Map<string, AudioBuffer>,
  laneIds: string[],
  start: number,
  end: number,
): AudioBuffer {
  const sampleRate = getSharedAudioCtx().sampleRate
  const frames = Math.max(1, Math.round((end - start) * sampleRate))
  const out = new AudioBuffer({ numberOfChannels: 2, length: frames, sampleRate })
  const outL = out.getChannelData(0)
  const outR = out.getChannelData(1)
  const bpm = project.bpm || 120
  for (const lane of project.lanes) {
    if (!laneIds.includes(lane.id)) continue
    const gain = lane.settings.volume ?? 1
    for (const clip of lane.clips) {
      if (clip.muted || clip.type === 'midi' || !clip.sourceUrl) continue
      // Same buffer choice and source-domain math as toScheduledClips / renderTimeline.
      const chosen = clipBuffer(clip, bpm, buffers)
      if (!chosen) continue
      const buf = chosen.buffer
      const sf = chosen.sf
      const srcStart = clip.trimStart * sf
      const dur = (clip.trimEnd - clip.trimStart) * sf
      const fadeIn = Math.min(Math.max(0.005, clip.fadeInDuration || 0.015), dur / 2)
      const fadeOut = Math.min(Math.max(0.005, clip.fadeOutDuration || 0.015), dur / 2)
      const t0 = Math.max(start, clip.timelineStart)
      const t1 = Math.min(end, clip.timelineStart + dur)
      if (t1 <= t0) continue
      const srcL = buf.getChannelData(0)
      const srcR = buf.getChannelData(Math.min(1, buf.numberOfChannels - 1))
      for (let o = Math.round((t0 - start) * sampleRate); o < Math.min(frames, Math.round((t1 - start) * sampleRate)); o++) {
        const into = start + o / sampleRate - clip.timelineStart
        const si = Math.floor((srcStart + into) * buf.sampleRate)
        if (si < 0 || si >= srcL.length) continue
        let g = gain
        if (into < fadeIn) g *= into / fadeIn
        else if (dur - into < fadeOut) g *= (dur - into) / fadeOut
        outL[o] += srcL[si] * g
        outR[o] += srcR[si] * g
      }
    }
  }
  // A quiet selection (e.g. a fade) still reaches the model at a usable level.
  let peak = 0
  for (let i = 0; i < frames; i++) peak = Math.max(peak, Math.abs(outL[i]), Math.abs(outR[i]))
  if (peak > 1e-4) {
    const g = 0.9 / peak
    for (let i = 0; i < frames; i++) {
      outL[i] *= g
      outR[i] *= g
    }
  }
  return out
}

export function audioBufferToWavFile(buffer: AudioBuffer, name: string): File {
  return new File([encodeWav(buffer)], name, { type: 'audio/wav' })
}

/**
 * Pearson correlation of the mono signals (decimated to ~6 kHz). Lego sometimes
 * returns a re-rendered copy of its context instead of a new part (seen at 0.75-0.96);
 * a real new part sits near 0.
 */
export function correlationWithContext(part: AudioBuffer, context: AudioBuffer): number {
  const step = Math.max(1, Math.floor(part.sampleRate / 6000))
  const ratio = context.sampleRate / part.sampleRate
  const n = Math.min(part.length, Math.floor(context.length / ratio))
  const mono = (b: AudioBuffer, i: number) => {
    let s = 0
    for (let c = 0; c < b.numberOfChannels; c++) s += b.getChannelData(c)[i]
    return s / b.numberOfChannels
  }
  let sa = 0, sb = 0, saa = 0, sbb = 0, sab = 0, k = 0
  for (let i = 0; i < n; i += step) {
    const a = mono(part, i)
    const b = mono(context, Math.floor(i * ratio))
    sa += a; sb += b; saa += a * a; sbb += b * b; sab += a * b; k++
  }
  if (k < 2) return 0
  const cov = sab / k - (sa / k) * (sb / k)
  const va = saa / k - (sa / k) ** 2
  const vb = sbb / k - (sb / k) ** 2
  return va > 1e-12 && vb > 1e-12 ? cov / Math.sqrt(va * vb) : 0
}

export const COPY_THRESHOLD = 0.3
