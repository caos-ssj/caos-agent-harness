/* Three short tones for the three things worth hearing while you do something else: a change landed, a test failed, something
   waits for you. Synthesised (no audio files), quiet, and off the moment the preference says so. A browser only lets a page
   make sound after the person has touched it, so the first tone may be silent. */

export type Tone = 'start' | 'landed' | 'rejected' | 'failed' | 'needs'
const NOTES: Record<Exclude<Tone, 'start'>, Array<[number, number]>> = {
  landed: [[523.25, 0], [783.99, 0.11]],        // up a fifth: done / landed
  rejected: [[311.13, 0], [233.08, 0.13]],      // down a fourth: failed / rejected
  failed: [[311.13, 0], [233.08, 0.13]],        // down a fourth: failed / stopped
  needs: [[659.25, 0], [659.25, 0.16]],         // the same note twice: your turn
}
let ctx: AudioContext | null = null
let enabled = true
export const setTones = (on: boolean): void => { enabled = on }

function context(): AudioContext | null {
  try {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AC) return null
    ctx = ctx ?? new AC()
    if (ctx.state === 'suspended') void ctx.resume()
    return ctx
  } catch { return null }
}
if (typeof window !== 'undefined') window.addEventListener('pointerdown', () => { context() }, { once: true })

export function playTone(tone: Tone): void {
  if (tone === 'start') return
  if (!enabled) return
  const ac = context()
  if (!ac || ac.state !== 'running') return
  for (const [freq, at] of NOTES[tone]) {
    const t = ac.currentTime + at, osc = ac.createOscillator(), gain = ac.createGain()
    osc.type = 'sine'
    osc.frequency.value = freq
    gain.gain.setValueAtTime(0.0001, t)
    gain.gain.exponentialRampToValueAtTime(0.07, t + 0.015)
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.32)
    osc.connect(gain).connect(ac.destination)
    osc.start(t)
    osc.stop(t + 0.36)
  }
}
