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

## 2. How the paywall + download flow works

1. **`POST /analyze`** — user submits name, email, **phone**, DOB, place,
   and a face photo. The backend calls Gemini (birth details only), which
   returns markdown with `[[PROBLEM]]...[[/PROBLEM]]` /
   `[[SOLUTION]]...[[/SOLUTION]]` markers around key sentences, plus a
   parseable Rashi line. The backend:
   - extracts the **Rashi** (Moon sign),
   - builds a list of **issue chips** ("Career Challenges Detected", etc.),
   - builds a **free teaser**: Executive Summary + Basic Astrological
     Details in full, then further sections up to ~30% of the remaining
     report's length, cut only at paragraph/section boundaries. Everything
     past that point is simply **not sent to the browser**,
   - generates the **full PDF** and stores it server-side,
   - creates a `report_id` and a Razorpay payment URL
     (`RAZORPAY_PAYMENT_LINK?reference_id=<report_id>`),
   - saves the user's details (name, normalized email, normalized phone,
     dob, place), face photo URL, Rashi, and the full report text to
     **Supabase** — this is the durable source of truth used later by the
     recovery download page, since Render's local disk is ephemeral.

2. User clicks **"Unlock Full Report — Rs 9"**, which opens the Razorpay
   Payment Page in a new tab, and a **"I've completed the payment"** link
   appears pointing to `download.html` (pre-filled with the email/phone
   they just submitted).

3. After paying, Razorpay redirects the browser to whatever **Redirect
   URL** is configured for that Payment Page — set this to
   `https://<your-domain>/payment/callback`. That route:
   - verifies the signature with `RAZORPAY_KEY_SECRET`,
   - flips `paid` to `true` for that `report_id` in **both** the local
     store and the matching Supabase row,
   - redirects the browser to `download.html?paid=1`.

4. **`download.html`** (a standalone page, linked from the result card and
   also the Razorpay redirect target) asks for **email + phone number**.
   `POST /download/lookup`:
   - normalizes both (lowercase/trimmed email; last-10-digits phone, so
     `+91 98765 43210` and `9876543210` match),
   - queries Supabase for the **most recent** row matching that email +
     phone where `paid = true`,
   - streams the PDF back. If the on-disk PDF from the original request
     is gone (e.g. a Render redeploy wiped the ephemeral disk), it's
     **regenerated on the fly** from the report text stored in Supabase —
     so downloads keep working even across redeploys.
   - If no paid row matches, returns a 404 with a clear "we couldn't find
     a completed payment for these details" message.

This means the *download* step is deliberately decoupled from any
particular browser/device/session — someone can pay on their phone and
retrieve the PDF later from a laptop, as long as they enter the same
email + phone they submitted originally.

**Important — one manual setup step:** Razorpay's redirect-back behaviour
must be configured **in the Razorpay Dashboard**: Payment Pages → your Rs
9 page → **Settings → Redirect URL** → set to
`https://<your-deployed-domain>/payment/callback`. Until you set this,
paying still works — the person just needs to manually click "I've
completed the payment" on the result page (or visit `download.html`
directly) instead of being auto-redirected.

If `RAZORPAY_KEY_SECRET` is left unset, the callback still works but
trusts the `status=paid` query param instead of cryptographically
verifying it — fine for testing, but set the real key secret before
taking real payments.

**Security note on the Supabase `paid` column:** the backend needs to be
able to flip `paid` to `true` after verifying a payment, which requires
an `UPDATE` policy in `supabase_setup.sql`. That policy is scoped to only
the `paid` / `pdf_filename` / `razorpay_payment_id` columns via a Postgres
column-level `GRANT`, so the publishable key can't rewrite anyone's name,
email, or report text — but because that key is designed to be
embeddable/public, someone holding it could in principle call Supabase's
REST API directly and flip their **own** row's `paid` to `true` without
actually paying (RLS can't verify a Razorpay signature). This is an
acceptable trade-off while testing; `supabase_setup.sql` includes the
exact steps to harden this (switch to a secret key + drop the anon update
policy) before relying on this for real revenue.

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
   `REPORT_PRICE_INR`, `FRONTEND_URL` (your deployed URL), and
   `SKIP_PAYMENT_CHECK` (see below — testing only).

**Testing the paywall + download flow without paying (`SKIP_PAYMENT_CHECK`):**
Normally `/download.html` only returns a PDF for a report whose `paid`
flag is `true` in Supabase — which only happens after a real (or
signature-verified) Razorpay payment. To test the "submit details ->
retrieve report" flow end-to-end without paying each time, set
`SKIP_PAYMENT_CHECK=true` as a Render env var (or in your local `.env`).
While it's on, both `/download/lookup` and `/report/{id}/download` will
serve the PDF for a matching email + phone regardless of payment status
— **anyone who knows/guesses an email + phone used on the app can then
download that report for free**, so remove this env var (or set it to
`false`) before accepting real payments. It defaults to `false`, so
production is unaffected unless you explicitly opt in.

Either way, you get **one Render URL** that serves the whole app.

Render's free tier disks are ephemeral — `uploads/` and `reports/*.pdf`
are cleared on every deploy/restart. That's fine for `uploads/` (temp-only,
already deleted per request). For `reports/`, it's also fine: **Supabase is
the durable source of truth**, and `/download/lookup` automatically
regenerates a missing PDF on the fly from the report text stored there. If
Supabase isn't configured at all, `/download/lookup` won't work (it needs
Supabase to look records up by email/phone) — the in-session `/report/{id}`
flow still works as a fallback for as long as the local disk survives.

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
| `/analyze` | POST | Submit birth details (incl. phone) + face photo → generates report, returns teaser + payment_url |
| `/report/{id}` | GET | Public view of a report (teaser, Rashi, issues, paid flag, payment_url) — used to restore state after the Razorpay redirect |
| `/report/{id}/status` | GET | `{ "paid": true/false }` — same-session convenience check |
| `/report/{id}/download` | GET | Full PDF download for that exact report_id — `402` until paid |
| `/payment/callback` | GET | Razorpay's redirect target after a payment attempt; verifies signature, marks paid in Supabase + local store, redirects to `download.html` |
| `/download/lookup` | POST | `{ email, phone }` → finds the latest **paid** row in Supabase matching both, streams the PDF back (regenerating it if the on-disk copy is gone) |

---

## 9. How the report + teaser + PDF pipeline works

- `/analyze` receives the form (name, email, phone, dob, place) + the face
  photo.
- `astro_calc.py` computes the **actual** Moon sign (Rashi), Nakshatra,
  Nakshatra Pada/Lord, and Sun sign for the date of birth using the
  Swiss Ephemeris library (sidereal, Lahiri ayanamsa) — these are real
  ephemeris positions, not something the AI model guesses. Since only a
  date (no time of birth, no geocoded place) is collected, this is
  evaluated at local noon UTC on that date; on the handful of dates a
  year where the Moon crosses a sign/nakshatra boundary, the facts are
  flagged as `*_uncertain` and the prompt notes that the reading applies
  to most of the day.
- These computed facts are sent to Gemini as ground truth the model must
  build its narrative around (not recalculate). The birth details (no
  images) plus these facts go to Gemini, which returns markdown
  containing `[[PROBLEM]]`/`[[SOLUTION]]` markers and a Rashi/Nakshatra
  line that should echo the computed facts.
- As a safety net, `report_utils.force_rashi()` overwrites the Rashi
  bullet in the model's markdown with the computed value regardless of
  what the model wrote, and the `rashi` stored/shown everywhere (teaser,
  PDF, Supabase row) is the computed value directly — never something
  parsed out of the AI's text. This guarantees the Rashi shown to the
  user is always astronomically correct.
- `report_utils.py` detects which sections raised a problem (for the "X
  Challenges Detected" chips), and builds the ~30% teaser HTML (red/green
  highlighted).
- `pdf_generator.py` renders the full report to PDF with the same
  red/green colouring and the Rashi highlighted in place of exact
  birth-time details (no time of birth is collected at all any more).
- The face photo is uploaded to the `palm-images` Supabase Storage bucket,
  and a row (report_id, name, normalized email, normalized phone, dob,
  place, face image URL, Rashi, report text, pdf_filename, paid flag) is
  inserted into the `palm_reports` table — best effort; if Supabase is
  unreachable, the user still gets their report, and the failure is
  logged.
- The local temp copy of the face photo is deleted after each request
  either way.
- The generated PDF is kept on the server and served either through the
  same-session `/report/{id}/download` route, or — the more robust path —
  through `/download.html` → `/download/lookup`, which finds the report by
  email + phone in Supabase and regenerates the PDF from the stored report
  text if the original file is gone.
