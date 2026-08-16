/* ==========================================================================
   AI Vedic Astrology Report — script.js
   Handles: field/image validation, a simple custom calendar for Date of
   Birth (no Time of Birth is collected), drag-and-drop upload, submitting
   the multipart form to the backend, animated progress steps while
   waiting, rendering the free ~30% teaser (problems in red, solutions in
   green), and the Rs 9 Razorpay unlock -> paid PDF download flow.

   Note: the face photo is uploaded purely to be stored alongside the
   user's record — it is never analyzed by the AI model. Only name, date
   of birth, and place of birth are sent for report generation.
   ========================================================================== */

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const API_BASE_URL = window.PALMAI_API_BASE_URL || "";
const STATUS_POLL_INTERVAL_MS = 4000;

// ---------------------------------------------------------------------------
// Element references
// ---------------------------------------------------------------------------

const form = document.getElementById("palmForm");
const submitBtn = document.getElementById("submitBtn");
const formNote = document.getElementById("formNote");

const formCard = document.getElementById("formCard");
const loadingCard = document.getElementById("loadingCard");
const errorCard = document.getElementById("errorCard");
const resultCard = document.getElementById("resultCard");

const errorMessageEl = document.getElementById("errorMessage");
const tryAgainBtn = document.getElementById("tryAgainBtn");

const rashiBadge = document.getElementById("rashiBadge");
const rashiValueEl = document.getElementById("rashiValue");
const issueChipsEl = document.getElementById("issueChips");
const teaserContentEl = document.getElementById("teaserContent");
const lockedNotice = document.getElementById("lockedNotice");

const paywallSection = document.getElementById("paywallSection");
const unlockBtn = document.getElementById("unlockBtn");
const unlockAmountEl = document.getElementById("unlockAmount");
const paymentWaiting = document.getElementById("paymentWaiting");
const checkPaymentBtn = document.getElementById("checkPaymentBtn");

const downloadSection = document.getElementById("downloadSection");
const downloadPdfBtn = document.getElementById("downloadPdfBtn");
const newReportBtn = document.getElementById("newReportBtn");

const progressStepsEl = document.getElementById("progressSteps");
const progressItems = Array.from(progressStepsEl.querySelectorAll("li"));

const fields = {
  name: document.getElementById("name"),
  email: document.getElementById("email"),
  dob: document.getElementById("dob"),
  place: document.getElementById("place"),
  confirm: document.getElementById("confirm"),
};

const fileInputs = {
  facePhoto: document.getElementById("facePhoto"),
};

let selectedFiles = {
  facePhoto: null,
};

let currentReportId = null;
let pollTimer = null;
let progressTimer = null;

// ---------------------------------------------------------------------------
// Simple calendar widget (Date of Birth)
// ---------------------------------------------------------------------------

const dobDisplay = document.getElementById("dobDisplay");
const dobHidden = document.getElementById("dob");
const calendarWrap = document.getElementById("calendarInputWrap");
const calendarPopup = document.getElementById("calendarPopup");
const calMonthSelect = document.getElementById("calMonthSelect");
const calYearSelect = document.getElementById("calYearSelect");
const calTitle = document.getElementById("calTitle");
const calDays = document.getElementById("calDays");
const calPrevMonth = document.getElementById("calPrevMonth");
const calNextMonth = document.getElementById("calNextMonth");
const calToday = document.getElementById("calToday");

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const today = new Date();
const MAX_YEAR = today.getFullYear();
const MIN_YEAR = today.getFullYear() - 100;

let viewYear = today.getFullYear() - 25; // a reasonable default starting point
let viewMonth = 0;
let selectedDate = null; // {year, month, day}

function pad2(n) {
  return String(n).padStart(2, "0");
}

function isoFromParts(year, month, day) {
  return `${year}-${pad2(month + 1)}-${pad2(day)}`;
}

function displayFromParts(year, month, day) {
  return `${pad2(day)}-${pad2(month + 1)}-${year}`;
}

function populateMonthYearSelects() {
  calMonthSelect.innerHTML = MONTH_NAMES
    .map((m, i) => `<option value="${i}">${m}</option>`)
    .join("");

  const years = [];
  for (let y = MAX_YEAR; y >= MIN_YEAR; y--) years.push(y);
  calYearSelect.innerHTML = years.map((y) => `<option value="${y}">${y}</option>`).join("");
}

function daysInMonth(year, month) {
  return new Date(year, month + 1, 0).getDate();
}

function renderCalendar() {
  calMonthSelect.value = String(viewMonth);
  calYearSelect.value = String(viewYear);
  calTitle.textContent = `${MONTH_NAMES[viewMonth]} ${viewYear}`;

  const firstWeekday = new Date(viewYear, viewMonth, 1).getDay();
  const totalDays = daysInMonth(viewYear, viewMonth);

  const cells = [];
  for (let i = 0; i < firstWeekday; i++) {
    cells.push('<span class="cal-day cal-day-empty"></span>');
  }

  for (let day = 1; day <= totalDays; day++) {
    const isFuture = new Date(viewYear, viewMonth, day) > today;
    const isSelected =
      selectedDate &&
      selectedDate.year === viewYear &&
      selectedDate.month === viewMonth &&
      selectedDate.day === day;

    const classes = ["cal-day"];
    if (isSelected) classes.push("cal-day-selected");
    if (isFuture) classes.push("cal-day-disabled");

    cells.push(
      `<button type="button" class="${classes.join(" ")}" data-day="${day}" ${isFuture ? "disabled" : ""}>${day}</button>`
    );
  }

  calDays.innerHTML = cells.join("");

  calDays.querySelectorAll(".cal-day:not(.cal-day-empty):not(.cal-day-disabled)").forEach((btn) => {
    btn.addEventListener("click", () => {
      const day = parseInt(btn.dataset.day, 10);
      selectDate(viewYear, viewMonth, day);
    });
  });
}

function selectDate(year, month, day) {
  selectedDate = { year, month, day };
  dobHidden.value = isoFromParts(year, month, day);
  dobDisplay.value = displayFromParts(year, month, day);
  clearFieldError("err-dob");
  dobDisplay.classList.remove("invalid");
  closeCalendar();
}

function openCalendar() {
  populateMonthYearSelects();
  renderCalendar();
  calendarPopup.hidden = false;
}

function closeCalendar() {
  calendarPopup.hidden = true;
}

dobDisplay.addEventListener("click", () => {
  if (calendarPopup.hidden) openCalendar();
  else closeCalendar();
});

document.addEventListener("click", (e) => {
  if (!calendarWrap.contains(e.target)) closeCalendar();
});

calMonthSelect.addEventListener("change", () => {
  viewMonth = parseInt(calMonthSelect.value, 10);
  renderCalendar();
});

calYearSelect.addEventListener("change", () => {
  viewYear = parseInt(calYearSelect.value, 10);
  renderCalendar();
});

calPrevMonth.addEventListener("click", () => {
  viewMonth -= 1;
  if (viewMonth < 0) {
    viewMonth = 11;
    viewYear = Math.max(MIN_YEAR, viewYear - 1);
  }
  renderCalendar();
});

calNextMonth.addEventListener("click", () => {
  viewMonth += 1;
  if (viewMonth > 11) {
    viewMonth = 0;
    viewYear = Math.min(MAX_YEAR, viewYear + 1);
  }
  renderCalendar();
});

calToday.addEventListener("click", () => {
  viewYear = today.getFullYear();
  viewMonth = today.getMonth();
  renderCalendar();
});

// ---------------------------------------------------------------------------
// Drag & drop / click-to-upload wiring
// ---------------------------------------------------------------------------

document.querySelectorAll(".dropzone").forEach((zone) => {
  const targetName = zone.dataset.target;
  const input = fileInputs[targetName];

  zone.addEventListener("click", () => input.click());

  zone.addEventListener("dragover", (e) => {
    e.preventDefault();
    zone.classList.add("dragover");
  });

  zone.addEventListener("dragleave", () => {
    zone.classList.remove("dragover");
  });

  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      input.files = e.dataTransfer.files;
      handleFileSelected(targetName, e.dataTransfer.files[0]);
    }
  });

  input.addEventListener("change", () => {
    if (input.files && input.files[0]) {
      handleFileSelected(targetName, input.files[0]);
    }
  });
});

function handleFileSelected(targetName, file) {
  const validTypes = ["image/jpeg", "image/png", "image/webp", "image/jpg"];
  if (!validTypes.includes(file.type)) {
    setFieldError(`err-${targetName}`, "Please upload a JPEG, PNG, or WEBP image.");
    return;
  }

  clearFieldError(`err-${targetName}`);
  document.getElementById(`upload-face`)
    .querySelector(".dropzone").classList.remove("invalid");

  selectedFiles[targetName] = file;

  const previewImg = document.getElementById(`preview-${targetName}`);
  const reader = new FileReader();
  reader.onload = (e) => {
    previewImg.src = e.target.result;
    previewImg.hidden = false;
    previewImg.closest(".dropzone").querySelector(".dropzone-placeholder").style.display = "none";
  };
  reader.readAsDataURL(file);
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

function setFieldError(errId, message) {
  const el = document.getElementById(errId);
  if (el) el.textContent = message;
}

function clearFieldError(errId) {
  const el = document.getElementById(errId);
  if (el) el.textContent = "";
}

function clearAllErrors() {
  document.querySelectorAll(".error-msg").forEach((el) => (el.textContent = ""));
  document.querySelectorAll("input").forEach((el) => el.classList.remove("invalid"));
  document.querySelectorAll(".dropzone").forEach((el) => el.classList.remove("invalid"));
  formNote.hidden = true;
}

function validateForm() {
  clearAllErrors();
  let isValid = true;

  if (!fields.name.value.trim()) {
    setFieldError("err-name", "Full name is required.");
    fields.name.classList.add("invalid");
    isValid = false;
  }

  if (!fields.email.value.trim()) {
    setFieldError("err-email", "Email address is required.");
    fields.email.classList.add("invalid");
    isValid = false;
  } else {
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailPattern.test(fields.email.value.trim())) {
      setFieldError("err-email", "Please enter a valid email address.");
      fields.email.classList.add("invalid");
      isValid = false;
    }
  }

  if (!fields.dob.value) {
    setFieldError("err-dob", "Please pick your date of birth.");
    dobDisplay.classList.add("invalid");
    isValid = false;
  }

  if (!fields.place.value.trim()) {
    setFieldError("err-place", "Place of birth is required.");
    fields.place.classList.add("invalid");
    isValid = false;
  }

  if (!selectedFiles.facePhoto) {
    setFieldError("err-facePhoto", "A face photo is required.");
    document.querySelector('[data-target="facePhoto"]').classList.add("invalid");
    isValid = false;
  }

  if (!fields.confirm.checked) {
    setFieldError("err-confirm", "Please confirm the information is correct.");
    isValid = false;
  }

  return isValid;
}

// ---------------------------------------------------------------------------
// View switching
// ---------------------------------------------------------------------------

function showCard(card) {
  [formCard, loadingCard, errorCard, resultCard].forEach((c) => (c.hidden = true));
  card.hidden = false;
}

// ---------------------------------------------------------------------------
// Progress step animation
// ---------------------------------------------------------------------------

function startProgressAnimation() {
  progressItems.forEach((li) => li.classList.remove("active", "done"));
  let index = 0;

  const stepDuration = 1400;

  progressTimer = setInterval(() => {
    if (index > 0) {
      progressItems[index - 1].classList.remove("active");
      progressItems[index - 1].classList.add("done");
    }
    if (index < progressItems.length) {
      progressItems[index].classList.add("active");
      index += 1;
    } else {
      clearInterval(progressTimer);
    }
  }, stepDuration);
}

function stopProgressAnimation() {
  if (progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
}

// ---------------------------------------------------------------------------
// Result rendering (teaser + paywall / unlocked state)
// ---------------------------------------------------------------------------

function renderResult(data) {
  currentReportId = data.report_id;

  if (data.rashi) {
    rashiValueEl.textContent = data.rashi;
    rashiBadge.hidden = false;
  } else {
    rashiBadge.hidden = true;
  }

  issueChipsEl.innerHTML = (data.issues || [])
    .map((label) => `<span class="issue-chip">&#9888; ${escapeHtml(label)} Detected</span>`)
    .join("");

  teaserContentEl.innerHTML = data.teaser_html || "";

  const amount = data.amount || 9;
  unlockAmountEl.textContent = `\u20B9${amount}`;

  setPaidState(!!data.paid);

  showCard(resultCard);
}

function setPaidState(paid) {
  if (paid) {
    stopPolling();
    lockedNotice.hidden = true;
    paywallSection.hidden = true;
    paymentWaiting.hidden = true;
    downloadSection.hidden = false;
  } else {
    lockedNotice.hidden = false;
    paywallSection.hidden = false;
    downloadSection.hidden = true;
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Payment polling
// ---------------------------------------------------------------------------

function startPolling() {
  stopPolling();
  pollTimer = setInterval(checkPaymentStatus, STATUS_POLL_INTERVAL_MS);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function checkPaymentStatus() {
  if (!currentReportId) return;
  try {
    const res = await fetch(`${API_BASE_URL}/report/${currentReportId}/status`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.paid) {
      setPaidState(true);
    }
  } catch (_) {
    /* network hiccup while polling — try again next tick */
  }
}

unlockBtn.addEventListener("click", async () => {
  if (!currentReportId) return;
  try {
    const res = await fetch(`${API_BASE_URL}/report/${currentReportId}`);
    const data = await res.json();
    if (data.payment_url) {
      window.open(data.payment_url, "_blank", "noopener");
    }
  } catch (_) {
    /* fall through — polling/manual check still available */
  }
  paymentWaiting.hidden = false;
  startPolling();
});

checkPaymentBtn.addEventListener("click", () => {
  checkPaymentStatus();
});

downloadPdfBtn.addEventListener("click", () => {
  if (!currentReportId) return;
  const link = document.createElement("a");
  link.href = `${API_BASE_URL}/report/${currentReportId}/download`;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
});

// ---------------------------------------------------------------------------
// Submit handler
// ---------------------------------------------------------------------------

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  if (!validateForm()) {
    formNote.hidden = false;
    formNote.textContent = "Please fix the highlighted fields before continuing.";
    return;
  }

  submitBtn.disabled = true;
  showCard(loadingCard);
  startProgressAnimation();

  const formData = new FormData();
  formData.append("name", fields.name.value.trim());
  formData.append("email", fields.email.value.trim());
  formData.append("dob", fields.dob.value);
  formData.append("place", fields.place.value.trim());
  formData.append("facePhoto", selectedFiles.facePhoto);

  try {
    const response = await fetch(`${API_BASE_URL}/analyze`, {
      method: "POST",
      body: formData,
    });

    stopProgressAnimation();

    if (!response.ok) {
      let detail = "Something went wrong. Please try again.";
      try {
        const errJson = await response.json();
        if (errJson && errJson.detail) detail = errJson.detail;
      } catch (_) {
        /* ignore parse errors, use default message */
      }
      throw new Error(detail);
    }

    const data = await response.json();

    if (!data.success) {
      throw new Error("Something went wrong. Please try again.");
    }

    submitBtn.disabled = false;
    renderResult(data);
  } catch (err) {
    stopProgressAnimation();
    submitBtn.disabled = false;
    errorMessageEl.textContent = err.message || "Please try again.";
    showCard(errorCard);
  }
});

// ---------------------------------------------------------------------------
// Result card actions
// ---------------------------------------------------------------------------

newReportBtn.addEventListener("click", () => {
  form.reset();
  selectedFiles = { facePhoto: null };
  selectedDate = null;
  dobHidden.value = "";
  dobDisplay.value = "";
  currentReportId = null;
  stopPolling();

  document.querySelectorAll(".preview-img").forEach((img) => {
    img.hidden = true;
    img.src = "";
  });
  document.querySelectorAll(".dropzone-placeholder").forEach((el) => (el.style.display = ""));

  clearAllErrors();

  // Drop any report_id/paid params from a previous payment redirect.
  if (window.history && window.history.replaceState) {
    window.history.replaceState({}, "", window.location.pathname);
  }

  showCard(formCard);
});

tryAgainBtn.addEventListener("click", () => {
  showCard(formCard);
});

// ---------------------------------------------------------------------------
// Restore state after redirect back from the Razorpay payment page
// ---------------------------------------------------------------------------

async function restoreFromUrlIfNeeded() {
  const params = new URLSearchParams(window.location.search);
  const reportId = params.get("report_id");
  if (!reportId) return;

  try {
    const res = await fetch(`${API_BASE_URL}/report/${reportId}`);
    if (!res.ok) return;
    const data = await res.json();
    renderResult(data);

    if (!data.paid && params.get("payment_error")) {
      paymentWaiting.hidden = false;
      startPolling();
    } else if (!data.paid) {
      // Came back before Razorpay's redirect finished / webhook landed.
      paymentWaiting.hidden = false;
      startPolling();
    }
  } catch (_) {
    /* if this fails, the person can just fill the form again */
  }
}

restoreFromUrlIfNeeded();
