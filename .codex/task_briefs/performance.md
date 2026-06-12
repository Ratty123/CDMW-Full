# Performance Brief

1. Identify the measured or reported bottleneck.
2. Keep slow work off the UI thread.
3. Prefer workers or services for long-running operations.
4. Avoid broad rewrites unless measurement requires them.
5. Add or update responsiveness/performance guard tests when feasible.
6. Run targeted checks from `docs/ai/TEST_MATRIX.md`.
