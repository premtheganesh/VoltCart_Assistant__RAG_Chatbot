/** Small inline icons (no icon library needed). They inherit the text color. */

type Props = { className?: string };
const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  viewBox: "0 0 24 24",
  "aria-hidden": true,
};

export const Bolt = ({ className }: Props) => (
  <svg viewBox="0 0 24 24" aria-hidden className={className}>
    <path d="M13.5 2 4 14h6.5L9 22l10-13h-6.5z" fill="currentColor" />
  </svg>
);
export const Send = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);
export const ThumbUp = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M7 10v11H4V10zM7 10l4-8a3 3 0 0 1 3 3v4h5.5a2 2 0 0 1 2 2.3l-1.3 8A2 2 0 0 1 18.2 21H7" />
  </svg>
);
export const ThumbDown = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M17 14V3h3v11zM17 14l-4 8a3 3 0 0 1-3-3v-4H4.5a2 2 0 0 1-2-2.3l1.3-8A2 2 0 0 1 5.8 3H17" />
  </svg>
);
export const Headset = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M4 14v-2a8 8 0 0 1 16 0v2M4 14h3v6H5a1 1 0 0 1-1-1zM20 14h-3v6h2a1 1 0 0 0 1-1zM17 20a4 4 0 0 1-4 2h-1" />
  </svg>
);
export const Plus = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);
export const External = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
  </svg>
);
export const Close = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);
export const ArrowUp = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M12 19V5M6 11l6-6 6 6" />
  </svg>
);
export const ArrowRight = ({ className }: Props) => (
  <svg {...base} className={className}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);

/** VoltCart's mark: a bolt on a volt-green dot. */
export const Mark = ({ className }: Props) => (
  <svg viewBox="0 0 32 32" aria-hidden className={className}>
    <circle cx="16" cy="16" r="16" fill="var(--accent)" />
    <path d="M17.5 6 9.5 17.5h5.5L13.5 26l9-12h-5.5z" fill="var(--on-accent)" />
  </svg>
);
