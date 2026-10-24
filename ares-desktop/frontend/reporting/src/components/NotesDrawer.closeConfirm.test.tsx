import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { NotesDrawer } from './NotesDrawer';

/**
 * Schliessen mit ungespeicherten Aenderungen fragt im Drawer nach
 * (kein nativer Browser-Dialog, den Electron nicht unterstuetzt):
 * Abbrechen/ESC = weiter bearbeiten, Schliessen = onClose.
 */

function renderDrawer(onClose: () => void, dirty: boolean) {
  return render(
    <NotesDrawer
      open
      title="Notiz"
      onClose={onClose}
      footer={<span>footer</span>}
      currentValues={{ text: dirty ? 'neu' : 'alt' }}
      originalValues={{ text: 'alt' }}
    >
      <span>inhalt</span>
    </NotesDrawer>,
  );
}

describe('NotesDrawer Schliess-Rueckfrage', () => {
  it('schliesst ohne Rueckfrage, wenn nichts geaendert ist', () => {
    const onClose = vi.fn();
    renderDrawer(onClose, false);
    fireEvent.click(screen.getByLabelText('Drawer schliessen'));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });

  it('fragt bei Aenderungen nach; Abbrechen laesst den Drawer offen', () => {
    const onClose = vi.fn();
    renderDrawer(onClose, true);
    fireEvent.click(screen.getByLabelText('Drawer schliessen'));
    expect(onClose).not.toHaveBeenCalled();
    const dialog = screen.getByRole('alertdialog');
    expect(dialog.textContent).toContain('Aenderung am Feld "text" geht verloren. Schliessen?');
    expect(document.activeElement?.textContent).toBe('Abbrechen');
    fireEvent.click(screen.getByText('Abbrechen'));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });

  it('ESC bricht die Rueckfrage ab, Schliessen bestaetigt', () => {
    const onClose = vi.fn();
    renderDrawer(onClose, true);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.getByRole('alertdialog')).not.toBeNull();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: 'Escape' });
    fireEvent.click(screen.getByText('Schliessen'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
