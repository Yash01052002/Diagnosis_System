import { useState } from "react";
import { useAuth } from "../auth/useAuth";
import { authApi, usersApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { PageHeader } from "../components/page";
import { Card, CardBody, CardHeader } from "../components/Card";
import { Button } from "../components/Button";
import { Input } from "../components/Input";
import { Badge } from "../components/Badge";
import { Alert } from "../components/feedback";
import { passwordProblem } from "../lib/password";
import { formatDateTime } from "../lib/format";

export function ProfilePage() {
  const { user, setUser, logout } = useAuth();

  // Profile form
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [profileMsg, setProfileMsg] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const [savingProfile, setSavingProfile] = useState(false);

  // Password form
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [pwMsg, setPwMsg] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const [savingPw, setSavingPw] = useState(false);

  if (!user) return null;

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    setProfileMsg(null);
    setSavingProfile(true);
    try {
      const updated = await usersApi.updateMe({
        full_name: fullName || null,
        email,
      });
      setUser(updated);
      setProfileMsg({ tone: "success", text: "Profile updated." });
    } catch (err) {
      setProfileMsg({ tone: "danger", text: errorMessage(err) });
    } finally {
      setSavingProfile(false);
    }
  }

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwMsg(null);
    const problem = passwordProblem(next);
    if (problem) {
      setPwMsg({ tone: "danger", text: problem });
      return;
    }
    setSavingPw(true);
    try {
      await authApi.changePassword(current, next);
      setCurrent("");
      setNext("");
      setPwMsg({
        tone: "success",
        text: "Password changed. Other sessions were signed out.",
      });
    } catch (err) {
      setPwMsg({ tone: "danger", text: errorMessage(err) });
    } finally {
      setSavingPw(false);
    }
  }

  return (
    <>
      <PageHeader title="Your profile" subtitle={user.email} />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Account details" />
          <CardBody>
            <form onSubmit={saveProfile} className="flex flex-col gap-4">
              {profileMsg && <Alert tone={profileMsg.tone}>{profileMsg.text}</Alert>}
              <Input label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
              <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-muted">Roles:</span>
                {user.roles.map((r) => (
                  <Badge key={r.id} tone="brand">
                    {r.name}
                  </Badge>
                ))}
              </div>
              <div className="text-sm text-muted">
                Member since {formatDateTime(user.created_at)} · Last login{" "}
                {formatDateTime(user.last_login_at)}
              </div>
              <div>
                <Button type="submit" loading={savingProfile}>
                  Save changes
                </Button>
              </div>
            </form>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Change password" />
          <CardBody>
            <form onSubmit={changePassword} className="flex flex-col gap-4">
              {pwMsg && <Alert tone={pwMsg.tone}>{pwMsg.text}</Alert>}
              <Input
                label="Current password"
                type="password"
                autoComplete="current-password"
                required
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
              />
              <Input
                label="New password"
                type="password"
                autoComplete="new-password"
                required
                value={next}
                onChange={(e) => setNext(e.target.value)}
              />
              <div className="flex items-center justify-between">
                <Button type="submit" loading={savingPw}>
                  Update password
                </Button>
                <Button type="button" variant="ghost" onClick={() => void logout(true)}>
                  Sign out everywhere
                </Button>
              </div>
            </form>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
