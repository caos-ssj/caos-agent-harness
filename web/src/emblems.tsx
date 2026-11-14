import React from 'react'

/* Clean 14–16px precision marks for agent families, the house mark, and cycle steps.
   Fine stroke (1.65), crisp geometry, no heavy square boxes. */

type P = { size?: number; className?: string; title?: string }
const Svg: React.FC<P & { children: React.ReactNode }> = ({ size = 16, className, title, children }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={1.65} strokeLinejoin="round" strokeLinecap="round"
    className={className} role={title ? 'img' : undefined} aria-label={title} aria-hidden={title ? undefined : true}>{children}</svg>
)

const FAMILY: Record<string, React.ReactNode> = {
  claude: (
    <>
      <path d="M12 2.5v19M2.5 12h19M5.3 5.3l13.4 13.4M18.7 5.3L5.3 18.7" />
      <circle cx="12" cy="12" r="2.6" fill="currentColor" stroke="none" />
    </>
  ),
  agy: (
    <>
      <path d="M12 2.2c1.1 5.4 4.4 8.7 9.8 9.8-5.4 1.1-8.7 4.4-9.8 9.8-1.1-5.4-4.4-8.7-9.8-9.8 5.4-1.1 8.7-4.4 9.8-9.8z" />
      <circle cx="12" cy="12" r="1.7" fill="currentColor" stroke="none" />
    </>
  ),
  gemini: (
    <>
      <path d="M12 2.2c1.1 5.4 4.4 8.7 9.8 9.8-5.4 1.1-8.7 4.4-9.8 9.8-1.1-5.4-4.4-8.7-9.8-9.8 5.4-1.1 8.7-4.4 9.8-9.8z" />
      <circle cx="12" cy="12" r="1.7" fill="currentColor" stroke="none" />
    </>
  ),
  codex: (
    <>
      <path d="M12 2.6l8 4.6v9.6l-8 4.6-8-4.6V7.2z" />
      <circle cx="12" cy="12" r="2.5" fill="currentColor" stroke="none" />
    </>
  ),
  openai: (
    <>
      <path d="M12 2.6l8 4.6v9.6l-8 4.6-8-4.6V7.2z" />
      <circle cx="12" cy="12" r="2.5" fill="currentColor" stroke="none" />
    </>
  ),
  opencode: (
    <>
      <path d="M5 7.5L10.5 12 5 16.5" />
      <path d="M12.5 16.5H19" />
    </>
  ),
  local: (
    <>
      <rect x="6.5" y="6.5" width="11" height="11" rx="2" />
      <rect x="9.8" y="9.8" width="4.4" height="4.4" rx="0.8" fill="currentColor" stroke="none" />
      <path d="M9.5 3.5v3M14.5 3.5v3M9.5 17.5v3M14.5 17.5v3M3.5 9.5h3M3.5 14.5h3M17.5 9.5h3M17.5 14.5h3" />
    </>
  ),
  reviewer: (
    <>
      <path d="M12 2.8l7.5 2.8v5.8c0 4.5-3 7.8-7.5 9.8-4.5-2-7.5-5.3-7.5-9.8V5.6z" />
      <path d="M8.8 12.2l2.2 2.2 4.4-4.6" />
    </>
  ),
  api: (
    <>
      <path d="M13 3L5.5 13.5H12L11 21l7.5-10.5H12z" />
    </>
  ),
  tool: (
    <>
      <circle cx="12" cy="12" r="7.5" />
      <circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none" />
    </>
  ),
}

/** The emblem of an agent's family: compact 14–16px precision glyph. */
export const FamilyEmblem: React.FC<P & { family?: string | null }> = ({ family, ...p }) => <Svg {...p}>{FAMILY[family ?? 'tool'] ?? FAMILY.tool}</Svg>

/** The house emblem: four stations around a core. */
export const HouseEmblem: React.FC<P> = (p) => (
  <Svg {...p}><circle cx="12" cy="12" r="8.6" /><path d="M12 1.2v4M12 18.8v4M1.2 12h4M18.8 12h4" strokeWidth={2.2} /><path d="M12 7.6l4.4 4.4-4.4 4.4-4.4-4.4z" fill="currentColor" stroke="none" /></Svg>
)

const STEP: Record<string, React.ReactNode> = {
  scout: <><circle cx="12" cy="12" r="7.5" /><path d="M12 2v4M12 18v4M2 12h4M18 12h4" /><circle cx="12" cy="12" r="1.8" fill="currentColor" stroke="none" /></>,
  author: <><path d="M4 20l1.6-6L16.2 3.4l4.4 4.4L10 18.4z" /><path d="M13.4 6.2l4.4 4.4" /><path d="M4 20l3.2-.8-2.4-2.4z" fill="currentColor" stroke="none" /></>,
  reviewer: <><path d="M12 2.5l8 3v6.2c0 4.6-3.2 8-8 9.8-4.8-1.8-8-5.2-8-9.8V5.5z" /><path d="M8.4 12l2.6 2.6 4.8-5.2" strokeWidth={2} /></>,
  verify: <><path d="M3 20h18" /><path d="M5 20a7 7 0 0 1 14 0" /><path d="M12 20l4.2-6.4" strokeWidth={2.2} /><circle cx="12" cy="20" r="1.6" fill="currentColor" stroke="none" /></>,
  landed: <><path d="M6 3v12a4 4 0 0 0 4 4h4" /><path d="M6 9a6 6 0 0 0 6 6" /><rect x="14" y="15.5" width="7" height="7" fill="currentColor" stroke="none" /><circle cx="6" cy="3.6" r="1.6" fill="currentColor" stroke="none" /></>,
}

/** One step of the cycle: scout, author, reviewer, verify, landed. */
export const StepGlyph: React.FC<P & { step: keyof typeof STEP | string }> = ({ step, ...p }) => <Svg {...p}>{STEP[step] ?? STEP.scout}</Svg>
