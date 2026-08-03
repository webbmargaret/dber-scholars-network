// Builds a mailto: link from the contribute form, plus a copy-paste fallback — some
// mail clients truncate long mailto bodies and some machines have no mail handler.

const CONTACT_EMAIL = "mew329@cornell.edu";
const MAILTO_BODY_SAFE_LENGTH = 1800;

function buildSubmissionText({ requestType, yourName, replyEmail, whichRecord, message }) {
  const lines = [
    `Request type: ${requestType}`,
    `Submitted name: ${yourName || "(not given)"}`,
    `Reply email: ${replyEmail || "(not given)"}`,
    `Which record (if editing): ${whichRecord || "(n/a — new entry)"}`,
    "",
    "Message:",
    message || "(none)",
  ];
  return lines.join("\n");
}

function initContributeForm({ form, scholarNames, fallbackTextarea, fallbackBox, mailBtn }) {
  const datalist = document.getElementById("scholar-names");
  if (datalist) {
    datalist.innerHTML = scholarNames.map((n) => `<option value="${n}"></option>`).join("");
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const data = new FormData(form);
    const bodyText = buildSubmissionText({
      requestType: data.get("requestType"),
      yourName: data.get("yourName"),
      replyEmail: data.get("replyEmail"),
      whichRecord: data.get("whichRecord"),
      message: data.get("message"),
    });

    const subject = `DBER Scholars Network — ${data.get("requestType")}`;
    fallbackTextarea.value = `To: ${CONTACT_EMAIL}\nSubject: ${subject}\n\n${bodyText}`;
    fallbackBox.style.display = "block";

    if (bodyText.length <= MAILTO_BODY_SAFE_LENGTH) {
      mailBtn.href = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(bodyText)}`;
      mailBtn.style.display = "inline-block";
    } else {
      mailBtn.style.display = "none";
    }

    fallbackBox.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  document.getElementById("copy-btn")?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(fallbackTextarea.value);
      const btn = document.getElementById("copy-btn");
      const original = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(() => (btn.textContent = original), 1500);
    } catch {
      fallbackTextarea.select();
    }
  });
}
