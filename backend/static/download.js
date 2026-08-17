/* ==========================================================================
   download.html — script.js companion.

   Looks up the latest PAID report matching an email + phone number (via
   POST /download/lookup) and, if found, downloads the PDF directly. This
   is the recovery path after a Razorpay payment: Razorpay's Redirect URL
   points here, and the "I've completed the payment" button on the main
   results page also links here — either way, the person just re-enters
   the same email + phone they submitted originally to fetch their PDF.
   ========================================================================== */

const API_BASE_URL = window.PALMAI_API_BASE_URL || "";

const form = document.getElementById("lookupForm");
const lookupBtn = document.getElementById("lookupBtn");
const lookupStatus = document.getElementById("lookupStatus");
const emailInput = document.getElementById("lookupEmail");
const phoneInput = document.getElementById("lookupPhone");

function setFieldError(id, message) {
  const el = document.getElementById(id);
  if (el) el.textContent = message;
}

function clearFieldErrors() {
  document.querySelectorAll(".error-msg").forEach((el) => (el.textContent = ""));
}

function showStatus(kind, html) {
  lookupStatus.hidden = false;
  lookupStatus.className = `lookup-status lookup-status-${kind}`;
  lookupStatus.innerHTML = html;
}

function hideStatus() {
  lookupStatus.hidden = true;
  lookupStatus.innerHTML = "";
}

// Prefill from query params (?email=...&phone=...), e.g. when linked from
// the main results page, or from Razorpay's redirect (which won't include
// these, but doesn't hurt to check).
(function prefillFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const email = params.get("email");
  const phone = params.get("phone");
  if (email) emailInput.value = email;
  if (phone) phoneInput.value = phone;

  if (params.get("razorpay_payment_link_status") === "paid" || params.get("paid") === "1") {
    showStatus(
      "info",
      "Payment received! Enter your email and phone number below to download your PDF."
    );
  }
})();

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearFieldErrors();
  hideStatus();

  const email = emailInput.value.trim();
  const phone = phoneInput.value.trim();

  let hasError = false;
  if (!email) {
    setFieldError("err-lookupEmail", "Email is required.");
    hasError = true;
  }
  if (!phone) {
    setFieldError("err-lookupPhone", "Phone number is required.");
    hasError = true;
  }
  if (hasError) return;

  lookupBtn.disabled = true;
  lookupBtn.querySelector(".btn-label").textContent = "Searching...";

  try {
    const res = await fetch(`${API_BASE_URL}/download/lookup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, phone }),
    });

    if (res.status === 404) {
      showStatus(
        "error",
        "We couldn't find a completed payment for these details. If you just paid, please wait a minute and try again — or make sure you're using the exact email and phone number you submitted with your birth details."
      );
      return;
    }

    if (!res.ok) {
      let detail = "Something went wrong. Please try again.";
      try {
        const errJson = await res.json();
        if (errJson && errJson.detail) detail = errJson.detail;
      } catch (_) {
        /* ignore */
      }
      showStatus("error", detail);
      return;
    }

    // Success: the response is the PDF itself. Turn it into a downloadable blob.
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : "astrology_report.pdf";

    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);

    showStatus("success", "&#10003; Found it! Your download should start automatically.");
  } catch (err) {
    showStatus("error", "Network error — please check your connection and try again.");
  } finally {
    lookupBtn.disabled = false;
    lookupBtn.querySelector(".btn-label").textContent = "Find & Download My PDF";
  }
});
