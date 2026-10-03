/**
 * Client-side checks that mirror the backend rules (backend `app.schemas.auth`).
 * They give immediate feedback; the backend still validates everything.
 */

export const MIN_PASSWORD_LENGTH = 8;
export const MAX_PASSWORD_LENGTH = 128;
export const MAX_NAME_LENGTH = 100;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

export function validateEmail(email: string): string | null {
  const value = normalizeEmail(email);
  if (!value) return "Enter your email address.";
  if (value.length > 320 || !EMAIL_PATTERN.test(value)) return "Enter a valid email address.";
  return null;
}

export function validateName(name: string): string | null {
  const value = name.trim();
  if (!value) return "Enter your name.";
  if (value.length > MAX_NAME_LENGTH) return `Use at most ${MAX_NAME_LENGTH} characters.`;
  return null;
}

export function validateNewPassword(password: string, email = ""): string | null {
  if (password.length < MIN_PASSWORD_LENGTH)
    return `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  if (password.length > MAX_PASSWORD_LENGTH)
    return `Use at most ${MAX_PASSWORD_LENGTH} characters.`;
  if (!password.trim()) return "The password cannot be only spaces.";
  if (!/\p{L}/u.test(password)) return "Include at least one letter.";
  if (/^\p{L}+$/u.test(password)) return "Include at least one number or symbol.";
  if (new Set(password).size < 4) return "This password is too repetitive.";
  const normalized = normalizeEmail(email);
  const lowered = password.toLowerCase();
  if (normalized && (lowered === normalized || lowered === normalized.split("@")[0]))
    return "Don't use your email address as the password.";
  return null;
}
