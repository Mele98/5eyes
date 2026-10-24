// O-1 (CIO-Entscheid): Der Risikoprofil-Editor (Beta) ist gesperrt. Er wich vom
// Standard-Fragebogen ab; erfasst wird nur im Standard-Fragebogen der
// Desktop-App. Der Server lehnt Profile aus dem Editor ab.
export function ProfilingEditorLocked() {
  return (
    <main className="mx-auto max-w-editorial px-page-x py-page-y" role="alert">
      <h1 className="text-lg font-semibold">Risikoprofil-Editor gesperrt</h1>
      <p className="mt-2">
        Bitte das Risikoprofil im Standard-Fragebogen der Desktop-App erfassen.
      </p>
    </main>
  );
}
