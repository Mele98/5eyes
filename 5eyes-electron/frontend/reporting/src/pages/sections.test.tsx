/**
 * Smoke-Tests für alle 15 Sub-App-Sektionen.
 *
 * Pro Sektion:
 * 1. Rendert ohne Crash (Schema-Drift-Schutz)
 * 2. Key-Content sichtbar (Datenpunkte aus Aggregator)
 * 3. Edge-Cases (leere Listen, fehlende Felder)
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/api/useUserRole', () => ({
  useUserRole: () => ({
    role: 'advisor',
    canEdit: false,
    loading: false,
    error: null,
  }),
}));

vi.mock('@/api/useReportNotes', () => ({
  useReportNotes: () => ({
    state: 'ready',
    data: null,
    error: null,
    reload: () => {},
    saving: false,
    saveError: null,
    save: async () => {},
  }),
}));

import { Cover } from './Cover';
import { Disclaimer } from './Disclaimer';
import { Inhaltsverzeichnis } from './Inhaltsverzeichnis';
import { Ausgangslage } from './Ausgangslage';
import { Positionen } from './Positionen';
import { Pruefpunkte } from './Pruefpunkte';
import { Erkenntnisse } from './Erkenntnisse';
import { AssetAllocation } from './AssetAllocation';
import { Risikowaehrungen } from './Risikowaehrungen';
import { Branchen } from './Branchen';
import { Goals } from './Goals';
import { Risikoprofil } from './Risikoprofil';
import { BuildingBlocks } from './BuildingBlocks';
import { StatementPm } from './StatementPm';
import { WeiteresVorgehen } from './WeiteresVorgehen';

import {
  makeAssetAllocation,
  makeAusgangslage,
  makeBranchen,
  makeBuildingBlocks,
  makeCover,
  makeDisclaimer,
  makeErkenntnisse,
  makeGoals,
  makeInhaltsverzeichnis,
  makePositionen,
  makePruefpunkte,
  makeRisikoprofil,
  makeRisikowaehrungen,
  makeStatementPm,
  makeWeiteresVorgehen,
} from '@/test/fixtures';

function withRouter(ui: React.ReactNode) {
  return <MemoryRouter>{ui}</MemoryRouter>;
}

describe('Section 1: Cover', () => {
  it('zeigt Client, Mandate, Advisor', () => {
    render(withRouter(<Cover data={makeCover()} />));
    expect(screen.getByText('Hans Muster')).toBeInTheDocument();
    expect(screen.getByText('MX-FOUNDATION-01')).toBeInTheDocument();
    expect(screen.getByText('Anna Beispiel')).toBeInTheDocument();
  });

  it('formatiert Datum im Swiss-Format DD.MM.YYYY', () => {
    render(withRouter(<Cover data={makeCover()} />));
    expect(screen.getByText('27.05.2026')).toBeInTheDocument();
  });
});

describe('Section 2: Disclaimer', () => {
  it('listet alle Hinweise', () => {
    render(withRouter(<Disclaimer data={makeDisclaimer()} />));
    expect(screen.getByText(/Beratungszwecken/)).toBeInTheDocument();
    expect(screen.getByText(/Vergangene Performance/)).toBeInTheDocument();
    expect(screen.getByText(/Monte-Carlo/)).toBeInTheDocument();
  });
});

describe('Section 3: Inhaltsverzeichnis', () => {
  it('listet Kapitel', () => {
    render(withRouter(<Inhaltsverzeichnis data={makeInhaltsverzeichnis()} />));
    expect(
      screen.queryAllByText(/Übersicht Ihrer Positionen/i).length,
    ).toBeGreaterThan(0);
  });
});

describe('Section 4: Ausgangslage', () => {
  it('rendert Client-Info mit Swiss-Format', () => {
    render(withRouter(<Ausgangslage data={makeAusgangslage()} />));
    expect(screen.getByText('49 Jahre')).toBeInTheDocument();
    expect(screen.getByText('16 Jahre')).toBeInTheDocument();
    expect(screen.getByText('Defensiv')).toBeInTheDocument();
    expect(screen.getByText('Frühpension mit 60')).toBeInTheDocument();
    expect(screen.getByText("CHF 66'000")).toBeInTheDocument();
  });

  it('rendert Wealth-Summary', () => {
    render(withRouter(<Ausgangslage data={makeAusgangslage()} />));
    expect(screen.getByText('Gesamtvermögen')).toBeInTheDocument();
    expect(screen.getByText("CHF 2'500'000")).toBeInTheDocument();
  });

  it('rendert alle 6 KPI-Karten', () => {
    render(withRouter(<Ausgangslage data={makeAusgangslage()} />));
    expect(screen.getByText('Risky-Fraction')).toBeInTheDocument();
    expect(screen.getByText('Zielerreichung')).toBeInTheDocument();
    expect(screen.getByText('Erw. Volatilität')).toBeInTheDocument();
    expect(screen.getByText('Erw. Rendite')).toBeInTheDocument();
    expect(screen.getByText('Max Drawdown')).toBeInTheDocument();
    expect(screen.getByText('VaR 95 %')).toBeInTheDocument();
  });

  it('rendert Alter 0 als em-dash', () => {
    const data = makeAusgangslage();
    data.client_info.alter = 0;
    render(withRouter(<Ausgangslage data={data} />));
    expect(screen.queryByText('0 Jahre')).not.toBeInTheDocument();
  });
});

describe('Section 5: Positionen', () => {
  it('rendert Bucket + ISIN + Swiss-Wert', () => {
    render(withRouter(<Positionen data={makePositionen()} />));
    expect(screen.getByText('Test-ETF SPI Schweiz')).toBeInTheDocument();
    expect(screen.getByText('CH0244767585')).toBeInTheDocument();
    expect(screen.getByText("CHF 300'000")).toBeInTheDocument();
  });

  it('handelt leere groups graziös', () => {
    render(
      withRouter(
        <Positionen
          data={{
            groups: [],
            total_rappen: 0,
            has_recommendation_run: false,
            hinweis: '',
          }}
        />,
      ),
    );
    expect(screen.getByText(/Keine Positionen erfasst/)).toBeInTheDocument();
  });
});

describe('Section 6: Pruefpunkte', () => {
  it('listet Bloecke', () => {
    render(withRouter(<Pruefpunkte data={makePruefpunkte()} />));
    expect(screen.getByText('Diversifikation')).toBeInTheDocument();
    expect(screen.getByText('Währungsrisiken')).toBeInTheDocument();
  });

  it('handelt leere bloecke graziös', () => {
    render(withRouter(<Pruefpunkte data={{ bloecke: [] }} />));
    expect(screen.getByText(/Keine Prüfpunkte erfasst/)).toBeInTheDocument();
  });
});

describe('Section 7: Erkenntnisse', () => {
  it('rendert alle 4 Ampel-Stati', () => {
    render(withRouter(<Erkenntnisse data={makeErkenntnisse()} />));
    expect(screen.getByText('OK')).toBeInTheDocument();
    expect(screen.getByText('Achtung')).toBeInTheDocument();
    expect(screen.getByText('Handeln')).toBeInTheDocument();
    expect(screen.getByText('Pendant')).toBeInTheDocument();
  });

  it('handelt leere checks graziös', () => {
    render(withRouter(<Erkenntnisse data={{ checks: [] }} />));
    expect(screen.getByText(/Keine Erkenntnisse erfasst/)).toBeInTheDocument();
  });
});

describe('Section 8: AssetAllocation', () => {
  it('rendert Items', () => {
    render(
      withRouter(
        <AssetAllocation
          data={makeAssetAllocation()}
          mandateId="test"
          onReload={() => {}}
        />,
      ),
    );
    expect(screen.getAllByText('Aktien').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Obligationen').length).toBeGreaterThan(0);
  });
});

describe('Section 9: Risikowaehrungen', () => {
  it('rendert FX-Kategorien', () => {
    render(
      withRouter(
        <Risikowaehrungen
          data={makeRisikowaehrungen()}
          mandateId="test"
          onReload={() => {}}
        />,
      ),
    );
    expect(screen.getByText('CHF')).toBeInTheDocument();
    expect(screen.getByText('USD')).toBeInTheDocument();
  });
});

describe('Section 10: Branchen', () => {
  it('rendert Sektoren', () => {
    render(
      withRouter(
        <Branchen
          data={makeBranchen()}
          mandateId="test"
          onReload={() => {}}
        />,
      ),
    );
    expect(screen.getByText('Tech')).toBeInTheDocument();
    expect(screen.getByText('Health')).toBeInTheDocument();
  });
});

describe('Section 11: Goals', () => {
  it('rendert Goals + Achievement-Score', () => {
    render(withRouter(<Goals data={makeGoals()} />));
    expect(screen.getByText('Frühpension mit 60')).toBeInTheDocument();
    expect(screen.getByText('Haus-Umbau')).toBeInTheDocument();
    expect(screen.getByText(/7[23] %/)).toBeInTheDocument();
  });

  it('rendert Goal-Status-Pills', () => {
    render(withRouter(<Goals data={makeGoals()} />));
    expect(screen.getByText('Erreichbar')).toBeInTheDocument();
    expect(screen.getByText('Knapp')).toBeInTheDocument();
  });
});

describe('Section 12: Risikoprofil', () => {
  it('rendert Profil + Score', () => {
    render(withRouter(<Risikoprofil data={makeRisikoprofil()} />));
    expect(screen.getAllByText('Defensiv').length).toBeGreaterThan(0);
    expect(screen.getByText('62 / 100')).toBeInTheDocument();
    expect(screen.getByText('42.5 %')).toBeInTheDocument();
  });

  it('zeigt Override-Hinweis bei is_overridden=true', () => {
    render(withRouter(<Risikoprofil data={makeRisikoprofil()} />));
    expect(screen.getByText(/Manuelle Übersteuerung/)).toBeInTheDocument();
  });
});

describe('Section 13: BuildingBlocks', () => {
  it('rendert Blocks + Constraints', () => {
    render(withRouter(<BuildingBlocks data={makeBuildingBlocks()} />));
    expect(screen.getAllByText('Aktien').length).toBeGreaterThan(0);
    expect(screen.getByText('Maximale Risikoquote')).toBeInTheDocument();
  });
});

describe('Section 14: StatementPm', () => {
  it('rendert Principles', () => {
    render(withRouter(<StatementPm data={makeStatementPm()} />));
    expect(screen.getByText('Langfristigkeit')).toBeInTheDocument();
    expect(screen.getByText('Diversifikation')).toBeInTheDocument();
  });
});

describe('Section 15: WeiteresVorgehen', () => {
  it('rendert Blöcke, Listen, Termin', () => {
    render(
      withRouter(
        <WeiteresVorgehen
          data={makeWeiteresVorgehen()}
          mandateId="test"
          onReload={() => {}}
        />,
      ),
    );
    expect(screen.getByText(/Quartals-Review/)).toBeInTheDocument();
    expect(screen.getByText(/Vorsorge-Aufbau/)).toBeInTheDocument();
    expect(screen.getByText(/Pillar 3a-Limit/)).toBeInTheDocument();
    expect(screen.getByText('2026-08-15')).toBeInTheDocument();
  });
});

describe('Branding discipline', () => {
  it('keine Dritt-Marken in Cover-Defaults', () => {
    const { container } = render(withRouter(<Cover data={makeCover()} />));
    const text = container.textContent?.toLowerCase() ?? '';
    expect(text).not.toContain('swiss life');
    expect(text).not.toContain('3eyes');
  });
});
