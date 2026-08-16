"""
main.py

FastAPI backend for the AI Vedic Astrology Report generator.

Responsibilities:
- Accept multipart/form-data submissions (user details + one face photo).
- Call Gemini (via generate_astrology_report) using ONLY the birth details
  (name, date of birth, place) -- no time of birth is collected, and no
  images are ever sent to Gemini.
- Build a free ~30% "teaser" preview (problems highlighted red, solutions
  highlighted green) and a full paid PDF (same colouring) from the result.
- Gate the full PDF behind a Rs 9 Razorpay Payment Page; verify the
  payment callback and unlock the download once payment is confirmed.
- Save the face photo to Supabase Storage and insert a row (user details +
  face image URL + report text) into a Supabase table.
"""

import os
import uuid
import logging
from datetime import datetime

import aiofiles
from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from google import genai
from google.genai import types as genai_types
from supabase import create_client, Client

try:
    # Works when the app is run from inside backend/ (uvicorn main:app),
    # i.e. when Render's Root Directory is set to "backend".
    from prompt import SYSTEM_PROMPT, build_user_prompt
    from pdf_generator import generate_pdf
    import report_utils
    import store
    import payments
except ImportError:
    # Works when the app is run from the repo root (uvicorn backend.main:app),
    # i.e. when Root Directory is unset/empty.
    from backend.prompt import SYSTEM_PROMPT, build_user_prompt
    from backend.pdf_generator import generate_pdf
    from backend import report_utils
    from backend import store
    from backend import payments

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("palmai")

BASE_DIR = os.path.dirname(__file__)
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# --- Gemini config ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

# --- Supabase config ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://xebgzpltairmyvegmdlh.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_waCxQWQp8hZW9VJtk82MRg_9BuSDBWN")
SUPABASE_TABLE = os.environ.get("SUPABASE_TABLE", "palm_reports")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "palm-images")

# --- Razorpay config ---
# Default is the Payment Page link supplied for this project. Override via
# env var if you create a new one. RAZORPAY_KEY_SECRET (Dashboard > Settings
# > API Keys) is required to cryptographically verify the payment callback;
# without it the callback falls back to trusting the "status=paid" query
# param, which is fine for testing but should be set for production.
RAZORPAY_PAYMENT_LINK = os.environ.get(
    "RAZORPAY_PAYMENT_LINK", "https://pages.razorpay.com/pl_TMx7x1Tdoh4cDh/view"
)
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
REPORT_PRICE_INR = int(os.environ.get("REPORT_PRICE_INR", "9"))
# Where to send the browser after /payment/callback finishes. Leave unset to
# just redirect back to "/" on this same service.
FRONTEND_URL = os.environ.get("FRONTEND_URL", "/")

# Allow the frontend origin(s) to be configured via env var (comma separated).
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*")
origins = (
    ["*"] if ALLOWED_ORIGINS.strip() == "*" else [o.strip() for o in ALLOWED_ORIGINS.split(",")]
)

MAX_IMAGE_SIZE_BYTES = 8 * 1024 * 1024  # 8 MB
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}

app = FastAPI(title="AI Vedic Astrology Report API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(BASE_DIR, "static")


class NoCacheStaticFiles(StaticFiles):
    """
    Same as StaticFiles, but adds Cache-Control: no-cache so browsers always
    revalidate with the server (a fast conditional request) instead of
    silently reusing a stale cached copy of index.html/script.js/style.css
    after a deploy.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


# NOTE: generated PDFs are intentionally NOT mounted as static files. They
# are only ever served through the paid-gated /report/{id}/download route
# below, so a guessed/leaked filename can't bypass the Rs 9 unlock.

gemini_client = None
if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception:
        logger.exception("Failed to initialize Gemini client — check GEMINI_API_KEY.")
else:
    logger.warning("GEMINI_API_KEY not set — report generation will fail until it's configured.")

supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        logger.exception(
            "Failed to initialize Supabase client — check SUPABASE_URL and SUPABASE_KEY "
            "for typos, stray quotes, or trailing spaces."
        )
else:
    logger.warning(
        "SUPABASE_URL / SUPABASE_KEY not set — user details and the face photo will NOT be saved."
    )

if not RAZORPAY_KEY_SECRET:
    logger.warning(
        "RAZORPAY_KEY_SECRET not set — the payment callback will trust the "
        "status query param instead of verifying Razorpay's signature. Set "
        "this before going live."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _save_upload(file: UploadFile, prefix: str) -> str:
    """
    Validate and save an uploaded image to disk. Returns the saved filepath.
    Raises HTTPException on validation failure.
    """
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"{prefix} image must be a JPEG, PNG, or WEBP file.",
        )

    contents = await file.read()

    if len(contents) == 0:
        raise HTTPException(status_code=400, detail=f"{prefix} image is empty.")

    if len(contents) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"{prefix} image exceeds the 8MB size limit.",
        )

    ext = os.path.splitext(file.filename or "")[1] or ".jpg"
    unique_name = f"{prefix}_{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOADS_DIR, unique_name)

    async with aiofiles.open(filepath, "wb") as out_file:
        await out_file.write(contents)

    return filepath


async def generate_astrology_report(name: str, dob: str, place: str) -> str:
    """
    Calls the Gemini API using ONLY the person's name, date of birth, and
    place of birth (no time of birth, no images) and returns a
    markdown-formatted Vedic astrology report containing [[PROBLEM]]/
    [[SOLUTION]] markers.
    """
    if gemini_client is None:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured on the server. "
            "Set it in your .env file (or Render environment variables) before starting the backend."
        )

    user_prompt = build_user_prompt(name=name, dob=dob, place=place)

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[user_prompt],
        config=genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.9,
            max_output_tokens=2600,
        ),
    )

    report_text = (response.text or "").strip()
    if not report_text:
        raise RuntimeError("Gemini returned an empty report.")

    return report_text


def save_to_supabase(
    name: str,
    email: str,
    dob: str,
    place: str,
    face_photo_path: str,
    report_markdown: str,
    report_id: str,
) -> None:
    """
    Uploads the face photo to Supabase Storage and inserts a row into the
    Supabase table with the user's details, the public face image URL, and
    the generated report. Failures here are logged but never block the
    response to the user — the report was already generated successfully.
    """
    if supabase is None:
        logger.warning("Supabase not configured; skipping save.")
        return

    try:
        ext = os.path.splitext(face_photo_path)[1] or ".jpg"
        storage_path = f"{uuid.uuid4().hex}_face{ext}"
        with open(face_photo_path, "rb") as f:
            supabase.storage.from_(SUPABASE_BUCKET).upload(
                storage_path,
                f.read(),
                {"content-type": _mime_type_from_ext(ext)},
            )
        face_image_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(storage_path)

        supabase.table(SUPABASE_TABLE).insert(
            {
                "report_id": report_id,
                "name": name,
                "email": email,
                "dob": dob,
                "place": place,
                "face_image_url": face_image_url,
                "report": report_markdown,
                "paid": False,
            }
        ).execute()
    except Exception:
        logger.exception("Failed to save report to Supabase")


def _mime_type_from_ext(ext: str) -> str:
    return {".png": "image/png", ".webp": "image/webp"}.get(ext.lower(), "image/jpeg")


def _public_report_view(record: dict) -> dict:
    """Only the fields safe to send to the browser (never the raw markdown
    or the on-disk PDF path)."""
    return {
        "report_id": record["report_id"],
        "name": record.get("name"),
        "rashi": record.get("rashi"),
        "teaser_html": record.get("teaser_html"),
        "issues": record.get("issues", []),
        "truncated": record.get("truncated", True),
        "paid": bool(record.get("paid")),
        "amount": REPORT_PRICE_INR,
        "payment_url": record.get("payment_url"),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.post("/analyze")
async def analyze(
    name: str = Form(...),
    email: str = Form(...),
    dob: str = Form(...),
    place: str = Form(...),
    facePhoto: UploadFile = File(...),
):
    """
    Main endpoint: accepts user details + a face photo, generates the AI
    Vedic astrology report from name + date of birth + place (no time of
    birth, no image analysis), builds the free teaser + the full paid PDF,
    and returns the teaser plus a Razorpay unlock link. The face photo is
    saved to Supabase for the user's record only.
    """
    # --- Server-side validation (mirrors frontend validation) ---
    errors = []
    if not name or not name.strip():
        errors.append("Full name is required.")
    if not email or not email.strip():
        errors.append("Email address is required.")
    if not dob or not dob.strip():
        errors.append("Date of birth is required.")
    if not place or not place.strip():
        errors.append("Place of birth is required.")
    if facePhoto is None:
        errors.append("Face photo is required.")

    if errors:
        raise HTTPException(status_code=422, detail=" ".join(errors))

    face_path = None

    try:
        # --- Save the face photo (stored only, never analyzed) ---
        try:
            face_path = await _save_upload(facePhoto, "face")
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Upload failed")
            raise HTTPException(status_code=400, detail="Image upload failed. Please try again.") from exc

        # --- Generate report via Gemini (name + dob + place only) ---
        try:
            report_markdown = await generate_astrology_report(
                name=name.strip(),
                dob=dob.strip(),
                place=place.strip(),
            )
        except Exception as exc:
            logger.exception("Gemini generation failed")
            raise HTTPException(
                status_code=502,
                detail="Something went wrong while generating your report. Please try again.",
            ) from exc

        # --- Parse the report: Rashi, issue chips, free teaser ---
        rashi = report_utils.extract_rashi(report_markdown)
        issues = report_utils.detect_issue_chips(report_markdown)
        teaser_html, truncated = report_utils.build_teaser_html(report_markdown)

        # --- Generate the full PDF (kept server-side until payment) ---
        try:
            pdf_filename = generate_pdf(
                name=name.strip(),
                email=email.strip(),
                dob=dob.strip(),
                place=place.strip(),
                rashi=rashi,
                report_markdown=report_markdown,
            )
        except Exception as exc:
            logger.exception("PDF generation failed")
            raise HTTPException(
                status_code=500,
                detail="Something went wrong. Please try again.",
            ) from exc

        # --- Create the report record + Razorpay unlock link ---
        report_id = uuid.uuid4().hex
        payment_url = payments.build_payment_url(RAZORPAY_PAYMENT_LINK, report_id)

        store.create_report(
            report_id,
            {
                "name": name.strip(),
                "email": email.strip(),
                "rashi": rashi,
                "issues": issues,
                "teaser_html": teaser_html,
                "truncated": truncated,
                "pdf_filename": pdf_filename,
                "payment_url": payment_url,
                "paid": False,
            },
        )

        # --- Save user details + face photo + report to Supabase (best-effort) ---
        save_to_supabase(
            name=name.strip(),
            email=email.strip(),
            dob=dob.strip(),
            place=place.strip(),
            face_photo_path=face_path,
            report_markdown=report_markdown,
            report_id=report_id,
        )

        record = store.get_report(report_id)
        return JSONResponse({"success": True, **_public_report_view(record)})

    finally:
        # Clean up the temporary uploaded photo regardless of outcome.
        if face_path and os.path.exists(face_path):
            try:
                os.remove(face_path)
            except OSError:
                logger.warning("Could not remove temp file: %s", face_path)


@app.get("/report/{report_id}")
async def get_report(report_id: str):
    """Fetch the public view of a report (used to restore the result card
    after the browser is redirected back from the Razorpay payment page)."""
    record = store.get_report(report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return JSONResponse({"success": True, **_public_report_view(record)})


@app.get("/report/{report_id}/status")
async def report_status(report_id: str):
    """Lightweight polling endpoint the frontend calls while waiting for
    payment confirmation."""
    record = store.get_report(report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return JSONResponse({"paid": bool(record.get("paid"))})


@app.get("/report/{report_id}/download")
async def download_report(report_id: str):
    """Serves the full PDF only once payment has been confirmed for this
    report_id. PDFs are never reachable by filename directly."""
    record = store.get_report(report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    if not record.get("paid"):
        raise HTTPException(
            status_code=402,
            detail="Payment required. Please complete the Rs 9 payment to download your full report.",
        )

    filepath = os.path.join(REPORTS_DIR, record["pdf_filename"])
    if not os.path.exists(filepath):
        raise HTTPException(status_code=410, detail="This report's PDF is no longer available.")

    download_name = f"{report_utils.strip_markers(record.get('name') or 'astrology')}_report.pdf".replace(" ", "_")
    return FileResponse(filepath, media_type="application/pdf", filename=download_name)


@app.get("/payment/callback")
async def payment_callback(request: Request):
    """
    Razorpay redirects the browser here after a payment attempt on the
    Rs 9 unlock Payment Page (configure this URL as the page's "Redirect
    URL" in the Razorpay Dashboard). Verifies the signature (when
    RAZORPAY_KEY_SECRET is set), marks the matching report as paid, then
    sends the browser back to the site so the frontend can offer the
    download.
    """
    params = request.query_params
    payment_id = params.get("razorpay_payment_id", "")
    payment_link_id = params.get("razorpay_payment_link_id", "")
    reference_id = params.get("razorpay_payment_link_reference_id", "")
    status_param = params.get("razorpay_payment_link_status", "")
    signature = params.get("razorpay_signature", "")

    if not reference_id:
        logger.warning("Payment callback missing reference_id; cannot match a report.")
        return RedirectResponse(url=f"{FRONTEND_URL}?payment_error=missing_reference")

    verified = False
    if RAZORPAY_KEY_SECRET:
        verified = payments.verify_payment_link_signature(
            payment_link_id=payment_link_id,
            payment_link_reference_id=reference_id,
            payment_link_status=status_param,
            payment_id=payment_id,
            signature=signature,
            key_secret=RAZORPAY_KEY_SECRET,
        )
        if not verified:
            logger.warning("Razorpay signature verification failed for report_id=%s", reference_id)
    else:
        # No key secret configured -- fall back to trusting the status flag.
        verified = status_param == "paid"

    if verified and status_param == "paid":
        record = store.mark_paid(reference_id, payment_id=payment_id)
        if record is None:
            logger.warning("Paid callback for unknown report_id=%s", reference_id)
            return RedirectResponse(url=f"{FRONTEND_URL}?payment_error=unknown_report")
        return RedirectResponse(url=f"{FRONTEND_URL}?report_id={reference_id}&paid=1")

    return RedirectResponse(url=f"{FRONTEND_URL}?report_id={reference_id}&payment_error=1")


# ---------------------------------------------------------------------------
# Frontend (static site)
# ---------------------------------------------------------------------------
# Serves backend/static/index.html at "/" and its assets (script.js,
# style.css) alongside it, so frontend + backend + Gemini all run from this
# single FastAPI app/Render service. Mounted LAST so it never shadows the
# /health, /analyze, /report, or /payment routes defined above it.
app.mount("/", NoCacheStaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
