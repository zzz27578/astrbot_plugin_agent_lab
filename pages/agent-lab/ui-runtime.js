// Small browser helpers shared by the existing full-screen canvas and forms.
// AstrBot's opaque-origin iframe may deny Storage access entirely.
const memory = new Map();
export const safeSession = {
  getItem(key) {
    if (memory.has(key)) return memory.get(key);
    try { return window.sessionStorage.getItem(key); } catch { return null; }
  },
  setItem(key, value) {
    memory.set(key, String(value));
    try { window.sessionStorage.setItem(key, value); } catch { /* page lifetime */ }
  },
  removeItem(key) {
    memory.set(key, null);
    try { window.sessionStorage.removeItem(key); } catch { /* page lifetime */ }
  },
};

export function preserveForm(root) {
  return [...root.querySelectorAll("input[id],textarea[id],select[id]")]
    .filter(el => !["password", "file"].includes(el.type))
    .map(el => ({ id: el.id, value: el.value, checked: el.checked, planVersion: el.dataset.planVersion,
                 focused: document.activeElement === el, start: el.selectionStart, end: el.selectionEnd }));
}

export function restoreForm(rows) {
  for (const row of rows) {
    const el = document.getElementById(row.id);
    if (!el) continue;
    el.value = row.value;
    if (row.planVersion !== undefined) el.dataset.planVersion = row.planVersion;
    if ("checked" in el) el.checked = row.checked;
    if (row.focused) {
      el.focus({ preventScroll: true });
      if (row.start !== null) {
        try { el.setSelectionRange(row.start, row.end); } catch { /* non-text */ }
      }
    }
  }
}

export async function boundedRequest(promise, timeout = 90000) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error("请求等待超时。操作可能仍在后台处理，请先刷新确认结果，避免重复提交。")), timeout);
    })]);
  } finally { clearTimeout(timer); }
}
