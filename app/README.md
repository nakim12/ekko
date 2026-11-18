# app

Public Riot ID lookup with a personal tilt report (Phase 6). Don't start until Phase 4 results exist.

- `api/`: FastAPI, job queue with leases, SSE progress, empirical Bayes per-player estimates
- `web/`: Next.js + TypeScript + Tailwind on Vercel; footer carries Riot's legal notice

Needs a Riot production key; apply once the prototype works.
