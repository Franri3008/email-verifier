type IconProps = { size?: number; className?: string };

const base = (size: number, className?: string) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  className,
  "aria-hidden": true,
});

export function SearchIcon({ size = 18, className }: IconProps) {
  return <svg {...base(size, className)}><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></svg>;
}

export function UploadIcon({ size = 20, className }: IconProps) {
  return <svg {...base(size, className)}><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" /><path d="M5 14v5h14v-5" /></svg>;
}

export function SendIcon({ size = 19, className }: IconProps) {
  return <svg {...base(size, className)}><path d="m5 12 14-7-4.5 14-3-5.5L5 12Z" /><path d="m11.5 13.5 3.6-3.6" /></svg>;
}

export function DownloadIcon({ size = 18, className }: IconProps) {
  return <svg {...base(size, className)}><path d="M12 4v11m0 0 4-4m-4 4-4-4" /><path d="M5 19h14" /></svg>;
}

export function SunIcon({ size = 18, className }: IconProps) {
  return <svg {...base(size, className)}><circle cx="12" cy="12" r="3.5" /><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>;
}

export function MoonIcon({ size = 18, className }: IconProps) {
  return <svg {...base(size, className)}><path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z" /></svg>;
}

export function FileIcon({ size = 18, className }: IconProps) {
  return <svg {...base(size, className)}><path d="M7 3h7l4 4v14H7z" /><path d="M14 3v5h5M9.5 13h5m-5 3h5" /></svg>;
}

export function CheckIcon({ size = 18, className }: IconProps) {
  return <svg {...base(size, className)}><path d="m5 12.5 4.2 4L19 7" /></svg>;
}

export function ChevronIcon({ size = 15, className }: IconProps) {
  return <svg {...base(size, className)}><path d="m8 10 4 4 4-4" /></svg>;
}

export function CloseIcon({ size = 18, className }: IconProps) {
  return <svg {...base(size, className)}><path d="m7 7 10 10M17 7 7 17" /></svg>;
}

export function AlertIcon({ size = 18, className }: IconProps) {
  return <svg {...base(size, className)}><path d="M12 4.5 2.8 20h18.4L12 4.5Z" /><path d="M12 10v4.2m0 2.6h.01" /></svg>;
}

export function QuestionIcon({ size = 18, className }: IconProps) {
  return <svg {...base(size, className)}><circle cx="12" cy="12" r="8.5" /><path d="M9.7 9.6a2.3 2.3 0 1 1 3.2 2.2c-.6.3-.9.8-.9 1.5v.4m0 2.3h.01" /></svg>;
}

export function JobsIcon({ size = 18, className }: IconProps) {
  return <svg {...base(size, className)}><path d="M4 7.5h16v12H4z" /><path d="M9 7.5V5.5h6v2M4 12h16" /></svg>;
}

export function SettingsIcon({ size = 18, className }: IconProps) {
  // Sliders, not a gear: a gear reads as the sun in the theme toggle beside it.
  return <svg {...base(size, className)}><path d="M4 7.5h4.5m3 0H20M4 16.5h9.5m3 0H20" /><circle cx="10" cy="7.5" r="2" /><circle cx="15" cy="16.5" r="2" /></svg>;
}

export function PeopleIcon({ size = 18, className }: IconProps) {
  return <svg {...base(size, className)}><circle cx="9.5" cy="8.5" r="3.2" /><path d="M3.5 19.5c0-3.1 2.7-5 6-5s6 1.9 6 5" /><path d="M16.5 6.4a3 3 0 0 1 0 5.8m1.4 2.6c1.7.6 2.9 2 2.9 4.1" /></svg>;
}

export function SignOutIcon({ size = 18, className }: IconProps) {
  return <svg {...base(size, className)}><path d="M14 4.5H6v15h8" /><path d="M18.5 12H11m7.5 0-3-3m3 3-3 3" /></svg>;
}

export function CopyIcon({ size = 18, className }: IconProps) {
  return <svg {...base(size, className)}><path d="M9 9h10v11H9z" /><path d="M15 9V4H5v11h4" /></svg>;
}


// Official OpenRouter glyph, taken from openrouter.ai/brand/v2/openrouter-{dark,light}.svg
// (the lockup's mark, wordmark dropped). Brand colours are set in CSS per theme.
export function OpenRouterMark({ size = 14, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size * (365.56 / 258.3)}
      height={size}
      viewBox="19.82 17.2 365.56 258.3"
      fill="currentColor"
      className={className}
      aria-hidden="true"
    >
      <path d="M303.9475,17.19926c42.79734,0,77.48933,34.69327,77.48933,77.48933s-34.69199,77.48933-77.48933,77.48933l76.86166,76.86244c9.76367,9.76313,2.84903,26.45667-10.95697,26.45667h-220.88335c-71.32686,0-129.14889-57.82202-129.14889-129.14889S77.64197,17.19926,148.96884,17.19926h154.97866ZM148.96884,68.85881c-42.79607,0-77.48933,34.69327-77.48933,77.48933s34.69327,77.48933,77.48933,77.48933,77.48933-34.69327,77.48933-77.48933-34.69327-77.48933-77.48933-77.48933Z" />
    </svg>
  );
}
