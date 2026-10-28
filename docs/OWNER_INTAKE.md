# Private owner intake

## Outcome and current step

Provide a discreet entrance from the public library to a separate passkey-only
owner service at `https://owner.bhakti.eeshan.xyz`. The owner can paste song links
and notes or load a UTF-8 text file, submit once, and see the durable private queue.
The public library stays on GitHub Pages. TimeCrystals authentication, credentials,
content and installed-app identity are unchanged.

The owner entrance is completely hidden: five ordinary taps/clicks on the About
heading, or the desktop keyboard shortcut. No public login control is rendered.
Owner enrollment and a real private submission were verified before this UI fix.

## User flow and design

- Tap the library's existing `?` button, then tap the About heading five times.
  Taps need not be fast. The fifth completed tap opens owner sign-in directly.
  No label, link, counter, hint or button advertises login. Other clicks, Escape,
  backgrounding and page restoration clear partial taps. No hold timer exists.
  `Alt/Option+Shift+O` remains the hidden desktop alternative outside editable fields.
- This entrance is discreet, not an authorization boundary. Knowing the URL or
  reading public source must never allow queue access or enrollment.
- Owner pages reuse Bhakti's burgundy ground, cream ink, serif headings, compact
  sans-serif controls, hairlines and visible keyboard focus. No public admin menu.
- Signed-out view offers one passkey sign-in action. Setup is a separate route
  requiring an owner-delivered one-time setup code, never open registration.
- Signed-in view contains a labelled text area, optional `.txt` import, submit,
  recent requests, export and sign out. Submitted text is rendered as text only.
  A failed submission retains the draft and request ID for a safe retry.
- Confirmation means the exact text is durably stored. State is `queued` and
  copy says processing is not connected yet. No model calls, URL fetching,
  workflow dispatch or publication is triggered by submission.

## Service boundary

Use a small Go CGI service with the maintained `go-webauthn` library and the
security patterns already exercised by TimeCrystals; do not copy its research
gateway. Embed the public owner HTML/CSS/JS in the binary. Keep all mutable state
outside every document root, with owner-only permissions and process-safe locking.
Never put actual hosting IPs, account names, absolute remote home paths, secrets,
requests or credentials in this public repository. Deployment uses `hostgator`.

The exact HTTPS origin and RP ID are `owner.bhakti.eeshan.xyz`. No parent-domain
RP, CORS access, shared cookies, password fallback or alternate public registration.
Require WebAuthn user verification, exact expected origin/RP/challenge, valid
signature and the enrolled owner credential. Use cryptographically random IDs,
single-use expiring challenges, opaque server-side sessions, Secure HttpOnly
SameSite=Strict host-only cookies, no-store responses, CSRF tokens and exact Origin
checks on browser mutations. Reject unexpected Host and untrusted forwarding.
Handle synced-passkey counters according to the library, not by inventing a
monotonic-counter requirement that rejects valid synced keys.

Bootstrap: a local SSH administration operation provisions one random code with
at most 24-hour validity. Store only its hash remotely. No owner credential may
exist before it is used. A successful verified registration atomically stores
the credential and closes bootstrap; competing or replayed enrollment fails.
An expired or lost first-enrollment code can be replaced over SSH while there
are still no credentials. Do not expose a web reset or recovery bypass.

## Browser API contract

All JSON responses are no-store. Errors have a bounded human-readable `error`.
WebAuthn begin responses carry `publicKey` plus an opaque `challengeId`; finish
requests carry `challengeId` and the standard serialized `credential` object.

- `GET /api/session`: `{authenticated:false}` or
  `{authenticated:true, csrfToken}`. Does not expose credential or session secrets.
- `POST /api/auth/begin`: `{}`; returns assertion options for the enrolled owner.
- `POST /api/auth/finish`: assertion above; establishes a session after verification.
- `POST /api/setup/begin`: `{code}`; returns registration options only with valid
  bootstrap authorization and no existing owner credential.
- `POST /api/setup/finish`: `{code, challengeId, credential}`; completes bootstrap.
- `POST /api/logout`: requires session and `X-CSRF-Token`; revokes that session.
- `GET /api/requests`: requires session; returns `{requests:[...]}`, newest first.
- `POST /api/requests`: requires session and CSRF header; accepts
  `{requestId, text}`. ID is a canonical UUID; UTF-8 text is nonblank, at most
  64 KiB. Preserve submitted text exactly. Return `{request}` only after commit.
- `GET /api/export`: requires session; downloads the owner's requests as JSON.

A stored request is `{id, text, createdAt, status:"queued"}`. Same ID/same text
returns the same record; same ID/different text returns 409. Bound overall body,
challenge/session storage, request count and aggregate text size, with explicit
capacity errors that never silently discard requests. The first release supports
up to 1,000 requests and 16 MiB total text. No deletion or automatic processing.

## Local bridge and deployment

Provide an authenticated SSH pull command that writes a private local JSON
snapshot atomically, without modifying the server queue or running the pipeline.
Its format is intake evidence, not the pipeline's `{songs:[{slug,source,...}]}`
manifest. A later reviewed consumer must resolve sources and derive that manifest.
The other translation chat and current library task both report that the new
semantic pipeline is not yet qualified end-to-end. The existing hosted workflow
immediately spends provider quota and publishes, so it is deliberately not called.
The GitHub repository is public; private submissions must not become issues/PRs.

Deploy backend before adding the public gesture. Provision the new vhost behind a
deny-by-default document root; obtain and verify its own HTTPS certificate before
authentication or enrollment. Activate a hash-verified binary atomically. Keep
private state across releases and retain the previous binary for rollback.
Do not alter Bhakti DNS or any TimeCrystals state. No test credential remains live.

## Verification and ownership

### Operation

Run `python3 hosting/owner/deploy.py inspect` before changing an existing deployment.
Provisioning creates a denied public root and requests HTTPS; activation refuses
to proceed without a trusted certificate for the exact hostname.

```sh
python3 hosting/owner/deploy.py activate --go /absolute/path/to/go
python3 hosting/owner/deploy.py verify
python3 hosting/owner/deploy.py bootstrap --output ~/.config/bhakti/owner-private/setup-code
python3 hosting/owner/pull.py --output ~/.config/bhakti/owner-private/requests.json
```

The private parent directory must be owner-only. The setup code is written with
mode `0600` and is never printed. Open the owner site's `/setup` page, enter that
code, and complete the normal Bitwarden passkey prompt. Enrollment consumes the
code; later visits use ordinary passkey sign-in. Never commit either local file.
The pull command reads the queue without changing it or starting translation.

Root owns the shared contract, public gesture, integration and release. Backend
worker owns `hosting/owner/` Go code and service tests. Browser worker owns its
embedded `web/` files. Deployment worker owns provisioning/export scripts once
the service layout is agreed. Independent review precedes implementation and
release of authentication/storage boundaries.

Tests must cover valid cryptographic enrollment/login; rejected wrong code,
origin, RP, challenge, UV, signature, credential and replay; enrollment races;
session expiry/logout; CSRF/Origin/Host enforcement; unauthenticated reads/writes;
exact Unicode text, empty/oversize payloads, duplicate/conflicting retries,
concurrent submissions, capacity and storage failure/restart. Use real filesystem
transactions and real WebAuthn signatures for those claims. Browser checks cover
sign-in/cancel/error states, draft retention, text import, safe rendering and
responsive layout. Actual Bitwarden enrollment requires owner confirmation;
automated authenticators are tests, not owner credentials.

## Release evidence

The deployed service rejects anonymous reads/writes, wrong Origin/Host, and
cleartext authentication. Trusted exact-host TLS, CGI response completion,
no-store responses and embedded assets were checked over the real network.
The local SSH export produced a version-1 empty queue in an owner-only file.

Go tests exercise real WebAuthn signatures and filesystem transactions; the race
suite and independent security review passed. Browser event tests cover the
entrance and inbox retry/import behavior. Codex in-app Browser checks covered
390px, tablet, desktop and large-screen layouts, literal request rendering, and
the former long-hold entrance. The owner subsequently reported that iPhone
selection/callouts intercepted it; desktop held-click evidence did not establish
phone usability. Authenticated layout used a localhost fixture; it
is not evidence of owner enrollment. Bitwarden enrollment and physical iPhone
Now Playing behavior require the owner's device.

The isolated release's 265-song contract audit and Python compilation passed.
The local recording-quality audit reported 275 recordings and no errors. The
existing trim audit reports six content-evidence failures (one interval mismatch
and five invalid review artifacts), retained for the separate translation/content
repair task. This release changes no recordings, lyrics, timing or trim evidence.

## Hidden entrance correction

The owner rejected both long press (iPhone text-selection/callout interference)
and a visible login link inside About. Preserve the explicit requirement for a
completely hidden entrance on both mobile and desktop. Five ordinary completed
clicks on the existing heading open login without a timer. The heading keeps its
text and appearance; scoped user-select and touch-action rules prevent selection
and double-tap zoom on this target while retaining page pinch zoom. The private
service remains the authorization boundary, never the gesture.

Tests first reject any public login link and require the fifth untimed click,
no earlier navigation, cancellation/reset, hidden-panel rejection, no held-pointer
navigation and the keyboard fallback. Implementation removes the link/styles,
adds the hidden interaction, then advances the service-worker shell for release.
Verify initial and dynamically loaded library entry, narrow/desktop layouts,
then publish. Physical iPhone behavior is not established by desktop simulation.

Hidden-entry verification: regression tests pass for five untimed completed clicks,
no visible owner control, no held-pointer navigation, partial-sequence reset,
keyboard modifiers and Back/Forward restoration. In-app Browser verified no login
link in About, no navigation after four clicks, navigation on the fifth, close
and reopen reset, and entry from a dynamically loaded library. 390px and desktop
checks passed; physical iPhone input remains unverified. The focused homepage,
PWA-update and design-authority tests, Python compilation and 265-song contract
audit pass. Audio and trim evidence are unchanged from the preceding release.
