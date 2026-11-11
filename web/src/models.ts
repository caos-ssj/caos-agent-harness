import { ModelProfile, RouterTier } from './api'

/* What is measured about a model, joined to what is installed and what runs it. A "system" in a benchmark is a model
   name, optionally with "+rules" (the same model behind the rule layer). */
export const baseName = (system: string) => system.split('+')[0]
export const family = (name: string) => (/llama/i.test(name) ? 'llama' : /qwen/i.test(name) ? 'qwen' : /gemma/i.test(name) ? 'gemma' : /phi/i.test(name) ? 'phi' : 'other')

export const variantsOf = (model: string, profiles: ModelProfile[]) => profiles.filter((p) => baseName(p.system) === baseName(model))

/** The tiers whose bar this profile's lower bound clears (the router also weighs coverage and speed). */
export const clears = (p: ModelProfile, tiers: RouterTier[]) => tiers.filter((t) => p.precision_lo >= t.needs).map((t) => t.tier)

export const gb = (bytes: number | null | undefined) => (bytes ? `${(bytes / 1e9).toFixed(bytes >= 1e10 ? 0 : 1)} GB` : '')
export const isEmbedding = (name: string) => /embed/i.test(name)
