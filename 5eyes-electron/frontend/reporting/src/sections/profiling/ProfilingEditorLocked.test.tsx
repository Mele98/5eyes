import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ProfilingEditorLocked } from './ProfilingEditorLocked';

describe('Risikoprofil-Editor gesperrt (O-1)', () => {
  it('zeigt nur den Sperrhinweis, kein Formular', () => {
    render(<ProfilingEditorLocked />);
    expect(screen.getByRole('alert')).toHaveTextContent('Risikoprofil-Editor gesperrt');
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('combobox')).toBeNull();
  });

  it('die Editor-Route mountet den Sperrhinweis statt des Editors', () => {
    const app = readFileSync(join(__dirname, '..', '..', 'App.tsx'), 'utf8');
    const route = app.split('path="/mandates/:mandateId/risikoprofil-editor"')[1].slice(0, 120);
    expect(route).toContain('<ProfilingEditorLocked');
    expect(app).not.toContain('<ProfilingPage');
  });
});
