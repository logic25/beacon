# Ordino — "New Content" Notification Bell (spec)

**Goal:** on Ordino's `/content` page, show a notification **bell with a badge**
that tells the team when Beacon has generated new content candidates to review —
replacing the idea of a Google Chat ping. Clicking the bell lists the new
candidates and clears the badge.

This is an **Ordino-side (Lovable/Supabase) change.** Beacon already does its part:
it auto-generates candidates on a daily schedule and writes them to the Supabase
`content_candidates` table (the same table Ordino's `/content` page reads).

---

## Data source

Candidates live in Supabase table `content_candidates`. Relevant columns:

- `id` (text)
- `title` (text)
- `priority` (`high` | `medium` | `low`)
- `content_type` (`blog_post` | `newsletter`)
- `team_questions_count` (int)
- `status` (`pending`, `drafted`, `review`, `approved`, `published`, `skipped`)
- `created_at` (ISO timestamp)

"New to review" = `status = 'pending'` AND `created_at > <user's last-seen time>`.

You can query Supabase directly (preferred, enables realtime), **or** call Beacon
through the existing `beacon-proxy` action:

```
GET /api/content/notifications?since=<ISO8601>
→ { success, pending_count, new_count, new: [...], pending: [...] }
```

`new_count` is the badge number; `new` is the dropdown list. Omit `since` to treat
all pending candidates as unseen.

---

## Per-user "last seen"

The badge is per user, so store when each user last opened the bell. Two options:

1. **Supabase table (recommended, syncs across devices):**
   ```sql
   create table content_notification_reads (
     user_email text primary key,
     last_seen_at timestamptz not null default now()
   );
   ```
   Read `last_seen_at` on load; write `now()` when the user opens/clears the bell.

2. **Local only (simplest):** keep `last_seen_at` in `localStorage`. Fine if
   per-device is acceptable.

---

## UI behavior

1. On `/content` load, compute `newCandidates = pending where created_at > last_seen_at`.
2. Render a bell icon in the page header/sidebar with a badge = `newCandidates.length`
   (hide badge when 0). Color it by highest priority present (red = has `high`).
3. Clicking the bell opens a dropdown listing each new candidate:
   `[PRIORITY] Title — N team questions`, newest first, each linking to that
   candidate in the pipeline.
4. Provide "Mark all as read" (and mark-on-open): set `last_seen_at = now()`,
   which clears the badge.
5. **Realtime (optional, nice):** subscribe to Supabase `postgres_changes` on
   `content_candidates` INSERT where `status = 'pending'` and bump the badge live
   without a refresh.

---

## Acceptance criteria

- [ ] Bell appears on `/content` with a badge equal to the count of pending
      candidates created since the current user last opened it.
- [ ] Badge is 0/hidden when there's nothing new; reappears when Beacon's daily
      job creates a new candidate.
- [ ] Opening the bell lists the new candidates (title, priority, question count)
      and each links to the candidate.
- [ ] "Mark all as read" / opening the bell clears the badge and persists per user.
- [ ] No dependency on Google Chat.

---

## Notes / handoff

- Nothing else in Beacon needs to change for this. If `new_count` is always 0 in
  production, confirm Beacon has `SUPABASE_URL` + `BEACON_ANALYTICS_KEY` set (so
  candidates save to Supabase, not just SQLite) and that the daily
  `CONTENT_SCHED_INTERVAL` job is running — check `GET /api/content-scheduler/status`.
- Good candidate for Claude Code inside the Ordino repo: point it at this file.
