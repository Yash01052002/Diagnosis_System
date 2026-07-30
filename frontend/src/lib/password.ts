// Mirrors the backend password policy (app/schemas/user.py) so a weak password
// is caught before a round-trip. The server remains the source of truth.
export const PASSWORD_MIN_LENGTH = 10;

export function passwordProblem(value: string): string | null {
  if (value.length < PASSWORD_MIN_LENGTH)
    return `Password must be at least ${PASSWORD_MIN_LENGTH} characters.`;
  const missing: string[] = [];
  if (!/[A-Z]/.test(value)) missing.push("an uppercase letter");
  if (!/[a-z]/.test(value)) missing.push("a lowercase letter");
  if (!/\d/.test(value)) missing.push("a digit");
  if (!/[^A-Za-z0-9]/.test(value)) missing.push("a special character");
  if (missing.length) return "Password must contain " + missing.join(", ") + ".";
  return null;
}
