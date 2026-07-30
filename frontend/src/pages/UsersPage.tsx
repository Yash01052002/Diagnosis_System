import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { usersApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { useDebounce } from "../lib/useDebounce";
import { formatRelative } from "../lib/format";
import { passwordProblem } from "../lib/password";
import { PageHeader } from "../components/page";
import { Card } from "../components/Card";
import { Button } from "../components/Button";
import { Input, Select } from "../components/Input";
import { Modal, ConfirmDialog } from "../components/Modal";
import { Badge } from "../components/Badge";
import { Pagination } from "../components/Pagination";
import { Table, TBody, TD, TH, THead, TR } from "../components/Table";
import { Alert, EmptyState, ErrorState, LoadingState } from "../components/feedback";
import type { RoleName, User } from "../api/types";

const ROLE_OPTIONS: RoleName[] = ["viewer", "engineer", "admin"];

export function UsersPage() {
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("");
  const [page, setPage] = useState(1);
  const [showCreate, setShowCreate] = useState(false);
  const [editUser, setEditUser] = useState<User | null>(null);
  const q = useDebounce(search);

  const query = useQuery({
    queryKey: ["users", { q, role, page }],
    queryFn: () => usersApi.list({ q, role: role || undefined, page, page_size: 20 }),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader
        title="Users"
        subtitle="Manage platform accounts and their roles."
        actions={<Button onClick={() => setShowCreate(true)}>Add user</Button>}
      />

      <Card className="mb-4 p-3">
        <div className="flex flex-col gap-3 sm:flex-row">
          <Input
            placeholder="Search by email or name…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="sm:max-w-xs"
          />
          <Select
            value={role}
            onChange={(e) => {
              setRole(e.target.value);
              setPage(1);
            }}
            className="sm:max-w-[12rem]"
          >
            <option value="">All roles</option>
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r} className="capitalize">
                {r}
              </option>
            ))}
          </Select>
        </div>
      </Card>

      <Card>
        {query.isLoading ? (
          <LoadingState />
        ) : query.isError ? (
          <ErrorState message={errorMessage(query.error)} onRetry={() => query.refetch()} />
        ) : query.data && query.data.items.length > 0 ? (
          <>
            <Table>
              <THead>
                <TR>
                  <TH>User</TH>
                  <TH>Roles</TH>
                  <TH>State</TH>
                  <TH>Last login</TH>
                  <TH />
                </TR>
              </THead>
              <TBody>
                {query.data.items.map((u) => (
                  <TR key={u.id}>
                    <TD>
                      <div className="font-medium">{u.full_name || "—"}</div>
                      <div className="text-xs text-muted">{u.email}</div>
                    </TD>
                    <TD>
                      <div className="flex flex-wrap gap-1">
                        {u.roles.map((r) => (
                          <Badge key={r.id} tone="brand">
                            {r.name}
                          </Badge>
                        ))}
                      </div>
                    </TD>
                    <TD>
                      {u.is_active ? (
                        <span className="text-xs text-emerald-500">active</span>
                      ) : (
                        <span className="text-xs text-red-500">disabled</span>
                      )}
                    </TD>
                    <TD className="text-muted">{formatRelative(u.last_login_at)}</TD>
                    <TD>
                      <Button size="sm" variant="ghost" onClick={() => setEditUser(u)}>
                        Manage
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <div className="px-3">
              <Pagination
                page={query.data.page}
                pages={query.data.pages}
                total={query.data.total}
                onChange={setPage}
              />
            </div>
          </>
        ) : (
          <EmptyState title="No users found" hint="Adjust your search or add a user." />
        )}
      </Card>

      {showCreate && <CreateUserModal onClose={() => setShowCreate(false)} />}
      {editUser && <ManageUserModal user={editUser} onClose={() => setEditUser(null)} />}
    </>
  );
}

function CreateUserModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    email: "",
    full_name: "",
    password: "",
    roles: ["viewer"] as string[],
    is_active: true,
  });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      usersApi.create({
        email: form.email,
        full_name: form.full_name || undefined,
        password: form.password,
        roles: form.roles,
        is_active: form.is_active,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
    onError: (err) => setError(errorMessage(err)),
  });

  function submit() {
    setError(null);
    const problem = passwordProblem(form.password);
    if (problem) {
      setError(problem);
      return;
    }
    mutation.mutate();
  }

  return (
    <Modal
      open
      title="Add user"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} loading={mutation.isPending}>
            Create
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {error && <Alert>{error}</Alert>}
        <Input label="Email" type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} required />
        <Input label="Full name" value={form.full_name} onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} />
        <Input
          label="Temporary password"
          type="password"
          value={form.password}
          onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
          required
        />
        <RolePicker
          value={form.roles}
          onChange={(roles) => setForm((f) => ({ ...f, roles }))}
        />
      </div>
    </Modal>
  );
}

function ManageUserModal({ user, onClose }: { user: User; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { user: me } = useAuth();
  const isSelf = me?.id === user.id;
  const [roles, setRoles] = useState<string[]>(user.roles.map((r) => r.name));
  const [isActive, setIsActive] = useState(user.is_active);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const update = useMutation({
    mutationFn: () => usersApi.update(user.id, { roles, is_active: isActive }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
    onError: (err) => setError(errorMessage(err)),
  });

  const remove = useMutation({
    mutationFn: () => usersApi.remove(user.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
    onError: (err) => setError(errorMessage(err)),
  });

  return (
    <Modal
      open
      title="Manage user"
      onClose={onClose}
      footer={
        <>
          {!isSelf && (
            <Button variant="danger" onClick={() => setConfirmDelete(true)} className="mr-auto">
              Delete
            </Button>
          )}
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => update.mutate()} loading={update.isPending}>
            Save
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {error && <Alert>{error}</Alert>}
        <div>
          <div className="text-sm font-medium">{user.full_name || user.email}</div>
          <div className="text-xs text-muted">{user.email}</div>
        </div>
        <RolePicker value={roles} onChange={setRoles} />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={isActive}
            disabled={isSelf}
            onChange={(e) => setIsActive(e.target.checked)}
            className="h-4 w-4"
          />
          Active account
        </label>
        {isSelf && (
          <p className="text-xs text-muted">
            You cannot deactivate or delete your own account.
          </p>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete user"
        danger
        confirmLabel="Delete"
        loading={remove.isPending}
        message={
          <>
            Permanently delete <strong>{user.email}</strong>?
          </>
        }
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => remove.mutate()}
      />
    </Modal>
  );
}

function RolePicker({
  value,
  onChange,
}: {
  value: string[];
  onChange: (roles: string[]) => void;
}) {
  function toggle(role: string) {
    onChange(value.includes(role) ? value.filter((r) => r !== role) : [...value, role]);
  }
  return (
    <div>
      <div className="mb-1 text-sm font-medium">Roles</div>
      <div className="flex flex-wrap gap-2">
        {ROLE_OPTIONS.map((r) => {
          const active = value.includes(r);
          return (
            <button
              key={r}
              type="button"
              onClick={() => toggle(r)}
              className={
                "rounded-full border px-3 py-1 text-sm capitalize transition-colors " +
                (active
                  ? "border-brand-600 bg-brand-600 text-white"
                  : "border-token surface text-muted hover:surface-2")
              }
            >
              {r}
            </button>
          );
        })}
      </div>
    </div>
  );
}
