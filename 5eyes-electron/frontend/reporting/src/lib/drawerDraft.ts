/**
 * Sprint U-23+U-24 (Roadmap-Punkte 23+24, 2026-06-04): Drawer Draft-Storage
 * + Dirty-State-Detection.
 *
 * Pure-Functions damit Tests ohne React-Render laufen.
 *
 * Dirty-State (U-24)
 * ------------------
 * Detection durch JSON-deep-equal von currentValues vs originalValues
 * (Forms haben kleine Payloads -> JSON.stringify-Compare ist OK).
 *
 * Draft-Storage (U-23)
 * --------------------
 * sessionStorage statt localStorage damit ein Logout / Tab-Close das
 * Draft killt (kein verwaister Berater-Text der im naechsten Login
 * eines anderen Beraters auftaucht).
 *
 * Key-Format: 5eyes:draft:{mandate_id}:{form_id}
 */


export interface DraftSnapshot {
  values: Record<string, unknown>;
  savedAt: string;  // ISO
}


export function isDirty(
  current: Record<string, unknown>,
  original: Record<string, unknown>,
): boolean {
  return JSON.stringify(current) !== JSON.stringify(original);
}


/**
 * Liefert die Liste der Feld-Namen die sich geaendert haben.
 * Nuetzlich fuer UI-Hint "diese Felder gehen verloren wenn du jetzt
 * abbrichst".
 */
export function dirtyFields(
  current: Record<string, unknown>,
  original: Record<string, unknown>,
): string[] {
  const allKeys = new Set([...Object.keys(current), ...Object.keys(original)]);
  const result: string[] = [];
  for (const key of allKeys) {
    if (JSON.stringify(current[key]) !== JSON.stringify(original[key])) {
      result.push(key);
    }
  }
  return result;
}


export function createDraftKey(mandateId: string, formId: string): string {
  // Strikte Whitelist gegen storage-key-injection
  const safeMandate = String(mandateId).replace(/[^A-Za-z0-9_\-]/g, '_');
  const safeForm = String(formId).replace(/[^A-Za-z0-9_\-]/g, '_');
  return `5eyes:draft:${safeMandate}:${safeForm}`;
}


function _getStorage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}


export function saveDraft(
  key: string,
  values: Record<string, unknown>,
): boolean {
  const storage = _getStorage();
  if (!storage) return false;
  const snapshot: DraftSnapshot = {
    values,
    savedAt: new Date().toISOString(),
  };
  try {
    storage.setItem(key, JSON.stringify(snapshot));
    return true;
  } catch {
    // QuotaExceeded oder SecurityError — degraded
    return false;
  }
}


export function loadDraft(key: string): DraftSnapshot | null {
  const storage = _getStorage();
  if (!storage) return null;
  let raw: string | null;
  try {
    raw = storage.getItem(key);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (
      parsed
      && typeof parsed === 'object'
      && 'values' in parsed
      && 'savedAt' in parsed
      && typeof parsed.savedAt === 'string'
      && parsed.values !== null
      && typeof parsed.values === 'object'
    ) {
      return parsed as DraftSnapshot;
    }
    return null;
  } catch {
    return null;
  }
}


export function clearDraft(key: string): boolean {
  const storage = _getStorage();
  if (!storage) return false;
  try {
    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}


/**
 * Sprint U-24: Confirm-Message fuer Dirty-Drawer-Close.
 * Berater-tauglich, kein Tech-Jargon.
 */
export function buildDirtyCloseMessage(dirtyFieldNames: string[]): string {
  if (dirtyFieldNames.length === 0) return '';
  if (dirtyFieldNames.length === 1) {
    return `Aenderung am Feld "${dirtyFieldNames[0]}" geht verloren. Schliessen?`;
  }
  return (
    `Aenderungen an ${dirtyFieldNames.length} Feldern gehen verloren. `
    + `Schliessen?`
  );
}
