/**
 * AstrBot plugin views run in an opaque-origin sandbox. Accessing the Storage
 * property itself can throw there, so even acquiring it must stay inside try.
 * Keep edits usable for this page lifetime when browser persistence is denied.
 */
type StoreName = "sessionStorage" | "localStorage";
const fallback: Record<StoreName, Map<string, string | null>> = {
  sessionStorage: new Map(),
  localStorage: new Map(),
};

function read(store: StoreName, key: string): string | null {
  const memory = fallback[store];
  if (memory.has(key)) return memory.get(key) ?? null;
  try {
    return window[store].getItem(key);
  } catch {
    return null;
  }
}

function write(store: StoreName, key: string, value: string): boolean {
  const text = String(value);
  fallback[store].set(key, text);
  try {
    window[store].setItem(key, text);
    return true;
  } catch {
    return false;
  }
}

function remove(store: StoreName, key: string): boolean {
  // A tombstone prevents a failed remove from resurrecting an older value.
  fallback[store].set(key, null);
  try {
    window[store].removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export const safeSessionGet = (key: string): string | null =>
  read("sessionStorage", key);
export const safeSessionSet = (key: string, value: string): boolean =>
  write("sessionStorage", key, value);
export const safeSessionRemove = (key: string): boolean =>
  remove("sessionStorage", key);
export const safeLocalGet = (key: string): string | null =>
  read("localStorage", key);
export const safeLocalSet = (key: string, value: string): boolean =>
  write("localStorage", key, value);
export const safeLocalRemove = (key: string): boolean =>
  remove("localStorage", key);
