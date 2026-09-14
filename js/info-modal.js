// First-visit "how this works" popup, reopenable anytime via the topnav button.
// Uses localStorage to avoid re-showing automatically on return visits; degrades
// gracefully (just re-shows every time) if storage is unavailable, e.g. Safari
// private mode throwing on setItem.

const INFO_SEEN_KEY = "dber_info_seen_v1";

function initInfoModal({ openBtn, modal, closeBtn, dismissBtn, backdrop }) {
  if (!modal) return;

  function open() {
    modal.hidden = false;
  }

  function close() {
    modal.hidden = true;
    try {
      localStorage.setItem(INFO_SEEN_KEY, "1");
    } catch (e) {
      // ignore — storage unavailable, just won't remember across reloads
    }
  }

  openBtn?.addEventListener("click", open);
  closeBtn?.addEventListener("click", close);
  dismissBtn?.addEventListener("click", close);
  backdrop?.addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) close();
  });

  let seen = false;
  try {
    seen = localStorage.getItem(INFO_SEEN_KEY) === "1";
  } catch (e) {
    // ignore — storage unavailable, treat as unseen
  }
  if (!seen) open();
}
