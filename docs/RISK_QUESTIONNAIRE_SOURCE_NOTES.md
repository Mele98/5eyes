# Risk Questionnaire Source Notes

## Source

- `C:\Users\Emanuele\Downloads\Form_FZ_Aenderung_Anlageinstruktion_D.pdf`

## Key Observation

This PDF is not a generic wealth-management risk profile. It is a wrapper-specific
questionnaire for a Swiss free-passage / BVG-style mandate with a limited strategy universe.

## Material Differences Versus Current 5Eyes Logic

### 1. Different objective

- PDF outcome is a restricted strategy choice:
  - `BVG-Mix 15`
  - `BVG-Mix 25`
  - `BVG-Mix 35`
  - `BVG-Mix 45`
  - `BVG-Mix 75`
- Current 5Eyes logic targets a broader `Risk Score -> Risky Fraction -> House Matrix`
  framework with advisory wealth, goals, Monte Carlo and portfolio construction.

### 2. Different risk-capacity questions

The PDF uses:
- Q2 `Investitions-/Desinvestitionsrhythmus`
- Q4 `monatliches Einkommen`
- Q5 `monatliche Verpflichtungen`
- Q6 `monatlicher Sparbetrag`
- Q7 `Ersparnisse für Notfälle`
- Q8 `frei verfügbares Vermögen`

Current 5Eyes v1.6 logic uses:
- income
- obligations
- savings rate
- available wealth
- horizon

This means the PDF includes:
- an explicit rhythm/liquidity behavior input
- emergency reserves as a dedicated question
- absolute monthly savings instead of savings-rate buckets

### 3. Different thresholds

Examples from the PDF:
- income: `<4k / 4-6k / 6-8k / 8-10k / >10k`
- obligations: `<2k / 2-4k / 4-6k / 6-8k / >8k`
- free wealth: `<50k / 50-99k / 100-250k / >250k`
- horizon: `0-4 / 5-7 / 8-11 / 12+`

Current 5Eyes v1.6 thresholds are materially different and broader.

### 4. Different willingness scale

The PDF is much more compressed:
- Anlageziel has only two outcomes
- behavior question uses `0..3`
- result universe tops out at `BVG-Mix 75`

That is structurally more conservative than the current 5Eyes 1–10 model.

## Practical Conclusion

This PDF should not blindly replace the current 5Eyes questionnaire.

Instead, it indicates that the product needs at least two profile modes:

1. `General WM / 5Eyes TBI profile`
   - broader household + goals + advisory-wealth context
   - 1–10 risk score
   - optimizer and house matrix

2. `FZ / BVG wrapper profile`
   - restricted strategy shelf
   - wrapper-specific thresholds
   - likely more conservative by design

## Implementation Consequence

Before changing the core questionnaire again, compare these sources side by side:
- `5eyes_Fachlogik_v1.6.docx`
- Excel source used for the scoring truth table
- this FZ PDF
- any second questionnaire provided by the user

If they differ, the clean solution is not a merged compromise but separate profile templates by mandate / wrapper type.
