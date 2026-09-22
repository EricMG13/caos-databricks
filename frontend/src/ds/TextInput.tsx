// Shared text input — the single-line field idiom used across the workspace.
// Consolidates the CAOS field chrome: bg/border/rounded, muted placeholder,
// accent focus border, and the keyboard `.focus-ring`, so every field focuses
// and reads identically. Pass width/padding/size via `className`.

import { forwardRef, type InputHTMLAttributes } from "react";

export const INPUT_BASE =
  "bg-caos-bg border border-caos-border rounded text-caos-text placeholder:text-caos-muted " +
  "outline-none focus:border-caos-accent/70 transition-caos focus-ring";

export const TextInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function TextInput({ className = "", ...props }, ref) {
    return (
      <input ref={ref} className={INPUT_BASE + (className ? " " + className : "")} {...props} />
    );
  },
);
