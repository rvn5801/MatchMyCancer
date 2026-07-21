# Deploying MatchMyCancer.ai

Target stack: **Vercel** (frontend) · **Fly.io** (backend) · **Upstash** (Redis) · **Namecheap** (domain).

Prereqs: accounts on all four, the `flyctl` CLI (`curl -L https://fly.io/install.sh | sh`), and your repo pushed to GitHub.

Run every command in this doc yourself in your terminal (prefix with `!` in this session to run inline). Nothing here logs into your accounts for you.

---

## 1. Redis — Upstash (2 min)

1. https://console.upstash.com → **Create Database** → Redis → pick a region near your Fly region (`iad` = US East).
2. On the database page, copy the **`rediss://…` URL** (the TLS one, port `6379` or `6380`). You'll paste it as `REDIS_URL` below.

## 2. Backend — Fly.io

From the repo, `cd backend`, then:

```bash
fly launch --no-deploy          # detects fly.toml + Dockerfile.prod; pick a unique app name + iad region
fly volumes create chroma_data --region iad --size 1   # 1 GB persistent disk for the trial index

# Secrets (never commit these):
fly secrets set OPENAI_API_KEY="sk-...你的新key..."
fly secrets set REDIS_URL="rediss://default:...@...upstash.io:6379"

fly deploy
```

Verify: `curl https://<your-app>.fly.dev/health` → `{"status":"ok",...}`.
Note the backend URL — you need it for the frontend.

> Scale-to-zero (`min_machines_running = 0`) is on: the machine sleeps when idle and cold-starts on the next request (a few seconds). Set it to `1` in `fly.toml` if you want it always warm.

## 3. Frontend — Vercel

1. https://vercel.com → **Add New → Project** → import your GitHub repo.
2. **Root Directory:** `frontend`  (Framework auto-detects as Next.js).
3. **Environment Variable:** `NEXT_PUBLIC_API_URL = https://<your-app>.fly.dev`
   (build-time inlined — must be set *before* the build).
4. **Deploy.** You'll get `https://<project>.vercel.app`.

## 4. Wire CORS

The backend only accepts requests from `FRONTEND_ORIGIN`. Set it to your live frontend origin:

```bash
fly secrets set FRONTEND_ORIGIN="https://<project>.vercel.app"   # or your custom domain
```

(Do this again after you attach the custom domain in step 5.)

## 5. Custom domain (Namecheap)

**Frontend (apex + www) → Vercel:** in Vercel → Project → Settings → Domains, add your domain. Vercel shows the exact records. In Namecheap → Domain → Advanced DNS:
- Apex `@`: **A** record → `76.76.21.21` (Vercel shows the current value)
- `www`: **CNAME** → `cname.vercel-dns.com`

**(Optional) API subdomain → Fly:** if you want `api.your-domain.com` instead of the `.fly.dev` URL:
```bash
fly certs add api.your-domain.com
```
Then in Namecheap add a **CNAME** `api` → `<your-app>.fly.dev`, and update `NEXT_PUBLIC_API_URL` (Vercel) + redeploy, and `FRONTEND_ORIGIN` (Fly).

DNS can take minutes to a few hours. HTTPS is automatic on both Vercel and Fly.

---

## 6. Smoke test

```bash
curl https://<your-app>.fly.dev/health                 # backend up
curl https://<your-app>.fly.dev/api/v1/stats           # {"analyses_today":0,...} → Redis reachable
```
Then open your domain, accept the consent gate, paste a sample report, and confirm the live streaming analysis renders.

## Environment variable reference

| Where | Variable | Value |
|-------|----------|-------|
| Fly (secret) | `OPENAI_API_KEY` | your OpenAI key |
| Fly (secret) | `REDIS_URL` | Upstash `rediss://…` URL |
| Fly (secret/env) | `FRONTEND_ORIGIN` | your live frontend origin |
| Fly (env, optional) | `TRIAL_REFRESH_ENABLED` | `true` to run the daily CT.gov refresh |
| Vercel | `NEXT_PUBLIC_API_URL` | your backend URL |

## Notes / gotchas

- **ChromaDB** lives on the single Fly volume — this is a single-instance design. Don't scale the backend past 1 machine without moving to a served vector store.
- **Trial index**: the Chroma index starts empty. Trials are indexed on demand during analysis; the daily refresh job only re-verifies already-indexed trials.
- **Cost**: Fly and Upstash are cheap but not always free — check current pricing. Vercel Hobby is free for personal use.
- **Rotate the OpenAI key** that was previously committed to git history before going live (assume it's compromised).
