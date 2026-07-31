import { Link } from "react-router-dom";
import { Button } from "../components/Button";

function StatusScreen({
  code,
  title,
  message,
}: {
  code: string;
  title: string;
  message: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
      <div className="text-6xl font-bold text-brand-600">{code}</div>
      <h1 className="text-xl font-semibold">{title}</h1>
      <p className="max-w-md text-sm text-muted">{message}</p>
      <Link to="/dashboard">
        <Button variant="secondary">Back to dashboard</Button>
      </Link>
    </div>
  );
}

export function NotFoundPage() {
  return (
    <StatusScreen
      code="404"
      title="Page not found"
      message="The page you were looking for does not exist or has moved."
    />
  );
}

export function ForbiddenPage() {
  return (
    <StatusScreen
      code="403"
      title="Access denied"
      message="Your account does not have permission to view this page. Ask an administrator if you need access."
    />
  );
}
