export function LogoMark({ className = "size-5" }: { className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className={`text-accent ${className}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
    >
      <path
        d="M8 6 3 12l5 6M16 6l5 6-5 6M13.5 4l-3 16"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
