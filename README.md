# VYRO Publishing Scheduler

**Repository:** `vyro-publishing-scheduler`  
**Purpose:** persistent content queue, due-job leasing, retry policy, publication audit trail, metrics ingestion, and data-backed posting-slot recommendations.

## Boundary

This repository owns queue state and timing decisions. It does not call Instagram, generate AI content, or render videos. A future orchestrator claims a due job, calls the relevant component, then records the outcome here. This separation prevents the scheduler from binding itself to one publisher implementation.

## State machine

`DRAFT → SCHEDULED → PROCESSING → PUBLISHED`  
`PROCESSING → RETRY_WAIT → PROCESSING` (bounded attempts)  
`PROCESSING → FAILED` (terminal)

Claims use SQLite transactions with a lease. A crashed worker's expired lease can be safely returned to the queue. `idempotency_key` prevents duplicate scheduling requests.

## Performance scoring

The slot recommender compares the actual account's historical posts by local publishing hour. It uses reach-normalized signals (shares, saves, comments, profile visits, follows, and inquiries) and Bayesian-style shrinkage toward the account-wide baseline when a time slot has few observations. It does not claim that the score is Meta's recommendation algorithm or guarantee viral reach. Recommendation output includes sample size and confidence tier.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## CLI

```bash
vyro-scheduler init
vyro-scheduler add --content-id vyro-001 --video-url https://cdn.example.com/vyro.mp4 --caption "Approved caption" --at "2026-11-24T19:30:00+07:00"
vyro-scheduler due --limit 10
vyro-scheduler complete JOB_ID --media-id INSTAGRAM_MEDIA_ID
vyro-scheduler fail JOB_ID --reason "Temporary API outage" --retry-in 300
vyro-scheduler metrics JOB_ID --views 1200 --reach 900 --shares 22 --saves 31 --comments 7 --profile-visits 18 --follows 5 --inquiries 2
vyro-scheduler recommend-slots
```

Default timezone is `Asia/Jakarta`. Set `TIMEZONE` and `VYRO_SCHEDULER_DB` to control timezone and persistent database path. Store timestamps with offsets; never assume server-local timezone. The CLI creates the database only when a command is executed, not during module import.

## Initial experimentation protocol

Test 07:30, 12:15, and 19:30 WIB as hypotheses—not platform-published algorithm timings. Rotate formats fairly. Collect enough posts per slot before changing the plan. Compare medians and business outcomes (qualified inquiries/orders), not only views.

## Operations

- Back up the SQLite database before upgrades.
- Keep the queue DB on reliable persistent storage; avoid shared network filesystems for concurrent writers.
- Use a single writer/worker initially; scale only after moving to a database with server-side concurrency controls.
- Set a sensible per-day publishing cap in the orchestrator.
- The scheduler never mass-posts, auto-engages, buys interactions, or sends unsolicited DMs.
