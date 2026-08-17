# Security Report

This document describes the security controls implemented in the Archipelago Alerts backend, and the known gaps. It describes what the code does today — where a control is aspirational rather than implemented, it is listed under [Known Gaps](#known-gaps) instead of being described as if it were in place.

## Authentication and Authorization

### Discord OAuth2
- **Authorization Code Flow with PKCE**: Clients complete the Discord flow and post `code`, `redirect_uri`, and `code_verifier` to the backend, which exchanges them server-side. All three are required; a request missing any of them is rejected before any outbound call is made.
- **Redirect URI Validation**: The submitted `redirect_uri` is compared for exact equality against the server's configured `DISCORD_REDIRECT_URI`. A mismatch is logged and refused, so an attacker cannot redirect the authorization code elsewhere.
- **Client Secret Isolation**: `DISCORD_CLIENT_SECRET` lives only on the server. The mobile client never holds it, which is why the code exchange is proxied rather than performed on-device.
- **Minimal Scope**: Only the `identify` scope is requested. The backend stores the Discord id, username, and avatar hash — never email or credentials.

### JWT (JSON Web Tokens)
- **Signing**: Tokens are signed with HMAC-SHA256 using `SECRET_KEY`, and carry `user_id`, `iat`, `exp`, `jti`, and `type` claims.
- **Long-Lived by Design**: These are **not** short-lived tokens. A Discord-authenticated token lasts **90 days**; a guest token lasts **730 days** (2 years). This is a deliberate trade — the app is a background notification client, and forcing re-authentication would silently break push delivery for users who rarely open it.
- **Revocation is the Control**: Because expiry is long, the `JWTBlocklist` table is the real revocation mechanism rather than a backstop. Every authenticated request checks the token's `jti` against the blocklist in `routes/common.py::token_required`, so a logout or account deletion invalidates the token immediately rather than at expiry. Blocklist rows are purged by `retention_service` only after the token they revoke would have expired on its own.
- **Guest Upgrade Path**: When a guest authenticates with Discord, the existing guest account is upgraded under a row-level lock rather than duplicated, so tracked rooms survive the transition without creating a second identity.

## API Security

### SSRF Protection
The backend fetches room state from user-supplied hostnames, which makes SSRF the primary risk surface. It is handled at the connector layer rather than by validating strings at the route:

- **Resolution-Time IP Validation**: `SSRFProtectedResolver` (in `app/utils.py`) subclasses the aiohttp resolver and runs `_validate_ip` against **every** address DNS returns, before a connection is opened. `SSRFProtectedTCPConnector` additionally validates literal IP hosts. This closes the DNS-rebinding gap that string-level hostname checks leave open.
- **Blocked Ranges**: `_validate_ip` rejects private, loopback, link-local, multicast, and reserved addresses, and anything not globally routable. `169.254.169.254` is rejected explicitly with its own error, so a user cannot aim the poller at cloud instance metadata.
- **Applied Everywhere Outbound**: The protected connector is used by the poller's shared aiohttp session, by `verify_ap_server` during room setup, and by the datapackage fetches in `game_routes`. Room verification therefore runs through the same guard as ongoing polling.
- **Development Exemption**: When `FLASK_ENV=development`, loopback and private addresses are permitted so a developer can point the backend at a local Archipelago server. This exemption is keyed on the environment variable — a production deployment must not set `FLASK_ENV=development`.

### Input Validation
- **Length Caps**: `room_url` is capped at 512 characters and `alias` at 128 on the room-creation path; oversized input is rejected with a 400 before any parsing or network call.
- **Type Coercion is Explicit**: Ambiguous fields such as `is_group` accept a bool or a recognized string form and reject anything else with a 400, rather than falling back to a truthiness check.
- **Parameterized Queries**: All data access goes through the SQLAlchemy ORM or bound parameters. No user input is concatenated into SQL.
- **Safe JSON Parsing**: All JSON is parsed with `json.loads`. The application never uses `pickle` or another unsafe deserialization format.

### Error Handling
- **Generic Client-Facing Messages**: `handle_db_errors` maps `OperationalError` to a 503 "Database is busy", `IntegrityError` to a 409, and everything else to a generic 500. Exception text is never returned to the client.
- **Detailed Server-Side Logging**: Full tracebacks are logged with `exc_info=True` for diagnosis.
- **Session Rollback**: Every error path rolls back and removes the scoped session in a `finally` block, so a failed request cannot leak a dirty transaction into the next one.

## Data Protection

### API Key Encryption
- **Fernet Encryption**: The `cheese_api_key` is encrypted with Fernet (AES-128-CBC with an HMAC-SHA256 authentication tag) before storage, so it is never at rest in plaintext and tampering is detectable.
- **Key Management**: The key comes from the `ENCRYPTION_KEY` environment variable and is not in version control. `_get_fernet` raises rather than falling back to a default if it is unset.
- **Fail-Closed Decryption**: A decryption failure — malformed ciphertext, or a rotated key — is logged and returns an empty string rather than raising into the caller, so a bad key degrades the Cheese integration instead of breaking unrelated requests.

### Database Security
- **Row-Level Locking**: The Discord login path selects the existing user `with_for_update()`, serializing concurrent logins for the same account so a double-submit cannot create duplicate users or clobber a guest upgrade mid-merge.
- **Data Retention**: `NotifiedItem` and `NotifiedHint` records are purged after 90 days, and guest accounts inactive for more than 90 days are deleted. Retained data is bounded by policy rather than growing indefinitely.
- **Migration Serialization**: Startup schema upgrades take a `pg_advisory_lock`, so the API and poller containers cannot apply migrations concurrently against the same database.

### Deployment
- **Non-Root Containers**: The image creates an unprivileged `appuser` and drops to it before running the application.
- **Resource Limits**: Both containers declare CPU and memory limits in Compose, bounding the blast radius of a runaway poll loop or a memory leak.
- **Secrets Outside the Image**: Credentials come from `backend/.env` via `env_file` and from mounted service-account JSON, not from anything baked into the image or committed.

## Known Gaps

These are accurate as of this revision and are listed so they are tracked rather than assumed handled:

- **No general rate limiting.** The only throttle in the codebase is a 30-second guard on room revival. Authentication, room creation, and history sync are unthrottled.
- **No security response headers.** The application sets no CSP, `X-Frame-Options`, `X-Content-Type-Options`, or HSTS headers on the server-rendered pages (landing, privacy policy, account deletion).
- **`ALLOWED_HOSTNAMES` is dead configuration.** It is parsed into `app.config` in `create_app()` and never read. It is not a hostname allowlist and provides no protection; SSRF is handled entirely by the IP-level controls described above. Either wire it up or remove it.
- **Development exemptions are environment-gated.** Both the SSRF exemption and the http/https downgrade in `get_web_base_url` key off `FLASK_ENV=development`. There is no second check, so the safety of production rests on that variable being set correctly.
- **Single shared signing secret.** `SECRET_KEY` signs all tokens with no key-rotation mechanism; rotating it invalidates every outstanding token at once.

## Operational Practices

- **Dependency Management**: Dependencies are pinned in `requirements.txt` and `backend/requirements.txt` and should be reviewed for advisories on a regular cadence.
- **Regular Security Audits**: The codebase should be audited periodically, and this document updated when controls change — including moving items out of Known Gaps as they are closed.
- **Principle of Least Privilege**: Run the application with the minimum privileges necessary; the container already drops to a non-root user.
