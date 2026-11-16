// ShieldVPN landing page: keeps the download button pointed at the newest APK
// without a redeploy. The static href already points to /releases/latest, so the
// page works even when the GitHub API is rate-limited or blocked.
(function () {
  "use strict";

  const REPO = "murshahsinov-bit/vpn-constructor";
  const download = document.getElementById("download");
  const meta = document.getElementById("release-meta");

  const year = document.getElementById("year");
  if (year) year.textContent = String(new Date().getFullYear());

  if (!download) return;

  const fallback = `https://github.com/${REPO}/releases/latest`;
  download.href = fallback;

  fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
    headers: { Accept: "application/vnd.github+json" },
  })
    .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
    .then((release) => {
      const apkAssets = (release.assets || []).filter((asset) => /\.apk$/i.test(asset.name));
      // Prefer the 64-bit build: it fits every phone made in the last decade.
      const apk = apkAssets.find((asset) => /arm64/i.test(asset.name)) || apkAssets[0];
      if (!apk) return;
      download.href = apk.browser_download_url;
      if (meta) {
        const size = (apk.size / (1024 * 1024)).toFixed(1).replace(".", ",");
        meta.textContent = `${release.tag_name} · ${apk.name} · ${size} МБ`;
      }
    })
    .catch(() => {
      // Offline, rate-limited or behind DPI: the static link still works.
    });
})();
