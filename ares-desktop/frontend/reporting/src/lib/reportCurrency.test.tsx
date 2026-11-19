/**
 * G7 N-894-10: React-Bericht beschriftet Betraege in der Mandatswaehrung
 * (advisory_report ``mandate_currency``), nicht fest "CHF".
 */
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';

import { Positionen } from '@/pages/Positionen';
import { makePositionen } from '@/test/fixtures';
import { makeYTickFormatter } from '@/components/MonteCarloPathsChart';
import { fanAboveScaleText, fanRangeSentence } from './fanAnnotations';
import { fmtChfCompact, formatChfFromRappen, formatChfRappen } from './format';
import { ReportCurrencyContext, reportCurrencyFrom } from './reportCurrency';

const plain = (t: string | null) => String(t ?? '').replace(/−/g, '-').replace(/ /g, ' ');

describe('Mandatswaehrung im React-Bericht', () => {
  it('liest die Waehrung aus dem Bericht (Default CHF)', () => {
    expect(reportCurrencyFrom({ mandate_currency: 'eur' })).toBe('EUR');
    expect(reportCurrencyFrom({})).toBeNull(); // G7 N4: unbekannt statt CHF
  });

  it.each(['EUR', 'JPY'])('Positionen zeigen %s statt CHF', (currency) => {
    const { container } = render(
      <ReportCurrencyContext.Provider value={currency}>
        <Positionen data={makePositionen()} />
      </ReportCurrencyContext.Provider>,
    );
    const text = plain(container.textContent);
    expect(text).toContain(`${currency} `);
    expect(text).not.toMatch(/CHF \d/);
  });

  it('Formatter: Rappen-Felder Faktor 100 auch bei JPY, Waehrung als Parameter', () => {
    expect(plain(formatChfRappen(8412698413, { currency: 'JPY' }))).toBe("JPY 84'126'984");
    expect(plain(formatChfFromRappen(55789550, 'EUR'))).toBe("EUR 557'896");
    expect(plain(fmtChfCompact(2855000, 'EUR'))).toBe('EUR 2.86 Mio.');
    expect(plain(formatChfRappen(123450, { currency: 'CHF' }))).toBe("CHF 1'235");
  });

  it('Faecher-Saetze und Achse in Mandatswaehrung', () => {
    expect(fanRangeSentence(2046, 2290000, 5610000, 'EUR')).toBe(
      'In 8 von 10 Verläufen liegt Ihr Vermögen 2046 zwischen EUR 2.29 und 5.61 Mio.',
    );
    expect(fanRangeSentence(2046, 345340000, 847900000, 'JPY')).toContain('JPY 345.34 und 847.90 Mio.');
    expect(fanAboveScaleText(5000000, 'EUR')).toBe('▲ EUR 5.00 Mio. über Skala');
    const fmt = makeYTickFormatter(600_000_000, 200_000_000, 'JPY');
    expect(fmt(200_000_000)).toBe('JPY 2 Mio.');
    expect(fmt(0)).toBe('JPY 0');
  });
});
