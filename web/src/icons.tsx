/* The icons of the app: one unified custom-drawn architectural SVG set on a crisp 24x24 grid.
   Three sizes only, set by class: `.icon` 16 px, `.icon-sm` 14 px, `.icon-xs` 12 px. */
import React from 'react'

export type IconWeight = 'thin' | 'light' | 'regular' | 'bold' | 'fill' | 'duotone'

export interface AppIconProps extends Omit<React.SVGProps<SVGSVGElement>, 'weight'> {
  size?: number | string
  strokeWidth?: number
  weight?: IconWeight
  mirrored?: boolean
  alt?: string
}
export type AppIcon = React.FC<AppIconProps>

/* An icon sits beside the words that name it, so it is hidden from a screen reader unless the call site gives it a label of its own. */
const make = (render: (weight: IconWeight) => React.ReactNode): AppIcon => ({
  size,
  strokeWidth = 1.6,
  weight = 'regular',
  mirrored: _m,
  alt: _a,
  width,
  height,
  ...p
}) => (
  <svg
    viewBox="0 0 24 24"
    width={size ?? width ?? '1em'}
    height={size ?? height ?? '1em'}
    fill="none"
    stroke="currentColor"
    strokeWidth={strokeWidth}
    strokeLinecap="square"
    strokeLinejoin="miter"
    aria-hidden={p['aria-label'] ? undefined : true}
    {...p}
  >
    {render(weight)}
  </svg>
)

export const Activity = make(() => <polyline points="2 12 6 12 9 4 15 20 18 12 22 12" />)
export const AlertTriangle = make(() => <><path d="M12 3L2 20h20L12 3Z" /><path d="M12 9v5" /><path d="M12 17h.01" /></>)
export const ArrowRight = make(() => <><path d="M4 12h15" /><path d="M14 6l6 6-6 6" /></>)
export const ArrowRightLeft = make(() => <><path d="M4 8h15" /><path d="M15 4l4 4-4 4" /><path d="M20 16H5" /><path d="M9 12l-4 4 4 4" /></>)
export const Ban = make(() => <><circle cx="12" cy="12" r="9" /><path d="M5.7 5.7l12.6 12.6" /></>)
export const Check = make(() => <path d="M4 12.5l5.5 5.5L20 6.5" />)
export const CheckCircle2 = make(() => <><circle cx="12" cy="12" r="9" /><path d="M8 12.5l2.8 2.8L16.5 9.5" /></>)
export const ChevronDown = make(() => <path d="M6 9l6 6 6-6" />)
export const ChevronLeft = make(() => <path d="M15 6l-6 6 6 6" />)
export const ChevronRight = make(() => <path d="M9 6l6 6-6 6" />)
export const ChevronUp = make(() => <path d="M6 15l6-6 6 6" />)
export const CircleDot = make(() => <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="2.5" fill="currentColor" /></>)
export const Clock = make(() => <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></>)
export const CloudUpload = make(() => <><path d="M12 20v-8" /><path d="M8.5 15l3.5-3.5 3.5 3.5" /><path d="M6.5 18H5a4 4 0 0 1-.8-7.9A6.5 6.5 0 0 1 17 8.2a4.5 4.5 0 0 1 .5 8.9" /></>)
export const Columns2 = make(() => <><rect x="3" y="4" width="18" height="16" /><path d="M12 4v16" /></>)
export const Copy = make(() => <><rect x="8" y="8" width="12" height="12" /><path d="M16 8V4H4v12h4" /></>)
export const Cpu = make(() => <><rect x="6" y="6" width="12" height="12" /><rect x="9.5" y="9.5" width="5" height="5" /><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" /></>)
export const Download = make(() => <><path d="M12 4v11" /><path d="M8 11.5l4 4 4-4" /><path d="M4 17v3h16v-3" /></>)
export const ExternalLink = make(() => <><path d="M14 4h6v6" /><path d="M10 14L20 4" /><path d="M18 13v7H4V6h7" /></>)
export const Eye = make(() => <><path d="M2 12s3.8-7 10-7 10 7 10 7-3.8 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></>)
export const FileArchive = make(() => <><path d="M6 3h8l4 4v14H6V3Z" /><path d="M14 3v4h4" /><path d="M10 7h1M9 10h1M10 13h1" /><rect x="9" y="15.5" width="2" height="3" /></>)
export const FileCode2 = make(() => <><path d="M6 3h8l4 4v14H6V3Z" /><path d="M14 3v4h4" /><path d="M10 12l-2 2 2 2M14 12l2 2-2 2" /></>)
export const FilePlus2 = make(() => <><path d="M6 3h8l4 4v14H6V3Z" /><path d="M14 3v4h4" /><path d="M12 11v6M9 14h6" /></>)
export const FileText = make(() => <><path d="M6 3h8l4 4v14H6V3Z" /><path d="M14 3v4h4" /><path d="M9 11h6M9 15h6M9 7h2" /></>)
export const FolderGit2 = make(() => <><path d="M3 5h6l2 2h10v12H3V5Z" /><circle cx="10" cy="13" r="1.5" /><circle cx="15" cy="11" r="1.5" /><circle cx="15" cy="15" r="1.5" /><path d="M11.5 13h2M13.5 11v4" /></>)
export const FolderOpen = make(() => <><path d="M3 6h6l2 2h9v3" /><path d="M3 6v13h16l3-8H6l-3 8" /></>)
export const GitBranch = make(() => <><circle cx="7" cy="6" r="2.5" /><circle cx="7" cy="18" r="2.5" /><circle cx="17" cy="8" r="2.5" /><path d="M7 8.5v7" /><path d="M17 10.5V13H7" /></>)
export const GitCompareArrows = make(() => <><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="18" r="2.5" /><path d="M6 8.5V18h7" /><path d="M10.5 15.5L13 18l-2.5 2.5" /><path d="M18 15.5V6h-7" /><path d="M13.5 8.5L11 6l2.5-2.5" /></>)
export const Globe = make(() => <><circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><ellipse cx="12" cy="12" rx="4" ry="9" /></>)
export const KeyRound = make(() => <><circle cx="8" cy="12" r="4.5" /><path d="M12.5 12H21v3M17.5 12v2.5" /></>)
export const LayoutGrid = make(() => <><rect x="3" y="3" width="7.5" height="7.5" /><rect x="13.5" y="3" width="7.5" height="7.5" /><rect x="3" y="13.5" width="7.5" height="7.5" /><rect x="13.5" y="13.5" width="7.5" height="7.5" /></>)
export const ListChecks = make(() => <><path d="M4 7l2 2 3.5-3.5M4 15l2 2 3.5-3.5" /><path d="M13 7h7M13 15h7" /></>)
export const Loader = make(() => <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" />)
export const Loader2 = make(() => <path d="M21 12a9 9 0 1 1-6.2-8.55" />)
export const Lock = make(() => <><rect x="5" y="11" width="14" height="10" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /><path d="M12 15v2" /></>)
export const MessageSquare = make(() => <path d="M4 4h16v12H8l-4 4V4Z" />)
export const MessageSquarePlus = make(() => <><path d="M4 4h16v12H8l-4 4V4Z" /><path d="M12 7.5v5M9.5 10h5" /></>)
export const PanelLeft = make(() => <><rect x="3" y="4" width="18" height="16" /><path d="M9 4v16" /></>)
export const Pencil = make(() => <><path d="M16.5 3.5l4 4L8 20H4v-4L16.5 3.5Z" /><path d="M14 6l4 4" /></>)
export const Pin = make(() => <><path d="M9 4h6l-1 6 3 3v2H7v-2l3-3-1-6Z" /><path d="M12 15v6" /></>)
export const Play = make((w) => <polygon points="6 4 20 12 6 20 6 4" fill={w === 'fill' ? 'currentColor' : 'none'} />)
export const Plus = make(() => <path d="M12 5v14M5 12h14" />)
export const RefreshCw = make(() => <><path d="M20 11a8 8 0 0 0-14.3-4.8L4 8" /><path d="M4 4v4h4" /><path d="M4 13a8 8 0 0 0 14.3 4.8L20 16" /><path d="M20 20v-4h-4" /></>)
export const RotateCcw = make(() => <><path d="M4 8l2-2A8 8 0 1 1 4.5 14" /><path d="M4 3.5V8h4.5" /></>)
export const Rows2 = make(() => <><rect x="3" y="4" width="18" height="16" /><path d="M3 12h18" /></>)
export const Search = make(() => <><circle cx="10.5" cy="10.5" r="6.5" /><path d="M15.2 15.2L20 20" /></>)
export const Send = make(() => <><path d="M21 3L3 10.5l7.5 3L13.5 21 21 3Z" /><path d="M10.5 13.5L21 3" /></>)
export const Share2 = make(() => <><circle cx="18" cy="5" r="2.5" /><circle cx="6" cy="12" r="2.5" /><circle cx="18" cy="19" r="2.5" /><path d="M8.3 10.7l7.4-4.4M8.3 13.3l7.4 4.4" /></>)
export const ShieldAlert = make(() => <><path d="M12 3L4 6.5v5.5c0 5 3.4 8.2 8 9.5 4.6-1.3 8-4.5 8-9.5V6.5L12 3Z" /><path d="M12 8.5v4.5M12 16h.01" /></>)
export const ShieldCheck = make(() => <><path d="M12 3L4 6.5v5.5c0 5 3.4 8.2 8 9.5 4.6-1.3 8-4.5 8-9.5V6.5L12 3Z" /><path d="M8.5 12l2.3 2.3L15.5 9.5" /></>)
export const ShieldX = make(() => <><path d="M12 3L4 6.5v5.5c0 5 3.4 8.2 8 9.5 4.6-1.3 8-4.5 8-9.5V6.5L12 3Z" /><path d="M9.5 9.5l5 5M14.5 9.5l-5 5" /></>)
export const SlidersHorizontal = make(() => <path d="M4 6h9M17 6h3M15 4v4M4 12h3M11 12h9M9 10v4M4 18h11M19 18h1M17 16v4" />)
export const Sparkles = make(() => <><path d="M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2L12 3Z" /><path d="M19 3v4M17 5h4" /></>)
export const Square = make((w) => <rect x="4" y="4" width="16" height="16" fill={w === 'fill' ? 'currentColor' : 'none'} />)
export const Terminal = make(() => <><rect x="3" y="4" width="18" height="16" /><path d="M7 9l3.5 3L7 15M12.5 15H17" /></>)
export const Trash2 = make(() => <path d="M4 6h16M9 6V4h6v2M6 6v14h12V6M10 10v6M14 10v6" />)
export const Workflow = make(() => <><rect x="3" y="3" width="6" height="6" /><rect x="15" y="15" width="6" height="6" /><path d="M9 6h6v9M6 9v9h9" /></>)
export const Wrench = make(() => <path d="M14.7 6.3a4.5 4.5 0 0 0-5.8 5.8L4 17l3 3 4.9-4.9a4.5 4.5 0 0 0 5.8-5.8l-2.6 2.6-2.4-2.4 2-3.2Z" />)
export const X = make(() => <path d="M6 6l12 12M18 6L6 18" />)
export const Zap = make(() => <polygon points="13 2 4 14 11 14 10 22 20 10 13 10 13 2" />)
export const Columns3 = make(() => <><rect x="3" y="4" width="18" height="16" /><path d="M9 4v16M15 4v16" /></>)
export const List = make(() => <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" />)
export const ScanSearch = make(() => <><path d="M4 8V4h4M16 4h4v4M4 16v4h4M20 16v4h-4" /><circle cx="11.5" cy="11.5" r="3.5" /><path d="M14.2 14.2L17 17" /></>)
export const ListPlus = make(() => <path d="M4 6h16M4 12h10M4 18h10M18 14v6M15 17h6" />)
export const Repeat2 = make(() => <><path d="M17 4l3 3-3 3" /><path d="M4 11V7h16" /><path d="M7 20l-3-3 3-3" /><path d="M20 13v4H4" /></>)
export const Gear = make(() => <><circle cx="12" cy="12" r="3.2" /><path d="M12 2.5v2.3M12 19.2v2.3M2.5 12h2.3M19.2 12h2.3M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6" /><circle cx="12" cy="12" r="7.2" /></>)
export const Users = make(() => <><circle cx="9" cy="8" r="3.5" /><path d="M3 19v-1.5A4.5 4.5 0 0 1 7.5 13h3A4.5 4.5 0 0 1 15 17.5V19" /><circle cx="16.5" cy="8.5" r="2.5" /><path d="M17 13h1a3 3 0 0 1 3 3v3" /></>)
export const Quote = make(() => <path d="M4 7h6v6H6.5L5 17h3M14 7h6v6h-3.5L15 17h3" />)
export const GripVertical = make(() => <><rect x="8.5" y="4.5" width="1.5" height="1.5" fill="currentColor" /><rect x="14" y="4.5" width="1.5" height="1.5" fill="currentColor" /><rect x="8.5" y="11.25" width="1.5" height="1.5" fill="currentColor" /><rect x="14" y="11.25" width="1.5" height="1.5" fill="currentColor" /><rect x="8.5" y="18" width="1.5" height="1.5" fill="currentColor" /><rect x="14" y="18" width="1.5" height="1.5" fill="currentColor" /></>)
export const Gauge = make(() => <><path d="M4.5 18a9 9 0 1 1 15 0" /><path d="M12 13l4-4" /><circle cx="12" cy="13" r="1.5" /></>)
export const MoreHorizontal = make(() => <><rect x="4.5" y="11" width="2" height="2" fill="currentColor" /><rect x="11" y="11" width="2" height="2" fill="currentColor" /><rect x="17.5" y="11" width="2" height="2" fill="currentColor" /></>)
