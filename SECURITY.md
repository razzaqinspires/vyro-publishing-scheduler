# Security Policy

- Internal operator queue only; do not connect it to the public website.
- New jobs remain pending until an operator explicitly approves them.
- Use unique idempotency keys and avoid putting personal data in captions or metadata.
- Keep the SQLite database private and back it up using an access-controlled method.
