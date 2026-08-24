(() => {
  const legacyPagesHost = "learnwithstories.pages.dev";
  const workerOrigin = "https://learn-with-stories.aaankurankur.workers.dev";
  if (window.location.hostname !== legacyPagesHost) return;

  document.documentElement.style.visibility = "hidden";
  const destination = new URL(window.location.pathname, workerOrigin);
  destination.search = window.location.search;
  destination.hash = window.location.hash;
  window.location.replace(destination.href);
})();
