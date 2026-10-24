import type { RiskAssessment, RiskProfileName } from '@/api/types';

const PROFILE_ORDER: RiskProfileName[] = [
  'Kapitalschutz',
  'Defensiv',
  'Ausgewogen',
  'Wachstumsorientiert',
  'Dynamisch',
  'Aktien',
];

export function riskProfileForScoreX10(scoreX10: number): RiskProfileName {
  if (scoreX10 <= 24) return 'Kapitalschutz';
  if (scoreX10 <= 44) return 'Defensiv';
  if (scoreX10 <= 64) return 'Ausgewogen';
  if (scoreX10 <= 84) return 'Wachstumsorientiert';
  if (scoreX10 <= 94) return 'Dynamisch';
  return 'Aktien';
}

export function conservativeRiskProfile(
  baseProfile: string | null | undefined,
  overrideProfile: string | null | undefined,
): string {
  if (!baseProfile) return overrideProfile || 'Nicht dokumentiert';
  if (!overrideProfile) return baseProfile;
  const baseIndex = PROFILE_ORDER.indexOf(baseProfile as RiskProfileName);
  const overrideIndex = PROFILE_ORDER.indexOf(overrideProfile as RiskProfileName);
  if (baseIndex < 0) return overrideProfile;
  if (overrideIndex < 0) return baseProfile;
  return PROFILE_ORDER[Math.min(baseIndex, overrideIndex)];
}

export function RiskSummary({
  assessment,
}: {
  assessment: RiskAssessment | null;
}) {
  if (!assessment) {
    return (
      <section
        aria-label="Aktuelles Risikoprofil"
        className="border border-rule bg-canvas-panel p-5"
      >
        <p className="text-micro uppercase tracking-widest text-ink-subtle">
          Aktuelles Risikoprofil
        </p>
        <p className="mt-2 font-serif text-h2 text-ink">Noch nicht gespeichert</p>
        <p className="mt-2 max-w-prose text-caption text-ink-muted">
          Nach dem Speichern zeigt diese Zusammenfassung das dokumentierte Profil.
        </p>
      </section>
    );
  }

  const overrideActive = Boolean(assessment.is_overridden);
  const effectiveProfile = conservativeRiskProfile(
    assessment.final_profile,
    overrideActive ? assessment.override_profile : null,
  );

  return (
    <section
      aria-label="Aktuelles Risikoprofil"
      className="border border-rule bg-canvas-panel p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-micro uppercase tracking-widest text-ink-subtle">
            Aktuelles Risikoprofil
          </p>
          <p className="mt-2 font-serif text-h2 text-ink">{effectiveProfile}</p>
        </div>
        {overrideActive ? (
          <span className="border border-status-neutral px-3 py-1 text-micro uppercase tracking-widest text-status-neutral">
            Override · tieferer Wert zaehlt
          </span>
        ) : (
          <span className="border border-rule px-3 py-1 text-micro uppercase tracking-widest text-ink-subtle">
            Standardlogik
          </span>
        )}
      </div>
      <dl className="mt-4 grid gap-3 text-caption sm:grid-cols-3">
        <div>
          <dt className="text-ink-subtle">Risikofaehigkeit</dt>
          <dd className="mt-1 font-semibold text-ink">
            {assessment.risk_capacity_profile}
          </dd>
        </div>
        <div>
          <dt className="text-ink-subtle">Risikobereitschaft</dt>
          <dd className="mt-1 font-semibold text-ink">
            {assessment.risk_willingness_profile}
          </dd>
        </div>
        <div>
          <dt className="text-ink-subtle">Anlagehorizont</dt>
          <dd className="mt-1 font-semibold text-ink">
            {assessment.investment_horizon_label}
          </dd>
        </div>
      </dl>
      {overrideActive ? (
        <p className="mt-4 max-w-prose text-caption text-ink-muted">
          {assessment.override_reason || 'Override ohne erfasste Begruendung.'}
        </p>
      ) : null}
    </section>
  );
}

