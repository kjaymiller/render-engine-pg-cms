const DEFAULT_BASE = "http://localhost:8000";

async function getBase() {
  // Prefer storage.local; fall back to sync; fall back to default.
  try {
    const { cmsBase } = await browser.storage.local.get("cmsBase");
    if (cmsBase) return cmsBase;
  } catch (_) {}
  try {
    const { cmsBase } = await browser.storage.sync.get("cmsBase");
    if (cmsBase) return cmsBase;
  } catch (_) {}
  return DEFAULT_BASE;
}

function normalize(base) {
  return base.replace(/\/+$/, "");
}

async function currentTab() {
  const tabs = await browser.tabs.query({ active: true, currentWindow: true });
  return tabs[0] || {};
}

async function buildTarget() {
  const base = normalize(await getBase());
  const tab = await currentTab();
  const params = new URLSearchParams();
  if (tab.url) params.set("url", tab.url);
  if (tab.title) params.set("title", tab.title);
  const qs = params.toString();
  return {
    tab,
    url: `${base}/quick${qs ? "?" + qs : ""}`,
  };
}

(async () => {
  try {
    const { tab, url } = await buildTarget();
    document.getElementById("url").value = tab.url || "";
    document.getElementById("title").value = tab.title || "";
    document.getElementById("target").textContent = "→ " + url;

    document.getElementById("go").addEventListener("click", async () => {
      await browser.tabs.create({ url });
      window.close();
    });
  } catch (e) {
    document.getElementById("err").textContent = String(e);
  }

  document.getElementById("opts").addEventListener("click", () => {
    browser.runtime.openOptionsPage();
  });
})();
