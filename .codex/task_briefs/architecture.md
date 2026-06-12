# Architecture Brief

1. Read `docs/ai/PROJECT_MAP.md` and `docs/ai/RESTRUCTURE_MIDPOINT_AUDIT.md`.
2. Keep shell, feature UI, services, domain rules, and workers separated.
3. Do not mutate archives from UI code.
4. Preserve public facades during moves.
5. Treat Graphify as advisory only.
6. Validate with architecture guard tests plus feature-specific behavior tests.
