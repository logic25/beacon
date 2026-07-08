# Ordino — "New Content" Notification Bell (spec)

## Goal
Show a bell on `/content` with a badge counting `content_candidates` rows where
`status='pending'` and `created_at >` the current user's last-seen timestamp.
Opening the bell lists them and clears the badge. Replaces the Google Chat ping idea.

## Scope
Ordino-side only. Beacon already writes to `content_candidates`. No changes to
Beacon or the beacon-proxy.

## Steps

### 1. Per-user "last seen" table (migration)
New table `content_notification_reads`, keyed by `auth.users.id` (not email —
matches every other RLS pattern in this repo):

```
user_id       uuid PK references auth.users on delete cascade
last_seen_at  timestamptz not null default now()
updated_at    timestamptz not null default now()
```

- Grants: `SELECT, INSERT, UPDATE` to `authenticated`; `ALL` to `service_role`.
- RLS enabled. Policy: users can select/insert/update only rows where
  `user_id = auth.uid()`.
- Update trigger on `updated_at`.

Also enable realtime on the candidates table:
`ALTER PUBLICATION supabase_realtime ADD TABLE public.content_candidates;`
(Skip if already added — check first.)

### 2. Hook: `useContentNotifications`
New file `src/hooks/useContentNotifications.ts`. Responsibilities:

- Fetch current user's `last_seen_at` (upsert a default row on first load).
- Query `content_candidates` where `status='pending'` ordered by `created_at desc`,
  select `id, title, priority, content_type, team_questions_count, created_at`.
- Derive `newCandidates = candidates.filter(c => c.created_at > last_seen_at)`.
- Subscribe to `postgres_changes` INSERT/UPDATE on `content_candidates` inside a
  `useEffect`, invalidate the query on change. Tear channel down on unmount (per
  the cloud-realtime rule).
- `markAllRead()` mutation → upsert `last_seen_at = now()`, invalidate.

Returns: `{ newCandidates, allPending, newCount, highestPriority, markAllRead, isLoading }`.

### 3. Component: `ContentNotificationBell`
New file `src/components/content/ContentNotificationBell.tsx`. Popover trigger =
`Bell` icon (lucide) with a `Badge` overlay:

- Hidden when `newCount === 0`.
- Color: red-ish when `highestPriority === 'high'`, amber for medium, muted for
  low. Uses semantic tokens defined in `index.css` (no hardcoded hex/`bg-red-500`
  — follow the design-system rule).
- Popover content: list of new candidates, newest first, one row each =
  `[PRIORITY badge] Title — N team questions`. Clicking a row scrolls to / opens
  that candidate in the pipeline (emit an event or accept an `onSelect` prop that
  the Content page wires to its existing candidate opener).
- Footer button: "Mark all as read" → calls `markAllRead()`.
- Opening the popover also calls `markAllRead()` (mark-on-open), so the badge
  clears immediately.

### 4. Wire into `/content`
In `src/pages/Content.tsx`, add `<ContentNotificationBell onSelect={...} />` into
the header row (lines 741–747), next to the "Compose from Scratch" button. Pass a
handler that opens the matching candidate card the same way clicking a pipeline row
does today.

### 5. Acceptance verification
Playwright pass:

- Visit `/content` as an authed user → bell renders, badge count == pending rows
  newer than `last_seen_at`.
- Click bell → dropdown lists those candidates → badge disappears.
- Insert a new `pending` row via SQL → badge reappears without refresh (realtime).

## Technical notes
- Uses `auth.uid()` throughout (not email) so RLS is trivial and matches the rest
  of the app.
- Query key: `["content-notifications", userId]`. Invalidated by the realtime
  channel and by `markAllRead`.
- No dependency on Google Chat, no changes to `beaconApi.ts`, and no calls to
  `/api/content/notifications` — we query Supabase directly so realtime works.
- Falls back gracefully if realtime isn't enabled: badge still updates on the next
  page load / react-query refetch.

## Out of scope
- Bell in the global `TopBar` (spec asks for /content page bell only).
- Notification for stage transitions (drafted/review/approved). Only new `pending`
  candidates count as "new."
- Beacon-side changes.

---

### Beacon-side dependency (already done, not part of this Ordino work)
For the badge to ever be non-zero, Beacon must be writing candidates into the
Supabase `content_candidates` table. That is handled: `run_auto_generate` now saves
via the engine's Supabase-first path, and the daily `ContentScheduler`
(`/api/content-scheduler/status`) runs it. Requires `SUPABASE_URL` +
`BEACON_ANALYTICS_KEY` set in Beacon's environment.
