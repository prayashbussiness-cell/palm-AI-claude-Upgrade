"""
payments.py

Small helpers for the Razorpay Payment Page / Payment Link "unlock full
report for Rs 9" flow. Deliberately dependency-free (uses only hmac /
hashlib from the standard library) so no new pip packages are required.

How the flow works end-to-end:
1. After /analyze, the backend returns a `payment_url` built from
   RAZORPAY_PAYMENT_LINK with `?reference_id=<report_id>` appended.
2. The user pays on Razorpay's hosted page.
3. Razorpay redirects the browser to the "Redirect URL" configured on
   that Payment Page in the Razorpay Dashboard (Payment Pages -> this
   page -> Settings -> Redirect URL). Set that to:
       https://<your-deployed-domain>/payment/callback
   Razorpay appends razorpay_payment_id, razorpay_payment_link_id,
   razorpay_payment_link_reference_id, razorpay_payment_link_status, and
   razorpay_signature as query params to that URL.
4. /payment/callback (in main.py) verifies the signature with
   verify_payment_link_signature() below, marks the matching report_id
   (== razorpay_payment_link_reference_id) as paid, and redirects the
   browser back to the site so the frontend can offer the PDF download.

If RAZORPAY_KEY_SECRET is not configured, signature verification is
skipped and the callback trusts the `status == paid` query param instead
— convenient for local testing, but you should set the real key secret
(Razorpay Dashboard -> Settings -> API Keys) before going live so a
forged callback URL can't unlock a report for free.
"""

import hmac
import hashlib
from typing import Optional


def verify_payment_link_signature(
    payment_link_id: str,
    payment_link_reference_id: str,
    payment_link_status: str,
    payment_id: str,
    signature: str,
    key_secret: str,
) -> bool:
    """
    Recreates Razorpay's documented Payment Link callback signature:
    HMAC-SHA256 hex digest of
    "<payment_link_id>|<payment_link_reference_id>|<payment_link_status>|<payment_id>"
    keyed with the account's key_secret, compared to the signature Razorpay
    sent back.
    """
    if not key_secret:
        return False

    payload = "|".join(
        [payment_link_id or "", payment_link_reference_id or "", payment_link_status or "", payment_id or ""]
    )
    expected = hmac.new(
        key_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def build_payment_url(base_link: str, report_id: str) -> str:
    """Append the report_id as Razorpay's reference_id query param."""
    separator = "&" if "?" in base_link else "?"
    return f"{base_link}{separator}reference_id={report_id}"
