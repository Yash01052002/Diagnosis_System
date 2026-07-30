import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { authApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { AuthLayout } from "../components/AuthLayout";
import { Button } from "../components/Button";
import { Input } from "../components/Input";
import { Alert } from "../components/feedback";
import { passwordProblem } from "../lib/password";

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const tokenFromUrl = params.get("token") ?? "";
  const [token, setToken] = useState(tokenFromUrl);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    const problem = passwordProblem(password);
    if (problem) {
      setError(problem);
      return;
    }
    setSubmitting(true);
    try {
      await authApi.resetPassword(token, password);
      setDone(true);
      setTimeout(() => navigate("/login", { replace: true }), 1500);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout
      title="Set a new password"
      footer={
        <Link to="/login" className="font-medium text-brand-600 hover:underline">
          Back to sign in
        </Link>
      }
    >
      {done ? (
        <Alert tone="success">
          Password updated. Redirecting you to sign in…
        </Alert>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          {error && <Alert>{error}</Alert>}
          {!tokenFromUrl && (
            <Input
              label="Reset token"
              required
              value={token}
              onChange={(e) => setToken(e.target.value)}
              hint="Paste the token from your reset email."
            />
          )}
          <Input
            label="New password"
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Input
            label="Confirm password"
            type="password"
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          <Button type="submit" loading={submitting} className="w-full">
            Update password
          </Button>
        </form>
      )}
    </AuthLayout>
  );
}
