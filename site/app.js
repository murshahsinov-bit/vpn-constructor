// ShieldVPN landing page.
// 1. Points the download buttons at the newest APK without a redeploy.
// 2. Fills the price cards from the subscription worker, so the site, the bot
//    and the app always quote the same numbers.
(function () {
  "use strict";

  const REPO = "murshahsinov-bit/vpn-constructor";
  const PANEL = "https://vpn-auth.de1.netrun.io";

  const download = document.getElementById("download");
  const downloadAndroid = document.getElementById("download-android");
  const meta = document.getElementById("release-meta");
  const year = document.getElementById("year");

  if (year) year.textContent = String(new Date().getFullYear());

  const fallback = `https://github.com/${REPO}/releases/latest`;

  function applyApk(url) {
    [download, downloadAndroid].forEach((button) => {
      if (button) button.href = url;
    });
  }

  applyApk(fallback);

  fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
    headers: { Accept: "application/vnd.github+json" },
  })
    .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
    .then((release) => {
      const apkAssets = (release.assets || []).filter((asset) => /\.apk$/i.test(asset.name));
      // Prefer the 64-bit build: it fits every phone made in the last decade.
      const apk = apkAssets.find((asset) => /arm64/i.test(asset.name)) || apkAssets[0];
      if (!apk) return;
      applyApk(apk.browser_download_url);
      if (meta) {
        const size = (apk.size / (1024 * 1024)).toFixed(1).replace(".", ",");
        meta.textContent = `${release.tag_name} · ${apk.name} · ${size} МБ`;
      }
    })
    .catch(() => {
      // Offline, rate-limited or behind DPI: the static link still works.
    });

  const format = (value) => String(value).replace(/\B(?=(\d{3})+(?!\d))/g, " ");

  fetch(`${PANEL}/api/plans`)
    .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
    .then((data) => {
      (data.plans || []).forEach((plan) => {
        const price = document.querySelector(`[data-price="${plan.id}"]`);
        const stars = document.querySelector(`[data-stars="${plan.id}"]`);
        const card = document.querySelector(`[data-plan="${plan.id}"]`);
        if (price) price.textContent = format(plan.price_rub);
        if (stars) stars.textContent = format(plan.price_stars);
        if (card && plan.days >= 30) {
          const perMonth = Math.round(Number(plan.price_rub) / (Number(plan.days) / 30));
          const note = card.querySelector(".price-note");
          if (note) note.textContent = `${format(perMonth)} ₽ в месяц`;
        }
      });
      const trial = document.querySelector("[data-trial-days]");
      if (trial && data.trial_days) trial.textContent = String(data.trial_days);
    })
    .catch(() => {
      // Hard-coded prices in the HTML are the fallback.
    });
})();
