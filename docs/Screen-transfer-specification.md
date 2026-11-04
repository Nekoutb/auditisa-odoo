# AuditISA → Odoo 19 Community — Screen transfer specification

*Prepared 2026-11-04 against dev @ 9c515a9, with later commits up to bd3af7e noted in section A and production 0d25ef0 for reference. All effort figures are estimates. Companion workbook: `Screen-inventory.xlsx`. Screenshots: `current-tool\` (other review) and `current-tool\extra\` (this review).*

[TOC]

## A. Method and scope

**What was reviewed.** The code base `platform/` of AuditISA, against the baseline `dev` @ `9c515a9`, the build running on https://dev.auditisa.com during the review (built 2026-11-04T01:14Z). Production https://www.auditisa.com runs the older build `0d25ef0` (built 2026-09-23); only its public version endpoint was opened and nothing was created there. The review covers `app/` (pages, layouts, API routes, server actions), `components/`, `lib/` (including `lib/papers/*` and `lib/backup/*`), `migrations/`, `db/`, `messages/`, `tests/` and the project documents. Small and rule-bearing modules were read in full; for the largest files the structure and exported functions were read and the bodies sampled. Authenticated screens were opened on DEV as the UAT partner (`uat.partner@uat-a.test`, UAT Firm A) and captured at 1440×900. `/users`, `/templates`, `/resources` and `/admin` redirect that account to the dashboard, so they are described **from the code only and were not seen running**; the same applies to the client portal as a `client_user`, `/invitations/[id]`, `/documents/[id]` and every action that writes (no data was created during this review).

**The code moved during the review.** Five commits landed on `dev` while the catalogues were being built (`0d66bd9`, `8a0fbea`, `64b2b77`, `a79951e`, `bd3af7e`), and a DEV deployment of `bd3af7e` was announced as this document was finalised, so the screenshots show `9c515a9`. The commits add `lib/legal-forms.ts` and migrations `20261104000001` and `20261104000002` (no new table), and change 50 files. The catalogues were read at different moments, so **a record may describe either version** in these areas: ISA 240 ¶32 references and the materiality vocabulary and trivial range (F032, F033); legal forms including SA_AG, C5.7 scoping and E4.36 as a core task (F052, F047); the statutory papers C5.1–C5.10 and AUSCGIE articles (F048–F058); the lead taxonomy and index L (F059, F060). The counts below are taken from git at `9c515a9`. The Library modules sheet has 167 rows because it includes `lib/legal-forms.ts`. Before phase 1 the team must re-run `git diff 9c515a9..<then-current dev>` and update these areas; the application is still changing, which is itself a risk (section I, R11).

**How the inventory was built.** Six cataloguing passes ran over the code: firm-level screens; engagement-file screens and paper definitions; tool screens; API routes and server actions; `lib/`; and a replay of the 119 SQL migrations to the current schema (from the SQL text; no database was queried). Each pass quoted the access checks and rule constants it found. Sections D–I were then spot-checked against the source, which corrected several statements, but the screen and library rows have not been individually re-verified. The results were merged into the workbook `Screen-inventory.xlsx` and into section C of this document. Effort figures are **estimates** (S = 1–2, M = 3–5, L = 6–10, XL = 11–20 person-days per screen; person-weeks per phase in section H) and should be re-based once the Odoo team has built the first paper and the first grid. The Odoo designs are proposals: nothing in this document has been built or tested on Odoo 19.

**Counts (dev @ 9c515a9).**

| Item | Count |
| --- | --- |
| Page routes (`app/**/page.tsx`) | 66 |
| Layouts, error, not-found, robots, sitemap | 6 |
| API route files (`app/api/**/route.ts`) / HTTP handlers | 43 / 48 |
| Server-action files (`app/actions/*.ts`) / exported actions | 23 / 140 |
| Library modules (`lib/**`) / lines | 166 / 54,109 |
| Paper definitions (`lib/papers/*.ts`) / task codes in the file index | 95 definitions for 94 codes, 24 further codes on a default paper / 118 |
| Components (`components/**`) / lines | 77 / 18,799 |
| Files under `app/` (lines) | 20,812 |
| Database tables after all migrations / migrations / SQL lines | 82 (81 application + `pgmigrations`) / 119 / 6,471 |
| Test files (vitest + Playwright) / unit tests (`it`/`test`) / E2E tests | 90 vitest + 11 Playwright / 896 / 22 |
| Message keys (EN = FR, parity enforced by test) | 1,373 per language |
| Screens inventoried (routes + modal/drawer flows) | 119 |
| Screenshots taken by this review (`current-tool\extra\`) | 87 |

**Reading guide.** Section B maps the application; section C is the screen-by-screen specification (grouped by area, with the task codes P1.1 … C6.2 kept as they are); section D explains the rules engine once, so that section C can refer to rules by name; sections E–I are the transfer plan; J is the full route list. The companion workbook holds the same inventory in filterable form plus the API, library and database sheets.

## B. Application map

The application has two shells: the **firm shell** (top bar: Dashboard · Engagements · engagement selector · search · notifications · settings · language · user) and the **engagement console** (the same bar with the four display phases as primary navigation: Planning & Risk Identification · Strategy & Risk Assessment · Execution · Conclusion & Reporting, and the tools reached from the engagement dashboard). A third surface, the **client portal**, is reached only by `client_user` accounts.

```
Public (no session)
├── /                      landing page
├── /login                 sign-in (email + password, optional TOTP, "next" carry-over, session-ended notice)
├── /invite/[token]        new colleague sets first password
├── /terms · /privacy      legal pages
└── /version · /api/version · /api/auth/* · /api/email/inbound

Firm shell (any firm role; read_only cannot write)
├── /dashboard             my engagements, my tasks, notes for/by me, deadlines; link to /admin for super-admins
├── /engagements           register (filters: stage, year, partner, mine, archived; FY+1 roll-forward)
│   └── /new-engagement    creation wizard (client, period, nature, naming, complexity questions → tier)
├── /invitations/[id]      accept / decline a team invitation (invited members only)
├── /search                full-text search across the files the user may see
├── /documents/[id]        document viewer: versions, check-out/in, upload, sign-offs, review notes
├── /change-password · /security (MFA)
├── Settings (gear)
│   ├── /settings          firm profile, branding, naming convention, allowed email domains, links below
│   ├── /settings/signoff  sign-off policy + per-task matrix (download / import Excel)
│   ├── /settings/retention  retention years, legal holds, retention report
│   ├── /settings/audit-log  firm security log + export
│   ├── /clients · /clients/[id]   entity records (master data, grouping overrides, portal contacts, engagements)
│   ├── /users             firm users: invite, roles, suspend, reset (firm_admin)
│   ├── /templates · /templates/[code]   working-paper templates and overrides (firm_admin)
│   └── /resources         team workload (firm_admin)
├── /admin                 super-admin: firms (onboarding wizard, delete), super-admins
└── /uat                   UAT workbook (dev/staging databases only)

Engagement console  /engagements/[id]  (accepted team members only)
├── (hub)                  sections A–F with documents, exports (JSON, bundle, activity)
├── /dashboard             engagement dashboard: phases and gates, task groups, PBC, forms, client link
├── /phases/[phase]        task list of a display phase (acceptance | planning | execution | conclusion)
├── /phase/[section]       task group list by section key (acceptance | strategy | execution | conclusion)
├── /groups/[group]        one task group (P1 … C6) or storage section
├── /tasks                 my tasks / all tasks, filters, assignment
├── /sections/[itemId]     THE TASK PAPER: guidance, paper wizard, sign-offs P/R/partner/EQR, files, notes, linked tasks
├── /forms/[code]          legacy structured forms (P1.1 acceptance form and others in FORM_DEFINITIONS)
├── /acceptance · /planning · /conclusion   phase cockpits with gates and actions (advance, issue report, archive)
├── /team                  team, roles, invitations, EQR appointment, partner transfer, delegate
├── /time                  time entries
├── /settings              engagement settings (profile, standards edition, naming, delegate)
├── /nature · /considerations   complexity re-assessment; planning considerations
├── /discussion            P5.2 team discussion
├── /risks · /cra          risk register (console) and combined risk assessment matrix
├── /findings              findings and deficiency evaluation (ISA 265)
├── /legal                 OHADA legal register and alerte
├── /pbc                   PBC requests, chases, portal uploads
├── /data · /analytics · /analyzers/[kind]   TB analyzer, analytical procedures, dataset analyzers (aging, AP …)
├── /activity              activity trail (+ export)
└── /tools                 hub → data-analytics · gl-console · lead-schedule · review-notes · forms ·
                           materiality · risks · cra · sad · sap · sampling · je-selection · sample-papers · pbc

Client portal  /portal   (client_user only): PBC requests of the client, upload documents
```

Storage sections of the file (used by the hub and the archive): A Financial statements (C2.1) · B Completion (C1.x, C4.x, C2.2, C3.1, C6.x) · C Communication (C5.1, C5.11) · D Acceptance & planning (P1 … P7, S1 … S6) · E Execution (E1 … E6, E4.1–E4.36 lead papers) · F OHADA legal (C5.2–C5.10). Display phases regroup the same codes: Planning & Risk Identification (P1–P7) · Strategy & Risk Assessment (S1–S5) · Execution (E1–E6) · Conclusion & Reporting (C1–C6).

## C. Screen-by-screen specification

Each screen is described as it is today (purpose, rules in plain words, data, who may do what) and then as its Odoo 19 target. Rule names refer to section D. Task codes (P1.1 … C6.2) are those of the file index and are kept unchanged in the Odoo data. Effort figures are estimates in person-days (pd).

### C.1 Public

#### C.1.1 `(framework) app/error.tsx` — Something went wrong

**What it is.** Framework row. Client-side error boundary: branded bilingual (EN/FR inline) message with no stack trace, a 'Try again' (reset) button and a link back to /engagements.

**Rules enforced (plain words).**

- no stack traces shown to users
- both languages rendered inline (not via messages/*.json)

**Data.** Reads: —. Writes: —.

**Who may do what.** everyone

**Navigation.** → /engagements

**Components / i18n.** — · inline EN/FR text

**Odoo 19 target.** Models: —. View: controller. Groups: —.

Odoo standard error pages (http.html 500 template) suffice; optional QWeb override for branding.

**Effort / phase.** S (0.5 pd) (estimate) · 1 Foundation. Source: `app/error.tsx`; rules in app/error.tsx. Screenshot: —

#### C.1.2 `(framework) app/layout.tsx` — Root layout (AuditISA shell)

**What it is.** Framework row. Root HTML layout for every page: loads Geist fonts, globals.css, the tenant BrandStyle (accent CSS from tenant.branding), the PageLoader progress bar and a nonce-protected inline script that stamps data-theme (localStorage choice, else OS preference) before first paint. Resolves the locale with getLocale() (cookie > signed-in user's preferred_language > default 'fr'). Metadata: robots noindex/nofollow, OpenGraph/Twitter cards, metadataBase from APP_URL.

**Rules enforced (plain words).**

- CSP nonce from proxy header x-nonce required for the inline theme script
- default locale fr (OHADA-first)
- theme persisted client-side only (localStorage 'theme')

**Data.** Reads: tenant (branding via BrandStyle/getBranding), app_user.preferred_language (via session). Writes: —.

**Who may do what.** everyone (public); locale and branding resolve per session

**Navigation.** wraps every route

**Components / i18n.** BrandStyle, PageLoader · lang attribute = locale from lib/locale.ts; messages via lib/i18n.ts (en/fr, parity test tests/lib/i18n.test.ts)

**Odoo 19 target.** Models: res.company (branding fields), res.users (lang), web layout. View: controller. Groups: —.

Replaced by Odoo web client + website layout; company branding via res.company.logo / primary_color (web_responsive or custom SCSS). Dark mode via Odoo 17+ color scheme preference. No OWL component needed.

**Effort / phase.** S (1 pd) (estimate) · 1 Foundation. Source: `app/layout.tsx`; rules in lib/locale.ts, lib/i18n.ts, lib/branding.ts, components/BrandStyle.tsx, proxy.ts. Screenshot: —

#### C.1.3 `(framework) app/not-found.tsx` — 404 — This page is not in the audit file

**What it is.** Framework row. Branded 404 page (EN/FR inline) with a link back to /engagements. Used by notFound() calls across pages (e.g. a document the user may not see, /uat on production, /settings/audit-log for non-admins).

**Rules enforced (plain words).**

- forbidden resources are rendered as 404 (not 403) where the page calls notFound(), so existence is not disclosed

**Data.** Reads: —. Writes: —.

**Who may do what.** everyone

**Navigation.** → /engagements

**Components / i18n.** — · inline EN/FR text

**Odoo 19 target.** Models: —. View: controller. Groups: —.

Odoo 404 template (website.404 / http 404). Record rules in Odoo raise AccessError rather than 404; decide whether to mask as 404 for documents.

**Effort / phase.** S (0.5 pd) (estimate) · 1 Foundation. Source: `app/not-found.tsx`; rules in app/not-found.tsx. Screenshot: —

#### C.1.4 `(framework) app/robots.ts` — robots.txt

**What it is.** Framework row. Generates robots.txt: allow only '/$' and '/login', disallow everything else; points to https://www.auditisa.com/sitemap.xml.

**Rules enforced (plain words).**

- search engines may index only the door (landing + login)
- engagement URLs must never be crawled

**Data.** Reads: —. Writes: —.

**Who may do what.** everyone

**Components / i18n.** — · —

**Odoo 19 target.** Models: website (robots field) or custom controller. View: controller. Groups: —.

Odoo website module serves /robots.txt (website.robots); add Disallow rules. If website module not installed, a tiny http.Controller route.

**Effort / phase.** S (0.5 pd) (estimate) · 1 Foundation. Source: `app/robots.ts`; rules in app/robots.ts. Screenshot: —

#### C.1.5 `(framework) app/sitemap.ts` — sitemap.xml

**What it is.** Framework row. Generates sitemap.xml with only the public surface: '/' (priority 1) and '/login' (0.8), base URL from APP_URL (default https://www.auditisa.com).

**Rules enforced (plain words).**

- only public routes listed

**Data.** Reads: —. Writes: —.

**Who may do what.** everyone

**Components / i18n.** — · —

**Odoo 19 target.** Models: website sitemap. View: controller. Groups: —.

Odoo website generates /sitemap.xml automatically for published pages; mark only landing/login as indexable.

**Effort / phase.** S (0.5 pd) (estimate) · 1 Foundation. Source: `app/sitemap.ts`; rules in app/sitemap.ts. Screenshot: —

#### C.1.6 `/` — Home (redirect)

**What it is.** Landing route with no UI of its own: calls auth() and redirects an anonymous visitor to /login and a signed-in user to /dashboard. Public per lib/public-routes.ts isPublic (path === '/').

**Rules enforced (plain words).**

- signed-in → /dashboard
- anonymous → /login
- client_user then confined by proxy to /portal

**Data.** Reads: session only (JWT; jwt callback may re-read app_user + membership via lib/session-guard.ts). Writes: —.

**Who may do what.** everyone; redirect target depends on session

**Navigation.** → /login, → /dashboard

**Components / i18n.** — · —

**Odoo 19 target.** Models: —. View: controller. Groups: —.

Odoo /web already redirects anonymous users to /web/login; set the default home action to the ea_audit dashboard (res.users.action_id) and portal users to /my.

**Effort / phase.** S (0.5 pd) (estimate) · 1 Foundation. Source: `app/page.tsx`; rules in app/page.tsx, lib/public-routes.ts, proxy.ts. Screenshot: —

#### C.1.7 `/privacy` — Privacy Policy / Politique de confidentialité

**What it is.** Static bilingual privacy notice (data processed, RLS isolation, password hashing, retention/legal hold, no third-party sharing, rights contact) with a link back to sign-in. Indexable (robots index true).

**Rules enforced (plain words).**

- public route (lib/public-routes.ts)
- content is static text

**Data.** Reads: —. Writes: —.

**Who may do what.** public

**Navigation.** from /login footer; → /login

**Components / i18n.** — · inline EN then FR paragraphs

**Odoo 19 target.** Models: website.page. View: website. Groups: public.

Static website page (QWeb) in ea_audit_legal or website module; translatable via website translations.

**Effort / phase.** S (0.5 pd) (estimate) · 5 Reports/portal/legal. Source: `app/privacy/page.tsx`; rules in app/privacy/page.tsx, lib/public-routes.ts. Screenshot: —

#### C.1.8 `/terms` — Terms of Service / Conditions d'utilisation

**What it is.** Static bilingual terms summary (subscription agreement prevails, authorised users only, credential confidentiality, professional standards, suspension right) with a link back to sign-in. Indexable.

**Rules enforced (plain words).**

- public route
- static text

**Data.** Reads: —. Writes: —.

**Who may do what.** public

**Navigation.** from /login footer; → /login

**Components / i18n.** — · inline EN then FR paragraphs

**Odoo 19 target.** Models: website.page. View: website. Groups: public.

Static website page.

**Effort / phase.** S (0.5 pd) (estimate) · 5 Reports/portal/legal. Source: `app/terms/page.tsx`; rules in app/terms/page.tsx, lib/public-routes.ts. Screenshot: —

#### C.1.9 `/version` — What is this site running?

**What it is.** Human-readable face of /api/version: environment (Production / Staging / Development server), deployed commit (short sha linked to GitHub), build time, process start time, Next build id, plus instructions for checking a deployment reached the site. Public, noindex, force-dynamic.

**Rules enforced (plain words).**

- target 'prod' → www.auditisa.com, 'dev' → dev.auditisa.com, else development server; relative times computed
- SOURCE_REPOSITORY github.com/Nekoutb/ea-audit-tool

**Data.** Reads: filesystem: RELEASE file (sha, ref, built, target) and .next/BUILD_ID (lib/release-info.ts); no DB. Writes: —.

**Who may do what.** public

**Navigation.** from /api/version in a browser; → /login, /api/version

**Components / i18n.** Chip, Panel, StatCell (ui/atlas) · inline fr/en; locale from getLocale()

**Odoo 19 target.** Models: ir.module.module (version), ir.config_parameter. View: controller. Groups: public.

Equivalent: /web/webclient/version_info plus a tiny public controller exposing the ea_audit module version and deploy commit (read from a file or ir.config_parameter). Useful for the status page integration.

**Effort / phase.** S (0.5 pd) (estimate) · 6 Migration & cutover. Source: `app/version/page.tsx`; rules in lib/release-info.ts, lib/public-routes.ts. Screenshot: —

### C.2 Auth

#### C.2.1 `/change-password` — Change password

**What it is.** Password self-service for any signed-in account and the only screen a temporary-password account can reach (proxy holds sessions with mustChangePassword here). Form: current, new, confirm. On success the server signs the user out and lands on /login?error=password-changed.

**Rules enforced (plain words).**

- forced password change: must_change_password holds the session on this page (proxy.ts) until replaced
- current password always required (wrong-current)
- confirm must match (mismatch)
- new must differ from current (reused)
- password policy MIN_PASSWORD_LENGTH 12, upper+lower case (needs-mixed-case), at least one digit (needs-digit), must not contain email local part when local part > 2 chars (contains-email)
- session_version bump invalidates every other session
- unknown ?error code shows generic text (never echoes URL)
- secret never logged

**Data.** Reads: app_user (email, password_hash). Writes: app_user (password_hash, must_change_password=false, password_changed_at, session_version+1) via changeOwnPassword; activity_log (action password.changed, entity app_user) via recordActivity. Server action: page-local changeAction → lib/password.ts changeOwnPassword then signOut.

**Who may do what.** any signed-in user (auth() only; firm roles and client_user with mustChangePassword); proxy: mustChangePassword → forced here before any other route, APIs refused 403

**Sub-flows on this screen.** /change-password # forced first-login password change

**Navigation.** reached from proxy redirect (temporary password), /security link; → /login?error=password-changed

**Components / i18n.** Panel, PanelHeader (components/ui/atlas) · inline fr/en page strings (not in messages/*.json)

**Odoo 19 target.** Models: res.users (password), ea.audit.password.policy (config), res.users.must_change_password (custom field). View: wizard. Groups: base.group_user, base.group_portal.

Odoo has change-password wizard (change.password.user / res.users preferences) but no policy; use OCA password_security (min length 12, complexity, history) and OCA auth_session_timeout; 'must change at first login' needs a custom boolean + login redirect (auth_signup reset flow is the Odoo-native alternative). Log in mail.message or custom audit model.

**Effort / phase.** M (3 pd) (estimate) · 1 Foundation. Source: `app/change-password/page.tsx`; rules in lib/password.ts, lib/password-policy.ts, proxy.ts, auth.ts. Screenshot: extra\x17-change-password.png

#### C.2.2 `/invite/[token]` — Choose your password

**What it is.** Public landing page of an invitation / password-reset email: shows the target email and lets the recipient choose and confirm a password. Nothing signs anybody in; on success it redirects to /login with the email pre-filled (and ?next= when the invite carried a destination). Expired, spent and unknown tokens all show one identical 'link no longer valid' message.

**Rules enforced (plain words).**

- token stored only as SHA-256 digest
- INVITE_TTL_DAYS 14; one live invitation per user (createInvite supersedes earlier ones: used_at=now()); token length < 20 rejected; invalid-or-expired is one undifferentiated message (no token probing); race-safe claim 'UPDATE … WHERE used_at IS NULL' must affect exactly 1 row; password policy (12 chars, mixed case, digit, not containing email local part) via passwordProblem; confirm mismatch; next_path sanitised by safeNext (on-site paths only); unknown ?error shows generic text

**Data.** Reads: user_invite (token_hash, used_at, expires_at, next_path) JOIN app_user (email, name). Writes: user_invite.used_at (atomic claim), app_user (password_hash, must_change_password=false, password_changed_at, session_version+1) via acceptInvite. Server action: page-local acceptAction → lib/invites.ts acceptInvite.

**Who may do what.** public (anonymous) — guarded by a live, unspent, unexpired token only

**Navigation.** reached from invitation / password-reset emails (lib/users.ts sendInvitation, resetUserPassword); → /login?email=…&next=…&ready=1

**Components / i18n.** SubmitButton · inline fr/en page strings

**Odoo 19 target.** Models: res.users (signup_token, signup_expiration via auth_signup), res.partner.signup_*. View: controller. Groups: public.

Odoo auth_signup 'reset password' / invitation token flow is the native equivalent (signup_token, expiration). Add: 14-day TTL, SHA-256 hashing of token (Odoo stores plain token — accept or override), supersede-on-reissue, password policy via OCA password_security, uniform error message. Odoo signs the user in after setting password; this app deliberately does not — keep as decision.

**Effort / phase.** S (2 pd) (estimate) · 1 Foundation. Source: `app/invite/[token]/page.tsx`; rules in lib/invites.ts, lib/password-policy.ts, lib/account-mail.ts, lib/public-routes.ts. Screenshot: —

#### C.2.3 `/login` — Sign in

**What it is.** Credentials sign-in form (email, password, optional 6-digit authenticator/recovery code) rendered as a server action so it works without JavaScript. Shows contextual notices (session ended, throttled with wait minutes, MFA required, password changed), pre-fills the email from account emails (?email=) and honours a same-origin ?next= destination. Links to Terms and Privacy; language switcher in the header.

**Rules enforced (plain words).**

- login throttle: per (email, IP) pair 5 free failures then backoff 1,2,4,8,16,30 min (BACKOFF_MINUTES), held at 30; without trusted IP (CLIENT_IP_HEADER unset) email-only ceiling of 15 free failures; blocked attempts are not recorded (no lockout extension); throttle fails open on DB error; constant-time decoy bcrypt compare (DECOY_HASH) so unknown emails cost the same; disabled account (disabled_at) refused as bad credential
- MFA: TOTP or one-time recovery code required only when totp_enrolled_at set (abandoned enrolment is not a factor), checked after password and before membership so a password alone never yields a session; mfaDisabled(): AUTH_DISABLE_MFA honoured only when database name matches /_(dev|staging|test|local)$/ (lib/instance.ts), otherwise warning and MFA stays on; no membership → refused; tenant/role = first membership by created_at; locale = preferred_language else fr
- JWT session 12 h (maxAge), stateless; principal re-validated every 60 s (SESSION_REVALIDATE_SECONDS) — membership gone/disabled/session_version mismatch ends session, role drift refreshes token; redirect callback and safeNext reject off-origin, '//host', backslash and control chars (open-redirect guard); error codes: session-ended, too-many-attempts:<minutes>, mfa-required, password-changed, generic '1'; email preset must match /^[^@\s]+@[^@\s]+\.[^@\s]+$/; code input maxLength 12

**Data.** Reads: app_user (id, email, password_hash, preferred_language, is_super, must_change_password, session_version, disabled_at, totp_secret, totp_enrolled_at), membership (first by created_at: tenant_id, role, client_id), login_attempt, mfa_recovery_code. Writes: login_attempt (recordLoginAttempt on every attempt, success clears streak); mfa_recovery_code.used_at (recovery code spent); app_user.preferred_language (LanguageSwitcher setLocale); app_user.session_version (+1 on signOut event). Server action: LoginForm loginAction → signIn('credentials') (auth.ts authorize).

**Who may do what.** public (anonymous); an already signed-in user is redirected to safeNext(next) or /dashboard

**Sub-flows on this screen.** /login # language switch, /login # second-factor code (MFA), /login # throttled notice

**Navigation.** reached from /, proxy redirect of any protected page (with ?next= and ?error=session-ended), account emails (/login?email=…&next=…), /invite success, sign-out; → /dashboard or next, → /terms, → /privacy

**Components / i18n.** LoginForm, LanguageSwitcher, SubmitButton · en/fr keys under login.* and common.* (messages/*.json); EN/FR parity enforced by tests/lib/i18n.test.ts; footer links inline fr/en

**Odoo 19 target.** Models: res.users, res.users.log, auth_totp (res.users.totp_secret, auth_totp.device), ea.audit.login.attempt (throttle). View: controller. Groups: public.

Odoo core login + auth_totp cover password+TOTP; recovery codes and the (email, IP) backoff schedule need a small custom module (override web.login controller or use OCA auth_brute_force with the 5/1-2-4-8-16-30 schedule). Session revocation via session_version maps to Odoo's res.users password change invalidating sessions; 12 h absolute session life → set session inactivity/expiry in ir.config_parameter. ?next= handled by Odoo's redirect param (same-origin check exists). Email domain/decoy timing is a controller detail.

**Effort / phase.** M (4 pd) (estimate) · 1 Foundation. Source: `app/login/page.tsx`; rules in auth.ts, lib/login-throttle.ts, lib/mfa-verify.ts, lib/mfa-policy.ts, lib/instance.ts, lib/session-guard.ts, lib/account-mail.ts (safeNext), lib/client-ip.ts, components/LoginForm.tsx, app/actions/locale.ts. Screenshot: —

#### C.2.4 `/login # language switch` — Language (English / Français)

**What it is.** Two-button server-action form that sets the 'locale' cookie (1 year, sameSite lax) and, when signed in, persists the choice to app_user.preferred_language; then revalidates the whole layout. Rendered on /login and on /settings.

**Rules enforced (plain words).**

- locale must be one of LOCALES ['en','fr'] (isLocale) else ignored
- priority at render: cookie > session preference > DEFAULT_LOCALE 'fr'

**Data.** Reads: —. Writes: app_user.preferred_language (app/actions/locale.ts setLocale).

**Who may do what.** everyone (anonymous sets cookie only)

**Navigation.** on /login and /settings

**Components / i18n.** LanguageSwitcher · labels common.english / common.french / common.language

**Odoo 19 target.** Models: res.users.lang, res.lang. View: controller. Groups: public.

Odoo native: website language switcher / user preferences lang (fr_FR, en_US). Activate fr_FR and en_US languages; set company default fr_FR.

**Effort / phase.** S (0.5 pd) (estimate) · 1 Foundation. Source: `components/LanguageSwitcher.tsx`; rules in app/actions/locale.ts, lib/locale.ts, lib/i18n.ts. Screenshot: —

### C.3 Dashboard

#### C.3.1 `/dashboard` — My engagements (Welcome back)

**What it is.** Post-sign-in home: welcome by first name, '+ New engagement' button, a personalised To-do panel (pending engagement invitations, open review notes on my tasks, papers awaiting my review, acceptances awaiting partner sign-off), the list of my non-archived engagements with progress %, my open tasks across engagements, and review notes addressed to me. A dev-only Diagnostics panel (RLS probe rows, test-notification button) appears when NODE_ENV!=='production' or E2E_DIAGNOSTICS==='1'. Platform operators with no engagements see a link to /admin.

**Rules enforced (plain words).**

- engagement visibility = accepted team membership (visibilityClause, F008) for every list; isMine = team_member row OR owner/assignee of a file_item; archived engagements hidden; progress % = tasks_done / tasks_total where a task counts done when signed or N/A with reason; open tasks = status != 'signed' (status prepared when preparer signed)
- To-do limited to 6 rows per kind; review queue = preparer-signed papers without reviewer/partner signature; acceptance queue = P1.1 preparer-signed without partner signature in phase acceptance; phaseDeadline(periodEnd, phase) computes deadline label; diagnostics panel gated by environment, never on prod .env

**Data.** Reads: engagement, client, team_member, file_item, document, signoff, activity_log (listEngagements); file_item, engagement, client, document, signoff (myTasks); review_note, file_item, engagement, client, app_user (myOpenTaskNotes); team_member, engagement, client, file_item, document, signoff, review_note (portfolioActions); rls_probe (diagnostics only); AppNav reads tenant.branding, notification. Writes: notification (sendTestNotification, dev diagnostics only) via app/actions/notifications.ts.

**Who may do what.** any firm role (auth() then requireTenant in loaders; client_user redirected to /portal by proxy); To-do 'review' rows only when canReview(role) (senior+), 'acceptance' rows only when canPartnerSignoff(role) (partner+)

**Sub-flows on this screen.** /dashboard # dev diagnostics (RLS probe + test notification)

**Navigation.** reached from /, /login, AppNav 'Dashboard'; → /new-engagement, /engagements/[id]/dashboard, /engagements/[id]/sections/[fileItemId], /invitations/[id], /engagements/[id]/acceptance, /admin (super)

**Components / i18n.** AppNav, Panel, PanelHeader, btnGhost (ui/atlas) · en/fr keys dashboard.*, engagements.stages.*, engagements.fiscalYear; To-do labels inline fr/en

**Odoo 19 target.** Models: ea.audit.engagement, ea.audit.team.member, ea.audit.file.item, ea.audit.document, ea.audit.signoff, ea.audit.review.note, mail.activity. View: kanban (dashboard) / OWL client action. Groups: ea_audit_core.group_read_only and above.

Best built as an OWL client action (my engagements + to-do + my tasks) or a kanban of ea.audit.engagement filtered by record rule (team membership) with computed progress fields (stored, recomputed on signoff/N-A changes). To-do queue = computed server method returning counts by kind, gated by groups. Drop the dev diagnostics panel (test tooling).

**Effort / phase.** M (5 pd) (estimate) · 2 Engagement file. Source: `app/dashboard/page.tsx`; rules in lib/engagements.ts (listEngagements, myTasks), lib/dashboards.ts (portfolioActions), lib/task-notes.ts (myOpenTaskNotes), lib/engagement-access.ts, lib/engagement-dashboard.ts (phaseDeadline), lib/rbac.ts. Screenshot: extra\x01-dashboard.png; other agent: 01-dashboard.png

### C.4 Clients

#### C.4.1 `/clients` — Entity records

**What it is.** Register of the firm's client entities with search (name, registration number, NIU) and a show/hide retired toggle; table shows name (+Archived chip), legal form, registration nº and engagement count with a 'View' link. Writers see a 'New client' panel (name, legal form, sector, listed, co-CAC) with a duplicate-name confirmation ('create anyway').

**Rules enforced (plain words).**

- retired (archived_at) clients hidden unless ?archived=1; search ILIKE on name/registration_number/niu with %/_ escaped (UAT B162); name required (name-required); duplicate name check case/whitespace-insensitive → ?error=duplicate-client with typed values preserved, bypassed only with force=1 ('create anyway'); legal form enum SA/SARL/SAS/GIE/OTHER (invalid → OTHER; form default SA, action default SARL); sector enum SECTORS (11 keys) stored as key; listed and co_cac booleans; after create → /clients/[id]
- RLS by tenant via withTenant

**Data.** Reads: client LEFT JOIN engagement (listClients). Writes: client (INSERT) via app/actions/audit-file.ts createClientAction → lib/clients.ts createClient.

**Who may do what.** any firm role reads (requireTenant); create panel shown only when canWrite(session.user.role) (not read_only/client_user); createClientAction re-checks `!canWrite(session.user.role)` → ?error=read-only-role and createClient uses requireWrite()

**Sub-flows on this screen.** /clients # create client form (with duplicate override)

**Navigation.** reached from /settings 'Manage entities' (clients left primary nav per IA audit); → /clients/[id]; filters via GET /clients?q=&archived=1

**Components / i18n.** AppNav, ErrorBanner, Chip, Panel, PanelHeader, btnPrimary · en/fr keys clients.* (title 'Entity records', search, showArchived/hideArchived, legalForm, sectors.*, newClient, createClient, archivedChip); registration column inline fr/en

**Odoo 19 target.** Models: res.partner (is_company, company_type) + ea.audit.client (legal_form, sector, listed, co_cac, niu, registration_number, year_end, framework, pie, archived/active). View: list + form (quick create). Groups: read: ea_audit_core.group_read_only+; create: group_staff+ (canWrite).

Model ea.audit.client delegating to res.partner (or extending res.partner with ea_* fields). 'Retired' = active=False (archive) — Odoo archive hides from default lists and from Many2one lookups, matching 'client archive blocks new engagement'. Duplicate warning as an onchange/constraint with a 'force' flag (or rely on Odoo's partner duplicate warning). Selection fields for legal_form/sector. Record rule multi-company.

**Effort / phase.** S (2 pd) (estimate) · 1 Foundation. Source: `app/clients/page.tsx`; rules in lib/clients.ts, app/actions/audit-file.ts (createClientAction), lib/rbac.ts. Screenshot: extra\x03-clients-list.png

#### C.4.2 `/clients # create client form` — New client

**What it is.** Inline create panel for writers: name (required), legal form select, sector select, listed and co-CAC checkboxes. A duplicate name returns the form pre-filled with a 'Create anyway (duplicate accepted)' checkbox; success opens the new entity record.

**Rules enforced (plain words).**

- name-required
- duplicate-client unless force=1 (case/whitespace-insensitive compare)
- legal form validated (fallback OTHER)
- sector validated (fallback null)
- listed/coCac from checkboxes

**Data.** Reads: client (duplicate check via listClients). Writes: client (INSERT) via createClientAction → createClient (requireWrite).

**Who may do what.** canWrite roles (staff, senior, manager, eqr_reviewer, partner, firm_admin); read_only redirected with error read-only-role

**Navigation.** panel on /clients; → /clients/[id]

**Components / i18n.** Panel, PanelHeader, btnPrimary · clients.newClient, name, legalForm, sector, sectors.*, listed, coCac, createClient; 'create anyway' inline fr/en

**Odoo 19 target.** Models: ea.audit.client / res.partner. View: form (quick create). Groups: ea_audit_core.group_staff and above.

Standard create form; duplicate check as a soft warning (onchange) with a confirm flag or a Python constraint that can be overridden.

**Effort / phase.** S (1 pd) (estimate, included in /clients S) · 1 Foundation. Source: `app/clients/page.tsx`; rules in app/actions/audit-file.ts (createClientAction), lib/clients.ts (createClient). Screenshot: extra\x03-clients-list.png

#### C.4.3 `/clients/[id]` — Entity record

**What it is.** One client's master record: header chips (legal form, listed, co-CAC, PIE, archived), identity panel (name, legal form, registration nº, NIU, sector, year-end, framework, PIE, address) editable by firm admins otherwise read-only, a Retire/Reinstate control (admin), the engagement history (fiscal year, stage, opinion, report date, Open) with 'New engagement for this entity', and the Portal contacts panel (list + add contact with email/name/password).

**Rules enforced (plain words).**

- firm_admin-only master-data edit (non-admins silently redirected); name required (name-required) max 120, address max 500, year_end max 40, other text max 200; framework must be in FRAMEWORKS SYSCOHADA/IFRS/Other else null; sector must be in SECTORS else null; legal form must be valid else unchanged; renaming a client regenerates names of its acceptance/planning engagements only when the current name equals the convention-generated name in en or fr (hand-chosen titles kept) (UAT B116); client archive: record and history stay, register and new-engagement lookup stop offering it (UAT B98), toggle reversible; portal contact: email + name required (fields-required), password ≥ 8 (password-too-short), email must not exist (email-taken), creates app_user without must_change_password and membership client_user bound to client_id (not subject to allowed-email-domain rule); opinion enum unmodified/qualified/adverse/disclaimer displayed
- 404 when client not found

**Data.** Reads: client LEFT JOIN engagement (getClient); engagement, client, team_member, file_item, document, activity_log (listEngagements(clientId) with visibility); engagement.opinion (listOpinions); membership JOIN app_user where role client_user (listPortalContacts). Writes: client (registration_number, niu, address, year_end, framework, pie, sector, name, legal_form) via app/actions/clients.ts updateClientMasterAction; engagement.name (renamed acceptance/planning engagements still carrying the generated name) same action; client.archived_at via setClientArchivedAction → setClientArchived; app_user + membership (role client_user, client_id) via app/actions/pbc.ts addPortalContactAction → addPortalContact.

**Who may do what.** any firm role reads (requireTenant); identity edit and archive/reinstate only when `session.user.role === "firm_admin"` (updateClientMasterAction checks role === 'firm_admin', setClientArchived requires requireWrite() + canManageFirm); add portal contact form shown to all but lib addPortalContact requires requireWrite() + canReview(role) (senior+) else PbcError 'forbidden'; engagement history limited to engagements the user is an accepted team member of

**Sub-flows on this screen.** /clients/[id] # edit master data (firm admin), /clients/[id] # retire / reinstate entity, /clients/[id] # add portal contact (creates client_user)

**Navigation.** reached from /clients 'View', engagement hub entity links, after createClientAction; → /engagements (back), /new-engagement?client=<id>, /engagements/[id]/dashboard

**Components / i18n.** AppNav, ErrorBanner, NavLink, SubmitButton, Chip, Panel, PanelHeader, btnPrimary · clients.*, engagements.*, pbc.contacts/contactName/contactEmail/contactPassword/addContact; page-local LABELS en/fr for identity fields (not yet in messages/*.json per IA audit 5D)

**Odoo 19 target.** Models: ea.audit.client / res.partner, ea.audit.engagement (history), res.users (portal user, base.group_portal) + res.partner child contact. View: form (with notebook: Identity, Engagement history, Portal contacts). Groups: read: group_read_only+; write identity & archive: ea_audit_core.group_firm_admin; add portal contact: group_senior+.

Field-level groups attribute on identity fields (groups='ea_audit_core.group_firm_admin'); active toggle = archive; One2many engagements with record rule filtering by team; portal contact = Odoo portal wizard (portal.wizard) granting base.group_portal to a child res.partner — replaces the custom password creation (Odoo sends invitation instead; decide if that is acceptable). Constraint for name→engagement rename propagation as a write() override. PIE boolean, opinion selection on engagement.

**Effort / phase.** M (4 pd) (estimate) · 1 Foundation. Source: `app/clients/[id]/page.tsx`; rules in lib/clients.ts, app/actions/clients.ts, app/actions/pbc.ts, lib/pbc.ts (addPortalContact, listPortalContacts), lib/complexity.ts (applyNamingConvention), lib/engagements.ts. Screenshot: extra\x04-client-record.png

### C.5 Engagement file

#### C.5.1 `/engagements` — Engagements

**What it is.** The engagements register: filter bar (stage, free-text, fiscal year, partner, 'mine' checkbox, archived toggle with count), table of title/client, FY, partner, stage chip, progress bar, deadline + status (on track / behind / report issued / archived · retain until), last activity, and either 'Open' or an FY+1 roll-forward button for concluded/archived rows. Whole row opens the engagement dashboard.

**Rules enforced (plain words).**

- accepted team membership visibility (no partner/admin oversight exception)
- archived hidden unless ?archived=1 or stage=archived
- status computed: archived → 'Archived · retain until <retention_until>' (ISA 230 ¶15), report_date set → report issued, deadline < today → behind, else on track
- deadline = phaseDeadline(period_end, phase) or report_date/period_end for archived
- progress % = done/total non-conditional tasks (N/A with reason counts done)
- partner column = first team_member with team_role 'partner'
- roll-forward offered only for phase conclusion or archived, newYear must exceed fiscal_year (invalid-year), prior file must have an engagement partner (engagement-partner-required), carries forward prior-year fields
- ?error banners (not-on-this-engagement, created-not-on-team)

**Data.** Reads: engagement, client, team_member, app_user, file_item, document, activity_log (listEngagements). Writes: engagement (new FY+1 row), team_member, completion_record, carried form_response rows via RegisterRow → app/actions/conclusion.ts rollforwardFromRegisterAction → lib/completion.ts rollforward + lib/forms.ts carryForwardFromPriorYear.

**Who may do what.** any firm role (auth(); listEngagements requireTenant) but only engagements where the user is an accepted team member (visibilityClause, F008); roll-forward: requireWrite (read_only refused by proxy + lib)

**Sub-flows on this screen.** /engagements # FY+1 roll-forward (RegisterRow button)

**Navigation.** reached from AppNav 'Engagements', error.tsx/not-found links, after createEngagementAction when creator not on team; → /new-engagement, /engagements/[id]/dashboard, roll-forward → new /engagements/[newId]/dashboard

**Components / i18n.** AppNav, RegisterRow, ErrorBanner, Panel, PanelHeader, btnPrimary · en/fr keys engagements.* (title, stages.*, status.*, filter*, rollForward '{year}', showArchived/hideArchived, never, open)

**Odoo 19 target.** Models: ea.audit.engagement (phase selection acceptance/planning/execution/conclusion/archived, fiscal_year, period_end, report_date, retention_until, progress computed), ea.audit.team.member, ea.audit.client. View: list (+ kanban) with search filters; roll-forward as server action/wizard. Groups: read: group_read_only+ (record rule: accepted team member); roll-forward: group_staff+.

ir.rule: engagement visible iff team_member_ids filtered(user=uid, state='accepted') — no bypass for admins (F008) except via sudo; stored computed fields progress_pct, status, deadline (phaseDeadline rules in lib/engagement-dashboard.ts); search filters as ir.filters; roll-forward = action_rollforward(new_year) with constraints; archived rows read-only (see mutability).

**Effort / phase.** M (4 pd) (estimate) · 2 Engagement file. Source: `app/engagements/page.tsx`; rules in lib/engagements.ts (listEngagements), lib/engagement-access.ts, lib/engagement-dashboard.ts (phaseDeadline), lib/completion.ts (rollforward), app/actions/conclusion.ts, components/RegisterRow.tsx. Screenshot: extra\x02-engagements-register.png; other agent: 02-engagements-list.png

#### C.5.2 `/engagements/[id]` — Audit file hub (file index)

**What it is.** Legacy hub listing the whole file index by section (A..F) with a 6-cell dashboard strip (steps, risks, B5/uncorrected vs materiality, unsigned documents, open PBC, next deadlines) and export links. Each E item links to its working paper; other items show their generated document or a Generate button.

**Rules enforced (plain words).**

- Team-only access F008 via layout
- Conditional chip: file_item.conditional=true items shown with 'conditional' chip (untriggered)
- Generate is get-or-create: generateDocument returns the existing document when one exists
- Export routes require requireEngagementAccess (file index CSV/XLSX, full ZIP bundle UAT B157, activity CSV)
- Archive immutability: document trigger refuses writes on archived engagement

**Data.** Reads: engagement, client, file_item, document, signoff, materiality, misstatement, pbc_item, statutory_deadline, risk, program_step, finding, review_note, team_member, app_user (lib/dashboards.ts engagementDashboard, lib/engagements.ts listFileItems). Writes: document, document_version (generateDocumentAction → lib/documents.ts generateDocument: get-or-create workpaper DOCX); activity_log.

**Who may do what.** auth() session (redirect /login) + layout F008 gate; generateDocumentAction → generateDocument requireWrite() (read_only refused) + not-on-this-engagement check

**Sub-flows on this screen.** # generate-document

**Navigation.** in: AppNav current engagement, /engagements register; out: /engagements/[id]/sections/[itemId] (E items), /documents/[documentId], /api/engagements/[id]/export, /api/engagements/[id]/export/bundle, /api/engagements/[id]/activity/export

**Components / i18n.** AppNav, Panel, StatCell, Chip · t.engagementDashboard, t.engagements, t.fileIndex (+ 2 inline FR/EN labels for bundle/trail); EN/FR parity 1373/1373 leaves

**Odoo 19 target.** Models: ea.audit.engagement, ea.audit.file.item, ea.audit.document, ea.audit.signoff. View: form (hub) + list grouped by section. Groups: ea_audit_core.group_staff+ (team record rule); generate: group_staff+ (not read_only).

Computed stat fields on engagement (steps_done/total, risks counts, uncorrected_total vs materiality, unsigned_count, pbc_open, next_deadlines); server action generate_document creating ea.audit.document + attachment (DOCX via ea_audit_reports); export controllers; group_read_only sees but cannot generate

**Effort / phase.** M (3 pd) · 2 Engagement file. Source: `app/engagements/[id]/page.tsx`; rules in lib/dashboards.ts, lib/engagements.ts, lib/documents.ts (generateDocument), lib/file-index.ts, app/actions/audit-file.ts, app/api/engagements/[id]/export/*. Screenshot: extra\e01-engagement-hub.png

#### C.5.3 `/engagements/[id] # generate-document` — Generate working-paper document (hub row button)

**What it is.** Inline form per file item without a document; creates (or returns) the DOCX working paper and redirects to /documents/[id].

**Rules enforced (plain words).**

- Get-or-create: existing document returned
- Archive immutability: refused on archived engagement
- Team-only F008

**Data.** Reads: file_item, engagement, team_member. Writes: document, document_version (INSERT), activity_log.

**Who may do what.** requireWrite() in generateDocument (read_only/portal refused); not-on-this-engagement check

**Navigation.** out: /documents/[documentId]

**Components / i18n.** inline <form> server action · t.fileIndex.generate / openDocument / version

**Odoo 19 target.** Models: ea.audit.document, ea.audit.document.version. View: server action (button). Groups: ea_audit_core.group_staff+.

action_generate_document on ea.audit.file.item; DOCX rendering in ea_audit_reports

**Effort / phase.** S (1 pd) · 3 Papers. Source: `app/engagements/[id]/page.tsx → app/actions/audit-file.ts generateDocumentAction`; rules in lib/documents.ts, app/actions/audit-file.ts. Screenshot: extra\e01-engagement-hub.png

#### C.5.4 `/engagements/[id] (layout)` — Engagement access gate (layout)

**What it is.** Single server-side gate wrapping every page under an engagement. Only an accepted team member may open the file; an invited member is redirected to the invitation, anyone else back to the register with error=not-on-this-engagement.

**Rules enforced (plain words).**

- Team-only access F008: only accepted team_member rows open the engagement (read or write), no firm-admin/partner exception
- Invited-member routing: status='invited' → /invitations/[id]
- Tenant isolation: UUID check + RLS so a foreign engagement id reads as not visible (UAT B01)

**Data.** Reads: engagement, team_member. Writes: —.

**Who may do what.** canSeeEngagement(id): EXISTS team_member tm WHERE tm.engagement_id = e.id AND tm.user_id = $user AND tm.status = 'accepted' (lib/engagement-access.ts visibilitySql); firm role plays no part (no partner/firm_admin override); invitationPending() → redirect /invitations/[id]; tenant RLS hides foreign ids

**Navigation.** in: every /engagements/[id]/* URL; out: /invitations/[id], /engagements?error=not-on-this-engagement

**Components / i18n.** — · — (redirect only)

**Odoo 19 target.** Models: ea.audit.engagement, ea.audit.team.member. View: controller. Groups: ea_audit_core.group_staff .. group_partner, group_eqr (membership-based record rule, not group-based).

Record rule on ea.audit.engagement: team_member_ids.user_id = user.id AND status='accepted' for every group incl. firm admin; ir.rule must also cascade to child models (file items, papers, attachments); invitation state machine invited/accepted/declined; no sudo bypass for admins on engagement data

**Effort / phase.** S (2 pd) · 1 Foundation. Source: `app/engagements/[id]/layout.tsx`; rules in lib/engagement-access.ts, lib/tenant.ts, lib/db.ts. Screenshot: —

#### C.5.5 `/engagements/[id]/acceptance` — Acceptance & continuance

**What it is.** Acceptance workspace: link to the P1.1 form, read-only history of the retired in-app independence campaign, the client's statutory mandate (statutes/AGO, start year, expiry and final-year warning), engagement/planning letters generation, and the acceptance→planning gates with the Advance button. Shows a continuance banner linking the prior-year file.

**Rules enforced (plain words).**

- Acceptance gates (lib/gates.ts acceptanceGatesTx): d31_form_complete (P1.1 form complete AND conclusion='accept'), d31_checks_passed (p11FailedChecks: integrity_ok, competence_ok, conflicts_ok, aml_ok, independence_ok, + predecessor_ok when engagement_type='new'), d31_partner_signed (approvalSigned: partner signature on the P1.1 WORKPAPER when the effective rule requires partner, else reviewer/partner; letters under the same code do not count), engagement_partner_designated (exactly one accepted team_role='partner', F003), review_notes_cleared (no open review_note on P1.% tasks)
- Atomic transition: advanceToPlanning locks engagement FOR UPDATE, re-runs gates, requires phase='acceptance' (wrong-phase), GateError lists failed keys → ?failed=
- Gate reopened banner: phase moved on but a gate fails (UAT B99) — phase never moves back
- No independence gate (F008): declarations obtained outside the system and filed on P2.1
- Classify-first: letters disabled until engagement.complexity set
- Mandate expiry: mandateExpiryYear(type,start) (statutes/AGO 2 or 6 fiscal years) with final-year warning

**Data.** Reads: engagement, client (mandate_type, mandate_start_year), form_response (P1.1), signoff, document, file_item, team_member, review_note, independence_campaign, independence_confirmation, engagement prior-year link (lib/engagement-dashboard priorYearEngagement). Writes: client (setMandateAction: mandate_type, mandate_start_year), document + document_version (generateLetterAction → lib/letters.ts generateLetter, filed under P1.4 engagement letter / C5.11 planning TCWG), engagement.phase (advanceToPlanning), activity_log (phase_advanced).

**Who may do what.** auth() + layout F008; setMandateAction/generateLetterAction/advanceToPlanningAction go through requireWrite() (read_only refused); advanceToPlanning any writer (no partner check in lib/gates.ts advanceToPlanning)

**Sub-flows on this screen.** # mandate-form, # generate-letter, # advance-to-planning

**Navigation.** in: phases/pre-planning workspace chips, AppNav; out: /engagements/[id]/forms/P1.1, /engagements/[id]/nature, /engagements/[prior]/dashboard, /documents/[letterId], /engagements/[id]/team (gate href)

**Components / i18n.** AppNav, GatesPanel, ErrorBanner, Panel · t.planning (acceptanceTitle, independence, mandate, letters, gates, gateNames, errors); parity ok

**Odoo 19 target.** Models: ea.audit.engagement, ea.audit.client (mandate), ea.audit.gate (computed), ea.audit.letter/ea.audit.document, ea.audit.signoff. View: form (workspace) + wizard for phase advance. Groups: ea_audit_core.group_staff+ view; actions group_staff+ (not read_only).

Gate engine as Python methods returning [(key, ok, detail, href)] shared with phases page; phase transition inside a single transaction with row lock (SELECT FOR UPDATE); mail.activity/notification on phase change; letter generation via ea_audit_reports QWeb/docx templates; mandate expiry computed on client

**Effort / phase.** M (4 pd) · 2 Engagement file. Source: `app/engagements/[id]/acceptance/page.tsx`; rules in lib/gates.ts, lib/forms.ts (p11FailedChecks, isFormComplete), lib/signoff-policy.ts (effectiveRuleTx), lib/letters.ts, lib/independence.ts, app/actions/planning.ts. Screenshot: extra\e06-acceptance.png

#### C.5.6 `/engagements/[id]/acceptance # advance-to-planning` — Advance to planning (phase gate button)

**What it is.** Button shown only while phase='acceptance'; runs the five acceptance gates inside a locked transaction and moves the engagement to planning, logging the transition.

**Rules enforced (plain words).**

- Gates, not guidance (spec §19.2): GateError('gates-failed:...') → redirect ?error=gates-failed&failed=keys
- wrong-phase when not in acceptance
- double-submit safe via FOR UPDATE

**Data.** Reads: engagement FOR UPDATE, form_response, signoff, document, file_item, team_member, review_note. Writes: engagement.phase='planning'; activity_log phase_advanced.

**Who may do what.** requireWrite(); no explicit rank check (any accepted team writer)

**Navigation.** stays on /acceptance

**Components / i18n.** GatesPanel, inline form · t.planning.advanceToPlanning, t.planning.gateNames

**Odoo 19 target.** Models: ea.audit.engagement. View: server action. Groups: ea_audit_core.group_staff+.

action_advance_to_planning with constraint raising UserError listing failed gate keys; state field selection acceptance/planning/execution/conclusion/archived

**Effort / phase.** S (1 pd) · 2 Engagement file. Source: `app/engagements/[id]/acceptance/page.tsx → app/actions/planning.ts advanceToPlanningAction → lib/gates.ts advanceToPlanning`; rules in lib/gates.ts. Screenshot: extra\e06-acceptance.png

#### C.5.7 `/engagements/[id]/activity` — Activity trail & answer history

**What it is.** Engagement audit trail: every logged user action (sign-offs, voids, assignments, attachments, PBC, phase changes, N/A, due dates...) with actor initials and timestamp, localised to French by regex on the stored English summaries; plus the F027 answer history — every working-paper field change with before/after values, grouped by task and field.

**Rules enforced (plain words).**

- Append-only trail: activity_log never edited; summaries stored in English and translated at render (UAT B127, run 3 B14)
- Answer history F027: per field change list with user, time, before, after (values truncated at 400 chars)
- Exports: CSV trail and ZIP bundle require requireEngagementAccess

**Data.** Reads: activity_log, app_user (listActivity, answerHistory). Writes: —.

**Who may do what.** auth() + layout F008; read-only

**Sub-flows on this screen.** # answer-history-details (expandable per field)

**Navigation.** in: dashboard feed; out: /engagements/[id]/dashboard, /api/engagements/[id]/activity/export, /api/engagements/[id]/export/bundle

**Components / i18n.** AppNav, NavLink, Panel, PanelHeader · t.dashboard.activity, t.auditLog (+ localizedSummary regex table and 2 inline labels); parity ok

**Odoo 19 target.** Models: ea.audit.activity.log (or mail.tracking.value + mail.message on each model). View: list (chatter-like) + report export. Groups: ea_audit_core.group_staff+ / group_eqr / group_read_only.

Use mail.thread tracking on paper answers for field-level before/after (F027) and a dedicated append-only ea.audit.activity.log with ir.rule read-only; translation of summaries should be done via structured action codes + i18n rather than regex; CSV export controller

**Effort / phase.** M (3 pd) · 1 Foundation. Source: `app/engagements/[id]/activity/page.tsx`; rules in lib/activity.ts, lib/audit-log.ts (answerHistory), app/api/engagements/[id]/activity/export/route.ts. Screenshot: extra\e18-activity.png

#### C.5.8 `/engagements/[id]/analytics` — Analytical procedures (lead-schedule analytics)

**What it is.** Read-only Excel-like grid of the lead schedules built from the pre-audit trial balance: per index the accounts, closing, prior year, movement and variance %, with an editable Commentary column at account and total level (ISA 520 risk-assessment analytics feeding P3.2).

**Rules enforced (plain words).**

- Requires a valid pre-audit TB: empty state otherwise ('import in the TB Analyzer')
- Figures read-only, only commentary editable; invalid-index / invalid-key validation on comment keys
- Archive immutability via form_response trigger

**Data.** Reads: trial_balance, trial_balance_version, trial_balance_row, client_lead_index_override, engagement, form_response (ap comments). Writes: form_response (AP commentary keys) via /api/engagements/[id]/ap-comments.

**Who may do what.** auth() + layout F008; comments saved via POST /api/engagements/[id]/ap-comments (lib/analytical-procedures.ts saveApComments)

**Sub-flows on this screen.** # ap-commentary-edit (per row/total inline textarea autosave)

**Navigation.** in: tools/data-analytics, sections P3.2 TOOL_LINKS chip, phases/execution workspace chip; out: /engagements/[id]/tools/data-analytics (back)

**Components / i18n.** AppNav, ErrorBanner, ApSchedules (client) · inline FR/EN labels in page; ApSchedules receives locale

**Odoo 19 target.** Models: ea.audit.trial.balance(.version/.row), ea.audit.lead.schedule (computed), ea.audit.ap.comment. View: pivot/list (OWL grid). Groups: ea_audit_core.group_staff+; comments not for group_read_only/group_eqr.

Lead-schedule aggregation as SQL view over TB rows with SYSCOHADA grouping rules + client overrides; commentary as separate model keyed by engagement/index/account; OWL grid with drill-down

**Effort / phase.** M (4 pd) · 4 Tools. Source: `app/engagements/[id]/analytics/page.tsx`; rules in lib/analytical-procedures.ts, lib/tb.ts, lib/lead-classes.ts, app/api/engagements/[id]/ap-comments/route.ts. Screenshot: extra\e17-analytics.png, extra\d12-analytical-procedures-with-data.png

#### C.5.9 `/engagements/[id]/analyzers/[kind]` — Sub-ledger analyzer (GL / AR / AP / inventory / fixed assets / payroll / bank / supplier statements)

**What it is.** One analyzer per sub-ledger kind: upload and map a dataset of that kind only (DatasetAnalyzer), list its datasets (pre-audit / post-audit / prior-year for journal entries), AR/AP aging grids, the GL insight suite (preparers/reviewers, class volumes, weekday analysis, entry lag, account prefixes, correlation), and the agreement of the latest dataset to the TB control account with a Reconcile action filed under the matching E4 paper.

**Rules enforced (plain words).**

- Kind isolation: each analyzer uploads and lists only its own kind
- RECON_TASK mapping ar→E4.1, ap→E4.2, inventory→E4.3, fixed assets→E4.4, payroll→E4.11, bank→E4.7 (UAT B80) — Reconcile disabled when the paper is not on the file
- Recon difference > 0.5 shown red; above clearly-trivial → finding raised on C1.2
- File limits: 60 MB (file-too-large 413), unsupported/unreadable/empty-file refusals (lib/subledgers.ts)
- Aging only for ar/ap
- GL insights only when a journal_entries dataset exists; link to GL correlation console

**Data.** Reads: sub_ledger_dataset, sub_ledger_row, engagement, file_item, trial_balance(+version/row), materiality, automation_run, syscohada_grouping_rule, client_grouping_override. Writes: sub_ledger_dataset, sub_ledger_row (upload), automation_run, document, document_version (runReconciliation records the run and files it on the E4 paper), finding on C1.2 when difference above clearly-trivial (per page text).

**Who may do what.** auth() + layout F008; kind must satisfy isSubLedgerKind else 404; uploads POST /api/engagements/[id]/subledgers (requireTenant, 60 MB cap); runReconFromAnalyzerAction → lib/engines.ts runReconciliation (requireWrite)

**Sub-flows on this screen.** # dataset-upload-wizard (file → header row → column mapping → confirm), # reconcile-to-control-account

**Navigation.** in: tools/data-analytics; out: /engagements/[id]/tools/data-analytics (back), /engagements/[id]/tools/gl-console, ?reconciled=1

**Components / i18n.** AppNav, DatasetAnalyzer (client, fixedKind), AgingGrid, GlInsightsBoard (client, /api/gl-insights), Panel, ErrorBanner, SubmitButton · page-local ANALYZER_TITLES EN/FR + inline labels; t.planning passed to DatasetAnalyzer

**Odoo 19 target.** Models: ea.audit.dataset, ea.audit.dataset.row, ea.audit.automation.run, ea.audit.aging (computed). View: form + list + graph (OWL upload wizard). Groups: ea_audit_core.group_staff+; read for group_eqr/group_read_only.

Import wizard (TransientModel) with delimiter/column detection; large row tables (consider PostgreSQL COPY, separate table per kind or JSONB); engines as server actions producing automation_run + attachment; aging/GL analytics as SQL views or computed on demand

**Effort / phase.** L (8 pd) · 4 Tools. Source: `app/engagements/[id]/analyzers/[kind]/page.tsx`; rules in lib/subledgers.ts, lib/subledger-kinds.ts, lib/aging.ts, lib/gl-insights.ts, lib/engines.ts (reconPreview, runReconciliation), app/actions/engines.ts, app/api/engagements/[id]/subledgers/*. Screenshot: —

#### C.5.10 `/engagements/[id]/analyzers/[kind] # reconcile-to-control-account` — Reconcile sub-ledger to TB control account

**What it is.** Records the agreement of the dataset total to the TB closing of its control prefixes as an automation run filed under the account's E4 paper; bank statements pass the period end.

**Rules enforced (plain words).**

- RECON_PREFIXES per kind
- aboveTrivial flag vs approved materiality trivial threshold
- requires the E4 task on the file
- archived engagement refused (trigger)

**Data.** Reads: sub_ledger_dataset, sub_ledger_row, trial_balance*, materiality, file_item. Writes: automation_run, document/document_version (run report), finding (C1.2) when above trivial.

**Who may do what.** requireWrite(); team F008

**Navigation.** redirect ?reconciled=1

**Components / i18n.** SubmitButton form · inline FR/EN

**Odoo 19 target.** Models: ea.audit.automation.run. View: server action. Groups: ea_audit_core.group_staff+.

Engine method on dataset; stores summary JSON; creates finding when above trivial

**Effort / phase.** S (1 pd) · 4 Tools. Source: `app/actions/engines.ts runReconFromAnalyzerAction → lib/engines.ts runReconciliation`; rules in lib/engines.ts. Screenshot: —

#### C.5.11 `/engagements/[id]/conclusion` — Conclusion, report issuance & archive

**What it is.** Completion workspace: retention & legal hold, the C4.1 completion gates, one-click runs (final analytics, FS tie-out), conclusion letters (affirmation, complementary, management letter, TCWG completion), completion records (disclosure checklist, subsequent events, points forward, partner conclusion), the opinion/report issuance form, the ISA 230 archive gates with the Archive button, roll-forward to next year and the ISA 700 report-components checklist.

**Rules enforced (plain words).**

- Completion gates C4.1 (lib/completion.ts completionGatesTx): sections_concluded (no E section unconcluded, no open steps), risks_concluded (no open risks, no unapproved mid-audit additions), b5_within_materiality (uncorrected total <= materiality AND SAD trivial line posted/in register), final_analytical_review, fs_tieout_passed, disclosure_checklist, subsequent_events, rep_letters_generated (>=2 distinct letters under C3.1), b4_cleared (no open route='b4' findings), eqr_complete (when EQR required: active 'eqr' sign-off on C4.2 by the appointed EQR with q_complete and q_resolved = yes written by that reviewer), c43_cleared (C4.3 q_none_open=yes AND no open review note anywhere), partner_conclusion
- Report issuance F003: canPartnerSignoff AND partnerTierRefusal null; phase must be execution or conclusion (report-requires-execution, UAT run 2 B154); already-issued refused; all completion gates green
- ISA 560: subsequent_events reviewedTo >= reportDate; opinion derived from checkboxes (material misstatement/pervasive/scope limitation/going concern)
- KAM required for listed clients (kam-required) unless kamNone with reason; sets phase='conclusion'
- Archive gates (archiveGates): report_issued, completion_gates, controls_concluded, deficiencies_communicated (C5.11), tasks_addressed (performed or N/A with reason), reviews_complete, papers_signed (P and R on every workpaper), review_approval (C4.1), review_notes_cleared, c62_checklist
- Archive: archive-partner-only + partnerTierRefusal; stamps retention_until = retentionDate(report_date, period_end, tenant.retention_years) inside the archiving transaction (never shortened later, UAT run 2 B86) and builds manifest v2
- Archive immutability thereafter (lib/mutability.ts + DB triggers on 20+ evidence tables; generate/save forms hidden when archived, ISA 230 §15-16)
- 60-day assembly deadline assemblyDeadline(reportDate) shown (ISA 230 ¶14; file_assembly deadline row in legal calendar)
- Legal hold: manager+ places with reason, partner releases with reason, released holds stay visible (UAT run 2 B158), assertNotHeld blocks destruction
- Roll-forward: newYear > fiscal_year, requires an engagement partner on the team, copies rolling items
- Disclosure checklist must be ticked (checklist-incomplete); subsequent events reviewedTo cannot precede period end (reviewed-before-period-end); finalAnalytics needs TB (no-tb); fsTieout must pass (tieout-failed)
- Completion records optimistic concurrency (stale-edit) and system keys reserved

**Data.** Reads: engagement, client (listed), completion_record, legal_hold, tenant (retention_years), file_item, document, document_version, signoff, review_note, finding, misstatement, program_step, section_conclusion, risk, control_test, scot, scot_control, form_response, materiality, team_member, membership, app_user. Writes: completion_record (final_analytical_review, fs_tieout, disclosure_checklist, subsequent_events, points_forward, partner_conclusion; optimistic version), document + document_version (letters), engagement (phase='conclusion', report_date, opinion; archived_at, retention_until, archive manifest), legal_hold (place/release), new engagement + file_item (rollforward), activity_log, notification.

**Who may do what.** auth() + layout F008; isPartner = canPartnerSignoff(role) gates partner conclusion, issue report, archive UI; canPlaceHold = atLeast(role,'manager'); canReleaseHold = atLeast(role,'partner'); server: issueReport/archiveEngagement require canPartnerSignoff + partnerTierRefusal (designated engagement partner or delegate, F003); recordCompletion requires partner for partner_conclusion; read_only refused by requireWrite

**Sub-flows on this screen.** # legal-hold-place, # legal-hold-release, # run-final-analytics, # run-fs-tieout, # generate-conclusion-letter (4 kinds), # completion-record-forms (disclosure, subsequent events, points forward, partner conclusion), # issue-report, # archive-file, # roll-forward

**Navigation.** in: phases/conclusion workspace chip, AppNav; out: gate fix links → /conclusion, /groups/e1, /tools/forms, /dashboard, /groups/c4, /tools/review-notes, /groups/c6; letters → /documents/[id]; rollforward → new engagement

**Components / i18n.** AppNav, ErrorBanner (scope conclusion, details per failed gate), GatesPanel, Panel · t.planning.conclusion, t.planning.errors (+ many inline FR/EN labels: legal hold, archive gate labels, report components); parity ok

**Odoo 19 target.** Models: ea.audit.engagement (report_date, opinion, archived_at, retention_until, manifest), ea.audit.completion.record, ea.audit.legal.hold, ea.audit.letter, ea.audit.gate. View: form (workspace) + wizards (issue report, archive, roll-forward). Groups: view group_staff+; completion records group_staff+; partner conclusion/issue/archive group_partner (and engagement-partner identity check); legal hold place group_manager, release group_partner.

Gate engine methods; issue_report wizard with opinion computation and KAM constraint; archive method stamping retention and writing an immutable manifest (ir.attachment + hash); post-archive write protection via ORM check in write()/unlink() of every evidence model (replace DB triggers) plus a DB-level trigger for safety; legal hold model with mail.thread; roll-forward = copy wizard; QWeb/docx letters in ea_audit_reports; cron for 60-day assembly reminder

**Effort / phase.** XL (12 pd) · 5 Reports/portal/legal. Source: `app/engagements/[id]/conclusion/page.tsx`; rules in lib/completion.ts, lib/conclusion.ts (via actions), lib/retention.ts, lib/report-components.ts, lib/letters.ts, lib/fs-tieout.ts, lib/analytics.ts, lib/signoff-policy.ts (partnerTierRefusal), lib/mutability.ts, migrations/20260820000002_archive_immutability.sql, app/actions/conclusion.ts, app/actions/retention.ts. Screenshot: extra\e20-conclusion-report-issuance.png

#### C.5.12 `/engagements/[id]/conclusion # archive-file` — Archive and lock the audit file

**What it is.** Partner-only button enabled when every archive gate is green: stamps retention, writes the manifest, sets archived_at; thereafter the file is read-only everywhere.

**Rules enforced (plain words).**

- no-report, already-archived refusals
- retention fixed at archiving
- immutability by DB triggers (form_response, program_step, task_attachment, document, section_conclusion, evidence, misstatement, finding, risk, potential_risk, control_test, scot, confirmation, cra_assessment, accounting_estimate, materiality, related_party, pbc_item, planning_snapshot, adjusting_journal + child tables + file_item, trial_balance, sub_ledger_dataset, gl_line, team_member, alerte, convention, fait_delictueux, statutory_deadline, independence_campaign, budget_line, automation_run, revise_log)

**Data.** Reads: archive gate tables; engagement FOR UPDATE; tenant.retention_years. Writes: engagement.archived_at, retention_until, archive manifest; activity_log 'Audit file archived and locked'.

**Who may do what.** canPartnerSignoff(role) → else archive-partner-only; partnerTierRefusal (F003); UI disables for non-partners and when gates fail

**Navigation.** stays; archived banner

**Components / i18n.** inline form / disabled buttons; also ArchiveChecklist on C6.2 · t.planning.conclusion.archive + inline labels

**Odoo 19 target.** Models: ea.audit.engagement. View: server action (confirm). Groups: ea_audit_core.group_partner + engagement partner identity.

action_archive with confirm dialog; write()/unlink() guard across models when engagement.archived_at set; manifest as JSON attachment with SHA-256

**Effort / phase.** S (2 pd) · 5 Reports/portal/legal. Source: `app/actions/conclusion.ts archiveAction → lib/completion.ts archiveEngagement`; rules in lib/completion.ts (archiveGates, archiveEngagement), lib/retention.ts, lib/mutability.ts. Screenshot: extra\e20-conclusion-report-issuance.png

#### C.5.13 `/engagements/[id]/conclusion # issue-report` — Issue auditor's report (opinion form)

**What it is.** Partner-only form: four opinion drivers (material misstatement, pervasive, scope limitation, going-concern uncertainty), basis and KAM text, KAM-none option for listed entities, report date; issues the report and moves the file to conclusion.

**Rules enforced (plain words).**

- report-requires-execution
- already-issued
- all completion gates
- subsequent_events reviewedTo >= reportDate (ISA 560)
- basis-required / kam-required (listed) validation in action
- fields-required (report date)

**Data.** Reads: engagement FOR UPDATE, completion_record, all completion gate tables, client.listed. Writes: engagement.phase='conclusion', report_date, opinion; activity_log.

**Who may do what.** canPartnerSignoff(role) AND partnerTierRefusal(tenant, engagement, user) === null (designated engagement partner or delegate); non-partners see 'Awaiting the engagement partner'

**Navigation.** stays on /conclusion (shows issued state + assembly deadline)

**Components / i18n.** inline form · t.planning.conclusion.*

**Odoo 19 target.** Models: ea.audit.engagement, ea.audit.report. View: wizard. Groups: ea_audit_core.group_partner + engagement partner identity.

TransientModel ea.audit.issue.report.wizard; opinion selection computed; constraint on completion gates; sets state

**Effort / phase.** S (2 pd) · 5 Reports/portal/legal. Source: `app/actions/conclusion.ts issueReportAction → lib/completion.ts issueReport`; rules in lib/completion.ts (issueReport), app/actions/conclusion.ts. Screenshot: extra\e20-conclusion-report-issuance.png

#### C.5.14 `/engagements/[id]/considerations` — Planning considerations (conditional forms)

**What it is.** The five one-field conditional planning forms (P4.2 control environment, P4.3 IT environment, S5.1 experts, S5.2 service organisations, S5.3 internal audit) on one screen; each is editable only when its S6.1 trigger question is answered yes, otherwise shown as 'not required' with the trigger named.

**Rules enforced (plain words).**

- Conditional tasks by trigger (CONDITIONAL_TRIGGERS): P4.2←assess_control_env, P4.3←assess_it_env, S5.1←uses_expert, S5.2←uses_service_org, S5.3←has_internal_audit — active only when the S6.1 answer === true
- returnTo honoured only for same-engagement paths
- optimistic concurrency via __revision in saveForm (stale refused)

**Data.** Reads: form_response (S6.1 triggers and each code), file_item, engagement. Writes: form_response (saveFormAction), file_item (saveForm may activate items), activity_log.

**Who may do what.** auth() + layout F008; saveFormAction → lib/forms.ts saveForm (requireWrite)

**Sub-flows on this screen.** # consideration-form-save (per code)

**Navigation.** in: /planning driver rows (#code anchors); out: /engagements/[id]/planning (back), /engagements/[id]/sections/[itemId] (working paper)

**Components / i18n.** AppNav, ErrorBanner, NavLink, SubmitButton, Chip, Panel · t.considerations, t.planning.save (+ 1 inline label); parity ok

**Odoo 19 target.** Models: ea.audit.paper.response (legacy form values), ea.audit.file.item. View: form (grouped). Groups: ea_audit_core.group_staff+.

attrs invisible/readonly based on trigger booleans from S6.1 answers; could be merged into the S6.1 paper form as notebook pages; activation of file items on trigger change (computed active flag)

**Effort / phase.** S (2 pd) · 2 Engagement file. Source: `app/engagements/[id]/considerations/page.tsx`; rules in lib/engagement-dashboard.ts (CONDITIONAL_TRIGGERS), lib/forms.ts, app/actions/planning.ts. Screenshot: extra\e10-considerations.png

#### C.5.15 `/engagements/[id]/cra` — Combined Risk Assessment matrix (full screen)

**What it is.** Full-screen CRA matrix: inherent risk x control risk per relevant assertion of each significant account (same CraBoard as the S3.1 paper), significant-risk counter, plus a SCOT rollup table (type, accounts, strategy, WCGW/controls counts, selected, operating effectiveness, assignee).

**Rules enforced (plain words).**

- CRA 'rely' needs a selected control: cr='rely' refused (rely-without-controls) when no scot_control selected_for_testing covers the assertion (or ITGC not supporting) unless a written cr_basis is given in the same request (UAT B51, ISA 330 ¶8)
- Reassessment reason: once planning closed or materiality approved, changing IR/CR requires a reason (reassessment-reason-required) and is journaled in cra_assessment_history
- Key-item threshold per index (saveIndexThreshold, > 0); invalid-assertion/invalid-index validation
- Planning gate cra_reliance_supported counts unsupported relies
- Archive immutability (423 archived)

**Data.** Reads: cra_assessment, cra_assessment_history, cra_index_setting, risk, risk_lead_index, materiality, file_item, engagement, scot, scot_index, wcgw, wcgw_control, scot_control, control_test, team_member, app_user. Writes: cra_assessment, cra_assessment_history, cra_index_setting (via /api/cra).

**Who may do what.** auth() + layout F008; cell edits POST /api/engagements/[id]/cra → lib/cra.ts saveCraCell (assertMutable; requireWrite in lib)

**Sub-flows on this screen.** # cra-cell-edit (relevant toggle, IR, IR basis, CR, CR basis, reason), # cra-threshold-edit, # cra-history

**Navigation.** in: tools, E4 paper CRA chip (wp-account-cra), S3.1 TOOL_LINKS; out: /engagements/[id]/tools (back), E4 papers via ?back= (CraBoard links)

**Components / i18n.** AppNav, CraBoard (client), NavLink, Chip, Panel, PanelHeader · page-local FR/EN labels (l.*), t.engagements.fiscalYear; CraBoard localized

**Odoo 19 target.** Models: ea.audit.cra.assessment, ea.audit.cra.history, ea.audit.cra.index.setting, ea.audit.scot. View: OWL matrix (pivot-like editable grid) + list. Groups: ea_audit_core.group_staff+ edit; group_eqr/group_read_only read.

Custom OWL matrix component; constraints in Python: rely requires selected control covering assertion or basis; history model with reason; locked-after-planning rule (engagement.phase != planning or materiality approved); rollup computed from SCOT/controls

**Effort / phase.** L (6 pd) · 4 Tools. Source: `app/engagements/[id]/cra/page.tsx`; rules in lib/cra.ts, lib/cra-model.ts, lib/scots.ts (listScots), lib/gates.ts (cra_reliance_supported), app/api/engagements/[id]/cra/route.ts. Screenshot: extra\e09-cra.png, extra\d05-cra-with-data.png

#### C.5.16 `/engagements/[id]/dashboard` — Engagement dashboard

**What it is.** Main engagement console: overall completion %, four phase cards (acceptance, strategy, execution, conclusion) each expanding into its task groups, an unassigned-tasks banner, an attention strip (open findings, uncorrected misstatements, unconcluded significant risks, unsigned papers, PBC owed) and three lists (my tasks, review notes/timetable, findings and the team feed). Redirects to /nature when the file has no tasks yet.

**Rules enforced (plain words).**

- Nature-first: tasks.length===0 → redirect /nature (file not propagated until the complexity conclusion)
- Task status derivation (engagement-dashboard taskStatus): reviewer signed → reviewed, preparer signed → in_review, document or HAS_WORK (complete step, live attachment, section conclusion, non-carried wp answer) → in_progress, else not_started
- N/A counts as done: task with na_reason counts complete in the phase % (UAT run2-B157)
- Unassigned banner: tasks with no owner and no assignee, not reviewed, not N/A (UAT run2-B143) → link to tools/forms
- Phase deadline rule phaseDeadline(periodEnd): acceptance -90d, planning -45d, execution +90d, conclusion +150d, per-task due_date wins (effectiveDueDate)
- Attention strip (UAT B112) computed from findings, misstatements, significant risks, unsigned papers, requested PBC
- Error banner for refused accept/decline (UAT B121)

**Data.** Reads: engagement, client, file_item, document, signoff, program_step, task_attachment, section_conclusion, form_response, review_note, risk, finding, misstatement, pbc_item, trial_balance, team_member, app_user, activity_log, materiality, statutory_deadline (lib/engagement-dashboard.ts, lib/dashboards.ts, lib/activity.ts). Writes: —.

**Who may do what.** auth() + layout F008; read-only for every team role (no write action on this page)

**Sub-flows on this screen.** # phase-card-expand (SectionStage slides a phase's groups open)

**Navigation.** in: AppNav, register, layout; out: /clients/[clientId], /engagements/[id]/groups/[g] (phase cards), /engagements/[id]/tools/forms (unassigned), /engagements/[id]/pbc (PBC chip), /engagements/[id]/sections/[itemId] (my tasks), /engagements/[id]/nature (redirect)

**Components / i18n.** AppNav, SectionStage (client, phase cards), TilesToggle, DashboardLists, ErrorBanner (GatesPanel) · t.dashboard, t.engagements (+ page-local STATUS_LABEL EN/FR and inline unassigned banner text); parity ok

**Odoo 19 target.** Models: ea.audit.engagement, ea.audit.file.item, ea.audit.signoff, ea.audit.review.note, ea.audit.finding, ea.audit.misstatement, ea.audit.pbc.item, ea.audit.activity.log. View: kanban/graph dashboard (OWL client action). Groups: ea_audit_core.group_staff+ / group_eqr / group_read_only (team record rule).

OWL dashboard component needed (phase rings + expandable groups); computed stored fields task_status, due_date_effective, is_unassigned on ea.audit.file.item; attention queue as a SQL view model (ea.audit.attention); phase deadline offsets as company settings; redirect to nature wizard when no file items

**Effort / phase.** L (6 pd) · 2 Engagement file. Source: `app/engagements/[id]/dashboard/page.tsx`; rules in lib/engagement-dashboard.ts, lib/dashboards.ts, lib/task-groups.ts, lib/file-index.ts, lib/activity.ts. Screenshot: extra\e02-engagement-dashboard.png, extra\d01-engagement-dashboard-with-data.png; other agent: 01-dashboard.png, 03-engagement-dashboard.png

#### C.5.17 `/engagements/[id]/data` — Trial Balance Analyzer

**What it is.** Upload a trial balance into the pre-audit, post-audit or prior-year slot (each upload supersedes the slot), confirm columns and SYSCOHADA classes (TbAnalyzer wizard), see validation status and reasons per slot, the full version history with debit/credit totals and a diff against the previous upload of the same slot, and the TB-to-GL roll-forward reconciliation when a GL dataset exists.

**Rules enforced (plain words).**

- Slots pre_audit/post_audit/prior_year: re-import supersedes but never deletes (version history)
- Working TB (current_version_no) moves only on a VALID pre-audit import or a posted adjustment (lib/tb.ts) — feeds tool-fed papers E4.1-E4.34, P6.2, C1.1 (F004)
- Validation statuses valid/invalid/warning with reasons (lib/tb-reasons.ts); missing-account-column / missing-amount-columns / empty-file refusals
- Version diff limited to 10 latest pairs, 100 rows (UAT B66)
- Planning gate tb_mapped: every account of the current version must match a grouping rule or client override; jdesc/jamount query params prefill the adjusting journal from findings (#journal)

**Data.** Reads: trial_balance, trial_balance_version, trial_balance_row, trial_balance_version_journal, adjusting_journal(+line), syscohada_grouping_rule, client_grouping_override, client_lead_index_override, sub_ledger_dataset, sub_ledger_row (rollForward), engagement. Writes: trial_balance, trial_balance_version, trial_balance_row (import); activity_log 'Trial balance imported (...)'.

**Who may do what.** auth() + layout F008; POST /api/engagements/[id]/tb and /tb/preview (requireTenant/requireWrite in lib/tb.ts importTrialBalance; 60 MB cap)

**Sub-flows on this screen.** # tb-upload-wizard (file → header row → column confirm → class confirm → import), # tb-version-diff (expand)

**Navigation.** in: tools/data-analytics, phases/execution workspace chip, findings 'propose adjustment' link; out: /engagements/[id]/tools/data-analytics (back)

**Components / i18n.** AppNav, ErrorBanner, TbAnalyzer (client wizard), TbValidationReasons, RollForwardGrid, Chip, Panel · inline FR/EN labels; t.planning passed to TbAnalyzer; tbStatusLabel

**Odoo 19 target.** Models: ea.audit.trial.balance, ea.audit.trial.balance.version, ea.audit.trial.balance.row, ea.audit.grouping.rule, ea.audit.client.grouping.override, ea.audit.adjusting.journal. View: form + list (OWL import wizard). Groups: ea_audit_core.group_staff+ import; others read.

Import TransientModel with column inference (lib/tb.ts inferTbMapping) and validation reasons; version model with status and totals; current_version pointer on TB updated only by valid pre-audit import or posted journal; diff computed on demand; roll-forward against GL dataset

**Effort / phase.** L (8 pd) · 4 Tools. Source: `app/engagements/[id]/data/page.tsx`; rules in lib/tb.ts, lib/tb-reasons.ts, lib/tb-rollforward.ts, lib/tool-fed-papers.ts, lib/gates.ts (tb_mapped), app/api/engagements/[id]/tb/*. Screenshot: extra\e16-data.png, extra\d02-tb-analyzer-with-data.png

#### C.5.18 `/engagements/[id]/discussion` — Team discussion (threads)

**What it is.** Engagement-level threaded discussion board: post a root comment, reply inline under each thread; newest threads first. Supports the P5.2 engagement team discussion informally (P5.2 itself is a working paper).

**Rules enforced (plain words).**

- body-required
- too-long (> 4000 chars)
- parent must belong to the same engagement (not-found)
- notifications on reply

**Data.** Reads: comment, app_user, membership. Writes: comment; notification (createNotification x2 in lib/comments.ts: mention/reply).

**Who may do what.** auth() + layout F008; addCommentAction → lib/comments.ts addComment uses requireTenant() (not requireWrite: a read_only member can post — ambiguity)

**Sub-flows on this screen.** # post-comment, # reply-in-thread

**Navigation.** in: AppNav/dashboard; out: /engagements/[id]/dashboard

**Components / i18n.** AppNav, NavLink, Panel, PanelHeader, SubmitButton · t.discussion, t.dashboard.backToDashboard; parity ok

**Odoo 19 target.** Models: mail.message on ea.audit.engagement (chatter) or ea.audit.comment. View: form chatter. Groups: all team groups incl. group_read_only (as today) — decide whether read_only may post.

Use native chatter (mail.thread) on the engagement; threading via parent_id; notifications via followers

**Effort / phase.** S (1 pd) · 2 Engagement file. Source: `app/engagements/[id]/discussion/page.tsx`; rules in lib/comments.ts, app/actions/comments.ts. Screenshot: extra\e12-discussion.png

#### C.5.19 `/engagements/[id]/findings` — Findings register & misstatements (B5)

**What it is.** The findings register: B5 misstatement evaluation (uncorrected vs corrected totals against final materiality, trivial threshold and count, per-item corrected toggle and 'propose adjustment' link to the TB journal), a raise-finding form (route C1 deficiency / B4 matter, severity, section, title, detail, recommendation) and the lists of B4 and C1 findings with clear-with-response.

**Rules enforced (plain words).**

- Finding severity (FINDING_SEVERITIES): c1 route requires a valid severity (invalid-severity) — significant_deficiency / deficiency / other; title-required
- Clear needs response-required
- B5 evaluation (evaluateB5): uncorrected total vs final materiality, trivial threshold = materiality.trivial, trivial items excluded and need trivial-confirm when routed (trivial-confirm-required)
- Propose adjustment → /data?jdesc&jamount#journal
- Completion gates b5_within_materiality and b4_cleared read this register
- C5.11 deficiency evaluation grid is fed from c1 findings

**Data.** Reads: finding, misstatement, materiality, file_item, engagement, app_user. Writes: finding (routeFinding INSERT, clearFinding UPDATE status/response), misstatement (setMisstatementCorrected), activity_log, notification (execution.ts).

**Who may do what.** auth() + layout F008; raiseFindingAction/clearFindingAction/setCorrectedAction → lib/execution.ts (requireWrite)

**Sub-flows on this screen.** # raise-finding, # clear-finding (response), # toggle-corrected, # propose-adjustment

**Navigation.** in: tools, phases/conclusion workspace chip, C5.11 linked-findings-register; out: /engagements/[id]/tools (back), /engagements/[id]/data?jdesc=...#journal

**Components / i18n.** AppNav, ErrorBanner, Panel, PanelHeader, Chip · t.planning.findings, t.planning.execution; parity ok

**Odoo 19 target.** Models: ea.audit.finding, ea.audit.misstatement, ea.audit.materiality. View: list + form (kanban by route). Groups: ea_audit_core.group_staff+ write; read for eqr/read_only.

Selection fields route (b4/c1/b5) and severity; computed B5 evaluation on engagement; constraint severity required for c1; link to adjusting journal wizard; mail activity on raise

**Effort / phase.** M (4 pd) · 4 Tools. Source: `app/engagements/[id]/findings/page.tsx`; rules in lib/execution.ts (routeFinding, evaluateB5, clearFinding, setMisstatementCorrected), lib/deficiencies.ts, app/actions/execution.ts. Screenshot: extra\e13-findings.png; other agent: 10-findings-register.png

#### C.5.20 `/engagements/[id]/legal` — OHADA legal register (C5.2–C5.9)

**What it is.** Statutory workspace: C5.2 deadline calendar (generate from period end / AGM / report / board dates, mark done, overdue flags), C5.3 regulated agreements register and special report, C5.4 art. 715 board report, C5.7 registered-securities attestation, C5.5 alerte procedure (start, advance stage, resume), C5.6 criminal offences disclosure (partner only) and irregularities letter, C5.8 equity vs half share capital monitor, C5.9 co-CAC worksplit/cross-review/disagreement panels.

**Rules enforced (plain words).**

- Deadline calendar (lib/legal.ts generateDeadlines): fs_arrete = period end + 4 months (AUDCIF art. 23), continuing_conventions_notice = +1 month (art. 438), ago = +6 months (art. 72), docs_to_cac = AGM - 45 days (art. 71), cac_report_shareholders = AGM - 15 days, rapport_special_deposit = AGM - 15 days (art. 442), fs_filing_rccm = AGM (or AGO default) + 1 month (art. 269, provisional without AGM), art715_board = board date, file_assembly = report + 60 days (ISA 230), mandate_expiry (art. 704, 2/6 exercises), egm_equity when breach
- AGM-relative rows pending until AGM date (UAT B35); escalateOverdue notifies partners (deadline-overdue)
- Legal task not in scope → added from template (task-not-in-scope only when absent from DEFAULT_FILE_INDEX, UAT B34)
- Conventions: parties/interested/nature required, capacity in CONVENTION_CAPACITIES, unauthorized flag when no board authorisation
- Alerte (lib/alerte.ts): variant by legal form (SA vs SARL), ordered stages with deadlines (request_sent 15d art.150/153, reply_recorded, board_invited 15d, board_deliberated 30d, court_informed, rapport_special 8d, ag_communicated, closed), only next stage allowed (invalid-transition), event date not in future and not before previous (event-date-before-previous), one open alerte at a time (alerte-open), discontinued resumable within 6 months (resume-expired), a closed procedure stays readable and a new one can start
- C5.7 attestation requires the C5.7 task, inspection date and count > 0, and q_kept & q_agrees = yes on the paper (titres-work-incomplete, UAT run 3 B25)
- Equity monitor: equityCheck needs TB (no-tb) and share capital (share-capital-required); conclusion breach / unchecked-breach / stale / ok (equityConclusionOf with egm_equity deadline, UAT run 2 B22); breach notifies and feeds C5.8 paper (c58-equity-contradicts)
- Faits délictueux partner-only read and write (spec §12.5.6); co-CAC panels optimistic concurrency (baseVersion → stale-edit, UAT B104)
- UnsavedGuard warns on navigation

**Data.** Reads: statutory_deadline, convention, alerte, alerte_event, fait_delictueux (partner), completion_record (f8_*), client (share_capital, legal_form, mandate), engagement (agm_date, report_date, board_date), trial_balance* (equity), file_item (C5.7 presence), form_response (wp:C5.7), document, team_member, app_user. Writes: statutory_deadline (generateDeadlines upsert, markDeadlineDone), engagement (agm_date, report_date, board_date), convention, document + document_version (rapport spécial, art. 715, attestation titres, irregularities letter, fait disclosure, alerte stage letters), fait_delictueux, alerte, alerte_event, client.share_capital, completion_record (f8_worksplit/crossreview/disagreement with baseVersion), file_item (fileUnderCode adds missing C5.x task from template), notification (deadline-overdue, equity-breach), activity_log.

**Who may do what.** auth() + layout F008; isPartner = canPartnerSignoff(role) shows C5.6 faits section (listFaits forbidden otherwise); all writes requireWrite (read_only may view, not change — UAT B10); revealFait partner only

**Sub-flows on this screen.** # generate-deadlines, # legal-dates-form, # deadline-mark-done, # add-convention, # rapport-special, # article-715, # titres-attestation, # alerte-start, # alerte-advance, # alerte-resume, # reveal-fait (partner), # irregularities-letter (partner), # share-capital, # equity-check, # cocac-panels (3)

**Navigation.** in: phases/conclusion workspace chip, C5.8 paper link, AppNav; out: /documents/[id] via actions (redirect after generation)

**Components / i18n.** AppNav, ErrorBanner, UnsavedGuard · t.planning.legal (deadlineNames, deadlineBasis, stages, capacities...), t.planning.errors; parity ok

**Odoo 19 target.** Models: ea.audit.legal.deadline, ea.audit.legal.convention, ea.audit.legal.alerte, ea.audit.legal.alerte.event, ea.audit.legal.fait, ea.audit.completion.record, ea.audit.client (share_capital, legal_form), ea.audit.document. View: form (notebook per C5.x) + lists + wizards (alerte advance). Groups: view group_staff+; writes group_staff+ (not read_only); faits group_partner only (record rule).

ea_audit_legal addon: deadline generator method with OHADA article bases; alerte state machine with deadline computation per variant; QWeb/docx letters per stage; record rule restricting ea.audit.legal.fait to group_partner; cron escalating overdue deadlines to partners (mail.activity); equity check reading TB; co-CAC records with write_date optimistic lock

**Effort / phase.** XL (12 pd) · 5 Reports/portal/legal. Source: `app/engagements/[id]/legal/page.tsx`; rules in lib/legal.ts, lib/alerte.ts, lib/completion.ts (recordCompletion), lib/letters.ts/docx.ts, app/actions/legal.ts. Screenshot: extra\e14-legal-register.png, extra\e14b-legal-register-full.png

#### C.5.21 `/engagements/[id]/legal # alerte-start / alerte-advance / alerte-resume` — Alerte procedure (going-concern alert) state machine

**What it is.** Start the OHADA alerte with a note and event date; advance it one stage at a time (with note, event date, 'satisfactory' flag at reply_recorded), each stage producing a dated letter; resume a discontinued procedure within six months.

**Rules enforced (plain words).**

- FLOWS per variant (sarl: request_sent→reply_recorded→court_informed→rapport_special→ag_communicated→closed; sa: request_sent→reply_recorded→board_invited→board_deliberated→rapport_special→ag_communicated→closed) with deadline days 15/15/15/30/8; one open alerte; invalid-event-date (future), event-date-before-previous; alerte-discontinued; not-discontinued; resume-expired (6 months)
- E6.3 going-concern linkage via activeAlerte

**Data.** Reads: alerte, alerte_event, engagement, client, team_member, app_user. Writes: alerte (stage, stage_deadline, discontinued_at), alerte_event, document/document_version (stage letters).

**Who may do what.** requireWrite(); team F008

**Navigation.** stays on /legal

**Components / i18n.** inline forms · t.planning.legal.stages/alerte

**Odoo 19 target.** Models: ea.audit.legal.alerte, ea.audit.legal.alerte.event. View: form with statusbar + wizard. Groups: ea_audit_core.group_staff+.

state selection per variant; compute next allowed stage; constraints on dates; letter templates per stage

**Effort / phase.** M (3 pd) · 5 Reports/portal/legal. Source: `app/actions/legal.ts startAlerteAction/advanceAlerteAction/resumeAlerteAction → lib/alerte.ts`; rules in lib/alerte.ts. Screenshot: extra\e14-legal-register.png, extra\e14b-legal-register-full.png

#### C.5.22 `/engagements/[id]/legal # equity-monitor (C5.8)` — Net equity vs half share capital monitor (art. 664)

**What it is.** Record the client's share capital and run the equity check against the working (pre- or post-audit) TB; a breach creates the egm_equity deadline, notifies and is reflected in the C5.8 paper.

**Rules enforced (plain words).**

- invalid-amount (> 0); no-tb; share-capital-required; equityConclusionOf → breach / unchecked-breach / stale / ok
- C5.8 paper save refused (c58-equity-contradicts) when claiming equity above half capital while figures show a breach

**Data.** Reads: trial_balance*, client.share_capital, statutory_deadline (egm_equity). Writes: client.share_capital, statutory_deadline (egm_equity), notification (equity-breach).

**Who may do what.** requireWrite

**Navigation.** stays; C5.8 paper links here

**Components / i18n.** forms · t.planning.legal.equity*

**Odoo 19 target.** Models: ea.audit.client, ea.audit.legal.deadline. View: form section + button. Groups: ea_audit_core.group_staff+.

computed equity from TB class totals; deadline creation on breach

**Effort / phase.** S (1 pd) · 5 Reports/portal/legal. Source: `app/actions/legal.ts equityCheckAction / setShareCapitalAction → lib/legal.ts equityCheck, equityStatus, setShareCapital`; rules in lib/legal.ts. Screenshot: extra\e14-legal-register.png, extra\e14b-legal-register-full.png

#### C.5.23 `/engagements/[id]/legal # titres-attestation (C5.7)` — Registered securities attestation (C5.7)

**What it is.** Generates the attestation document from inspection date and securities count once the C5.7 paper confirms the register is kept and agrees.

**Rules enforced (plain words).**

- titres-task-missing (C5.7 not on file, UAT run 3 B25)
- titres-inspection-date-required
- titres-count-required (> 0)
- titres-work-incomplete unless q_kept and q_agrees = yes

**Data.** Reads: file_item (C5.7), form_response (wp:C5.7 q_kept, q_agrees), engagement, client. Writes: document + document_version filed under C5.7.

**Who may do what.** requireWrite

**Navigation.** redirect /documents/[id]

**Components / i18n.** inline form · t.planning.legal

**Odoo 19 target.** Models: ea.audit.document. View: server action (docx). Groups: ea_audit_core.group_staff+.

report template in ea_audit_reports; constraint on paper answers

**Effort / phase.** S (1 pd) · 5 Reports/portal/legal. Source: `app/actions/legal.ts titresAttestationAction → lib/legal.ts generateTitresAttestation`; rules in lib/legal.ts. Screenshot: extra\e14-legal-register.png, extra\e14b-legal-register-full.png

#### C.5.24 `/engagements/[id]/nature` — Nature of entity (complexity questionnaire)

**What it is.** Seventeen yes/no questions (with live preview) conclude whether the entity is complex, non-complex or very simple; the conclusion propagates the file index at the matching scope (core / core+standard / all) and seeds the two presumed ISA 240 risks. Reopens with saved answers; reclassifying after planning started needs a reason.

**Rules enforced (plain words).**

- Complexity classification (lib/complexity.ts classifyComplexity): knock-out questions (listing, public interest, group consolidation...) force complex; else score >= COMPLEX_THRESHOLD → complex, >= NON_COMPLEX_THRESHOLD → non_complex, else very_simple; server recomputes from raw answers (never trusts the preview)
- File-index tiers (lib/file-index.ts tierOf/itemsForComplexity): very_simple = core only and no conditional items, non_complex = core + standard, complex = everything (CORE_CODES includes the whole acceptance D3 family, P6.2, P7.1, P7.2, C-core
- EXTENDED_CODES C4.2, E4.6, E4.12, E4.13, C5.5, C5.9)
- Reclassification: after planning started a reason >= 3 chars is required (reclassify-reason-required) and only adds missing tasks; after execution it is refused (reclassify-too-late, UAT run 2 B77)
- Redirect: first classification → /team, reclassification → /dashboard
- Engagement name applies the firm naming convention {CLIENT}_{PERIOD_END}_{NATURE}

**Data.** Reads: engagement (complexity_answers, complexity, phase), file_item (propagated?). Writes: engagement (complexity, complexity_answers), file_item (INSERT itemsForComplexity ... ON CONFLICT DO NOTHING), risk (seedPresumedRisks: revenue_fraud, management override), activity_log 'Nature of entity concluded: ... (reason: ...)'.

**Who may do what.** auth() + layout F008; classifyEntityAction → applyComplexity (requireWrite; ForbiddenError surfaces as ?error=)

**Sub-flows on this screen.** # classify-and-propagate, # reclassify-with-reason

**Navigation.** in: dashboard redirect when no tasks, acceptance classify-first link; out: /engagements/[id]/team or /dashboard

**Components / i18n.** AppNav, ErrorBanner, NatureAssessment (client, live preview) · t.engagements.assessment (questions, levels, hint, result, formsNote) + inline FR/EN; parity ok

**Odoo 19 target.** Models: ea.audit.engagement (complexity, complexity_answers JSON), ea.audit.file.item, ea.audit.risk. View: wizard (TransientModel) → server action. Groups: ea_audit_core.group_staff+.

Questionnaire as wizard with computed preview; propagation method creating file items from ea.audit.file.index.template (data XML, 118 entries with tier/conditional); reason required when state != acceptance; refuse after execution

**Effort / phase.** M (3 pd) · 2 Engagement file. Source: `app/engagements/[id]/nature/page.tsx`; rules in lib/complexity.ts, lib/file-index.ts, lib/engagements.ts (applyComplexity), lib/risks.ts (seedPresumedRisks), app/actions/audit-file.ts (classifyEntityAction). Screenshot: extra\e11-nature.png

#### C.5.25 `/engagements/[id]/pbc` — PBC requests (client-provided documents)

**What it is.** Firm-side PBC register: add a request (title, note) which notifies the client portal users, table of items with status, requested/uploaded dates, age in days (red after 14) and chase count, Chase button for requested items, and Accept (or Attach) of an uploaded file onto an E section so it is filed as evidence.

**Rules enforced (plain words).**

- PBC chase: refused when the client has no portal contact (no-portal-contact, UAT run 2 B76); only status='requested' can be chased (wrong-status); increments chase_count, chased_at and notifies portal users
- Age computed in calendar days in Africa/Douala (UAT run2-B112), > 14 days red
- Accept requires a target E section (attach-required) — a file reachable from nowhere is refused; accept only from status 'uploaded' with content; attach for accepted items without document
- Upload safety: accepted content passes checkUpload (UnsafeFileError → file-type); portal upload cap MAX_PBC_BYTES, empty-file
- Status is read-only on the planning page (UAT B09)

**Data.** Reads: pbc_item, file_item, engagement, client, membership (portal contacts), team_member, app_user. Writes: pbc_item (INSERT; chased_at/chase_count; status accepted, document_id), document + document_version (accepted upload filed under the chosen E section), membership/app_user (portal contacts elsewhere), notification (pbc-requested, pbc-reminder, pbc-uploaded), activity_log (PBC requested/chased/uploaded/accepted/filed).

**Who may do what.** auth() + layout F008; addPbcItem requireWrite; chasePbc requireWrite; acceptPbc/attachAcceptedPbc require canReview(role) (senior+) → else forbidden

**Sub-flows on this screen.** # add-pbc-request, # chase-pbc, # accept-upload-to-section, # attach-accepted-file

**Navigation.** in: dashboard attention PBC chip, planning PBC list link, phases/execution workspace chip; out: /documents/[documentId]

**Components / i18n.** AppNav, ErrorBanner, Panel · t.pbc, t.portal.statuses; parity ok

**Odoo 19 target.** Models: ea.audit.pbc.item, ea.audit.document, res.partner (portal users). View: list + form; portal counterpart in ea_audit_portal. Groups: add/chase group_staff+; accept/attach group_senior+; base.group_portal for client upload.

pbc.item with state requested/uploaded/accepted/filed, chase_count, binary field; mail template to portal users on request/chase; portal controller for upload (ea_audit_portal); accept action creates document on target file item; upload safety validator shared

**Effort / phase.** M (4 pd) · 5 Reports/portal/legal. Source: `app/engagements/[id]/pbc/page.tsx`; rules in lib/pbc.ts, lib/upload-safety.ts, lib/notifications.ts, app/actions/pbc.ts. Screenshot: extra\e15-pbc.png

#### C.5.26 `/engagements/[id]/pbc # accept-upload-to-section` — Accept client upload and file it as evidence

**What it is.** Senior+ picks the E section and accepts the uploaded file, which becomes a document on that task; attach does the same for items accepted before the target became mandatory.

**Rules enforced (plain words).**

- attach-required
- wrong-status (must be uploaded with content / accepted without document)
- checkUpload on the stored bytes (file-type)
- redirect to the new document

**Data.** Reads: pbc_item FOR UPDATE, file_item. Writes: pbc_item (status accepted, document_id), document + document_version, activity_log 'PBC accepted/filed'.

**Who may do what.** canReview(role) (forbidden otherwise)

**Navigation.** redirect /documents/[id]

**Components / i18n.** inline select + button · t.pbc

**Odoo 19 target.** Models: ea.audit.pbc.item, ea.audit.document. View: wizard. Groups: ea_audit_core.group_senior+.

action_accept with required target file item; creates attachment/document

**Effort / phase.** S (1 pd) · 5 Reports/portal/legal. Source: `app/actions/pbc.ts acceptPbcAction / attachPbcAction → lib/pbc.ts acceptPbc / attachAcceptedPbc`; rules in lib/pbc.ts, lib/upload-safety.ts. Screenshot: extra\e15-pbc.png

#### C.5.27 `/engagements/[id]/planning` — Planning workspace (drivers, materiality, team/budget/PBC, material sections, gates)

**What it is.** Planning hub: the 20 planning driver papers with status (not required / not started / in progress / complete / signed) and open links, carry-forward from the prior year, P6.1 materiality versions with partner approval and a create form fed by TB benchmark bases, P2.2 team list with assign/remove and EQR declaration, budget hours by team grade, PBC quick list, manual material flags on E sections, and the planning→execution gates with Close planning.

**Rules enforced (plain words).**

- Materiality (lib/materiality.ts): justification-required; percentage 0-100, performancePct and trivialPct within PERFORMANCE_PCT_RANGE/TRIVIAL_PCT_RANGE (invalid-materiality)
- TE away from the default % needs performance-justification (ISA 320 ¶11, UAT B42); benchmark % out of BENCHMARK_RANGES or basis mismatch vs TB needs overrideJustification (materiality-out-of-range / materiality-basis-mismatch, UAT B47)
- Materiality approval: partner only (requires-partner), only the latest version (stale-version), draft → approved; approved version feeds P6.1 auto field, tool-fed gate and planning gate materiality_approved
- Driver status: signed when partner sign-off or task reviewed, complete when form complete or in_review, P6.1 complete once materiality approved; conditional drivers 'not required' unless S6.1 trigger true
- Planning close gates (lib/gates.ts planningCloseGatesTx): materiality_approved (latest version approved), p22/p52/s31_partner_signed (approvalSigned, only when the task is active on the file — UAT run 2 B09), p72_partner_signed (rasPartnerApprovedTx: P7.2 summary partner-approved, UAT run 2 B07), cra_reliance_supported (no cra 'rely' without selected control or basis), significant_risks_linked (every significant non-rebutted risk has >= 1 risk_response program step), rebuttals_approved (rebutted presumed revenue-fraud risk has rebuttal_approved_by), material_sections_covered (every material E file_item has a program_step not N/A — stand-back), tb_mapped, review_notes_cleared (no open note on P% / S% tasks, UAT B144)
- Close planning: locked transaction, snapshot of materiality/risks/program steps into planning_snapshot, phase='execution', logged
- Team assign: one-engagement-partner, partner-role-requires-partner-rank, EQR eligibility (eqr-rank, eqr-on-team, eqr-cooling-off 2 years as partner of same client, eqr-declaration-required), not-a-firm-member, email domain allow-list F070
- Team remove: last-partner refused, partner removal partner-only
- Budget grade must be a TEAM_ROLE so actuals (logged under team role) meet budget
- PBC add title-required

**Data.** Reads: form_response, signoff, document, file_item, materiality, trial_balance*, team_member, membership, app_user, budget_line, pbc_item, engagement, risk, risk_response, program_step, cra_assessment, scot*, review_note, syscohada_grouping_rule, client_grouping_override. Writes: form_response + related_party (carryForwardFromPriorYear), materiality (createMaterialityVersion draft; approveMateriality status approved), misstatement (reflagMisstatements), team_member (assign/remove), budget_line, pbc_item, file_item.material (setSectionMaterial), planning_snapshot + engagement.phase='execution' (closePlanning), activity_log, notification.

**Who may do what.** auth() + layout F008; all actions requireWrite; approveMateriality canPartnerSignoff (requires-partner); assignTeamMember requireTeamManager (manager+, not EQR; partner role needs partner rank); closePlanning any writer

**Sub-flows on this screen.** # carry-forward-prior-year, # materiality-create, # materiality-approve (partner), # team-assign, # team-remove, # budget-set, # pbc-quick-add, # toggle-material-section, # close-planning

**Navigation.** in: phases/planning workspace chip, time page 'Set the budget' (#budget), AppNav; out: /sections/[itemId], /considerations#code, /forms/[code], /pbc, /sections (E sections)

**Components / i18n.** AppNav, SubmitButton, MaterialityBasis (client), ErrorBanner, GatesPanel, Chip, Panel, PanelHeader · t.planning (driver, materiality, team, budget, pbc, sections, gates, gateNames, carryForward) (+ 1 inline EQR declaration + no-TB hint); parity ok

**Odoo 19 target.** Models: ea.audit.materiality (versions), ea.audit.team.member, ea.audit.budget.line, ea.audit.pbc.item, ea.audit.file.item (material), ea.audit.planning.snapshot, ea.audit.engagement. View: form (workspace) + wizards. Groups: view group_staff+; materiality approve group_partner; team assign group_manager+ (not eqr); close planning group_staff+.

Materiality as versioned model with state draft/approved/superseded and Python constraints for ranges/justifications; approval button group_partner; gate engine; close_planning in one transaction with snapshot JSON; team member constraints (sql unique partner per engagement, EQR eligibility checks); budget lines keyed by team role

**Effort / phase.** L (8 pd) · 2 Engagement file. Source: `app/engagements/[id]/planning/page.tsx`; rules in lib/gates.ts, lib/materiality.ts, lib/materiality-model.ts, lib/team.ts, lib/forms.ts (carryForwardFromPriorYear, isFormComplete), lib/planning-ras.ts (rasPartnerApprovedTx), lib/engagement-dashboard.ts, app/actions/planning.ts. Screenshot: extra\e07-planning.png

#### C.5.28 `/engagements/[id]/planning # close-planning` — Close planning (planning → execution gate)

**What it is.** Button shown while phase='planning': evaluates the planning close gates in a locked transaction, takes the planning snapshot and moves to execution.

**Rules enforced (plain words).**

- GateError lists failed keys (?failed=)
- wrong-phase
- snapshot = latest materiality, all risks, all program steps

**Data.** Reads: engagement FOR UPDATE + gate tables. Writes: planning_snapshot, engagement.phase='execution', activity_log.

**Who may do what.** requireWrite(); no explicit rank check

**Navigation.** stays on /planning

**Components / i18n.** GatesPanel + form · t.planning.closePlanning, gateNames

**Odoo 19 target.** Models: ea.audit.engagement, ea.audit.planning.snapshot. View: server action. Groups: ea_audit_core.group_staff+.

action_close_planning; snapshot JSON field

**Effort / phase.** S (1 pd) · 2 Engagement file. Source: `app/actions/planning.ts closePlanningAction → lib/gates.ts closePlanning`; rules in lib/gates.ts. Screenshot: extra\e07-planning.png

#### C.5.29 `/engagements/[id]/planning # materiality-create / materiality-approve` — Materiality version create & partner approval

**What it is.** Create a draft materiality version (benchmark, amount, %, performance %, trivial %, justifications) from TB-derived bases; the partner approves the latest draft, which becomes the file's figure (P6.1, SAD, significance).

**Rules enforced (plain words).**

- see planning page: justification-required, invalid-materiality, performance-justification-required, materiality-out-of-range, materiality-basis-mismatch, stale-version, not-found
- approved version is what tool-fed papers and gates read

**Data.** Reads: materiality, trial_balance*, team_member, app_user. Writes: materiality (INSERT draft / UPDATE approved, approved_by, approved_at), misstatement (reflag trivial), activity_log 'Materiality vN created/approved'.

**Who may do what.** create: requireWrite; approve: canPartnerSignoff(role) → else requires-partner

**Navigation.** stays on /planning (or returnTo)

**Components / i18n.** forms + MaterialityBasis · t.planning.materiality

**Odoo 19 target.** Models: ea.audit.materiality. View: form + button. Groups: create group_staff+; approve group_partner.

version_no sequence per engagement; state; constraints; action_approve sets state and supersedes earlier approved versions

**Effort / phase.** S (2 pd) · 4 Tools. Source: `app/actions/planning.ts createMaterialityAction / approveMaterialityAction → lib/materiality.ts`; rules in lib/materiality.ts, lib/materiality-model.ts. Screenshot: extra\e07-planning.png

#### C.5.30 `/engagements/[id]/risks` — Risk Console (ISA 315 risk register)

**What it is.** Three-lane risk console: add a documented risk (description, source, category business/fraud/error, level assertion/FS, likelihood, magnitude, inherent risk factors, index + assertions link, management-missed note, FS note, significant flag); potential risks raised from tasks (promote / dismiss with rationale); the register with the two presumed ISA 240 risks, category/level/significant/rebutted/pending-approval chips, spectrum-of-inherent-risk SVG, coverage chips (unlinked, unresponded significant, unjustified significant indexes, significant accounts without SCOT), per-risk index links, edit assessment, map to E section with assertions, and partner rebuttal of the presumed revenue-fraud risk.

**Rules enforced (plain words).**

- Presumed risks seeded at classification: revenue_fraud and management override; management override never rebuttable, presumed risks cannot be un-flagged significant (not-rebuttable)
- Revenue-fraud rebuttal needs partner + justification + engagement partner identity (F003) and sets rebutted/status concluded with approver recorded → planning gate rebuttals_approved
- Significant risk must link to a program step (planning gate significant_risks_linked
- 'unresponded' coverage chip)
- Risks added after planning close flagged addedAfterPlanning and need partner approval (approveRiskAddition, spec §8.4; completion gate risks_concluded counts unapproved additions)
- Description >= 3 chars (risk-description-required); index codes validated (invalid-index)
- CRA = IR when no controls reliance (ISA 315 ¶34 hint); inherentRating high and not significant → warning
- P5.2 potential risks: dismiss requires rationale, promote creates a register risk; significance orphans from P6.2 and SCOT coverage computed for the coverage chips

**Data.** Reads: risk, risk_lead_index, risk_section, risk_response, potential_risk, file_item, engagement, app_user, trial_balance*, form_response, scot, scot_index, sub_ledger_* (significantAccounts), client_lead_index_override. Writes: risk (INSERT addRisk; UPDATE likelihood/magnitude/factors/significant/controlsReliance/category/status/fsNote; rebutted + rebuttal_justification + rebuttal_approved_by; addition_approved_by), risk_lead_index (link/unlink), risk_section (mapRiskToSection), potential_risk (dismiss/promote), risk_response/program_step (linkRiskToStep elsewhere), activity_log.

**Who may do what.** auth() + layout F008; isPartner = canPartnerSignoff(role) shows the rebut form and approve-addition; rebutRevenueFraudRisk: canPartnerSignoff (rebut-partner-only) AND partnerTierRefusalTx (engagement partner/delegate F003); approveRiskAddition canPartnerSignoff; other writes requireWrite/requireTenant

**Sub-flows on this screen.** # add-risk, # potential-risk-promote, # potential-risk-dismiss, # link-risk-to-index, # unlink-index, # edit-assessment, # map-to-section, # rebut-revenue-fraud (partner), # approve-mid-audit-addition (partner)

**Navigation.** in: tools, phases/planning workspace chip, S3.1 TOOL_LINKS; out: /engagements/[id]/tools (back), P5.2 working paper (/sections/[p52]) or /forms/P5.2

**Components / i18n.** AppNav, AssertionLegend, DropdownChecklist (client), ErrorBanner, Panel, PanelHeader, Spectrum (inline SVG) · t.planning.risks, t.planning.execution (+ many inline FR/EN labels, FACTORS); parity ok

**Odoo 19 target.** Models: ea.audit.risk, ea.audit.risk.index.link, ea.audit.risk.section, ea.audit.risk.response, ea.audit.risk.potential. View: kanban/list + form (OWL spectrum chart optional). Groups: write group_staff+; rebut/approve addition group_partner + engagement partner identity.

risk model with selections (category, level, likelihood, magnitude, status), many2many assertions, presumed_type, rebutted fields; constraints replicating not-rebuttable; onchange computing inherent rating; coverage counters as computed fields on engagement; spectrum as graph view or OWL

**Effort / phase.** L (8 pd) · 4 Tools. Source: `app/engagements/[id]/risks/page.tsx`; rules in lib/risks.ts, lib/execution.ts (approveRiskAddition), lib/significant-accounts.ts, lib/assertions.ts, lib/lead-classes.ts, lib/signoff-policy.ts (partnerTierRefusalTx), app/actions/planning.ts, app/actions/execution.ts. Screenshot: extra\e08-risks.png, extra\d13-risks-with-data.png

#### C.5.31 `/engagements/[id]/risks # rebut-revenue-fraud` — Rebut the presumed revenue-fraud risk (partner)

**What it is.** Partner-only form with justification; marks the presumed revenue fraud risk rebutted/concluded with the approving partner recorded.

**Rules enforced (plain words).**

- justification-required
- not-rebuttable for anything but presumed_type='revenue_fraud'
- planning gate rebuttals_approved

**Data.** Reads: risk FOR UPDATE, team_member, engagement. Writes: risk (rebutted=true, rebuttal_justification, rebuttal_approved_by, significant=false, status='concluded').

**Who may do what.** canPartnerSignoff(role) (rebut-partner-only) + partnerTierRefusalTx === null (designated engagement partner or delegate)

**Navigation.** stays on /risks

**Components / i18n.** inline form · t.planning.risks.rebut*

**Odoo 19 target.** Models: ea.audit.risk. View: wizard. Groups: ea_audit_core.group_partner + engagement partner identity.

action_rebut with reason wizard; records approver

**Effort / phase.** S (1 pd) · 4 Tools. Source: `app/actions/planning.ts rebutRiskAction → lib/risks.ts rebutRevenueFraudRisk`; rules in lib/risks.ts. Screenshot: extra\e08-risks.png, extra\d13-risks-with-data.png

#### C.5.32 `/engagements/[id]/settings` — Engagement settings (period, standards edition, team link)

**What it is.** What belongs to this engagement: fiscal year, period end (correctable during acceptance/planning by a senior+, regenerating the engagement name and the legal calendar), retention date, the ISA standards edition (derived from the period start, overridable by a manager+ with a reason, F045) and a link to the team page.

**Rules enforced (plain words).**

- Period end only in acceptance/planning (UAT run 2 B96 regenerates C5.2 calendar)
- Engagement name regenerated via applyNamingConvention
- Standards edition F045: default editionForPeriod(periodEnd, duration) → periods beginning on/after 2026-12-15 use 'revised_2026' (ISA 240 Revised, ISA 570 Revised 2024) else 'current'; override requires manager+ and a reason (<= 500), shown as overridden vs derived; papers resolve {{tokens}} per edition
- Retention until shown when stamped

**Data.** Reads: engagement, client, statutory_deadline, tenant branding (naming convention). Writes: engagement (period_end, name; standards_edition + reason), statutory_deadline (regenerated; egm_equity realigned), activity_log (period_end_changed, standards edition change).

**Who may do what.** auth() + layout F008; periodEditable = (phase acceptance|planning) && canReview(role); editionEditable = phase != archived && atLeast(role,'manager'); server: updatePeriodEndAction canReview + phase check (wrong-phase); setStandardsEdition manager+ (forbidden), reason-required, archived refused

**Sub-flows on this screen.** # correct-period-end, # change-standards-edition (reason)

**Navigation.** in: dashboard; out: /engagements/[id]/dashboard, /engagements/[id]/team

**Components / i18n.** AppNav, ErrorBanner, SubmitButton, Panel · t.standardsEdition (+ inline FR/EN labels); parity ok

**Odoo 19 target.** Models: ea.audit.engagement (period_end, standards_edition, edition_reason, retention_until). View: settings-like form. Groups: period group_senior+ (state acceptance/planning); edition group_manager+.

compute default edition from period start; onchange regenerating name and legal deadlines; tracking with reason via wizard

**Effort / phase.** S (2 pd) · 2 Engagement file. Source: `app/engagements/[id]/settings/page.tsx`; rules in lib/standards-edition.ts, lib/engagements.ts (setStandardsEdition, standardsEditionOf), lib/complexity.ts (applyNamingConvention), lib/legal.ts (generateDeadlines), app/actions/audit-file.ts. Screenshot: extra\e05-engagement-settings.png; other agent: 07-settings-signoff-matrix.png

#### C.5.33 `/new-engagement` — New audit engagement

**What it is.** Engagement creation reduced to the identity questions: client name typed with datalist (existing client matched by name, new name creates the entity with a legal form), fiscal year + period end date (defaults to the client's year-end or 31 Dec), nature (statutory audit / agreed-upon procedures / other free text) and the mandatory engagement partner; the generated engagement name is previewed live from the firm's naming convention. Scope (nature of entity) and team follow on later screens.

**Rules enforced (plain words).**

- role minimum staff to open a file (assurance C2)
- engagement partner mandatory and must be a firm user with role partner or firm_admin (engagement-partner-required, partner-role-requires-partner-rank)
- fiscal year integer 2000–2100, period end must be a valid ISO date (invalid-engagement) default <FY>-12-31 or client year_end
- client matched case/whitespace-insensitively, >1 match → ambiguous-client, no match → client created (legal form default SA, listed/coCac false)
- engagement name = applyNamingConvention(branding.engagementNaming default '{CLIENT}_{PERIOD_END}_{NATURE}') max 120
- complexity null = deferred scoping (no file_items until /nature)
- uniqueness one engagement per client per fiscal year (PG 23505 → duplicate-engagement)
- standards edition default by period start: revised_2026 when period start ≥ 2026-12-15 else current (F045)
- continuance: when a prior-year engagement exists → first_year=false, P1.1 engagement_type 'continuing', carry-forward of prior fields, activity 'continuance'
- creator (manager/senior/staff) auto-seated accepted, a partner/firm_admin creating for another partner is NOT seated → redirect /engagements?error=created-not-on-team (F008)
- otherwise → /engagements/[id]/nature
- nature 'other' requires free text max 60

**Data.** Reads: client (listClients), tenant.branding (getBranding naming), app_user JOIN membership (lib/team.ts listFirmUsers — partners/firm admins). Writes: client (INSERT when new name), engagement (INSERT incl. standards_edition, first_year), team_member (partner seated accepted; creator seated if manager/senior/staff), form_response (P1.1 engagement_type='continuing' on continuance), engagement.first_year=false, carried form_response rows, activity_log (created, continuance). Server action: components/EngagementWizard → app/actions/audit-file.ts createEngagementAction → lib/engagements.ts createEngagement.

**Who may do what.** `if (!atLeast(session.user.role as Role, "staff")) redirect("/dashboard")` — staff, senior, manager, eqr_reviewer, partner, firm_admin (read_only and client_user excluded); createEngagement/createClient use requireWrite()

**Sub-flows on this screen.** /new-engagement # EngagementWizard (client match/create, period end, nature, partner, generated name preview)

**Navigation.** reached from /dashboard and /engagements '+ New engagement', /clients/[id] 'New engagement for this entity' (?client=); → /engagements/[id]/nature or /engagements?error=…

**Components / i18n.** AppNav, EngagementWizard, ErrorBanner, Panel, SubmitButton, btnPrimary · en/fr keys engagements.newEngagementTitle/newEngagementHint/client/fiscalYear/createEngagement; wizard labels inline fr/en; NATURE_OPTIONS en/fr

**Odoo 19 target.** Models: ea.audit.engagement, ea.audit.client, ea.audit.team.member, ea.audit.form.response (P1.1), res.company naming convention field. View: wizard (TransientModel) → creates engagement. Groups: ea_audit_core.group_staff and above.

TransientModel ea.audit.engagement.wizard with onchange computing name preview (naming convention placeholders {CLIENT} {YEAR} {PERIOD_END} {NATURE}); SQL unique constraint (client_id, fiscal_year); partner_id domain on users in group_partner|group_firm_admin; standards_edition computed default; continuance detection by prior engagement of same client; post-create: seat partner (state accepted) and creator; redirect to Nature-of-entity step (ea_audit_core). Python port of lib/complexity.ts applyNamingConvention needed.

**Effort / phase.** M (5 pd) (estimate) · 2 Engagement file. Source: `app/new-engagement/page.tsx`; rules in app/actions/audit-file.ts (createEngagementAction), lib/engagements.ts (createEngagement), lib/complexity.ts, lib/standards-edition.ts (editionForPeriod), lib/team.ts (listFirmUsers), lib/forms.ts (carryForwardFromPriorYear), lib/engagement-dashboard.ts (priorYearEngagement), components/EngagementWizard.tsx. Screenshot: extra\x16-new-engagement-wizard.png

#### C.5.34 `/new-engagement # EngagementWizard` — Engagement wizard (identity questions)

**What it is.** Client component posting to createEngagementAction: client name input with datalist (shows 'Existing client' or 'New client — the entity will be created' and a legal-form select for new names), fiscal year (2000–2100) and period-end date (defaults to the client's recorded year-end parsed from '31/12' / '06-30' forms, else 12-31; editing the date re-derives the year), nature select with free text for 'other' (max 60), mandatory engagement partner select (firm partners and administrators, administrators labelled), and a live preview of the generated engagement name.

**Rules enforced (plain words).**

- client name max 80
- year-end parsing: 'a/b' with a > 12 → day/month else month/day, invalid → null
- period end = <year>-<MM-DD>
- name preview = applyNamingConvention(naming, client, year, {periodEnd, nature}) with nature upper-cased free text for 'other'
- partner required (HTML required + server check)
- empty partner list shows guidance to invite one via Settings > Users

**Data.** Reads: props from page: clients (id, name, yearEnd), partners (partner/firm_admin users), branding.engagementNaming. Writes: see /new-engagement (createEngagementAction).

**Who may do what.** staff and above (page gate atLeast(role,'staff'); action requireWrite)

**Navigation.** embedded on /new-engagement

**Components / i18n.** EngagementWizard, Panel, SubmitButton · labels from engagements.* passed as props; inline fr/en hints; NATURE_OPTIONS en/fr

**Odoo 19 target.** Models: ea.audit.engagement.wizard (TransientModel). View: wizard. Groups: ea_audit_core.group_staff and above.

Onchange methods replicate name preview and period-end defaulting; Many2one client with create-on-the-fly (quick create) replaces the datalist; partner_id domain by groups.

**Effort / phase.** S (2 pd) (estimate, included in /new-engagement M) · 2 Engagement file. Source: `components/EngagementWizard.tsx`; rules in components/EngagementWizard.tsx, lib/complexity.ts, app/actions/audit-file.ts. Screenshot: extra\x16-new-engagement-wizard.png

#### C.5.35 `/search` — Search

**What it is.** Full-text search across the audit file: query box (quotes for phrases, OR, '-' exclusion, accents ignored), result count (with '+' when truncated), hit cards with kind badge (entity record, engagement, task, risk, finding, misstatement, review note, conclusion, procedure, control test, SCOT, document, working paper), code, title, client and an escaped ts_headline snippet.

**Rules enforced (plain words).**

- engagement team visibility applied to every branch (F008); query < 2 chars returns nothing; websearch_to_tsquery with 'audit_search' config (fr/en branches); prefix fallback when no exact hit
- MAX_HITS+1 to flag truncation; snippet HTML escaped and only ts_headline <b> re-admitted (stored-XSS guard); plain GET form works without JS

**Data.** Reads: engagement, client (name/registration_number/niu), and the search_vector-indexed tables behind each kind (file_item, risk, finding, misstatement, review_note, section conclusions, program steps, control tests, scot, document, form_response 'wp:' answers) per lib/search.ts branchesFor. Writes: —.

**Who may do what.** any firm role (auth(); search() requireTenant) — hits limited to engagements the user is an accepted team member of (visibilityClause)

**Navigation.** reached from AppNav search box (GET /search?q=); → hit.href (task, document, register pages)

**Components / i18n.** AppNav, Panel · inline fr/en; KIND_LABEL en/fr map

**Odoo 19 target.** Models: all ea.audit.* content models; optional ea.audit.search.index. View: controller / OWL client action (or Odoo command palette). Groups: group_read_only+ (record rules apply).

Odoo has no cross-model full-text search in Community; options: PostgreSQL tsvector columns + a custom search controller returning typed hits (port of branchesFor), or per-model name_search via command palette. Record rules give visibility for free. Medium effort if cross-model relevance ranking is kept.

**Effort / phase.** M (4 pd) (estimate) · 3 Papers. Source: `app/search/page.tsx`; rules in lib/search.ts, lib/engagement-access.ts. Screenshot: extra\x12-search.png

### C.6 Working papers

#### C.6.1 `/documents/[id]` — Working paper

**What it is.** Viewer and review surface for one generated working-paper document (.docx): title and status chip (draft/signed), archived notice, check-out / cancel check-out / download current version, in-browser DocxPreview, upload-new-version panel when checked out by me; right pane with sign-off chips or buttons (preparer P, reviewer R, partner) greyed with the reason when refused (tool output missing, role below task minimum, self-review), EQR chip, reopen-with-reason form, voided sign-offs, review notes (add, clear with response) and the version history with restore.

**Rules enforced (plain words).**

- engagement team membership gate (guardDocument); fait délictueux partner-only (ISA 250 / OHADA)
- ArchivedError / 'archived': archived engagement is read-only (no checkout, upload, sign, reopen, note
- DB triggers enforce too); check-out: refused when signed (signed-locked) or checked out by another (checked-out-by-other); check-in only by the holder (not-checked-out); restore: not when signed or checked out (note: restoreVersion uses requireTenant, not requireWrite — proxy blocks read_only server actions); sign-off order: preparer first (preparer-first), already-signed refused, no-version, checked-out refused; self-review ban (preparer cannot sign reviewer/partner
- UI greys buttons)
- EQR independence: firm-role or team-role EQR read-only on team's work, may only sign 'eqr' on C4.2 and only if appointed (eqr-own-paper); must be ACCEPTED team member (not-on-team-to-sign, accept-engagement-first); role minimum (policy matrix F002): team role ≥ task minPreparer / minReviewer via effectiveTaskRule (role-below-task-minimum-<role>); partner tier only engagement partner or delegate (F003: designate-engagement-partner-first, not-engagement-partner); engagement partner pressing R on a partner-required paper is recorded as 'partner' (UAT B20)
- PARTNER_ONLY_APPROVAL codes P5.2, P7.2, S6.1, S6.2, S3.1, C1.1 refuse non-partner review (partner-only); phase gates: nothing of a later phase signed while earlier phase gates open (phaseStillOpen); tool-fed papers (F004): P6.1 needs approved materiality, P6.2 TB+materiality, C1.1 TB+materiality+SAD conclusion, E4.1–E4.34 valid current TB (tool-output-missing-*); open review notes block sign-off (open-notes); section conclusion reviewed first (review-conclusion-first)
- RAS approved (ras-not-approved); signing writes content_hash of the version; reviewer signature sets status 'signed' (partner-required papers wait for partner); reopen: manager+ with reason (reason-required), after report_date partner only (requires-partner-after-report-date), cannot void a more senior sign-off than own rank (SIGNOFF_TIER_FLOOR preparer→staff, reviewer→senior, partner→partner, eqr→partner: cannot-void-more-senior-signoff), voids sign-offs and returns to draft; review note body required; clearing requires response, by author or manager+, never by the paper's preparer (not-preparer-clears)

**Data.** Reads: document, file_item, app_user (getDocument); document_version (listVersions); signoff JOIN app_user (listSignoffs); review_note (listReviewNotes); engagement, client (getEngagement); fait_delictueux (guard); team_member, firm_signoff_policy, firm_task_signoff_rule (roleMinimumRefusals); materiality, trial_balance, trial_balance_version, form_response (toolOutputsMissing). Writes: document (checked_out_by/at, current_version, status) via checkoutAction/cancelCheckoutAction/restoreVersionAction/signAction/reopenAction; document_version (POST /api/documents/[id]/upload → checkinDocument; restoreVersion inserts new version); signoff (INSERT with content_hash; voided_at/void_reason on reopen); review_note (INSERT addNoteAction; UPDATE clearNoteAction); activity_log via recordActivity. Actions in app/actions/audit-file.ts: checkoutAction, cancelCheckoutAction, restoreVersionAction, signAction, reopenAction, addNoteAction, clearNoteAction; API: GET /api/documents/[id]/versions/[no], POST /api/documents/[id]/upload.

**Who may do what.** accepted team members of the document's engagement only (guardDocument → visibleToUser, else ForbiddenError rendered as 404); fait délictueux documents partner+ only (`canPartnerSignoff(role)`); writes require requireWrite (read_only cannot); reopen `requireRole("manager")`; reviewer sign needs canReview (senior+), partner sign canPartnerSignoff (partner+); eqr_reviewer may only sign 'eqr' on C4.2; clearing a note: author or atLeast(role,'manager')

**Sub-flows on this screen.** /documents/[id] # check-out / upload new version / cancel, /documents/[id] # sign-off P / R / Partner / EQR, /documents/[id] # reopen (void sign-offs) with reason, /documents/[id] # review notes add & clear, /documents/[id] # version history restore

**Navigation.** reached from task pages (/engagements/[id]/sections/[fileItemId]), phase lists after generateDocumentAction, PBC accept (→ /documents/<id>), search hits; → /engagements/[id] (back to file), /api/documents/[id]/versions/[no] (download)

**Components / i18n.** AppNav, DocxPreview, UploadVersion, Chip, Panel, PanelHeader · en/fr keys document.* (title, statusSigned/Draft, archivedNotice, checkout, signPreparer/Reviewer/Partner, signedBy*, reopen, reviewNotes, versions, errors.*)

**Odoo 19 target.** Models: ea.audit.document (state draft/signed, checked_out_by, current_version), ea.audit.document.version (ir.attachment), ea.audit.signoff (role, version_no, content_hash, voided_at, invalidated_at), ea.audit.review.note, ea.audit.signoff.policy / rule, ea.audit.file.item. View: form (with chatter) + OWL docx preview widget. Groups: read: team members (record rule); write: group_staff+; reviewer sign: group_senior+; partner sign: group_partner+; reopen: group_manager+; EQR: group_eqr.

Heaviest business-rule surface: port signDocument/reopenDocument as model methods with the full refusal catalogue (codes above) raised as UserError with translated messages; constraints: unique active signoff per (document, role); archived engagement → write() guard (ArchivedError) plus optional SQL trigger; docx preview needs an OWL component (docx-preview.js) or server-side PDF conversion; check-out/check-in semantics custom (Odoo documents module lacks locking) — consider 'documents' Enterprise not available in Community, so custom model with ir.attachment versions; review notes could reuse mail.activity but need status open/cleared + response, so custom model.

**Effort / phase.** XL (14 pd) (estimate) · 3 Papers. Source: `app/documents/[id]/page.tsx`; rules in lib/documents.ts, lib/signoff-policy.ts, lib/tool-fed-papers.ts, lib/eqr.ts, lib/gates.ts (phaseStillOpen), lib/mutability.ts, lib/engagement-access.ts, app/actions/audit-file.ts. Screenshot: —

#### C.6.2 `/engagements/[id]/forms/[code]` — Legacy planning form (task canvas)

**What it is.** Hub-and-spoke task page for the 17 legacy FORM_DEFINITIONS codes (P1.1, S6.1, S6.2, P3.1, P3.2, P4.1, P4.2, P4.3, S5.1, S5.2, S5.3, S4.1, P5.1, S4.2, S4.3, S4.4, P5.2): header with status chip, deadline and overdue days, P/R meta strip, due-date editor, template purpose/checklist, the typed form fields (boolean yes/no selects, selects, text, number, date) with carried-forward chips, evidence version trail, sign-off footer (Save / Save & hand off, reviewer R), review notes, S4.3 related-party and S4.4 estimates registers, and a raise-potential-risk box. P5.2 redirects to its working paper.

**Rules enforced (plain words).**

- Unanswered booleans not saved: blank yes/no stays unanswered so required checks cannot be faked (adversarial fix)
- Optimistic concurrency __revision → stale refused
- Save & hand off = saveForm + generateDocument + signDocument('preparer') — paper-incomplete redirects to the working-paper screen (UAT B30)
- Reviewer R: shown only when preparer signed and not yet reviewed; signDocument enforces self-review ban F001, role minimum F002 (belowMinimumCode), partner tier F003, tool-fed F004, phaseStillOpen, open-notes, review-conclusion-first, accept-engagement-first
- P1.1 trigger: auditor_change/engagement_type new → P1.2 task activated (setPredecessorTaskActiveTx, UAT run 2 B19)
- P5.2 redirect to sections (UAT B47)
- Due date: effectiveDueDate (task due_date else phaseDeadline)
- Carried forward chips from prior-year carryForward
- Read-only accounts see the form as a record

**Data.** Reads: form_response, file_item, document, document_version, signoff, review_note, related_party, accounting_estimate, engagement, app_user, firm template overrides (lib/template-overrides.ts appliedTemplate). Writes: form_response (saveForm), file_item (setPredecessorTaskActiveTx → P1.2 activation; due_date), document/document_version (hand-off generateDocument), signoff (preparer on hand-off, reviewer via R), potential_risk (raiseRiskAction), related_party / accounting_estimate (registers), activity_log.

**Who may do what.** auth() + layout F008; readOnly = !(isRole(role) && canWrite(role)) hides all controls (UAT run 3 B23); saveFormAction → saveForm (requireWrite); signOffReviewerAction → signDocument rules; setDueDateAction canWrite; raiseRiskAction → raisePotentialRisk (requireWrite)

**Sub-flows on this screen.** # save-form, # save-and-hand-off (preparer sign-off), # reviewer-sign-off, # set-due-date, # raise-potential-risk, # related-party-register (S4.3), # estimates-register (S4.4)

**Navigation.** in: /planning driver rows, /acceptance (P1.1), hub; out: back to /groups/[g] or /phases/[slug], /documents/[documentId], /api/documents/[id]/versions/[no], /sections/[itemId] (P5.2 redirect, paper-incomplete)

**Components / i18n.** AppNav, ErrorBanner, NavLink, SubmitButton, SubmitOnceButton, Panel, PanelHeader, Chip, PlanningRegisters (RelatedPartyRegister, EstimatesRegister) · t.planning, t.taskPage, t.dashboard (rowStatus, signoff, deadlineTag), t.document, t.common, t.fileIndex (+ inline evidence labels); parity ok

**Odoo 19 target.** Models: ea.audit.paper.response (form values), ea.audit.file.item, ea.audit.document, ea.audit.signoff, ea.audit.risk.potential, ea.audit.related.party, ea.audit.estimate. View: form (dynamic fields from definition). Groups: ea_audit_core.group_staff+ edit; group_read_only/group_eqr read; R: group_senior+ on team.

Legacy forms could be folded into the paper model (ea.audit.paper with x_fields from definition JSON); write_date-based optimistic lock; hand-off button = save + create document + preparer signoff; registers as one2many; mostly superseded by /sections — candidate for consolidation during migration

**Effort / phase.** M (5 pd) · 3 Papers. Source: `app/engagements/[id]/forms/[code]/page.tsx`; rules in lib/forms.ts, lib/documents.ts (signDocument, listReviewNotes, listVersions), lib/registers.ts, lib/risks.ts (raisePotentialRisk), lib/template-overrides.ts, lib/engagement-dashboard.ts (taskForItem, effectiveDueDate), app/actions/planning.ts, app/actions/audit-file.ts. Screenshot: extra\e28-paper-P1.1.png

#### C.6.3 `/engagements/[id]/groups/[group]` — Task group list (sign-off table)

**What it is.** The only place a group's detail tasks are listed (framework §7): one row per task with display code, title, preparer/reviewer state and initials, deadline tag, status, and in-row P/R sign-off squares. Offers 'Add missing tasks' for group members not yet on the file but in scope of the entity's complexity. E4 shows only accounts designed in S5.5 (or holding work) and warns about design gaps.

**Rules enforced (plain words).**

- Viewing never changes scope (UAT B155): tasks added only by the explicit button and only those itemsForComplexity(engagement.complexity) scopes in (core/standard/extended tiers)
- C4.2 follows EQR determination not tier (eqrRequiredTx, UAT run 2 B13)
- Tool-fed papers F004: toolOutputsMissing greys P/R with the reason (tool-output-missing-materiality/tb/sad)
- Role minimum F002: roleMinimumRefusals greys P/R with belowMinimumCode (D2)
- Self-review F001: selfPrepared row disables R with the self-review label; phaseStillOpen: later-phase tasks cannot be signed while an earlier phase is open (acceptance-open/planning-open/execution-open; conclusion papers except C6.x open from execution)
- Phase gate checked BEFORE generating the paper so a refused sign-off leaves no document (UAT run2-B142)
- E4 filter: only indexes designed in S5.5 (dspDesignedIndexes) or tasks holding work; design gaps banner (dspDesignGaps)
- Deadline: effectiveDueDate per task

**Data.** Reads: file_item, document, signoff, program_step, task_attachment, section_conclusion, form_response, team_member, app_user, engagement, firm_signoff_policy, firm_task_signoff_rule, materiality, trial_balance*, (S5.5 design form_response for E4). Writes: file_item (instantiateGroupTasksAction INSERT ... ON CONFLICT DO NOTHING; ensureTaskTx C4.2), document/document_version + signoff (signOffPreparerAction/signOffReviewerAction via signOffFromList), activity_log.

**Who may do what.** auth() + layout F008; canSign = canWrite(role) && !phaseStillOpen(taskPhase, engagement.phase, code); canReview(role) for R; Add missing tasks: canReview(role); server signDocument re-checks everything

**Sub-flows on this screen.** # sign-preparer-chip, # sign-reviewer-chip, # add-missing-group-tasks

**Navigation.** in: dashboard phase cards, phase/[section] group tiles, forms back link, sections back; out: /engagements/[id]/sections/[itemId] (every row), /engagements/[id]/dashboard

**Components / i18n.** AppNav, ErrorBanner, NavLink, PhaseTaskRow (client), SubmitButton, Panel, PanelHeader · t.dashboard (taskList, taskCols, signoff, deadlineTag, rowStatus, stage.addMissing), t.document.errors (+ page-local MONTHS, E4 gap banner inline); parity ok

**Odoo 19 target.** Models: ea.audit.file.item, ea.audit.signoff, ea.audit.task.group (static), ea.audit.signoff.policy, ea.audit.task.signoff.rule. View: list (editable buttons per row) / kanban. Groups: ea_audit_core.group_staff+ (P), group_senior+ (R), add tasks group_senior+.

List view with row buttons calling action_sign(role); button readonly/invisible computed by compute_sign_refusal (tool-fed, role-below-minimum, self-review, phase-open) so the reason shows as tooltip; group definitions as data XML (ea.audit.task.group); add-missing as server action respecting complexity tiers

**Effort / phase.** M (4 pd) · 3 Papers. Source: `app/engagements/[id]/groups/[group]/page.tsx`; rules in lib/engagement-dashboard.ts, lib/file-index.ts (itemsForComplexity), lib/completion.ts (eqrRequired), lib/gates.ts (phaseStillOpen), lib/signoff-policy.ts (roleMinimumRefusals), lib/tool-fed-papers.ts, lib/design-procedures.ts, lib/psp.ts (indexesForTask), lib/task-groups.ts, app/actions/audit-file.ts (signOffFromList, instantiateGroupTasksAction). Screenshot: extra\e32-group-p1.png

#### C.6.4 `/engagements/[id]/groups/[group] # sign-preparer-chip / sign-reviewer-chip` — In-row P / R sign-off squares

**What it is.** The P square generates the working paper if needed and signs as preparer (hand-off); the R square signs as reviewer (recorded as partner when the engagement partner presses R on a partner-gated paper). Disabled variants explain tool-fed, role-below-minimum and self-review refusals.

**Rules enforced (plain words).**

- signDocument order: role allowed (requires-senior/requires-partner), archived, EQR rules (eqr own paper C4.2 only), signed-locked, phaseStillOpen, not-on-team-to-sign / accept-engagement-first (UAT B133), belowMinimumCode(minPreparer|minReviewer) F002, partner recorded for engagement partner's R on partnerRequired papers (UAT B20), PARTNER_ONLY_APPROVAL (P5.2, P7.2, S6.1, S6.2, S3.1, C1.1) reviewer refused unless engagement partner/delegate, partner tier F003 (designate-engagement-partner-first / not-engagement-partner), tool-output-missing F004, no-version, checked-out, already-signed, preparer-first, paper-incomplete (bespoke papers: every required key answered or N/A with reason), embeddedWorkGap for S1.2/S1.3/S2.1/S2.2, significance-unjustified (P6.2), itapp-strategy-missing (S2.3), ras-not-approved (P7.2), self-review F001, open-notes (document or task notes), review-conclusion-first
- Lock: reviewer locks unless partnerRequired (PARTNER_GATED stay open until partner signs)

**Data.** Reads: file_item, engagement, document, signoff, team_member, firm_signoff_policy, firm_task_signoff_rule, form_response, review_note, section_conclusion, materiality, trial_balance*. Writes: document/document_version (get-or-create), signoff (content_hash bound), document.status='signed' (reviewer when no partner required, or partner), activity_log '<code> signed off as <role>'.

**Who may do what.** P: canWrite + phase open + accepted team member at/above minPreparer; R: canReview (firm) AND team role in TEAM_REVIEW_ROLES (senior..partner) at/above minReviewer; EQR never signs P/R (eqr-read-only/forbidden)

**Navigation.** redirect back to returnTo (group/phase list) with ?error=code on refusal

**Components / i18n.** PhaseTaskRow · t.dashboard.signAsPreparer/signAsReviewer, t.document.errors

**Odoo 19 target.** Models: ea.audit.signoff, ea.audit.document. View: server action (row buttons). Groups: P group_staff+; R group_senior+; partner tier group_partner + engagement partner identity.

Central ea.audit.signoff.create() constraint chain replicating signDocument; content_hash of paper answers stored on signoff; document state; refusal codes as translatable UserError; the firm sign-off policy (min roles per task family, partner list) as configurable models in ea_audit_core

**Effort / phase.** L (6 pd) · 3 Papers. Source: `components/PhaseTaskRow.tsx → app/actions/audit-file.ts signOffPreparerAction / signOffReviewerAction → lib/documents.ts signDocument`; rules in lib/documents.ts (signDocument), lib/signoff-policy.ts, lib/eqr.ts, lib/tool-fed-papers.ts, lib/gates.ts, lib/working-papers.ts (paperMissing, paperContentHashTx). Screenshot: extra\e32-group-p1.png

#### C.6.5 `/engagements/[id]/phase/[section]` — Phase overview (acceptance / strategy / execution / conclusion)

**What it is.** Read-only phase page: reviewed count, the phase gate name, an intro, 'fed by' / 'feeds' links to the other phases, every task of the phase in execution order with status dot, assignee and standard, the conditional papers that apply in some engagements (outside the count), and group tiles with progress.

**Rules enforced (plain words).**

- SECTION_ORDER acceptance→strategy→execution→conclusion with SECTION_GATE labels
- conditional tasks listed separately and excluded from the count
- standards edition shown per task (paperFor(code, engagement.standardsEdition).std, F045)

**Data.** Reads: file_item, document, signoff, program_step, task_attachment, section_conclusion, form_response, team_member, app_user, engagement. Writes: —.

**Who may do what.** auth() + layout F008; read-only

**Navigation.** in: dashboard; out: /engagements/[id]/dashboard, /phase/[other], /sections/[itemId], /groups/[g]

**Components / i18n.** AppNav, Chip, Panel, PanelHeader · inline FR/EN labels + page-local STATUS_LABEL; PHASE_INTRO from lib/working-papers

**Odoo 19 target.** Models: ea.audit.file.item, ea.audit.task.group. View: kanban/list grouped by group. Groups: all team groups.

Could be a filtered list view of file items grouped by task group with a header; edition label from engagement

**Effort / phase.** S (2 pd) · 2 Engagement file. Source: `app/engagements/[id]/phase/[section]/page.tsx`; rules in lib/task-groups.ts, lib/working-papers.ts (PHASE_INTRO, paperFor), lib/engagement-dashboard.ts. Screenshot: —

#### C.6.6 `/engagements/[id]/phases/[phase]` — Phase task sign-off table (pre-planning / planning / execution / conclusion)

**What it is.** Phase drill-down behind a dashboard gauge: workspace chips (acceptance; planning + risks; data + analytics + PBC; legal + conclusion + findings), a 'phase locked' banner naming the failing gates of the still-open earlier phase, and the sign-off table with in-row P/R squares (PhaseTaskRow), deadline tags and status.

**Rules enforced (plain words).**

- Gates, not guidance (UAT B15): phaseStillOpen(phase, currentPhase) → read-only table + banner listing acceptanceGates or planningCloseGates failures
- Tool-fed F004 and role-minimum F002 greyed chips with reasons; self-review F001 chip; phaseDeadline per phase (-90/-45/+90/+150 days) with per-task due_date override; header count = real reviewed sign-offs

**Data.** Reads: file_item, document, signoff, team_member, app_user, engagement, form_response, review_note, materiality, trial_balance*, firm_signoff_policy, firm_task_signoff_rule, risk, program_step, cra_assessment, scot* (gates). Writes: document/document_version + signoff via signOffFromList; activity_log.

**Who may do what.** auth() + layout F008; canSign = !phaseStillOpen(phase, engagement.phase) && canWrite(role); mayReview = canReview(role); server rules in signDocument

**Sub-flows on this screen.** # sign-preparer-chip, # sign-reviewer-chip, # phase-locked-banner

**Navigation.** in: dashboard gauges, forms back link; out: /engagements/[id]/sections/[itemId], workspace chips (/acceptance, /planning, /risks, /data, /analytics, /pbc, /legal, /conclusion, /findings), /dashboard

**Components / i18n.** AppNav, ErrorBanner, GatesPanel, NavLink, PhaseTaskRow, Chip, Panel, PanelHeader · t.dashboard (phaseNames, taskList, taskCols, signoff, deadlineTag, rowStatus, taskStatus), t.planning (titles, errors), t.document.errors (+ page-local PHASE_TITLES/MONTHS); parity ok

**Odoo 19 target.** Models: ea.audit.file.item, ea.audit.signoff, ea.audit.gate. View: list with row buttons. Groups: P group_staff+, R group_senior+.

Same list as groups page filtered by phase; banner computed from gate engine; PHASE_SLUGS pre-planning→acceptance

**Effort / phase.** M (4 pd) · 3 Papers. Source: `app/engagements/[id]/phases/[phase]/page.tsx`; rules in lib/gates.ts (phaseStillOpen, acceptanceGates, planningCloseGates), lib/engagement-dashboard.ts (phaseTasks, phaseDeadline), lib/signoff-policy.ts, lib/tool-fed-papers.ts, app/actions/audit-file.ts. Screenshot: extra\e22-phase-planning.png, extra\e23-phase-execution.png, extra\e24-phase-conclusion.png

#### C.6.7 `/engagements/[id]/sections/[itemId]` — Working-paper screen (canonical task page)

**What it is.** The one page every task opens on: header band (tool chip, back, code/title with TL badge, standards edition line, deadline/overdue chip, P/R (+EQR) sign-off chips, assignee select, N/A toggle), left rail (guidance from the paper definition, practical tips, review notes), centre PaperWizard (status page, questionnaire pages, conclusion + key findings) with task-specific boards in the embed slot (SCOT register, WCGW builder, walkthroughs, FSCP, IT apps, CRA, substantive design, deficiency grid, archive checklist) and side registers (significant accounts, trigger panel, related parties, estimates, materiality strip, FS tie-out), right rail (attachments and linked tasks). E4 account tasks use a dedicated layout: AccountWorkpaper (lead schedule, PSP program generated from the S5.5 design, attachments), section conclusion with review, and a matter-arising form.

**Rules enforced (plain words).**

- Team-only F008
- Self-review ban F001: preparer never reviews own paper (chip disabled, server self-review)
- Role minimum F002 from firm sign-off policy matrix (roleMinimumRefusals/belowMinimumCode) greys P/R
- Partner tier F003 (designated engagement partner or delegate; engagement partner's R recorded as partner on partnerRequired papers
- PARTNER_ONLY_APPROVAL codes)
- EQR read-only on team work and C4.2 keys reserved (EQR_C42_KEYS writable only by the appointed EQR, other C4.2 keys locked for the EQR
- EQR signs only 'eqr' on C4.2; filterPaperWrite eqr-read-only/eqr-own-paper)
- Tool-fed F004: P6.1/P6.2/C1.1/E4.1-34 chips greyed until tool output exists; phaseStillOpen on sign-off
- Archive immutability: archived file read-only everywhere (viewOnly, chips locked, attachments readOnlyReason)
- Paper completeness: sign-off refused (paper-incomplete) until every required key answered or N/A with reason (F040), exempt for E4.x, P7.2, embed-only and non-bespoke papers
- Embedded work gaps (S1.2/S1.3/S2.1/S2.2) and S2.3 itapp-strategy-missing, P6.2 significance-unjustified, P7.2 ras-not-approved
- Sign-off voiding on later edits: savePaper → invalidateStaleSignoffs voids signatures whose content_hash no longer matches (invalidated_at + voided_at + reason), voided review also clears the section conclusion review, paper returns to draft, signers notified (signoff-voided), answer history F027 in activity_log
- Optimistic concurrency: __baseVersion + per-field digests, advisory lock; stale-edit refuses, StaleEditConflict keeps the user's text in a 30-min httpOnly cookie and shows the colleague's version per field (UAT run 3 firm.perf-concurrent)
- Refused saves (c58-equity-contradicts when C5.8 q_above=yes but equity breach; tieout-unexplained when E6.10 q_n_agrees=yes with unexplained tie-out differences) keep typed text (UAT run 4 B01)
- Review notes block gates: open task/document notes refuse R (open-notes) and keep planning/archive gates red; note respond by preparer, clear by author or manager+ who is not the preparer (not-preparer-clears, UAT B19)
- N/A toggle: canReview, not EQR, reason required (<= 500), reinstate clears; counts as done for % and archive gate tasks_addressed
- Assignment: canReview, assignee must be a team member and never the EQR (eqr-not-assignable, UAT B73), assignee off the team still shown (UAT run 2 B04), notification task_assigned
- Attachments: upload staff+ via /api/attachments (25 MB, checkUpload: extension allow-list, executables refused, magic bytes/OOXML marker, empty-file), versioned by filename, rename staff+, delete/restore manager+ within the recovery window (restore-window-expired), copy from existing, templates (E/F/K/N account workpapers, ITGC, JE testing, FS checklist) auto-attached on first open (ensureDefaultWorkpaper), EQR refused (assertNotEqrWriteOnItem)
- E4 account: generatePsp materialises the S5.5 design as program steps on open (idempotent), only indexes with a design selection are performable, CRA chip from S3.1, SAP counts link, lead schedule from working TB
- Section conclusion: conclusion-required, steps-open refused, no retained procedure → noProceduresRationale required (UAT B45), review by senior+/partner with self-review ban, team membership, accept-engagement-first, F002 minimum, partner tier
- R refused until conclusion reviewed (review-conclusion-first, UAT B149)
- Matter arising: routeFinding c1 needs severity
- Standards edition F045: paper tokens resolved per engagement.standardsEdition, edition line in header
- Auto fields (blue) filled from tools: P6.1 benchmark (approved materiality + specific thresholds + TE justification), S6.1 context, S5.4 je_design
- Linked tasks from CROSS_LINKS + group siblings (max 6); back= param honoured only for same-engagement paths

**Data.** Reads: file_item, engagement, form_response (wp:<code>, legacy forms, 'sad', 'fscp', dsp/itapps/ras keys), document, document_version, signoff, review_note, task_attachment, program_step, section_conclusion, risk*, materiality, trial_balance*, cra_assessment*, scot*, wcgw*, control_test, toc_sample_draw, finding, misstatement, deficiency_evaluation, related_party, accounting_estimate, statutory_deadline, client, team_member, membership, app_user, firm_signoff_policy, firm_task_signoff_rule, sub_ledger_*, substantive_analytical_procedure, paper-draft cookie. Writes: form_response (savePaper; board saves via /api/cra, /api/scots, /api/dsp, /api/itapps, /api/significance, /api/planning-ras, /api/psp), signoff (P/R/EQR; invalidateStaleSignoffs voids on edit), document (status, get-or-create), program_step + risk_response (generatePsp on open, PSP results), section_conclusion (save/review), finding/misstatement (routeFinding), file_item (assignee_user_id, na_reason/na_by/na_at), task_attachment (upload/rename/delete/restore/versions/templates), review_note (task notes raise/respond/clear), deficiency_evaluation + finding severity (C5.11), scot/wcgw/scot_control/scot_index/toc_sample_draw (SCOT studio), cra_assessment(+history, index settings), activity_log, notification.

**Who may do what.** auth() + layout F008; itemId must be a UUID of this engagement (404 otherwise); viewOnly = archived || !canWrite(role) || (actsAsEqr && code !== 'C4.2') || (C4.2 && firm-role EQR not appointed); chipsLocked = archived || !canWrite || actsAsEqr; mayReviewHere = canReview(role) && (no team role || team role in TEAM_REVIEW_ROLES senior..partner); canAssign/canMarkNa = canReview(role) && !isEqr; canManageEvidence (rename/delete/restore) = atLeast(role,'manager'); EQR chip active only for the appointed EQR on C4.2 (eqrStanding); server re-checks every rule

**Sub-flows on this screen.** # paper-wizard-steps, # sign-off-chips (P/R/EQR), # mark-not-applicable, # assign-task, # review-note-thread, # attachments-drawer, # section-conclusion-and-review (E4), # matter-arising (E4), # scot-register (S1.1), # wcgw-builder (S1.2/S2.1/S2.2), # walkthrough-board (S1.3), # fscp-form (S1.4), # itapps-board (S2.3/S2.5), # cra-matrix (S3.1), # design-procedures-board (S5.5), # significant-accounts-grid (P6.2), # trigger-panel (S6.1/S4.2), # registers (S4.3/S4.4/E6.2/E6.7), # planning-ras (P7.2), # toc-board (E1.2), # deficiency-grid (C5.11), # archive-checklist (C6.1/C6.2), # eqr-sign-off (C4.2), # stale-edit-conflict-merge, # tie-out-board (E6.10), # equity-monitor (C5.8)

**Navigation.** in: every task row (groups, phases, phase, tasks, dashboard my-tasks, planning drivers, considerations, hub E items, search); out: back to /groups/[g] or /dashboard (E4: /groups/e4 or ?back), tool chips (/tools/materiality, /tools/sad, /risks, /analytics), /cra, /tools/sap?index=, /tools/lead-schedule#idx, /tools/sampling, /findings, /legal (C5.8), /api/engagements/[id]/toc/export (E1.2), S5.5 design paper, linked tasks

**Components / i18n.** AppNav, PaperWizard (client), PracticalTips, ReviewNotes (client), Fold/MaybeFold, SignificantAccounts, PlanningRas, SrmMattersPanel, DeficiencyEvaluationPanel, DesignProceduresBoard, ItAppsBoard, AccountWorkpaper, ScotRegister, WcgwBuilder, WalkthroughBoard, TocBoard, FscpForm, PlanningRegisters, TriggerPanel, CraBoard, SubmitButton, TaskAttachments (client), ErrorBanner, Panel, PanelHeader, Chip, ArchiveChecklist · t.planning (execution, findings, legal), t.document.errors, t.planning.carriedForward (+ extensive inline FR/EN in page and components; paper definitions carry EN/FR text); parity ok for messages

**Odoo 19 target.** Models: ea.audit.file.item, ea.audit.paper (definition), ea.audit.paper.response, ea.audit.signoff, ea.audit.document, ea.audit.review.note, ea.audit.attachment (+version), ea.audit.program.step, ea.audit.section.conclusion, ea.audit.finding, ea.audit.scot/wcgw/control, ea.audit.cra.assessment, ea.audit.deficiency.evaluation, ea.audit.related.party, ea.audit.estimate, ea.audit.ras.answer. View: form (OWL paper wizard) with embedded OWL boards; list for attachments/notes. Groups: edit group_staff+ on team; R group_senior+; partner tier group_partner; group_eqr read-only except C4.2 EQR keys; N/A & assign group_senior+; evidence delete group_manager+; group_read_only read.

Core of ea_audit_papers: paper definitions as data (JSON/XML) rendered by an OWL wizard; ea.audit.paper.response keyed by (engagement, code, field_key) with write tracking for F027; signoff model with content_hash and automatic invalidation on response write (override write); constraint chain for sign-off refusal codes; optimistic lock via base version + per-field digest (custom); attachments with versioning and upload validator; review notes as model with state open/cleared and respond/clear permissions; per-code embed components in ea_audit_tools (SCOT studio, CRA, DSP, ITGC, significance, RAS, deficiencies); E4 account view variant; standards-edition token resolution at render

**Effort / phase.** XL (20 pd) · 3 Papers. Source: `app/engagements/[id]/sections/[itemId]/page.tsx`; rules in lib/working-papers.ts, lib/documents.ts, lib/signoff-policy.ts, lib/eqr.ts, lib/tool-fed-papers.ts, lib/gates.ts, lib/mutability.ts, lib/task-notes.ts, lib/attachments.ts, lib/upload-safety.ts, lib/wp-templates.ts, lib/paper-drafts.ts, lib/team.ts (assignTask, getTaskAssignee), lib/execution.ts, lib/psp.ts, lib/programs.ts, lib/significant-accounts.ts, lib/cra.ts, lib/design-procedures.ts, lib/itgc.ts, lib/scots.ts, lib/planning-ras.ts, lib/deficiencies.ts, lib/archive-checklist.ts, lib/registers.ts, lib/legal.ts (equityStatus), lib/fs-tieout.ts, lib/standards-edition.ts, lib/papers/*.ts, app/actions/planning.ts (savePaperAction, markNotApplicableAction, assignTaskAction), app/actions/audit-file.ts (signOff*Action), app/actions/execution.ts, app/api/engagements/[id]/{cra,scots,dsp,itapps,significance,planning-ras,psp,task-notes}/route.ts, app/api/attachments/*. Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.8 `/engagements/[id]/sections/[itemId] # archive-checklist (C6.1 / C6.2)` — Archive checklist board (gates and open items)

**What it is.** Groups report / completion / papers / review / assembly listing every archive gate with pending counts and the items behind each (with fix links); on C6.2 also the Archive button (partner, all gates green) and the roll-forward form after archiving.

**Rules enforced (plain words).**

- same as archive gates
- C6.1 paper records the judgement that every red-gate item was fixed or explained

**Data.** Reads: document, signoff, file_item, review_note, program_step, section_conclusion, finding, risk, scot, scot_control, control_test, form_response, engagement. Writes: engagement (archive), new engagement (rollforward).

**Who may do what.** archive: canPartnerSignoff (UI) + server archive-partner-only + partnerTierRefusal; rollforward requireWrite + engagement partner required

**Sub-flows on this screen.** # archive-confirm, # roll-forward

**Navigation.** fix links to tasks/tools

**Components / i18n.** ArchiveChecklist · titleEn/titleFr from lib + inline

**Odoo 19 target.** Models: ea.audit.gate (computed), ea.audit.engagement. View: form section (OWL or QWeb). Groups: view all; archive group_partner.

reuse gate engine; items with links

**Effort / phase.** M (3 pd) · 5 Reports/portal/legal. Source: `components/ArchiveChecklist.tsx → lib/archive-checklist.ts; archiveAction / rollforwardAction`; rules in lib/archive-checklist.ts, lib/completion.ts. Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.9 `/engagements/[id]/sections/[itemId] # assign-task` — Assign task to a team member

**What it is.** Header select of team members (EQR excluded) with OK; sets the direct assignee and notifies them.

**Rules enforced (plain words).**

- eqr-not-assignable (ISQM 2 ¶18-20, UAT B73)
- not-found when not on team
- assignTasks (forms tool) also enforces F002 minimum per role (preparer/approver) and preparer-equals-approver when policy requireDistinctPreparerApprover

**Data.** Reads: team_member, file_item. Writes: file_item.assignee_user_id, notification (task_assigned), activity_log (assigned/unassigned).

**Who may do what.** canReview(role) && !isEqr (UI); server assignTask: assignee must be a team member, never eqr_reviewer

**Navigation.** stays; revalidates /tasks

**Components / i18n.** inline form · inline FR/EN

**Odoo 19 target.** Models: ea.audit.file.item (assignee_id, owner_id/preparer, approver_id). View: many2one on form. Groups: ea_audit_core.group_senior+.

domain excluding EQR team members; constraint preparer != approver when policy set; min role check vs firm policy

**Effort / phase.** S (1 pd) · 2 Engagement file. Source: `app/actions/planning.ts assignTaskAction → lib/team.ts assignTask`; rules in lib/team.ts (assignTask, assignTasks), lib/signoff-policy.ts. Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.10 `/engagements/[id]/sections/[itemId] # attachments-drawer` — Task evidence attachments (upload, versions, templates, edit locally)

**What it is.** Right-rail evidence panel: list of live attachments with version history, documents filed on the task (accepted PBC, letters), add menu (upload file, from template, from an existing attachment), rename, delete (soft, restorable), restore deleted, download, and an edit-locally watcher using the File System Access API that re-uploads saved changes as new versions.

**Rules enforced (plain words).**

- Upload safety (lib/upload-safety.ts checkUpload): no-extension, executable-refused, extension-not-allowed, empty-file, content-mismatch (magic bytes / textual check), not-an-office-file (OOXML marker)
- 25 MB cap (file-too-large 413)
- Versioning by filename: re-upload creates next version, history downloadable (UAT B108); name-required / name-taken on rename; restore-window-expired; attachments never cross engagements (copyAttachment); templates: toc-scot, itgc-e11, sub-trade-receivables/payables/inventory/fixed-assets (default for E4.1-E4.4), je-testing, fs-checklist-ohada; default workpaper auto-attached on first open of E4.1-E4.4

**Data.** Reads: task_attachment, file_item, app_user, document (listItemDocuments). Writes: task_attachment (INSERT new version; name; deleted_at; restore), activity_log (Attachment uploaded/deleted/restored/renamed).

**Who may do what.** upload/rename: atLeast(role,'staff') (read_only/portal refused); delete/restore: atLeast(role,'manager'); download: atLeast(role,'read_only'); EQR refused on team work (assertNotEqrWriteOnItem); archived refused; UI readOnly with readOnlyReason archived/eqr/role

**Sub-flows on this screen.** # add-menu, # rename-inline, # delete/restore, # version-history, # edit-locally

**Navigation.** download /api/attachments/file/[id]; documents → /documents/[id]

**Components / i18n.** TaskAttachments (client) · inline FR/EN in component

**Odoo 19 target.** Models: ea.audit.attachment (ir.attachment extension) with version, deleted_at, file_item_id; ea.audit.wp.template. View: list inline (OWL) / many2many_binary. Groups: upload group_staff+; delete/restore group_manager+; group_eqr denied on team tasks.

Extend ir.attachment with version chain and soft delete; mimetype/magic validation in create(); size limit via config; template attachments as data; edit-locally watcher is browser-only (optional OWL feature)

**Effort / phase.** M (5 pd) · 3 Papers. Source: `components/TaskAttachments.tsx → /api/attachments/[fileItemId], /api/attachments/file/[attachmentId], /api/engagements/[id]/wp-templates/[key] → lib/attachments.ts, lib/upload-safety.ts, lib/wp-templates.ts`; rules in lib/attachments.ts, lib/upload-safety.ts, lib/wp-templates.ts, lib/eqr.ts, app/api/attachments/[fileItemId]/route.ts, app/api/attachments/file/[attachmentId]/route.ts. Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.11 `/engagements/[id]/sections/[itemId] # deficiency-grid (C5.11)` — ISA 265 deficiency evaluation grid (C5.11)

**What it is.** One card per c1 deficiency from the findings register: likelihood, magnitude, accounts/assertions, management awareness, A6-A7 indicators, related deficiencies aggregated, final grade written back to the finding, and the date/recipient of the written communication to TCWG.

**Rules enforced (plain words).**

- invalid-severity, invalid-severity-factor, invalid-date, recipient-required when communicated, related-finding-unknown
- archive gate deficiencies_communicated (uncommunicatedSignificantDeficienciesTx) requires significant deficiencies communicated

**Data.** Reads: finding (route c1), deficiency_evaluation, file_item, app_user. Writes: deficiency_evaluation, finding.severity.

**Who may do what.** requireWrite; readOnly follows viewOnly

**Navigation.** link /findings

**Components / i18n.** DeficiencyEvaluationPanel (server-rendered forms) · inline FR/EN

**Odoo 19 target.** Models: ea.audit.deficiency.evaluation, ea.audit.finding. View: one2many cards / list. Groups: ea_audit_core.group_staff+.

suggested grade computed; constraint communicated requires recipient; gate

**Effort / phase.** M (3 pd) · 5 Reports/portal/legal. Source: `components/DeficiencyEvaluationPanel.tsx → app/actions/deficiencies.ts → lib/deficiencies.ts`; rules in lib/deficiencies.ts, lib/completion.ts (archiveGates). Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.12 `/engagements/[id]/sections/[itemId] # design-procedures-board (S5.5)` — Design substantive procedures board (S5.5)

**What it is.** Per significant index and assertion: choose nature and timing of substantive procedures, extent, select from the procedure library, add other substantive procedures (OSP list); shows design gaps (key assertions with nothing selected). The design is materialised as the E4 program (generatePsp).

**Rules enforced (plain words).**

- invalid-field/invalid-index/invalid-selection/invalid-osp/invalid-value; nature-not-permitted when the assertion/account is significant (certain natures forbidden); timing-not-permitted vs CRA level (timingAllowed(craLevel)); design gaps surfaced on groups/e4
- E4 group shows only designed indexes

**Data.** Reads: form_response (dsp keys), file_item, program_step, cra view. Writes: form_response (dsp_* keys), later program_step via generatePsp.

**Who may do what.** POST /api/dsp: assertMutable; lib requireWrite

**Sub-flows on this screen.** # osp-add, # nature/timing/extent select

**Navigation.** links /tools/sampling, /tools/sap; E4 papers link back (Design S5.5)

**Components / i18n.** DesignProceduresBoard (client) · inline FR/EN

**Odoo 19 target.** Models: ea.audit.dsp.design (per index/assertion), ea.audit.osp. View: OWL grid. Groups: ea_audit_core.group_staff+.

selection constraints depending on CRA level and significance; procedure library as data

**Effort / phase.** L (6 pd) · 4 Tools. Source: `components/DesignProceduresBoard.tsx → /api/engagements/[id]/dsp → lib/design-procedures.ts`; rules in lib/design-procedures.ts, lib/design-procedures-model.ts, lib/psp.ts, lib/procedure-library.ts. Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.13 `/engagements/[id]/sections/[itemId] # itapps-board (S2.3 / S2.5)` — IT applications register & strategy per application

**What it is.** S2.3 editable register of IT applications (name, layers, strategy, ITGC note, remove); S2.5 reads the same record read-only to evaluate against it.

**Rules enforced (plain words).**

- invalid-key, invalid-strategy (IT_STRATEGIES)
- S2.3 sign-off refused while any application strategy undecided (itapp-strategy-missing, UAT run 2 B46); feeds CRA ITGC state

**Data.** Reads: form_response (itapps keys). Writes: form_response.

**Who may do what.** POST /api/itapps: assertMutable; lib requireWrite; readOnly on S2.5 or viewOnly

**Navigation.** within paper

**Components / i18n.** ItAppsBoard (client) · inline FR/EN

**Odoo 19 target.** Models: ea.audit.it.application. View: one2many editable list. Groups: ea_audit_core.group_staff+.

selection strategy; constraint on sign-off

**Effort / phase.** S (2 pd) · 4 Tools. Source: `components/ItAppsBoard.tsx → /api/engagements/[id]/itapps → lib/itgc.ts`; rules in lib/itgc.ts, lib/itgc-model.ts. Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.14 `/engagements/[id]/sections/[itemId] # mark-not-applicable` — Task N/A toggle (mark not applicable / reinstate)

**What it is.** Header control: a senior+ marks the task not applicable with a reason (shown truncated in the header) or reinstates it; N/A tasks count as complete and satisfy the archive gate.

**Rules enforced (plain words).**

- rationale-required (<= 500 chars)
- archived refused
- dashboard counts N/A as done
- archive gate tasks_addressed accepts N/A with reason

**Data.** Reads: file_item, team_member. Writes: file_item (na_reason, na_by, na_at), activity_log (marked_not_applicable / na_cleared).

**Who may do what.** canReview(role) && !actsAsEqr (eqr-read-only, UAT run 2 B18 / run 3 B03); assertMutable

**Navigation.** stays

**Components / i18n.** inline form · inline FR/EN

**Odoo 19 target.** Models: ea.audit.file.item. View: button + wizard (reason). Groups: ea_audit_core.group_senior+ (not group_eqr).

na_reason/na_by/na_date fields; tracked

**Effort / phase.** S (1 pd) · 3 Papers. Source: `app/actions/planning.ts markNotApplicableAction`; rules in app/actions/planning.ts, lib/eqr.ts, lib/mutability.ts. Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.15 `/engagements/[id]/sections/[itemId] # paper-wizard-steps` — Paper wizard (status → questionnaire pages → conclusion)

**What it is.** Paginated working paper: page 1 is a read-only status summary (conclusions and who signed, F039), then the questionnaire in screen-sized pages (fields, numbered procedures with result/N-A/reason, Yes/No items with explanation on No or N/A, auto fields from tools), then the conclusion statements with key findings last. Embed slot shows the task's board as first page (embedOnly for S1.2/S1.3/S2.1/S2.2). Compact toggle, go-to-conclusion, next/back.

**Rules enforced (plain words).**

- F040: every item/procedure can be N/A with reason
- N/A without reason is not an answer (keyAnswered); required keys = inputs/selects + p_ procs + q_ items + c_ conclusions; auto fields never saved; edition label (F045); save = all-or-conflict with held-back drafts

**Data.** Reads: paper values (form_response wp:<code>), autoValues, signoffs. Writes: form_response via savePaperAction (filterPaperWrite restricts keys to paperKeys(def)); hidden __baseVersion/__baseDigests.

**Who may do what.** readOnly prop = viewOnly (archived, read_only, EQR on team work, non-appointed EQR on C4.2); lockedKeys per EQR rules

**Navigation.** within page

**Components / i18n.** PaperWizard, AutoTextarea, PracticalTips · labelEn/labelFr in definitions; wizard chrome inline FR/EN

**Odoo 19 target.** Models: ea.audit.paper, ea.audit.paper.response. View: OWL wizard component inside form. Groups: as parent.

OWL component rendering definition JSON; needs pagination, N/A reason boxes, auto fields readonly, conflict display; definitions migrated from lib/papers/*.ts to data files (see papers-B.json)

**Effort / phase.** L (8 pd) · 3 Papers. Source: `components/PaperWizard.tsx (+ WorkingPaper.tsx legacy renderer)`; rules in lib/papers/types.ts, lib/working-papers.ts, lib/paper-drafts.ts. Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.16 `/engagements/[id]/sections/[itemId] # planning-ras (P7.2)` — Planning review & approval summary (P7.2)

**What it is.** Replaces the wizard on P7.2: Section A confirmations (fieldwork lead and manager), Section B (engagement partner), Section C (quality reviewer), Appendix 1 team competence rows, task-state checklist, and four signature roles (fieldwork, manager, partner, eqr) that can be signed or withdrawn; the partner signature is what the planning gate p72_partner_signed reads.

**Rules enforced (plain words).**

- invalid-key regex
- signing needs the summary ready (rasGaps → RasRuleError)
- withdrawing a signature needs nothing
- identity rule for EQR (ISQM 2 ¶19) not rank
- rasPartnerApprovedTx feeds the planning gate and refuses P7.2 R/partner chips until approved (ras-not-approved)

**Data.** Reads: form_response (ras keys), team_member, app_user. Writes: form_response (a*/b*/c*/ap_* keys, signatures).

**Who may do what.** answers: Section A requires senior+, Section B partner (SECTION_FLOOR), Section C only an actor with firm role eqr_reviewer who holds no other team role (assertQualityReviewer: eqr-must-be-the-quality-reviewer, eqr-cannot-be-on-the-team); signatures: requireRole(definition.min) senior/manager/partner/eqr_reviewer; UI allowed flags via atLeast

**Sub-flows on this screen.** # ras-sign / ras-unsign per role

**Navigation.** within paper

**Components / i18n.** PlanningRas (client) · inline FR/EN + SECTION titles

**Odoo 19 target.** Models: ea.audit.ras (answers + signatures). View: form with sections and signature buttons. Groups: A group_senior+, B group_partner, C group_eqr (identity), signatures per role.

custom model with per-section write rules; partner approval drives gate

**Effort / phase.** M (4 pd) · 3 Papers. Source: `components/PlanningRas.tsx → /api/engagements/[id]/planning-ras → lib/planning-ras.ts`; rules in lib/planning-ras.ts, app/api/engagements/[id]/planning-ras/route.ts. Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.17 `/engagements/[id]/sections/[itemId] # review-note-thread` — Task review notes (raise / respond / clear)

**What it is.** Left-rail panel listing the task's review notes with author, body, response and status; seniors+ raise a note, the preparer/assignee answers, the author or a manager+ (not the preparer) clears it with a response.

**Rules enforced (plain words).**

- Open notes block reviewer/partner sign-off (open-notes) and the review_notes_cleared gates (acceptance P1.%, planning P%/S%, archive, C4.3 c43_cleared)
- note-required / response-required
- archived file takes no notes
- notes raised on task (file_item_id) or document (document_id) are both counted

**Data.** Reads: review_note, file_item, document, engagement, client, app_user. Writes: review_note (INSERT status open; response; status cleared), notification (review_note to preparer/assignee; to author on response), activity_log (raised/answered/cleared).

**Who may do what.** canRaise = canReview(role) (UI); server: addTaskNote requireWrite + assertNoteReachable (engagement visible to user, UAT run 3 B01); respondToTaskNote requireWrite; clearTaskNote author, or atLeast(role,'manager') and not the preparer (requires-manager-or-author, not-preparer-clears)

**Navigation.** within page; /tools/review-notes register (other agent)

**Components / i18n.** ReviewNotes (client) · inline FR/EN in component

**Odoo 19 target.** Models: ea.audit.review.note. View: list/kanban inline (OWL) or mail.activity. Groups: raise group_senior+; respond group_staff+; clear author or group_manager+.

Model with state open/answered/cleared, author, assignee, response; constraint in signoff create; gate counts; could reuse mail.activity but custom permissions needed

**Effort / phase.** M (3 pd) · 3 Papers. Source: `components/ReviewNotes.tsx → /api/engagements/[id]/task-notes{,/respond,/clear} → lib/task-notes.ts`; rules in lib/task-notes.ts, lib/documents.ts (addReviewNote, clearReviewNote), lib/gates.ts, lib/completion.ts. Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.18 `/engagements/[id]/sections/[itemId] # scot-studio (S1.1 register, S1.2 WCGW builder, S1.3 walkthroughs, S2.1 select, S2.2 design, E1.2 TOC board, S1.4 FSCP)` — SCOT Studio boards embedded in strategy/execution papers

**What it is.** S1.1: create/update/delete/assign SCOTs, link lead indexes with assertions, strategy controls/substantive. S1.2: flows, WCGWs (assertion required) and controls (type, frequency, owner, linked WCGWs). S1.3: walkthrough answers per SCOT (14 keys). S2.1: select controls for testing. S2.2: design tests (sample sizes, MUS preview, sampling link). E1.2: tests of controls grid by SCOT with sample draws and operating conclusions. S1.4: FSCP close-process form.

**Rules enforced (plain words).**

- name-required, duplicate-name; invalid-index
- WCGW needs >= 1 assertion (assertion-required, UAT B134); control selected for testing must link a WCGW (control-without-wcgw, UAT B46); operating 'effective' needs a planned sample fully tested (toc-no-sample, toc-incomplete, UAT run 2 B15, ISA 330)
- TOC sample draw: population >= 1, size >= 1, redraw needs reason >= 3 chars and manager+ after testing (redraw-after-testing-manager-only); embeddedWorkGap gates sign-off of S1.2/S1.3/S2.1/S2.2 (WALKTHROUGH_KEYS answered per SCOT etc.)
- CRA 'rely' support derived from selected controls

**Data.** Reads: scot, scot_index, scot_control, wcgw, wcgw_control, control_test, toc_sample_draw, cra_assessment, risk, risk_lead_index, form_response, sub_ledger_*, team_member, app_user. Writes: scot, scot_index, scot_control, wcgw, wcgw_control, toc_sample_draw, form_response (walkthrough, fscp, toc), cra_assessment/history (write-back), notification.

**Who may do what.** POST /api/scots: assertMutable (423 archived) + lib requireWrite/requireEngagementAccess; redraw after testing manager-only (team rank)

**Sub-flows on this screen.** # scot-add/edit/assign, # wcgw-add, # control-add/edit/select, # sample-draw, # walkthrough-form, # toc-eval

**Navigation.** within paper; links to /tools/sampling; E1.2 export

**Components / i18n.** ScotRegister, WcgwBuilder, WalkthroughBoard, TocBoard, FscpForm (all client) · inline FR/EN in components

**Odoo 19 target.** Models: ea.audit.scot, ea.audit.scot.index, ea.audit.wcgw, ea.audit.control, ea.audit.control.test, ea.audit.toc.sample. View: OWL boards embedded in form (or one2many editable lists). Groups: ea_audit_core.group_staff+; redraw after testing group_manager+.

ea_audit_tools models with constraints above; walkthrough answers as JSON or key/value; sample draws with seeded RNG; operating conclusion computed from control tests

**Effort / phase.** XL (12 pd) · 4 Tools. Source: `components/ScotRegister.tsx, WcgwBuilder.tsx, WalkthroughBoard.tsx, TocBoard.tsx, FscpForm.tsx → /api/engagements/[id]/scots → lib/scots.ts`; rules in lib/scots.ts, lib/toc-grid.ts, lib/toc-sampling.ts, lib/documents.ts (embeddedWorkGap, WALKTHROUGH_KEYS), app/api/engagements/[id]/scots/route.ts. Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.19 `/engagements/[id]/sections/[itemId] # section-conclusion-and-review (E4)` — Account conclusion (prepare + review)

**What it is.** E4 account paper footer: write the conclusion, tick objectives achieved, give a rationale when no procedure was retained; a reviewer confirms the conclusion before the paper's R can be signed.

**Rules enforced (plain words).**

- conclusion-required
- steps-open (planned steps remain)
- no-procedures-rationale-required (UAT B45)
- self-review F001
- not-on-team-to-sign / accept-engagement-first
- voided paper review clears the conclusion review (invalidateStaleSignoffs)
- completion gate sections_concluded

**Data.** Reads: section_conclusion, program_step, file_item, team_member, firm policy. Writes: section_conclusion (conclusion, objectives_achieved, no_procedures_rationale, prepared_by; reviewed_by/partner_reviewed_by + timestamps).

**Who may do what.** save: requireWrite; review: canReview (or canPartnerSignoff when asPartner) + accepted team member + F002 minReviewer (belowMinimumCode) + partner tier when asPartner; self-review refused

**Navigation.** stays

**Components / i18n.** inline forms · t.planning.execution

**Odoo 19 target.** Models: ea.audit.section.conclusion. View: form section + buttons. Groups: save group_staff+; review group_senior+/partner.

one2one per E file item; review buttons with constraint chain; cleared when related reviewer signoff voided

**Effort / phase.** S (2 pd) · 3 Papers. Source: `app/actions/execution.ts saveConclusionAction / reviewConclusionAction → lib/execution.ts saveSectionConclusion / reviewSectionConclusion`; rules in lib/execution.ts. Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.20 `/engagements/[id]/sections/[itemId] # significant-accounts-grid (P6.2)` — Significant accounts & relevant assertions grid (P6.2)

**What it is.** Grid computed from the working TB against the approved materiality's tolerable error: per lead index closing, volume, status (significant/not), relevant assertions, SCOT coverage, risk link, specific TE and justification; autosaves permissively, sign-off demands justifications.

**Rules enforced (plain words).**

- Tool-fed: needs TB + approved materiality
- specific threshold must be below overall materiality (specific-above-materiality) and below TE (specific-above-te, UAT B43)
- invalid-index
- sign-off refused while unjustified departures exist (significance-unjustified, UAT B44)
- risk-derived assertions from the Risk Console

**Data.** Reads: trial_balance*, materiality, form_response, scot, scot_index, sub_ledger_*, client_lead_index_override, risk. Writes: form_response (significance overrides, assertions, specific TE, justification).

**Who may do what.** POST /api/significance: lib requireWrite

**Navigation.** within paper; tool chip /tools/materiality

**Components / i18n.** SignificantAccounts (client), Fold · inline FR/EN

**Odoo 19 target.** Models: ea.audit.significance (per engagement/index). View: OWL grid / editable list. Groups: ea_audit_core.group_staff+.

computed defaults from TB vs TE with stored overrides; constraints on specific TE

**Effort / phase.** M (4 pd) · 4 Tools. Source: `components/SignificantAccounts.tsx → /api/engagements/[id]/significance → lib/significant-accounts.ts`; rules in lib/significant-accounts.ts, lib/tool-fed-papers.ts. Screenshot: extra\e25-archive-checklist-C6.1.png, extra\e34-paper-C1.1-sad.png, extra\e35-paper-C4.1-review-summary.png, extra\e37-section-S3.1-cra.png, extra\e38-section-P6.2-significant-accounts.png, extra\e39-section-E3.1-je.png, extra\e40-section-E4.1-lead.png, extra\e41-section-P7.2-ras.png, extra\e42-section-S1.2-wcgw.png, extra\e43-section-C5.5-alerte.png, extra\e36-section-P1.1.png, extra\e29-section-P6.1-tool-fed.png, extra\e27-section-C5.1-report.png, extra\e31-section-C4.2-eqr.png, extra\e26-section-C6.2-archive.png

#### C.6.21 `/engagements/[id]/tasks` — My Tasks (engagement work queue)

**What it is.** Dense engagement-wide task list with filter chips (All, For my review, To-dos, Assigned to me, Unassigned, Hide completed), review-note badges, assignee/preparer initials, due date and status dot; every row opens the canonical working-paper screen.

**Rules enforced (plain words).**

- isMine = assignee OR owner (preparer) OR approver (same definition as the dashboard tile, UAT B94)
- isUnassigned = no owner and no assignee, not reviewed, not N/A (UAT run2-B143)
- status per taskStatus
- open review-note counts per task (notes on task or document, UAT run 2 B71)

**Data.** Reads: file_item, document, signoff, program_step, task_attachment, section_conclusion, form_response, review_note, team_member, app_user, engagement. Writes: —.

**Who may do what.** auth() + layout F008; read-only list

**Navigation.** in: AppNav/dashboard; out: /engagements/[id]/sections/[itemId], /dashboard

**Components / i18n.** AppNav, NavLink, Panel · page-local LABELS EN/FR (not in messages/*.json), t.dashboard; MONTHS inline

**Odoo 19 target.** Models: ea.audit.file.item. View: list with filters/search panel. Groups: all team groups.

Standard list view with predefined filters (my tasks domain uses assignee/owner/approver), computed open_note_count and status; move LABELS into i18n

**Effort / phase.** S (2 pd) · 2 Engagement file. Source: `app/engagements/[id]/tasks/page.tsx`; rules in lib/engagement-dashboard.ts (engagementTasks, taskStatus), lib/task-groups.ts. Screenshot: extra\e03-tasks.png, extra\e03b-tasks-full.png; other agent: 04-phase-tasks.png

### C.7 Tools

#### C.7.1 `/engagements/[id]/tools` — Tools hub

**What it is.** Landing of the engagement tools: 14 tiles (Data Analytics, GL Correlation Console, Lead Schedule, Review Notes, Forms, Materiality, Risk Register, Combined Risk Assessment, SAD, Substantive Analytics, Sampling, Journal-Entry Selection, Sample Working Papers, PBC Requests), each with the task codes it feeds (e.g. Materiality → P6.1; SAD → C1.1, C3.1; Sampling → E4.1/E4.2/E4.4). Back link to dashboard; four phase chips (SECTION_ORDER) link to /phase/<key>.

**Rules enforced (plain words).**

- TILE_FEEDS: static TILES array maps each tool to the task codes it feeds (data-analytics→P6.1,P6.2,E3.1; gl-console→P6.2,E3.1; lead-schedule→S4.1,C2.1; review-notes→C4.1,C4.3; forms→P1.1,C4.1; materiality→P6.1; risk→S3.1; cra→S3.1,E6.8; sad→C1.1,C3.1; sap→S5.5,E4.1,E4.20; sampling→E4.1,E4.2,E4.4; je-selection→E3.1; sample-papers→E1.1,E1.2,E3.1; pbc→P2.2,E1.1)
- ONE_HIERARCHY: each tool's back arrow returns to the hub, hub back goes to dashboard (no tabs)

**Data.** Reads: engagement, client (getEngagement); file_item (+document, signoff via engagementTasks) for tile 'feeds' tooltips. Writes: —.

**Who may do what.** auth() session else redirect('/login'); getEngagement() → requireTenant() (client_user refused 'portal-account'); engagement-team visibility (F008, visibleToUser: team_member.status='accepted') enforced by proxy.ts + app/engagements/[id]/layout.tsx. Any firm role incl. read_only/eqr_reviewer may view.

**Navigation.** From dashboard (/engagements/[id]/dashboard). To each tool route, /engagements/[id]/risks, /cra, /pbc, /phase/<acceptance|strategy|execution|conclusion>.

**Components / i18n.** AppNav, Chip (ui/atlas), Link · Inline EN/FR literals in TILES (nameEn/nameFr/descEn/descFr); page title via localizedTitle('Tools','Outils'); sectionLabel from lib/task-groups SECTION_LABELS. messages/en.json & fr.json have full key parity (1373 keys each).

**Odoo 19 target.** Models: ea.audit.engagement (menu only). View: kanban (menu/tile board) or OWL dashboard. Groups: ea_audit_core.group_staff and above (read); group_eqr, group_read_only read.

Implement as an engagement form 'Tools' smart-button page or a client action (OWL tile board) listing tool actions with task-code badges; record rule: user must be accepted member of engagement team (ea.audit.team.member state=accepted).

**Effort / phase.** S (1 pd) · 4 Tools. Source: `app/engagements/[id]/tools/page.tsx`; rules in app/engagements/[id]/tools/page.tsx; lib/task-groups.ts; lib/engagement-dashboard.ts; lib/engagement-access.ts; proxy.ts. Screenshot: extra\t01-tools-hub.png; other agent: 08-tools.png

#### C.7.2 `/engagements/[id]/tools/data-analytics` — Data Analytics (analyzer list)

**What it is.** Section landing listing the seven analyzers with the tasks they feed: Trial Balance Analyzer (/data; P6.1,P6.2,S4.1), General Ledger Analyzer (/analyzers/journal_entries; E3.1,S1.4), AR (/analyzers/ar_open_items; E4.1), AP (/analyzers/ap_open_items; E4.2), Inventory (/analyzers/inventory_listing; E4.3), Financial Analysis (/tools/financial-analysis; P3.2,S4.2), Analytical Procedures (/analytics; P3.2,C2.1).

**Rules enforced (plain words).**

- Static ANALYZERS catalogue
- no computation

**Data.** Reads: engagement, client; file_item (engagementTasks) for feed tooltips. Writes: —.

**Who may do what.** auth() + getEngagement (requireTenant); team visibility via proxy/layout (F008). All roles read.

**Navigation.** Back → /tools. Links to /data, /analyzers/<kind>, /tools/financial-analysis, /analytics.

**Components / i18n.** AppNav, Panel (ui/atlas) · Inline EN/FR in ANALYZERS; localizedTitle('Data Analytics','Analyse de données')

**Odoo 19 target.** Models: —. View: kanban / menu. Groups: group_staff+, group_eqr, group_read_only.

Sub-menu of Tools; can be a plain menu with 7 actions.

**Effort / phase.** S (0.5 pd) · 4 Tools. Source: `app/engagements/[id]/tools/data-analytics/page.tsx`; rules in app/engagements/[id]/tools/data-analytics/page.tsx. Screenshot: extra\t02-tb-analyzer.png

#### C.7.3 `/engagements/[id]/tools/financial-analysis` — Financial Analysis (ratio battery)

**What it is.** 20 ratios in 5 groups (Liquidity, Activity, Profitability, Leverage, Investment), Current Y vs Prior Y, variance and %, with auto-saved commentary per ratio and a units switch (FCFA / '000 / millions). Basis: pre-audit TB closing vs prior-year TB closing (or TB opening). DSO/DPO need the GL.

**Rules enforced (plain words).**

- AGGREGATE_BUCKETS (SYSCOHADA prefixes, debit-positive, credit-natured negated; client_lead_index_override re-homes an account: F→inventory, C→cash, E→receivables, N→payables, VA*→COGS): inventory=class 3; cash=class 5 excl. 59; receivables=41; payables=credit 40; revenue=−class7; expenses=class6; cogs=60; financeCosts=67; depreciation=68+69; equity=−(10..15) + PBT when no non-zero 13x account (pre-closing TB); financialDebt=−(16..18); currentAssets=inventory+class4 debit+max(cash,0); currentLiabilities=class4 credit+max(−cash,0); totalAssets=class2+inventory+class4 debit+max(cash,0); pbt=revenue−expenses; ebitda=pbt+financeCosts+depreciation
- RATIOS: current=CA/CL; quick=(CA−inventory)/CL; cash=max(cash,0)/CL; wc=CA−CL; inv_turn=cogs/inventory; rec_turn=revenue/receivables; pay_turn=cogs/payables; asset_turn=revenue/totalAssets; gross%=(revenue−cogs)/revenue; ebitda%=ebitda/revenue; net%=pbt/revenue; gearing%=debt/(debt+equity); dte=debt/equity; equity_ratio%=equity/totalAssets; int_cover=(pbt+financeCosts)/financeCosts; roa%=pbt/totalAssets; roe%=pbt/equity; roce%=(pbt+financeCosts)/(equity+debt)
- P&L ratios null when revenue=0 and expenses=0; division by 0 → null; rounded 2 dp
- DSO_DPO: last 3 months before period end from GL — sales = |amount| accounts 70*, purchases = accounts 6[0-2]*
- DSO=round(receivables/sales3m×90), DPO=round(payables/purchases3m×90); prior DSO/DPO always null; note 'Requires the General Ledger' when no GL in window
- PRIOR_SOURCE: prior-year TB closing beats working TB opening (classes 6/7 reset at year start under SYSCOHADA)
- COMMENT_KEYS: index 'FA' accepts only RATIO_KEYS else 'invalid-key' (UAT B31)

**Data.** Reads: engagement; client_lead_index_override; trial_balance + trial_balance_version (current_version_no) + trial_balance_row; trial_balance_version timing='prior_year' AND superseded_at IS NULL; sub_ledger_dataset kind='journal_entries' (pre_audit first) + sub_ledger_row (last 3 months); form_response code LIKE 'ap:%' (comments). Writes: form_response code='ap:FA', field_key ∈ RATIO_KEYS (POST /api/engagements/[id]/ap-comments; empty value deletes the row).

**Who may do what.** Page: auth() + getEngagement; commentary save via /api/engagements/[id]/ap-comments → saveApComments → requireWrite() (read_only & client_user refused 'read-only-role'); team visibility via proxy (F008).

**Sub-flows on this screen.** # commentary autosave; # units switch (client-only)

**Navigation.** Back → /tools/data-analytics. Empty state when no TB ingested points to Trial Balance Analyzer.

**Components / i18n.** FinAnalysisGrid (client; ui/grid GRID_* classes; fixed column geometry 200/88/88/88/62px; useAutoSave debounce → ap-comments), AppNav · Inline EN/FR + DEFS labels (label/labelFr); localizedTitle('Financial Analysis','Analyse financière')

**Odoo 19 target.** Models: ea.audit.financial.ratio (computed, transient or stored per TB version), ea.audit.ap.comment (index='FA', key). View: OWL spreadsheet-like grid (or list with grouped rows) + comment column. Groups: read: group_staff+, group_eqr, group_read_only; write comment: group_staff+ (not read_only/eqr).

Computed fields over trial_balance_row of current version; prefix rules as Python constants; needs OWL grid with inline-editable commentary; units toggle client-side; GL 3-month window needs dataset mapping (account, amount or debit/credit, journalDate).

**Effort / phase.** M (4 pd) · 4 Tools. Source: `app/engagements/[id]/tools/financial-analysis/page.tsx`; rules in lib/financial-analysis.ts; lib/analytical-procedures.ts (saveApComments); components/FinAnalysisGrid.tsx; app/api/engagements/[id]/ap-comments/route.ts. Screenshot: extra\t04-financial-analysis.png, extra\d11-financial-analysis-with-data.png

#### C.7.4 `/engagements/[id]/tools/forms` — Forms matrix (assignment of preparer / approver)

**What it is.** Every standard form of the file index (DEFAULT_FILE_INDEX) grouped by the four phases, each linking to its task page; for reviewers+ a per-phase 'Assign phase' (preparer or approver) and per-form P/A selects. Rows where preparer==approver are shown in red (F006). Triggered conditional tasks (P4.2, P4.3, S5.1-S5.3) included (UAT B69).

**Rules enforced (plain words).**

- ASSIGN_TARGET_ON_TEAM: assignee must have a team_member row else 'not-found'
- EQR_NOT_ASSIGNABLE: team_role 'eqr_reviewer' refused (ISQM 2 ¶18-20, UAT B73)
- MIN_RANK (assertAssignmentRulesTx): effectiveTaskRule(policy, task rules, code) gives minPreparer/minReviewer on TEAM_LADDER [staff, senior, manager, senior_manager, director, partner]; teamRank(teamRole) < teamRank(minimum) → 'role-below-task-minimum-<rank>'
- DISTINCT_P_A: when signoff policy requireDistinctPreparerApprover, approver cannot equal owner_id/assignee_user_id and preparer cannot equal approver_user_id → 'preparer-equals-approver' (F006)
- CLIENT_FILTER: FormsAssignRow hides the person chosen on the other side unless already stored (conflict to correct)
- CONDITIONAL_TRIGGERS: P4.2 assess_control_env, P4.3 assess_it_env, S5.1 uses_expert, S5.2 uses_service_org, S5.3 has_internal_audit (S6.1 answers); forms not instantiated on this file shown greyed 'Not in this engagement's scope'; redirect ?assigned=<n> or ?error=<code>

**Data.** Reads: engagement; file_item (+document, signoff, form_response trigger for conditionals) via engagementTasksWithActiveConditionals; team_member + app_user (listTeam); DEFAULT_FILE_INDEX (code constant). Writes: file_item.owner_id (preparer) / approver_user_id (approver) / assignee_user_id via assignTasks (app/actions/planning.ts assignFormsTasksAction → lib/team.ts assignTasks); activity (tasks_assigned/unassigned); notification kind 'task_assigned' to assignee.

**Who may do what.** View: any authenticated team member. Assign: canAssign = canReview(session.user.role) i.e. atLeast(role,'senior') (senior, manager, eqr_reviewer, partner, firm_admin); server: assignFormsTasksAction re-checks canReview → 'forbidden'; assignTasks → requireWrite() + assertNotEqrWrite (EQR acting on team → 'eqr-read-only'); team list excludes teamRole 'eqr_reviewer'.

**Sub-flows on this screen.** # assign phase (role select preparer|approver + team select + OK); # assign P/A per form (FormsAssignRow)

**Navigation.** Back → /tools; each form → /engagements/[id]/sections/<itemId>; revalidates /tasks

**Components / i18n.** FormsAssignRow (client, two forms P/A per row), SubmitButton, Panel, AppNav · planning.errors (assignment-preparer-is-approver, eqr-not-assignable, role-below-task-minimum-*, preparer-equals-approver, not-found) via getMessages; shortTitle(code, locale) from lib/file-index; sectionLabel; inline EN/FR

**Odoo 19 target.** Models: ea.audit.file.item (owner_id/preparer, approver_id, assignee_id), ea.audit.team.member, ea.audit.signoff.policy, ea.audit.task.rule. View: list (editable, grouped by phase) + wizard for bulk phase assignment. Groups: view: group_staff+, group_eqr, group_read_only; assign: group_senior+ (not group_eqr for writes).

Python constraints on file.item write: assignee ∈ accepted team, not EQR, rank ≥ task minimum, preparer≠approver when policy flag; server action 'Assign phase' as wizard (role + user); notification via mail.thread message_post/activity; conditional tasks visibility computed from S6.1 answers.

**Effort / phase.** M (3 pd) · 4 Tools. Source: `app/engagements/[id]/tools/forms/page.tsx`; rules in app/engagements/[id]/tools/forms/page.tsx; app/actions/planning.ts; lib/team.ts (assignTasks, assertAssignmentRulesTx); lib/signoff-policy.ts; lib/eqr.ts; lib/engagement-dashboard.ts; lib/file-index.ts; lib/task-groups.ts; components/FormsAssignRow.tsx. Screenshot: extra\t11-forms-matrix.png, extra\t11b-forms-matrix-full.png

#### C.7.5 `/engagements/[id]/tools/gl-console` — GL Correlation Console

**What it is.** Interrogate an imported general ledger (dataset kind journal_entries) three ways over the typed gl_line projection: entry analysis (what else moves with selected accounts, by month or weekday), two-account correlation (monthly totals, ratio, Pearson r), and the 30-analytic catalogue; every figure drills to the underlying lines (capped, paginated). Arrives pre-filtered from a lead-schedule figure (?accounts=…&opening=…&closing=…) and reconciles the drill to it (UAT run 2 B68).

**Rules enforced (plain words).**

- AMOUNT_CONVENTION: signed = debit − credit, debits positive, credits negative, never reversed downstream
- TOLERANCE=0.005 for debit/credit reconciliation
- POPULATION_CHECKS (validatePopulation, status passed/warning/failed): required mapping (account, jeNumber, amount or debit+credit) failed if missing; no empty account (failed); no empty JE number (failed)
- JE number not journal-code-like (failed); unreadable dates: 0 passed, <1% of lines warning, else failed; zero-amount lines warning; ΣDr−ΣCr within TOLERANCE else failed; unbalanced entries (|Σsigned| per je_number > TOLERANCE) failed; dates-in-period [period_end−1y+1d, period_end] warning; exact duplicate lines (account, je, date, reference, signed, description) warning; completeness vs source rows warning
- ENTRY_ANALYSIS: ≤25 selected accounts, mode any|all, rank abs|net|postings|entries|account, limit 10|20|50|all (ALL_CAP 200), period month|weekday, selected accounts excluded from counterparts
- CORRELATION: restricted to entries containing both accounts; ratio aTotal/bTotal (sign kept, null when 0, 4 dp)
- Pearson r on signed and on absolute monthly totals (null when flat)
- DRILL: DRILL_CAP 500, page 100, filters accounts(≤50)/entryAccounts(≤25)/month/weekday/jeNumber/preparer/reviewer/approver/minAbs/maxAbs/dateFrom/dateTo/journalCode/weekendOnly/missingReference
- ACCOUNT_RE /^[A-Za-z0-9._-]{1,40}$/
- URL accounts /^\d{1,12}$/ max 50
- CATALOGUE_30 (per month aggregates; unavailable when required field unmapped
- 25 out-of-hours 'no posting timestamp', 26 sequence-gaps and 28 post-period 'declared but not computed', 27 manual-vs-automated 'no entry-source indicator'): 1 ledger-reconciliation, 2 unbalanced-entries, 3 exact-duplicates, 4 near-duplicates, 5 zero-value, 6 invalid-debit-credit (both sides/negative/neither), 7 weekend-postings (isodow 6-7), 8 entry-date-lag (entry_date − journal_date buckets same day/1/2-3/>3/negative), 9 year-end-concentration (yearEndDays default 15, 1-90), 10 monthly-spikes (value > mean + sdFactor×sd, default 2), 11 top-value (percentile default 0.99), 12 round-numbers (roundMin 100000 and multiple of roundStep 100000), 13 benford (first-digit expected log10(1+1/d)·100: 30.1,17.6,12.5,9.7,7.9,6.7,5.8,5.1,4.6 %
- MAD > 1.5 points = risk indicator; nil amounts excluded), 14 repeated-amounts (minOccurrences default 10), 15 rare-accounts (rareMax default 3 postings/year), 16 normal-side-exceptions (debit-side account credited / credit-side debited), 17 unusual-account-combinations (pairMax default 3 entries), 18 missing-mandatory-fields, 19 missing-references, 20 third-party-attribution (prefixes default 40,41), 21 preparer-volume / 22 preparer-value / 23 reviewer-workload (topN default 10), 24 self-review (preparer==reviewer), 29 debit-credit-correlation (Pearson monthly), 30 account-frequency-value (informational)
- WORDING_RULE: outputs are 'exceptions / risk indicators requiring audit consideration', never fraud/error/misstatement

**Data.** Reads: sub_ledger_dataset (listDatasets, kind='journal_entries'); gl_line (all aggregates); sub_ledger_row (build only); engagement period_end. Writes: gl_line (op 'build' → buildProjection: typed projection of sub_ledger_row, batches of 2000; signed = debit − credit; rejects rows with empty account or JE number).

**Who may do what.** Page: auth() + getEngagement. API /api/engagements/[id]/gl-analytics: auth() (401), team visibility via proxy; only op 'build' calls assertMutable (archived → 423 'archived'); all read ops stay available on archived files. No role gate beyond write-through requireTenant.

**Sub-flows on this screen.** # build projection + validate population; # pick accounts (GlAccountPicker); # entry analysis grid; # two-account correlation (swap); # analytics catalogue → run analytic with params; # drill-down overlay (filter, paginate 100, reconcile to lead-schedule figure)

**Navigation.** Back → /tools; link to /analyzers/journal_entries (import ledger); arrives from Lead Schedule account/total drill links; JE Selection links here

**Components / i18n.** GlConsole (client, 1723 lines: tabs entry|correlate|analytics, dataset select, build/validate panel, drill overlay panel with line filter), GlAccountPicker (MAX_SELECTED 25, search), ui/excel.tsx Sheet primitives (column letters, #DAE9F8 header, #E7E6E6 calc cells, negatives in parentheses), AppNav · Inline EN/FR via T(); analytic titles/objectives/exceptions bilingual in lib/gl-analytics ANALYTICS; localizedTitle

**Odoo 19 target.** Models: ea.audit.gl.line (projection, indexed), ea.audit.subledger.dataset, ea.audit.gl.analytic (catalogue definition, data), ea.audit.gl.analytic.run (optional cache). View: OWL client action (three tabs + drill dialog); pivot/graph for monthly grids. Groups: read: group_staff+, group_eqr, group_read_only; build: group_staff+ (not read_only/eqr).

Heavy SQL aggregates → implement as model methods with raw SQL over ea_audit_gl_line (indexes on dataset_id, je_number, account, journal_date); OWL component for console with drill dialog; constants table for the 30 analytics; Benford/Pearson pure Python; archived check only on build.

**Effort / phase.** XL (15 pd) · 4 Tools. Source: `app/engagements/[id]/tools/gl-console/page.tsx`; rules in app/engagements/[id]/tools/gl-console/page.tsx; components/GlConsole.tsx; components/GlAccountPicker.tsx; components/ui/excel.tsx; lib/gl-analytics.ts; lib/gl-correlation.ts; lib/gl-line.ts; app/api/engagements/[id]/gl-analytics/route.ts; lib/subledgers.ts. Screenshot: extra\t03-gl-console.png, extra\d09-gl-console-with-data.png

#### C.7.6 `/engagements/[id]/tools/gl-console # build projection & validate` — GL Console — Build projection / population checks

**What it is.** Select a journal_entries dataset, build the gl_line projection (once; reused afterwards), then show the population validation checks (passed/warning/failed) and head stats (lines, entries, accounts, debit, credit, difference).

**Rules enforced (plain words).**

- See parent POPULATION_CHECKS
- mapping debit+credit pair OR single signed amount column
- dates parsed ISO/dd-mm-yyyy/Excel serial (epoch 1899-12-30)
- rows with empty account or JE number rejected (counted)

**Data.** Reads: sub_ledger_dataset.mapping, sub_ledger_row; gl_line. Writes: gl_line (INSERT in batches of 2000; BuildResult lines/rejected/reused).

**Who may do what.** op build: assertMutable (archived → 423); any writer; op validate read-only

**Sub-flows on this screen.** collapsible validation panel

**Navigation.** inside console

**Components / i18n.** GlConsole (gl-build, gl-validation-toggle), SheetTable · check labels bilingual (labelEn/labelFr, detailEn/detailFr)

**Odoo 19 target.** Models: ea.audit.gl.line, ea.audit.gl.population.check (transient). View: server action + OWL panel. Groups: group_staff+.

Projection build as queued job (queue_job) for large ledgers; store validation result JSON on dataset.

**Effort / phase.** M (4 pd) · 4 Tools. Source: `components/GlConsole.tsx; platform/lib/gl-line.ts`; rules in lib/gl-line.ts (buildProjection, validatePopulation); app/api/engagements/[id]/gl-analytics/route.ts. Screenshot: extra\t03-gl-console.png, extra\d09-gl-console-with-data.png

#### C.7.7 `/engagements/[id]/tools/gl-console # drill-down` — GL Console — Drill-down overlay

**What it is.** Overlay panel listing the ledger lines behind any clicked figure (grouped by entry optionally), with a line filter (accounts, dates, min/max abs, journal) and prev/next paging; when opened from a lead-schedule figure shows opening/closing and whether the drilled lines reconcile.

**Rules enforced (plain words).**

- DRILL_CAP 500
- PAGE 100; filter whitelist (see parent)
- RECONCILE: opening + Σsigned(drilled lines) vs closing of the lead-schedule figure (UAT run 2 B68)

**Data.** Reads: gl_line. Writes: —.

**Who may do what.** read-only op 'drill' (no archive guard)

**Sub-flows on this screen.** overlay dialog

**Navigation.** opened from cells of entry grid / correlation / analytic rows / lead-schedule link

**Components / i18n.** GlConsole (gl-drill-overlay/panel, gl-line-filter), SheetTable · inline EN/FR

**Odoo 19 target.** Models: ea.audit.gl.line. View: OWL dialog with list. Groups: read: all team roles.

Could reuse list view with domain + context; cap 500.

**Effort / phase.** S (2 pd) · 4 Tools. Source: `components/GlConsole.tsx; platform/lib/gl-correlation.ts (drillDown)`; rules in lib/gl-correlation.ts; components/GlConsole.tsx. Screenshot: extra\t03-gl-console.png, extra\d09-gl-console-with-data.png

#### C.7.8 `/engagements/[id]/tools/je-selection` — Journal-Entry Selection studio (ISA 240 ¶32)

**What it is.** Risk-directed selection of journal-entry LINE items to test over one journal_entries dataset: tick built-in criteria (with editable thresholds), add auditor rules (field/operator/value, any|all), run (paginated), record the run as the S5.4 selection design, export the E3.1 workbook. Each selected line carries every reason it was picked (a line caught by 4 criteria appears once with 4 reasons).

**Rules enforced (plain words).**

- NOT_RANDOM: International Audit Methodology 321.03 / ISA 240 — no random 25; every line has stated criterion
- CRITERIA (JE_CRITERIA): weekend-posting (isodow 6/7 on dateBasis journal|entry); no-description (both je_description and line_description empty); public-holiday (country ISO2 default CM; seeded calendar + firm_holiday; empty calendar → note 'selected nothing because calendar is empty'); round-amount (|signed| ≥ roundMin default 100000 AND |signed| mod roundStep default 100000 = 0; same as analytic 12); unusual-pairing (entry-level: entry touches both sides of a pairing
- 6 pairings revenue-cash, expense-cash, revenue-expense, fixed-assets-revenue, fixed-assets-cash, inventory-cash; classes derived from lead-classes prefix map via CLASS_PREFIXES up to 3 digits, e.g. 28 fixed assets but 281 amortisation masked); year-end-volume (entry-level: top topEntries default 5 (1-100) entries dated within yearEndDays default 15 (1-90) before period_end, by lines or gross value); incomplete-description (< minDescriptionChars default 10 (1-200) OR < minDescriptionWords default 2 (1-20) OR only filler terms list divers, misc, od, ajustement, régularisation, correction, écriture, journal, reclass, provision, test, na, rien, autre, other, tbd… accented+unaccented, max 200 terms); preparer-is-reviewer (trimmed lower-cased names equal); preparer-is-approver (UAT B141); user-defined rules (≤20) over RULE_FIELDS (account, accountName, jeNumber, journalCode, jeDescription, lineDescription, reference, thirdPartyCode, thirdPartyName, preparer, reviewer, approver, costCenter, journalDate, entryDate, debit, credit, signed, absAmount, lineNo) with operators text: equals/notEquals/contains/notContains/startsWith/endsWith/isEmpty/isNotEmpty; number: equals/notEquals/greaterThan/greaterOrEqual/lessThan/lessOrEqual/between; date: equals/before/after/between/isEmpty/isNotEmpty; userRulesMode any|all (UAT run 2 B67)
- LIMITS: DEFAULT_SELECTION_LIMIT 200, SELECTION_CAP 500 per page, CANDIDATE_CEILING 20000 flagged lines → note 'counts are floors'
- OUT_OF_HOURS not offered (no timestamp in import)
- SETTINGS clamped server-side (resolveSettings) never taken raw
- ERRORS 400: no-criteria, invalid-rule-field, invalid-rule-operator, invalid-rule-value
- 503 selection-timeout (PG 57014)
- RECORD_DESIGN explicit only (UAT run 2 B16), keeps dated history, voids S5.4 sign-offs
- EXPORT: re-runs selection at export (nothing persisted), POST carries studio body with limit=SELECTION_CAP
- GET exports all built-in criteria at defaults

**Data.** Reads: sub_ledger_dataset (journal_entries); gl_line (SQL narrowing, SCOPE dataset_id+engagement_id); public_holiday (seeded national calendar) + firm_holiday; engagement period_end; form_response code 'wp:S5.4' (je_design, je_design_history). Writes: form_response code='wp:S5.4' field je_design (JSON: datasetId, criteria, params, userRules, userRulesMode, selectedLines, populationLines, recordedBy, recordedAt) and je_design_history (append prior); signoff voided on S5.4 (invalidateStaleSignoffs) + reportInvalidatedSignoffs; firm_holiday (add/remove via other screens); activity 'export' log (logExport e3.1-journal-entries).

**Who may do what.** Page: auth() + getEngagement. API POST /api/engagements/[id]/je-selection: requireEngagementAccess (accepted team) → 403; run writes nothing (allowed on archived); recordDesign → assertMutable (423 'archived') + requireWrite (read_only refused) + 'je-design-empty' when 0 lines. Export /je/export: requireEngagementAccess.

**Sub-flows on this screen.** # configure criteria & thresholds; # rule builder (add rule, mode any/all); # run selection (paginated results); # record as S5.4 design; # export E3.1 workbook (POST /je/export)

**Navigation.** Back → /tools; links to /analyzers/journal_entries (import) and /tools/gl-console; design recorded appears on S5.4 paper

**Components / i18n.** JeSelectionStudio (client, 1032 lines: dataset select, limit select, criteria cards with param controls, rule builder, results table with reasons, prev/next, Run / Record / Export buttons), AppNav · Criteria names/descriptions/rationales bilingual (nameEn/nameFr…); operator labels RULE_OPERATOR_LABELS en/fr; studio messageFor() EN/FR; localizedTitle('Journal-entry selection','Sélection des écritures')

**Odoo 19 target.** Models: ea.audit.je.criterion (catalogue data), ea.audit.je.selection.run (params JSON + result cache), ea.audit.je.user.rule, ea.audit.firm.holiday, ea.audit.public.holiday, ea.audit.form.response (wp:S5.4 je_design). View: OWL client action (studio) + wizard for params; report xlsx (E3.1). Groups: run/read: group_staff+, group_eqr, group_read_only; record design & export: group_staff+ (not read_only/eqr).

SQL narrowing with OR-clauses over gl_line then Python reasoning; selection unit = line with reasons list; constraint: record requires selectedLines>0 and engagement not archived; voids S5.4 signoffs (ea.audit.signoff write-through); holiday calendar seeded data (CM) + firm additions.

**Effort / phase.** XL (14 pd) · 4 Tools. Source: `app/engagements/[id]/tools/je-selection/page.tsx`; rules in lib/je-selection.ts; components/JeSelectionStudio.tsx; app/api/engagements/[id]/je-selection/route.ts; app/api/engagements/[id]/je/export/route.ts; lib/je-export.ts; lib/je-workbook.ts; lib/lead-classes.ts; lib/gl-line.ts. Screenshot: extra\t09-je-selection.png, extra\d10-je-selection-with-data.png

#### C.7.9 `/engagements/[id]/tools/je-selection # export E3.1 workbook` — E3.1 Journal entries workbook export

**What it is.** ExcelJS workbook with 5 tabs: 1 Cover (Readme inputs typed once, fraud-risk context, four unpredictability levers, four controls, conclusion), 2 Population (ledger relied on + population checks — the population is IPE), 3 Criteria (each criterion, parameters, rationale, entries/lines matched), 4 Selection (items + reasons + four tests), 5 Exceptions. Identity typed once on Cover, other tabs by formula.

**Rules enforced (plain words).**

- Selection re-run at export
- limit SELECTION_CAP 500 and Selection tab says if capped
- missing ledger is not an error (Population tab states no dataset)
- never states 'sampled at random'
- bilingual by locale
- filename server-named (Content-Disposition)

**Data.** Reads: sub_ledger_dataset, gl_line (validatePopulation + runSelection), engagement, client. Writes: activity (export log).

**Who may do what.** requireEngagementAccess; logExport('e3.1-journal-entries')

**Sub-flows on this screen.** download

**Navigation.** from studio Export button or GET from E3.1 paper

**Components / i18n.** — · EN/FR by locale param; ISA refs via standards-edition

**Odoo 19 target.** Models: ea.audit.je.selection.run. View: report (xlsx via report_xlsx / openpyxl). Groups: group_staff+.

ea_audit_reports: xlsx report with formulas referencing Cover cells; blank template variant (blankJeTemplate) also served by Sample Papers.

**Effort / phase.** L (6 pd) · 4 Tools. Source: `lib/je-export.ts; platform/lib/je-workbook.ts; platform/app/api/engagements/[id]/je/export/route.ts`; rules in lib/je-export.ts; lib/je-workbook.ts. Screenshot: extra\t09-je-selection.png, extra\d10-je-selection-with-data.png

#### C.7.10 `/engagements/[id]/tools/lead-schedule` — Lead Schedule (index-named schedules)

**What it is.** Every account of the current (pre-audit) TB under its lead index (34 indexes T,Q,P1-P4,L,K,J,F,N,E,O1,O2,O4,I1,I2,G2,G3,C,UA,UB2,UC,U1,VA1,VA2,VB,VO,VD1-VD5,V1): Current Y closing, Prior Y, movement, variance %, auto-saved commentary per account and per total; units switch; print header (UAT B91); 'Extract to Excel' (Introduction tab + one tab per index). Account and total figures drill to the GL Console.

**Rules enforced (plain words).**

- CLOSING = opening_debit − opening_credit + debit − credit (debit-positive)
- PRIOR_SOURCE (UAT B81): valid prior_year TB closing per account if uploaded, else current TB opening
- MOVEMENT = closing − prior
- VARIANCE% = round(movement/|prior|×1000)/10, null when prior=0
- INDEX_MAPPING: client_lead_index_override longest prefix wins, else leadIndexFor() SYSCOHADA PREFIX_INDEX (e.g. 10-15→T, 16-18→Q, 19→P1, 20-21→L, 22-25,28→K, 281→L, 26-27,29→J, 3→F, 40→N, 41→E, 42-43→P2, 44→O2, 444/445/449→O1, 45-46→I2, 462→I1, 47→G2, 477→P3, 478→G3, 479→P4, 48→P3, 481→N, 49→G2, 490/491→E, 5→C, 60→VA1, 603→VA2, 604/605/608,61-63→VD1, 64→VO, 65→VD4, 66→VB, 67→VD5, 68-69→VD2, 70→UA, 71-73,75→UB2, 77→UC, 78-79→VD3, 81-83→V1, 84-86,88→U1, 89→O4); unmapped accounts skipped; indexes with no account omitted
- EXPORT: tab name '<code> <label>' sanitised, ≤31 chars; columns Account, Description, Account class, Account type, Current Y, Prior Y, Movement, Variance % (0.0%), Commentary
- TOTAL row double top border
- TOOL_FED: E4.1-E4.34 papers refuse sign-off with 'tool-output-missing-tb' until a VALID current-year TB exists (lib/tool-fed-papers.ts)
- INDEX_SECTION maps index → E4.x task (E→E4.1, N→E4.2, F→E4.3, K→E4.4 … O4→E4.34)

**Data.** Reads: engagement, client; trial_balance + trial_balance_version(current) + trial_balance_row; trial_balance_version timing='prior_year' validation_status='valid' latest; client_lead_index_override; form_response code LIKE 'ap:%'. Writes: form_response code='ap:<INDEX>' field_key = account (/^[0-9]{1,12}$/) or 'total' (POST ap-comments; empty deletes).

**Who may do what.** Page: auth() + getEngagement; commentary write via /api/engagements/[id]/ap-comments → requireWrite; export GET /lead-schedule-export → getEngagement (requireTenant) + proxy team gate; EQR/read_only can view and export, cannot comment.

**Sub-flows on this screen.** # commentary autosave (per account / total); # units switch; # Extract to Excel (GET /api/engagements/[id]/lead-schedule-export); # drill account/total to GL Console

**Navigation.** Back → /tools; drill → /tools/gl-console?accounts=…; empty state → Trial Balance Analyzer (/data)

**Components / i18n.** ApSchedules (client; showOverall=false here; useAutoSave → ap-comments; units fcfa/k/m; links to gl-console with ?accounts&opening&closing), AppNav · leadIndexLabel/accountTypeLabel/accountClassLabel en/fr; inline EN/FR; export language = screen locale (getLocale)

**Odoo 19 target.** Models: ea.audit.lead.index (data: 34 indexes + sub-indexes), ea.audit.lead.schedule.line (computed from TB rows), ea.audit.ap.comment, ea.audit.lead.index.override. View: OWL grid (grouped by index, expandable) or hierarchical list with editable commentary; xlsx report. Groups: read/export: group_staff+, group_eqr, group_read_only; comment: group_staff+ (writers).

Computed (non-stored or recomputed on TB version change) lines; prefix map as data model with 'longest prefix wins' Python; xlsx report one sheet per index; print layout with header (client, period end, printed by/when).

**Effort / phase.** M (5 pd) · 4 Tools. Source: `app/engagements/[id]/tools/lead-schedule/page.tsx`; rules in lib/analytical-procedures.ts; lib/lead-classes.ts; components/ApSchedules.tsx; app/api/engagements/[id]/lead-schedule-export/route.ts; app/api/engagements/[id]/ap-comments/route.ts; lib/tool-fed-papers.ts. Screenshot: extra\t10-lead-schedule.png, extra\d03-lead-schedule-with-data.png

#### C.7.11 `/engagements/[id]/tools/materiality` — Materiality (ISA 320) — PM / TE / SAD nominal

**What it is.** Derive benchmark bases from the ingested TB, generate a materiality version (benchmark, amount, %, TE %, SAD %, justifications), show the current thresholds (Planning Materiality, Tolerable Error, SAD Nominal) with deviation chips, the version in force when a draft sits above it (UAT B49), partner approval, and the version history. Approved version feeds P6.1 (tool-fed), P6.2 significance, SAD, SAP and Sampling.

**Rules enforced (plain words).**

- BENCHMARKS: pbt, revenue, total_assets, equity, expenses
- BENCHMARK_RANGES %: pbt 5–10, revenue 0.5–2, total_assets 0.5–2, equity 1–5, expenses 0.5–2 (form default % = midpoint, e.g. pbt 7.5)
- PERFORMANCE_PCT_RANGE min 60 max 85 default 75
- TRIVIAL_PCT_RANGE min 0.5 max 10 default 5
- COMPUTE: overall(PM)=round(benchmarkAmount×pct/100); performance(TE)=round(PM×performancePct/100); trivial(SAD nominal)=round(PM×trivialPct/100)
- UMT = max(0, PM − TE) (uncorrectedMisstatementThreshold)
- TB_BASES (SYSCOHADA, closing=opening_debit−opening_credit+debit−credit): revenue=max(0,round(−Σclass7)); expenses=max(0,round(Σclass6)); pbt=revenue−expenses; equity=max(0,round(−Σ accounts 10-15)); total_assets=round(Σ debit-balance accounts of classes 2-5)
- VALIDATION (invalid-materiality): amount>0, 0<pct≤100, performancePct within 60-85, trivialPct within 0.5-10; justification required (defaults to 'Documented in P6.1')
- TE_JUSTIFICATION: performancePct ≠ 75 requires performanceJustification ('performance-justification-required', ISA 320 ¶11, UAT B42)
- DEVIATIONS (UAT B47): outOfRange = pct outside benchmark range; basisMismatch = TB base>0 and ||amount|−base| > max(1, base×0.005); either requires overrideJustification else 'materiality-out-of-range' / 'materiality-basis-mismatch'; override text appended to performance_justification with ' — '
- DRAFT_DOES_NOT_SUPERSEDE: new version is draft; approved version stays in force until partner approves the draft (approveMateriality supersedes older approved)
- APPROVE: only latest version_no ('stale-version'), status must be draft ('not-found'), two versions never both approved
- REFLAG (ISA 450 ¶5, ISA 320 ¶12-13): misstatement.trivial := |amount| < approved.trivial (classification only, amounts untouched; counts logged)
- REVISION_NOTIFY: creating a version while an approved one exists notifies team partners
- BENCHMARK_SELECT: changing benchmark refills amount from TB base and % from range midpoint (client)
- TOOL_FED: P6.1 sign-off refused 'tool-output-missing-materiality' until status approved

**Data.** Reads: materiality (+app_user approved_by); trial_balance/trial_balance_version(current)/trial_balance_row (tbBenchmarkAmounts); engagement. Writes: materiality INSERT (version_no = max+1, status draft) via createMaterialityAction; materiality UPDATE status approved/superseded + approved_by/approved_at via approveMaterialityAction; misstatement.trivial re-flagged (reflagMisstatements); notification kind 'materiality-revised' to team partners; activity logMaterialityChange created/revised/approved + 'materiality.reflagged'.

**Who may do what.** View: any team member. Generate: createMaterialityVersion → requireWrite() ('read-only-role' for read_only/client_user). Approve: approveMateriality → requireWrite + canPartnerSignoff(role) = atLeast(role,'partner') (partner, firm_admin) else 'requires-partner'; button rendered only for isPartner (UAT B129), others see 'Awaiting partner approval'. Archived: DB triggers raise 'engagement-archived' → ?error=archived.

**Sub-flows on this screen.** # use TB basis / choose benchmark (fills form); # generate version (createMaterialityAction); # approve version (partner only; approveMaterialityAction → reflag misstatements); # version history table

**Navigation.** Back → /tools; returnTo hidden field keeps user on tool (actions default to /planning otherwise); notification href → this tool; P6.1 paper cites approved figures

**Components / i18n.** MaterialityBasis (client: 5 base cards with Use button; hint of ranges), MaterialityBenchmarkSelect (client), SubmitButton, ErrorBanner (GatesPanel), Chip/Panel/PanelHeader, AppNav · planning.materiality.* (title, benchmark, benchmarks.{pbt,revenue,total_assets,equity,expenses}, amount, percentage, performancePct, performanceJustification, trivialPct, approve, statusLabel) and planning.errors.* (invalid-materiality, materiality-out-of-range, materiality-basis-mismatch, performance-justification-required, justification-required, stale-version, requires-partner, archived) — EN/FR parity; formatFCFA (space-grouped, 'FCFA'); inline EN/FR for chips/history. Note: en.json trivialPct label says '3–5' while code range is 0.5–10 (text drift).

**Odoo 19 target.** Models: ea.audit.materiality (version_no, benchmark, benchmark_amount, percentage, justification, performance_pct, performance_justification, trivial_pct, overall, performance, trivial, state draft/approved/superseded, approved_by, approved_at), ea.audit.misstatement (trivial recomputed). View: form (tool page) + list (history) + wizard 'Generate version'; button 'Approve' with group check. Groups: view: group_staff+, group_eqr, group_read_only; generate: group_staff+ (writers); approve: group_partner, group_firm_admin.

Computed fields overall/performance/trivial (store=True); SQL/py constraints on ranges; constraint TE justification when performance_pct≠75; deviation check against TB bases needs override justification; action_approve: only latest, supersede others, re-flag misstatements, mail activity to partners on revision; record rule team membership; P6.1 sign-off gate depends on approved record.

**Effort / phase.** M (5 pd) · 4 Tools. Source: `app/engagements/[id]/tools/materiality/page.tsx`; rules in lib/materiality.ts; lib/materiality-model.ts; app/actions/planning.ts (createMaterialityAction, approveMaterialityAction); components/MaterialityBasis.tsx; components/MaterialityBenchmarkSelect.tsx; lib/rbac.ts; lib/tool-fed-papers.ts; messages/en.json planning.materiality. Screenshot: extra\t05-materiality.png, extra\d04-materiality-with-data.png; other agent: 09-materiality-tool.png

#### C.7.12 `/engagements/[id]/tools/materiality # approve` — Materiality — Partner approval

**What it is.** Partner approves the latest draft; older approved version becomes superseded; SAD misstatements re-classified against the new trivial threshold; activity logged.

**Rules enforced (plain words).**

- Only latest version_no ('stale-version')
- supersede all other approved
- draft→approved else 'not-found'
- reflag: trivial=false where |amount|≥trivial, trivial=true where |amount|<trivial
- counts in activity summary

**Data.** Reads: materiality. Writes: materiality.status/approved_by/approved_at; misstatement.trivial; activity.

**Who may do what.** requireWrite + canPartnerSignoff (atLeast partner) → 'requires-partner'

**Sub-flows on this screen.** button → server action

**Navigation.** stays on tool via returnTo

**Components / i18n.** SubmitButton form (approve-materiality) · planning.materiality.approve; planning.errors.stale-version / requires-partner

**Odoo 19 target.** Models: ea.audit.materiality, ea.audit.misstatement. View: form button (server action). Groups: group_partner, group_firm_admin.

action_approve with ensure_one; recompute misstatement.trivial via write.

**Effort / phase.** S (1 pd) · 4 Tools. Source: `lib/materiality.ts (approveMateriality, reflagMisstatements)`; rules in lib/materiality.ts. Screenshot: extra\t05-materiality.png, extra\d04-materiality-with-data.png; other agent: 09-materiality-tool.png

#### C.7.13 `/engagements/[id]/tools/review-notes` — Review notes register

**What it is.** Every review note of the engagement (notes on tasks and on documents merged, UAT B18) in one filterable table: task code/title, owner (assignee), author, note + response, state open/cleared, raised at, resolution hours, cleared by. Filters: scope all / for me / by me (?scope= from dashboard), state all/open/cleared, text search. Row opens the task.

**Rules enforced (plain words).**

- REGISTER_SCOPE: WHERE coalesce(n.engagement_id, d.engagement_id, fi.engagement_id) = engagement
- ORDER cleared last, newest first
- RESOLUTION_HOURS = round((cleared_at − created_at)/3600, 1); mine = author_id = me; forMe = assignee_id = me; times shown Africa/Douala 'WAT'

**Data.** Reads: review_note; document; file_item; app_user (author, assignee, cleared_by). Writes: —.

**Who may do what.** View: any accepted team member (auth + getEngagement). No writes on this page; mutations happen on the task page via API routes (see flow record).

**Sub-flows on this screen.** # scope/state filters (client-only)

**Navigation.** Back → /tools; rows → /engagements/[id]/sections/<fileItemId>; dashboard 'For me'/'By me' deep-link with ?scope=for_me|by_me

**Components / i18n.** NoteRegister (client filter/search; ui/grid), Panel, AppNav · inline EN/FR; task titles title_en/title_fr

**Odoo 19 target.** Models: ea.audit.review.note (file_item_id, document_id, engagement_id, author_id, assignee_id, body, response, state open/cleared, cleared_by, cleared_at). View: list with filters/search panel (My notes, For me, Open) + computed resolution_hours. Groups: read: group_staff+, group_eqr, group_read_only.

Standard list view with search filters; computed field resolution_hours; open notes block sign-off and archive gate (see flow record).

**Effort / phase.** S (2 pd) · 4 Tools. Source: `app/engagements/[id]/tools/review-notes/page.tsx`; rules in lib/task-notes.ts (noteRegister); components/NoteRegister.tsx. Screenshot: extra\t12-review-notes.png

#### C.7.14 `/engagements/[id]/tools/review-notes # raise / respond / clear (API)` — Review note lifecycle (raise → respond → clear)

**What it is.** Mutations behind the register (invoked from the task page ReviewNotes panel): raise a note on a task (lands on assignee's dashboard + notification), reply without clearing (UAT B19), clear with attributed comment. Open notes block reviewer/partner signature (signDocument) and the archive gate review_notes_cleared.

**Rules enforced (plain words).**

- NOTE_REQUIRED ('note-required')
- RESPONSE_REQUIRED on respond
- TASK_IN_ENGAGEMENT: fileItemId UUID and belongs to engagement in URL (UAT run 3 B01) else 404
- NOTE_IN_ENGAGEMENT (UAT run 2 B03)
- CLEAR_RULES as above; notes are cleared never deleted (trail); only status='open' rows can be responded/cleared

**Data.** Reads: review_note, document, file_item, app_user, team_member. Writes: review_note INSERT (author_id, assignee_id = task assignee); UPDATE response appended as '[name · YYYY-MM-DD HH:MI WAT] text'; UPDATE status='cleared', cleared_at, cleared_by; notification kind 'review_note' to author on reply; activity review_note_answered / review_note_cleared.

**Who may do what.** All three: requireWrite() (read_only/client_user → 403 'read-only-role') + assertNoteReachable (visibleToUser accepted team → 403 'not-on-this-engagement'). Clear: author may always clear own note; otherwise atLeast(role,'manager') ('requires-manager-or-author') AND not the preparer of the paper (isPreparerOfNote → 'not-preparer-clears', ISA 220R ¶29). EQR can raise notes (notes are its channel; EQR write block applies to papers, not notes).

**Sub-flows on this screen.** # add review note; # respond; # clear

**Navigation.** from task page; links back via notification href

**Components / i18n.** ReviewNotes (task page panel) · error codes read-only-role, not-on-this-engagement, requires-manager-or-author, not-preparer-clears in planning.errors

**Odoo 19 target.** Models: ea.audit.review.note. View: form/chatter-like panel on file item; server actions action_respond/action_clear. Groups: raise/respond: group_staff+, group_eqr; clear: author or group_manager+ (not preparer).

Python check in action_clear (author or manager+ and not preparer signoff holder); mail.activity/notification to assignee and author; constraint blocking signoff and archive while open notes exist.

**Effort / phase.** M (3 pd) · 4 Tools. Source: `lib/task-notes.ts; platform/app/api/engagements/[id]/task-notes/route.ts; task-notes/respond/route.ts; task-notes/clear/route.ts; platform/components/ReviewNotes.tsx`; rules in lib/task-notes.ts; app/api/engagements/[id]/task-notes/*/route.ts; lib/documents.ts (isPreparerOfNote). Screenshot: extra\t12-review-notes.png

#### C.7.15 `/engagements/[id]/tools/sad` — Summary of Audit Differences (ISA 450) workbook

**What it is.** Replica of the firm's Excel SAD template (1016_DPDC_SAD) on one page with six expandable schedules: Uncorrected, Corrected, Conclusion, Reclassifications, Cash-flow misstatements, Disclosure misstatements. Entries flow automatically from adjustments proposed on E4/E5 working-paper steps (psp results finding/adj_debit_*/adj_credit_*) and from C1.1 register rows without a step (sampling projections, routed findings); preparer classifies caption (suggested from SYSCOHADA account), type, corrected flag, rationale, and posts each onto the misstatement register C1.1 evaluates. Conclusion tab: tax effect, prior-period turnaround, UMT verdict, qualitative factors, team conclusion (tool-fed C1.1). Export Excel client copy.

**Rules enforced (plain words).**

- CAPTIONS: current_asset, non_current_asset, current_liability, non_current_liability, equity, income, expense → 6 grid columns (income & expense share column 5 'Income statement')
- SUGGEST_CAPTION (SYSCOHADA leading digits): class 1: 10-15 equity else non_current_liability
- 2 non_current_asset
- 3 current_asset
- 4: 41/45/47/49 current_asset else current_liability
- 5: 56 current_liability else current_asset
- 6 expense
- 7 income
- 8 odd second digit expense / even income
- TYPES: factual, judgmental, projected (MAIN_TYPES), classification, disclosure; default factual
- CORRECTED spellings yes/1/true vs no/0/false
- ENTRY_SOURCE: step has adjustment when dr or cr amount ≠0 or an account filled; amount posted = max(|dr|,|cr|); accounts text 'Dr <acct> (<caption label>) / Cr <acct> (<caption label>)' in poster's language (UAT B152)
- STALE: posted row re-flagged when register amount/accounts/type/corrected no longer match the paper (UAT run 2 B11) → re-post; postSadEntryIfPosted re-posts automatically when paper changes
- REGISTER_ONLY rows (program_step_id IS NULL, trivial=false): caption default expense, SAD edits type/corrected in place (UAT run 2 B63)
- TRIVIAL (ISA 450 ¶5, UAT B51): item is clearly trivial when max(|dr|,|cr|) < nominal = round(PM×trivial_pct/100); listed apart, never summed; misstatement.trivial stored at post time = amount < materiality.trivial
- GRID TOTALS per column: +dr in dr caption column, −cr in cr caption column
- FS_CAPTIONS from current TB: closing grouped by suggestCaption; assets debit-positive, liabilities/equity/IS credit-positive; column 5 = classes 7 − 6 net; incomeBeforeTax = −(Σclass6+Σclass7)
- EFFECT% = total/FS amount
- TAX_CASCADE: rate default 33 % (meta tax_rate 0-100); taxEffect = −cumIS×rate; afterTax = cumIS + taxEffect; cumulative = afterTax + (turnaround_factual + turnaround_judgmental)×(1−rate)
- CONCLUSION_SERIES: [cumIS, cumIS+turnF+turnJ, afterTax, cumulative] each compared with UMT = PM − TE → Yes (red #ffc0c0) / No (green #c6efce); % of income before tax / after tax (meta income_after_tax)
- QUALITATIVE: template questions tq_1..tq_5 (sensitivity items a-i, trend masking, management bias, intentional misstatements/fraud, prior-period effect) answers yes/no/na with comments tq_Nc (comment required if any Yes), legacy q_/qx_ for SAD_QUAL_FACTORS sensitivity, subtotals, balance_sheet, covenants, loss_reversal, segments, trend_mask, bias (ISA 450 ¶A21)
- META_VALIDATION: cf_rows/disc_rows must be JSON arrays; rationale ≤4000 chars; meta ≤100000 chars; unknown key → invalid-field
- TOOL_FED C1.1: sign-off refused until concl_text non-empty AND approved materiality AND valid TB ('tool-output-missing-sad/-materiality/-tb')
- SORT entries by taskCode numeric then ref
- CURRENCY from trial_balance.currency default XAF (UAT run2-B128)

**Data.** Reads: engagement, client, trial_balance.currency; program_step + file_item (code LIKE 'E%'); form_response (code LIKE 'psp:%' results; code='sad' overrides and meta); misstatement; materiality (approved: overall, performance, trivial_pct); trial_balance_row of current version (FS caption totals). Writes: form_response code='sad' field '<drcap|crcap|mtype|corrected|rationale>_<stepId>' and meta keys (concl_text, cf_rows, disc_rows, tax_rate, turnaround_factual, turnaround_judgmental, income_after_tax, q_*, qx_*, tq_1..5, tq_Nc) via saveSad/saveSadMeta; misstatement INSERT/UPDATE (program_step_id upsert; description, accounts text, amount, mtype, corrected, trivial) via postSadEntry; for register-only rows UPDATE misstatement mtype/corrected.

**Who may do what.** View: any team member (auth + getEngagement). POST /api/engagements/[id]/sad: assertMutable (archived → 423); op save/saveMeta → requireTenant (any non-client role incl. read_only can technically write — no requireWrite; EQR not blocked here); op post → requireWrite. Export GET: getEngagement (requireTenant) + proxy team gate.

**Sub-flows on this screen.** # classify entry (dr/cr caption, type, corrected, rationale — autosave); # post to misstatement register (and re-post stale); # conclusion tab (tax rate, turnaround, income after tax, qualitative tq_1..5 + comments, team conclusion text); # cash-flow manual rows; # disclosure manual rows (corrected/uncorrected); # Export Excel client copy (GET /api/engagements/[id]/sad/export)

**Navigation.** Back → /tools; each entry links to its working paper /sections/<taskItemId>; evaluated in C1.1; attached to representation letter C3.1

**Components / i18n.** SadWorkbook (client, 649 lines: six section() accordions, grid with HDR #d9d9d9 / BAND #c0c0c0 / YEL #ffff99 cells, Debit/(Credit) brackets, inline selects for caption/type, corrected checkbox, rationale, Post button, conclusion inputs, manual cf/disc row editors), AppNav. (SadBoard.tsx is an older unused variant.) · SAD_CAPTION_LABELS and MISSTATEMENT_TYPE_LABELS en/fr (shared with C1.2, UAT run2-B151); inline EN/FR; export ?locale=

**Odoo 19 target.** Models: ea.audit.misstatement (register), ea.audit.sad.entry (per step overrides: dr/cr caption, mtype, corrected, rationale), ea.audit.sad.meta / ea.audit.sad.conclusion (tax_rate, turnarounds, income_after_tax, tq answers, concl_text), ea.audit.sad.cashflow.line, ea.audit.sad.disclosure.line, ea.audit.materiality, ea.audit.trial.balance.row. View: OWL client action replicating the 6-schedule workbook (spreadsheet-like grid) + xlsx report (6 sheets). Groups: view: group_staff+, group_eqr, group_read_only; classify/meta: group_staff+ writers; post: group_staff+ (requireWrite).

Entries are computed from program-step results (ea.audit.program.step.result) joined to overrides; suggestCaption as Python; stored misstatement.trivial recomputed on materiality approval; constraint: C1.1 sign-off requires conclusion text; report in ea_audit_reports with the template colours; consider storing SAD entries as real records (one per step) instead of key/value form_response.

**Effort / phase.** XL (12 pd) · 4 Tools. Source: `app/engagements/[id]/tools/sad/page.tsx`; rules in lib/sad.ts; lib/sad-model.ts; lib/materiality-model.ts; components/SadWorkbook.tsx; app/api/engagements/[id]/sad/route.ts; app/api/engagements/[id]/sad/export/route.ts; lib/tool-fed-papers.ts. Screenshot: extra\t08-sad.png, extra\d06-sad-with-data.png

#### C.7.16 `/engagements/[id]/tools/sad # export Excel` — SAD — Excel export (client copy)

**What it is.** ExcelJS workbook, 6 sheets: 'SAD uncorrected' (band Entity/Period/Currency, PM/TE/Nominal; grid by factual/judgmental/projected; totals; FS amounts; effect %; trivial list; tax cascade), 'SAD corrected' (with rationale col), 'SAD conclusion' (before/after tax × before/after turnaround, % of income, PM, UMT, Yes/No verdict, qualitative tq_1..5, team conclusion), 'Reclassification missts', 'Cash flow missts', 'Missts in disclosures'. Landscape, fit to width, footer entity/title/page.

**Rules enforced (plain words).**

- MONEY format '#,##0;(#,##0)'
- PCT '0.00%'; colours HDR FFD9D9D9, BAND FFC0C0C0, YEL FFFFFF99; verdict fills FFFFC0C0 / FFC6EFCE; filename SAD-<entity>-<periodEnd>.xlsx; same arithmetic as screen (rate default 33 %)

**Data.** Reads: sadView (see parent). Writes: —.

**Who may do what.** getEngagement (requireTenant) + proxy team gate; no export log (unlike other exports)

**Sub-flows on this screen.** download

**Navigation.** button on SAD page

**Components / i18n.** — · ?locale=fr|en

**Odoo 19 target.** Models: —. View: report xlsx. Groups: all team roles.

ea_audit_reports xlsx; add export logging for consistency.

**Effort / phase.** M (3 pd) · 4 Tools. Source: `app/api/engagements/[id]/sad/export/route.ts`; rules in app/api/engagements/[id]/sad/export/route.ts; lib/sad-model.ts. Screenshot: extra\t08-sad.png, extra\d06-sad-with-data.png

#### C.7.17 `/engagements/[id]/tools/sad # post to register` — SAD — Post entry onto misstatement schedule (C1.1)

**What it is.** Upsert one misstatement row per program step from the SAD entry: description (finding or '<ref> adjustment'), accounts text with caption labels, amount = max(|dr|,|cr|), mtype, corrected, trivial flag.

**Rules enforced (plain words).**

- trivial = amount < approved trivial nominal
- register-only rows: only mtype/corrected updated
- re-post when SadWorkbook changes type/corrected of a posted row
- stale detection compares amount, 'Dr <acct> (' prefix, ' / Cr <acct> (' and type/corrected

**Data.** Reads: form_response (psp + sad), misstatement, materiality. Writes: misstatement INSERT/UPDATE.

**Who may do what.** requireWrite; assertMutable

**Sub-flows on this screen.** button

**Components / i18n.** SadWorkbook Post button · caption labels in poster's locale

**Odoo 19 target.** Models: ea.audit.misstatement. View: server action. Groups: group_staff+ writers.

Method action_post on sad.entry; keep link program_step_id unique per engagement.

**Effort / phase.** S (1 pd) · 4 Tools. Source: `lib/sad.ts (postSadEntry, postSadEntryIfPosted)`; rules in lib/sad.ts. Screenshot: extra\t08-sad.png, extra\d06-sad-with-data.png

#### C.7.18 `/engagements/[id]/tools/sample-papers` — Sample working papers (blank templates shelf)

**What it is.** Catalogue of the methodology's blank papers grouped by TEMPLATE_CATEGORIES (Tests of controls; Substantive procedures; General audit procedures), each card naming the task(s) it is the standard paper for, with a download link. Downloading changes nothing on the engagement; the paper a task works on is the attachment seeded on that task from the same catalogue.

**Rules enforced (plain words).**

- TEMPLATES (8): toc-scot 'E1.2 Tests of Controls.xlsx' (generated, defaultFor E1.2
- FR name 'E1.2 Tests des contrôles.xlsx'); itgc-e11 'E1.1 ITGC Testing.xlsx' (generated, E1.1); sub-trade-receivables 'E_Trade Receivables.xlsx' (shipped, E4.1); sub-trade-payables 'N_Trade Payables.xlsx' (E4.2); sub-inventory 'F_Inventory.xlsx' (E4.3); sub-fixed-assets 'K_Fixed Assets.xlsx' (E4.4); je-testing 'E3.1 Journal Entries.xlsx' (generated blankJeTemplate, E3.1); fs-checklist-ohada 'C2.1.1_Ohada Financial Statement Checklist.xlsx' (generated, E6.10
- 36 notes of SYSCOHADA révisé)
- GENERATED papers built on demand in locale (never cached) from the same builders as completed papers so templates cannot drift
- SHIPPED files read once and cached
- SEEDING: ensureDefaultWorkpaper attaches template bytes as task_attachment version 1 on first task open (idempotent, skipped when archived)
- ASSIGN from task attachments menu: assignTemplate → assertMutable; toc-scot built from the engagement's own controls when present (exportTocWorkbook); voids stale sign-offs on the item (UAT run 2 B10) and logs 'attachment_template_assigned'; downloads follow interface language (UAT run 2 B61)

**Data.** Reads: engagement; file_item (engagementTasks for task titles); static TEMPLATES; files under wp-templates/ (E_Trade Receivables.xlsx, N_Trade Payables.xlsx, F_Inventory.xlsx, K_Fixed Assets.xlsx). Writes: activity (logExport).

**Who may do what.** View: any team member. Download GET /api/engagements/[id]/wp-templates/[key]: requireEngagementAccess (403) ; logged as export 'sample-working-paper:<key>'.

**Sub-flows on this screen.** # download template (GET)

**Navigation.** Back → /tools; download /api/engagements/[id]/wp-templates/<key>

**Components / i18n.** Panel/PanelHeader, AppNav · titleEn/titleFr, descriptionEn/descriptionFr per template; localizedTitle('Sample working papers','Feuilles de travail types')

**Odoo 19 target.** Models: ea.audit.wp.template (key, category, name, title, description, default_for codes, attachment or generator), ea.audit.task.attachment. View: kanban (cards grouped by category) + controller /ea_audit/wp_template/<key> download. Groups: read/download: group_staff+, group_eqr, group_read_only.

Shipped xlsx as ir.attachment data files; generated ones via xlsx builders in ea_audit_reports (ToC E1.2, ITGC E1.1, JE E3.1, OHADA FS checklist); seeding hook on file.item open; assign action voids signoffs.

**Effort / phase.** M (3 pd) + builders counted elsewhere · 4 Tools. Source: `app/engagements/[id]/tools/sample-papers/page.tsx`; rules in lib/wp-templates.ts; app/api/engagements/[id]/wp-templates/[key]/route.ts; lib/toc-workbook.ts; lib/itgc-workbook.ts; lib/je-workbook.ts; lib/fs-checklist-workbook.ts. Screenshot: extra\t13-sample-papers.png

#### C.7.19 `/engagements/[id]/tools/sampling` — Sampling (tests of controls, tests of details, results & projection)

**What it is.** Three sections: 1 Sampling for tests of controls — controls selected on S2.1 with attributes; enter/save population; minimum sample from frequency table; server-side seeded random draw with append-only history (F061); Excel extract one tab per control. 2 Sampling for tests of details — choose Balance sheet / Income statement side and assurance from other procedures; generate workbook with one tab per lead index (key items ≥ threshold + MUS systematic sample). 3 Results & projection — record per index sample value, sample misstatement, key-item misstatement, remaining population; projected misstatement to C1.1.

**Rules enforced (plain words).**

- TOC_MIN_SAMPLE (SAMPLE 3.3, tocSuggested): automated control → 1 (ITGCs effective); manual daily (daily/continuous/many times): population required; >250 → 25, or 60 when 'sole' control covering an assertion
- 50–250 → ceil(10 %)
- 5–49 → 5; <5 → all; weekly 5; monthly 2; quarterly 2; semi-annually 2; annually 1 (capped at population)
- SOLE = control is the only selected control covering one of its WCGW assertions
- FREQ normalisation by keywords (dail/jour/continuous/many; week/hebdo; month/mens; quart/trim; semi/semes; ann)
- DRAW: partial Fisher–Yates over 1..population, k = min(size, population), ascending
- RNG seeded: seed = 16 random bytes hex, random(seed,i) = HMAC-SHA256(seed, i) first 4 bytes / 2^32 → reproducible from stored seed (F061)
- REDRAW: draw_no>1 needs reason ≥3 chars ('redraw-reason-required'); once E1.2 grid has any result (tocTestingStarted) only teamRank ≥ manager may redraw; population <1 → 'toc-population-required'; size<1 → 'toc-size-invalid'
- TOC_EVALUATE (tocEvaluate, discovery sampling): plan ≥60 or tested ≥60: 0 deviations high, 1 moderate, >1 none; plan 25: 0 rely, 1 extend (to TOC_EXTENDED_SIZE 60), >1 none; plans 5/2/1: 0 rely else none
- (alt A2 table in sampling-params ATTRIBUTE_SAMPLE_SIZES daily 30, weekly 10, monthly 4, quarterly 2, annual 1, automated 1; evaluateAttribute 60: ≤1 high/2 moderate
- 30: 0 high/1 moderate
- 10: 0 moderate)
- TOD_PLAN (planTod): key items = lines ≥ threshold (default TE
- S3.1 cra_index_setting.key_item_threshold; capped at TE and at specific materiality from P6.1 sm_<index>, UAT B43); population = Σ|amount| of non-zero lines; coverage% = keyItemValue/population; column = largest ART_COLS [0,10,30,50,70,90,100] ≤ coverage; factor = ART_MUS[cra][assurance][col] (e.g. minimal/little [0.5,0.4,0.1,N…]; low/little [1.0,0.9,0.7,0.3,N…]; low_sr/little [1.4,1.3,1.0,0.7,0.2]; moderate/little [2.1,2.0,1.7,1.4,0.9]; high/little [2.6,2.5,2.3,1.9,1.4,0.3]; high_sr/little [3.0,2.9,2.6,2.3,1.8,0.7]; assurance some/corroborative/persuasive lower; null = no representative sample); baseSize = remaining/TE; sampleSize = ceil(base×factor) capped at remaining line count (then full population); interval = floor(remaining/sampleSize) ≥1; systematic MUS selection with start = floor(fraction×interval)+1, fraction = stableStartFraction(engagementId, index, ledger sha) (FNV-1a hash mod 1000 /1000) so the same ledger draws the same sample (UAT B79); one line selected once however many hooks
- CRA for index = worst ToD of relevant assessed cells (rowWorstTod) else DEFAULT_CRA 'moderate'; sides: bs = Assets/Liabilities/Equity indexes, is = Revenues/Expenses; export refusals: no-materiality (approved TE required), no-gl, no-mapping (account + amount or debit/credit)
- GL lines signed = debit−credit or amount; zero lines skipped
- TOD_RESULT (recordTodResult/evaluateSampling, ISA 530 ¶14): indexCode /^[A-Z][A-Z0-9]{0,2}$/; sampleValue>0 ('empty-population'); remaining ≥0; projected = round(sampleMisstatement/sampleValue × |remaining|); raised to C1.1 (route b5, mtype projected) when |projected| ≥ trivial; key-item misstatement ≠0 routed as factual (trivialConfirmed); screen: total likely = projected + key
- 'Exceeds TE' when |total| > TE
- MUS_PARAMS (sampling-params, used by task-level runSampling): CONFIDENCE_FACTORS 99→4.6, 98→3.7, 95→3.0, 90→2.3, 85→1.9, 80→1.6, 75→1.4, 70→1.2, 65→1.1, 60→0.9, 55→0.8, 50→0.7
- RISK_BAND_CONFIDENCE high 95, moderate 85, low 70; interval = tolerable/factor; n = ceil(population/interval); expected < tolerable; projectMLE = mean tainting × population (ratio fallback)

**Data.** Reads: file_item (tasks, S2.2 link); scot, scot_control (selectedForTesting, frequency, controlType, tocPopulation, sampleSize, tocSampleItems, tocSampleDrawnAt, toc_grid), wcgw assertions; materiality (approved TE); automation_run engine='sampling' method 'tod-mus'; toc_sample_draw; team_member (viewer rank); for ToD export: cra_assessment via craBoard, cra_index_setting.key_item_threshold, form_response wp:P6.1 'sm_<index>' (specific materiality), sub_ledger_dataset + sub_ledger_row (journal_entries), client_lead_index_override, trial_balance.currency. Writes: scot_control.toc_population (op updateControl); toc_sample_draw INSERT (draw_no, seed, population, sample_size, items, rule, reason, drawn_by) + scot_control.sample_size/sample_note/toc_sample_items/toc_sample_drawn_at (op drawTocSample); signoff voided on S2.2 and E1.2 (voidStaleScotSignoffs); activity toc_sample_drawn/redrawn; automation_run (recordTodResult: engine 'sampling', params method 'tod-mus', result_summary) + document/document_version (run sheet) ; misstatement via routeFinding (b5 → C1.1): projected (mtype 'projected') when ≥ trivial, key-item factual always (trivialConfirmed); activity export logs toc-samples / tod-sampling:<side>.

**Who may do what.** View: any team member. Draw/save population via POST /api/engagements/[id]/scots: assertMutable (423) + requireWrite + requireEngagementAccess; REDRAW after testing started requires team rank ≥ manager (TEAM_LADDER) else 'redraw-after-testing-manager-only'. Exports: requireEngagementAccess. recordTodResultAction → requireWrite.

**Sub-flows on this screen.** # save population (updateControl); # draw / redraw ToC sample (reason, manager lock); # draw history; # extract ToC samples workbook (GET sampling/toc-export); # generate ToD workbook per FS side (GET sampling/tod-export?side&assurance&locale); # record ToD result & project (recordTodResultAction → ?recorded=1 / ?error=)

**Navigation.** Back → /tools; control name → S2.2 task (/sections/<id>); results → C1.1 register; samples listed in E1.2 paper

**Components / i18n.** SamplingStudio (client: ToC table with population input/Save, Draw/Redraw with reason, history toggle (seed, items, who, when, why), Extract button; ToD side radiogroup + assurance select + Generate workbook; results form + results table), SubmitButton, Panel/PanelHeader, AppNav · inline EN/FR; REFUSALS map in studio for redraw-reason-required / redraw-after-testing-manager-only / toc-population-required (not in messages json); freqLabel from lib/control-labels; CRA/assurance labels en/fr in tod-workbook

**Odoo 19 target.** Models: ea.audit.scot.control (toc_population, sample_size, toc_sample_items, toc_sample_drawn_at, toc_grid), ea.audit.toc.sample.draw (append-only), ea.audit.tod.result (automation_run tod-mus), ea.audit.misstatement, ea.audit.materiality, ea.audit.cra.index.setting, ea.audit.sampling.param (constants: frequency table, ART_MUS matrix, confidence factors). View: OWL client action (3 sections) + wizards (draw with reason; ToD export options; record result); xlsx reports (ToC samples one sheet per control; ToD one sheet per index + cover). Groups: view: group_staff+, group_eqr, group_read_only; save population/draw/record: group_staff+ writers; redraw after testing: group_manager+ (team rank).

Pure Python ports of tocSuggested, drawTocSample (Fisher–Yates with HMAC-SHA256 seeded RNG), planTod (ART matrix as data), projection; constraints: redraw reason ≥3 chars, manager lock when E1.2 grid has results; void S2.2/E1.2 signoffs on draw; ToD export requires approved materiality; routeFinding creates misstatement rows on C1.1.

**Effort / phase.** XL (14 pd) · 4 Tools. Source: `app/engagements/[id]/tools/sampling/page.tsx`; rules in components/SamplingStudio.tsx; lib/toc-sampling.ts; lib/sampling-params.ts; lib/tod-plan.ts; lib/tod-export.ts; lib/tod-workbook.ts; lib/toc-sample-export.ts; lib/toc-sample-workbook.ts; lib/scots.ts (drawTocSampleForControl, listTocDraws); lib/engines.ts (recordTodResult, evaluateSampling, seededRandom); app/actions/engines.ts; app/api/engagements/[id]/sampling/toc-export/route.ts; app/api/engagements/[id]/sampling/tod-export/route.ts; app/api/engagements/[id]/scots/route.ts; lib/cra-model.ts; lib/cra.ts; lib/significant-accounts.ts (specificThresholds); lib/signoff-policy.ts (TEAM_LADDER). Screenshot: extra\t06-sampling.png, extra\d08-sampling-with-data.png

#### C.7.20 `/engagements/[id]/tools/sampling # ToD workbook export` — Sampling — Tests-of-details workbook (one tab per lead index)

**What it is.** For the chosen FS side builds cover + one sheet per index with parameters (CRA from S3.1 or default moderate, key-item threshold from S3.1 or TE, TE, assurance), key items in full, representative MUS sample, tester columns; indexes with no ledger line named on the cover.

**Rules enforced (plain words).**

- see parent TOD_PLAN
- filename Tests-of-details-<balance-sheet|income-statement>-<client>-<FY>.xlsx
- colours HDR FFD9D9D9, BAND FFC0C0C0, ENTRY FFFFF2CC, KEY FFFFEB9C, SAMPLE FFDDEBF7
- tab name ≤31 chars

**Data.** Reads: materiality (approved), cra_assessment/cra_index_setting, form_response wp:P6.1 sm_*, sub_ledger_dataset/sub_ledger_row, client_lead_index_override, trial_balance.currency, app_user. Writes: activity export log 'tod-sampling:<side>'.

**Who may do what.** requireEngagementAccess; 409 with code no-materiality / no-gl / no-mapping

**Sub-flows on this screen.** side radiogroup + assurance select + Generate

**Components / i18n.** SamplingStudio exportSide() · locale param; CRA_LABEL / ASSURANCE_LABEL en/fr

**Odoo 19 target.** Models: —. View: report xlsx + wizard. Groups: all team roles (read) — writes nothing.

ea_audit_reports; deterministic start fraction for reproducibility.

**Effort / phase.** L (6 pd) · 4 Tools. Source: `lib/tod-export.ts; platform/lib/tod-workbook.ts; platform/app/api/engagements/[id]/sampling/tod-export/route.ts`; rules in lib/tod-export.ts; lib/tod-plan.ts; lib/tod-workbook.ts. Screenshot: extra\t06-sampling.png, extra\d08-sampling-with-data.png

#### C.7.21 `/engagements/[id]/tools/sampling # draw ToC sample` — Sampling — Draw / redraw test-of-controls sample

**What it is.** Server draws `size` occurrence numbers from 1..population using a stored random seed; appends to toc_sample_draw (never replaced); updates the control's current draw; voids S2.2/E1.2 sign-offs; logs activity.

**Rules enforced (plain words).**

- see parent TOC_MIN_SAMPLE / DRAW / REDRAW
- note text 'Test of controls — <rule> · population N' stored as sample_note

**Data.** Reads: scot_control (FOR UPDATE), scot, toc_sample_draw count, team_member. Writes: toc_sample_draw, scot_control, signoff (void), activity.

**Who may do what.** requireWrite + requireEngagementAccess; redraw after testing: teamRank(accepted team role) ≥ manager

**Sub-flows on this screen.** inline reason input + Draw button

**Components / i18n.** SamplingStudio generateSample() · REFUSALS en/fr in component

**Odoo 19 target.** Models: ea.audit.toc.sample.draw. View: wizard. Groups: group_staff+; redraw-after-testing group_manager+.

Use row lock (FOR UPDATE) on control; append-only model (no unlink).

**Effort / phase.** M (3 pd) · 4 Tools. Source: `lib/scots.ts (drawTocSampleForControl); platform/lib/toc-sampling.ts`; rules in lib/scots.ts; lib/toc-sampling.ts; lib/engines.ts (seededRandom). Screenshot: extra\t06-sampling.png, extra\d08-sampling-with-data.png

#### C.7.22 `/engagements/[id]/tools/sampling # record ToD result` — Sampling — Record tests-of-details result and project

**What it is.** Form per index: sample value, misstatement in sample, key-item misstatement, remaining population → stores an automation_run (sheet 'ToD results <index>'), projects misstatement, routes to C1.1.

**Rules enforced (plain words).**

- projected = round(sampleMisstatement/sampleValue × |remaining|)
- raisedToB5 when |projected| ≥ trivial
- key misstatement routed factual (small ones logged trivial, not refused)
- errors invalid-index, invalid-amount, empty-population
- amounts parsed with spaces and comma decimals

**Data.** Reads: file_item (E4.x of index via INDEX_SECTION), materiality thresholds. Writes: automation_run, document/document_version (run sheet), misstatement (routeFinding b5).

**Who may do what.** requireWrite

**Sub-flows on this screen.** form submit

**Navigation.** redirect ?recorded=1 → 'see C1.1 for the register'

**Components / i18n.** SamplingStudio results form · inline EN/FR; finding titles in recorder language (UAT B137)

**Odoo 19 target.** Models: ea.audit.tod.result, ea.audit.misstatement. View: form (wizard) + list of results. Groups: group_staff+ writers.

Server action creating misstatement rows; computed 'exceeds TE'.

**Effort / phase.** S (2 pd) · 4 Tools. Source: `lib/engines.ts (recordTodResult, evaluateSampling); platform/app/actions/engines.ts (recordTodResultAction)`; rules in lib/engines.ts; app/actions/engines.ts; lib/execution.ts (routeFinding). Screenshot: extra\t06-sampling.png, extra\d08-sampling-with-data.png

#### C.7.23 `/engagements/[id]/tools/sap` — Substantive analytical procedures (ISA 520, F038)

**What it is.** Left: the 34 lead indexes with counts procedures · concluded · exceeding. Right (for ?index=): one procedure per assertion C/E/A/V/P: expectation model (required), inputs, expected value (required), data reliability (ISA 520 ¶5(b)), threshold default % of performance materiality by CRA level (firm defaults low 75 / moderate 50 / high 25 %, from tenant settings) or override % with mandatory reason, recorded amount from TB closing (or typed when no TB), difference vs threshold (within/above/not evaluable), investigation, corroboration, conclusion supported / not_supported.

**Rules enforced (plain words).**

- DEFAULT_SAP_THRESHOLDS low 75 %, moderate 50 %, high 25 % of performance materiality
- SAP_PCT_MIN 1, SAP_PCT_MAX 100, integers; thresholdPctFor: CRA minimal/low → low %, moderate → moderate %, high or NOT ASSESSED → high % (tightest)
- ORDER constraint firm settings: low ≥ moderate ≥ high ('sap-threshold-order')
- EVALUATE: threshold = round(PM_performance × pct/100) (null without approved materiality); difference = round(actual − expected); exceeds = |difference| > threshold (null when either unknown); pct = override ?? snapshot default
- VALIDATION: indexCode in LEAD_INDEX_BY_CODE ('invalid-index'); assertion ∈ C,E,A,V,P; expectationModel required ('sap-expectation-required' — without expectation it is a variance review not a substantive procedure); expectedValue finite ('sap-expected-value-required'); override needs isSapPct and reason ('sap-threshold-out-of-range', 'sap-override-reason-required'); conclusion ∈ supported|not_supported|null
- ACTUAL: TB closing of index when a TB exists (actual_source 'tb', typed value ignored) else manual
- SNAPSHOT: CRA level, firm pct and PM frozen at save (later settings changes affect only new saves)
- VOCABULARY F033: figure called 'performance materiality / seuil de travail', never 'PM'; counts per index exposed to E4 papers (sapCountsByIndex); variance review of lead schedules remains ISA 315 risk analytic, not replaced

**Data.** Reads: tenant (sap_threshold_low/moderate/high_pct); materiality (approved performance); cra_assessment (relevant ir/cr → craOf); file_item code LIKE 'E4.%'; substantive_analytical_procedure (+app_user updated_by); trial balance via apLeadSchedules (closing per index). Writes: substantive_analytical_procedure UPSERT (engagement_id, index_code, assertion) with snapshot cra_level, threshold_pct, override, performance_materiality, actual_value, actual_source tb|manual, texts, conclusion, updated_by; activity 'sap_saved'; tenant sap_threshold_* (settings action).

**Who may do what.** View: any team member. readOnly = engagement.phase==='archived' OR !canWrite(role) (fieldset disabled, no Save). saveSap → requireWrite + assertMutable; EQR not specifically blocked (canWrite true for eqr_reviewer). Firm thresholds: setSapThresholds → requireRole('firm_admin') (Settings page).

**Sub-flows on this screen.** # select index (left list); # save procedure per assertion (saveSapAction); (firm thresholds set in /settings via setSapThresholdsAction — firm_admin)

**Navigation.** Back → /tools; index link ?index=<code>; '<E4.x> → account paper' link to /sections/<fileItemId>; reached from S5.5 and each E4 paper; redirect to #sap-<assertion> after save

**Components / i18n.** ErrorBanner, Chip/Panel/PanelHeader, AppNav; plain server forms per assertion (saveSapAction) · sapAssertionLabel en/fr; craLevelLabel/craTone; planning.errors sap-expectation-required, sap-expected-value-required, sap-threshold-out-of-range, sap-threshold-order, sap-override-reason-required, invalid-index; inline EN/FR; localizedTitle('Substantive Analytics','Analytiques substantives')

**Odoo 19 target.** Models: ea.audit.sap.procedure (unique engagement+index+assertion), ea.audit.firm.settings (sap_threshold_low/moderate/high_pct), ea.audit.cra.assessment, ea.audit.materiality. View: form (master-detail: index list + 5 assertion sub-forms) or one2many editable; settings view for thresholds. Groups: view: group_staff+, group_eqr, group_read_only; save: group_staff+ writers (not read_only; archived read-only); thresholds: group_firm_admin.

Computed fields threshold/difference/exceeds (stored snapshot pct & PM); constraints as listed; archived engagement → readonly attrs; settings fields on res.company/ea.audit.firm with order constraint.

**Effort / phase.** M (4 pd) · 4 Tools. Source: `app/engagements/[id]/tools/sap/page.tsx`; rules in lib/sap.ts; lib/sap-model.ts; app/actions/sap.ts; lib/cra-model.ts; lib/analytical-procedures.ts; lib/lead-classes.ts (INDEX_SECTION). Screenshot: extra\t07-sap.png, extra\d07-sap-with-data.png

### C.8 Team

#### C.8.1 `/engagements/[id]/team` — Manage team (members, engagement partner seat, add by email)

**What it is.** Team table (member, initials, team role, invitation status with response time in WAT and decline reason, open assigned tasks, Remove), the engagement partner panel (partner, delegate; transfer the seat with the outgoing partner's new role; set/clear a delegate), and an add-by-email form (role on the six-level ladder or EQR, EQR objectivity declaration) that provisions unknown colleagues and sends an invitation.

**Rules enforced (plain words).**

- Exactly one engagement partner (one-engagement-partner; gate engagement_partner_designated needs exactly one accepted) F003; partner-role-requires-partner-rank (firm partner or firm_admin may hold the seat); last-partner: the only accepted partner cannot be removed/demoted
- Transfer: by firm_admin or current partner only, incoming must be partner rank and not the EQR, outgoing gets a ladder role below partner
- Delegate: must be a firm partner already on the team (delegate-not-on-team), not the partner (delegate-is-partner), not EQR
- EQR eligibility F005 (assertEqrEligibleTx): eqr-rank (firm partner/admin or firm-role EQR), eqr-on-team (no other team role, not the delegate; cannot switch to/from EQR role), eqr-cooling-off (accepted partner of the same client on an engagement whose period end is within the prior 2 years, ISQM 2 ¶20), eqr-declaration-required (objectivity checkbox); not-a-firm-member (client users excluded)
- Email domain allow-list F070 (invalid-email-domain names allowed domains); invalid-email; already-on-team unless declined; email-taken across tenants
- Invitation F008: new member status 'invited', sees only /invitations/[id], accept/decline with reason (reason-required), decline notifies the partner; archived engagement keeps its team (assertMutable, UAT B156); removing a member unassigns their tasks; times displayed in Africa/Douala WAT (UAT B123/B133)

**Data.** Reads: team_member, app_user, membership, engagement (partner_delegate_user_id), file_item (open assigned counts), tenant (allowed email domains). Writes: team_member (INSERT status invited; UPDATE role; DELETE/remove), app_user + membership (provision new colleague), invite token, engagement (partner_delegate_user_id; partner transfer updates team roles), file_item (unassign tasks of removed member), notification (engagement-invite, engagement-declined), email, activity_log.

**Who may do what.** auth() + layout F008; canManage = canReview(role) shows remove/add (server requireTeamManager: manager+ and not eqr_reviewer → team-manager-only; partner team role needs partner firm rank → partner-only-team-role); maySteerSeat = firm_admin OR current engagement partner (server transfer-partner-forbidden / not-engagement-partner); only accepted members reach the page so an admin not staffed cannot act (F008)

**Sub-flows on this screen.** # add-member-by-email, # remove-member, # transfer-engagement-partner, # set-partner-delegate

**Navigation.** in: settings, nature redirect, acceptance gate href, AppNav; out: /engagements/[id]/dashboard; invitation flow /invitations/[id] (other agent)

**Components / i18n.** AppNav, ErrorBanner (vars domains), NavLink, SubmitButton, Panel, PanelHeader · t.team, t.planning.team.roles (+ page-local OPEN_TASKS and many inline FR/EN); parity ok

**Odoo 19 target.** Models: ea.audit.team.member (user, team_role, status, responded_at, decline_reason), ea.audit.engagement (partner_delegate_id), res.users (provisioning), ea.audit.invite. View: form with one2many + wizards. Groups: manage group_manager+ (not group_eqr); partner seat changes group_partner (current engagement partner) or group_firm_admin.

Python constraints replicating all refusal codes; sql unique partial index one accepted partner per engagement; EQR eligibility check incl. 2-year cooling-off query; invitation via mail template + portal-less accept page; allowed email domains on res.company; display tz WAT

**Effort / phase.** L (6 pd) · 1 Foundation. Source: `app/engagements/[id]/team/page.tsx`; rules in lib/team.ts, lib/email-domains.ts, lib/invites.ts, lib/engagement-access.ts, lib/gates.ts (engagementPartnerDesignated), app/actions/planning.ts (team actions), app/actions/team-independence.ts. Screenshot: extra\e04-team.png; other agent: 06-team.png

#### C.8.2 `/engagements/[id]/team # transfer-engagement-partner / set-partner-delegate` — Engagement partner seat: transfer & delegate

**What it is.** Hand the partner seat to another firm partner (outgoing partner keeps a lower ladder role) or designate a delegate partner who may give partner-tier sign-offs.

**Rules enforced (plain words).**

- designate-engagement-partner-first
- already-engagement-partner
- partner-role-requires-partner-rank
- eqr-on-team
- invalid-team-role for outgoing (not partner/eqr)
- delegate-is-partner, delegate-requires-partner-rank, delegate-not-on-team
- assertMutable

**Data.** Reads: team_member, membership, engagement. Writes: team_member (roles), engagement.partner_delegate_user_id, activity_log.

**Who may do what.** actorRole === 'firm_admin' || actor is the current engagement partner (transfer-partner-forbidden / not-engagement-partner)

**Navigation.** stays

**Components / i18n.** forms · inline FR/EN

**Odoo 19 target.** Models: ea.audit.team.member, ea.audit.engagement. View: wizard. Groups: group_firm_admin or engagement partner identity.

wizard with constraints; partner tier checks (partnerTierRefusal) read partner + delegate

**Effort / phase.** S (2 pd) · 1 Foundation. Source: `app/actions/planning.ts transferEngagementPartnerAction / setPartnerDelegateAction → lib/team.ts`; rules in lib/team.ts (transferEngagementPartner, setPartnerDelegate), lib/signoff-policy.ts (engagementPartnerTx). Screenshot: extra\e04-team.png; other agent: 06-team.png

#### C.8.3 `/engagements/[id]/time` — Time (my entries & budget vs actual)

**What it is.** Log time (date, hours 0.25-24 in 0.25 steps, optional task from the non-conditional file index in phase order, note), list and delete my own entries, and a budget-vs-actual table by team grade with variance and totals, linking to the planning budget.

**Rules enforced (plain words).**

- invalid-date (YYYY-MM-DD), invalid-hours (> 0 and <= 24), invalid engagement
- Hours attributed to the logger's TEAM role (budgetVsActual joins team_member) — without a team role they fall under 'unassigned' and a warning shows (UAT run2-B146/B147); task options exclude conditional items and are sorted P,S,E,C numerically; budget set on /planning#budget (UAT B58)

**Data.** Reads: time_entry, budget_line, team_member, file_item, engagement. Writes: time_entry (INSERT/DELETE own).

**Who may do what.** auth() + layout F008; logTime/deleteTimeEntry requireWrite; delete only own rows (WHERE user_id = me)

**Sub-flows on this screen.** # log-time, # delete-entry

**Navigation.** in: AppNav/dashboard; out: /dashboard, /planning#budget

**Components / i18n.** AppNav, SubmitButton, NavLink, Panel, PanelHeader · t.time, t.planning.team.roles, t.users.roles (+ 1 inline label); parity ok

**Odoo 19 target.** Models: ea.audit.time.entry (or account.analytic.line), ea.audit.budget.line. View: list + form (timesheet-like) + pivot. Groups: ea_audit_core.group_staff+; own-rows record rule for unlink.

could reuse hr_timesheet/analytic lines keyed to engagement; grade from team role; budget vs actual pivot

**Effort / phase.** M (3 pd) · 2 Engagement file. Source: `app/engagements/[id]/time/page.tsx`; rules in lib/time.ts, lib/team.ts (listBudget, setBudgetLine), app/actions/time.ts. Screenshot: extra\e19-time.png

#### C.8.4 `/invitations/[id]` — Engagement invitation

**What it is.** The only engagement screen an invited (not yet accepted) team member may open (F008): shows engagement name, client, fiscal year and the offered team role, with Accept and Decline (reason mandatory). Accepting opens the engagement dashboard; declining notifies the engagement partner(s) and returns to /dashboard. Nothing of the file's content is shown.

**Rules enforced (plain words).**

- engagement team membership gate (F008): only accepted members open a file; invited members are routed here by proxy.ts invitationPending(); decline requires a reason (reason-required
- HTML minLength 3 and pattern with 3 non-space chars); response timestamped; a decline creates a notification for every other team_member with team_role 'partner'
- UUID format validated; team roles labelled partner/director/senior_manager/manager/senior/staff/eqr_reviewer

**Data.** Reads: team_member, engagement, client (myInvitation); team_member visibility (canSeeEngagement). Writes: team_member (status accepted/declined, responded_at, decline_reason) via respondToEngagement; notification (kind engagement-declined, to partners) via createNotification; activity_log (engagement_accepted / engagement_declined with reason meta). Server action: app/actions/team-independence.ts respondEngagementAction.

**Who may do what.** any signed-in firm role holding a team_member row with status 'invited' on that engagement (requireTenant; client_user refused); an already-accepted member is redirected to the engagement; anyone else to /engagements?error=not-on-this-engagement

**Sub-flows on this screen.** /invitations/[id] # decline with reason

**Navigation.** reached from proxy redirect on /engagements/[id]/*, dashboard To-do 'invitation' rows (portfolioActions), added-to-engagement email (/login?next=/invitations/<id>); → /engagements/[id]/dashboard (accept), → /dashboard (decline)

**Components / i18n.** AppNav, ErrorBanner (GatesPanel), SubmitButton, Panel · inline fr/en page strings; ErrorBanner uses planning.errors.*

**Odoo 19 target.** Models: ea.audit.team.member (state: invited/accepted/declined, decline_reason, responded_at), ea.audit.engagement, mail.message / mail.activity (partner notification). View: form. Groups: ea_audit_core.group_staff and above (any internal firm group).

Record rule on ea.audit.engagement: visible only when an accepted team.member row exists for the user (ir.rule with domain on team_member_ids). Invitation form as a simplified form view / wizard with Accept/Decline buttons; decline_reason required constraint; message_post to partners. Server action equivalents: action_accept/action_decline.

**Effort / phase.** S (2 pd) (estimate) · 2 Engagement file. Source: `app/invitations/[id]/page.tsx`; rules in lib/team.ts (myInvitation, respondToEngagement), lib/engagement-access.ts, app/actions/team-independence.ts, proxy.ts. Screenshot: —

#### C.8.5 `/resources` — Team workload

**What it is.** Firm-wide workload table: per internal user the name, role, open tasks (owned file items without a signed document), hours logged (time_entry) and number of engagements they sit on, sorted by open tasks desc.

**Rules enforced (plain words).**

- firm-management information only (assurance C2)
- counts are firm-wide totals, deliberately not filtered by engagement visibility (a partial count presented as total would mislead)
- client_user memberships excluded

**Data.** Reads: membership JOIN app_user, file_item, document, time_entry, team_member (teamWorkload). Writes: —.

**Who may do what.** page: `if (!canManageFirm(session.user.role as Role)) redirect("/dashboard")` (firm_admin only); lib teamWorkload: `requireRole("manager")` (the page is stricter than the lib)

**Navigation.** reached from /settings 'Team workload' (admin only)

**Components / i18n.** AppNav, Panel · en/fr keys resources.* (title, subtitle, member, role, openTasks, hours, engagements, empty), users.roles.*

**Odoo 19 target.** Models: res.users, ea.audit.file.item, ea.audit.time.entry (or hr_timesheet account.analytic.line), ea.audit.team.member. View: pivot / graph / list (read-only report). Groups: ea_audit_core.group_firm_admin (page) — decide whether to open to group_manager as the lib allows.

SQL view model (ea.audit.workload.report, _auto=False) or computed via read_group; pivot view by user. Ambiguity to resolve: page firm_admin vs lib manager.

**Effort / phase.** S (2 pd) (estimate) · 2 Engagement file. Source: `app/resources/page.tsx`; rules in lib/resources.ts, lib/rbac.ts. Screenshot: extra\x11-resources.png (redirected to /dashboard)

### C.9 Users

#### C.9.1 `/users` — Users

**What it is.** Firm user administration: table of internal users (name with '(you)', email, role select + Save, status Active / Invited — link not yet used / Invitation expired, actions Reset password or Resend invitation, Remove with confirmation naming the team count) and an 'Invite a user' form (name, email, role). Banners for errors and for sent invitations.

**Rules enforced (plain words).**

- ASSIGNABLE_ROLES firm_admin, partner, manager, senior, staff, eqr_reviewer, read_only (client_user never assignable)
- invite: email regex (invalid-email), name required (name-required), role valid (invalid-role)
- existing address: same firm & already active or client_user → email-taken, same firm still awaiting link → fresh link, belongs to another firm → email-other-firm (one login never straddles two firms), no firm → readmitted with new credentials
- no password ever travels by email — set-password link only (UAT B39), token hashed, 14 days, one live per user
- status derived: active (must_change false) / invited (live invite) / invite-expired
- resend only for must_change accounts (already-active)
- reset: cannot-reset-self, unusable placeholder hash, must_change=true, all sessions closed (session_version), reset link mailed
- role change: cannot-change-self, not for client_user rows (not-found)
- remove: cannot-remove-self, deletes membership but keeps app_user (sign-off history), removes team rows and clears task assignments on non-archived engagements only (archived files immutable), revokes sessions
- allowed-email-domain rule does NOT apply here (it applies to engagement-team invitations in lib/team.ts)
- ?invited echo validated as email
- self row has no actions

**Data.** Reads: membership JOIN app_user, user_invite, team_member (listFirmUsers); tenant.name, app_user (inviter) for mails. Writes: app_user (INSERT with random hash + must_change_password=true; UPDATE name/hash/must_change/session_version on readmission or reset), membership (INSERT role; UPDATE role; DELETE on remove), user_invite (createInvite: supersede + INSERT token hash, 14-day expiry), team_member (DELETE on live engagements when removing), file_item (owner_id/approver_user_id/assignee_user_id cleared on remove), app_user.session_version (+1 on reset/remove), activity_log (invited, password_reset, role_changed, removed); emails 'invitation' / 'password-reset' via lib/email.ts. Actions in app/actions/users.ts: inviteUserAction, resendInviteAction, resetPasswordAction, changeRoleAction, removeUserAction.

**Who may do what.** firm_admin only: page `if (!canManageFirm(session.user.role as Role)) redirect("/dashboard")`; every lib function calls requireAdmin → canManageFirm else UserAdminError('forbidden')

**Sub-flows on this screen.** /users # invite user (set-password link email), /users # change role, /users # reset password (confirm dialog), /users # resend invitation, /users # remove user (confirm dialog with team count)

**Navigation.** reached from /settings 'Manage users' (admin); invitation emails → /invite/[token]

**Components / i18n.** AppNav, ConfirmSubmitButton, SubmitButton, Panel, PanelHeader, btnPrimary · en/fr keys users.* (title, subtitle, firmUsers, name, email, role, status, roles.*, statuses.*, you, saveRole, resetPassword, resendInvite, remove, confirmReset/Remove/RemoveTeams '{name}' '{count}', invite, inviteHint, inviteButton, invitedDone '{email}', resetDone, saved, errors.*)

**Odoo 19 target.** Models: res.users (+ groups ea_audit_core.*), res.partner, res.users signup token (auth_signup), ea.audit.team.member, ea.audit.file.item. View: list + form (res.users) with custom role selection field mapped to groups. Groups: ea_audit_core.group_firm_admin (and base.group_erp_manager restricted).

Map the single firm role to exclusive groups via a Selection field 'ea_role' on res.users (compute/inverse to groups_id, implied hierarchy firm_admin > partner > manager = eqr > senior > staff > read_only); invitations via auth_signup reset-password mail (customise template: no password in mail, 14-day expiry); 'remove' = deactivate company membership (multi-company: remove company_ids) + unlink team rows + clear assignments via override; prevent self role-change/removal with constraints; status computed from signup_valid/password set. Session revocation: Odoo invalidates sessions on password change natively.

**Effort / phase.** L (6 pd) (estimate) · 1 Foundation. Source: `app/users/page.tsx`; rules in lib/users.ts, lib/invites.ts, lib/account-mail.ts, lib/email.ts, lib/rbac.ts, app/actions/users.ts. Screenshot: extra\x05-users.png (redirected to /dashboard)

#### C.9.2 `/users # invite user` — Invite a user

**What it is.** Four-field form (name, email, role default staff, Invite) that provisions the account with an unusable random hash and must_change_password, creates the firm membership and emails a one-time set-password link (14 days). Success banner names the email; errors map users.errors.*.

**Rules enforced (plain words).**

- invalid-email, name-required, invalid-role (ASSIGNABLE_ROLES only)
- existing address rules: same firm active or client_user → email-taken
- same firm awaiting link → re-issue
- other firm → email-other-firm
- no firm → readmitted
- no credential in mail
- link single-use, 14-day TTL
- allowed email domains NOT applied here (only to engagement-team invitations)

**Data.** Reads: app_user by email, membership (existing memberships), tenant.name, inviter app_user. Writes: app_user (INSERT or UPDATE readmission), membership (INSERT), user_invite (supersede + INSERT), activity_log 'invited'; email 'invitation' with /invite/<token>.

**Who may do what.** firm_admin only (requireAdmin → canManageFirm)

**Navigation.** panel on /users; → /users?invited=<email>

**Components / i18n.** SubmitButton, Panel, PanelHeader · users.invite, inviteHint, inviteButton, invitedDone '{email}', errors.*

**Odoo 19 target.** Models: res.users (create with auth_signup invitation), res.partner. View: form (quick create) / wizard. Groups: ea_audit_core.group_firm_admin.

Odoo 'Create user' + 'Send an invitation email' (auth_signup) covers it; customise mail template and token validity (auth_signup.reset_password.validity.hours → 14 days); enforce cross-company email rules in create() override (one login never straddles two firms — note Odoo users can be multi-company by design, so this is a policy constraint).

**Effort / phase.** S (1.5 pd) (estimate, included in /users L) · 1 Foundation. Source: `app/users/page.tsx`; rules in lib/users.ts (inviteFirmUser, sendInvitation), lib/invites.ts, lib/account-mail.ts. Screenshot: extra\x05-users.png (redirected to /dashboard)

### C.10 Settings

#### C.10.1 `/security` — Account security (Two-factor authentication)

**What it is.** Per-account two-factor enrolment: when off, shows a freshly minted setup key (formatted secret + otpauth URI) and a confirmation form that returns the 10 recovery codes once into component state; when on, shows the remaining recovery codes and a 'Turn off' form requiring the current password. Links to /change-password. Warns when the staging instance skips the challenge.

**Rules enforced (plain words).**

- MFA enrolment: secret minted on page load (not in URL), encrypted at rest with key scrypt(AUTH_SECRET, 'auditisa.mfa.v1'); nothing enforced until a working code is confirmed (abandoned setup not a factor; re-running replaces unconfirmed secret); already-enrolled / no-enrolment-started / wrong-code refusals
- 10 recovery codes (5 random bytes hex upper) shown once, stored hashed, each spent once (used_at marked, not deleted); disable requires current password (wrong-password); auth-secret-missing when AUTH_SECRET absent; mfaDisabled() notice on non-production DB; unknown ?error → generic text

**Data.** Reads: app_user (totp_secret, totp_enrolled_at, password_hash), mfa_recovery_code (count unused). Writes: app_user.totp_secret (beginEnrolment, AES-256-GCM encrypted), app_user.totp_enrolled_at (confirmEnrolment), mfa_recovery_code (DELETE + 10 INSERT bcrypt hashes; DELETE on disable), app_user totp fields NULL on disable; activity_log (mfa.enrolled, mfa.disabled). Server actions: page-local confirmAction (useActionState) and disableAction → lib/mfa.ts.

**Who may do what.** any signed-in user (auth() only; lib/mfa.ts uses auth()); in practice firm roles (client_user confined to /portal by proxy)

**Sub-flows on this screen.** /security # MFA enrolment (setup key + confirm code → recovery codes), /security # MFA disable (current password)

**Navigation.** reached from /settings 'Account security → Manage'; → /change-password

**Components / i18n.** AppNav, MfaConfirmForm, Panel, PanelHeader · inline fr/en page strings

**Odoo 19 target.** Models: res.users (auth_totp: totp_secret), auth_totp.device, ea.audit.mfa.recovery.code (custom). View: wizard (res.users preferences / auth_totp.wizard). Groups: base.group_user.

Odoo core auth_totp provides enrolment with QR + confirm code and 'trusted devices'; it lacks recovery codes and encrypted secret at rest — add a small custom model for hashed recovery codes and accept Odoo's secret storage or encrypt via a field override. Disable requires password re-auth in Odoo (check_identity) — matches.

**Effort / phase.** M (3 pd) (estimate) · 1 Foundation. Source: `app/security/page.tsx`; rules in lib/mfa.ts, lib/mfa-verify.ts, lib/mfa-policy.ts, lib/totp.ts, components/MfaConfirmForm.tsx. Screenshot: extra\x13-security.png

#### C.10.2 `/security # MFA enrolment` — Turn on two-factor (confirm code → recovery codes)

**What it is.** Client form (useActionState) that submits the six-digit code from the authenticator; on success it renders the 10 recovery codes once in component state (never in the URL) with an 'I have saved these' link back to /security; on failure shows the page-provided message for the code.

**Rules enforced (plain words).**

- wrong-code / already-enrolled / no-enrolment-started refusals
- codes shown once and never again
- code input maxLength 7, numeric

**Data.** Reads: app_user.totp_secret / totp_enrolled_at. Writes: app_user.totp_enrolled_at, mfa_recovery_code (DELETE + 10 INSERT), activity_log mfa.enrolled.

**Who may do what.** the signed-in user for their own account (confirmEnrolment uses auth())

**Navigation.** embedded on /security

**Components / i18n.** MfaConfirmForm · inline fr/en

**Odoo 19 target.** Models: auth_totp wizard (res.users TOTP enable) + ea.audit.mfa.recovery.code. View: wizard. Groups: base.group_user.

auth_totp.wizard handles secret + code confirmation; extend to generate/display hashed recovery codes once.

**Effort / phase.** S (1 pd) (estimate, included in /security M) · 1 Foundation. Source: `components/MfaConfirmForm.tsx`; rules in lib/mfa.ts (confirmEnrolment), components/MfaConfirmForm.tsx. Screenshot: extra\x13-security.png

#### C.10.3 `/settings` — Firm settings

**What it is.** Firm settings hub: Account security link (everyone); admin panels linking to Users, Templates, Audit log, Team workload; Sign-off rules link (partner+); Entity records link; Allowed email domains form (admin); File retention (period form for admin, read-only otherwise, report link manager+); Substantive analytical procedures thresholds (admin); Data integration info; Language switcher; Branding & letterhead form (admin: display name, accent colour with reset, logo upload/remove, letterhead lines, footer, engagement naming convention).

**Rules enforced (plain words).**

- branding: display name required max 160 (MAX_TEXT), accent must be valid hex and pass readability guard (lightness 0.08–0.8 and contrast vs white ≥ MIN_CONTRAST → accent-low-contrast), accent equal to DEFAULT_ACCENT '#047857' or reset stored as null, logo png/jpeg ≤ 150 KB (action) stored as data URI ≤ MAX_LOGO_CHARS (logo-too-large / invalid-logo-type), 'remove + upload' = replace, naming convention default '{CLIENT}_{PERIOD_END}_{NATURE}' stored null when default; retention period integer 10–30 years (RETENTION_MIN/MAX_YEARS, retention-out-of-range), applies only to files archived from now on (retention_until fixed at archive time)
- SAP thresholds integers 1–100 each (sap-threshold-out-of-range) and low ≥ moderate ≥ high (sap-threshold-order), defaults 75/50/25; allowed email domains: parsed from lines/commas/semicolons, '@' tolerated, lower-cased, de-duplicated, each must match domain regex (invalid-email-domain), exact match only (subdomains not implied), empty list = no restriction, applies to engagement-team invitations by email (lib/team.ts addTeamMemberByEmail), not to portal contacts; non-admins see read-only text with settings.adminOnly

**Data.** Reads: tenant (branding jsonb, retention_years, sap_threshold_low/moderate/high_pct, allowed_email_domains). Writes: tenant.branding (updateBrandingAction → lib/branding.ts updateBranding), tenant.retention_years (setRetentionYearsAction → lib/retention.ts), tenant.sap_threshold_* (setSapThresholdsAction → lib/sap.ts), tenant.allowed_email_domains (setAllowedDomainsAction → lib/email-domains.ts), app_user.preferred_language (LanguageSwitcher); activity_log (retention.period_set, email_domains.set).

**Who may do what.** any firm role reads; isAdmin = canManageFirm(role) (firm_admin) for Users/Templates/Audit log/Workload links and the email-domains, retention, SAP and branding forms; Sign-off rules link `atLeast(role, "partner")`; retention report link `atLeast(role, "manager")`; libs: updateBranding requireWrite + canManageFirm, setRetentionYears `requireRole("firm_admin")`, setSapThresholds `requireRole("firm_admin")`, setAllowedDomains `requireRole("firm_admin")`

**Sub-flows on this screen.** /settings # branding & letterhead form (logo upload), /settings # retention period form, /settings # SAP thresholds form, /settings # allowed email domains form, /settings # language switch

**Navigation.** reached from AppNav gear (outside an engagement); → /security, /users, /templates, /settings/signoff, /clients, /settings/audit-log, /resources, /settings/retention

**Components / i18n.** AppNav, ErrorBanner, LanguageSwitcher, Panel, PanelHeader, btnPrimary · en/fr keys settings.* (title 'Firm settings', brandingTitle, displayName, accent, logo, letterhead1/2, footer, naming, emailDomains*, sap*, saved*, adminOnly, language), users.*, templates.*, auditLog.*, resources.*, integrations.*; some panel titles inline fr/en

**Odoo 19 target.** Models: res.company (+ ea_* fields: logo, accent, letterhead1/2, footer, engagement_naming, retention_years, sap_threshold_low/moderate/high, allowed_email_domains), res.config.settings (ea_audit settings view). View: settings (res.config.settings) + company form. Groups: read: base.group_user; write: ea_audit_core.group_firm_admin.

Implement as res.config.settings page in ea_audit_core with related fields on res.company; Python constraints for retention 10–30, SAP 1–100 & ordering, accent hex/contrast, domain regex; logo size check in create/write; chatter tracking on res.company for the audit trail (activity equivalents retention.period_set / email_domains.set). Letterhead fields feed QWeb reports (ea_audit_reports).

**Effort / phase.** M (4 pd) (estimate) · 1 Foundation. Source: `app/settings/page.tsx`; rules in lib/branding.ts, lib/retention.ts, lib/sap.ts, lib/sap-model.ts, lib/email-domains.ts, app/actions/branding.ts, app/actions/retention.ts, app/actions/sap.ts, app/actions/email-domains.ts, lib/rbac.ts. Screenshot: extra\x06-settings.png; other agent: 07-settings-signoff-matrix.png

#### C.10.4 `/settings # branding upload` — Branding & letterhead

**What it is.** Firm identity form: display name, accent colour picker with 'reset to default', logo file upload (PNG/JPEG) with optional remove, two letterhead lines, footer and the engagement naming convention; saving revalidates the whole layout so nav and theme update everywhere.

**Rules enforced (plain words).**

- logo ≤ 150 KB (MAX_LOGO_BYTES) and image/png|image/jpeg (logo-too-large, invalid-logo-type), stored as base64 data URI
- accent hex validated and readability-guarded (accent-low-contrast)
- texts ≤ MAX_TEXT (text-too-long), display name required max 160
- default accent/naming stored as null
- a selected file wins over 'remove'

**Data.** Reads: tenant.branding. Writes: tenant.branding (jsonb merge) via updateBrandingAction → updateBranding.

**Who may do what.** firm_admin only (updateBranding: requireWrite + canManageFirm → BrandingError('forbidden')); non-admins see settings.adminOnly

**Navigation.** panel on /settings; → /settings?saved=1

**Components / i18n.** Panel, PanelHeader, btnPrimary · settings.brandingTitle, brandingHint, displayName, accent, resetAccent, logo, removeLogo, letterhead1/2, footer, naming, namingHint, save, saved

**Odoo 19 target.** Models: res.company (logo, primary/secondary colour, ea_letterhead1/2, ea_footer, ea_engagement_naming). View: settings / company form. Groups: ea_audit_core.group_firm_admin.

res.company.logo (binary) native; add colour and letterhead fields; constraints for size/mimetype/contrast in write(); report layouts (base.document.layout) consume letterhead.

**Effort / phase.** S (1.5 pd) (estimate, included in /settings M) · 1 Foundation. Source: `app/settings/page.tsx`; rules in lib/branding.ts, app/actions/branding.ts. Screenshot: extra\x06-settings.png; other agent: 07-settings-signoff-matrix.png

#### C.10.5 `/settings # retention policy form` — File retention (period)

**What it is.** Single-field form setting the firm's retention period in years for files archived from now on; read-only sentence for non-admins; link to the retention report for manager+.

**Rules enforced (plain words).**

- integer between RETENTION_MIN_YEARS 10 and RETENTION_MAX_YEARS 30 (retention-out-of-range)
- applies prospectively only — an archived engagement keeps its retention_until
- default 10 when unset

**Data.** Reads: tenant.retention_years. Writes: tenant.retention_years via setRetentionYearsAction → setRetentionYears; activity_log retention.period_set.

**Who may do what.** firm_admin (setRetentionYears: requireRole('firm_admin')); report link atLeast manager

**Navigation.** panel on /settings; → /settings?saved=retention; link → /settings/retention

**Components / i18n.** Panel, PanelHeader, btnPrimary · inline fr/en labels; settings.saveRetention, savedRetention, adminOnly

**Odoo 19 target.** Models: res.company.ea_retention_years. View: settings. Groups: ea_audit_core.group_firm_admin.

Integer field with _check constraint 10–30; archive action on engagement stamps retention_until = (report_date or period_end) + years.

**Effort / phase.** S (0.5 pd) (estimate, included in /settings M) · 1 Foundation. Source: `app/settings/page.tsx`; rules in lib/retention.ts (setRetentionYears, stampRetention, retentionDate), app/actions/retention.ts. Screenshot: extra\x06-settings.png; other agent: 07-settings-signoff-matrix.png

#### C.10.6 `/settings/audit-log` — Audit log

**What it is.** Firm-wide activity log (F027): filters (user, engagement or 'firm level', from/to dates, entity type, action), paginated table (at, user + acting role, engagement, entity, action + non-success outcome, summary, before, after values clipped to 160 chars) and a CSV export of the filtered set via /api/settings/audit-log.

**Rules enforced (plain words).**

- AUDIT_LOG_PAGE_SIZE 50
- AUDIT_LOG_EXPORT_MAX 50,000 rows; filters sanitised by cleanFilters (dates /^\d{4}-\d{2}-\d{2}$/, codes /^[a-z0-9_.:-]{1,80}$/i, malformed dropped); engagementId='firm' selects firm-level rows (engagement_id IS NULL); timestamps shown in UTC; before/after JSON rendered via answerText; rendered as 404 for non-admins

**Data.** Reads: activity_log, app_user, engagement, client, membership (listFirmActivity, firmActivityFacets). Writes: —.

**Who may do what.** firm_admin only: page `if (session.user.role !== "firm_admin") notFound()`; lib requireFirmAdmin `ctx.role !== "firm_admin"` → ForbiddenError('firm-admin-only'); API route returns 403

**Sub-flows on this screen.** /settings/audit-log # CSV export

**Navigation.** reached from /settings 'Open the audit log'; → /settings, /api/settings/audit-log?filters (CSV)

**Components / i18n.** AppNav, Panel, btnPrimary · en/fr keys auditLog.* (title, intro, user, engagement, firmLevel, from, to, entity, action, apply, reset, exportCsv, count '{n} {page} {pages}', at, summary, before, after, empty, previous, next), settings.title

**Odoo 19 target.** Models: ea.audit.activity.log (user_id, engagement_id, entity_type, entity_id, action, summary, before_value, after_value, outcome, acting_role, created_at) — or mail.message/mail.tracking.value. View: list (read-only) with filters/group-by + export. Groups: ea_audit_core.group_firm_admin.

Keep a dedicated append-only model (mail.tracking.value does not cover custom action codes or before/after JSON); Odoo list export (xlsx/csv) is native; access rights read-only for firm_admin, create via sudo from business methods; ir.rule by company. Retain the action/entity vocabulary for migration (phase 6 import of existing rows).

**Effort / phase.** M (3 pd) (estimate) · 1 Foundation. Source: `app/settings/audit-log/page.tsx`; rules in lib/audit-log.ts, lib/activity.ts, app/api/settings/audit-log/route.ts. Screenshot: —

#### C.10.7 `/settings/retention` — File retention report

**What it is.** Retention report (UAT B65): the firm's retention period and, for every archived engagement, archived date, retain-until date and status chip (Legal hold / Due for destruction / Retained), with the count of files past expiry without a hold.

**Rules enforced (plain words).**

- retention date = report_date (or period_end when no report) + firm retention years, stamped at archive time (stampRetention) and never shortened retroactively; dueForDestruction = no active legal hold AND retention_until ≤ today; legal hold (manager+ to place with reason, partner+ to release with reason, never a platform operator) suspends destruction
- DB trigger refuses engagement DELETE while held; minimum 10 years (OHADA / ISA 230 practice)

**Data.** Reads: engagement (archived_at, retention_until), client, legal_hold (retentionReport); tenant.retention_years (retentionPolicy). Writes: —.

**Who may do what.** manager and above: page `if (!atLeast(session.user.role as Role, "manager")) redirect("/settings?error=requires-manager")`; lib retentionReport `requireRole("manager")` (eqr_reviewer rank 4 passes atLeast)

**Navigation.** reached from /settings 'Retention report' (manager+); → /settings, /engagements/[id]/conclusion

**Components / i18n.** AppNav, Chip, Panel, PanelHeader · inline fr/en page strings

**Odoo 19 target.** Models: ea.audit.engagement (archived_at, retention_until, held computed), ea.audit.legal.hold (reason, placed_by, released_at, release_reason). View: list (filtered archived engagements) with status badge. Groups: ea_audit_core.group_manager and above (incl. group_eqr).

Filtered list view of engagements (phase=archived) with computed fields retention_status; legal hold model with constraints (one active hold per engagement, reason required); ondelete guard raising when held; destruction itself is not implemented in the current app (no delete path) — keep as report only.

**Effort / phase.** S (2 pd) (estimate) · 2 Engagement file. Source: `app/settings/retention/page.tsx`; rules in lib/retention.ts, lib/rbac.ts. Screenshot: extra\x08-settings-retention.png

#### C.10.8 `/settings/signoff` — Firm sign-off rules

**What it is.** Sign-off governance (F002): (a) policy defaults — minimum reviewer role floor, task codes requiring the partner's sign-off, 'preparer and approver must differ' checkbox, and the permanently disabled sole-practitioner exemption; (b) Excel matrix download and import; (c) per-task table (117 tasks grouped by phase) with minimum preparer, minimum reviewer and partner sign-off selects showing the effective default in brackets.

**Rules enforced (plain words).**

- self-review ban (F001): allow_sole_practitioner always written false and never read by any sign-off path
- team ladder staff < senior < manager < senior_manager < director < partner (eqr_reviewer outside it)
- default matrix by task family: P1–P2 manager/partner, P3–P7 senior/manager, S1–S6 senior/manager, E1–E6 staff/senior except E3.1/E6.3/E6.10 senior/manager, C1–C4 senior/manager, C5–C6 manager/partner
- default partner sign-off on P1.1, P2.2, P5.2, P7.2, S3.1, S6.1, S6.2, C1.1, C6.2, every C5.x plus PARTNER_GATED and PARTNER_ONLY_APPROVAL sets
- effective rule = task rule else matrix raised by policy floor
- reviewer minimum never below preparer minimum
- policy requirePartnerOn codes must exist in index (unknown-task-code)
- ladder role validated (invalid-team-role)
- a per-task 'No' lifts a default partner sign-off
- a row with all three values null is deleted (= firm default)
- only rows the form carried are saved (partial post never resets others)
- matrix import: .xlsx ≤ 1 MB, sheet 'Tasks', read by column position I–K only, header row ignored, blank cell = default, roles accepted by key or FR/EN short/long label, Oui/Non/Yes/No/1/0, unknown code / duplicate / bad role / bad yes-no reported per row, nothing saved unless the whole file is clean
- one engagement partner / partner-tier signature rules (F003) live in lib/signoff-policy.ts and are enforced at sign time

**Data.** Reads: firm_signoff_policy, firm_task_signoff_rule (getPolicy); DEFAULT_FILE_INDEX (lib/file-index, code). Writes: firm_signoff_policy (upsert) via saveSignoffPolicyAction → savePolicy; firm_task_signoff_rule (upsert / delete when all null) via saveTaskRulesAction and importSignoffMatrixAction → saveTaskRules; activity_log (signoff_policy_updated, task_signoff_rules_updated with before/after). API: GET /api/settings/signoff-matrix (xlsx).

**Who may do what.** partner and firm_admin: page `if (!isRole(session.user.role) || !atLeast(session.user.role, "partner")) notFound()`; lib requirePolicyEditor = requireWrite() + `atLeast(ctx.role, "partner")` else ForbiddenError('signoff-policy-partner-only'); download API uses getPolicy (same check)

**Sub-flows on this screen.** /settings/signoff # policy defaults form, /settings/signoff # per-task rules table, /settings/signoff # Excel matrix download, /settings/signoff # Excel matrix import (SignoffMatrixImport, all-or-nothing)

**Navigation.** reached from /settings 'Sign-off rules' (partner+); → /settings, /api/settings/signoff-matrix

**Components / i18n.** AppNav, ErrorBanner, SignoffMatrixImport, SubmitButton, Panel, PanelHeader, btnPrimary · inline fr/en page strings; MATRIX_ROLE_LABELS fr/en; planning.errors.* for refusals; settings.title

**Odoo 19 target.** Models: ea.audit.signoff.policy (one per company: min_reviewer_role, require_partner_on codes, require_distinct_preparer_approver), ea.audit.signoff.rule (code, min_preparer_role, min_reviewer_role, partner_required), ea.audit.file.index (task catalogue). View: settings form + editable list (one2many) + import wizard (xlsx). Groups: ea_audit_core.group_partner, group_firm_admin.

Port DEFAULT_MATRIX and effectiveTaskRule to Python (used by signoff validation in ea_audit_papers); unique (company, code) constraint; wizard for xlsx import (openpyxl) with row-level error report, transactional; xlsx export via report or controller; chatter tracking for before/after. Keep sole-practitioner flag out of the model entirely.

**Effort / phase.** L (6 pd) (estimate) · 1 Foundation. Source: `app/settings/signoff/page.tsx`; rules in lib/signoff-policy.ts, lib/signoff-matrix.ts, lib/file-index.ts, app/actions/signoff-policy.ts, app/api/settings/signoff-matrix/route.ts. Screenshot: extra\x07-settings-signoff.png; other agent: 07-settings-signoff-matrix.png

#### C.10.9 `/settings/signoff # signoff matrix import` — Import a completed matrix (Excel)

**What it is.** useActionState upload form for the sign-off matrix workbook: posts the .xlsx to importSignoffMatrixAction, then shows either 'Matrix imported: N row(s) read, M rule(s) changed' or 'Nothing was saved' with the per-row error list.

**Rules enforced (plain words).**

- file required and non-empty
- ≤ 1 MB
- must be a readable xlsx with a sheet named 'Tasks' (case-insensitive)
- header row skipped
- columns read by position: A code, I min preparer, J min reviewer, K partner Yes/No
- blank = firm default (null)
- unknown task code, duplicate code, unknown role label, bad yes/no reported with Excel row numbers
- all-or-nothing: nothing saved when any row has an error
- returns count of changed rules

**Data.** Reads: firm_signoff_policy, firm_task_signoff_rule (prior rules for diff). Writes: firm_task_signoff_rule (upsert/delete) via saveTaskRules; activity_log task_signoff_rules_updated.

**Who may do what.** partner and firm_admin (requirePolicyEditor → signoff-policy-partner-only)

**Navigation.** panel on /settings/signoff; download counterpart GET /api/settings/signoff-matrix

**Components / i18n.** SignoffMatrixImport · inline fr/en; refusal codes via planning.errors.*

**Odoo 19 target.** Models: ea.audit.signoff.matrix.import (TransientModel with binary file) → ea.audit.signoff.rule. View: wizard. Groups: ea_audit_core.group_partner, group_firm_admin.

openpyxl-based wizard mirroring parseSignoffMatrix (sheet 'Tasks', columns I–K, label lookup FR/EN); export via controller building the same layout with data validation lists. Transactional save.

**Effort / phase.** S (2 pd) (estimate, included in /settings/signoff L) · 1 Foundation. Source: `components/SignoffMatrixImport.tsx`; rules in lib/signoff-matrix.ts, lib/signoff-policy.ts (saveTaskRules, requirePolicyEditor), app/actions/signoff-policy.ts (importSignoffMatrixAction). Screenshot: extra\x07-settings-signoff.png; other agent: 07-settings-signoff-matrix.png

#### C.10.10 `/templates` — Working-paper templates

**What it is.** List of every task code in the default file index with its short title, base template id/version and a Standard/Customised chip, each linking to the editor. Success/error banners after save or reset.

**Rules enforced (plain words).**

- customisations apply only to newly generated papers
- existing documents never change (templates.subtitle)
- customised = override row exists for code

**Data.** Reads: template_override (listOverrides); DEFAULT_FILE_INDEX and templateFor (code constants). Writes: —.

**Who may do what.** firm_admin only: `if (!canManageFirm(session.user.role as Role)) redirect("/dashboard")`; listOverrides requireTenant

**Navigation.** reached from /settings 'Manage templates'; → /templates/[code]

**Components / i18n.** AppNav, Chip, Panel, PanelHeader · en/fr keys templates.* (title, subtitle, list, code, name, base, status, customized, standard, edit, saved '{code}', errors.*)

**Odoo 19 target.** Models: ea.audit.paper.template (code, base template id/version) + ea.audit.paper.template.override (company, code, purpose_en/fr, items_en/fr). View: list. Groups: ea_audit_core.group_firm_admin.

Base templates seeded as data (noupdate) from lib/templates.ts and lib/papers/*; override as company-specific records; list with computed 'customized' badge.

**Effort / phase.** S (1 pd) (estimate) · 3 Papers. Source: `app/templates/page.tsx`; rules in lib/template-overrides.ts, lib/templates.ts, lib/file-index.ts, lib/rbac.ts. Screenshot: extra\x10-templates.png (redirected to /dashboard)

#### C.10.11 `/templates/[code]` — Firm customisation (template editor)

**What it is.** Editor for one task's working-paper template override: purpose (EN/FR) and item lists (EN/FR, one per line) with the base template text as placeholders; Save and, when an override exists, Reset to standard.

**Rules enforced (plain words).**

- code must exist in DEFAULT_FILE_INDEX (invalid-code / 404)
- blank fields fall back to the base template (templates.blankHint)
- saving all-blank removes the override
- items split by line, trimmed, empty lines dropped
- overrides apply to newly generated papers only

**Data.** Reads: template_override (listOverrides), DEFAULT_FILE_INDEX, templateFor(code). Writes: template_override (DELETE then INSERT; DELETE on reset) via app/actions/templates.ts saveTemplateAction / resetTemplateAction → lib/template-overrides.ts.

**Who may do what.** firm_admin only: `if (!canManageFirm(session.user.role as Role)) redirect("/dashboard")`; lib saveOverride/resetOverride requireAdmin → canManageFirm else TemplateError('forbidden')

**Sub-flows on this screen.** /templates/[code] # save override, /templates/[code] # reset to standard

**Navigation.** reached from /templates 'Edit'; → /templates?saved=<code>

**Components / i18n.** AppNav, Panel, PanelHeader, btnPrimary · en/fr keys templates.* (backToList, editHint, editorTitle, purposeEn/Fr, itemsEn/Fr, blankHint, save, reset, errors.*)

**Odoo 19 target.** Models: ea.audit.paper.template.override. View: form. Groups: ea_audit_core.group_firm_admin.

Form on the override model with translatable Text fields (purpose, items as Text one-per-line or One2many lines); 'reset' = unlink. Generation code in ea_audit_papers must read override-then-base (applyOverride).

**Effort / phase.** S (1 pd) (estimate) · 3 Papers. Source: `app/templates/[code]/page.tsx`; rules in lib/template-overrides.ts, app/actions/templates.ts. Screenshot: —

### C.11 Admin

#### C.11.1 `/admin` — Platform admin console

**What it is.** Platform operator console (super admin): table of every audit firm (name, slug, sending address <mail_local>@<domain>, users, clients, engagements, created) with a type-the-slug-to-confirm Delete form (hidden for the protected operator-home tenant); table of platform administrators with Remove (not self) and an 'Add an administrator' form; and the four-step FirmOnboardingWizard (firm name/slug, administrator, sending address, review) with live availability checks.

**Rules enforced (plain words).**

- super-admin gate on every action (server actions are public endpoints); firm onboarding: name, slug and valid admin email required (fields-required), slug normalised (slugify: NFD strip accents, lower, [a-z0-9-], max 48), slug unique (slug-taken), mail_local defaults to slug and must match ^[a-z0-9._-]{1,64}$ (bad-mail-local) and be unique case-insensitively (mail-local-taken), language en/fr default fr; temporary password 24 random bytes base64url, bcrypt cost 10, only ever leaves by email, never returned/logged (Phase 0 item 1); existing account keeps its password (emailed=false); forced password change at first sign-in; add admin: email regex (admin-fields-required), already-admin refused, membership-less accounts seated as firm_admin in the protected operator-home tenant (no-operator-home if none); remove admin: cannot-remove-self (never zero operators), admin-not-found, sessions revoked, operator-home membership released; delete firm: confirmation slug must equal tenant slug (confirm-mismatch)
- DB policy refuses firm-has-archived-files (ISA 230 retention), firm-has-legal-hold, firm-holds-operator-membership, firm-protected (protected tenant cannot be deleted); accounts whose only firm it was go with it, others survive; app DB role holds no DELETE on tenant (function is SECURITY DEFINER); wizard: nothing written before the last step, steps 0 and 2 confirm uniqueness server-side before advancing

**Data.** Reads: tenant (all), membership (counts), per-tenant client/engagement counts under each tenant's RLS (listFirms); app_user where is_super (listPlatformAdmins); tenant/app_user existence checks (checkAvailability). Writes: tenant (INSERT name, slug, default_language, mail_local) + app_user (INSERT must_change_password=true or reuse) + membership (firm_admin) via createFirm; app_user (INSERT is_super/must_change or UPDATE is_super) + membership in protected tenant via addPlatformAdmin; app_user (is_super=false, session_version+1) + membership DELETE in protected tenant via removePlatformAdmin; whole tenant data via DB function admin_delete_firm (SECURITY DEFINER) in deleteFirm; emails 'firm-onboarded' / 'admin-access' (platformSender). Page-local server actions: createFirmAction, deleteFirmAction, addAdminAction, removeAdminAction, checkAvailabilityAction.

**Who may do what.** super admins only: page `if (!session.user.isSuper) redirect("/dashboard")`; every lib call requireSuper() (`session.user.isSuper` else AdminError('forbidden')) — the firm role is irrelevant

**Sub-flows on this screen.** /admin # FirmOnboardingWizard (4 steps, availability pre-flight), /admin # delete firm (type slug to confirm), /admin # add platform administrator, /admin # remove platform administrator

**Navigation.** reached from AppNav 'Platform' link and /dashboard operator notice (isSuper); not linked otherwise

**Components / i18n.** AppNav (hideLinks), FirmOnboardingWizard, Panel, PanelHeader · inline fr/en page and wizard strings

**Odoo 19 target.** Models: res.company (one per firm, slug, mail_local, protected flag, default_language), res.users (is_super → base.group_system or custom ea_audit_core.group_platform_admin), res.company deletion wizard. View: list + form (res.company) + wizard (onboarding, delete-with-confirmation). Groups: ea_audit_core.group_platform_admin (super users; distinct from firm_admin).

Multi-company Odoo: each firm = res.company with strict record rules on every ea.audit.* model (company_id). Onboarding wizard creates company + admin user (auth_signup invitation instead of temp password, or keep temp password with must_change flag); company deletion in Odoo is normally refused — implement guarded unlink override checking archived engagements / legal holds / protected flag, or replace by 'deactivate company'. mail_local → company email alias (mail.alias domain). Pre-flight checks = SQL unique constraints + onchange.

**Effort / phase.** L (7 pd) (estimate) · 1 Foundation. Source: `app/admin/page.tsx`; rules in lib/admin.ts, lib/account-mail.ts, lib/email.ts, components/FirmOnboardingWizard.tsx, db (admin_delete_firm function via migrations). Screenshot: extra\x15-admin.png (redirected to /dashboard)

#### C.11.2 `/admin # FirmOnboardingWizard` — Onboard an audit firm (4 steps)

**What it is.** Client-side 4-step wizard (0 the firm: name + slug auto-derived; 1 the administrator: name, email, default language; 2 sending address local part; 3 review) that writes nothing until the final submit. Steps 0 and 2 call checkAvailabilityAction before advancing so slug / mail collisions surface early; going back is allowed, forward only past a valid step.

**Rules enforced (plain words).**

- step validity: firm name required, slug non-empty and not taken
- admin name required and email matches EMAIL_RE
- mail local part [a-z0-9._-] only and not taken
- existing admin email → 'keeps their password' (emailExists)
- server re-checks all constraints inside the transaction (wizard pre-flight never replaces them)
- nothing written before step 3

**Data.** Reads: tenant (slug, mail_local), app_user (email exists) via checkAvailability. Writes: tenant, app_user, membership via createFirm (see /admin); email firm-onboarded.

**Who may do what.** super admins only (checkAvailability and createFirm both call requireSuper())

**Navigation.** embedded on /admin; success → /admin?ok=created(-emailed)

**Components / i18n.** FirmOnboardingWizard · inline fr/en wizard strings

**Odoo 19 target.** Models: ea.audit.firm.onboarding.wizard (TransientModel) → res.company + res.users. View: wizard (multi-step TransientModel form). Groups: ea_audit_core.group_platform_admin.

TransientModel with state field for steps, onchange-based availability checks (search on res.company.slug / mail_local, res.users.login), final action_create. OWL not required.

**Effort / phase.** M (3 pd) (estimate) · 1 Foundation. Source: `components/FirmOnboardingWizard.tsx`; rules in components/FirmOnboardingWizard.tsx, lib/admin.ts (checkAvailability, createFirm, slugify). Screenshot: extra\x15-admin.png (redirected to /dashboard)

#### C.11.3 `/admin # delete firm` — Delete firm (type slug to confirm)

**What it is.** Inline per-row destructive flow: the operator types the firm's exact slug in a confirmation field and submits; the server verifies the slug and calls the SECURITY DEFINER database function admin_delete_firm, which applies the deletion policy and removes the tenant with all its data and the accounts that belonged only to it. Hidden for the protected operator-home tenant.

**Rules enforced (plain words).**

- confirm-mismatch when typed slug differs
- protected tenant cannot be deleted (firm-protected)
- refused when the firm has archived audit files (firm-has-archived-files, ISA 230 retention), an engagement under legal hold (firm-has-legal-hold), or holds the platform operator's only membership (firm-holds-operator-membership)
- accounts also belonging to another firm survive
- app DB role has no DELETE on tenant

**Data.** Reads: tenant.slug. Writes: tenant and every tenant-scoped table, membership, orphaned app_user rows (via admin_delete_firm).

**Who may do what.** super admins only (deleteFirm → requireSuper())

**Navigation.** row control on /admin; → /admin?ok=deleted or ?error=<code>

**Components / i18n.** — · inline fr/en messages for each refusal code

**Odoo 19 target.** Models: res.company (unlink override / deactivate wizard), ea.audit.engagement, ea.audit.legal.hold. View: wizard (confirmation TransientModel). Groups: ea_audit_core.group_platform_admin.

Odoo discourages deleting companies; implement a confirmation wizard requiring the slug, with unlink() override raising UserError for the four refusal conditions; alternatively archive the company (active=False) and purge via a scheduled job. Decision needed in migration spec.

**Effort / phase.** S (2 pd) (estimate) · 1 Foundation. Source: `app/admin/page.tsx`; rules in lib/admin.ts (deleteFirm), migrations (admin_delete_firm SQL function). Screenshot: extra\x15-admin.png (redirected to /dashboard)

#### C.11.4 `/uat` — Acceptance test workbook

**What it is.** In-app UAT workbook for the dev/staging instance: progress summary for the signed-in tester, selector of the engagement the scenario links point at, section index, and for every scenario (lib/uat-scenarios.ts) the steps, expected result, an 'Open the screen' link and a form to record a verdict (not started / works / does not work / could not test) with notes; other testers' answers shown underneath.

**Rules enforced (plain words).**

- UAT page dev-only: available only when the database name matches /_(dev|staging|test|local)$/ (lib/instance.ts
- production is ea_audit) — fails closed
- scenario key must exist in ALL_SCENARIOS (unknown-scenario)
- status in not_started/passed/failed/blocked (invalid-status)
- notes truncated to 4000 chars
- one answer per (user, scenario), others' answers visible
- progress counted over own answers
- timestamps shown in Africa/Douala time

**Data.** Reads: uat_result JOIN app_user (listResults); engagement, client, team_member … (listEngagements for the link selector). Writes: uat_result (upsert on (user_id, scenario_key): status, notes, updated_at) via page-local saveAction → lib/uat.ts recordResult.

**Who may do what.** any firm role on a non-production instance (`if (!uatAvailable()) notFound()`; listResults/recordResult use requireTenant — read_only is not refused by the lib, only by the proxy's mutation rule, which lets page server actions through; ambiguity noted); absent (404) on production

**Sub-flows on this screen.** /uat # record scenario verdict

**Navigation.** direct URL /uat (not linked in nav); scenario links → the screens under test

**Components / i18n.** AppNav, SubmitButton, Panel, PanelHeader · inline fr/en page strings; scenario texts from lib/uat-scenarios.ts

**Odoo 19 target.** Models: ea.audit.uat.scenario (data), ea.audit.uat.result (user, scenario, status, notes) — optional. View: kanban / list (or drop). Groups: base.group_user on staging only (ir.config_parameter flag).

Candidate to drop or keep as a tiny optional module 'ea_audit_uat' installed only on staging DB; scenario catalogue (lib/uat-scenarios.ts) becomes data records; per-user result upsert = unique (user, scenario). Not part of production cutover.

**Effort / phase.** S (2 pd) (estimate) · 6 Migration & cutover. Source: `app/uat/page.tsx`; rules in lib/uat.ts, lib/uat-scenarios.ts, lib/instance.ts. Screenshot: extra\x14-uat.png

### C.12 Portal

#### C.12.1 `/portal` — Client portal — Documents requested by your auditor

**What it is.** The client user's only surface (spec §2.3): the auditor firm's branding, a sign-out button and the list of PBC (prepared-by-client) requests across the client's engagements with status (requested / uploaded / accepted), note, uploaded filename and an upload form for items not yet accepted. Never shows the audit file.

**Rules enforced (plain words).**

- portal confinement (client_user never reaches firm routes
- firm users redirected off /portal)
- clientId taken from session, argument must equal it (not-your-client)
- file required (file-required), non-empty (empty-file), ≤ MAX_PBC_BYTES 25 MB (file-too-large)
- upload-safety allowlist + byte-signature check (lib/upload-safety.ts checkUpload
- executables and mismatched extensions refused → file-type)
- stored name/MIME derived from bytes not client claim
- only items with status != 'accepted' accept uploads (re-upload replaces)
- status transition requested → uploaded (→ accepted by firm senior+ on the engagement PBC page)
- team notified in-app
- proxy allows client_user mutations only on /portal paths (ownPortalAction)

**Data.** Reads: pbc_item JOIN engagement JOIN client (listPortalItems, filtered e.client_id = session clientId), tenant.branding (getPortalBranding). Writes: pbc_item (status='uploaded', filename, mime, content bytea, uploaded_by, uploaded_at) via app/actions/pbc.ts uploadPbcAction → lib/pbc.ts uploadPbc; activity_log (pbc_uploaded, acting_role client_user, sha256 meta) written directly; notification (kind pbc-uploaded) to every team_member of the engagement.

**Who may do what.** client_user only: `if (session.user.role !== "client_user" || !session.user.clientId) redirect("/dashboard")`; loaders use requirePortalUser() (firm staff refused 'not-a-portal-account'); proxy confines client_user to /portal and refuses all firm APIs 403

**Sub-flows on this screen.** /portal # PBC file upload

**Navigation.** reached after client_user sign-in (proxy redirect); sign-out → /login

**Components / i18n.** ErrorBanner (GatesPanel) · en/fr keys portal.* (title, signOut, welcome, empty, uploaded, upload, statuses.*); ErrorBanner planning.errors.*

**Odoo 19 target.** Models: ea.audit.pbc.item (state requested/uploaded/accepted, attachment_id), res.partner (client contact), res.users portal, ir.attachment. View: portal (website portal template /my/pbc). Groups: base.group_portal (record rule: pbc items of the partner's commercial partner / client).

Odoo portal controller (ea_audit_portal) extending portal.CustomerPortal: list PBC items, upload via portal form; record rules restrict ea.audit.pbc.item to the portal partner's client; file validation (size 25 MB, mimetype/magic allowlist) in controller; message_post + mail.activity to team on upload; company branding via website/company. Portal users have no access to engagement models (no record rule grants).

**Effort / phase.** M (5 pd) (estimate) · 5 Reports/portal/legal. Source: `app/portal/page.tsx`; rules in lib/pbc.ts, lib/upload-safety.ts, lib/tenant.ts (requirePortalUser), lib/branding.ts (getPortalBranding), app/actions/pbc.ts, proxy.ts. Screenshot: extra\x18-portal-redirect.png (redirected to /dashboard)

### C.13 Working-paper definitions (lib/papers)

The task papers rendered by `/engagements/[id]/sections/[itemId]` are defined declaratively. One line per paper; the Odoo port loads these definitions as data for the OWL paper component (section E).

| Code | Title | Kind | Fields | Special widgets / logic | Tool feed | Sign-off notes |
| --- | --- | --- | --- | --- | --- | --- |

| C1.1 | Summary of Audit Differences | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid TB + approved materiality + SAD conclusion (form_response code 'sad', field concl_text) | default matrix min preparer=senior, min reviewer=manager; partner signature required=True; PARTNER_ONLY_APPROVAL (a reviewer sign-off is refused unless by the engagement partner/delegate); tool-fed: every sign-off refused until the tool output exists (F004) |

| C1.2 | Summary Review Memorandum | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | SrmMattersPanel (significant matters read from findings, misstatements, risks)  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| C1.3 | Consultation Record | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| C2.1 | Final Overall Financial Statement Review (ISA 520) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| C2.2 | Subsequent Events Review (ISA 560) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| C3.1 | Management Representation Letter(s) (ISA 580) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| C4.1 | Review and Approval Summary | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| C4.2 | Engagement Quality Review | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | EQR chip (signOffEqrAction); EQR_C42_KEYS writable only by the appointed EQR, the other keys locked for the EQR  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False; EQR's own paper: 'eqr' sign-off by the appointed EQR only; team P/R attest the governance communications; completion gate eqr_complete reads the eqr sign-off + q_complete/q_resolved |

| C4.3 | Points Outstanding | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | open review notes list (from archive checklist review_notes_cleared)  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| C5.1 | Opinion and auditor's report (ISA 700–706) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True |

| C5.2 | Statutory Deadlines Calendar | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True |

| C5.3 | Regulated Agreements Register & Special Report | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True |

| C5.4 | Article 715 Report to the Board | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True |

| C5.5 | Alert Procedure File | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True |

| C5.6 | Disclosure of Criminal Offences to the Prosecutor | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True |

| C5.7 | Registered Securities Register Attestation | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True |

| C5.8 | Equity vs Half-of-Share-Capital Monitoring | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | equity monitor strip (art. 664) read from /legal; save refused 'c58-equity-contradicts' when q_above=yes but figures show a breach  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True |

| C5.9 | Joint Auditor Coordination File | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True |

| C5.10 | Article 525 Certification — Highest-Paid Persons' Remuneration | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True |

| C5.11 | Communications with those charged with governance and management (ISA 260/265) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | DeficiencyEvaluationPanel embed (ISA 265 grid fed from the findings register; saveDeficiencyEvaluationAction)  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True |

| C6.1 | Archive Checklist — Gates and Open Items | archive checklist (board) + Yes/No judgement | — | ArchiveChecklist embed (archive gates and open items with fix links)  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=False |

| C6.2 | Complete Documentation and Archive Engagement | archive checklist (board) + Yes/No judgement | — | ArchiveChecklist embed with the Archive button (partner only, all gates green) and roll-forward  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True |

| C6.2 | Complete Documentation and Archive Engagement | archive checklist (board) + Yes/No judgement | — | ArchiveChecklist embed with the Archive button (partner only, all gates green) and roll-forward  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True |

| E1.1 | ITGC Testing | questionnaire + offline workbook template | — | ITGC workbook template (wp-templates itgc-e11) + /api/engagements/[id]/itgc/export; four IT domains, select fields  | what-can-go-wrong (declared tools; TL badge on header) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False |

| E1.2 | Test Controls over Significant Classes of Transactions | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | TocBoard embed (tests of controls by SCOT) + pre-filled E1.2 .xlsx export (/api/engagements/[id]/toc/export)  | - | default matrix min preparer=staff, min reviewer=senior; partner signature required=False |

| E2.1 | Update Tests of Controls and ITGCs (post-interim) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=staff, min reviewer=senior; partner signature required=False |

| E3.1 | Tests of Journal Entries & Mandatory Fraud Procedures (ISA 240) | questionnaire + offline workbook template | — | je-testing workbook template; JE engine results; senior/manager minimums  | journal-entry-testing (declared tools; TL badge on header) | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| E4.1 | Trade Receivables (E) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.2 | Trade Payables (N) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.3 | Inventories (F) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.4 | Property, Plant & Equipment (K) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.5 | Intangible Assets (L) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.6 | Financial Assets (J) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.7 | Cash & Cash Equivalents (C) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.8 | Borrowings (Q) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.9 | Share Capital & Reserves (T) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.10 | Provisions for Risks & Charges (P1) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.14 | Tax Receivables (O1) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.15 | Tax Payables (O2) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.23 | Exceptional Income (U1) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.26 | Personnel Costs (VB) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.33 | Exceptional Expenses (V1) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.34 | Income Tax (O4) | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | valid current-year trial balance (lead schedule) | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.35 | Leases | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E4.36 | Cash Flow (TFT) Tie-out | account workpaper (lead schedule + PSP program from the S5.5 design + Part A/B/C paper) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=staff, min reviewer=senior; partner signature required=False; completeness exempt (E4 account paper); section conclusion must be reviewed before R (review-conclusion-first) |

| E6.1 | Laws & Regulations / NOCLAR (ISA 250) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=staff, min reviewer=senior; partner signature required=False |

| E6.2 | Related Parties (ISA 550) | register + questionnaire | — | RelatedPartyRegister side register (shared with S4.3)  | - | default matrix min preparer=staff, min reviewer=senior; partner signature required=False |

| E6.3 | Going Concern (ISA 570) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| E6.4 | Minutes & Statutory Records | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=staff, min reviewer=senior; partner signature required=False |

| E6.5 | Opening Balances & Comparatives (ISA 510/710) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=staff, min reviewer=senior; partner signature required=False |

| E6.6 | Subsequent Events (ISA 560) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=staff, min reviewer=senior; partner signature required=False |

| E6.7 | Accounting Estimates (ISA 540) | register + questionnaire | — | EstimatesRegister side register (shared with S4.4)  | - | default matrix min preparer=staff, min reviewer=senior; partner signature required=False |

| E6.8 | Reassess Combined Risk Assessments | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=staff, min reviewer=senior; partner signature required=False |

| E6.9 | Litigation & Claims (ISA 501) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=staff, min reviewer=senior; partner signature required=False |

| E6.10 | Financial Statement Procedures (tie-out of accounts and notes) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | FS tie-out board (runFsTieout: TB balanced, bilan = CR result, client FS diffs); save refused 'tieout-unexplained' when q_n_agrees=yes with unexplained differences  | sad, lead-schedule (declared tools; TL badge on header) | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| P1.1 | Consider Client Acceptance / Continuance Results | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | legacy /forms/P1.1 form (acceptance gate: complete, conclusion=accept, P11 checks) and the working paper  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True; PARTNER_GATED (phase gate reads the partner signature; the engagement partner's R is recorded as partner; reviewer R does not lock the paper) |

| P1.2 | Predecessor Auditor Communication (ISA 300 / IESBA §320) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=False |

| P1.3 | Preconditions for an Audit (ISA 210) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=False |

| P1.4 | Engagement Letter (ISA 210) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=False |

| P1.5 | Engagement Quality Review Determination (ISQM 1/2) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=False |

| P2.1 | Independence and Ethics Conclusion (IESBA Code) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=False |

| P2.2 | Assess the Team and Determine Need for Specialised Skills | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=True; PARTNER_GATED (phase gate reads the partner signature; the engagement partner's R is recorded as partner; reviewer R does not lock the paper) |

| P2.3 | Audit Scope and Components (ISA 600) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=manager, min reviewer=partner; partner signature required=False |

| P3.1 | Understand the Business — the Entity, its Environment and the Applicable Framework (ISA 315) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| P3.2 | Analytical Risk Assessment Procedures | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | trial-balance, analytics (declared tools; TL badge on header) | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| P4.1 | Assess Internal Control at the Entity Level | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| P4.2 | Control Environment Assessment | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| P4.3 | Understand the IT Environment and Determine IT Involvement | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| P5.1 | Identify Fraud Risks and Determine Responses (ISA 240) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| P5.2 | Engagement Team Discussion | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | potential risks raised from tasks feed the Risk Console; /forms/P5.2 redirects to the working paper  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=True; PARTNER_GATED (phase gate reads the partner signature; the engagement partner's R is recorded as partner; reviewer R does not lock the paper); PARTNER_ONLY_APPROVAL (a reviewer sign-off is refused unless by the engagement partner/delegate) |

| P6.1 | Determine Materiality — Overall, Performance and Clearly Trivial (ISA 320) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | approved-materiality strip + auto 'benchmark' field from the materiality tool; header tool chip -> tools/materiality  | materiality tool (approved version required) | default matrix min preparer=senior, min reviewer=manager; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004) |

| P6.2 | Identify Significant Accounts, Disclosures and Relevant Assertions | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | SignificantAccounts grid (fold) via /api/engagements/[id]/significance; sign-off refused while significance-unjustified  | valid TB + approved materiality (significance grid) | default matrix min preparer=senior, min reviewer=manager; partner signature required=False; tool-fed: every sign-off refused until the tool output exists (F004); significance-unjustified refusal |

| P7.1 | Report to Those Charged with Governance - Audit Planning | checklist (Yes/No items + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S1.1 | Identify Significant Classes of Transactions and Related Applications | register (SCOT register) + questionnaire | — | ScotRegister embed (SCOT register: add/assign/link index/strategy) via /api/engagements/[id]/scots  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S1.2 | Understand Flows of Transactions, WCGWs and Controls | board/embed-driven working paper (embedOnly) | — | WcgwBuilder mode=wcgw (flows, WCGWs, controls), embedOnly; sign-off needs embeddedWorkGap clear  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False; completeness exempt, embeddedWorkGap checked instead |

| S1.3 | Perform Walkthroughs | board/embed-driven working paper (embedOnly) | — | WalkthroughBoard embedOnly (WALKTHROUGH_KEYS answered per SCOT)  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False; completeness exempt, embeddedWorkGap checked instead |

| S1.4 | Understand and Evaluate the FSCP | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | FscpForm embed (close-process form, form_response code 'fscp')  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S2.1 | Select Controls to Test | board/embed-driven working paper (embedOnly) | — | WcgwBuilder mode=select (select controls to test) embedOnly; control-without-wcgw refused  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False; completeness exempt, embeddedWorkGap checked instead |

| S2.2 | Design Tests of Controls | board/embed-driven working paper (embedOnly) | — | WcgwBuilder mode=design (design tests of controls, sampling link) embedOnly  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False; completeness exempt, embeddedWorkGap checked instead |

| S2.3 | Understand ITGCs (IT General Controls) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | ItAppsBoard editable (IT applications and strategy per application); sign-off refused while any app strategy undecided (itapp-strategy-missing)  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False; itapp-strategy-missing refusal |

| S2.4 | Design & Execute Tests of ITGCs | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | sampling (declared tools; TL badge on header) | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S2.5 | Evaluate ITGCs | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | ItAppsBoard read-only (S2.3 decisions)  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S3.1 | Make Combined Risk Assessments (Risk Register) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | CraBoard embed (IR x CR per relevant assertion, key-item threshold, reassessment history), wide layout; 'rely' needs a selected control covering the assertion or a written basis  | what-can-go-wrong, strategy (declared tools; TL badge on header) | default matrix min preparer=senior, min reviewer=manager; partner signature required=True; PARTNER_GATED (phase gate reads the partner signature; the engagement partner's R is recorded as partner; reviewer R does not lock the paper); PARTNER_ONLY_APPROVAL (a reviewer sign-off is refused unless by the engagement partner/delegate) |

| S4.1 | Commitments & Contingencies | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S4.2 | Going Concern — Preliminary (ISA 570) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | TriggerPanel (legacy S4.2 form fields)  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S4.3 | Related Parties (ISA 550) | register + questionnaire | — | RelatedPartyRegister side register (shared with E6.2)  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S4.4 | Accounting Estimates — Planning (ISA 540) | register + questionnaire | — | EstimatesRegister side register (shared with E6.7)  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S5.1 | Reliance on Experts (ISA 620) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S5.2 | Service Organisations (ISA 402) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S5.3 | Internal Audit (ISA 610) | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S5.4 | Design Tests of Journal Entries and Other Mandatory Fraud Procedures | form (fields + conclusion) | — | auto 'je_design' field from the JE selection engine (+ dated history)  | je-selection (declared tools; TL badge on header) | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S5.5 | Design Substantive Procedures | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | DesignProceduresBoard embed (nature/timing/extent per assertion, other substantive procedures list), wide layout; nature/timing options constrained by the CRA level  | sampling (declared tools; TL badge on header) | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S5.6 | Plan General Audit Procedures | questionnaire (numbered procedures + Yes/No evaluation + conclusion) | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=False |

| S6.1 | Prepare Audit Strategies Memorandum | memorandum (audit strategies) questionnaire | — | TriggerPanel (legacy S6.1 yes/no triggers activating P4.2/P4.3/S5.1/S5.2/S5.3) + auto 'context' (approved materiality + risk counts)  | materiality, strategy (declared tools; TL badge on header) | default matrix min preparer=senior, min reviewer=manager; partner signature required=True; PARTNER_ONLY_APPROVAL (a reviewer sign-off is refused unless by the engagement partner/delegate) |

| S6.2 | Direction from the Engagement Partner | memorandum (audit strategies) questionnaire | — | PaperWizard pages (read-only status page, questionnaire pages, conclusion + key findings last); N/A with reason on every item/procedure (F040); practical tips rail; review notes; attachments; linked tasks  | - | default matrix min preparer=senior, min reviewer=manager; partner signature required=True; PARTNER_ONLY_APPROVAL (a reviewer sign-off is refused unless by the engagement partner/delegate) |



## D. The business-rules engine as a whole

This section describes the rules that the current code enforces, where each one lives today, and how each becomes an Odoo mechanism. The mapping follows one principle: **every rule that today lives in a TypeScript function guarding a SQL write becomes a Python check that runs inside the Odoo ORM (`@api.constrains`, overridden `write()`/`create()`, or a model method called by a button), never only in the view.** Odoo's record rules (`ir.rule`) replace the Postgres row-level-security policies, and Odoo groups replace the rank table in `lib/rbac.ts`.

### D.1 The audit file index (`lib/file-index.ts`, `lib/task-groups.ts`, `lib/complexity.ts`)

**What exists today.** `DEFAULT_FILE_INDEX` lists 118 task codes in six storage sections (A Financial statements, B Completion, C Communication, D Acceptance & planning, E Execution, F OHADA legal). Each entry has an English and a French title, a tier resolved by `tierOf` from the entry's own flag and the `CORE_CODES` and `EXTENDED_CODES` sets (`core` = every engagement, about 50 codes; `standard` = non-complex and complex; `extended` = complex only, 7 codes: P2.3, C4.2, E4.6, E4.12, E4.13, C5.5, C5.9) and an optional `conditional` flag (11 entries: P1.2, P4.2, P4.3, S5.1, S5.2, S5.3 and E5.1–E5.5; they are only *activated* when a trigger answers "yes", and no code was found that activates E5.1–E5.5). The numbering gaps (no D2, no D5.3) are intentional. `lib/task-groups.ts` is the presentation layer: four display phases (Planning & Risk Identification = acceptance, Strategy & Risk Assessment, Execution, Conclusion & Reporting), each split into task groups (P1…P7, S1…S5, E1…E6, C1…C6) with the gate each phase closes against (G1…G6). Internal codes (P1.1, E4.1, C1.1 …) are the storage keys in `file_item.code`.

**Complexity classification** (`lib/complexity.ts`): seventeen yes/no questions answered in the engagement creation wizard. Three are knock-outs (`listed`, `publicInterest`, `group` → complex). The rest carry weights 1 or 2 (jointAudit 2, foreignOps 2, complexFinancing 2, complexRevenue 2, estimates 2, controlsReliance 1, complexIt 1, multiLocation 1, largeSize 2, firstAudit 1, goingConcern 2, relatedParties 1, restructuring 2, litigation 2). Score ≥ 8 → complex; ≥ 3 → non-complex; otherwise very simple. The level selects the tasks through `itemsForComplexity` (very simple: 49 tasks, core and not conditional; non-complex: 111; complex: 118). `applyComplexity` in `lib/engagements.ts` only inserts missing codes, so a re-assessment on the *Nature* screen adds tasks and never removes any.

**Odoo target.**
- `ea.audit.task.template` (data model loaded from XML/CSV): code, section, title (translatable field, `translate=True`), tier (Selection core/standard/extended), conditional (Boolean), group (Many2one `ea.audit.task.group`), sequence, trigger expression (which paper field activates it).
- `ea.audit.task.group`, `ea.audit.phase` (data).
- `ea.audit.file.item` (one row per task per engagement, = `file_item`): template_id, engagement_id, code (related, stored), state (not_started / in_progress / prepared / reviewed / signed), `conditional` (Boolean, True while the trigger is unanswered), `not_applicable`, `material` (E-section), assignee_id, approver_id, due_date, `tool_fed` (computed).
- `ea.audit.complexity.question` (data, 17 rows with weight and knock-out flag) and a `classify()` method on `ea.audit.engagement` reproducing the thresholds 8 / 3. The wizard (`ea.audit.engagement.create.wizard`, TransientModel) previews the level live via an `@api.onchange`.
- Instantiation = `engagement._instantiate_file_index()` called from `create()`; re-assessment = server action on the engagement form.

### D.2 Phases and gates (`lib/gates.ts`, `lib/completion.ts`, `lib/archive-checklist.ts`)

**Phase ladder.** `engagement.phase` ∈ acceptance(0) → planning(1) → execution(2) → conclusion(3) → archived(4). Transitions run *gate check + mutation in one transaction with the engagement row locked* (`SELECT … FOR UPDATE`), so two users cannot advance twice. Every transition writes an `activity_log` row ("phase_advanced") after commit.

**Gate 1 — acceptance → planning** (`advanceToPlanning`): P1.1 form complete and concluded "accept" (`d31_form_complete`); P1.1 automated checks pass (`d31_checks_passed`, `p11FailedChecks`); P1.1 signed by the partner (or by the reviewer where the firm's rule for P1.1 lifts the partner requirement — `approvalSigned`); exactly one accepted engagement partner on the team (`engagement_partner_designated`); no open review note on P1.x papers. F008 (2026-10-27): there is **no** independence-confirmation gate any more — declarations are obtained outside the system and filed on P2.1.

**Gate 2 — planning → execution** (`closePlanning`): latest materiality version approved; partner (or effective-rule) signature on P2.2, P5.2, S3.1 (only where the task is active on this file); P7.2 planning summary approved by the partner through the RAS (`rasPartnerApprovedTx`, every confirmation and deliverable ticked); every significant non-rebutted risk linked to ≥ 1 program step; every rebutted presumed revenue-fraud risk carries a partner-approved rebuttal; every material E-section has at least one planned program step (stand-back); every account of the current TB version maps to a SYSCOHADA grouping rule or a client override (`tb_mapped`); no open review note on any P or S paper; every CRA cell assessed "rely" rests on a control selected for testing that covers the assertion, or on a written basis (`cra_reliance_supported`). Closing takes a **planning snapshot** (materiality + risks + program steps as JSON into `planning_snapshot`).

**Later-phase work is blocked while an earlier phase is open** (`phaseStillOpen`): a task of phase X cannot be signed while the engagement is in a lower phase; completion papers C1–C5 open from execution, only C6.1/C6.2 (post-report) wait for the report.

**Report issuance** (`issueReport`): only a user with `canPartnerSignoff` AND the designated engagement partner or delegate; phase execution or conclusion; not already issued; all twelve **completion gates** pass (`sections_concluded`, `risks_concluded`, `b5_within_materiality`, `final_analytical_review`, `fs_tieout_passed`, `disclosure_checklist`, `subsequent_events` reviewed up to the report date, `rep_letters_generated` ≥ 2, `b4_cleared`, `eqr_complete` when an EQR is required, `c43_cleared`, `partner_conclusion`). Sets `phase = conclusion`, `report_date`, `opinion` (unmodified / qualified / adverse / disclaimer). The 60-day assembly deadline (`assemblyDeadline`) is **shown, not enforced**.

**Archive** (`archiveEngagement`, gates `archiveGates`): report issued; completion gates; every control selected for testing concluded (design evaluated + at least one operating test); every significant deficiency communicated in writing (C5.11 grid date, ISA 265 ¶9, F037); every task holding work has a paper that is prepared and reviewed (`tasks_addressed`, `reviews_complete`, `papers_signed`); C4.1 complete; all review notes cleared; C6.2 checklist complete. Archiving stamps `retention_until` (report date or period end + firm retention years, 10 ≤ years ≤ 30), builds an immutable **archive manifest** (hash of every document version and attachment, stored as the `completion_record` row with key `archive_manifest`, protected by the "manifest immutable" trigger) and sets `archived_at`. After that, **every evidence-bearing table carries a BEFORE INSERT/UPDATE/DELETE trigger raising `engagement-archived`** (migrations 20260820000002/7) — the database, not the application, is the authority; `assertMutable` in `lib/mutability.ts` only produces a friendly error first.

**Odoo target.**
- `ea.audit.engagement.phase` Selection field on `ea.audit.engagement`; `action_advance_to_planning()`, `action_close_planning()`, `action_issue_report()` (wizard `ea.audit.report.issue.wizard` for opinion + date), `action_archive()`; each method opens a `with self.env.cr.savepoint()` block, locks the row (`SELECT … FOR UPDATE NOWAIT` through `self._cr.execute`), evaluates `_gate_results(kind)` returning a list of `(key, ok, detail, action)` and raises `UserError` listing the failed gates with their labels.
- A `ea.audit.gate.result` TransientModel feeds a **Gates panel** (OWL component or a simple `list` of computed non-stored lines) on the engagement form, phase screens and C6.1.
- Planning snapshot: `ea.audit.planning.snapshot` with a `Json` field.
- Archive immutability: Odoo has no table triggers out of the box; port it as (a) `_check_archived()` in the `write()/unlink()/create()` overrides of every engagement-scoped model (a mixin `ea.audit.engagement.scoped.mixin`), **and** (b) keep the Postgres triggers, installed by a `post_init_hook` from a SQL file (same approach as today) so the guarantee survives raw SQL and bugs. Decision needed (see I).
- Archive manifest: `ea.audit.archive.manifest` + `ea.audit.archive.manifest.line` (sha256 of each `ir.attachment` datas), made read-only by `write()` override raising.

### D.3 Sign-off tiers and the firm policy matrix (`lib/signoff-policy.ts`, `lib/signoff-matrix.ts`, `lib/documents.ts#signDocument`, `lib/eqr.ts`)

**Tiers.** A paper carries up to four active signatures in `signoff`: `preparer` (P), `reviewer` (R), `partner`, and `eqr` (only on C4.2). Signatures can be **voided** (`voided_at`, with reason; voiding an `eqr` signature requires a partner) and are **invalidated** (`invalidated_at`) automatically when the paper's content changes after signature — every signature stores a `content_hash` of the paper's answers at signing time, and every answer edit is recorded with its before/after value as an `answer_changed` row of `activity_log` by a deferred trigger (migration 20261027000002 — there is no separate answer-history table).

**The ladder** (`TEAM_LADDER`): staff < senior < manager < senior_manager < director < partner; the EQR sits outside it. These are **team roles** on `team_member.team_role`, distinct from the firm roles of `membership.role` (firm_admin, partner, manager, senior, staff, eqr_reviewer, read_only, client_user). Signing rights follow the **team role on this engagement** (F002); the firm role is an additional floor (`canReview` ≥ senior for R, `canPartnerSignoff` ≥ partner for the partner tier).

**Default matrix** (`DEFAULT_MATRIX`, firm decision F002 of 2026-10-27, first match wins): E3.1/E6.3/E6.10 senior/manager; P1.x–P2.x manager/partner; P3.x–P7.x senior/manager; S1.x–S6.x senior/manager; E1.x–E6.x staff/senior; C1.x–C4.x senior/manager; C5.x–C6.x manager/partner. Default partner sign-off on: P1.1, P2.2, P5.2, P7.2, S3.1, S6.1, S6.2, C1.1, C6.2, every C5.x, plus `PARTNER_GATED` {P1.1, P2.2, P5.2, S3.1, P7.2} and `PARTNER_ONLY_APPROVAL` {P5.2, P7.2, S6.1, S6.2, S3.1, C1.1} (on these, anyone else's R is refused: "partner-only").

**Firm policy** (`firm_signoff_policy`, one row per tenant; Settings › Sign-off rules, editable by partner or firm_admin): `min_reviewer_role` (floor under every task), `require_partner_on` (list of codes added to the matrix), `require_distinct_preparer_approver`, `allow_sole_practitioner` (**always stored false**; the no-self-review rule is never relaxed — F001). Per-task overrides in `firm_task_signoff_rule` (code → min preparer, min reviewer, partner required yes/no/default); a per-task "No" is how a firm lifts a default partner signature. The effective rule (`effectiveTaskRule`) = task rule where set, else matrix raised by the policy floor; the reviewer minimum is never below the preparer minimum. The matrix can be downloaded and re-imported as Excel (`lib/signoff-matrix.ts`, sheet "Tasks", columns I–K).

**signDocument — the order of refusals** (each is a kebab-case code the UI translates): forbidden role → `requires-senior` / `requires-partner` → archived → not-found → EQR rules (`eqr-own-paper`, EQR may sign nothing else) → `signed-locked` → `phaseStillOpen` (`acceptance-open`, `planning-open`, `execution-open`) → `not-on-team-to-sign` / `accept-engagement-first` → `role-below-task-minimum-<role>` → engagement partner pressing R on a partner-required paper is recorded as `partner` → `partner-only` → `designate-engagement-partner-first` / `not-engagement-partner` → tool-fed `tool-output-missing-<materiality|tb|sad>` → `no-version` → `checked-out` → `already-signed` → `preparer-first` → `paper-incomplete` (every question answered, every "No" explained, N/A counts) → embedded-work gaps (EMBED_ONLY_PAPERS) → `significance-unjustified` (P6.2) → `itapp-strategy-missing` (S2.3) → `ras-not-approved` (P7.2) → **`self-review`** (the preparer never signs R or partner on their own paper) → `open-notes` → `review-conclusion-first` (section conclusion reviewed first). Then the signature is inserted with the content hash and the paper status moves to signed when the required tiers are present.

**Engagement partner (F003).** Exactly one accepted `team_member` with `team_role = 'partner'`; `engagement.partner_delegate_user_id` may hold a delegate. Partner-tier signatures, report issuance, archive and rebuttal approvals are refused to anyone else (`partnerTierRefusal`). The seat is handed over from the team page (`transferEngagementPartner`); a firm administrator not staffed on the file cannot take it.

**EQR (F005, ISQM 2).** Eligibility when appointing the `eqr_reviewer` team role (`assertEqrEligibleTx`, refusals in order): `eqr-rank` (firm partner, firm_admin or firm-role EQR); `eqr-on-team` (not in any other team role, not the partner's delegate); `eqr-cooling-off` (not the accepted engagement partner of the same client on any engagement whose period end falls within the two years before this one's, inclusive); `eqr-declaration-required` (objectivity declaration ticked; recorded as `eqr_declared_at/by`). An appointed EQR makes C4.2 a completion gate. The EQR is **read-only on the team's work** (`assertNotEqrWrite`: cannot answer, attach, assign, sign P/R/partner) and owns the reviewer fields of C4.2 (`EQR_C42_KEYS`); the team's P/R on C4.2 attest the governance communications only. `eqrRequired` = a reviewer is on the team OR any Part B criterion of P1.5 answered yes.

**Odoo target.**
- `ea.audit.signoff` (document_id, role Selection preparer/reviewer/partner/eqr, user_id, version_no, content_hash, signed_at, voided_at/by/reason, invalidated_at). `action_sign(role)` on `ea.audit.paper` reproduces the refusal list above **in the same order** so the test port stays 1:1; refusal codes become `UserError` messages keyed through `_()`.
- `ea.audit.signoff.policy` (one per company, `res.company` Many2one, `_sql_constraints` unique) and `ea.audit.signoff.task.rule` (company, code, min_preparer, min_reviewer, partner_required Selection yes/no/default). `effective_rule(code)` is a Python port of `effectiveTaskRule` with the `DEFAULT_MATRIX` as a module-level list of `(regex, min_preparer, min_reviewer)`.
- Team roles: `ea.audit.team.member` (engagement_id, user_id, team_role Selection, state invited/accepted/declined, decline_reason, eqr_declared_at/by). SQL constraint: unique (engagement, user). Python constraint `_check_one_partner` (at most one accepted partner; the gate requires exactly one). Python constraint `_check_eqr_eligible` on create/write when team_role = eqr_reviewer.
- Matrix Excel round-trip: `ea.audit.signoff.matrix.wizard` (TransientModel, Binary field) using `openpyxl`; a `report_xlsx`-style export (the `report_xlsx` OCA module or a plain controller returning the workbook).
- Chatter (`mail.thread`) on `ea.audit.paper` records every signature/void as a tracked message, replacing the hand-written activity rows for those events.

### D.4 Team-only access and visibility (`lib/engagement-access.ts`, `proxy.ts`, Postgres RLS)

**Today.** Two layers: (1) **tenant isolation** — every tenant-scoped table has `tenant_id`, `FORCE ROW LEVEL SECURITY`, policy `tenant_id = current_setting('app.tenant_id')`, the app connects as the non-owner role `ea_app` and sets the GUC inside each transaction (`withTenant`); (2) **team-only** (F008, 2026-10-27) — only an *accepted* member of the engagement team may open the engagement, read, sign, export or call its API routes; firm administrators and partners not on the team do not see it in the register, dashboards or search. `proxy.ts` enforces it on every `/engagements/<uuid>` and `/api/engagements/<uuid>` path before the page streams; `app/engagements/[id]/layout.tsx` re-checks; an *invited* member is redirected to `/invitations/[id]` to accept or decline. `read_only` cannot reach any mutation (proxy refuses non-GET API calls and lets server actions through to `requireWrite`, which raises `read-only-role`). `client_user` is confined to `/portal`.

**Odoo target.**
- Tenant = `res.company` (one company per firm; multi-company Odoo is the standard answer, with `company_id` on every model and the implicit company rule). A sub-decision is whether firms become companies in **one database** (true multi-tenant, as today) or **one database per firm** (simpler, safer, the usual Odoo SaaS pattern). The spec recommends **one database per firm** for an audit firm's product (data separation is absolute, backups and retention are per firm, no RLS port needed) and keeps `company_id` so a firm with several legal entities can still use multi-company. See open decision I-1.
- Team-only: an `ir.rule` on `ea.audit.engagement` and on **every engagement-scoped model** (via the mixin's `engagement_id`): `[('engagement_id.team_member_ids', 'any', [('user_id','=',user.id),('state','=','accepted')])]` for all groups including partner and firm admin; a second rule for the invitation model lets an invited user read their own invitation row. Odoo 17+/19 supports the `any` operator on x2many in domains.
- `read_only` → group `group_read_only` with only `read` ACLs in `ir.model.access.csv`; `client_user` → `base.group_portal` with portal controllers only.
- The proxy's security headers (CSP, HSTS, frame-ancestors) are set by the reverse proxy (nginx/Apache) in front of Odoo and by Odoo's `--proxy-mode`.

### D.5 Tool-fed papers (`lib/tool-fed-papers.ts`, F004)

**Today.** P6.1 needs an **approved** materiality version; P6.2 needs a valid current TB **and** approved materiality; C1.1 needs TB + materiality + a recorded SAD conclusion (`form_response` code `sad`, field `concl_text` non-empty); E4.1–E4.34 lead schedules need a valid current-year TB (`trial_balance.current_version_no > 0` and that version's `validation_status = 'valid'`). Until the output exists every signature is refused with `tool-output-missing-<output>` and the P/R buttons are greyed with the reason.

**Odoo target.** `ea.audit.file.item.tool_outputs_missing` computed (non-stored) field returning the first missing output code; `action_sign` checks it; the paper form shows a banner (`<div class="alert">` with `invisible` attrs) and disables the buttons with `invisible="tool_outputs_missing"`.

### D.6 Allowed email domains (`lib/email-domains.ts`, F070)

**Today.** `tenant.allowed_email_domains text[]` kept by the firm administrator in Settings. Rule: the part after the last `@`, lower-cased, must **equal** one listed domain (no sub-domain matching, so `x.eca.com` is refused when only `eca.com` is listed); empty list = no restriction. Applied to every way a person is put on a team by email (`addTeamMemberByEmail`, user invitations); portal contacts are exempt. Input parsing accepts newlines, commas, semicolons, spaces and a leading "@"; each entry validated against a hostname regex.

**Odoo target.** `res.company.ea_allowed_email_domains` (Char, parsed into a list by a helper) shown in `res.config.settings`; `@api.constrains('email')` on `ea.audit.team.invite` and `res.users` creation path (`_check_email_domain_allowed`). Port `parseDomainList` and `emailDomainAllowed` 1:1 with their unit tests.

### D.7 Standards edition (`lib/standards-edition.ts`, F045)

**Today.** `engagement.standards_edition` ∈ {current, revised_2026}; default derived from the **period start** (`period_end + 1 day − duration months`, clamped like Postgres interval arithmetic) — periods beginning on or after 2026-12-15 use ISA 240 (Revised) / ISA 570 (Revised 2024). Paper definitions carry `{{tokens}}` (`ISA240.jeTesting`, `ISA570.horizon`, … about 40 keys in the `REFS` table) that `resolvePaper` substitutes per edition and language; `hasUnresolvedToken` guards the catalogue in tests. Every paragraph number under `revised_2026` is marked "to verify" by the firm's technical desk.

**Odoo target.** Selection field + `_compute_default_edition` on `ea.audit.engagement`; `ea.audit.isa.ref` data model (key, edition, lang, text) loaded from XML; a `resolve_text(text, edition, lang)` helper used by the paper renderer (QWeb template or OWL) and by the report exports. The REFS rows become translatable data; correcting a number corrects every paper.

### D.8 Materiality (`lib/materiality.ts`, `lib/materiality-model.ts`)

**Today.** Versioned `materiality` rows per engagement (draft → approved; a draft never supersedes an approved version; only the latest version can be approved). Benchmarks and their ranges: profit before tax 5–10 %; revenue, total assets and total expenses 0.5–2 %; equity 1–5 %. Performance materiality is 60–85 % of overall materiality (default 75); a departure from the default needs a justification. **The clearly trivial range differs by version:** 0.5–10 % of overall at `9c515a9` and 3–5 % from commit `0d66bd9` (F033, default 5 in both; only new versions are constrained). The Odoo port takes 3–5 %. The uncorrected misstatement threshold is overall − performance. Older code and papers call overall "PM" and performance "TE"; F033 unifies the vocabulary. Approval is a partner action and feeds P6.1, P6.2, C1.1, sampling (tolerable = performance materiality) and the SAD evaluation.

**Odoo target.** `ea.audit.materiality` (engagement_id, version_no, benchmark Selection, benchmark_amount, overall_pct, overall, performance_pct, performance, trivial_pct, trivial, rationale Html, state draft/approved, approved_by/at). `@api.constrains` for the ranges; `action_approve` requires partner tier; `engagement.materiality_id` computed = latest approved. Amounts in FCFA with `formatFCFA` style (no decimals, space grouping) → `res.currency` XAF with `decimal_places = 0`.

### D.9 Risk assessment: risks, CRA, SCOTs, controls (`lib/risks.ts`, `lib/cra.ts`, `lib/cra-model.ts`, `lib/scots.ts`, `lib/design-procedures.ts`, `lib/itgc.ts`)

**Today.** The **risk register** (`risk`, `risk_response`) holds risks by assertion with `significant`, `rebutted` (presumed revenue-fraud risk, rebuttal needs `rebuttal_approved_by` = partner), category, and links to program steps; additions after planning close need approval. **CRA** (`cra_assessment`, one row per lead index × assertion): inherent risk lower/higher × control risk rely/not_rely → level minimal / low / moderate / high (`craOf`), with a significant-risk overlay (`toTod`: low_sr / high_sr) that feeds the sampling tool; "rely" requires a control selected for testing covering the assertion or a written `cr_basis`; E1.2 writes through a deficient control conclusion as `CR_DEFICIENT_BASIS`; the RO assertion column was added by F041; history in `cra_assessment_history`. Key-item threshold and timing guidance per level are text suggestions. **SCOTs** (`scot`, `scot_index`, `wcgw`, `wcgw_control`, `scot_control`, walkthroughs, FSCP) model significant classes of transactions → what-could-go-wrong → controls → selection for testing → design evaluation → `control_test` results; **IT applications** and ITGC (no table of their own: stored as key-encoded `form_response` rows; strategy per application, S2.3 refuses signature while an application is undecided; ITGC workbook export).

**Odoo target.** `ea.audit.risk`, `ea.audit.risk.response` (M2M to program steps), `ea.audit.cra.assessment` (computed `level` and `tod_level`, `@api.constrains` on rely-without-support only evaluated by the gate, not at save), `ea.audit.cra.history` (or rely on `mail.tracking.value` for the two fields), `ea.audit.scot`, `ea.audit.wcgw`, `ea.audit.control`, `ea.audit.control.test`, `ea.audit.walkthrough`, `ea.audit.it.app`. The CRA matrix is a grid (lead index rows × 6 assertion columns with two toggles per cell) — an **OWL component** (or the `web_widget_x2many_2d_matrix` OCA widget) is required; a plain list view cannot express it.

### D.10 Sampling, tests of controls and tests of details (`lib/sampling-params.ts`, `lib/toc-sampling.ts`, `lib/tod-plan.ts`, `lib/toc-*`, `lib/tod-*`)

**Today.** MUS: confidence factors 99→4.6, 98→3.7, 95→3.0, 90→2.3, 85→1.9, 80→1.6, 75→1.4, 70→1.2, 65→1.1, 60→0.9, 55→0.8, 50→0.7; risk bands high→95 %, moderate→85 %, low→70 %; interval = tolerable ÷ factor; sample size = ⌈population ÷ interval⌉; expected misstatement must stay below tolerable; MLE projection by average per-item misstatement ratio (ratio method fallback). **Two control-sampling tables coexist.** `lib/sampling-params.ts`, used by task-level sampling: daily 30, weekly 10, monthly 4, quarterly 2, annual 1, automated 1; evaluation at 95 %: 60 items ≤1 high / 2 moderate; 30 items 0 high / 1 moderate; 10 items 0 moderate. `lib/toc-sampling.ts`, used by the sampling tool: automated 1; daily >250 occurrences 25, or 60 if the control is the sole one; 50–250, 10 %; <50, 5; <5, all; weekly 5; monthly, quarterly and semi-annual 2; annual 1. Which one survives is decision I-9. **ToC draws** (`toc_sample_draw`, append-only, F061) use a seeded HMAC-SHA256 Fisher–Yates shuffle so a draw is reproducible; a redraw needs a reason of at least 3 characters and manager rank once E1.2 testing has started; results write through to the CRA (`tests/lib/toc-cra-writethrough.test.ts`). ToD plans (`tod-plan.ts`) and workbooks (xlsx) per index.

**Odoo target.** Pure functions → `ea_audit_tools/services/sampling.py` (no ORM, unit-tested 1:1); models `ea.audit.sample.plan` (kind mus/attribute, inputs, computed outputs), `ea.audit.sample.draw`, `ea.audit.sample.item`; xlsx exports through `openpyxl` in report controllers.

### D.11 Trial balance, GL and analytics (`lib/tb.ts`, `lib/gl-*.ts`, `lib/je-selection.ts`, `lib/leadsheets.ts`, `lib/sad.ts`, `lib/sap.ts`)

**Today.** TB import (CSV/XLSX preview → confirm) validates balance, account codes, SYSCOHADA class mapping (`syscohada_grouping_rule` seed + `client_grouping_override`), stores versions (`trial_balance_version`, `trial_balance_row`, `validation_status`, superseded flag), prior-year TB, adjustments posted from the SAD; lead schedules group accounts by lead index (E, N, F, K … with sub-totals and variances). GL import (`gl_line`, projection) feeds JE selection (risk-directed criteria per ISA 240 ¶32: user, timing, round amounts, unusual accounts, keywords; each selection records its reason), the GL correlation console (two-account correlation, "thirty-analytic catalogue"), GL insights, aging, roll-forward, AP schedules, financial analysis ratios. SAD evaluates differences by FS caption against materiality and records the team's conclusion; SAP records expectation / threshold by CRA / difference / investigation / conclusion per index and assertion.

**Odoo target.** `ea.audit.tb`, `ea.audit.tb.version`, `ea.audit.tb.line`, `ea.audit.grouping.rule` (SYSCOHADA seed as CSV data), `ea.audit.client.grouping.override`, `ea.audit.gl.line` (large table — keep raw SQL inserts via `cr.executemany`/COPY for imports), `ea.audit.je.selection`, `ea.audit.sad.item`, `ea.audit.sap.procedure`. Analytics are read-heavy SQL: port the SQL (it is Postgres already) into model methods using `self.env.cr.execute`; grids use Odoo list/pivot views where flat, and an OWL grid (or `spreadsheet` from Odoo Enterprise is **not** available in Community — plan an OWL table component or the OCA `web_widget_*` set) for the console.

### D.12 Working papers and attachments (`lib/working-papers.ts`, `lib/papers/*.ts`, `lib/forms.ts`, `lib/documents.ts`, `lib/attachments.ts`, `lib/upload-safety.ts`, `lib/task-notes.ts`)

**Today.** A paper = a definition in `lib/papers/*` (sections of questions/procedures/registers/memos, EN/FR labels, practical tips, ISA references with edition tokens) whose answers are stored one row per field in `form_response` (`code = 'wp:<task>'`, `field_key`, jsonb `value`; the same table also holds tool data under other code families such as `sad`, `itapps`, `ap:`, `psp:` and `dsp`, which should become real models) with the `answer_changed` trail in `activity_log`. Papers autosave; "paper complete" = every required field answered and every "No" explained. A `document` row (kind workpaper / letter / other) with `document_version` (bytea, docx) carries the signatures; check-out/check-in lock for Word round-trips; DOCX rendered in the browser (`docx-preview`). Attachments on tasks (`task_attachment`, soft delete, quarantine of unsafe uploads: MIME sniffing, size limit, extension allow-list). Review notes (`review_note`) on a document or a task: open → responded → cleared; open notes block R/partner signatures and the gates. Section conclusions (`section_conclusion`) need their own review before the paper reads "Reviewed".

**Odoo target.** `ea.audit.paper.def` (data: code, sections, fields with type/choices/required/edition tokens — loaded from a JSON/XML export of `lib/papers`), `ea.audit.paper` (= document for the task), `ea.audit.paper.answer` (paper_id, field_key, value Json, history via a `write()` hook into `ea.audit.paper.answer.history`, replacing the trigger-written `answer_changed` activity rows), `ea.audit.review.note` (`mail.thread` + `mail.activity` for the respond/clear flow and reminders), `ir.attachment` for files (with `ea.audit.attachment` wrapper rows for quarantine state, uploaded_by, soft delete), `ea.audit.document.version` → `ir.attachment` versions. Rendering 95 paper definitions (about 1,350 required answers, parsed from the definitions) generically needs an **OWL "paper" component** reading the definition and the answers — this is the single largest front-end piece of the port (see E).

### D.13 Legal register and alerte (OHADA) (`lib/legal.ts`, `lib/alerte.ts`, `lib/registers.ts`, `lib/letters.ts`)

**Today.** Section F papers C5.2–C5.10: statutory deadlines calendar, regulated agreements register and special report, article 715 report to the board, alert procedure file (alerte: phases with event dates and deadlines, document titles), disclosure of criminal offences, registered securities attestation, equity vs half-of-share-capital monitoring, joint auditor coordination, article 525 certification of highest-paid persons. Public holidays table drives deadline arithmetic. Letters (engagement letter, representation letters, management letter…) are generated as DOCX from `lib/letters.ts` with firm letterhead (`lib/letterhead.ts`, branding).

**Odoo target.** `ea_audit_legal`: `ea.audit.legal.deadline`, `ea.audit.regulated.agreement`, `ea.audit.alerte` (+ phase lines), `ea.audit.public.holiday` (data), each with computed deadlines; QWeb PDF reports for the special reports; letters as QWeb-HTML → PDF (Odoo native) plus optional DOCX through `python-docx` where Word editing is required.

### D.14 Retention, legal hold, backups, audit log (`lib/retention.ts`, `lib/backup*`, `lib/audit-log.ts`, `lib/activity.ts`)

**Today.** Firm retention years 10–30 (default 10; "ten years is the floor" — OHADA/ISA 230); `retention_until` stamped at archive; legal holds (`legal_hold`, manager+) suspend destruction; retention report (manager+). Backups: `backup_job` table and `lib/backup/*.mjs` (extract/restore of a tenant scope with manifest and keys). One append-only `activity_log` table holds both the per-engagement trail and the firm audit log, with before/after JSON (there is no separate audit-log table). Login throttle (`login_attempt`: 5 free attempts per email and IP, 15 per email, then back-off of 1-2-4-8-16-30 minutes), password policy (at least 12 characters, mixed case, a digit, must not contain the email), forced password change for temporary passwords, optional TOTP MFA (`lib/mfa*.ts`, `lib/totp.ts`), session integrity (session invalidated on password change / suspension).

**Odoo target.** `res.company.ea_retention_years` with constraint; `ea.audit.legal.hold`; retention report as a list view with filters + `ir.cron` reminder. Audit log → Odoo's `mail.tracking.value` + the OCA `auditlog` module (records create/write/unlink with old/new values per model) — recommended rather than re-writing. Login throttle/password policy/MFA → Odoo native (`auth_totp` module in Community, `auth_password_policy`, built-in login rate-limiting via `ir.config_parameter` plus fail2ban at the reverse proxy; the exact thresholds above need custom code if they must be kept). Backups → standard `pg_dump` + filestore copy per database (the one-database-per-firm decision makes this trivial).

### D.15 Notifications, email and the portal (`lib/notifications.ts`, `lib/account-mail.ts`, `lib/tenant-mail.ts`, `lib/email*.ts`, `lib/pbc.ts`, `app/portal`)

**Today.** In-app notifications per user (bell with unread count, mark read), email via MailerSend (disabled on DEV), inbound-mail webhook (`/api/email/inbound`, shared secret), effectively a no-op since F008 retired its only token family (`IND-`), so it need not be ported as it stands; PBC requests with chase/reminder schedule and portal upload by `client_user` (quarantined); user invitations by token (`user_invite`, `/invite/[token]`).

**Odoo target.** `mail.thread` + `mail.activity` + `bus` notifications (native bell), `mail.mail` outgoing with `ir.mail_server`, `mail.gateway`/fetchmail for inbound (native), portal through `website`/`portal` modules with a `portal.mixin` on `ea.audit.pbc.request` and a controller for uploads; invitations = `res.users` signup tokens (`auth_signup`, native).

## E. Code-base transfer plan

### E.1 Target: Odoo 19 Community, one suite of addons

Odoo 19 Community (LGPL) gives the port, out of the box: users, groups and record rules; multi-company; the chatter (messages, followers, activities, tracked field changes); attachments with a filestore and checksum; the mail gateway (outgoing, inbound), notifications and the bell; translations of fields, selections and views (EN/FR); list/form/kanban/graph/pivot/calendar/activity views; search, filters and favourites; QWeb PDF reports; the website and portal; scheduled actions (`ir.cron`); server actions and automated actions; the test framework (`TransactionCase`, `HttpCase`, tours); the `auth_totp` and `auth_signup` modules. Everything that today is bespoke infrastructure in `platform/` (NextAuth, proxy, RLS plumbing, `withTenant`, notifications table, i18n JSON, DOCX preview, backup scripts) is replaced by platform features and **dropped**.

Odoo Community does **not** provide the Enterprise apps `documents`, `sign`, Studio or the end-user spreadsheet editor (to be confirmed on the staging server). The spreadsheet-like grids of the tools (TB analyzer, GL console, JE selection, CRA matrix, SAD workbook, lead schedules) therefore become **OWL components** (the standard Odoo 17+/19 front-end framework) or OCA widgets, and Excel round-trips stay as `openpyxl` exports/imports — which is what the current app does with `exceljs` anyway.

### E.2 Addon structure

| Addon | Content | Depends on |
| --- | --- | --- |
| `ea_audit_core` | Firm settings (`res.config.settings`), groups and ACLs, `ea.audit.client`, `ea.audit.engagement` (phases, gates, complexity, standards edition, naming convention, roll-forward), `ea.audit.team.member` (+ invitations, EQR eligibility, partner transfer), `ea.audit.task.template` / `task.group` / `file.item`, `ea.audit.signoff` + policy + task rules, activity trail (chatter + OCA `auditlog`), notifications (native), retention and legal hold, allowed email domains, `ea.audit.public.holiday`, dashboards (firm + engagement) | `base`, `mail`, `web`, `auth_signup`, `auth_totp`, `auditlog` (OCA) |
| `ea_audit_papers` | Paper definitions (data), `ea.audit.paper`, answers and answer history, the OWL paper renderer, practical tips, ISA references with edition tokens, review notes, section conclusions, task attachments (quarantine, soft delete), document versions/check-out, templates (the `wp-templates/` Excel files, `template_override`), forms matrix, task notes | `ea_audit_core` |
| `ea_audit_tools` | Trial balance (import, versions, validation, grouping rules, overrides, adjustments, prior year), GL lines + projection, lead schedules, aging, roll-forward, AP schedules, financial analysis, analytical procedures, materiality, significant accounts, risk register, CRA, SCOT/WCGW/controls/walkthroughs/FSCP, IT apps and ITGC, design procedures / programs / procedure library, sampling (MUS, attribute, ToC draws, ToD plans), JE selection, SAD, SAP, deficiencies, PBC requests, time entries, confirmations (read-only history) | `ea_audit_papers` |
| `ea_audit_reports` | All exports: engagement export (JSON/zip bundle), archive bundle and manifest, activity export, ITGC/JE/ToC/ToD/SAD/lead-schedule workbooks (`openpyxl`), letters and governance reports (QWeb PDF; DOCX via `python-docx` where Word editing is required), FS checklist workbook, letterhead/branding | `ea_audit_tools`, `report_xlsx` (OCA, optional) |
| `ea_audit_portal` | Client portal: PBC request list and uploads, portal contacts, inbound-mail filing | `portal`, `ea_audit_tools` |
| `ea_audit_legal` | OHADA legal register: statutory deadlines, regulated agreements, art. 715 report, alerte procedure, criminal disclosure, securities attestation, equity monitoring, joint auditor file, art. 525 certification | `ea_audit_papers` |
| `ea_audit_uat` (optional) | UAT scenario workbook (`lib/uat-scenarios.ts`, dev-only) | `ea_audit_core` |

Module layout follows Odoo conventions: `models/`, `wizards/`, `services/` (pure Python ports of the pure TypeScript modules: sampling, complexity, materiality arithmetic, CRA matrix, standards edition, email domains, amount formatting), `security/ir.model.access.csv` + `security/rules.xml`, `data/` (file index, task groups, complexity questions, SYSCOHADA grouping rules, paper definitions, ISA references, public holidays, procedure library, wp templates), `views/`, `static/src/` (OWL components), `report/`, `tests/`, `i18n/fr.po`.

### E.3 What is translated TypeScript → Python (1:1 logic port)

All of `lib/` that encodes **methodology** and **rules** — gates, sign-off policy and `signDocument`, EQR, team rules, tool-fed papers, standards edition, complexity, materiality, CRA, risks, SCOTs, design procedures, sampling (both rule sets), JE selection criteria, GL analytics tests, TB validation and grouping, SAD/SAP evaluation, lead schedule taxonomy, financial analysis ratios, archive checklist and gates, retention arithmetic, legal deadlines and alerte, letters text, paper definitions (`lib/papers/*`, about 6,300 lines of declarative data → data files), forms definitions, task groups and file index. The pure modules (no DB) port first with their vitest tests converted to `unittest`; the DB-bound modules port as model methods whose SQL is either expressed as ORM calls or kept as parameterised SQL through `self.env.cr` (Postgres stays Postgres — the analytics queries can be reused almost verbatim once `tenant_id` becomes `company_id` and table names change).

### E.4 What Odoo provides natively (dropped from the code base)

| Today | Odoo |
| --- | --- |
| `auth.ts`, NextAuth, `lib/password*.ts`, `lib/login-throttle.ts`, `lib/session-guard.ts`, `lib/mfa*.ts`, `lib/totp.ts`, `lib/invites.ts`, `/invite/[token]`, `/change-password`, `/security` | `res.users`, `auth_signup` (invitation + reset tokens), `auth_totp`, `auth_password_policy`, built-in password hashing (`passlib`), session store; forced password change via `res.users` action |
| `lib/rbac.ts`, `lib/tenant.ts`, `proxy.ts`, RLS, `withTenant` | `res.groups`, `ir.model.access`, `ir.rule`, multi-company |
| `lib/notifications.ts`, `NotificationBell`, `/api/notifications/read` | `mail.notification`, `bus.bus`, the systray bell |
| `lib/email.ts`, `account-mail.ts`, `tenant-mail.ts`, `email-inbound.ts`, `/api/email/inbound` | `ir.mail_server`, `mail.mail`, `mail.template`, `fetchmail.server` / `mail.gateway` |
| `lib/activity.ts`, `lib/audit-log.ts`, `/settings/audit-log`, `/engagements/[id]/activity` | `mail.thread` tracking + OCA `auditlog` + `res.users.log` |
| `lib/attachments.ts` storage, `document_version` bytea | `ir.attachment` (filestore, sha1 checksum, mimetype sniffing); keep the quarantine state as a wrapper model |
| `lib/i18n.ts`, `messages/*.json`, `LanguageSwitcher`, `lib/locale.ts` | `.po` files, `res.lang`, user preference |
| `lib/search.ts`, `/search`, full-text migration | Odoo global search / `_rec_names_search`; FTS via `pg_trgm` only if needed |
| `lib/branding.ts`, `/settings` branding | `res.company` logo + report layout |
| `lib/backup/*`, `backup_job`, `scripts/backup-*` | `pg_dump` + filestore per database; OCA `auto_backup` |
| `lib/release-info.ts`, `/version`, `/api/version`, `/api/probe` | module manifest version, `/web/webclient/version_info`, `/web/health` |
| `app/layout.tsx`, `AppNav`, `ThemeToggle`, `PageLoader`, `components/ui/atlas.tsx` | web client shell, menus, dark mode |
| `lib/docx.ts` preview, `DocxPreview` | PDF preview of attachments; DOCX preview only via conversion (LibreOffice headless) — decision needed |
| `lib/zip.ts`, `lib/export-bundle.ts` mechanics | Python `zipfile` |
| `node-pg-migrate`, `migrations/*.sql` | module data + `pre/post_init_hook`, migration scripts `migrations/<version>/` (OpenUpgrade style) |

### E.5 What changes for the user

- One Odoo web client instead of the Atlas shell: left menu (Audit › Engagements, Clients, Tools, Reports, Configuration), top search, chatter at the bottom of every record, activity reminders.
- The phase screens become kanban/list views of `ea.audit.file.item` grouped by task group; the task paper is a form view with an embedded OWL paper component; sign-offs are buttons in the status bar.
- Review notes become chatter threads with activities instead of a separate register (the register remains as a list view with filters).
- Tools keep their layouts as OWL components inside form/`client action` views; exports become report actions.
- The client portal is the Odoo portal (same login page as the staff, portal group).
- Language is the user's Odoo language; FR remains the default.

### E.6 What is dropped

The UAT workbook page (optional addon), the probe route, the `_*.js` ad-hoc scripts, the marketing landing page (`app/page.tsx` — replace by the Odoo login page or a static site), the in-browser DOCX renderer (replace by PDF preview), the independence campaign tables (read-only history, migrate as archived data only), `rls_probe`, `pgmigrations`.

### E.7 Hosting of the build

The Odoo target is a **dedicated staging server, test.auditisa.com**, separate from the VPS that hosts AuditISA DEV and PROD. Odoo builds, parity runs, migration rehearsals and UAT run there; nothing Odoo-related is installed on the AuditISA VPS. Consequences: migration rehearsals need a dump copied across from the AuditISA server and handled as client data on the new host (access, encryption, deletion after use); the Next.js application keeps serving the firm until cutover; and the production Odoo host remains to be decided (I-13). This review did not connect to or inspect test.auditisa.com, so its Odoo version and installed modules are unverified here.

## F. Data migration

### F.1 Principles

1. **Source of truth** = a `pg_dump` of the production database `ea_audit` taken at cutover (production today runs 0d25ef0; its schema is behind DEV by the 2026-09-25 … 2026-11-03 migrations — the dump must first be upgraded to the DEV schema by applying those migrations on a copy, after repairing the `pgmigrations` order defect noted in the project memory). Document version bytes (`document_version.content`) and attachments are extracted to files.
2. **One Odoo database per firm (tenant)** — see open decision I-1. The extraction script therefore runs once per `tenant` row, filtered by `tenant_id`, and loads into that firm's Odoo database. If the one-database multi-company variant is chosen instead, the same script runs with `company_id = <firm>` on one database.
3. **Identity mapping**: every source UUID is kept in an `ea_legacy_uuid` Char field (indexed) on every migrated model, and an `ea.audit.migration.map` table (model, legacy_uuid, res_id) is written during the load so relations are resolved in load order and the migration can be re-run idempotently.
4. **Enums** map to Selection values with the same keys wherever possible (phase, roles, sign-off roles, opinion, complexity, standards edition, materiality status, CRA ir/cr …) so reports and tests keep their vocabulary.
5. **Timestamps and authorship**: `created_at`/`updated_at` → `create_date`/`write_date` (set through SQL after load, because the ORM stamps "now"); `created_by` → `create_uid` where a user mapping exists.
6. **Immutable history** (sign-offs, voided sign-offs, the `answer_changed` trail, activity log, archive manifest, CRA history, TB versions) is loaded as-is, never recomputed.
7. **Archived engagements** are loaded with `archived_at` set and the Python guards active; the manifest hashes are re-verified after load (hash of each migrated attachment must equal the manifest value) — this is the acceptance test of the document migration.

### F.2 Load order (parents before children) — the 82 tables of the current schema

The schema after all 119 migrations holds 82 tables (81 application tables + `pgmigrations`), 917 columns, one true Postgres enum (`user_role`) and 75 text columns constrained by CHECK lists (→ Odoo `Selection`), 112 triggers and 16 functions (archive immutability on 39 tables + 12 parent-lookup guards, cross-tenant guards on 42 engagement-scoped tables, sign-off integrity, manifest immutability, audit-trail hardening, `answer_changed` trail), 114 indexes, RLS on 73 tables. No table or column was ever renamed or dropped; the "recode / rehome / retitle" migrations are data updates. Binary payloads live in `bytea` in four tables (`document_version.content`, `task_attachment.content`, `evidence.content`, `pbc_item.content`) and all become `ir.attachment`. `gl_line` is a projection of `sub_ledger_row` and is rebuilt, not migrated.

1. **Reference data installed by the module** (compare with the dump, migrate only firm edits): `syscohada_grouping_rule` (94 seed rows) → `ea.audit.grouping.rule`; `public_holiday` (106 rows, Cameroon) → `ea.audit.public.holiday` / `resource.calendar.leaves`.
2. **Firm**: `tenant` → `res.company` (+ retention years, allowed email domains, naming convention, branding, `protected` flag); `firm_signoff_policy`, `firm_task_signoff_rule` → `ea.audit.signoff.policy` / `.rule`; `template_override`; `firm_holiday` (firm-wide rows).
3. **Users**: `app_user` + `membership` (enum `user_role`) → `res.users` + groups (super-admins → dedicated group; suspended → inactive; `must_change_password` → forced reset; TOTP secrets and `mfa_recovery_code` not migrated — users re-enrol; `user_invite` and `login_attempt` not migrated).
4. **Clients**: `client` → `res.partner` (company) + `ea.audit.client`; `client_grouping_override`, `client_lead_index_override`.
5. **Engagements**: `engagement` → `ea.audit.engagement`; `team_member` → `ea.audit.team.member`; `budget_line`; `independence_campaign` / `independence_confirmation` (retired, history only); `firm_holiday` (engagement rows); `legal_hold`; `time_entry` → `ea.audit.time.entry` (or `account.analytic.line`).
6. **File index**: `file_item` → `ea.audit.file.item` (100–200 rows per engagement; title/code recodes already applied in data).
7. **Answers**: `form_response` (EAV: `code` = `wp:<task>` or a form/tool code such as `sad`, `field_key`, jsonb `value`) → `ea.audit.paper.answer`; the `answer_changed` rows of `activity_log` → `ea.audit.paper.answer.history`.
8. **Planning**: `related_party`, `accounting_estimate` (soft-deleted rows kept inactive), `materiality` + `materiality_specific`, `potential_risk`, `risk`, `risk_section`, `risk_lead_index`, `program_step`, `risk_response` (→ Many2many), `planning_snapshot`, `scot`, `scot_index`, `wcgw`, `scot_control`, `wcgw_control` (→ Many2many), `cra_assessment` + `cra_assessment_history`, `cra_index_setting`, `revise_log`.
9. **Documents and sign-offs**: `document` → `ea.audit.paper`; `document_version` → `ir.attachment` (one per version, checksum verified); `signoff` (active / voided / invalidated, content hash); `section_conclusion`; `review_note` → `ea.audit.review.note`; `task_attachment` (quarantine state, soft delete) and `evidence` → `ir.attachment` + wrappers; `comment` → `mail.message`.
10. **Data**: `trial_balance`, `trial_balance_version` (superseded rows kept), `trial_balance_row` (bulk COPY), `adjusting_journal` + `adjusting_journal_line` + `trial_balance_version_journal` → `ea.audit.adjustment` (not `account.move`), `sub_ledger_dataset` + `sub_ledger_row` (largest tables; COPY), then rebuild `gl_line`.
11. **Tests and analytics**: `toc_sample_draw` (append-only), `control_test`, `automation_run`, `substantive_analytical_procedure` (SAP), `misstatement` (SAD), `confirmation`.
12. **Conclusion**: `finding`, `deficiency_evaluation`, `completion_record` (incl. the `archive_manifest` row), `statutory_deadline`, `convention`, `alerte` + `alerte_event`, `fait_delictueux`, `pbc_item` (+ portal uploads).
13. **Trails**: `activity_log` (append-only; → `ea.audit.activity.log` or OCA `auditlog`), `notification` (unread only, optional), `backup_job` (drop), `uat_result` (optional), `rls_probe` and `pgmigrations` (drop).

Archived engagements must be loaded **before** the Odoo-side immutability guards (Python overrides and re-installed SQL triggers) are enabled; the load runs as a privileged script with the guards disabled, then the guards are switched on and the manifest verification pass runs.

### F.3 Validation checks (run after every load, per firm)

- Row counts per source table vs target model (with the expected drops: superseded TB versions kept, soft-deleted attachments inactive, notifications optional).
- For every engagement: phase, report date, opinion, archived flag, retention date equal; number of active sign-offs per paper equal; gate evaluation (`_gate_results`) gives the **same pass/fail per key** as the current `/api/engagements/[id]/status` JSON captured before cutover (export it for all engagements as a fixture).
- Materiality latest approved values equal; CRA levels equal per cell; sampling plans recompute to the same sample sizes; SAD totals equal; TB totals per version and per lead index equal; lead schedule export of E/N/F/K identical to the current export (cell-by-cell diff).
- Attachment checksums match the archive manifest for archived files.
- A sample of 20 papers per firm compared field by field (answers, tips, references rendered for the edition).
- Access: for 10 users per firm, the list of visible engagements in Odoo equals the current register (team-only rule).

## G. Testing strategy

### G.1 Port of the existing tests

At `9c515a9` the repository has 90 vitest files under `tests/lib` (896 `it`/`test` calls) and 11 Playwright specs under `tests/e2e` (22 tests). They split into three groups:

1. **Pure-logic tests** (no DB: amount, complexity, cra-model, materiality-model, sampling params, toc-sample/tod-plan, je-key-projection, email-domains, standards-edition, password policy, totp, public-routes, i18n parity, paper registry/tips, letters-text, dataset-mapping, parse-tabular, gate labels, rank authority …) → ported 1:1 to `unittest`/`pytest`-style tests in each addon's `tests/` (`odoo.tests.TransactionCase` not required; plain `unittest.TestCase` runs under `odoo-bin --test-enable` too). Expected effort: mechanical.
2. **DB-bound rule tests** (signoff governance, engagement-partner-required, eqr-determination, team-add-member, engagement-access, gates uat2-gates, tool-output, conclusion/archive, retention, documents, execution, planning, legal, tb, je-selection, workbook integrity, backup round-trip, rls, concurrency) → `TransactionCase` tests creating the same fixtures through the ORM; the refusal codes become asserted `UserError` messages. The RLS tests are replaced by `ir.rule` tests (user A cannot read user B's engagement; non-member cannot read; invited member sees only the invitation). The concurrency tests (double-submit of a phase transition) become two-cursor tests using `self.registry.cursor()`.
3. **E2E** (phase1…phase9, isolation, notifications, branding) → Odoo **tours** (`odoo.tests.HttpCase` + JS tour steps) for the critical paths: create engagement → acceptance gate → planning close → report issuance → archive; sign-off refusals visible in the UI; portal upload; language switch. Keep Playwright as an external smoke suite against the staging Odoo if the team prefers (it works unchanged against any URL).

### G.2 Parity harness

Before cutover, export from DEV for every UAT engagement: the status JSON, gates, materiality, CRA matrix, sample sizes, SAD, lead schedules (xlsx), and the paper answer sets. Load them as fixtures and assert the Odoo port produces the same values. This harness is the objective definition of "done" for phases 2–5.

### G.3 UAT

Reuse the 317-scenario UAT script (`lib/uat-scenarios.ts`) as the acceptance plan for the Odoo build: the scenarios describe business behaviour rather than React, so most should carry over with their navigation steps rewritten (a judgement; not counted). Run it with the UAT firms (A and B) re-created on the Odoo staging server test.auditisa.com, by role (firm admin, partner, manager, senior, staff, EQR, read-only, client user).

## H. Phased roadmap with effort ranges

All effort is an **estimate** in person-weeks (pw, 5 person-days), for a team with one senior Odoo developer, one developer who knows the current code and a part-time auditor as product owner. Phase numbers match the Phase column of `Screen-inventory.xlsx`.

**How the range was derived.** The workbook estimates three overlapping layers: screens 440 pd, library modules 376 pd, API routes and actions 265.5 pd (1,081.5 pd if simply added, which double-counts). API handlers and actions are thin wrappers over the library, so they are left out. For each phase the **low** figure assumes the largest layer already contains the other (the screens and the library fully overlap) and the **high** figure assumes no overlap between screens and library. Preparation, migration and test porting are not in the catalogues and are judgement figures.

| Phase | Scope | Deliverable | Screens / lib pd | Effort (pw) | Depends on |
| --- | --- | --- | --- | --- | --- |
| 0 Preparation | Decisions I-1…I-13, parity fixtures from DEV, repository and CI running `odoo-bin --test-enable`, staging on test.auditisa.com, re-baseline on current `dev` | Decision log, fixtures, CI green on an empty addon | judgement | 2–3 | — |
| 1 Foundation (`ea_audit_core`) | Settings, groups, ACLs, record rules, users and invitations, clients, sign-off model, policy and matrix, gates engine, team and EQR rules, activity trail | Team-only access and gate logic pass ported tests | 66 / 174 | 35–48 | 0 |
| 2 Engagement file | Engagement creation and complexity, file index, register, dashboards, cockpits, risks, CRA, legal hold | Gates 1 and 2 pass on migrated UAT data | 59 / counted in 1 | 12–15 | 1 |
| 3 Papers (`ea_audit_papers`) | Paper definition loader, OWL paper component, answers and history, content hash, sign-off refusal ladder, review notes, attachments, versions, templates | Every task paper renders and signs with today's refusals | 83 / 53 | 17–27 | 2 |
| 4 Tools (`ea_audit_tools`) | TB, lead schedules, materiality, SCOT and controls, sampling, GL console, JE selection, SAD, SAP, analyzers, PBC | Parity harness green; tool-fed papers unlock | 179.5 / 86 | 36–53 | 3 (grids can start in parallel) |
| 5 Reports, portal, legal | Workbooks, bundles and manifest, letters, portal, OHADA register and alerte | Issuance, archive and exports match today | 50 / 63 | 13–23 | 4 |
| 6 Migration and cutover | Extraction and load scripts (F.2), validation (F.3), dry runs, training, parallel run, decommissioning | Production on Odoo | judgement | 6–9 | 5 |
| Cross-cutting | Port of the 896 unit tests, tours, UAT by role | Test suite and UAT sign-off | judgement | 8–12 | runs alongside 1–6 |
| **Total** | | | | **129–190 pw** | |

At the full team rate this is about 10–15 months with 3 full-time developers, or 15–22 months with 2, before holidays and the firm's own acceptance time. If the firm wants this shorter, scope is the lever: decisions I-3, I-6 and I-10 move the most effort.

Milestones: M1 end of phase 2 (gates 1 and 2 on migrated data), M2 end of phase 3 (all papers sign with parity), M3 end of phase 4 (parity harness), M4 UAT sign-off, M5 go-live.

**Difference from `Migration-plan-Odoo19.md`.** That plan, written in parallel by another session, estimates 45–60 pw of development (excluding testing and the firm's acceptance work), by engine. It also assumes one `ea_audit` module with `ea.*` models and `res.company` per firm, which is what `odoo-module\ea_audit` sketches, while this document proposes six addons, `ea.audit.*` models and one database per firm. The two have not been reconciled; this is decision I-12. The screen-by-screen count here is roughly two to three times the engine-level figure, so the firm should not budget on the lower number until the first paper and first grid have been built and timed.

## I. Risks and open decisions

### I.1 Top risks

| # | Risk | Impact | Mitigation |
| --- | --- | --- | --- |
| R1 | **Paper renderer**: 95 paper definitions for 94 of the 118 task codes, about 1,350 required answers, conditional logic, tips, edition tokens and embedded registers; a generic OWL component is a large front-end build and the one piece with no Odoo equivalent | Schedule of phase 3; user acceptance of the paper UX | Export `lib/papers` to a JSON schema first; build the component against 5 representative papers (P1.1, S3.1, E4.1, C4.2, C6.1) then generalise; keep the autosave/complete semantics identical |
| R2 | **Grid-heavy tools** (TB analyzer, GL console 1,723-line component, JE selection studio, CRA matrix, SAD workbook) have no native Community view | Phase 4 effort and UX regression | OWL table components with virtual scrolling; accept list/pivot views where the grid is only read; keep Excel export as the power-user path |
| R3 | **Immutability and gate guarantees** currently enforced by Postgres triggers and single-transaction gate+mutation | A port that relies only on ORM checks weakens audit evidence | Keep the SQL triggers (installed by `post_init_hook`), lock rows with `FOR UPDATE` in gate methods, add tests for double-submit |
| R4 | **Multi-tenancy model** (one DB per firm vs multi-company) decided late | Rework of record rules, migration scripts and hosting | Decide in phase 0 (I-1) |
| R5 | **Refusal-code parity**: 40+ kebab-case codes drive banners and tests | Subtle behaviour drift, UAT regressions | Port `signDocument` ladder in the same order; keep the code strings as message keys; port the governance tests first |
| R6 | **Data migration of documents** (bytea versions, manifests, quarantine) | Loss of audit evidence; archive manifests no longer verifiable | Checksum verification pass; migrate archived engagements first in a dry run |
| R7 | **Production schema lag** (PROD 0d25ef0 vs DEV 9c515a9; `pgmigrations` order defect) | Migration scripts written against DEV fail on PROD | Upgrade a PROD copy to the DEV schema before extraction; repair `pgmigrations` first |
| R8 | **ISA 2026 revised paragraph numbers "to verify"** | Wrong references in papers | Technical desk verifies the REFS table before data load |
| R9 | **Team capacity / Odoo expertise** | Estimates slip | Engage one senior Odoo developer; keep the current developer for domain knowledge |
| R10 | **Rules found inconsistent during cataloguing** — page stricter than lib or vice versa: `/resources` page requires firm_admin while `teamWorkload` requires manager; portal-contact form shown to every role but `addPortalContact` refuses below senior; `/uat` verdicts, `restoreVersion`, `addComment` (discussion), `addRisk`, `dismissPotentialRisk`, `completeStep`, `respondToEngagement`, SAD `save/saveMeta`, `createDataset` use `requireTenant` only (no `canWrite`), so a read-only member can reach them through page server actions; the EQR is not blocked on SAD/SAP saves; `/api/steps/[id]/evidence` sits outside the proxy's team gate (tenant RLS only); `assertMutable` missing on ap-comments, significance, tb, subledgers, planning-ras, task-notes (DB triggers still refuse); lead-schedule, SAD and sign-off-matrix exports are not logged and collapse errors to 401/500; `/api/email/inbound` is effectively a no-op since F008; `advanceToPlanning`/`closePlanning` have no rank check beyond `requireWrite`; two ToC sample-size tables coexist (`lib/toc-sampling.ts` used by the tool, `lib/sampling-params.ts` used by task-level sampling); C6.2 is defined twice (gam.ts wins); E5.1–E5.5 are conditional but no trigger activates them | Porting bugs as features | Resolve each in phase 0 as a decision (I-9) and port the decided rule |
| R11 | **The source keeps changing**: five commits and 50 changed files arrived during this review alone | Specification and parity fixtures go stale; two systems to keep in step | Re-baseline in phase 0; freeze methodology changes or log them for the port during the build |

### I.2 Open decisions for the firm owner

- **I-1 Tenancy**: one Odoo database per firm (recommended) or one database with multi-company? Affects hosting, backups, record rules and the migration script.
- **I-2 Clients as `res.partner`**: link `ea.audit.client` to `res.partner` (enables contacts, portal users, future invoicing) or keep it standalone?
- **I-3 DOCX round-trip**: keep Word check-out/check-in with in-browser preview (needs LibreOffice headless for PDF preview) or move narrative papers fully into the paper component with PDF output only?
- **I-4 Immutability**: Python guards only, or Python guards + the existing Postgres triggers (recommended)?
- **I-5 Audit log**: OCA `auditlog` (recommended) or a bespoke `ea.audit.activity` port with before/after JSON?
- **I-6 Grids**: OWL components (recommended, larger effort) or plain list/pivot views with Excel export for the console-style tools?
- **I-7 Portal**: Odoo portal (same host) or keep PBC uploads by email only?
- **I-8 MFA and password policy**: enable `auth_totp` for partner/firm admin (the 2026-07-09 decision descoped mandatory 2FA)?
- **I-9 Rule inconsistencies** listed in R10 — which side is right in each case?
- **I-10 Scope cuts**: drop the UAT workbook, the marketing landing page, the GL analytics catalogue entries marked unavailable (25–28), the retired independence campaign and the SadBoard component (unused)?
- **I-11 Parallel run**: how long should Next.js and Odoo run side by side, and which firm/engagements pilot first?
- **I-12 Which plan governs**: this document or `Migration-plan-Odoo19.md` on module structure (six addons or one `ea_audit`), model prefix, tenancy and budget (129–190 pw or 45–60 pw plus testing)?
- **I-13 Production host**: test.auditisa.com is the staging target; where does production Odoo run, and who may hold client data on the staging server during rehearsals?

## J. Appendix — full route list

### J.1 Pages

| # | Route | Area | Screen | Roles | Effort | Phase |
| --- | --- | --- | --- | --- | --- | --- |

| 1 | `(framework) app/error.tsx` | Public | Something went wrong | everyone | S (0.5 pd) (estimate) | 1 Foundation |

| 2 | `(framework) app/layout.tsx` | Public | Root layout (AuditISA shell) | everyone (public); locale and branding resolve per session | S (1 pd) (estimate) | 1 Foundation |

| 3 | `(framework) app/not-found.tsx` | Public | 404 — This page is not in the audit file | everyone | S (0.5 pd) (estimate) | 1 Foundation |

| 4 | `(framework) app/robots.ts` | Public | robots.txt | everyone | S (0.5 pd) (estimate) | 1 Foundation |

| 5 | `(framework) app/sitemap.ts` | Public | sitemap.xml | everyone | S (0.5 pd) (estimate) | 1 Foundation |

| 6 | `/` | Public | Home (redirect) | everyone; redirect target depends on session | S (0.5 pd) (estimate) | 1 Foundation |

| 7 | `/privacy` | Public | Privacy Policy / Politique de confidentialité | public | S (0.5 pd) (estimate) | 5 Reports/portal/legal |

| 8 | `/terms` | Public | Terms of Service / Conditions d'utilisation | public | S (0.5 pd) (estimate) | 5 Reports/portal/legal |

| 9 | `/version` | Public | What is this site running? | public | S (0.5 pd) (estimate) | 6 Migration & cutover |

| 10 | `/change-password` | Auth | Change password | any signed-in user (auth() only; firm roles and client_user with mustChangePassword); proxy: mustChangePassword → forced here before any other route, APIs refus | M (3 pd) (estimate) | 1 Foundation |

| 11 | `/invite/[token]` | Auth | Choose your password | public (anonymous) — guarded by a live, unspent, unexpired token only | S (2 pd) (estimate) | 1 Foundation |

| 12 | `/login` | Auth | Sign in | public (anonymous); an already signed-in user is redirected to safeNext(next) or /dashboard | M (4 pd) (estimate) | 1 Foundation |

| 13 | `/login # language switch` | Auth | Language (English / Français) | everyone (anonymous sets cookie only) | S (0.5 pd) (estimate) | 1 Foundation |

| 14 | `/dashboard` | Dashboard | My engagements (Welcome back) | any firm role (auth() then requireTenant in loaders; client_user redirected to /portal by proxy); To-do 'review' rows only when canReview(role) (senior+), 'acce | M (5 pd) (estimate) | 2 Engagement file |

| 15 | `/clients` | Clients | Entity records | any firm role reads (requireTenant); create panel shown only when canWrite(session.user.role) (not read_only/client_user); createClientAction re-checks `!canWri | S (2 pd) (estimate) | 1 Foundation |

| 16 | `/clients # create client form` | Clients | New client | canWrite roles (staff, senior, manager, eqr_reviewer, partner, firm_admin); read_only redirected with error read-only-role | S (1 pd) (estimate, included in /clients S) | 1 Foundation |

| 17 | `/clients/[id]` | Clients | Entity record | any firm role reads (requireTenant); identity edit and archive/reinstate only when `session.user.role === "firm_admin"` (updateClientMasterAction checks role == | M (4 pd) (estimate) | 1 Foundation |

| 18 | `/engagements` | Engagement file | Engagements | any firm role (auth(); listEngagements requireTenant) but only engagements where the user is an accepted team member (visibilityClause, F008); roll-forward: req | M (4 pd) (estimate) | 2 Engagement file |

| 19 | `/engagements/[id]` | Engagement file | Audit file hub (file index) | auth() session (redirect /login) + layout F008 gate; generateDocumentAction → generateDocument requireWrite() (read_only refused) + not-on-this-engagement check | M (3 pd) | 2 Engagement file |

| 20 | `/engagements/[id] # generate-document` | Engagement file | Generate working-paper document (hub row button) | requireWrite() in generateDocument (read_only/portal refused); not-on-this-engagement check | S (1 pd) | 3 Papers |

| 21 | `/engagements/[id] (layout)` | Engagement file | Engagement access gate (layout) | canSeeEngagement(id): EXISTS team_member tm WHERE tm.engagement_id = e.id AND tm.user_id = $user AND tm.status = 'accepted' (lib/engagement-access.ts visibility | S (2 pd) | 1 Foundation |

| 22 | `/engagements/[id]/acceptance` | Engagement file | Acceptance & continuance | auth() + layout F008; setMandateAction/generateLetterAction/advanceToPlanningAction go through requireWrite() (read_only refused); advanceToPlanning any writer  | M (4 pd) | 2 Engagement file |

| 23 | `/engagements/[id]/acceptance # advance-to-planning` | Engagement file | Advance to planning (phase gate button) | requireWrite(); no explicit rank check (any accepted team writer) | S (1 pd) | 2 Engagement file |

| 24 | `/engagements/[id]/activity` | Engagement file | Activity trail & answer history | auth() + layout F008; read-only | M (3 pd) | 1 Foundation |

| 25 | `/engagements/[id]/analytics` | Engagement file | Analytical procedures (lead-schedule analytics) | auth() + layout F008; comments saved via POST /api/engagements/[id]/ap-comments (lib/analytical-procedures.ts saveApComments) | M (4 pd) | 4 Tools |

| 26 | `/engagements/[id]/analyzers/[kind]` | Engagement file | Sub-ledger analyzer (GL / AR / AP / inventory / fixed assets / payroll / bank / supplier statements) | auth() + layout F008; kind must satisfy isSubLedgerKind else 404; uploads POST /api/engagements/[id]/subledgers (requireTenant, 60 MB cap); runReconFromAnalyzer | L (8 pd) | 4 Tools |

| 27 | `/engagements/[id]/analyzers/[kind] # reconcile-to-control-account` | Engagement file | Reconcile sub-ledger to TB control account | requireWrite(); team F008 | S (1 pd) | 4 Tools |

| 28 | `/engagements/[id]/conclusion` | Engagement file | Conclusion, report issuance & archive | auth() + layout F008; isPartner = canPartnerSignoff(role) gates partner conclusion, issue report, archive UI; canPlaceHold = atLeast(role,'manager'); canRelease | XL (12 pd) | 5 Reports/portal/legal |

| 29 | `/engagements/[id]/conclusion # archive-file` | Engagement file | Archive and lock the audit file | canPartnerSignoff(role) → else archive-partner-only; partnerTierRefusal (F003); UI disables for non-partners and when gates fail | S (2 pd) | 5 Reports/portal/legal |

| 30 | `/engagements/[id]/conclusion # issue-report` | Engagement file | Issue auditor's report (opinion form) | canPartnerSignoff(role) AND partnerTierRefusal(tenant, engagement, user) === null (designated engagement partner or delegate); non-partners see 'Awaiting the en | S (2 pd) | 5 Reports/portal/legal |

| 31 | `/engagements/[id]/considerations` | Engagement file | Planning considerations (conditional forms) | auth() + layout F008; saveFormAction → lib/forms.ts saveForm (requireWrite) | S (2 pd) | 2 Engagement file |

| 32 | `/engagements/[id]/cra` | Engagement file | Combined Risk Assessment matrix (full screen) | auth() + layout F008; cell edits POST /api/engagements/[id]/cra → lib/cra.ts saveCraCell (assertMutable; requireWrite in lib) | L (6 pd) | 4 Tools |

| 33 | `/engagements/[id]/dashboard` | Engagement file | Engagement dashboard | auth() + layout F008; read-only for every team role (no write action on this page) | L (6 pd) | 2 Engagement file |

| 34 | `/engagements/[id]/data` | Engagement file | Trial Balance Analyzer | auth() + layout F008; POST /api/engagements/[id]/tb and /tb/preview (requireTenant/requireWrite in lib/tb.ts importTrialBalance; 60 MB cap) | L (8 pd) | 4 Tools |

| 35 | `/engagements/[id]/discussion` | Engagement file | Team discussion (threads) | auth() + layout F008; addCommentAction → lib/comments.ts addComment uses requireTenant() (not requireWrite: a read_only member can post — ambiguity) | S (1 pd) | 2 Engagement file |

| 36 | `/engagements/[id]/findings` | Engagement file | Findings register & misstatements (B5) | auth() + layout F008; raiseFindingAction/clearFindingAction/setCorrectedAction → lib/execution.ts (requireWrite) | M (4 pd) | 4 Tools |

| 37 | `/engagements/[id]/legal` | Engagement file | OHADA legal register (C5.2–C5.9) | auth() + layout F008; isPartner = canPartnerSignoff(role) shows C5.6 faits section (listFaits forbidden otherwise); all writes requireWrite (read_only may view, | XL (12 pd) | 5 Reports/portal/legal |

| 38 | `/engagements/[id]/legal # alerte-start / alerte-advance / alerte-resume` | Engagement file | Alerte procedure (going-concern alert) state machine | requireWrite(); team F008 | M (3 pd) | 5 Reports/portal/legal |

| 39 | `/engagements/[id]/legal # equity-monitor (C5.8)` | Engagement file | Net equity vs half share capital monitor (art. 664) | requireWrite | S (1 pd) | 5 Reports/portal/legal |

| 40 | `/engagements/[id]/legal # titres-attestation (C5.7)` | Engagement file | Registered securities attestation (C5.7) | requireWrite | S (1 pd) | 5 Reports/portal/legal |

| 41 | `/engagements/[id]/nature` | Engagement file | Nature of entity (complexity questionnaire) | auth() + layout F008; classifyEntityAction → applyComplexity (requireWrite; ForbiddenError surfaces as ?error=) | M (3 pd) | 2 Engagement file |

| 42 | `/engagements/[id]/pbc` | Engagement file | PBC requests (client-provided documents) | auth() + layout F008; addPbcItem requireWrite; chasePbc requireWrite; acceptPbc/attachAcceptedPbc require canReview(role) (senior+) → else forbidden | M (4 pd) | 5 Reports/portal/legal |

| 43 | `/engagements/[id]/pbc # accept-upload-to-section` | Engagement file | Accept client upload and file it as evidence | canReview(role) (forbidden otherwise) | S (1 pd) | 5 Reports/portal/legal |

| 44 | `/engagements/[id]/planning` | Engagement file | Planning workspace (drivers, materiality, team/budget/PBC, material sections, gates) | auth() + layout F008; all actions requireWrite; approveMateriality canPartnerSignoff (requires-partner); assignTeamMember requireTeamManager (manager+, not EQR; | L (8 pd) | 2 Engagement file |

| 45 | `/engagements/[id]/planning # close-planning` | Engagement file | Close planning (planning → execution gate) | requireWrite(); no explicit rank check | S (1 pd) | 2 Engagement file |

| 46 | `/engagements/[id]/planning # materiality-create / materiality-approve` | Engagement file | Materiality version create & partner approval | create: requireWrite; approve: canPartnerSignoff(role) → else requires-partner | S (2 pd) | 4 Tools |

| 47 | `/engagements/[id]/risks` | Engagement file | Risk Console (ISA 315 risk register) | auth() + layout F008; isPartner = canPartnerSignoff(role) shows the rebut form and approve-addition; rebutRevenueFraudRisk: canPartnerSignoff (rebut-partner-onl | L (8 pd) | 4 Tools |

| 48 | `/engagements/[id]/risks # rebut-revenue-fraud` | Engagement file | Rebut the presumed revenue-fraud risk (partner) | canPartnerSignoff(role) (rebut-partner-only) + partnerTierRefusalTx === null (designated engagement partner or delegate) | S (1 pd) | 4 Tools |

| 49 | `/engagements/[id]/settings` | Engagement file | Engagement settings (period, standards edition, team link) | auth() + layout F008; periodEditable = (phase acceptance|planning) && canReview(role); editionEditable = phase != archived && atLeast(role,'manager'); server: u | S (2 pd) | 2 Engagement file |

| 50 | `/new-engagement` | Engagement file | New audit engagement | `if (!atLeast(session.user.role as Role, "staff")) redirect("/dashboard")` — staff, senior, manager, eqr_reviewer, partner, firm_admin (read_only and client_use | M (5 pd) (estimate) | 2 Engagement file |

| 51 | `/new-engagement # EngagementWizard` | Engagement file | Engagement wizard (identity questions) | staff and above (page gate atLeast(role,'staff'); action requireWrite) | S (2 pd) (estimate, included in /new-engagement M) | 2 Engagement file |

| 52 | `/search` | Engagement file | Search | any firm role (auth(); search() requireTenant) — hits limited to engagements the user is an accepted team member of (visibilityClause) | M (4 pd) (estimate) | 3 Papers |

| 53 | `/documents/[id]` | Working papers | Working paper | accepted team members of the document's engagement only (guardDocument → visibleToUser, else ForbiddenError rendered as 404); fait délictueux documents partner+ | XL (14 pd) (estimate) | 3 Papers |

| 54 | `/engagements/[id]/forms/[code]` | Working papers | Legacy planning form (task canvas) | auth() + layout F008; readOnly = !(isRole(role) && canWrite(role)) hides all controls (UAT run 3 B23); saveFormAction → saveForm (requireWrite); signOffReviewer | M (5 pd) | 3 Papers |

| 55 | `/engagements/[id]/groups/[group]` | Working papers | Task group list (sign-off table) | auth() + layout F008; canSign = canWrite(role) && !phaseStillOpen(taskPhase, engagement.phase, code); canReview(role) for R; Add missing tasks: canReview(role); | M (4 pd) | 3 Papers |

| 56 | `/engagements/[id]/groups/[group] # sign-preparer-chip / sign-reviewer-chip` | Working papers | In-row P / R sign-off squares | P: canWrite + phase open + accepted team member at/above minPreparer; R: canReview (firm) AND team role in TEAM_REVIEW_ROLES (senior..partner) at/above minRevie | L (6 pd) | 3 Papers |

| 57 | `/engagements/[id]/phase/[section]` | Working papers | Phase overview (acceptance / strategy / execution / conclusion) | auth() + layout F008; read-only | S (2 pd) | 2 Engagement file |

| 58 | `/engagements/[id]/phases/[phase]` | Working papers | Phase task sign-off table (pre-planning / planning / execution / conclusion) | auth() + layout F008; canSign = !phaseStillOpen(phase, engagement.phase) && canWrite(role); mayReview = canReview(role); server rules in signDocument | M (4 pd) | 3 Papers |

| 59 | `/engagements/[id]/sections/[itemId]` | Working papers | Working-paper screen (canonical task page) | auth() + layout F008; itemId must be a UUID of this engagement (404 otherwise); viewOnly = archived || !canWrite(role) || (actsAsEqr && code !== 'C4.2') || (C4. | XL (20 pd) | 3 Papers |

| 60 | `/engagements/[id]/sections/[itemId] # archive-checklist (C6.1 / C6.2)` | Working papers | Archive checklist board (gates and open items) | archive: canPartnerSignoff (UI) + server archive-partner-only + partnerTierRefusal; rollforward requireWrite + engagement partner required | M (3 pd) | 5 Reports/portal/legal |

| 61 | `/engagements/[id]/sections/[itemId] # assign-task` | Working papers | Assign task to a team member | canReview(role) && !isEqr (UI); server assignTask: assignee must be a team member, never eqr_reviewer | S (1 pd) | 2 Engagement file |

| 62 | `/engagements/[id]/sections/[itemId] # attachments-drawer` | Working papers | Task evidence attachments (upload, versions, templates, edit locally) | upload/rename: atLeast(role,'staff') (read_only/portal refused); delete/restore: atLeast(role,'manager'); download: atLeast(role,'read_only'); EQR refused on te | M (5 pd) | 3 Papers |

| 63 | `/engagements/[id]/sections/[itemId] # deficiency-grid (C5.11)` | Working papers | ISA 265 deficiency evaluation grid (C5.11) | requireWrite; readOnly follows viewOnly | M (3 pd) | 5 Reports/portal/legal |

| 64 | `/engagements/[id]/sections/[itemId] # design-procedures-board (S5.5)` | Working papers | Design substantive procedures board (S5.5) | POST /api/dsp: assertMutable; lib requireWrite | L (6 pd) | 4 Tools |

| 65 | `/engagements/[id]/sections/[itemId] # itapps-board (S2.3 / S2.5)` | Working papers | IT applications register & strategy per application | POST /api/itapps: assertMutable; lib requireWrite; readOnly on S2.5 or viewOnly | S (2 pd) | 4 Tools |

| 66 | `/engagements/[id]/sections/[itemId] # mark-not-applicable` | Working papers | Task N/A toggle (mark not applicable / reinstate) | canReview(role) && !actsAsEqr (eqr-read-only, UAT run 2 B18 / run 3 B03); assertMutable | S (1 pd) | 3 Papers |

| 67 | `/engagements/[id]/sections/[itemId] # paper-wizard-steps` | Working papers | Paper wizard (status → questionnaire pages → conclusion) | readOnly prop = viewOnly (archived, read_only, EQR on team work, non-appointed EQR on C4.2); lockedKeys per EQR rules | L (8 pd) | 3 Papers |

| 68 | `/engagements/[id]/sections/[itemId] # planning-ras (P7.2)` | Working papers | Planning review & approval summary (P7.2) | answers: Section A requires senior+, Section B partner (SECTION_FLOOR), Section C only an actor with firm role eqr_reviewer who holds no other team role (assert | M (4 pd) | 3 Papers |

| 69 | `/engagements/[id]/sections/[itemId] # review-note-thread` | Working papers | Task review notes (raise / respond / clear) | canRaise = canReview(role) (UI); server: addTaskNote requireWrite + assertNoteReachable (engagement visible to user, UAT run 3 B01); respondToTaskNote requireWr | M (3 pd) | 3 Papers |

| 70 | `/engagements/[id]/sections/[itemId] # scot-studio (S1.1 register, S1.2 WCGW builder, S1.3 walkthroughs, S2.1 select, S2.2 design, E1.2 TOC board, S1.4 FSCP)` | Working papers | SCOT Studio boards embedded in strategy/execution papers | POST /api/scots: assertMutable (423 archived) + lib requireWrite/requireEngagementAccess; redraw after testing manager-only (team rank) | XL (12 pd) | 4 Tools |

| 71 | `/engagements/[id]/sections/[itemId] # section-conclusion-and-review (E4)` | Working papers | Account conclusion (prepare + review) | save: requireWrite; review: canReview (or canPartnerSignoff when asPartner) + accepted team member + F002 minReviewer (belowMinimumCode) + partner tier when asP | S (2 pd) | 3 Papers |

| 72 | `/engagements/[id]/sections/[itemId] # significant-accounts-grid (P6.2)` | Working papers | Significant accounts & relevant assertions grid (P6.2) | POST /api/significance: lib requireWrite | M (4 pd) | 4 Tools |

| 73 | `/engagements/[id]/tasks` | Working papers | My Tasks (engagement work queue) | auth() + layout F008; read-only list | S (2 pd) | 2 Engagement file |

| 74 | `/engagements/[id]/tools` | Tools | Tools hub | auth() session else redirect('/login'); getEngagement() → requireTenant() (client_user refused 'portal-account'); engagement-team visibility (F008, visibleToUse | S (1 pd) | 4 Tools |

| 75 | `/engagements/[id]/tools/data-analytics` | Tools | Data Analytics (analyzer list) | auth() + getEngagement (requireTenant); team visibility via proxy/layout (F008). All roles read. | S (0.5 pd) | 4 Tools |

| 76 | `/engagements/[id]/tools/financial-analysis` | Tools | Financial Analysis (ratio battery) | Page: auth() + getEngagement; commentary save via /api/engagements/[id]/ap-comments → saveApComments → requireWrite() (read_only & client_user refused 'read-onl | M (4 pd) | 4 Tools |

| 77 | `/engagements/[id]/tools/forms` | Tools | Forms matrix (assignment of preparer / approver) | View: any authenticated team member. Assign: canAssign = canReview(session.user.role) i.e. atLeast(role,'senior') (senior, manager, eqr_reviewer, partner, firm_ | M (3 pd) | 4 Tools |

| 78 | `/engagements/[id]/tools/gl-console` | Tools | GL Correlation Console | Page: auth() + getEngagement. API /api/engagements/[id]/gl-analytics: auth() (401), team visibility via proxy; only op 'build' calls assertMutable (archived → 4 | XL (15 pd) | 4 Tools |

| 79 | `/engagements/[id]/tools/gl-console # build projection & validate` | Tools | GL Console — Build projection / population checks | op build: assertMutable (archived → 423); any writer; op validate read-only | M (4 pd) | 4 Tools |

| 80 | `/engagements/[id]/tools/gl-console # drill-down` | Tools | GL Console — Drill-down overlay | read-only op 'drill' (no archive guard) | S (2 pd) | 4 Tools |

| 81 | `/engagements/[id]/tools/je-selection` | Tools | Journal-Entry Selection studio (ISA 240 ¶32) | Page: auth() + getEngagement. API POST /api/engagements/[id]/je-selection: requireEngagementAccess (accepted team) → 403; run writes nothing (allowed on archive | XL (14 pd) | 4 Tools |

| 82 | `/engagements/[id]/tools/je-selection # export E3.1 workbook` | Tools | E3.1 Journal entries workbook export | requireEngagementAccess; logExport('e3.1-journal-entries') | L (6 pd) | 4 Tools |

| 83 | `/engagements/[id]/tools/lead-schedule` | Tools | Lead Schedule (index-named schedules) | Page: auth() + getEngagement; commentary write via /api/engagements/[id]/ap-comments → requireWrite; export GET /lead-schedule-export → getEngagement (requireTe | M (5 pd) | 4 Tools |

| 84 | `/engagements/[id]/tools/materiality` | Tools | Materiality (ISA 320) — PM / TE / SAD nominal | View: any team member. Generate: createMaterialityVersion → requireWrite() ('read-only-role' for read_only/client_user). Approve: approveMateriality → requireWr | M (5 pd) | 4 Tools |

| 85 | `/engagements/[id]/tools/materiality # approve` | Tools | Materiality — Partner approval | requireWrite + canPartnerSignoff (atLeast partner) → 'requires-partner' | S (1 pd) | 4 Tools |

| 86 | `/engagements/[id]/tools/review-notes` | Tools | Review notes register | View: any accepted team member (auth + getEngagement). No writes on this page; mutations happen on the task page via API routes (see flow record). | S (2 pd) | 4 Tools |

| 87 | `/engagements/[id]/tools/review-notes # raise / respond / clear (API)` | Tools | Review note lifecycle (raise → respond → clear) | All three: requireWrite() (read_only/client_user → 403 'read-only-role') + assertNoteReachable (visibleToUser accepted team → 403 'not-on-this-engagement'). Cle | M (3 pd) | 4 Tools |

| 88 | `/engagements/[id]/tools/sad` | Tools | Summary of Audit Differences (ISA 450) workbook | View: any team member (auth + getEngagement). POST /api/engagements/[id]/sad: assertMutable (archived → 423); op save/saveMeta → requireTenant (any non-client r | XL (12 pd) | 4 Tools |

| 89 | `/engagements/[id]/tools/sad # export Excel` | Tools | SAD — Excel export (client copy) | getEngagement (requireTenant) + proxy team gate; no export log (unlike other exports) | M (3 pd) | 4 Tools |

| 90 | `/engagements/[id]/tools/sad # post to register` | Tools | SAD — Post entry onto misstatement schedule (C1.1) | requireWrite; assertMutable | S (1 pd) | 4 Tools |

| 91 | `/engagements/[id]/tools/sample-papers` | Tools | Sample working papers (blank templates shelf) | View: any team member. Download GET /api/engagements/[id]/wp-templates/[key]: requireEngagementAccess (403) ; logged as export 'sample-working-paper:<key>'. | M (3 pd) + builders counted elsewhere | 4 Tools |

| 92 | `/engagements/[id]/tools/sampling` | Tools | Sampling (tests of controls, tests of details, results & projection) | View: any team member. Draw/save population via POST /api/engagements/[id]/scots: assertMutable (423) + requireWrite + requireEngagementAccess; REDRAW after tes | XL (14 pd) | 4 Tools |

| 93 | `/engagements/[id]/tools/sampling # ToD workbook export` | Tools | Sampling — Tests-of-details workbook (one tab per lead index) | requireEngagementAccess; 409 with code no-materiality / no-gl / no-mapping | L (6 pd) | 4 Tools |

| 94 | `/engagements/[id]/tools/sampling # draw ToC sample` | Tools | Sampling — Draw / redraw test-of-controls sample | requireWrite + requireEngagementAccess; redraw after testing: teamRank(accepted team role) ≥ manager | M (3 pd) | 4 Tools |

| 95 | `/engagements/[id]/tools/sampling # record ToD result` | Tools | Sampling — Record tests-of-details result and project | requireWrite | S (2 pd) | 4 Tools |

| 96 | `/engagements/[id]/tools/sap` | Tools | Substantive analytical procedures (ISA 520, F038) | View: any team member. readOnly = engagement.phase==='archived' OR !canWrite(role) (fieldset disabled, no Save). saveSap → requireWrite + assertMutable; EQR not | M (4 pd) | 4 Tools |

| 97 | `/engagements/[id]/team` | Team | Manage team (members, engagement partner seat, add by email) | auth() + layout F008; canManage = canReview(role) shows remove/add (server requireTeamManager: manager+ and not eqr_reviewer → team-manager-only; partner team r | L (6 pd) | 1 Foundation |

| 98 | `/engagements/[id]/team # transfer-engagement-partner / set-partner-delegate` | Team | Engagement partner seat: transfer & delegate | actorRole === 'firm_admin' || actor is the current engagement partner (transfer-partner-forbidden / not-engagement-partner) | S (2 pd) | 1 Foundation |

| 99 | `/engagements/[id]/time` | Team | Time (my entries & budget vs actual) | auth() + layout F008; logTime/deleteTimeEntry requireWrite; delete only own rows (WHERE user_id = me) | M (3 pd) | 2 Engagement file |

| 100 | `/invitations/[id]` | Team | Engagement invitation | any signed-in firm role holding a team_member row with status 'invited' on that engagement (requireTenant; client_user refused); an already-accepted member is r | S (2 pd) (estimate) | 2 Engagement file |

| 101 | `/resources` | Team | Team workload | page: `if (!canManageFirm(session.user.role as Role)) redirect("/dashboard")` (firm_admin only); lib teamWorkload: `requireRole("manager")` (the page is stricte | S (2 pd) (estimate) | 2 Engagement file |

| 102 | `/users` | Users | Users | firm_admin only: page `if (!canManageFirm(session.user.role as Role)) redirect("/dashboard")`; every lib function calls requireAdmin → canManageFirm else UserAd | L (6 pd) (estimate) | 1 Foundation |

| 103 | `/users # invite user` | Users | Invite a user | firm_admin only (requireAdmin → canManageFirm) | S (1.5 pd) (estimate, included in /users L) | 1 Foundation |

| 104 | `/security` | Settings | Account security (Two-factor authentication) | any signed-in user (auth() only; lib/mfa.ts uses auth()); in practice firm roles (client_user confined to /portal by proxy) | M (3 pd) (estimate) | 1 Foundation |

| 105 | `/security # MFA enrolment` | Settings | Turn on two-factor (confirm code → recovery codes) | the signed-in user for their own account (confirmEnrolment uses auth()) | S (1 pd) (estimate, included in /security M) | 1 Foundation |

| 106 | `/settings` | Settings | Firm settings | any firm role reads; isAdmin = canManageFirm(role) (firm_admin) for Users/Templates/Audit log/Workload links and the email-domains, retention, SAP and branding  | M (4 pd) (estimate) | 1 Foundation |

| 107 | `/settings # branding upload` | Settings | Branding & letterhead | firm_admin only (updateBranding: requireWrite + canManageFirm → BrandingError('forbidden')); non-admins see settings.adminOnly | S (1.5 pd) (estimate, included in /settings M) | 1 Foundation |

| 108 | `/settings # retention policy form` | Settings | File retention (period) | firm_admin (setRetentionYears: requireRole('firm_admin')); report link atLeast manager | S (0.5 pd) (estimate, included in /settings M) | 1 Foundation |

| 109 | `/settings/audit-log` | Settings | Audit log | firm_admin only: page `if (session.user.role !== "firm_admin") notFound()`; lib requireFirmAdmin `ctx.role !== "firm_admin"` → ForbiddenError('firm-admin-only') | M (3 pd) (estimate) | 1 Foundation |

| 110 | `/settings/retention` | Settings | File retention report | manager and above: page `if (!atLeast(session.user.role as Role, "manager")) redirect("/settings?error=requires-manager")`; lib retentionReport `requireRole("ma | S (2 pd) (estimate) | 2 Engagement file |

| 111 | `/settings/signoff` | Settings | Firm sign-off rules | partner and firm_admin: page `if (!isRole(session.user.role) || !atLeast(session.user.role, "partner")) notFound()`; lib requirePolicyEditor = requireWrite() +  | L (6 pd) (estimate) | 1 Foundation |

| 112 | `/settings/signoff # signoff matrix import` | Settings | Import a completed matrix (Excel) | partner and firm_admin (requirePolicyEditor → signoff-policy-partner-only) | S (2 pd) (estimate, included in /settings/signoff L) | 1 Foundation |

| 113 | `/templates` | Settings | Working-paper templates | firm_admin only: `if (!canManageFirm(session.user.role as Role)) redirect("/dashboard")`; listOverrides requireTenant | S (1 pd) (estimate) | 3 Papers |

| 114 | `/templates/[code]` | Settings | Firm customisation (template editor) | firm_admin only: `if (!canManageFirm(session.user.role as Role)) redirect("/dashboard")`; lib saveOverride/resetOverride requireAdmin → canManageFirm else Templ | S (1 pd) (estimate) | 3 Papers |

| 115 | `/admin` | Admin | Platform admin console | super admins only: page `if (!session.user.isSuper) redirect("/dashboard")`; every lib call requireSuper() (`session.user.isSuper` else AdminError('forbidden')) | L (7 pd) (estimate) | 1 Foundation |

| 116 | `/admin # FirmOnboardingWizard` | Admin | Onboard an audit firm (4 steps) | super admins only (checkAvailability and createFirm both call requireSuper()) | M (3 pd) (estimate) | 1 Foundation |

| 117 | `/admin # delete firm` | Admin | Delete firm (type slug to confirm) | super admins only (deleteFirm → requireSuper()) | S (2 pd) (estimate) | 1 Foundation |

| 118 | `/uat` | Admin | Acceptance test workbook | any firm role on a non-production instance (`if (!uatAvailable()) notFound()`; listResults/recordResult use requireTenant — read_only is not refused by the lib, | S (2 pd) (estimate) | 6 Migration & cutover |

| 119 | `/portal` | Portal | Client portal — Documents requested by your auditor | client_user only: `if (session.user.role !== "client_user" || !session.user.clientId) redirect("/dashboard")`; loaders use requirePortalUser() (firm staff refus | M (5 pd) (estimate) | 5 Reports/portal/legal |


### J.2 API routes

| Route | Method | Purpose | Auth | Odoo equivalent |
| --- | --- | --- | --- | --- |

| `/api/attachments/[fileItemId]` | GET | Picker list for 'attach an existing file': the engagement's other task attachments (metadata, latest live version per task+name) plus the shelf of blank working-paper templates. | await requireTenant(); if (!atLeast(role, "staff")) 403; lib: guardFileItem -> visibleToUser (ForbiddenError not-on-this | model method ea.audit.task.action_list_attachable_files() (JSON-RPC call_kw) or controller /ea_audit/task/<id>/attachable |

| `/api/attachments/[fileItemId]` | POST | Upload a file against a task as the next version of that filename (multipart), or attach something the engagement already holds (JSON {copyFrom} copies another task's attachment, JSON {template} assigns a blank working-paper template). | await requireTenant(); if (!atLeast(role, "staff")) 403; lib saveAttachment: guardFileItem/visibleToUser, assertCanWrite | model method ea.audit.attachment.action_upload() over ir.attachment (versioned by name) + ea.audit.attachment.action_copy_from()/action_from_template(); upload transport: native /web/binary/upload_attachment or controller /ea_audit/task/<id>/upload |

| `/api/attachments/file/[attachmentId]` | GET | Download one live attachment version (bytes). | await requireTenant(); if (!atLeast(role, "read_only")) 403; lib getAttachment: guardAttachment -> visibleToUser | native ir.attachment download (/web/content/<id>?download=true) with ir.rule on engagement team membership |

| `/api/attachments/file/[attachmentId]` | PATCH | Rename an attachment (all its live versions, extension preserved) or restore a soft-deleted one within the 30-day window. | await requireTenant(); restore: if (!atLeast(role, "manager")) 403; rename: if (!atLeast(role, "staff")) 403; lib: guard | model methods ea.audit.attachment.action_rename(name) and action_restore() (button actions); soft delete via active flag + deleted_at |

| `/api/attachments/file/[attachmentId]` | DELETE | Soft-delete an attachment and all its versions (deleted_at/deleted_by), restorable for 30 days. | await requireTenant(); if (!atLeast(role, "manager")) 403; lib deleteAttachment: guardAttachment, assertCanDelete(manage | model method ea.audit.attachment.action_soft_delete() (unlink() override refusing hard delete) |

| `/api/auth/[...nextauth]` | GET | Auth.js (NextAuth v5) handler endpoints: session, csrf, providers, signin page redirects, callback. | public (NextAuth own endpoints; excluded from proxy rules via PUBLIC_ROUTES '/api/auth') | native Odoo auth (res.users login, /web/login, /web/session/*), auth_totp for MFA, res.users.company_id/groups for tenant+role; login throttle via custom ir.config_parameter + auth_signup/ base brute-force limiter |

| `/api/auth/[...nextauth]` | POST | Auth.js credential sign-in / sign-out POST endpoints. | public (NextAuth) | native /web/login + /web/session/logout |

| `/api/documents/[id]/upload` | POST | Check in an edited working paper (.docx) as the next document version; requires a prior check-out by the same user. | await requireTenant(); if (!atLeast(role, "staff")) 403; lib checkinDocument: requireWrite() | model method ea.audit.document.action_checkin(binary) producing ea.audit.document.version (ir.attachment per version); transport native upload or controller /ea_audit/document/<id>/checkin |

| `/api/documents/[id]/versions/[no]` | GET | Download a specific version of a working paper / letter / report document. | await requireTenant(); if (!atLeast(role, "read_only")) 403; lib getVersionContent -> guardDocument: visibleToUser + fai | native ir.attachment download (/web/content) on ea.audit.document.version with ir.rule |

| `/api/email/inbound` | POST | MailerSend inbound-route webhook; matches replies by [ref:...] token in subject/text. Currently the only token family (IND-) is retired (F008) so every message is acknowledged and ignored. | shared-secret header: request.headers.get("x-inbound-secret") compared with timingSafeEqual to process.env.EMAIL_INBOUND | native mail gateway (fetchmail.server / mail.thread.message_process) — replies threaded by Message-Id/alias instead of [ref:] token; or controller /ea_audit/mail/inbound with shared secret if MailerSend webhook kept |

| `/api/engagements/[id]/activity/export` | GET | Engagement audit trail (activity_log, up to 5000 rows) as a CSV with UTF-8 BOM; the export itself is logged first. | await requireEngagementAccess(id) (requireTenant + visibleToUser -> ForbiddenError not-on-this-engagement) | report action (ir.actions.report, custom CSV via controller /ea_audit/engagement/<id>/activity.csv) over mail.message/ea.audit.activity; log export in chatter |

| `/api/engagements/[id]/ap-comments` | POST | Auto-save one commentary cell of the analytical-procedures (lead schedule variance) grid. | none in handler; lib saveApComments: requireWrite(); engagement membership enforced by proxy only | model method ea.audit.lead.schedule.write({'comment_<key>': value}) via inline-edit (ORM write) on ea.audit.ap.comment |

| `/api/engagements/[id]/cra` | POST | S3.1 combined risk assessment matrix: save one cell (relevant, IR, IR basis, CR, CR basis, reason) or one lead index key-item threshold. | await assertMutable(id) (requireTenant inside) -> 423 archived; lib saveCraCell/saveIndexThreshold: requireWrite() | model ea.audit.cra.assessment with write() + mail tracking (history), ea.audit.cra.index.setting; grid widget inline write |

| `/api/engagements/[id]/dsp` | POST | S5.5 design-of-substantive-procedures board: save one field of one account index's design. | await assertMutable(id) -> 423; lib saveDsp: requireWrite() | model ea.audit.dsp.line write() (one2many on ea.audit.engagement) via inline edit |

| `/api/engagements/[id]/export/bundle` | GET | The complete audit file streamed as a ZIP (documents, versions, attachments, registers, README); logged before streaming. | lib exportEngagementBundle: requireTenant(); if (!(await canSeeEngagement(id))) throw ForbiddenError("not-on-this-engage | controller /ea_audit/engagement/<id>/bundle.zip (odoo.http.Controller, streamed zipfile) + chatter log; or ir.actions.report via server action |

| `/api/engagements/[id]/export` | GET | Regulator export: the file index with task statuses and sign-offs as .xlsx (9.6). | await requireEngagementAccess(id) | report action (ir.actions.report report_type xlsx, report_xlsx) ea_audit.report_file_index |

| `/api/engagements/[id]/gl-analytics` | POST | GL analytics engine single endpoint: build (project imported ledger into gl_line + validate), validate, catalogue (30 analytics), accounts (picker), analytic (run one), entry (entry analysis), correlate (two accounts), drill (lines behind a cell). | const session = await auth(); if (!session?.user) 401; op 'build' only: await assertMutable(id) -> 423; lib functions: r | model ea.audit.gl.dataset methods: action_build_projection(), analytics_catalogue(), run_analytic(key, params), entry_analysis(), correlate(), drill_down() exposed via call_kw (JSON-RPC) to an OWL client component |

| `/api/engagements/[id]/gl-insights` | POST | GL insight computation needing client input: account correlation matrix over the imported ledger. | const session = await auth(); if (!session?.user) 401; lib correlationMatrix: requireTenant() | model method ea.audit.gl.dataset.correlation_matrix(accounts) via call_kw |

| `/api/engagements/[id]/itapps` | POST | S2.3 IT applications board: save one application row (name, layers, strategy, ITGC note, removed flag). | await assertMutable(id) -> 423; lib saveItApp: requireWrite() | model ea.audit.it.application (one2many) write() via inline edit |

| `/api/engagements/[id]/itgc/export` | GET | E1.1 ITGC testing workbook (Cover, Applications, one tab per IT process domain, deficiency diagnostic) as .xlsx. | await requireEngagementAccess(id) | report action xlsx ea_audit.report_itgc_workbook |

| `/api/engagements/[id]/je-selection` | POST | Journal-entry selection engine: run the auditor's criteria/user rules over a projected ledger and return selected lines with reasons; optionally record the run as the S5.4 selection design. | await requireEngagementAccess(id); lib runSelection: requireTenant(); recordSelectionDesign: assertMutable + requireWrit | model methods ea.audit.je.selection.run(dataset, criteria, params, rules) and action_record_design() via call_kw; selection design stored on ea.audit.working.paper S5.4 |

| `/api/engagements/[id]/je/export` | GET | E3.1 journal entries workbook (Cover, Population, Criteria, Selection, Exceptions) at default thresholds for the current/selected ledger. | await requireEngagementAccess(id) | report action xlsx ea_audit.report_je_workbook |

| `/api/engagements/[id]/je/export` | POST | Same workbook built from the selection the studio just ran (body = /je-selection body), carrying the chosen criteria, thresholds, rules and every selected line. | await requireEngagementAccess(id) | same report action with data passed via wizard (ea.audit.je.export.wizard) |

| `/api/engagements/[id]/lead-schedule-export` | GET | Lead schedules as one Excel workbook: Introduction tab + one tab per lead index with accounts, Current Y/Prior Y, movement, variance and saved commentary. | none in handler; lib getEngagement/apLeadSchedules/apComments: requireTenant(); engagement membership enforced by proxy  | report action xlsx ea_audit.report_lead_schedules |

| `/api/engagements/[id]/planning-ras` | POST | Planning risk-assessment summary: record one confirmation answer, or sign/withdraw one signature tier (preparer/manager/partner/eqr). | const session = await auth(); if (!isRole(role)) 401; sign: if (!atLeast(role, definition.min)) 403 insufficient-role; l | model ea.audit.planning.ras with action_sign(tier)/action_withdraw(tier) button methods and field write for answers |

| `/api/engagements/[id]/psp` | POST | E4 account workpaper mutations: generate primary substantive procedures for a task, add an 'other' procedure, save a result/finding field, toggle a procedure done (through completeStep with its conclusion) or undone. | await assertMutable(id) -> 423; taskCodeOfStep: requireTenant(); lib generatePsp/addOtherPsp/savePspResult: requireWrite | model ea.audit.program.step methods action_generate_psp(), action_add_other(), write(result), action_complete(conclusion)/action_uncomplete() (button actions) |

| `/api/engagements/[id]/sad/export` | GET | Summary of audit differences as the firm's workbook: uncorrected, corrected, conclusion (UMT = PM - TE, qualitative factors), reclassifications, cash-flow and disclosure schedules. | none in handler; lib getEngagement/sadView: requireTenant(); membership via proxy only | report action xlsx ea_audit.report_sad_workbook over ea.audit.misstatement |

| `/api/engagements/[id]/sad` | POST | SAD mutations: classify a line/flag corrected/record rationale (save), post a step's finding onto the misstatement schedule (post), save tab meta such as qualitative factors, conclusion text, cash-flow/disclosure rows (saveMeta). | await assertMutable(id) -> 423; lib saveSad/saveSadMeta: requireTenant() (no write-role check); postSadEntry: requireWri | model ea.audit.sad.line write() + action_post_to_schedule(); ea.audit.sad.meta key/value on engagement |

| `/api/engagements/[id]/sampling/toc-export` | GET | Tests-of-controls samples workbook: one tab per control selected for testing with population, minimum sample, drawn occurrence numbers and tester columns. | await requireEngagementAccess(id) | report action xlsx ea_audit.report_toc_samples |

| `/api/engagements/[id]/sampling/tod-export` | GET | Tests-of-details sampling workbook for one FS side: cover + one tab per lead index with key items and representative sample. | await requireEngagementAccess(id) | report action xlsx ea_audit.report_tod_sampling with wizard for side/assurance |

| `/api/engagements/[id]/scots` | POST | SCOT Studio: all significant-class-of-transactions mutations behind one op discriminator (create/update/delete/assign SCOT, link/unlink lead index, WCGW add/delete, control add/update/delete, toggle WCGW-control link, draw ToC sample, walkthrough and FSCP answers, ToD and MUS previews). | await assertMutable(id) -> 423; scotIdsBelongTo(id, ...) else 404; lib: requireWrite() for creates/updates/links, requir | models ea.audit.scot / ea.audit.wcgw / ea.audit.control / ea.audit.toc.draw with ORM create/write/unlink + button methods action_draw_toc_sample(), tod_preview(), mus_preview() |

| `/api/engagements/[id]/significance` | POST | Record one lead schedule's significance decision (P6.1/P6.2): status, justification, relevant assertions, specific materiality amount. | none in handler; lib saveSignificance: requireWrite(); membership via proxy | model ea.audit.significant.account write() via inline edit |

| `/api/engagements/[id]/status` | GET | Machine-readable engagement status for data integration: summary, per-phase progress and the full task list with sign-off states. | none in handler; lib getEngagement/engagementPhaseProgress/phaseTasks: requireTenant(); membership via proxy | native JSON-RPC read on ea.audit.engagement + ea.audit.task (or controller /ea_audit/engagement/<id>/status for API keys) |

| `/api/engagements/[id]/subledgers/preview` | POST | Analyse a sub-ledger CSV/XLSX without ingesting: headers, example values, amount column guess. | await requireTenant() | wizard ea.audit.dataset.import.wizard onchange(file) computing preview (transient model) |

| `/api/engagements/[id]/subledgers` | POST | Upload a typed sub-ledger dataset (CSV/XLSX) for the engagement (step 3.4): replaces the dataset of the same kind+timing, stores rows and total. | none in handler; lib createDataset: requireTenant() (no write-role check); membership via proxy | wizard ea.audit.dataset.import.wizard.action_import() creating ea.audit.dataset + ea.audit.dataset.row (or storing rows as jsonb) |

| `/api/engagements/[id]/task-notes/clear` | POST | Answer and clear a review note raised on a task. | none in handler; lib clearTaskNote: requireWrite(); assertNoteReachable (visibleToUser); if (!atLeast(role, "manager"))  | model method ea.audit.review.note.action_clear(response) (button) |

| `/api/engagements/[id]/task-notes/respond` | POST | Reply to a review note without clearing it. | none in handler; lib respondToTaskNote: requireWrite() + assertNoteReachable | model method ea.audit.review.note.action_respond(text) or mail.message reply on the note thread |

| `/api/engagements/[id]/task-notes` | POST | Raise a review note on a task; it reaches the assignee's dashboard (notification). | none in handler; lib addTaskNote: requireWrite() (+ engagement/task ownership check -> not-found / not-on-this-engagemen | model method ea.audit.review.note.create() + mail.activity/notification to assignee |

| `/api/engagements/[id]/tb/preview` | POST | Analyse a trial-balance file without ingesting: inferred column mapping, readability, sample rows, class mapping against the engagement's existing overrides. | none in handler; lib previewTrialBalance: requireTenant() | wizard ea.audit.tb.import.wizard preview step (transient) -> ea.audit.trial.balance.action_import_preview() |

| `/api/engagements/[id]/tb` | POST | Import a trial balance (step 3.1): persists class-mapping and lead-index overrides chosen on the confirm screen, then ingests rows as a new TB version superseding the previous one for that timing. | none in handler; lib importTrialBalance/addOverride/saveLeadIndexOverride: requireWrite(); getEngagement: requireTenant( | model method ea.audit.trial.balance.action_import(file, mapping, overrides, timing) via wizard ea.audit.tb.import.wizard; versions as ea.audit.trial.balance.version |

| `/api/engagements/[id]/toc/export` | GET | E1.2 tests of controls workbook (Cover, Board, Tests, Exceptions). | await requireEngagementAccess(id) | report action xlsx ea_audit.report_toc_workbook |

| `/api/engagements/[id]/wp-templates/[key]` | GET | Download a blank sample working paper from the templates shelf (shipped .xlsx or generated), in the interface language. | await requireEngagementAccess(id) | native ir.attachment download of template records (ea.audit.wp.template) via /web/content, with chatter log |

| `/api/notifications/read` | POST | Mark one in-app notification read (bell menu). | none in handler; lib markNotificationRead: requireTenant() and UPDATE ... WHERE user_id = caller | native mail.notification / bus (mark as read) or ea.audit.notification.action_mark_read() |

| `/api/probe` | GET | Cross-tenant isolation probe used by the E2E RLS test: returns the caller's tenant id and rls_probe notes, tenant derived from session only. | await requireTenant() | drop (test-only); equivalent is an Odoo test asserting ir.rule multi-company isolation |

| `/api/settings/audit-log` | GET | Firm-wide audit log as CSV with the page's filters (F027); export itself recorded. | lib firmActivityForExport -> requireFirmAdmin(): requireTenant(); if (ctx.role !== "firm_admin") throw ForbiddenError("f | report action / controller /ea_audit/settings/audit-log.csv over ea.audit.activity restricted to group ea_audit.group_firm_admin |

| `/api/settings/signoff-matrix` | GET | Firm sign-off role matrix as an Excel workbook (F002): every task of the default index with today's rule and columns I-K for the firm to fill in and re-import. | lib getPolicy -> requirePolicyEditor(): requireWrite(); if (!atLeast(ctx.role, "partner")) throw ForbiddenError("signoff | report action xlsx ea_audit.report_signoff_matrix (export of ea.audit.signoff.policy / ea.audit.task.signoff.rule) |

| `/api/steps/[id]/evidence` | POST | Attach an uploaded file as evidence to a program step (step 4.3). | none in handler; lib addEvidenceFile: requireWrite() | model method ea.audit.program.step.action_add_evidence() creating ir.attachment (res_model=ea.audit.program.step) |

| `/api/version` | GET | Which commit/build this instance runs (deploy pipeline proof); browsers are sent to the readable /version page. | public (PUBLIC_ROUTES '/api/version') | native /web/webclient/version_info extended, or controller /ea_audit/version returning module manifest version + git sha from a deploy-written file |


### J.3 Server actions

| Action | File | Purpose | Auth | Odoo equivalent |
| --- | --- | --- | --- | --- |

| `createClientAction` | app/actions/audit-file.ts | Create a client in the register; asks once on a duplicate name unless force=1. | const session = await auth(); if (!session?.user || !canWrite(session.user.role)) redirect("/clients?error=read-only-rol | native res.partner create (ea.audit.client inherits res.partner) with duplicate-name warning in onchange |

| `createEngagementAction` | app/actions/audit-file.ts | New-engagement wizard: match or create the client by name, pick fiscal year/period end/nature and the engagement partner, create the engagement (scoping deferred), detect a prior-year file and carry it forward as a continuance. | lib createEngagement: requireWrite(); listFirmUsers/listClients: requireTenant(); canSeeEngagement after creation | wizard ea.audit.engagement.create.wizard (transient) -> ea.audit.engagement.create() with _sql_constraints unique(client, fiscal_year, nature) and continuance logic in create() |

| `updateStandardsEditionAction` | app/actions/audit-file.ts | Override the engagement's standards edition with a logged reason (F045). | lib setStandardsEdition: requireWrite(); if (!atLeast(role, "manager")) throw Error("forbidden") | model method ea.audit.engagement.action_set_standards_edition(edition, reason) via wizard with reason field |

| `updatePeriodEndAction` | app/actions/audit-file.ts | Correct the period end while in acceptance/planning; regenerates the name and the C5.2 statutory calendar. | const { tenantId, role } = await requireTenant(); if (!canReview(role)) redirect(`${path}?error=forbidden`) | model method ea.audit.engagement.write({'period_end'}) with constraint on phase + onchange recompute of name and deadlines |

| `classifyEntityAction` | app/actions/audit-file.ts | Nature-of-entity screen: recompute complexity from raw answers, record it, propagate the file index at that level; reclassification after planning start requires a reason, refused after execution. | requireTenant() (read); lib applyComplexity: requireWrite() | model method ea.audit.engagement.action_classify(answers, reason) + _propagate_file_index() |

| `generateDocumentAction` | app/actions/audit-file.ts | Generate (get-or-create) the working-paper document for a task and open it. | lib generateDocument: requireWrite() + visibleToUser (not-on-this-engagement) | model method ea.audit.task.action_generate_document() (button) returning act_window on ea.audit.document |

| `setDueDateAction` | app/actions/audit-file.ts | Set or clear a task's due date. | const { tenantId, role } = await requireTenant(); if (!canWrite(role)) redirect(...error=read-only-role) | native field write ea.audit.task.due_date (tracking=True) |

| `instantiateGroupTasksAction` | app/actions/audit-file.ts | Add a task group's not-yet-instantiated tasks (e.g. E2 IT) to an existing engagement, within the entity's complexity scope; idempotent. | const { tenantId, role } = await requireTenant(); if (!canReview(role)) redirect(back) | model method ea.audit.engagement.action_instantiate_group(group_id) |

| `signOffPreparerAction` | app/actions/audit-file.ts | P button on phase/group task list: generate the paper if needed and sign as preparer. | signOffFromList -> requireTenant(); lib generateDocument/signDocument: requireWrite(); signDocument rank rules | model method ea.audit.task.action_sign(role='preparer') (button) creating ea.audit.signoff |

| `signOffReviewerAction` | app/actions/audit-file.ts | R button: sign the task's paper as reviewer (recorded tier may become 'partner' when the rule requires the engagement partner). | as signOffPreparerAction; signDocument: requested reviewer requires canReview (requires-senior); partner tier requires c | ea.audit.task.action_sign(role='reviewer') |

| `signOffEqrAction` | app/actions/audit-file.ts | Engagement quality reviewer's own sign-off, C4.2 only. | signDocument: role eqr only on EQR_PAPER C4.2; isAppointedEqrTx else eqr-own-paper | ea.audit.task.action_sign(role='eqr') |

| `checkoutAction` | app/actions/audit-file.ts | Check a document out for local editing. | lib checkoutDocument: requireWrite() | model method ea.audit.document.action_checkout() (button, lock field) |

| `cancelCheckoutAction` | app/actions/audit-file.ts | Release the caller's own check-out. | lib cancelCheckout: requireWrite(); UPDATE ... WHERE checked_out_by = caller | ea.audit.document.action_cancel_checkout() |

| `restoreVersionAction` | app/actions/audit-file.ts | Restore an earlier document version as the new current version. | lib restoreVersion: requireTenant() (no write-role check in lib; proxy blocks read_only server actions? No — proxy lets  | ea.audit.document.action_restore_version(no) |

| `signAction` | app/actions/audit-file.ts | Sign the open document as preparer/reviewer/partner/eqr from the document page. | lib signDocument: requireWrite() + rank rules (requires-senior, requires-partner, forbidden for eqr off C4.2) | ea.audit.document.action_sign(role) |

| `reopenAction` | app/actions/audit-file.ts | Reopen a signed document: void its sign-offs with a reason. | lib reopenDocument: requireRole("manager"); report_date set -> requires-partner-after-report-date; floor rank -> cannot- | ea.audit.document.action_reopen(reason) via wizard |

| `addNoteAction` | app/actions/audit-file.ts | Add a review note on a document. | lib addReviewNote: requireWrite() | ea.audit.review.note.create() (or mail.message with note subtype) |

| `clearNoteAction` | app/actions/audit-file.ts | Clear a review note with a response. | lib clearReviewNote: requireWrite(); if (!atLeast(role, "manager")) ForbiddenError requires-manager-or-author; isPrepare | ea.audit.review.note.action_clear(response) |

| `updateBrandingAction` | app/actions/branding.ts | Firm branding settings: display name, accent colour, logo (<=150 KB png/jpeg as data URI), letterhead lines, footer, engagement naming convention. | lib updateBranding: requireWrite(); if (!canManageFirm(role)) throw BrandingError("forbidden") | native res.company fields (logo, primary_color, report header/footer) + ea.audit.settings (res.config.settings) |

| `updateClientMasterAction` | app/actions/clients.ts | Update client master data (registration number, NIU, address, year end, framework, PIE, sector, name, legal form); renamed clients propagate to convention-generated engagement titles in acceptance/planning. | const { tenantId, role } = await requireTenant(); if (role === "firm_admin") { ... } (others silently redirected back) | native res.partner write (ea.audit.client) with groups on fields + onchange renaming engagements |

| `setClientArchivedAction` | app/actions/clients.ts | Retire or reinstate a client in the register. | lib setClientArchived: requireWrite(); if (!canManageFirm(role)) throw ForbiddenError("forbidden") | native active flag (archive/unarchive) on ea.audit.client |

| `addCommentAction` | app/actions/comments.ts | Post a discussion comment (optionally threaded) on an engagement. | lib addComment: requireTenant() (membership checked in lib -> CommentError not-found) | native mail.message (chatter) on ea.audit.engagement |

| `finalAnalyticsAction` | app/actions/conclusion.ts | 7.3 Final analytical review on final figures, snapshotted into completion record C4.1. | lib recordCompletion: requireRole("senior") (+ assertMutable); analyticalReview: requireTenant() | model method ea.audit.engagement.action_final_analytics() writing ea.audit.completion.record |

| `fsTieoutAction` | app/actions/conclusion.ts | 7.4/7.5 FS tie-out: run checks against final TB and record result. | recordCompletion: requireRole("senior"); runFsTieout: requireTenant() | ea.audit.engagement.action_fs_tieout() |

| `disclosureChecklistAction` | app/actions/conclusion.ts | Record disclosure checklist completion (notes 1-36). | recordCompletion: requireRole("senior") | ea.audit.engagement.action_record_completion('disclosure_checklist') |

| `subsequentEventsAction` | app/actions/conclusion.ts | Record ISA 560 subsequent events review (reviewed-to date, events). | recordCompletion: requireRole("senior"); requireTenant for period end read | ea.audit.engagement.action_record_completion('subsequent_events') with constraint reviewed_to > period_end |

| `pointsForwardAction` | app/actions/conclusion.ts | Record points forward for next year. | recordCompletion: requireRole("senior") (archive check skipped for points_forward) | ea.audit.engagement.action_record_completion('points_forward') |

| `partnerConclusionAction` | app/actions/conclusion.ts | Partner's overall conclusion. | recordCompletion: requireWrite() then if (key === "partner_conclusion" && !canPartnerSignoff(role)) throw CompletionErro | ea.audit.engagement.action_partner_conclusion() restricted to group_partner |

| `generateConclusionLetterAction` | app/actions/conclusion.ts | Generate a conclusion-phase letter (management representation etc.) as a .docx document. | lib generateLetter: requireWrite() | report action qweb-docx/pdf ea_audit.report_letter_<kind> stored as ea.audit.document version |

| `issueReportAction` | app/actions/conclusion.ts | 7.9-7.11 decide opinion from flags, issue the report (phase -> conclusion, report_date, opinion) and generate the audit report document. | lib issueReport: requireWrite(); if (!canPartnerSignoff(role)) throw CompletionError("requires-partner"); generateAuditR | wizard ea.audit.issue.report.wizard -> ea.audit.engagement.action_issue_report() + report action for the audit report |

| `archiveAction` | app/actions/conclusion.ts | Archive the engagement after all archive gates pass; queues the backup job. | lib archiveEngagement: requireWrite(); if (!canPartnerSignoff(role)) throw CompletionError("archive-partner-only") | ea.audit.engagement.action_archive() + ir.cron/queue for backup |

| `rollforwardAction` | app/actions/conclusion.ts | Create next year's engagement from this one. | lib rollforward: requireWrite() | ea.audit.engagement.action_rollforward(new_year) (copy with carry-forward) |

| `rollforwardFromRegisterAction` | app/actions/conclusion.ts | Register variant of roll-forward; engagement id travels in the form. | as rollforwardAction | same method from list-view action |

| `generateLeadScheduleAction` | app/actions/data.ts | Generate the lead schedule workbook document for an E-section task from the current TB, preserving prior commentary. | lib generateLeadSchedule: requireWrite() | report action xlsx ea_audit.report_lead_schedule stored as document version |

| `assignSectionAction` | app/actions/data.ts | Assign an E-section (lead schedule) owner. | lib assignSection: requireWrite() | native field write ea.audit.task.owner_id |

| `raiseAnalyticsRiskAction` | app/actions/data.ts | Raise a potential risk from the analytics screen (source P3.2). | lib raisePotentialRisk: requireWrite() | ea.audit.potential.risk.create() |

| `saveApCommentsAction` | app/actions/data.ts | Save one lead schedule's commentary cells (c_* fields) from the analytical procedures grid. | lib saveApComments: requireWrite() | ea.audit.ap.comment write() |

| `saveDeficiencyEvaluationAction` | app/actions/deficiencies.ts | ISA 265 evaluation grid on C5.11 (F037): likelihood, magnitude, assertions, management awareness, indicators, related findings, aggregation note, grade, communication. | lib saveDeficiencyEvaluation: requireWrite() + assertMutable | model ea.audit.deficiency.evaluation write() (one2one on ea.audit.finding) |

| `setAllowedDomainsAction` | app/actions/email-domains.ts | Settings: allowed email domains for engagement-team invitations (F070). | lib setAllowedDomains: requireRole("firm_admin") | res.config.settings field on res.company (allowed_email_domains) |

| `runSamplingAction` | app/actions/engines.ts | Run the sampling engine (random/MUS/...) over a dataset for a task; stores run + generated workbook document. | lib runSampling: requireWrite() | model ea.audit.sampling.run.action_run() (wizard ea.audit.sampling.wizard) + xlsx report |

| `evaluateSamplingAction` | app/actions/engines.ts | Record misstatement found in the sample and project it. | lib evaluateSampling: requireWrite() | ea.audit.sampling.run.action_evaluate(misstatement) |

| `recordTodResultAction` | app/actions/engines.ts | Sampling tool results step (UAT B78): record ToD workbook findings, project to population, carry to C1.1. | lib recordTodResult: requireWrite() | ea.audit.tod.result.create() + projection to ea.audit.misstatement |

| `runReconFromAnalyzerAction` | app/actions/engines.ts | Agree a sub-ledger to its control account from the analyzer page. | lib runReconciliation: requireWrite() | ea.audit.dataset.action_reconcile() |

| `runReconAction` | app/actions/engines.ts | Same reconciliation from the E4 paper. | requireWrite() | same |

| `runSupplierReconAction` | app/actions/engines.ts | Supplier statement vs ledger reconciliation. | requireWrite() | ea.audit.dataset.action_supplier_recon() |

| `runJeTestingAction` | app/actions/engines.ts | Legacy journal-entry testing engine (large/unusual entries). | requireWrite() | superseded by je-selection; ea.audit.je.selection.run |

| `runAnalyticAction` | app/actions/engines.ts | Substantive analytic: expectation vs actual within tolerance for a task. | requireWrite() | ea.audit.task.action_run_analytic() |

| `completeStepAction` | app/actions/execution.ts | Complete a program step with its conclusion. | lib completeStep: requireTenant() (no write-role check) ; assertExecutionOpen | ea.audit.program.step.action_complete(conclusion) |

| `markStepNaAction` | app/actions/execution.ts | Mark a program step not applicable with rationale. | lib markStepNa: requireWrite() | ea.audit.program.step.action_mark_na(rationale) |

| `routeFindingAction` | app/actions/execution.ts | Route a finding from a section: B4 misstatement (amount, accounts, type, trivial confirmation) or C1 matter (severity), optionally raising a post-planning risk. | lib routeFinding: requireWrite() | wizard ea.audit.finding.route.wizard -> ea.audit.finding.create()/ea.audit.misstatement.create() |

| `raiseFindingAction` | app/actions/execution.ts | Raise a C1.2 matter or C5.11 deficiency from the findings register (section optional, UAT B21). | requireWrite() | ea.audit.finding.create() |

| `recordControlTestAction` | app/actions/execution.ts | Record a test of control result; deviation decisions extend/abandon/deficiency create follow-up steps, drop controls reliance or raise a deficiency. | lib recordControlTest: requireWrite() | ea.audit.control.test.create() with onchange side effects |

| `saveConclusionAction` | app/actions/execution.ts | Save a section conclusion (objectives achieved, rationale when no procedures). | lib saveSectionConclusion: requireWrite() | ea.audit.section.conclusion write() |

| `reviewConclusionAction` | app/actions/execution.ts | Review (senior+) or partner-review a section conclusion. | lib reviewSectionConclusion: requireWrite(); asPartner requires canPartnerSignoff else canReview (forbidden) | ea.audit.section.conclusion.action_review(as_partner) |

| `clearFindingAction` | app/actions/execution.ts | Clear a finding with a response. | lib clearFinding: requireWrite() | ea.audit.finding.action_clear(response) |

| `setCorrectedAction` | app/actions/execution.ts | Flag a misstatement corrected/uncorrected. | lib setMisstatementCorrected: requireWrite() | field write ea.audit.misstatement.corrected (tracking) |

| `approveRiskAdditionAction` | app/actions/execution.ts | Partner approves a risk added after planning. | lib approveRiskAddition: requireWrite(); if (!canPartnerSignoff(role)) throw ExecutionError("forbidden") | ea.audit.risk.action_approve_addition() (group_partner) |

| `generateDeadlinesAction` | app/actions/legal.ts | Generate the C5.2 statutory calendar (OHADA deadlines) from period end / AGM date. | lib generateDeadlines: requireWrite() | ea.audit.engagement.action_generate_deadlines() creating ea.audit.statutory.deadline (or mail.activity) |

| `setLegalDatesAction` | app/actions/legal.ts | Set AGM, planned report and board dates the AGM-relative deadlines derive from. | lib setLegalDates: requireWrite() | field writes on ea.audit.engagement with onchange |

| `markDeadlineDoneAction` | app/actions/legal.ts | Tick a statutory deadline done. | requireWrite() | ea.audit.statutory.deadline.action_done() |

| `addConventionAction` | app/actions/legal.ts | Add a regulated agreement (convention réglementée) to the register. | lib addConvention: requireWrite() | ea.audit.convention.create() |

| `rapportSpecialAction` | app/actions/legal.ts | Generate the special report on regulated agreements (.docx). | lib generateRapportSpecial: requireWrite() | report action (qweb/docx) ea_audit.report_rapport_special stored as document |

| `article715Action` | app/actions/legal.ts | Generate the OHADA article 715 report to the board (.docx). | requireWrite() | report action ea_audit.report_article_715 |

| `startAlerteAction` | app/actions/legal.ts | Start the procédure d'alerte (going-concern alert) with stage letter. | lib startAlerte: requireWrite() | model ea.audit.alerte (state machine) action_start() |

| `advanceAlerteAction` | app/actions/legal.ts | Move the alert to the next stage (or record a satisfactory reply = discontinue), generating the stage letter. | requireWrite() | ea.audit.alerte.action_advance(stage) |

| `resumeAlerteAction` | app/actions/legal.ts | Resume a discontinued alert within the legal window. | requireWrite() | ea.audit.alerte.action_resume() |

| `revealFaitAction` | app/actions/legal.ts | Record and generate the révélation de fait délictueux letter (partner only). | lib revealFait: requireWrite(); if (!canPartnerSignoff(role)) throw LegalError("forbidden") | ea.audit.fait.delictueux.create() + report, record rule restricting to group_partner |

| `irregularitiesAction` | app/actions/legal.ts | Generate the irregularities letter to AG or board. | requireWrite() | report action ea_audit.report_irregularities |

| `titresAttestationAction` | app/actions/legal.ts | Generate the securities (titres) inspection attestation. | requireWrite() | report action ea_audit.report_titres_attestation with precondition checks |

| `equityCheckAction` | app/actions/legal.ts | Run the equity < half share capital check; creates/removes the EGM deadline. | lib equityCheck: requireWrite() | ea.audit.engagement.action_equity_check() |

| `setShareCapitalAction` | app/actions/legal.ts | Record the client's share capital. | requireWrite() | field write ea.audit.client.share_capital |

| `cocacAction` | app/actions/legal.ts | Co-CAC (joint auditor) records F8: work split, cross review, disagreement, with optimistic concurrency. | lib recordCompletion: requireRole("senior") + assertMutable | ea.audit.completion.record write() with write_date check (stale-edit) |

| `setLocale` | app/actions/locale.ts | Switch UI language: cookie always, profile when signed in. | none required; const session = await auth(); if (session?.user?.id) persist | native res.users.lang / web client language switch |

| `sendTestNotification` | app/actions/notifications.ts | Dev helper: create a test notification for the current user. | const { tenantId, userId } = await requireTenant() | drop (bus.bus / mail.notification test) |

| `markRead` | app/actions/notifications.ts | Mark a notification read. | lib markNotificationRead: requireTenant() + user_id = caller | native mail.notification mark read |

| `addPbcItemAction` | app/actions/pbc.ts | Firm side: add a PBC request item (title, note). | lib pbc.addPbcItem: requireWrite() | ea.audit.pbc.item.create() |

| `chasePbcAction` | app/actions/pbc.ts | Remind the client of an outstanding request (email to portal contacts). | lib chasePbc: requireWrite() | ea.audit.pbc.item.action_chase() sending mail.template |

| `acceptPbcAction` | app/actions/pbc.ts | Accept an uploaded PBC response and file it as a document under a task. | lib acceptPbc: requireWrite(); if (!canReview(role)) throw PbcError("forbidden") | ea.audit.pbc.item.action_accept(task) creating ea.audit.document from the portal attachment |

| `attachPbcAction` | app/actions/pbc.ts | File an already-accepted upload under a task it was never attached to. | lib attachAcceptedPbc: requireWrite() + canReview | ea.audit.pbc.item.action_attach(task) |

| `uploadPbcAction` | app/actions/pbc.ts | Portal side: client user uploads a response file to a PBC item. | const session = await auth(); clientId = session?.user?.clientId; if (!clientId) throw Error("forbidden"); lib uploadPbc | native portal controller (odoo.addons.portal) /my/pbc/<id>/upload or portal form on ea.audit.pbc.item with ir.rule for portal users |

| `addPortalContactAction` | app/actions/pbc.ts | Create a client portal user (client_user membership) for a client. | lib addPortalContact: requireWrite(); if (!canReview(role)) throw PbcError("forbidden") | native portal.wizard (grant portal access to res.partner contact) |

| `setRetentionYearsAction` | app/actions/retention.ts | Firm retention period in years. | lib setRetentionYears: requireRole("firm_admin") | res.config.settings field retention_years on res.company |

| `placeLegalHoldAction` | app/actions/retention.ts | Place a legal hold on an engagement (blocks retention disposal). | lib placeLegalHold: requireRole("manager") | ea.audit.legal.hold.create() via wizard (group_manager) |

| `releaseLegalHoldAction` | app/actions/retention.ts | Release the active legal hold. | lib releaseLegalHold: requireRole("partner") | ea.audit.legal.hold.action_release(reason) (group_partner) |

| `saveSapAction` | app/actions/sap.ts | Substantive analytical procedure (F038) per index and assertion: expectation model, inputs, expected value, reliability, threshold override, actual, investigation, corroboration, conclusion. | lib saveSap: requireWrite() + assertMutable | model ea.audit.sap write() (one record per index+assertion) |

| `setSapThresholdsAction` | app/actions/sap.ts | Firm SAP threshold percentages (low/moderate/high). | lib setSapThresholds: requireRole("firm_admin") | res.config.settings fields on res.company |

| `saveFormAction` | app/actions/planning.ts | Save a planning/acceptance form (2.1/2.11) by its FORM_DEFINITIONS code; with handoff=1 also generate the paper and sign as preparer, landing on the group list. | lib saveForm: requireWrite() + assertNotEqrWrite(tenantId, engagementId, userId, role); handoff path: generateDocument/s | model ea.audit.form.response write() via dynamic form view on ea.audit.working.paper; handoff = action_save_and_handoff() button |

| `carryForwardAction` | app/actions/planning.ts | Carry forward prior-year form answers and related parties. | lib carryForwardFromPriorYear: requireWrite() | ea.audit.engagement.action_carry_forward() |

| `addRelatedPartyAction` | app/actions/planning.ts | Add a related party to the S4.3 register. | lib registers.writeRegister: requireWrite(); assertMutable; assertNotEqrWrite | ea.audit.related.party.create() |

| `removeRegisterLineAction` | app/actions/planning.ts | Soft-remove a related party or estimate register line. | writeRegister: requireWrite() + assertMutable + assertNotEqrWrite | ea.audit.related.party / ea.audit.estimate action_remove() (active=False) |

| `addEstimateAction` | app/actions/planning.ts | Add an accounting estimate to the S4.4 register. | writeRegister: requireWrite() + assertMutable + assertNotEqrWrite | ea.audit.estimate.create() |

| `generateLetterAction` | app/actions/planning.ts | Generate an acceptance-phase letter (engagement letter, etc.) once the entity is classified. | lib getEngagement: requireTenant(); generateLetter: requireWrite() | report action ea_audit.report_letter_<kind> stored as ea.audit.document |

| `markNotApplicableAction` | app/actions/planning.ts | Mark a task not applicable with reason, or clear the mark. | const { tenantId, userId, role } = await requireTenant(); if (!canReview(role)) throw Error("forbidden"); if (await acts | ea.audit.task.action_mark_na(reason)/action_clear_na() |

| `setMandateAction` | app/actions/planning.ts | Record the auditor's mandate type (statutes/AGO) and start year on the client. | const { tenantId } = await requireWrite() | field writes on ea.audit.client |

| `assignTeamAction` | app/actions/planning.ts | Add/replace a team member with a team role (partner, manager, senior, staff, eqr_reviewer) from the planning page; EQR objectivity declaration recorded. | lib assignTeamMember: requireTeamManager(engagementId, teamRole) = requireTenant(); if (role === "eqr_reviewer" || !atLe | ea.audit.team.member create/write with constraints (one2many on engagement) |

| `removeTeamAction` | app/actions/planning.ts | Remove a team member; their task assignments cleared, partner delegate cleared. | lib removeTeamMember: requireTeamManager(engagementId); partner removal needs atLeast partner; assertMutable | ea.audit.team.member.unlink() with ondelete handling |

| `assignTeamFromTeamPageAction` | app/actions/planning.ts | Team-page variant of assignTeamAction. | as assignTeamAction | same |

| `removeTeamFromTeamPageAction` | app/actions/planning.ts | Team-page variant of removeTeamAction. | as removeTeamAction | same |

| `transferEngagementPartnerAction` | app/actions/planning.ts | Hand the engagement partner seat to another firm partner (F003); outgoing partner keeps a chosen role or leaves. | lib transferEngagementPartner: requireWrite(); requireEngagementAccess; assertMutable; if (actorRole !== "firm_admin" && | ea.audit.engagement.action_transfer_partner(new_partner, outgoing_role) wizard |

| `setPartnerDelegateAction` | app/actions/planning.ts | Set or clear the partner to whom the engagement partner delegates sign-offs (F003). | lib setPartnerDelegate: requireWrite(); requireEngagementAccess; assertMutable; if (actorRole !== "firm_admin" && !partn | field write ea.audit.engagement.partner_delegate_id with constraint |

| `assignTaskAction` | app/actions/planning.ts | Assign/unassign a task to a team member. | const session = await auth(); if (!session?.user || !canReview(session.user.role)) throw Error("forbidden"); lib assignT | field write ea.audit.task.assignee_id (domain team members) + mail.activity |

| `assignFormsTasksAction` | app/actions/planning.ts | Bulk-assign tasks (assignee/preparer/approver role) from the Forms tool. | auth() + canReview else forbidden; lib assignTasks: requireWrite() + assertNotEqrWrite | server action (ir.actions.server) mass-assign on ea.audit.task |

| `setBudgetAction` | app/actions/planning.ts | Set budgeted hours for a grade. | lib setBudgetLine: requireWrite() | ea.audit.budget.line write() |

| `addPbcAction` | app/actions/planning.ts | Add a PBC item from the planning page. | lib team.addPbcItem: requireWrite(); requireEngagementAccess | ea.audit.pbc.item.create() |

| `createMaterialityAction` | app/actions/planning.ts | Create a materiality version (benchmark, %, performance %, trivial %, justifications). | lib createMaterialityVersion: requireWrite() | ea.audit.materiality.create() (versioned) with compute + constraints |

| `approveMaterialityAction` | app/actions/planning.ts | Partner approves a materiality version; previous approved superseded; misstatements re-flagged trivial. | lib approveMateriality: requireWrite(); if (!canPartnerSignoff(role)) throw Error("requires-partner") | ea.audit.materiality.action_approve() (group_partner) |

| `raiseRiskAction` | app/actions/planning.ts | Raise a potential risk from a form (source code). | lib raisePotentialRisk: requireWrite() | ea.audit.potential.risk.create() |

| `dismissPotentialAction` | app/actions/planning.ts | Dismiss a potential risk with rationale. | lib dismissPotentialRisk: requireTenant() (no write-role check) | ea.audit.potential.risk.action_dismiss(rationale) |

| `promotePotentialAction` | app/actions/planning.ts | Promote a potential risk into the risk register. | lib promotePotentialRisk: requireWrite() | ea.audit.potential.risk.action_promote() |

| `updateRiskAction` | app/actions/planning.ts | Update a risk's ratings, significance, controls reliance, status, category, inherent factors, FS note; checkbox fields only when their marker travelled. | lib updateRisk: requireWrite() | ea.audit.risk write() |

| `mapRiskAction` | app/actions/planning.ts | Map a risk to a section (task) with assertions. | lib mapRiskToSection: requireWrite() | ea.audit.risk.section (many2many with assertions) create |

| `rebutRiskAction` | app/actions/planning.ts | Partner rebuts the presumed revenue fraud risk (ISA 240) with justification. | lib rebutRevenueFraudRisk: requireWrite(); if (!canPartnerSignoff(role)) throw Error("rebut-partner-only") | ea.audit.risk.action_rebut(justification) (group_partner) |

| `linkRiskStepAction` | app/actions/planning.ts | Link a risk to a program step (response). | lib linkRiskToStep: requireWrite() | ea.audit.risk.response create (m2m) |

| `generateProgramAction` | app/actions/planning.ts | Generate the audit program steps for a task from the library and mapped risks. | lib generateProgram: requireWrite() | ea.audit.task.action_generate_program() |

| `addStepAction` | app/actions/planning.ts | Add a custom program step with assertions. | lib addCustomStep: requireWrite() | ea.audit.program.step.create() |

| `advanceToPlanningAction` | app/actions/planning.ts | Phase gate acceptance -> planning. | lib advanceToPlanning: requireWrite(); gates (GateError) | ea.audit.engagement.action_advance_to_planning() (state transition with gate checks) |

| `closePlanningAction` | app/actions/planning.ts | Phase gate planning -> execution; takes a planning snapshot. | lib closePlanning: requireWrite(); gates | ea.audit.engagement.action_close_planning() |

| `setMaterialAction` | app/actions/planning.ts | Flag an E-section material / not material. | lib setSectionMaterial: requireWrite() | field write ea.audit.task.material |

| `savePaperAction` | app/actions/planning.ts | Save a structured working paper's fields with optimistic concurrency (base version + per-field digests); on conflict or refusal the typed draft is kept in an httpOnly cookie for 30 min. | lib savePaper: assertMutable; requireWrite(); filterPaperWrite -> EQR rules (eqr-read-only / eqr-own-paper, C4.2 keys) | ea.audit.working.paper write() with write_date concurrency check (Odoo's native __last_update conflict) and per-field merge |

| `addRiskAction` | app/actions/planning.ts | Risk Console: hand-documented risk with category, level, ratings, factors, index link, assertions, management-missed, FS note. | lib addRisk: requireTenant() (no write-role check) | ea.audit.risk.create() |

| `linkRiskIndexAction` | app/actions/planning.ts | Link a risk to a lead index with threatened assertions. | lib linkRiskToIndex: requireWrite() | ea.audit.risk.lead.index create |

| `unlinkRiskIndexAction` | app/actions/planning.ts | Unlink a risk from a lead index. | lib unlinkRiskFromIndex: requireWrite() | unlink |

| `saveSignoffPolicyAction` | app/actions/signoff-policy.ts | Firm sign-off policy defaults: minimum reviewer role, tasks requiring partner, distinct preparer/approver. | lib savePolicy: requirePolicyEditor() = requireWrite(); if (!atLeast(role, "partner")) ForbiddenError("signoff-policy-pa | ea.audit.signoff.policy (one per company) write via res.config.settings |

| `saveTaskRulesAction` | app/actions/signoff-policy.ts | Per-task sign-off rules table (min preparer, min reviewer, partner required); only posted rows change. | lib saveTaskRules: requirePolicyEditor() | ea.audit.task.signoff.rule editable list (one2many) |

| `importSignoffMatrixAction` | app/actions/signoff-policy.ts | Import a completed sign-off matrix .xlsx (columns I-K); all-or-nothing after validating every row. useActionState shape. | await requirePolicyEditor() (returns {status:'invalid', error} on refusal) | wizard ea.audit.signoff.matrix.import.wizard (binary field + validation) |

| `createJournalAction` | app/actions/tb.ts | Create an adjusting journal from 'account;label;debit;credit' lines. | lib createJournal: requireWrite() | ea.audit.adjusting.journal create with one2many lines (balanced constraint) |

| `postJournalAction` | app/actions/tb.ts | Post a draft journal producing a new adjusted/final TB version. | lib postJournal: requireWrite() | ea.audit.adjusting.journal.action_post(kind) creating ea.audit.trial.balance.version |

| `addOverrideAction` | app/actions/tb.ts | Add a client-level account grouping override (prefix/exact -> section) with rationale. | lib addOverride: requireWrite() | ea.audit.grouping.override.create() |

| `deactivateOverrideAction` | app/actions/tb.ts | Deactivate a grouping override. | lib deactivateOverride: requireWrite() | active=False |

| `addTeamByEmailAction` | app/actions/team-independence.ts | Add a team member by email; unknown emails provision a staff account with temporary password and invitation mail. | lib addTeamMemberByEmail: requireTeamManager(engagementId, teamRole); assertMutable; assertEmailDomainAllowed | ea.audit.team.member.action_invite_by_email() creating res.users (auth_signup invitation) |

| `respondEngagementAction` | app/actions/team-independence.ts | Accept or decline an engagement invitation (decline needs reason, UAT B130). | lib respondToEngagement: requireTenant() (own team_member row) | ea.audit.team.member.action_accept()/action_decline(reason) on own record |

| `saveTemplateAction` | app/actions/templates.ts | Firm override of a working-paper template's purpose/items (EN/FR). | lib saveOverride -> requireAdmin(): requireTenant(); if (!canManageFirm(role)) throw TemplateError("forbidden") | ea.audit.wp.template.override write() |

| `resetTemplateAction` | app/actions/templates.ts | Remove the firm override for a template code. | requireAdmin() | unlink override |

| `logTimeAction` | app/actions/time.ts | Log time on an engagement/task. | lib logTime: requireWrite() | native account.analytic.line (hr_timesheet) or ea.audit.time.entry create |

| `deleteTimeAction` | app/actions/time.ts | Delete own time entry. | lib deleteTimeEntry: requireWrite(); DELETE ... WHERE user_id = caller | unlink with ir.rule user_id = uid |

| `inviteUserAction` | app/actions/users.ts | Invite a firm user (creates account with temporary password or re-attaches a pending one) and sends invitation. | lib inviteFirmUser -> requireAdmin(): requireTenant(); if (!canManageFirm(role)) throw UserAdminError("forbidden") | native res.users create + auth_signup reset-password invitation |

| `resendInviteAction` | app/actions/users.ts | Re-issue the set-password link to a pending user (UAT B87). | requireAdmin() | native res.users.action_reset_password() |

| `resetPasswordAction` | app/actions/users.ts | Admin resets another user's password (temporary, must change). | requireAdmin(); cannot-reset-self | native res.users password reset |

| `changeRoleAction` | app/actions/users.ts | Change a firm user's role. | requireAdmin(); cannot-change-self | native res.users groups write |

| `removeUserAction` | app/actions/users.ts | Remove a user from the firm: membership deleted, removed from live engagement teams, task assignments cleared, sessions revoked. | requireAdmin(); cannot-remove-self | native res.users archive (active=False) + cleanup hook |


### J.4 Database tables (final state)

| Table | Domain | Tenant-scoped | Odoo model |
| --- | --- | --- | --- |

| `tenant` | Tenant & users | False | res.company |

| `app_user` | Tenant & users | False | res.users (+ res.partner) |

| `membership` | Tenant & users | False | res.users.company_ids + res.groups (firm role) / portal user for client_user |

| `rls_probe` | Framework (pgmigrations, rls_probe) | True | (none - drop) |

| `client` | Clients | True | res.partner (is_company=True) + ea.audit.client (extension) |

| `engagement` | Engagement & team | True | ea.audit.engagement |

| `team_member` | Engagement & team | True | ea.audit.team.member |

| `budget_line` | Engagement & team | True | ea.audit.budget.line |

| `time_entry` | Engagement & team | True | account.analytic.line (hr_timesheet) or ea.audit.time.entry |

| `file_item` | File index & tasks | True | ea.audit.file.item (task) — optionally project.task |

| `template_override` | Templates & branding | True | ea.audit.template.override |

| `document` | Documents & sign-offs | True | ea.audit.document (+ ir.attachment for versions) |

| `document_version` | Documents & sign-offs | True | ir.attachment (one per version) + ea.audit.document.version |

| `signoff` | Documents & sign-offs | True | ea.audit.signoff |

| `review_note` | Review notes & comments | True | ea.audit.review.note (or mail.activity) |

| `comment` | Review notes & comments | True | mail.message (model ea.audit.engagement, message_type comment) |

| `task_attachment` | Attachments | True | ir.attachment (res_model ea.audit.file.item) + ea.audit.attachment.version |

| `form_response` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.answer (one2many on file item) or Json field per paper |

| `related_party` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.related.party |

| `accounting_estimate` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.accounting.estimate |

| `independence_campaign` | Engagement & team | True | ea.audit.independence.campaign |

| `independence_confirmation` | Engagement & team | True | ea.audit.independence.confirmation |

| `materiality` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.materiality |

| `materiality_specific` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.materiality.specific (o2m) |

| `potential_risk` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.potential.risk |

| `risk` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.risk |

| `risk_section` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.risk.section (m2m with assertions) |

| `risk_lead_index` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.risk.lead.index |

| `program_step` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.program.step |

| `risk_response` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | Many2many risk<->program_step |

| `planning_snapshot` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.planning.snapshot |

| `scot` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.scot |

| `scot_index` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.scot.index (o2m) |

| `wcgw` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.wcgw |

| `scot_control` | Sampling & ToC/ToD | True | ea.audit.control |

| `wcgw_control` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | Many2many wcgw<->control |

| `control_test` | Sampling & ToC/ToD | True | ea.audit.control.test |

| `toc_sample_draw` | Sampling & ToC/ToD | True | ea.audit.toc.sample.draw |

| `cra_assessment` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.cra.cell |

| `cra_assessment_history` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.cra.cell.history (or mail.tracking.value on cra cell) |

| `cra_index_setting` | Sampling & ToC/ToD | True | ea.audit.cra.index.setting |

| `trial_balance` | Trial balance & GL | True | ea.audit.trial.balance |

| `trial_balance_version` | Trial balance & GL | True | ea.audit.tb.version |

| `trial_balance_row` | Trial balance & GL | True | ea.audit.tb.line |

| `adjusting_journal` | Trial balance & GL | True | ea.audit.adjustment (not account.move: audit adjustments are not firm books) |

| `adjusting_journal_line` | Trial balance & GL | True | ea.audit.adjustment.line (o2m) |

| `trial_balance_version_journal` | Trial balance & GL | True | Many2many tb.version<->adjustment (with order) |

| `syscohada_grouping_rule` | Templates & branding | False | ea.audit.grouping.rule (global reference data, noupdate XML data) |

| `client_grouping_override` | Clients | True | ea.audit.client.grouping.override |

| `client_lead_index_override` | Clients | True | ea.audit.client.lead.index.override |

| `sub_ledger_dataset` | Trial balance & GL | True | ea.audit.dataset |

| `sub_ledger_row` | Trial balance & GL | True | ea.audit.dataset.row (Json) — or keep as attachment |

| `gl_line` | Trial balance & GL | True | ea.audit.gl.line (typed projection) — rebuildable from sub_ledger_row |

| `automation_run` | SAD/SAP/analytics | True | ea.audit.engine.run |

| `substantive_analytical_procedure` | SAD/SAP/analytics | True | ea.audit.sap.procedure |

| `evidence` | Attachments | True | ea.audit.evidence (+ ir.attachment for kind=file) |

| `finding` | Conclusion & archive | True | ea.audit.finding |

| `deficiency_evaluation` | Conclusion & archive | True | ea.audit.deficiency.evaluation (one2one on finding) |

| `misstatement` | SAD/SAP/analytics | True | ea.audit.misstatement (SAD) |

| `revise_log` | Planning (materiality/risks/CRA/SCOT/controls/ITGC/programs) | True | ea.audit.revise.log |

| `section_conclusion` | Documents & sign-offs | True | ea.audit.section.conclusion (one2one on file item) |

| `confirmation` | Confirmations | True | ea.audit.confirmation |

| `completion_record` | Conclusion & archive | True | ea.audit.completion.record |

| `legal_hold` | Retention & backup | True | ea.audit.legal.hold |

| `backup_job` | Retention & backup | True | ea.audit.backup.job (or drop; infra record) |

| `statutory_deadline` | Legal (OHADA) | True | ea.audit.statutory.deadline (+ mail.activity reminders) |

| `convention` | Legal (OHADA) | True | ea.audit.convention (conventions réglementées) |

| `alerte` | Legal (OHADA) | True | ea.audit.alerte |

| `alerte_event` | Legal (OHADA) | True | ea.audit.alerte.event (o2m) |

| `fait_delictueux` | Legal (OHADA) | True | ea.audit.fait.delictueux |

| `pbc_item` | Portal & PBC | True | ea.audit.pbc.item (portal-visible) + ir.attachment |

| `notification` | Notifications & activity | True | mail.notification / mail.message (inbox) — or drop |

| `activity_log` | Audit log & security | True | ea.audit.activity.log (append-only) — mail.message/mail.tracking.value insufficient |

| `login_attempt` | Audit log & security | False | (none — Odoo auth_brute_force / res.users.log) |

| `mfa_recovery_code` | Audit log & security | False | (none — re-enrol 2FA in Odoo) |

| `user_invite` | Audit log & security | False | (none — Odoo signup tokens on res.partner) |

| `uat_result` | UAT | True | ea.audit.uat.result (or export to spreadsheet) |

| `public_holiday` | Templates & branding | False | resource.calendar.leaves (global) or ea.audit.public.holiday |

| `firm_holiday` | Templates & branding | True | resource.calendar.leaves (company-scoped) or ea.audit.firm.holiday |

| `firm_signoff_policy` | Templates & branding | True | ea.audit.signoff.policy (one per company) or res.company fields |

| `firm_task_signoff_rule` | Templates & branding | True | ea.audit.signoff.rule (o2m on policy) |

| `pgmigrations` | Framework (pgmigrations, rls_probe) | False | (none — ir.module / migration ledger) |


**Proposed load order:** syscohada_grouping_rule → public_holiday → tenant → app_user → membership → firm_signoff_policy → firm_task_signoff_rule → template_override → firm_holiday(firm-wide rows) → client → client_grouping_override → client_lead_index_override → engagement → team_member → budget_line → independence_campaign → independence_confirmation → firm_holiday(engagement rows) → legal_hold → file_item → time_entry → form_response → related_party → accounting_estimate → materiality → materiality_specific → potential_risk → risk → risk_section → risk_lead_index → program_step → risk_response → planning_snapshot → scot → scot_index → wcgw → scot_control → wcgw_control → toc_sample_draw → cra_assessment → cra_assessment_history → cra_index_setting → document → document_version → signoff → section_conclusion → review_note → task_attachment → comment → trial_balance → trial_balance_version → trial_balance_row → adjusting_journal → adjusting_journal_line → trial_balance_version_journal → sub_ledger_dataset → sub_ledger_row → gl_line → automation_run → evidence → control_test → finding → deficiency_evaluation → misstatement → revise_log → substantive_analytical_procedure → confirmation → statutory_deadline → convention → alerte → alerte_event → fait_delictueux → pbc_item → completion_record → backup_job → notification → activity_log → uat_result
