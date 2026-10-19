"use client";

import styles from "./ui.module.css";

export type FieldErrors = { username?: string; password?: string };

export function validateCredentials(form: HTMLFormElement, username: string, password: string): FieldErrors {
  const errors: FieldErrors = {};
  if (!username.trim()) errors.username = "Enter your username.";
  if (!password) errors.password = "Enter your password.";
  const first = errors.username ? "username" : errors.password ? "password" : null;
  const input = first && form.elements.namedItem(first);
  if (input instanceof HTMLElement) input.focus();
  return errors;
}

export function CredentialsFields({ username, password, setUsername, setPassword, busy, errors, errorId }: {
  username: string; password: string; setUsername: (value: string) => void; setPassword: (value: string) => void;
  busy: boolean; errors: FieldErrors; errorId?: string;
}) {
  return <div className={styles.credentials}>
    <div className={styles.field}><label htmlFor="signin-username">Username</label>
      <input id="signin-username" name="username" autoComplete="username" spellCheck={false} required maxLength={64}
        value={username} onChange={event => setUsername(event.target.value)} disabled={busy}
        aria-invalid={!!errors.username} aria-describedby={errors.username ? "username-error" : errorId} />
      {errors.username && <span id="username-error" className={styles.fieldError} role="alert">{errors.username}</span>}
    </div>
    <div className={styles.field}><label htmlFor="signin-password">Password</label>
      <input id="signin-password" name="password" type="password" autoComplete="current-password" required maxLength={128}
        value={password} onChange={event => setPassword(event.target.value)} disabled={busy}
        aria-invalid={!!errors.password} aria-describedby={errors.password ? "password-error" : errorId} />
      {errors.password && <span id="password-error" className={styles.fieldError} role="alert">{errors.password}</span>}
    </div>
  </div>;
}
