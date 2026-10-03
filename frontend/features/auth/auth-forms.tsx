"use client";

import { Eye, EyeOff } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useId, useState, type FormEvent, type InputHTMLAttributes } from "react";

import { isApiError } from "@/services/api/errors";

import { useAuth } from "./auth-context";
import {
  MAX_NAME_LENGTH,
  MAX_PASSWORD_LENGTH,
  MIN_PASSWORD_LENGTH,
  normalizeEmail,
  validateEmail,
  validateName,
  validateNewPassword,
} from "./validation";

type Errors<K extends string> = Partial<Record<K, string>>;

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
}

function Field({ label, error, hint, id, ...input }: FieldProps) {
  const generated = useId();
  const inputId = id ?? generated;
  const describedBy = error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined;
  return (
    <div>
      <label htmlFor={inputId} className="block text-xs text-fg-muted">
        {label}
      </label>
      <input
        id={inputId}
        aria-invalid={!!error}
        aria-describedby={describedBy}
        className="mt-1 w-full rounded border border-border bg-surface-sunken px-2.5 py-2 text-sm text-fg outline-none placeholder:text-fg-subtle focus:border-accent aria-[invalid=true]:border-danger"
        {...input}
      />
      {error ? (
        <p id={`${inputId}-error`} className="mt-1 text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="mt-1 text-[11px] text-fg-subtle">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function PasswordField(props: Omit<FieldProps, "type">) {
  const [visible, setVisible] = useState(false);
  const generated = useId();
  const id = props.id ?? generated;
  return (
    <div className="relative">
      <Field {...props} id={id} type={visible ? "text" : "password"} />
      <button
        type="button"
        onClick={() => setVisible((value) => !value)}
        aria-label={visible ? "Hide password" : "Show password"}
        aria-controls={id}
        aria-pressed={visible}
        className="absolute top-[1.4rem] right-1 inline-flex size-8 items-center justify-center rounded text-fg-muted hover:text-fg"
      >
        {visible ? (
          <EyeOff aria-hidden className="size-4" />
        ) : (
          <Eye aria-hidden className="size-4" />
        )}
      </button>
    </div>
  );
}

function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger"
    >
      {message}
    </p>
  );
}

function SubmitButton({
  busy,
  label,
  busyLabel,
}: {
  busy: boolean;
  label: string;
  busyLabel: string;
}) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="w-full rounded bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-strong disabled:opacity-60"
    >
      {busy ? busyLabel : label}
    </button>
  );
}

function errorText(error: unknown, fallback: string): string {
  if (!isApiError(error)) return fallback;
  if (error.kind === "network" || error.kind === "timeout")
    return "The CodeWalk backend is not reachable. Check that it is running and try again.";
  if (error.code === "validation_error")
    return "Some fields are invalid. Check them and try again.";
  return error.message;
}

/** Keeps `?next=` when switching between the login and registration pages. */
function useAuthLink(path: "/login" | "/register"): string {
  const next = useSearchParams().get("next");
  return next ? `${path}?next=${encodeURIComponent(next)}` : path;
}

export function LoginForm() {
  const { login, sessionExpired } = useAuth();
  const registerHref = useAuthLink("/register");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Errors<"email" | "password">>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const next: Errors<"email" | "password"> = {
      email: validateEmail(email) ?? undefined,
      password: password ? undefined : "Enter your password.",
    };
    setErrors(next);
    setFormError(null);
    if (next.email || next.password) return;
    setBusy(true);
    try {
      await login({ email: normalizeEmail(email), password });
      // The page guard redirects once the session is established.
    } catch (error) {
      setFormError(errorText(error, "Sign-in failed. Try again."));
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate className="space-y-4" aria-labelledby="auth-title">
      <div>
        <h1 id="auth-title" className="text-base font-semibold text-fg">
          Sign in
        </h1>
        <p className="mt-1 text-xs text-fg-muted">
          Use the email and password of your CodeWalk account.
        </p>
      </div>
      {sessionExpired && !formError && (
        <p
          role="status"
          className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning"
        >
          Your session ended. Sign in again to continue.
        </p>
      )}
      <FormError message={formError} />
      <Field
        label="Email"
        type="email"
        autoComplete="email"
        autoFocus
        value={email}
        disabled={busy}
        error={errors.email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <PasswordField
        label="Password"
        autoComplete="current-password"
        value={password}
        disabled={busy}
        maxLength={MAX_PASSWORD_LENGTH}
        error={errors.password}
        onChange={(event) => setPassword(event.target.value)}
      />
      <SubmitButton busy={busy} label="Sign in" busyLabel="Signing in…" />
      <p className="text-center text-xs text-fg-muted">
        No account yet?{" "}
        <Link href={registerHref} className="text-accent hover:underline">
          Create one
        </Link>
      </p>
    </form>
  );
}

export function RegisterForm() {
  const { register } = useAuth();
  const loginHref = useAuthLink("/login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Errors<"name" | "email" | "password" | "confirm">>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const next = {
      name: validateName(name) ?? undefined,
      email: validateEmail(email) ?? undefined,
      password: validateNewPassword(password, email) ?? undefined,
      confirm: confirm === password ? undefined : "The passwords do not match.",
    };
    setErrors(next);
    setFormError(null);
    if (Object.values(next).some(Boolean)) return;
    setBusy(true);
    try {
      await register({ name: name.trim(), email: normalizeEmail(email), password });
    } catch (error) {
      if (isApiError(error) && error.code === "email_taken") {
        setErrors({ email: "An account with this email already exists. Sign in instead." });
      } else {
        setFormError(errorText(error, "The account could not be created. Try again."));
      }
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} noValidate className="space-y-4" aria-labelledby="auth-title">
      <div>
        <h1 id="auth-title" className="text-base font-semibold text-fg">
          Create your account
        </h1>
        <p className="mt-1 text-xs text-fg-muted">
          Your projects and history are private to this account.
        </p>
      </div>
      <FormError message={formError} />
      <Field
        label="Name"
        autoComplete="name"
        autoFocus
        value={name}
        disabled={busy}
        maxLength={MAX_NAME_LENGTH + 20}
        error={errors.name}
        onChange={(event) => setName(event.target.value)}
      />
      <Field
        label="Email"
        type="email"
        autoComplete="email"
        value={email}
        disabled={busy}
        error={errors.email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <PasswordField
        label="Password"
        autoComplete="new-password"
        value={password}
        disabled={busy}
        maxLength={MAX_PASSWORD_LENGTH}
        error={errors.password}
        hint={`At least ${MIN_PASSWORD_LENGTH} characters, with a letter and a number or symbol.`}
        onChange={(event) => setPassword(event.target.value)}
      />
      <PasswordField
        label="Confirm password"
        autoComplete="new-password"
        value={confirm}
        disabled={busy}
        maxLength={MAX_PASSWORD_LENGTH}
        error={errors.confirm}
        onChange={(event) => setConfirm(event.target.value)}
      />
      <SubmitButton busy={busy} label="Create account" busyLabel="Creating account…" />
      <p className="text-center text-xs text-fg-muted">
        Already have an account?{" "}
        <Link href={loginHref} className="text-accent hover:underline">
          Sign in
        </Link>
      </p>
    </form>
  );
}
