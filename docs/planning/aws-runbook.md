# AWS Deployment Runbook & Operations Plan

Companion to [aws-deployment.md](aws-deployment.md), which answers *what and
how much*. This document answers *how, in what order, and who keeps it
running*. Target: **State 1 lean** (Fargate + RDS, no NAT, Langfuse Cloud,
~$56/mo + tokens), reached in five phases.

---

## Part 1 — Code-change audit (verified against the code, Sept 2026)

Verdict: the architecture is deployment-friendly — config is fully
env-driven (`app/config.py` is the only reader), the LLM/tool gateways are
single chokepoints, Langfuse degrades gracefully when unreachable, and
`tracer.flush()` runs per request. **The gaps are packaging and data
provenance, not re-architecture.**

### Blocking — the app cannot deploy (or survive contact) without these

**B1. The FAQ knowledge base is not reproducible from git.** Found during
this audit: `.gitignore`'s `*.sqlite3` rule excludes
`datasources/vector_database/chroma.sqlite3` — the Chroma catalog that binds
collections to the (tracked) HNSW segment files — and the raw FAQ dump was
removed from the repo. A fresh clone therefore has orphaned binary segments
and **no working FAQ collection**; `create_vectordb.py` has nothing to read.
Fix: restore the raw FAQ corpus to the repo (small text; it is the *source*,
the embeddings are derived), and build the collection at **image build time**
via `create_vectordb.py`. Do not commit `chroma.sqlite3` — it would also
carry user-memory segments (user data does not belong in git).

**B2. Dockerfile + entrypoint (none exist).** `docker-compose.yml` is the
Langfuse stack only. Needed:
- `python:3.11-slim` base; install from a new `requirements-prod.txt` =
  `requirements-ci.txt` minus pytest, plus `uvicorn`, `sentence-transformers`
  with **CPU-only torch** (`--index-url .../whl/cpu` — otherwise the CUDA
  wheels add ~4 GB to the image for nothing).
- Copy `app/ prompts/ scripts/ create_vectordb.py` + FAQ corpus; `WORKDIR
  /app` (the code resolves `prompts/`, `app/static`, `vector_db_path`
  relative to CWD — correct by construction once WORKDIR is set).
- Build steps: **bake the MiniLM model** (`sentence-transformers` download at
  build, ~80 MB) and **build the FAQ Chroma collection** into the image.
  Cold starts then need no network besides OpenAI.
- Entrypoint: run migrations, then `uvicorn app.main:app --host 0.0.0.0
  --workers 2`.
- `.dockerignore`: `.env`, `datasources/`, `code_repos/`, `docs/`, `notes/`,
  `tests/`, `.git`.

**B3. Migration race under 2+ tasks.** `scripts/db/migrate.py` has no
concurrency guard — two Fargate tasks booting simultaneously can both pass
the "not yet applied" check and double-apply a migration. Five-line fix:
`SELECT pg_advisory_lock(...)` around `apply_migrations()`. (Belt-and-braces
alternative for later: CD runs migrate as a one-off task before the service
update; keep boot-time migrate for the single-task era.)

**B4. Writable vector path for user memory.** FAQ embeddings can be baked
into the image (read-only, fine), but `user_memory` writes to the same
`vector_db_path` — a container filesystem loses it on every deploy. Split the
paths: `FAQ_VECTOR_PATH` baked in the image, `vector_db_path` → EFS mount
(`/data/vector_db`). Small config + two-constructor-arg change. (This whole
item evaporates when the planned pgvector swap lands — which is the argument
for doing that swap early.)

**B5. Fail fast on default secrets.** `jwt_secret` defaults to
`"change-me-in-.env"` and the app boots happily with it. Add a startup guard:
refuse to start when `jwt_secret` is the default and an `ENVIRONMENT=prod`
flag is set. Cheap insurance against the worst quiet misconfiguration.

### Explicitly NOT needed (verified — resist the urge)

- **No secrets-SDK code in `config.py`.** Pydantic Settings reads real env
  vars first; ECS task definitions inject Secrets Manager values *as env
  vars* (`secrets:` block). The earlier plan's "secrets source swap" is
  task-definition wiring, zero code. Just never bake `.env` into the image.
- **No CORS middleware** — the SPA is served same-origin from the API.
- **No Langfuse code changes** — point `LANGFUSE_BASE_URL`/keys at Langfuse
  Cloud; the tracer already degrades gracefully if it is unreachable.
- **No shutdown-flush hook** — `runner.py` flushes per request.
- **No streaming rework yet** — `--workers 2` + task count covers T0/T1;
  streaming (story 2.4) is a capacity requirement before T2, not before v1.

### Should-fix in the first two weeks (not launch-blocking)

| # | Item | Why |
| --- | --- | --- |
| S1 | `/health/ready` doing `SELECT 1` | `/health` is static — ALB keeps routing to a task whose DB link died |
| S2 | Tool-call timeouts in the gateway | known debt; a hung tool call holds a worker for the full LLM retry budget |
| S3 | Delete dead `db_path` (SQLite) setting | enterprise data lives in Postgres since the migration; the setting misleads |
| S4 | Change `demo123` before any non-team exposure | nine users share a published password |
| S5 | Log formatter: add date, consider JSON | CloudWatch stamps arrival time; queryable fields help metric filters |
| S6 | Rate limiting story | until WAF (State 2): ALB + 60-min token TTL is all there is |

---

## Part 2 — Deployment runbook (five phases to State 1)

**IaC stance (tradeoff, decided):** first deploy via scripted AWS CLI calls
checked into `scripts/aws/` — one env, three people, fastest path to a URL,
and every step reviewable. Codify into Terraform **before State 2** (when
resources multiply and drift starts costing). Terraform-from-day-one was
rejected: it front-loads a learning curve onto the person deploying while the
resource shape is still moving.

### Phase 0 — Prerequisites (half a day, mostly console)
1. AWS account + region `us-east-1`; enable IAM Identity Center for humans.
2. **AWS Budgets alert first** — $100/mo threshold, email. Before any
   resource exists.
3. Langfuse Cloud: create org/project, note the three keys (replaces the
   local Docker stack in AWS — keep self-host for laptops).
4. GitHub OIDC: create the `github-actions-deploy` IAM role trusted for this
   repo — no long-lived AWS keys ever land in GitHub secrets.
5. Domain decision: Route 53 hosted zone (or skip and use the raw ALB DNS
   name for the demo phase — TLS via ACM needs a domain, so "skip" means
   HTTP-only demo).

### Phase 1 — Package (1–2 days, all local, no AWS)
1. Land B1–B5 as one branch: FAQ corpus restored + build script, Dockerfile
   + `.dockerignore` + `requirements-prod.txt`, advisory lock, vector-path
   split, secrets guard.
2. Local proof: `docker build`, run the container against the laptop's
   Postgres (`host.docker.internal:5433`), then **run the golden set against
   the container** — same 16 cases, same pass bar. The image is "done" when
   goldens pass against it, not when it boots.

### Phase 2 — Foundation (half a day, scripted)
1. VPC: 2 public subnets, 2 AZs. No NAT (documented v1 stance: tasks get
   public IPs; security groups do the fencing).
2. Security groups: `alb-sg` (443/80 from world) → `app-sg` (8000 from
   alb-sg only) → `rds-sg` (5432 from app-sg only).
3. ECR repository; RDS PostgreSQL 16 `db.t4g.micro`, 20 GB gp3, single-AZ,
   7-day automated backups, **not publicly accessible**.
4. EFS (until pgvector): one access point, mounted `/data` in the task.
5. Secrets Manager: `openai-api-key`, `jwt-secret` (fresh random),
   `langfuse-keys`; `app-db-url` from the RDS endpoint.
6. CloudWatch log group `/insureagent/app`, 30-day retention.

### Phase 3 — First deploy (half a day)
1. Push image to ECR (manual `docker push` this once).
2. Task definition: 0.5 vCPU / 1 GB; `secrets:` refs for the four secrets;
   env: `VECTOR_DB_PATH=/data/vector_db`, `MEMORY_ENABLED=true`,
   `ENVIRONMENT=prod`; EFS volume; awslogs driver.
3. **One-off seeding (explicit, never in the entrypoint):** ECS RunTask with
   command `python scripts/seed_enterprise.py && python scripts/seed_users.py`.
   `seed_enterprise` wipes tables — it must stay a deliberate human act.
4. ECS service (1 task) + ALB: target group on `/health`, idle timeout 60 s
   (> the 8–20 s graph latency), HTTPS listener + HTTP→HTTPS redirect if a
   domain exists.
5. Smoke checklist (in order): `/health` 200 → login `USR001` → "what is my
   premium" gets a grounded answer → trace visible in Langfuse Cloud with
   correct user/session mapping → feedback thumb lands as a score → RDS
   `memory_items` row appears after 4 messages.

### Phase 4 — CD (half a day)
Extend `.github/workflows/ci.yml` with a `deploy` job: on push to `main`,
after `unit` and `golden-eval` pass → OIDC auth → build & push image (tagged
with the git SHA) → register new task definition revision → RunTask migrate →
`update-service`. **Rollback is redeploying the previous task-definition
revision** — one command, and the reason image tags are SHAs, not `latest`.

### Phase 5 — Fast follows (the standing order from the deployment plan)
pgvector swap (kills EFS and B4) → 2-task HA + NAT when it stops being a
demo → State 2 pieces as their features land.

---

## Part 3 — Operations plan

### 3.1 The release loop (unchanged discipline, new tail)
PR → CI unit tests → review → merge → golden eval (16 cases, 80% floor,
security cases hard-fail) → CD deploy. The eval gate stays mandatory; a
red golden run blocks deploy exactly like a red unit test. Feature flags
(`COMPLEXITY_ROUTING_ENABLED`, `PROMPT_SOURCE`) flip only alongside an eval
run — the discipline that caught three real regressions locally is now the
production gate.

### 3.2 Monitoring — three panes, no overlap
| Pane | Watches | Signals |
| --- | --- | --- |
| **CloudWatch** | infrastructure + logs | alarms below; metric filters on the structured log lines (`ERROR`, login failures, tool-denial 🔧 lines) |
| **Langfuse Cloud** | quality + token cost | traces per turn, feedback scores, per-agent token spend from CallRecords |
| **AWS Budgets** | money | $100 warning, hard-review at 2× forecast |

Day-one alarms (all → one SNS topic → email):
ALB 5xx > 5/5 min · healthy targets < 1 · RDS CPU > 80%/15 min · RDS storage
< 15% · RDS connections > 80% of max · log metric `ERROR` > 10/5 min · login
failures > 20/5 min (credential stuffing tell) · Budgets threshold.

### 3.3 Incident cards (the four that will actually happen)
- **OpenAI outage/degradation:** symptom — turns time out, `ERROR` alarm.
  The gateway already retries + tier-falls-back; beyond that, post a banner,
  wait it out. Do *not* restart tasks — nothing is wrong with them.
- **Bad deploy:** symptom — goldens passed but prod behaves worse (feedback
  thumbs, Langfuse traces). Action: redeploy previous task-def revision
  (minutes), then reproduce via trace → new golden case → fix. The
  USR001-incident loop, now as the standard incident path.
- **DB trouble:** RDS single-AZ means an AZ event = downtime until restore.
  Action: restore latest PITR snapshot, repoint the secret, restart service.
  Accepted risk until State 3 Multi-AZ (+$14).
- **Secret rotation:** JWT secret — rotate in Secrets Manager, force new
  deployment; every session invalidates (60-min TTL makes this a non-event —
  schedule it, don't fear it). OpenAI key — two-step: add new key, deploy,
  revoke old.

### 3.4 Backup & DR (write it down once)
RDS PITR + 7-day snapshots ⇒ **RPO ≤ 5 min** for all authoritative data —
Postgres holds everything, by design. Chroma/EFS is a *rebuildable index*
(memory embeddings re-derivable from `memory_items` rows; FAQ rebuilt from
the corpus in git) — add the small `rebuild_index.py` to the ops backlog and
DR becomes: restore RDS, redeploy image, rebuild index. **RTO ~1–2 h,
manual.** Good enough until State 3.

### 3.5 Cost operations (15 min, weekly)
Budgets vs. forecast → Langfuse token dashboard (cost per turn drifting from
the $0.008–0.015 band? which agent?) → top-5 most expensive traces (usually
iteration-cap loops — each one is a routing bug wearing a cost hat) → tier
check against the traffic table in aws-deployment.md. Levers, in order, are
already documented there (complexity routing first).

### 3.6 Security operations
GitHub OIDC only (no stored AWS keys) · Dependabot on `requirements*.txt` ·
demo passwords rotated before any non-team user (S4) · quarterly SG/IAM
review · WAF lands with State 2 · Krishna's guardrails middleware has a
reserved mount point in `app/main.py` — the ops hook for prompt-injection
defense sits there, not in AWS.

### 3.7 Ownership (proposed — to be agreed with the team)
| Area | Proposed owner |
| --- | --- |
| Deploy pipeline, AWS infra, auth & secrets | Syam |
| Guardrails, security review, WAF rules (State 2) | Krishna |
| CI quality gates, code standards, dependency hygiene | Jayanth |
| Golden set curation & eval triage | rotating, weekly |

Not on-call — a **business-hours "who looks first"** map. Alarms go to a
shared channel; the owner column is who triages, not who is paged at 3 a.m.
That posture changes only when real customers do.
