/**
 * Sprint U-P28 PR C: User-Rolle vom `/me`-Endpoint laden.
 *
 * Wird benutzt, um den „✎ Bearbeiten"-Button nur für Berater zu zeigen.
 * Kunden / readonly sehen den Report read-only, ohne Edit-UI.
 *
 * Backend liefert `role ∈ {"admin", "advisor", "readonly"}`. Wir behandeln
 * `admin` und `advisor` als „editierberechtigt", `readonly` nicht.
 */
import { useEffect, useState } from 'react';
import { ApiError } from './client';

export type UserRole = 'admin' | 'advisor' | 'readonly' | 'unknown';

declare global {
  interface Window {
    desktop?: {
      getAuthToken?: () => Promise<string | null>;
    };
  }
}

interface UserResponse {
  id: string;
  full_name: string;
  role: UserRole;
}

async function resolveAuthToken(): Promise<string | null> {
  if (typeof window === 'undefined') return null;
  try {
    const desktopToken = await window.desktop?.getAuthToken?.();
    if (desktopToken) return desktopToken;
  } catch {
    /* dev fallback */
  }
  try {
    const t = window.sessionStorage.getItem('5eyes_token');
    if (t) return t;
  } catch {
    /* hardened */
  }
  try {
    const t = window.localStorage.getItem('5eyes_token');
    if (t) return t;
  } catch {
    /* hardened */
  }
  if (import.meta.env.DEV && import.meta.env.VITE_5EYES_TOKEN) {
    return import.meta.env.VITE_5EYES_TOKEN;
  }
  return null;
}

export interface UseUserRoleResult {
  role: UserRole;
  /** True wenn der eingeloggte User Override-Felder ändern darf. */
  canEdit: boolean;
  loading: boolean;
  error: ApiError | null;
}

export function useUserRole(): UseUserRoleResult {
  const [role, setRole] = useState<UserRole>('unknown');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const token = await resolveAuthToken();
        const response = await fetch('/me', {
          method: 'GET',
          credentials: 'include',
          headers: {
            Accept: 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          signal: controller.signal,
        });
        if (!response.ok) {
          setRole('unknown');
          setError(new ApiError(response.status, `HTTP ${response.status}`));
          return;
        }
        const body = (await response.json()) as UserResponse;
        const raw = body?.role;
        if (raw === 'admin' || raw === 'advisor' || raw === 'readonly') {
          setRole(raw);
        } else {
          setRole('unknown');
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(new ApiError(0, (err as Error).message, err));
        setRole('unknown');
      } finally {
        setLoading(false);
      }
    };
    void load();
    return () => controller.abort();
  }, []);

  const canEdit = role === 'admin' || role === 'advisor';
  return { role, canEdit, loading, error };
}
