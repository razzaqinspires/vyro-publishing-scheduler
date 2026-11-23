# Changelog

## 1.2.0 — Approval-gated queue
- Added mandatory operator approval before a job can be claimed by the scheduler.
- Added approval revocation, status summary, stronger idempotency conflict detection, and metrics validation.
- Existing unapproved scheduled jobs are migrated to `PENDING_APPROVAL` for safety.
- Kept the scheduler independent from the public VYRO website.
