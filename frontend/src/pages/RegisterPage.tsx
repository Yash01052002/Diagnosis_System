import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { authApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { AuthLayout } from "../components/AuthLayout";
import { Button } from "../components/Button";
import { Input } from "../components/Input";
import { Alert } from "../components/feedback";
import { passwordProblem, PASSWORD_MIN_LENGTH } from "../lib/password";

export function RegisterPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/dashboard" replace />;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const problem = passwordProblem(password);
    if (problem) {
      setError(problem);
      return;
    }
    setSubmitting(true);
    try {
      await authApi.register({
        email,
        password,
        full_name: fullName || undefined,
      });
      // New accounts get the viewer role; sign straight in.
      await login(email, password);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle="New accounts start with read-only access."
      footer={
        <>
          Already registered?{" "}
          <Link to="/login" className="font-medium text-brand-600 hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        {error && <Alert>{error}</Alert>}
        <Input
          label="Full name"
          autoComplete="name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
        />
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Input
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint={`At least ${PASSWORD_MIN_LENGTH} characters with upper, lower, digit and a symbol.`}
        />
        <Button type="submit" loading={submitting} className="w-full">
          Create account
        </Button>
      </form>
    </AuthLayout>
  );
}
