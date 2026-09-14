// Mobile bottom-sheet toggle for the sidebar. No-op on desktop, where the toggle
// button is hidden by CSS and the sidebar is always fully visible.

function initSidebarDrawer({ toggleBtn, sidebar }) {
  if (!toggleBtn || !sidebar) return;
  toggleBtn.addEventListener("click", () => {
    const open = sidebar.classList.toggle("open");
    toggleBtn.setAttribute("aria-expanded", String(open));
  });
}
