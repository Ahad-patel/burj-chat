# Deploying — Oracle Always Free + GitHub Pages

Total cost: **$0/month, permanently.** Oracle's Always Free ARM tier does not
expire, and GitHub Pages is free for public repositories.

| Piece | Where | Cost |
|---|---|---|
| API | Oracle Always Free ARM VM (4 cores, 24 GB) | $0 |
| TLS certificate | Let's Encrypt via Caddy, auto-renewed | $0 |
| Widget JS | GitHub Pages, built by Actions on every push | $0 |
| Hostname | `sslip.io` (or your own domain) | $0 |

Oracle asks for a card to verify identity. Always Free resources are not
billed; to be certain, leave the account on the **Always Free** upgrade setting
so nothing can silently start costing money.

---

## Part 1 — The VM

### 1.1 Create it

Oracle Cloud → **Compute → Instances → Create**.

| Setting | Value | Why |
|---|---|---|
| Image | Ubuntu 22.04 or 24.04 | Docker installs cleanly |
| Shape | **Ampere `VM.Standard.A1.Flex`** | The ARM shape is the free one |
| OCPUs / Memory | 2 OCPU / 12 GB | Half the free allowance; leaves room for a second VM |
| SSH key | Upload your public key | Password login is disabled |

> **"Out of capacity" is normal.** Free ARM capacity is genuinely scarce in
> popular regions. Retry, or pick a quieter home region — the account's home
> region cannot be changed later, so choose one that has stock.

Note the **public IP**.

### 1.2 Open the ports — *both* firewalls

This is where most Oracle deployments stall. There are **two** independent
firewalls and the VM answers on neither until both allow traffic.

**Firewall 1 — the OCI security list** (in the console):
Networking → VCN → Subnet → Security List → Add Ingress Rules

| Source | Protocol | Port |
|---|---|---|
| `0.0.0.0/0` | TCP | 80 |
| `0.0.0.0/0` | TCP | 443 |

**Firewall 2 — iptables on the VM itself.** Oracle's Ubuntu images ship a
restrictive `iptables` ruleset that silently drops everything but SSH. Opening
the security list alone leaves you with a VM that pings but never answers, and
the failure looks exactly like a DNS or Caddy problem.

```sh
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save     # survives reboot
```

### 1.3 Install Docker

```sh
sudo apt-get update && sudo apt-get install -y ca-certificates curl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker
```

---

## Part 2 — A hostname with real TLS

The widget is embedded on an **HTTPS** page. A browser blocks an HTTP API call
from an HTTPS page as mixed content, so the request never leaves — the widget
appears broken with nothing in the server log. TLS is not polish here; without
it nothing works.

Let's Encrypt will not issue a certificate for a bare IP address, so you need a
hostname. Either:

**A. A free one, no domain needed.** `sslip.io` resolves any embedded IP:

```
132-145-10-20.sslip.io  →  132.145.10.20
```

Nothing to register or configure. Good for a demo.

**B. Your own domain** — point an `A` record at the VM's IP:

```
api.burjconstructions.com.   A   132.145.10.20
```

Better for the client, and what you want before going live on their site.

---

## Part 3 — Deploy

```sh
git clone https://github.com/Ahad-patel/burj-chat.git
cd burj-chat
cp .env.example deploy/.env
nano deploy/.env
```

`deploy/.env` needs, at minimum:

```sh
DOMAIN=132-145-10-20.sslip.io          # or api.burjconstructions.com

LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-flash-latest

# Every origin the widget is embedded on. No wildcard, ever — a permissive API
# origin lets any site on the internet spend the LLM budget.
CORS_ALLOWED_ORIGINS=https://burjconstructions.com,https://www.burjconstructions.com
```

Then:

```sh
docker compose -f deploy/docker-compose.yml up -d --build
```

Caddy obtains a certificate on first request; give it 30 seconds.

```sh
curl https://$DOMAIN/health
# {"status":"ok"}
```

Production hides the detail — a bare `{"status":"ok"}` is correct, not a
truncated response.

### Verify the guardrails survived deployment

```sh
curl -s -X POST https://$DOMAIN/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"who is the prime minister of India"}'
# → is_fallback: true, and no model was ever called

curl -s -X POST https://$DOMAIN/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What amenities does Burj Chishti have?"}'
# → a real answer from the knowledge base
```

---

## Part 4 — The widget

GitHub Actions builds and publishes it. Pages must be enabled **once** — the
workflow token cannot do this itself, as creating a Pages site needs repo-admin
scope:

```sh
gh api --method POST repos/OWNER/REPO/pages -f build_type=workflow
```

or **Settings → Pages → Source: GitHub Actions**. Already done for this repo.

Push to `main` and the workflow typechecks, runs the 73 tests, enforces the
60 KB gzipped ceiling, and deploys. The file lands at:

```
https://ahad-patel.github.io/burj-chat/burj-chat.js
```

Embed it on the client's site, immediately before `</body>`:

```html
<script src="https://ahad-patel.github.io/burj-chat/burj-chat.js"
        data-api-url="https://api.burjconstructions.com"
        defer></script>
```

That is the entire integration. No build step on their side, no CSS to include,
no jQuery plugin to register.

---

## Operating it

```sh
docker compose -f deploy/docker-compose.yml logs -f burj-api   # structured JSON
docker compose -f deploy/docker-compose.yml restart burj-api
git pull && docker compose -f deploy/docker-compose.yml up -d --build   # update
```

**Restarting clears every in-progress conversation.** That is by design — there
is no database, and conversations exist only to resolve follow-ups within a
single visit. Deploy when the site is quiet.

### If something is wrong

| Symptom | Cause |
|---|---|
| Connection times out | iptables on the VM (§1.2, firewall 2) — the usual one |
| Caddy cannot get a certificate | DNS not pointing at the VM yet, or port 80 closed |
| Widget silently does nothing | API is HTTP, page is HTTPS — mixed content, blocked before the request is sent |
| Every visitor rate-limited as one | `TRUST_PROXY_HEADERS` not true, so every request looks like it came from Caddy |
| Browser console: CORS error | The site's origin is missing from `CORS_ALLOWED_ORIGINS` |
| Answers are always the fallback | Provider quota. The API now returns **503**, not the fallback, so check `docker logs` for `llm_call_failed` |

### Cost guardrails

Nothing here can bill you: the VM is Always Free, Pages is free, and Let's
Encrypt is free. The only spendable resource is **LLM tokens**, capped by the
per-IP and per-conversation rate limits in `deploy/.env`. Gemini's free tier
adds a second ceiling underneath those.
