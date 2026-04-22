const DEFAULT_BASE = "http://localhost:8000";
const $base = document.getElementById("cmsBase");
const $status = document.getElementById("status");

async function readBase() {
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

(async () => {
  $base.value = await readBase();
})();

document.getElementById("f").addEventListener("submit", async (e) => {
  e.preventDefault();
  const value = $base.value.trim();
  await browser.storage.local.set({ cmsBase: value });
  try {
    await browser.storage.sync.set({ cmsBase: value });
  } catch (_) {}
  $status.textContent = "Saved";
  setTimeout(() => ($status.textContent = ""), 1500);
});
