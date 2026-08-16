# AI Vedic Astrology Report

A complete MVP web app that generates a personalized AI Vedic astrology
(Kundli) report from a user's **name, date of birth, and place of birth**
(no time of birth is collected). The user also uploads a face photo, which
is stored with their record in Supabase for reference — it is **not**
analyzed by the AI model.

The result page shows a free ~30% preview ("teaser") of the report, with
problem areas highlighted in red and solutions/remedies highlighted in
green. Unlocking the full report (and its downloadable PDF, with the same
red/green highlighting) costs **Rs 9**, paid through a Razorpay Payment
Page.

- **Frontend:** plain HTML5 / CSS3 / vanilla JavaScript (no frameworks),
  served directly by the backend as static files (same origin — one URL,
  one Render service). Date of birth uses a custom, simple calendar
  picker (month/year dropdowns + day grid) instead of the native browser
  date input.
- **Backend:** Python 3.12, FastAPI, Uvicorn
- **AI:** Gemini API (`gemini-3.5-flash-lite` by default), text-only —
  the model reasons over birth details alone; no images are ever sent to it
- **Database & storage:** Supabase (Postgres table + Storage bucket, for
  the face photo)
- **PDF:** ReportLab
- **Payments:** Razorpay Payment Page (hosted checkout, Rs 9 unlock)
- **Deploy target:** Render (single web service)

---

## 1. Project Structure

```
PalmAI/
│
├── backend/
│   ├── main.py              # FastAPI app: /health, /analyze, /report/*,
│   │                         # /payment/callback, + serves static/ (the
│   │                         # frontend) at "/"
│   ├── prompt.py             # Gemini prompt templates (name+dob+place only,
│   │                         # includes [[PROBLEM]]/[[SOLUTION]] marker rules)
│   ├── report_utils.py       # Parses the markdown: extracts Rashi, builds
│   │                         # the free ~30% teaser HTML with red/green marks
│   ├── pdf_generator.py      # ReportLab PDF generation (Rashi highlighted
│   │                         # red, PROBLEM/SOLUTION coloured red/green)
│   ├── store.py              # Tiny JSON-file store: report_id -> paid status
│   ├── payments.py           # Razorpay Payment Link signature verification
│   ├── requirements.txt
│   ├── .env.example          # sample environment file
│   ├── Procfile               # Render/Heroku-style start command
│   ├── static/                # the frontend — served by this same FastAPI app
│   │   ├── index.html
│   │   ├── style.css
│   │   └── script.js
│   ├── uploads/               # temp storage for the uploaded face photo (auto-cleaned)
│   └── reports/               # generated PDFs + store.json (paid status) live here
│
├── supabase_setup.sql         # run once in Supabase SQL editor
├── render.yaml                 # Render Blueprint (one-click deploy)
└── README.md
```

Frontend and backend are deployed together as **one Render web service**:
FastAPI serves the API routes and, for every other path, serves
`backend/static/index.html` and its assets. Since frontend and API share an
origin in production, `script.js` calls the API with relative URLs (e.g.
`fetch("/analyze")`) — no backend URL to configure.

---

## 2. How the paywall flow works

1. **`POST /analyze`** — user submits name, DOB, place, and a face photo.
   The backend calls Gemini (birth details only), which returns markdown
   with `[[PROBLEM]]...[[/PROBLEM]]` / `[[SOLUTION]]...[[/SOLUTION]]`
   markers around key sentences, plus a parseable Rashi line. The backend:
   - extracts the **Rashi** (Moon sign),
   - builds a list of **issue chips** ("Career Challenges Detected", etc.)
     from which sections actually contain a problem,
   - builds a **free teaser**: the Executive Summary + Basic Astrological
     Details in full, then further sections up to ~30% of the remaining
     report's length, cut only at paragraph/section boundaries so a
     sentence is never shown half-cut. Everything past that point is
     simply **not sent to the browser** — it can't be revealed by
     inspecting the page source,
   - generates the **full PDF** (with the same red/green colouring, Rashi
     highlighted instead of exact birth time) and stores it server-side,
   - creates a `report_id` and a Razorpay payment URL
     (`RAZORPAY_PAYMENT_LINK?reference_id=<report_id>`),
   - saves the user's details + face photo URL + full report to Supabase
     (best-effort; a Supabase outage never blocks the user's report).
   - Returns the teaser + Rashi + issue chips + `payment_url` — never the
     full markdown or a PDF path.

2. User clicks **"Unlock Full Report — Rs 9"**, which opens the Razorpay
   Payment Page in a new tab and starts polling
   `GET /report/{id}/status` every few seconds.

3. After paying, Razorpay redirects the browser to whatever **Redirect
   URL** is configured for that Payment Page in the Razorpay Dashboard.
   Point that at `https://<your-domain>/payment/callback` — Razorpay
   appends `razorpay_payment_id`, `razorpay_payment_link_id`,
   `razorpay_payment_link_reference_id` (this is your `report_id`),
   `razorpay_payment_link_status`, and `razorpay_signature` as query
   params. `/payment/callback`:
   - verifies the signature with `RAZORPAY_KEY_SECRET` (HMAC-SHA256 over
     `payment_link_id|reference_id|status|payment_id`, Razorpay's
     documented algorithm),
   - marks that `report_id` as paid in `store.py`,
   - redirects the browser back to `FRONTEND_URL?report_id=<id>&paid=1`.

4. The frontend (via the polling loop, or by reading `?report_id=...` on
   page load) sees `paid: true` and reveals **"Download Full PDF"**, which
   hits the gated `GET /report/{id}/download` route. PDFs are **never**
   reachable by a guessed/static filename — only through this route, which
   returns `402 Payment Required` until `paid` is true.

**Important — one manual setup step:** Razorpay's redirect-back behaviour
must be configured **in the Razorpay Dashboard**, not in this code:
Payment Pages → your Rs 9 page → **Settings → Redirect URL** → set to
`https://<your-deployed-domain>/payment/callback`. Until you set this, the
"I've completed the payment" button and the automatic status polling still
work as a fallback (the user can manually confirm), but the automatic
redirect-back won't fire.

If `RAZORPAY_KEY_SECRET` is left unset, the callback still works but
trusts the `status=paid` query param instead of cryptographically
verifying it — fine for testing, but set the real key secret (Dashboard →
Settings → API Keys) before taking real payments.

---

## 3. Prerequisites

- Python 3.12+
- A Gemini API key ([aistudio.google.com/apikey](https://aistudio.google.com/apikey))
- A Supabase project ([supabase.com](https://supabase.com)) — free tier is fine
- A Razorpay account with the Rs 9 Payment Page already created
  (`https://pages.razorpay.com/pl_TMx7x1Tdoh4cDh/view` is the default
  baked into `main.py` — override with `RAZORPAY_PAYMENT_LINK` if you
  create a new one)
- A modern web browser

---

## 4. One-time Supabase setup

1. Open your Supabase project → **SQL Editor** → paste in the contents of
   `supabase_setup.sql` → run it. This creates:
   - a `palm_reports` table (report_id, name, email, dob, place, face
     image URL, report text, paid flag)
   - a public `palm-images` storage bucket
   - RLS policies allowing the publishable key to insert/read rows in
     `palm_reports` and upload/read files in `palm-images` (nothing else).

2. Get your key from **Project Settings → API Keys**:
   - **Publishable key** (`sb_publishable_...`) → `SUPABASE_KEY` — low
     privilege, safe to embed. `backend/main.py` already has a working
     default baked in, so you don't strictly need to set this as a Render
     env var — it'll work out of the box. Only set `SUPABASE_URL` /
     `SUPABASE_KEY` if you want to override the default (e.g. after
     rotating the key).
   - If you'd rather lock things down further, use the **secret key**
     (`sb_secret_...`) instead — it bypasses RLS entirely, so you can drop
     the `anon` policies in `supabase_setup.sql`. Never hardcode a secret
     key in source — only ever set it as a Render environment variable.

> **Security note:** a *publishable* key is designed to be public/embedded —
> that's fine. A *secret*/`service_role` key is not — if one was ever
> pasted into a chat, doc, or public repo, rotate it immediately from the
> Supabase dashboard.

---

## 5. Razorpay setup

1. In the Razorpay Dashboard, confirm the Rs 9 Payment Page exists (or
   create a new one) and note its URL.
2. **Payment Pages → your page → Settings → Redirect URL** → set to
   `https://<your-deployed-domain>/payment/callback`.
3. **Settings → API Keys** → copy the **Key Secret** → set it as
   `RAZORPAY_KEY_SECRET` in your Render environment variables (never in
   source control).
4. If you created a new Payment Page (different URL from the default),
   set `RAZORPAY_PAYMENT_LINK` to its URL as well.

---

## 6. Backend Setup (local)

```bash
cd backend

# Create and activate a virtual environment
python3.12 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# then edit .env: fill in GEMINI_API_KEY, and RAZORPAY_KEY_SECRET if you
# want to test real payment verification locally (ngrok or similar is
# needed for Razorpay to reach a local /payment/callback)
```

Run it locally (this serves both the API and the frontend):

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- Visit `http://localhost:8000/` — the app itself.
- Visit `http://localhost:8000/health` — you should see `{"status": "healthy", ...}`.

There's no separate frontend server to run; `backend/static/` is served
directly by this same FastAPI app.

---

## 7. Deploying to Render (one service, frontend + backend + Gemini)

**Option A — Blueprint (render.yaml), recommended:**
1. Push this repo to GitHub.
2. In Render: **New → Blueprint** → select the repo. Render reads
   `render.yaml` and creates a single web service (`palmai`) automatically.
3. When prompted, fill in `GEMINI_API_KEY` and `RAZORPAY_KEY_SECRET`.
   `SUPABASE_URL` / `SUPABASE_KEY` can be left blank (working defaults are
   baked in). Once you know your Render URL, update `FRONTEND_URL` to it
   and set the same URL + `/payment/callback` as the Razorpay Payment
   Page's Redirect URL (see section 5).

**Option B — Manual web service:**
1. **New → Web Service** → connect the repo.
2. **Root Directory:** `backend`
3. **Build Command:** `pip install -r requirements.txt`
4. **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Under **Environment**, add at minimum `GEMINI_API_KEY` and
   `RAZORPAY_KEY_SECRET`. Optionally add `GEMINI_MODEL`, `SUPABASE_URL` /
   `SUPABASE_KEY` (only if overriding built-in defaults), `SUPABASE_TABLE`,
   `SUPABASE_BUCKET`, `ALLOWED_ORIGINS`, `RAZORPAY_PAYMENT_LINK`,
   `REPORT_PRICE_INR`, and `FRONTEND_URL` (your deployed URL).

Either way, you get **one Render URL** that serves the whole app.

Render's free tier disks are ephemeral — `uploads/`, `reports/`, and
`reports/store.json` (which tracks paid status) are cleared on every
deploy/restart. That's fine for `uploads/` (temp-only, already deleted per
request). For `reports/` and the paid-status store, that means an **unpaid
report_id created right before a redeploy will be lost** — acceptable for
an MVP, but if you need durability across deploys, either add a Render
persistent Disk mounted at `backend/reports/`, or move `store.py`'s
persistence into the `palm_reports` Supabase table (it already has a
`paid` column ready for this) and update `/payment/callback` to also
`UPDATE palm_reports SET paid = true WHERE report_id = ...`.

**If you do override `SUPABASE_URL` / `SUPABASE_KEY`:** copy them fresh
from Supabase → **Project Settings → API Keys** straight into Render's env
var fields — a stray quote, extra space, or trailing newline pasted into
the value is the most common cause of `SupabaseException: Invalid API key`
at startup.

---

## 8. API reference

| Route | Method | Purpose |
|---|---|---|
| `/health` | GET | Health check |
| `/analyze` | POST | Submit birth details + face photo → generates report, returns teaser + payment_url |
| `/report/{id}` | GET | Public view of a report (teaser, Rashi, issues, paid flag, payment_url) — used to restore state after the Razorpay redirect |
| `/report/{id}/status` | GET | `{ "paid": true/false }` — used for polling |
| `/report/{id}/download` | GET | Full PDF download — `402` until paid |
| `/payment/callback` | GET | Razorpay's redirect target after a payment attempt; verifies signature, marks paid, redirects back to the site |

---

## 9. How the report + teaser + PDF pipeline works

- `/analyze` receives the form (name, dob, place) + the face photo.
- Only the birth details (no images) are sent to Gemini, which returns
  markdown containing `[[PROBLEM]]`/`[[SOLUTION]]` markers and a Rashi
  line.
- `report_utils.py` extracts the Rashi, detects which sections raised a
  problem (for the "X Challenges Detected" chips), and builds the ~30%
  teaser HTML (red/green highlighted).
- `pdf_generator.py` renders the full report to PDF with the same
  red/green colouring and the Rashi highlighted in place of exact
  birth-time details (no time of birth is collected at all any more).
- The face photo is uploaded to the `palm-images` Supabase Storage bucket,
  and a row (report_id, name, email, dob, place, face image URL, report
  text, paid flag) is inserted into the `palm_reports` table — best
  effort; if Supabase is unreachable, the user still gets their report,
  and the failure is logged.
- The local temp copy of the face photo is deleted after each request
  either way.
- The generated PDF is kept **only** on the server and served exclusively
  through the paid-gated `/report/{id}/download` route.
