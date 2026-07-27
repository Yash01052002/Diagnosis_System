# Sample API requests (curl)

Every example assumes the stack is running on `http://localhost:8000`.
Interactive documentation is at <http://localhost:8000/docs>.

All error responses share one envelope:

```json
{
  "error": {
    "code": "invalid_credentials",
    "message": "Incorrect email or password.",
    "details": { "...": "optional" }
  }
}
```

---

## 1. Health

```bash
curl -s http://localhost:8000/health | jq
# {"status":"ok","version":"0.1.0","environment":"local"}

curl -s http://localhost:8000/health/ready | jq
# {"status":"ok","version":"0.1.0","environment":"local",
#  "checks":{"database":"ok","redis":"ok"}}
```

`/health` never touches a dependency, so use it as the container liveness
probe. `/health/ready` returns **503** when PostgreSQL is unreachable; a Redis
outage is reported as `degraded` but still returns 200 because the API can
serve traffic without it.

---

## 2. Register

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{
        "email": "engineer@example.com",
        "password": "Str0ng!Passw0rd",
        "full_name": "Field Engineer"
      }' | jq
```

```json
{
  "id": "9f2c...",
  "email": "engineer@example.com",
  "full_name": "Field Engineer",
  "is_active": true,
  "is_verified": false,
  "roles": [{ "id": "...", "name": "viewer", "description": "..." }]
}
```

New accounts always get `viewer`. An admin grants higher roles afterwards.

Password policy: at least `PASSWORD_MIN_LENGTH` (default 10) characters with an
uppercase letter, a lowercase letter, a digit and a special character.

---

## 3. Log in

```bash
TOKENS=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@blackbox.example.com","password":"ChangeMe123!"}')

ACCESS=$(echo "$TOKENS"  | jq -r .access_token)
REFRESH=$(echo "$TOKENS" | jq -r .refresh_token)
```

```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": { "email": "admin@blackbox.example.com", "roles": [{ "name": "admin" }] }
}
```

After `MAX_FAILED_LOGIN_ATTEMPTS` consecutive failures the account is locked
for `ACCOUNT_LOCKOUT_MINUTES` and login returns **423**.

---

## 4. Authenticated requests

```bash
curl -s http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $ACCESS" | jq
```

---

## 5. Rotate tokens

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/refresh \
  -H 'Content-Type: application/json' \
  -d "{\"refresh_token\":\"$REFRESH\"}" | jq
```

Refresh tokens are **single use**: the presented token is revoked and a new
pair is issued. Replaying an old token returns **401** — which is also how
token theft surfaces.

---

## 6. Log out

```bash
# This session only
curl -s -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d "{\"refresh_token\":\"$REFRESH\"}" | jq

# Every session on every device
curl -s -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' \
  -d '{"all_sessions": true}' | jq
```

---

## 7. Password reset

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/forgot-password \
  -H 'Content-Type: application/json' \
  -d '{"email":"engineer@example.com"}' | jq
# {"message":"If an account exists for that email, a reset link has been sent."}
```

The response is identical whether or not the account exists, so the endpoint
cannot be used to enumerate users. With `EMAIL_BACKEND=console` the link is
printed to the backend log:

```bash
docker compose logs backend | grep reset-password
# .../reset-password?token=Q1p4...
```

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/reset-password \
  -H 'Content-Type: application/json' \
  -d '{"token":"Q1p4...","new_password":"N3w!Str0ngPass"}' | jq
```

The token is single use, expires after `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES`,
and completing a reset revokes every existing session.

---

## 8. User administration (admin only)

```bash
# List, search and filter
curl -s "http://localhost:8000/api/v1/users?page=1&page_size=20" -H "Authorization: Bearer $ACCESS" | jq
curl -s "http://localhost:8000/api/v1/users?q=engineer&role=engineer&is_active=true" -H "Authorization: Bearer $ACCESS" | jq

# Create
curl -s -X POST http://localhost:8000/api/v1/users \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"email":"engineer2@example.com","password":"Str0ng!Passw0rd",
       "full_name":"Engineer Two","roles":["engineer"]}' | jq

# Promote
curl -s -X PATCH "http://localhost:8000/api/v1/users/$USER_ID" \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"roles":["engineer"]}' | jq

# Deactivate (revokes the user's sessions immediately)
curl -s -X PATCH "http://localhost:8000/api/v1/users/$USER_ID" \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"is_active":false}' | jq

# Delete
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE \
  "http://localhost:8000/api/v1/users/$USER_ID" -H "Authorization: Bearer $ACCESS"
# 204
```

Paginated responses look like:

```json
{ "items": [ ... ], "total": 42, "page": 1, "page_size": 20, "pages": 3 }
```

A `viewer` or `engineer` calling these endpoints gets **403**:

```json
{ "error": { "code": "permission_denied",
             "message": "This action requires one of the following roles: admin",
             "details": { "required_roles": ["admin"] } } }
```

---

## 9. Self-service profile

```bash
curl -s -X PATCH http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"full_name":"Platform Administrator"}' | jq
```

A `roles` field in this payload is ignored — privilege escalation is not
possible through the self-service route.

---

## 10. Audit trail (admin only)

```bash
curl -s "http://localhost:8000/api/v1/audit-logs?action=user.login_failed" \
  -H "Authorization: Bearer $ACCESS" | jq '.items[0]'
```

```json
{
  "action": "user.login_failed",
  "actor_email": "engineer@example.com",
  "ip_address": "172.18.0.1",
  "success": false,
  "context": { "reason": "bad_password" },
  "created_at": "2026-07-27T09:14:22Z"
}
```
