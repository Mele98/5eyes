/**
 * Vitest Global Setup.
 *
 * Registriert @testing-library/jest-dom Matcher (toBeInTheDocument, etc.)
 * für alle Tests + Default-Cleanup nach jedem Test.
 */
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
});
