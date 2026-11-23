# VYRO Publishing Scheduler

**Release:** 1.2.0 · **Python:** 3.11+ · **Storage:** SQLite WAL.

This is an internal queue and analytics component. It is not connected to the public VYRO Media Library website. Live publication remains the responsibility of `vyro-instagram-publisher` and requires its own operator approval.

## Safety and queue states
- New jobs start at `PENDING_APPROVAL` and cannot be claimed.
- An operator must run `vyro-scheduler approve <job_id>` to move a job to `SCHEDULED`.
- The worker claims approved due jobs with a lease and bounded attempt count.
- Expired leases are recovered; completed jobs become `PUBLISHED`; exhausted jobs become `FAILED`.
- `idempotency_key` is unique. Reusing the same key with a different payload is rejected.

## Usage
```bash
pip install -e '.[dev]'
vyro-scheduler init
vyro-scheduler add --content-id vyro-demo-01 --video-url https://cdn.example/video.mp4 --caption "Caption" --at "2026-11-24T19:30:00+07:00" --idempotency-key "vyro-demo-01-reel-01"
vyro-scheduler approve <job_id>
vyro-scheduler due --limit 5
vyro-scheduler status
```

Record post metrics with `vyro-scheduler metrics`; inspect account-specific exploratory time-slot rankings with `vyro-scheduler recommend-slots`. Sample-size and retention caveats apply. These scores are not Instagram ranking signals and cannot guarantee reach or virality.
