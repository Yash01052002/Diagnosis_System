import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import { AuthLayout } from "../components/AuthLayout";
import { Button } from "../components/Button";
import { Input } from "../components/Input";
import { Alert } from "../components/feedback";
import { errorMessage } from "../api/client";

interface LocationState {
  from?: { pathname: string };
}

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const from = (location.state as LocationState | null)?.from?.pathname ?? "/devices";
  if (user) return <Navigate to={from} replace />;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Access the crash diagnosis platform."
      footer={
        <>
          Need an account?{" "}
          <Link to="/register" className="font-medium text-brand-600 hover:underline">
            Register
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        {error && <Alert>{error}</Alert>}
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
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <div className="text-right">
          <Link to="/forgot-password" className="text-sm text-brand-600 hover:underline">
            Forgot password?
          </Link>
        </div>
        <Button type="submit" loading={submitting} className="w-full">
          Sign in
        </Button>
      </form>
    </AuthLayout>
  );
}
