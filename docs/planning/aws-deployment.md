# AWS Deployment Plan — Resources, Improvements, Costs

All prices ≈ monthly, us-east-1, on-demand, Sept 2026 — verify in the AWS
Pricing Calculator before committing; free-tier credits (first 12 months) can
zero several lines. LLM token spend is separate from infra and scales with
usage in every state.

## The app's real runtime needs (what must exist anywhere it runs)

FastAPI monolith (uvicorn) · PostgreSQL 16 (all data incl. memory) · Chroma
files on disk (FAQ + user_memory embeddings; MiniLM model ~80 MB loads at
startup) · outbound HTTPS to OpenAI · optional Langfuse (self-host stack OR
cloud) · secrets (OpenAI key, JWT secret, DB URL) · migrations+seeds on first
boot.

---

## State 0 — exact structure, lift-and-shift (one VM)

Truthful "as is": one EC2 VM running docker compose (app + Postgres +
optionally the Langfuse stack), exactly like the laptop.

| Resource | Purpose | ~$/mo |
| --- | --- | --- |
| EC2 t4g.medium (2 vCPU/4 GB; Langfuse stack needs the RAM) | everything | 24.50 |
| EBS gp3 30 GB | disk (PG data, Chroma, images) | 2.40 |
| Elastic IP (attached) | stable address | 3.60 |
| Route 53 hosted zone (optional) + data transfer | DNS, egress | ~2 |
| **Total infra** | | **~$32–40** |

Pros: cheapest, zero re-architecture, Langfuse self-host fits. Cons: single
point of failure, you patch the VM, no autoscaling, deploys are SSH+compose.
Fine for a shared team demo; not the target.

## State 1 — minimal managed (recommended first real deployment)

The same monolith, containerized, on managed services. Maps to register M2's
core without the heavy tail.

| Service | Purpose / sizing | ~$/mo |
| --- | --- | --- |
| ECS Fargate | the app container; 0.5 vCPU/1 GB per task | 18 (1 task) / 36 (2-task HA) |
| ALB | HTTPS entry, health checks, later WAF attach | 18–21 |
| RDS PostgreSQL 16, db.t4g.micro single-AZ + 20 GB gp3 | ALL data — and **pgvector**, see improvement #2 | 14 |
| EFS (only if Chroma stays) ~5 GB | shared persistent vector files for Fargate | 1.50 |
| ECR | image registry | 0.50 |
| Secrets Manager (3 secrets) | keys out of .env | 1.20 |
| CloudWatch Logs ~5 GB ingest | our structured logs + metric filters (login-fail alarms) | 2.50 |
| Route 53 + ACM | domain + free TLS cert | 0.50 |
| **NAT Gateway — AVOID in v1** | private-subnet egress to OpenAI | (32.90 + data) |
| Langfuse Cloud (Hobby tier) instead of self-host | tracing/evals/feedback | 0 |
| **Total** | single task, public-subnet egress, no NAT | **~$56** |
| **Total** | 2-task HA + NAT (the "proper" posture) | **~$105–115** |

The two swing decisions: **NAT** ($33+ for private subnets; public subnet +
tight security group is a legitimate dev-stage alternative) and **Langfuse**
(self-hosting its 6-container stack on Fargate+RDS ≈ +$60–90/mo; Langfuse
Cloud's free tier covers our volume — recommend Cloud until scale or data
residency says otherwise).

## State 2 — the register's M2 target (managed everything)

| Added service | Purpose | ~$/mo delta |
| --- | --- | --- |
| Cognito | auth swap (AuthProvider impl) | 0 at our MAU |
| DynamoDB on-demand | ConversationStore swap | 1–3 |
| ElastiCache Redis cache.t4g.micro | ShortTermMemory swap, API-key/session cache | 11.50 |
| WAF on ALB | edge protection | 8–12 |
| SQS + EventBridge | async/events (v2 actions, notifications) | ~0 at low volume |
| RDS → db.t4g.small (+pgvector absorbs Chroma) | headroom; EFS+Chroma retired | +9, −1.5 |
| Bedrock (if D1 flips) | LLM via AWS instead of OpenAI | token-based, ≈ same order |
| *(OpenSearch only if chosen over pgvector)* | managed vector search | (+26+; recommend pgvector) |
| **Total** | | **~$135–190** |

## State 3 — production hardening (register M3)

| Added | Purpose | ~$/mo delta |
| --- | --- | --- |
| RDS Multi-AZ | DB failover | +14 |
| Fargate autoscaling 2–4 tasks (avg 3) | load | +18 |
| CloudFront | static assets/edge | 1–5 |
| GuardDuty + Security Hub (light) | threat detection | 8–15 |
| AWS Backup, X-Ray/OTel | DR + cross-service traces | 5–8 |
| **Production total** | | **~$220–280** |
| Staging environment (scaled-down clone) | register M2-20/M3-13 | +80–120 |
| **All-in** | | **~$300–400** |

## LLM token costs (every state, usage-driven)

Per message turn today: ~2 supervisor calls (gpt-4o, ~1.1k in/70 out each) +
3–4 FAST calls (gpt-4o-mini) + the summarizer every 4 messages ⇒ **≈ $0.008–
0.015 per turn ⇒ ~$8–15 per 1,000 message turns.** Golden-set run ≈ $0.15–
0.30. Memory retrieval adds no LLM cost (embeddings are local). The dormant
complexity-routing flag is the future lever here; CloudWatch + Langfuse both
see per-call tokens via CallRecords, and AWS Budgets alerts (free) should be
day-one.

---

## Improvements BEFORE deploying (the honest gap list)

1. **A Dockerfile does not exist.** docker-compose.yml is Langfuse-only. Need:
   app image (python:3.11-slim, requirements, `app/ prompts/ scripts/`),
   `.dockerignore`, entrypoint that runs `scripts/db/migrate.py` before
   uvicorn, and the **MiniLM embedding model baked into the image** (else
   every cold start downloads ~80 MB and Chroma queries stall).
2. **Retire Chroma in AWS → pgvector on RDS 16.** Removes EFS, removes the
   embedded-DB-in-container awkwardness, one store instead of two. The
   `MemoryStore`/retriever interfaces make this a swap; the FAQ collection
   re-ingests. Biggest simplification available; do it as part of State 1 or
   immediately after.
3. **Secrets source swap:** `config.py` reads Secrets Manager/SSM when an env
   flag says so (one-file change by design). Never ship `.env`.
4. **Multi-worker/task honesty:** uvicorn is single-worker and the graph is
   synchronous — one long LLM call blocks the worker. Run `--workers 2` in the
   container and/or ≥2 tasks; the real fix is the streaming story (2.4).
5. **Seeding gate:** demo data must be an explicit one-off task (ECS RunTask),
   never part of app startup — seed_enterprise wipes tables.
6. **CI → CD:** the existing GitHub Actions workflow gains a deploy job (build
   → ECR push → ECS update) behind merge-to-main; OIDC role, no long-lived AWS
   keys in GitHub.
7. **ALB/WAF details:** health check `/health` exists ✓; set idle timeout ≥
   graph latency (~60 s default is fine today); HTTPS-only redirect.
8. **AWS Budgets alert on day one** — the register's own cost-guardrail task,
   and the cheapest insurance in this plan.
9. Small code debts that matter more in prod: tool-call timeouts (still
   unimplemented), JWT secret rotation story, rate limiting (WAF covers
   crudely in State 2).

## Suggested order

1. Improvements #1, #3, #5 (Dockerfile, secrets swap, seed gate) — deployable
   artifact exists.
2. State 1 without NAT, Langfuse Cloud, single task — first live URL,
   ~$56/mo + tokens.
3. Improvement #2 (pgvector) + CD job (#6).
4. HA + NAT when it stops being a demo; State 2 pieces as their features land
   (Cognito with auth hardening, Redis with the action loop, SQS with v2).
5. State 3 only alongside register M3's testing gates.
