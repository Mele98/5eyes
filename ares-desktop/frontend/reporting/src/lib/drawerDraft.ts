/**
 * Sprint U-24 (Roadmap-Punkt 24, 2026-06-04): Dirty-State-Detection fuer
 * Drawer-Formulare.
 *
 * Pure-Functions damit Tests ohne React-Render laufen.
 *
 * Dirty-State (U-24)
 * ------------------
 * Detection durch JSON-deep-equal von currentValues vs originalValues
 * (Forms haben kleine Payloads -> JSON.stringify-Compare ist OK).
 *
 * Draft-Storage (U-23) wurde entfernt (W4-a3): die Speicherfunktionen
 * hatten keinen Produktaufrufer. Bleiben nur die Dirty-State-Helfer.
 */


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
