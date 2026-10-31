/**
 * GENERIERT - NICHT EDITIEREN.
 *
 * Quelle: api/openapi.json (Repo-Root), erzeugt von
 * ares-desktop/frontend/reporting/scripts/gen-api-types.mjs mit
 * openapi-typescript (exakt gepinnt in package.json).
 * Neu erzeugen: `npm run gen:api-types`; Drift-Check: `npm run check:api-types`.
 */
export interface paths {
    "/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/market-data/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Market Data Status */
        get: operations["get_market_data_status_admin_market_data_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/optimizer-policies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Optimizer Policies */
        get: operations["list_optimizer_policies_admin_optimizer_policies_get"];
        put?: never;
        /** Create Optimizer Policy */
        post: operations["create_optimizer_policy_admin_optimizer_policies_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/optimizer-policies/{policy_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Optimizer Policy Detail */
        get: operations["get_optimizer_policy_detail_admin_optimizer_policies__policy_id__get"];
        /** Update Optimizer Policy */
        put: operations["update_optimizer_policy_admin_optimizer_policies__policy_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/optimizer-policies/{policy_id}/activate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Activate Optimizer Policy */
        post: operations["activate_optimizer_policy_admin_optimizer_policies__policy_id__activate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/optimizer-policies/{policy_id}/clone": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Clone Optimizer Policy */
        post: operations["clone_optimizer_policy_admin_optimizer_policies__policy_id__clone_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/optimizer-policies/{policy_id}/house-matrix": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Replace House Matrix Rows */
        put: operations["replace_house_matrix_rows_admin_optimizer_policies__policy_id__house_matrix_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/prices/mapping-gaps": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Mapping Gaps */
        get: operations["get_mapping_gaps_admin_prices_mapping_gaps_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/prices/refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Refresh Prices */
        post: operations["refresh_prices_admin_prices_refresh_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/prices/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Price Status */
        get: operations["get_price_status_admin_prices_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/annual-returns": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Annual Returns */
        get: operations["get_annual_returns_admin_system_annual_returns_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/annual-returns/backfill": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Backfill Annual Returns Endpoint
         * @description Sprint U-P11a (2026-05-22): Annual-Returns automatisch aus
         *     Marktdaten-Aggregator (yfinance + stooq) befüllen.
         *
         *     Defaults:
         *         from_year = aktuelles Jahr - 20
         *         to_year   = aktuelles Jahr - 1
         *     Body-Params (Query):
         *         overwrite: True (default) - bestehende Rows überschreiben.
         *                    False = vorhandene Rows beibehalten, nur Lücken füllen.
         *
         *     Audit-Log-Eintrag wird geschrieben (Action=BACKFILL).
         */
        post: operations["backfill_annual_returns_endpoint_admin_system_annual_returns_backfill_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/annual-returns/{year}/{asset_class}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Upsert Annual Return */
        put: operations["upsert_annual_return_admin_system_annual_returns__year___asset_class__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/asset-class-prices/backfill": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Backfill Asset Class Prices Endpoint
         * @description Sprint U-P19: Tägliche EOD-Serie je Asset-Klasse aus dem Marktdaten-
         *     Aggregator (yfinance + stooq) befüllen — Foundation für den Daily-Backtest.
         *
         *     Defaults:
         *         from_year = aktuelles Jahr - 20
         *         to_year   = aktuelles Jahr
         *     overwrite: True (default) bestehende Rows überschreiben, False = nur Lücken.
         *
         *     Audit-Log-Eintrag (Action=BACKFILL).
         */
        post: operations["backfill_asset_class_prices_endpoint_admin_system_asset_class_prices_backfill_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/asset-class-prices/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Asset Class Prices Status
         * @description Sprint U-P19: Abdeckung der täglichen EOD-Serie je Asset-Klasse
         *     (erste/letzte Bar + Punktzahl) — Datenquelle für resolution=daily.
         */
        get: operations["get_asset_class_prices_status_admin_system_asset_class_prices_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/audit-log": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Audit Log */
        get: operations["get_audit_log_admin_system_audit_log_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/backups": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Backups */
        get: operations["get_backups_admin_system_backups_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/clients/{client_id}/purge-demo": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Purge Demo Client */
        post: operations["purge_demo_client_admin_system_clients__client_id__purge_demo_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/compliance": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Compliance Status */
        get: operations["get_compliance_status_admin_system_compliance_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/db/backup": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Backup Database */
        post: operations["backup_database_admin_system_db_backup_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/db/integrity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Database Integrity */
        get: operations["database_integrity_admin_system_db_integrity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/db/optimize": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Optimize Database */
        post: operations["optimize_database_admin_system_db_optimize_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/foundation-example": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Foundation Example */
        post: operations["create_foundation_example_admin_system_foundation_example_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/foundation-example/purge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Purge Foundation Example */
        post: operations["purge_foundation_example_admin_system_foundation_example_purge_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/fx-rates/refresh-now": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Refresh Fx Rates Now
         * @description Sprint U-99 (2026-06-05): FX-only Recovery-Trigger.
         *
         *     Aktualisiert ausschliesslich asset_class_fx_history (kein Product-
         *     oder Asset-Class-Proxy-Sweep). Sinnvoll wenn Berater Wochenend-Pflege
         *     der Reference-Data macht ohne den vollen Marktdaten-Refresh
         *     anzustossen.
         *
         *     AUTH-TEN-06 (Codex-Audit 2026-08-25): Endpoint pflegt globale
         *     FX-Referenzdaten (kein tenant_id auf FXRate/AssetClassFxHistory) --
         *     firmengebundener 'admin' durfte sie in JEDER Installation aendern.
         *     Tier-1 (Default) bleibt exakt unveraendert (admin/super_admin wie
         *     zuvor); in einer echten Multi-Tenant-Installation
         *     (strict_tenant_isolation) ist admin jetzt ausgeschlossen --
         *     super_admin/portfolio_management (Platform-/IC-Rolle) noetig.
         */
        post: operations["refresh_fx_rates_now_admin_system_fx_rates_refresh_now_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/logs/recent": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Recent Logs */
        get: operations["get_recent_logs_admin_system_logs_recent_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/market-data/provider-health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Provider Health Registry */
        get: operations["get_provider_health_registry_admin_system_market_data_provider_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/market-data/provider-health/reset": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Reset Provider Health Registry */
        post: operations["reset_provider_health_registry_admin_system_market_data_provider_health_reset_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/market-data/purge-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Market Data Purge History */
        get: operations["get_market_data_purge_history_admin_system_market_data_purge_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/market-data/purge-now": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Purge Market Data Cache Now
         * @description Manual recovery trigger for the health-aware market-data cache purge.
         */
        post: operations["purge_market_data_cache_now_admin_system_market_data_purge_now_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/market-data/refresh-now": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Refresh Market Data Now
         * @description U-31: manueller Recovery-Trigger fuer den taeglichen Marktdaten-Refresh.
         */
        post: operations["refresh_market_data_now_admin_system_market_data_refresh_now_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/optimizer-mode": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Optimizer Mode */
        get: operations["get_optimizer_mode_admin_system_optimizer_mode_get"];
        /** Set Optimizer Mode */
        put: operations["set_optimizer_mode_admin_system_optimizer_mode_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/paths": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Paths */
        get: operations["get_paths_admin_system_paths_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/recommendation-runs/cleanup": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Cleanup Recommendation Runs Endpoint
         * @description Sprint U-104 (2026-06-05): RecommendationRuns aelter als
         *     retention_days (default 90) loeschen. Berater-Trigger, kein Cron
         *     (Anlagephilosophie ADR-003).
         *
         *     Body (alles optional):
         *       - retention_days: int (default 90, min 30)
         *       - dry_run: bool (default False)
         */
        post: operations["cleanup_recommendation_runs_endpoint_admin_system_recommendation_runs_cleanup_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/shadow-comparison-aggregate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Shadow Comparison Aggregate
         * @description Stage 8 Foundation: aggregierter Shadow-Vergleich über alle Mandate.
         *
         *     Quelle für die Owner-Verifikation und das Compliance-Template
         *     (docs/compliance/shadow-vergleich-template.md). Liefert
         *     GREEN/YELLOW/RED-Counts, repräsentative Beispiele und das
         *     Methodology-§4-Gesamt-Verdikt fuer den Default-Wechsel.
         */
        get: operations["get_shadow_comparison_aggregate_admin_system_shadow_comparison_aggregate_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/shadow-comparison/{mandate_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Shadow Comparison */
        get: operations["get_shadow_comparison_admin_system_shadow_comparison__mandate_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/system/support-bundle": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Support Bundle Endpoint */
        post: operations["create_support_bundle_endpoint_admin_system_support_bundle_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/2fa/disable": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Twofa Disable
         * @description Deaktiviert 2FA (erfordert einen gueltigen Code) und loescht das Secret.
         */
        post: operations["twofa_disable_auth_2fa_disable_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/2fa/enable": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Twofa Enable
         * @description Aktiviert 2FA nach Bestaetigung eines gueltigen Codes aus dem Authenticator.
         */
        post: operations["twofa_enable_auth_2fa_enable_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/2fa/recovery/regenerate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Twofa Recovery Regenerate
         * @description Erzeugt einen NEUEN Satz Recovery-Codes (alte werden ungueltig). 2FA muss aktiv sein.
         */
        post: operations["twofa_recovery_regenerate_auth_2fa_recovery_regenerate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/2fa/recovery/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Twofa Recovery Status */
        get: operations["twofa_recovery_status_auth_2fa_recovery_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/2fa/setup": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Twofa Setup
         * @description Erzeugt ein neues TOTP-Secret (noch NICHT aktiv) + otpauth-URI fuer den QR-Code.
         */
        post: operations["twofa_setup_auth_2fa_setup_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/2fa/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Twofa Status */
        get: operations["twofa_status_auth_2fa_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/admin/revoke-all-sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Revoke All Sessions Endpoint
         * @description AF-6 (2026-10-23): Massenwiderruf je Mandant. Alle Access- und
         *     Refresh-Tokens aller Benutzer des Mandanten werden ungueltig (inkl. des
         *     aufrufenden Admins -- bewusst: danach Neuanmeldung).
         *
         *     Mandantentrennung: ein admin wirkt nur auf den eigenen Mandanten (ein
         *     fremder tenant_id im Body -> 403). Ein super_admin muss tenant_id
         *     explizit angeben. Der globale Widerruf ueber alle Mandanten ist bewusst
         *     NUR als Betreiber-CLI verfuegbar (scripts/revoke_all_sessions.py).
         */
        post: operations["revoke_all_sessions_endpoint_auth_admin_revoke_all_sessions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/bootstrap-admin": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Bootstrap Admin */
        post: operations["bootstrap_admin_auth_bootstrap_admin_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/bootstrap-status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Bootstrap Status */
        get: operations["bootstrap_status_auth_bootstrap_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/change-password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Change Password
         * @description AUTH-02 (2026-07-19): Authentifizierter Passwortwechsel des eingeloggten
         *     Users. Verifiziert das aktuelle Passwort, setzt das neue (>=8 Zeichen,
         *     verschieden) und loescht must_change_password. Bleibt bei gesetztem
         *     must_change_password ERREICHBAR (Ausnahme im get_current_user-Gate), damit
         *     sich niemand aussperrt.
         */
        post: operations["change_password_auth_change_password_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/invite/accept": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Invite Accept
         * @description Public: Mitarbeiter setzt sein Passwort per Token. Token wird verbraucht.
         *     Loggt direkt ein -> beim ersten Login erzwingt das 2FA-Gate das Enrollment.
         */
        post: operations["invite_accept_auth_invite_accept_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/invite/{token}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Invite Preview
         * @description Public: validiert den Token und liefert Anzeige-Infos fuer die Set-Passwort-Maske.
         */
        get: operations["invite_preview_auth_invite__token__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Login */
        post: operations["login_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Logout
         * @description AUTH-04 (2026-07-22): Logout war bisher ein No-op — ein gestohlenes
         *     Token blieb bis zum Ablauf gueltig. Setzt token_revoked_before = jetzt;
         *     get_current_user verweigert danach jedes Token mit iat < diesem Zeitpunkt
         *     (401), unabhaengig von dessen exp.
         *
         *     Roadmap #28 (2026-08-08): revoziert zusaetzlich ALLE Refresh-Tokens
         *     dieses Users (alle Sessions/Geraete) -- konsistent zum bestehenden
         *     user-weiten (nicht nur session-weiten) token_revoked_before-Verhalten.
         */
        post: operations["logout_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Me */
        get: operations["me_auth_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/password-reset/confirm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Password Reset Confirm
         * @description Setzt das Passwort per gueltigem, nicht abgelaufenem, einmaligem Token.
         */
        post: operations["password_reset_confirm_auth_password_reset_confirm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/password-reset/request": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Password Reset Request
         * @description Startet einen Passwort-Reset. Antwortet IMMER generisch (keine Konto-
         *     Enumeration). Versendet bei konfiguriertem SMTP eine Mail; sonst kein Leak.
         */
        post: operations["password_reset_request_auth_password_reset_request_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Refresh Access Token
         * @description Roadmap #28 (Standpunkt 2026-08-07): tauscht einen gueltigen Refresh-
         *     Token gegen ein neues Access-Token + einen NEUEN (rotierten) Refresh-
         *     Token. Oeffentlicher Endpoint (kein Bearer-Access-Token noetig -- das
         *     ist der Zweck: der alte Access-Token darf bereits abgelaufen sein).
         *
         *     Rate-limited wie /login (derselbe Guard, IP-basiert), da der Endpoint
         *     ohne vorherige Authentifizierung erreichbar ist.
         */
        post: operations["refresh_access_token_auth_refresh_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/building-blocks/current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Current Building Blocks */
        get: operations["get_current_building_blocks_building_blocks_current_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/calendar/reviews.ics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get My Review Calendar Feed
         * @description Oeffentlicher (nicht per Bearer-Auth geschuetzter) Kalender-Feed-
         *     Endpoint -- Outlook kann beim automatischen periodischen Abo-Refresh
         *     keine interaktive Anmeldung durchfuehren, daher traegt die Abo-URL
         *     selbst das Geheimnis (siehe services/review_calendar_feed.py-Docstring).
         */
        get: operations["get_my_review_calendar_feed_calendar_reviews_ics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/capital-market-assumptions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Cma
         * @description Admin only — update capital market assumptions (creates new version).
         *
         *     rp-ueberarbeitung: nicht im Body gesetzte Felder werden von der vorigen
         *     Version uebernommen, damit ein partial-Update keine zuvor gepflegten
         *     sub_asset_class/correlation/etc. Werte unbeabsichtigt loescht.
         *
         *     2026-07-31 (WP3, Jurisdiktions-Verwaltung): optionaler jurisdiction/
         *     tenant_id Query-Parameter, Default "CH". Fuer jurisdiction="CH" (Default)
         *     bleibt die Vorgaenger-Suche UNVERAENDERT (kein jurisdiction-Filter noetig,
         *     weil bestehende CH-Zeilen jurisdiction IS NULL haben und das vor WP3 die
         *     einzigen is_current=1-Zeilen ueberhaupt waren) -- die Versionierungslogik
         *     selbst (Snapshot/Supersede/version+1) ist NICHT angefasst. Fuer eine
         *     andere jurisdiction wird die Vorgaenger-Suche zusaetzlich auf
         *     (jurisdiction, tenant_id) eingeschraenkt, damit ein DE-Update nicht
         *     versehentlich die CH-Zeile (oder eine andere Jurisdiktion/Tenant)
         *     superseded.
         */
        put: operations["update_cma_capital_market_assumptions_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/capital-market-assumptions/current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Current Cma
         * @description 2026-07-31 (WP3, Jurisdiktions-Verwaltung): optionaler jurisdiction/
         *     tenant_id Query-Parameter, Default "CH" -- unveraendertes Verhalten fuer
         *     alle bestehenden Aufrufer (kein Query-Parameter gesetzt = exakt die
         *     bisherige Query, siehe services/jurisdiction/resolve.py::
         *     resolve_cma_for_jurisdiction, das fuer jurisdiction in (None,'CH') die
         *     identische Query ohne jurisdiction-Filter faehrt und tenant_id ignoriert).
         */
        get: operations["get_current_cma_capital_market_assumptions_current_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/capital-market-assumptions/{id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Approve Capital Market Assumption
         * @description Setzt CapitalMarketAssumption.status="committee_approved" fuer die
         *     Zeile mit der gegebenen id.
         *
         *     Design-Entscheidung (dokumentiert wie in der Aufgabenstellung erlaubt):
         *     ein frisch freigegebener Kandidat wird SOFORT aktiv (is_current=1) --
         *     eine IC-Freigabe ohne Aktivierung waere ein toter Zustand, den niemand
         *     explizit anfordert (das WP-Doc nennt genau diesen Use-Case: "data_derived"
         *     -> "committee_approved" Freigabe). Die zuvor aktuelle Zeile DERSELBEN
         *     Jurisdiktion+Tenant-Scope wird dabei mit with_for_update() gelockt und auf
         *     is_current=0 gesetzt (analog zum Muster in routers/allocation.py::
         *     update_cma). CH-Zeilen (jurisdiction IS NULL) sind i.d.R. bereits
         *     committee_approved + is_current=1 -- ein Aufruf darauf ist dann ein
         *     No-Op-Erfolg (kein Fehler), aendert aber nichts an der bestehenden
         *     CH-Versionierung durch routers/allocation.py::update_cma.
         */
        post: operations["approve_capital_market_assumption_capital_market_assumptions__id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/client-portal/mandates/{mandate_id}/report": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Client Portal Mandate Report
         * @description Advisory-Report (volle 24 Sektionen) fuer EIGENES Mandat.
         *
         *     Sicherheits-Gates:
         *       - Mandat muss zum verknuepften Kunden gehoeren
         *       - Sonst 404 (kein Leak ob fremdes Mandat existiert)
         */
        get: operations["client_portal_mandate_report_client_portal_mandates__mandate_id__report_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/client-portal/mandates/{mandate_id}/risk-profile/sign": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Client Portal Sign Risk Profile
         * @description Modell B (Kundenportal): der eingeloggte Kunde signiert das aktuelle
         *     Risikoprofil (FIDLEG-Eignungspruefung) SEINES verknuepften Mandats.
         *
         *     Sicherheits-Gates (identisch zum Report-Endpoint):
         *       - Kunde ist 1:1 mit genau seiner Client-Akte verknuepft
         *       - Mandat muss zu dieser Akte gehoeren, sonst 404 (kein Leak, ob ein
         *         fremdes Mandat existiert) -> ein Kunde kann NUR sein eigenes Profil
         *         signieren, nie ein fremdes.
         *     Reine DOKUMENTATION der Bestaetigung — aendert die Eignungs-Konformitaet
         *     (Audit is_compliant) NICHT.
         */
        post: operations["client_portal_sign_risk_profile_client_portal_mandates__mandate_id__risk_profile_sign_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/client-portal/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Client Portal Me
         * @description Stammdaten + alle Mandate des verknuepften Kunden.
         *
         *     Berater-Reichweite: Kunde sieht nur SEINE Akte, nicht andere.
         */
        get: operations["client_portal_me_client_portal_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/client-portal/onsite-signature/{transaction_id}/confirm": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Client Confirm Onsite Signature
         * @description Kundeneigener Faktor: der eingeloggte Kunde bestaetigt Code, angezeigten
         *     Dokument-Hash und Einwilligung auf seinem eigenen Geraet.
         */
        post: operations["client_confirm_onsite_signature_client_portal_onsite_signature__transaction_id__confirm_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Clients */
        get: operations["list_clients_clients_get"];
        put?: never;
        /** Create Client */
        post: operations["create_client_clients_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Client */
        get: operations["get_client_clients__client_id__get"];
        /** Update Client */
        put: operations["update_client_clients__client_id__put"];
        post?: never;
        /** Delete Client */
        delete: operations["delete_client_clients__client_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/cashflow-projection": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Cashflow Projection */
        get: operations["cashflow_projection_clients__client_id__cashflow_projection_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/cashflow-summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Cashflow Summary */
        get: operations["cashflow_summary_clients__client_id__cashflow_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/cashflows": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Cashflows
         * @description C10.1: Standardmaessig nur aktive Cashflows. include_inactive=true
         *     fuer Admin-/Audit-Sicht.
         */
        get: operations["list_cashflows_clients__client_id__cashflows_get"];
        put?: never;
        /** Create Cashflow */
        post: operations["create_cashflow_clients__client_id__cashflows_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/cashflows-derived": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Cashflows Derived
         * @description Vermögensgetriebene, schreibgeschützte Cashflows (Hypothekarzins,
         *     Amortisation, Miet-/Zinserträge) — damit die UI sie sichtbar UND klar als
         *     'automatisch aus Vermögen' gekennzeichnet anzeigen kann.
         */
        get: operations["cashflows_derived_clients__client_id__cashflows_derived_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/cashflows/{cf_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Cashflow */
        put: operations["update_cashflow_clients__client_id__cashflows__cf_id__put"];
        post?: never;
        /** Delete Cashflow */
        delete: operations["delete_cashflow_clients__client_id__cashflows__cf_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/client-login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Client Login
         * @description Sprint U-36: Erstellt User mit role='client' + ClientLogin-Linkage.
         *
         *     Body (Pflicht):
         *       - username: str
         *       - password: str (min 8 Zeichen)
         *     Optional:
         *       - full_name: str (Default: Kunde.first_name + last_name)
         *       - email: str
         *
         *     Bedingungen:
         *       - Berater muss den Client besitzen (oder Admin sein)
         *       - Username darf nicht vergeben sein
         *       - Pro Client darf nur EINE aktive Linkage existieren
         */
        post: operations["create_client_login_clients__client_id__client_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/data-export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Data
         * @description DSG Art. 25 — Auskunftsrecht. Liefert alle personenbezogenen Daten
         *     des Kunden in maschinenlesbarem JSON-Format.
         *
         *     Authentifizierung
         *         Advisor-only. Mandantentrennung wird ueber `_get_client_or_404`
         *         erzwungen (Berater darf nur seine eigenen Kunden exportieren,
         *         ausser bei globalem Zugriff).
         *
         *     Audit
         *         Jeder Export landet als `EXPORT`-Eintrag im audit_log mit
         *         integrity_hash, sodass spaeter nachvollziehbar bleibt, welcher
         *         Berater wann welche Daten herausgegeben hat (FINMA-konform).
         */
        get: operations["export_data_clients__client_id__data_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/due-diligence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Due Diligence */
        get: operations["get_due_diligence_clients__client_id__due_diligence_get"];
        /**
         * Upsert Due Diligence
         * @description 1:1-Erfassung (GwG Art. 3-6 / FINMA-RS 2016/7 Sorgfaltspflichten) --
         *     anders als Nationalitaeten/Opt-History keine Liste, sondern genau eine
         *     Zeile pro Kunde. Upsert: legt die Zeile beim ersten Aufruf an, aktualisiert
         *     sie bei jedem weiteren -- ein PUT-nur-Create haette erzwungen, dass der
         *     Client vorher weiss, ob schon eine Erfassung existiert.
         */
        put: operations["upsert_due_diligence_clients__client_id__due_diligence_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/erase": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Erase Client
         * @description DSG Art. 32 -- Loeschungsanspruch. Anonymisiert irreversibel alle
         *     direkt identifizierenden Personendaten dieses Kunden (siehe
         *     services/client_erasure.py fuer die vollstaendige rechtliche und
         *     technische Begruendung des Umfangs). Admin-only, Pflichtbegruendung
         *     (schemas.clients.ClientErasureRequest), idempotent-sicher (409 bei
         *     Doppelaufruf). Die Aktion selbst wird -- wie jede sensible Aktion --
         *     unveraenderlich im Audit-Log protokolliert (wer hat wann wen aus
         *     welchem Grund geloescht).
         */
        post: operations["erase_client_clients__client_id__erase_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/knowledge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Knowledge */
        get: operations["list_knowledge_clients__client_id__knowledge_get"];
        put?: never;
        /** Create Knowledge */
        post: operations["create_knowledge_clients__client_id__knowledge_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/mandates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Mandates */
        get: operations["list_mandates_clients__client_id__mandates_get"];
        put?: never;
        /** Create Mandate */
        post: operations["create_mandate_clients__client_id__mandates_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/nationalities": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Nationalities */
        get: operations["list_nationalities_clients__client_id__nationalities_get"];
        put?: never;
        /** Add Nationality */
        post: operations["add_nationality_clients__client_id__nationalities_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/opt-history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Opt History */
        get: operations["get_opt_history_clients__client_id__opt_history_get"];
        put?: never;
        /**
         * Add Opt History
         * @description FIDLEG-STATE-001 (2026-08-27-Audit): dies ist der einzige Pfad, ueber
         *     den sich client_classification aendern darf (siehe ClientUpdate, die das
         *     Feld bewusst nicht mehr besitzt). from_classification muss serverseitig
         *     mit dem tatsaechlich gespeicherten Ausgangszustand uebereinstimmen --
         *     vorher akzeptierte der Router jeden behaupteten Ausgangszustand
         *     (reproduziert: claimed_from='Institutioneller Kunde' bei einem
         *     tatsaechlichen Privatkunden) und stampfte den Client trotzdem auf
         *     to_classification um. Ein stale/falscher from-Wert (z.B. durch eine
         *     zwischenzeitliche parallele Aenderung) wird jetzt mit 409 abgelehnt,
         *     statt eine fachlich unmoegliche History-Zeile zu erzeugen.
         *
         *     DUAL-STACK-01-Nachtrag (2026-10-07): derselbe Stale-Schutz gilt jetzt
         *     auch fuer is_professional_opt_out/is_qualified_investor, die ansonsten
         *     (seit ClientUpdate sie ausschliesst) gar keinen Aenderungspfad mehr
         *     haetten. Beide Flag-Uebergaenge sind optional und unabhaengig von der
         *     Klassifikationsaenderung -- eine reine Flag-Aenderung ohne
         *     Klassifikationswechsel ist gueltig (from_classification ==
         *     to_classification), ebenso eine reine Reklassifikation ohne
         *     Flag-Aenderung (from_*\/to_* fuer die Flags bleiben None).
         */
        post: operations["add_opt_history_clients__client_id__opt_history_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/tax-residencies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Tax Residencies */
        get: operations["list_tax_residencies_clients__client_id__tax_residencies_get"];
        put?: never;
        /** Add Tax Residency */
        post: operations["add_tax_residency_clients__client_id__tax_residencies_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/wealth-inflows": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Wealth Inflows */
        get: operations["list_wealth_inflows_clients__client_id__wealth_inflows_get"];
        put?: never;
        /** Create Wealth Inflow */
        post: operations["create_wealth_inflow_clients__client_id__wealth_inflows_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/wealth-positions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Wealth Positions
         * @description C10.1: Standardmaessig nur aktive Positionen. include_inactive=true
         *     fuer Admin-/Audit-Sicht.
         */
        get: operations["list_wealth_positions_clients__client_id__wealth_positions_get"];
        put?: never;
        /** Create Wealth Position */
        post: operations["create_wealth_position_clients__client_id__wealth_positions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/wealth-positions/{wp_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Wealth Position */
        put: operations["update_wealth_position_clients__client_id__wealth_positions__wp_id__put"];
        post?: never;
        /** Delete Wealth Position */
        delete: operations["delete_wealth_position_clients__client_id__wealth_positions__wp_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/clients/{client_id}/wealth-summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Wealth Summary */
        get: operations["wealth_summary_clients__client_id__wealth_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/cma-policies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Policies */
        get: operations["list_policies_cma_policies_get"];
        put?: never;
        /** Create Policy */
        post: operations["create_policy_cma_policies_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/cma-policies/model-status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Model Status */
        get: operations["get_model_status_cma_policies_model_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/cma-policies/{policy_row_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Policy */
        get: operations["get_policy_cma_policies__policy_row_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/cma-policies/{policy_row_id}/activate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Activate Policy */
        post: operations["activate_policy_cma_policies__policy_row_id__activate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/cma-policies/{policy_row_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Approve Policy */
        post: operations["approve_policy_cma_policies__policy_row_id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/cma-policies/{policy_row_id}/components": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Replace Components */
        put: operations["replace_components_cma_policies__policy_row_id__components_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/cma-policies/{policy_row_id}/retire": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Retire Policy */
        post: operations["retire_policy_cma_policies__policy_row_id__retire_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/cma-policies/{policy_row_id}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Revoke Policy */
        post: operations["revoke_policy_cma_policies__policy_row_id__revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/cma-policies/{policy_row_id}/validate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Validate Policy */
        post: operations["validate_policy_cma_policies__policy_row_id__validate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/dashboard/active-triggers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Active Triggers */
        get: operations["active_triggers_dashboard_active_triggers_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/dashboard/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Dashboard Summary
         * @description Aggregated dashboard: all clients with wealth, active alerts count.
         *
         *     SECURITY (Mandanten-Trennung): KEIN ungescopter Admin-Zweig mehr. Auch
         *     globale Admins laufen ueber get_accessible_client_ids/-mandate_ids — diese
         *     ueberspringen den advisor_id-Filter, wenden aber IMMER den Tenant-Filter an.
         *     Ein Firma-A-Admin sieht so alle Clients SEINES Tenants, aber nie fremde.
         *     (Legacy-Admin ohne tenant_id: Tier-1-Single-Tenant, sieht weiter alles.)
         */
        get: operations["dashboard_summary_dashboard_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/fx-rates": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Upsert Fx Rates
         * @description Upsert mehrere FX-Rates. Alte is_current=1 Werte werden auf
         *     is_current=0 + valid_until=now gesetzt (Versionierung).
         */
        put: operations["upsert_fx_rates_fx_rates_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/fx-rates/current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Current Fx Rates
         * @description Listet alle aktuellen FX-Rates: DB-gepflegte Kurse (is_current=1) je
         *     Waehrung, ergaenzt um Default-Kurse fuer jede Waehrung, die (noch) keine
         *     DB-Zeile hat.
         *
         *     FX-CURRENT-LIST-DEFAULT-DROP-001 (Kontrollrunde 2026-09-24): vorher war
         *     dies ein reines Entweder-Oder -- sobald AUCH NUR EINE Waehrung eine
         *     DB-Zeile hatte, verschwanden alle uebrigen (noch nie manuell gepflegten)
         *     Default-Waehrungen komplett aus der Liste, obwohl fuer sie weiterhin ein
         *     gueltiger Default-Kurs existiert (und in der tatsaechlichen Konvertierung,
         *     FXRateSource.from_db_for_model, bereits korrekt als Fallback verwendet
         *     wird -- nur diese Listen-Ansicht war inkonsistent). Live reproduziert:
         *     nach dem Setzen NUR einer einzelnen Waehrung zeigte das Beratertool
         *     fuer alle anderen 12 Default-Waehrungen keinen Kurs mehr an.
         */
        get: operations["list_current_fx_rates_fx_rates_current_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health Root
         * @description Backwards-compat Root-Endpoint. Antwortet immer 200 wenn der
         *     Prozess Requests entgegennimmt — kein DB-Hit.
         */
        get: operations["health_root_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/db": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health Db */
        get: operations["health_db_health_db_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/live": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health Live
         * @description U-63 (2026-06-01): Liveness-Probe.
         *
         *     Entscheidet ob der Prozess RESTARTET werden muss. Soll NICHT
         *     von DB/External-Services abhaengen — sonst wuerden DB-Outages
         *     einen Process-Restart triggern und die Recovery noch verzoegern.
         */
        get: operations["health_live_health_live_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health Ready
         * @description U-63 (2026-06-01): Readiness-Probe.
         *
         *     Entscheidet ob TRAFFIC zum Prozess gerouted wird. Prueft DB-
         *     Verbindung — bei DB-Outage 503 (Traffic stoppen), Prozess bleibt
         *     aber laufen (Liveness intakt). price_runtime_status ist
         *     informational (non-blocking).
         */
        get: operations["health_ready_health_ready_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/house-matrix/{score}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get House Matrix For Score
         * @description Get house matrix band for a given risk score (1–10).
         */
        get: operations["get_house_matrix_for_score_house_matrix__score__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/jurisdictions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Jurisdictions */
        get: operations["list_jurisdictions_jurisdictions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/jurisdictions/{code}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Jurisdiction */
        get: operations["get_jurisdiction_jurisdictions__code__get"];
        /** Update Jurisdiction */
        put: operations["update_jurisdiction_jurisdictions__code__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/jurisdictions/{code}/cma/compute-candidate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Compute Cma Candidate */
        post: operations["compute_cma_candidate_jurisdictions__code__cma_compute_candidate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/jurisdictions/{code}/home-bias-defaults": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Home Bias Defaults */
        get: operations["list_home_bias_defaults_jurisdictions__code__home_bias_defaults_get"];
        put?: never;
        /** Create Home Bias Default */
        post: operations["create_home_bias_default_jurisdictions__code__home_bias_defaults_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/jurisdictions/{code}/home-bias-defaults/{row_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Home Bias Default */
        put: operations["update_home_bias_default_jurisdictions__code__home_bias_defaults__row_id__put"];
        post?: never;
        /** Delete Home Bias Default */
        delete: operations["delete_home_bias_default_jurisdictions__code__home_bias_defaults__row_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Mandate */
        get: operations["get_mandate_mandates__mandate_id__get"];
        /** Update Mandate */
        put: operations["update_mandate_mandates__mandate_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/advisory-log": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Advisory Log
         * @description Sprint U-FINMA-2.1: Listet die *aktuellen* (non-superseded) Einträge.
         *
         *     Mit `?include_history=true` werden alle Versionen geliefert (für
         *     Compliance-Audit). Default: nur aktuelle Köpfe der Versions-Ketten.
         */
        get: operations["list_advisory_log_mandates__mandate_id__advisory_log_get"];
        put?: never;
        /**
         * Create Advisory Log Entry
         * @description Sprint U-FINMA-2.1: FINMA-konforme Eintragserstellung mit Hash,
         *     Aufbewahrungs-Datum und vollem Audit-Log.
         */
        post: operations["create_advisory_log_entry_mandates__mandate_id__advisory_log_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/advisory-log/from-report-generation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Advisory Log From Report Generation
         * @description Sprint U-FINMA-2.2: Erzeugt ein Beratungsprotokoll mit pre-filled
         *     Defaults — Topics aus Mandat-Kontext, Risk-Warnings aus aktiven
         *     Suitability-Mismatches. Berater editiert anschliessend via PUT.
         *
         *     Endpoint ist explizit — Auto-Log passiert NICHT beim normalen
         *     Report-Abruf (sonst Audit-Spam).
         */
        post: operations["create_advisory_log_from_report_generation_mandates__mandate_id__advisory_log_from_report_generation_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/advisory-log/{log_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Advisory Log Entry
         * @description Sprint U-FINMA-2.1: Einzelner Eintrag mit Read-Audit-Tracking.
         */
        get: operations["get_advisory_log_entry_mandates__mandate_id__advisory_log__log_id__get"];
        /**
         * Update Advisory Log Entry
         * @description Sprint U-FINMA-2.1: Update erzeugt eine *neue Version*, der alte
         *     Eintrag wird markiert als superseded (FINMA-Pflicht: keine destructive
         *     Updates am Beratungsprotokoll).
         */
        put: operations["update_advisory_log_entry_mandates__mandate_id__advisory_log__log_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/advisory-report": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Advisory Report
         * @description Sprint U-P21: Voller 15-Seiten Advisory-Report als JSON.
         *
         *     Konsumiert von der React-Sub-App (ares-desktop/frontend/reporting/,
         *     folgt in U-P22) und vom Server-PDF (U-P26). Berater-Auth via
         *     get_current_user, gleiche Pattern wie Depot-Check-Endpoint.
         */
        get: operations["get_advisory_report_mandates__mandate_id__advisory_report_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/backtest/ab": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Backtest Ab
         * @description Sprint U-P15: A/B-HouseMatrix-Backtest.
         *
         *     Vergleicht zwei OptimizerPolicy-Versionen auf dem Risikoprofil des
         *     Mandates und liefert Bucket-Gewichtung, Risk-Metriken (Return/Vol/
         *     Sharpe/TER) und Stress-Replays pro Policy + Diff-Strukturen.
         *
         *     Read-only: kein DB-Mutation, kein Audit-Log nötig.
         *
         *     Fehler:
         *         400: policy_a == policy_b
         *         404: eine der Policies nicht gefunden
         *         409: Assessment fehlt oder keine aktive CMA
         */
        get: operations["get_backtest_ab_mandates__mandate_id__backtest_ab_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/backtest/strategy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Strategy Backtest
         * @description Sprint U-P17: SOLL-Strategie-Backtest auf historischen Jahresrenditen.
         *
         *     Wendet die aktuelle TargetAllocation (Bucket-Gewichte) auf die Jahres-
         *     renditen aus admin/system/annual-returns an. Beratungsvermögen als
         *     Initial-Kapital (Snapshot aus advisory_wealth_at_generation_rappen,
         *     fallback aktuelle WealthPositions-Summe).
         *
         *     Liefert für SOLL beide Pfade (mit / ohne jährlichem Rebalancing).
         *     Optional gleiche Methode auf einen frei konfigurierbaren Benchmark-Mix.
         *
         *     Query-Params:
         *         start_year, end_year — optional, default = max verfügbarer Bereich
         *         benchmark_*_bps — optional, alle 5 zusammen ergeben den Benchmark.
         *             Wenn alle None, kein Benchmark. Summe wird auf 10000 normalisiert.
         *         benchmark_sub_assets — optional Sub-Asset-Benchmark, Format
         *             'Key1:bps,Key2:bps' (Phase 3 Sub-Asset-Sprint 2026-06-09).
         *
         *     Read-only, kein Audit-Log.
         */
        get: operations["get_strategy_backtest_mandates__mandate_id__backtest_strategy_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/backtest/stress-replays": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Backtest Stress Replays
         * @description Sprint U-P13: Historische Stress-Szenarien (Dotcom 2000-2002, GFC
         *     2008, Covid 2020, Bonds-Crash 2022, Stagflation 1973-74) angewandt
         *     auf die SOLL-Gewichtung der gueltigen Target-Allocation des Mandates.
         *
         *     Stress-Replay der empfohlenen SOLL-Allokation (nicht des aktuellen
         *     Depots): IST-Bestaende fliessen nicht ein (``scope`` =
         *     ``approved_target_allocation``, ``scope_label`` fuer die Anzeige).
         *
         *     Foundation-Variante mit hartcodierten Returns. Voll-Pipeline mit
         *     historischer Time-Series kommt in Sprint U-P11.
         */
        get: operations["get_backtest_stress_replays_mandates__mandate_id__backtest_stress_replays_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/conflict-disclosures": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Conflicts */
        get: operations["list_conflicts_mandates__mandate_id__conflict_disclosures_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/conflicts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Conflicts */
        get: operations["list_conflicts_mandates__mandate_id__conflicts_get"];
        put?: never;
        /** Create Conflict */
        post: operations["create_conflict_mandates__mandate_id__conflicts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/conflicts/{conflict_id}/acknowledge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Acknowledge Conflict
         * @description Die Kenntnisnahme des Kunden protokollieren.
         */
        post: operations["acknowledge_conflict_mandates__mandate_id__conflicts__conflict_id__acknowledge_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/conflicts/{conflict_id}/attach-document": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Attach Conflict Document
         * @description Das Offenlegungsdokument nachtraeglich ablegen.
         *
         *     Noetig, weil `/disclose` einmalig ist: wer die Offenlegung protokolliert,
         *     bevor das Dokument abgelegt war, bliebe sonst dauerhaft bei
         *     `evidence_incomplete` -- und mit einem Finalisierungs-Gate darauf waere
         *     das Mandat unaufloesbar blockiert. Genau die Falle, die dieser ganze
         *     Endpunkt-Satz vermeiden soll, nur eine Ebene tiefer.
         *
         *     Ein BEREITS abgelegtes Dokument wird NICHT ersetzt: die Referenz ist Teil
         *     des Nachweises, und sie stillschweigend umzuhaengen wuerde ihn
         *     entwerten. Ein Austausch braucht eine eigene, bewusste Entscheidung --
         *     die es heute nicht gibt und die hier nicht nebenbei erfunden wird.
         */
        post: operations["attach_conflict_document_mandates__mandate_id__conflicts__conflict_id__attach_document_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/conflicts/{conflict_id}/disclose": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Disclose Conflict
         * @description Die Offenlegung an den Kunden protokollieren (FIDLEG Art. 25/26).
         */
        post: operations["disclose_conflict_mandates__mandate_id__conflicts__conflict_id__disclose_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/conflicts/{conflict_id}/mitigate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Mitigate Conflict
         * @description Die getroffene organisatorische Massnahme protokollieren.
         *
         *     Anders als Offenlegung und Kenntnisnahme ist das KEIN einmaliger
         *     Zustandsuebergang: eine Massnahme kann praezisiert oder ersetzt werden.
         *     Der alte Wert bleibt deshalb im Audit-Log, nicht in der Zeile.
         */
        post: operations["mitigate_conflict_mandates__mandate_id__conflicts__conflict_id__mitigate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/cost-disclosure/ex-ante": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Ex Ante Cost Disclosure
         * @description FIDLEG Art. 8/9 Ex-ante Kostenausweis fuer das Mandat.
         *
         *     Konsumiert die aktuelle RecommendationRun (oder die aktive OptimizerPolicy
         *     als Fallback). Bei fehlender Empfehlung wird `data_pending=True`
         *     zurueckgegeben — die Schema-Form bleibt gleich, der Client braucht
         *     keine 404-Sonderbehandlung.
         */
        get: operations["get_ex_ante_cost_disclosure_mandates__mandate_id__cost_disclosure_ex_ante_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/depot-check": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Depot Check
         * @description Vollstaendiger Depot-Check fuer das Mandat.
         *
         *     Defensive: kein Crash bei fehlenden Daten. Returnt was berechnen geht +
         *     Liste der Warnings/Empfehlungen.
         *
         *     DEPOT-E2E-SNAPSHOT-001: mit ``analysis_snapshot_id`` der gespeicherte,
         *     an einen Depot-Snapshot gebundene Depot-Check (derselbe, den das PDF
         *     liest) statt einer Live-Berechnung; Manipulation -> 409.
         */
        get: operations["get_depot_check_mandates__mandate_id__depot_check_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/depot-snapshots": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Depot Snapshot */
        post: operations["create_depot_snapshot_mandates__mandate_id__depot_snapshots_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/depot-snapshots/{snapshot_id}/depot-check": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Depot Check Analysis
         * @description DEPOT-E2E-SNAPSHOT-001: Depot-Check auf dem Bestand eines gespeicherten
         *     Depot-Snapshots berechnen und gebunden speichern (idempotent). JSON
         *     (``GET /depot-check?analysis_snapshot_id=``) und PDF lesen ihn.
         */
        post: operations["create_depot_check_analysis_mandates__mandate_id__depot_snapshots__snapshot_id__depot_check_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/depot-snapshots/{snapshot_id}/stress-replays": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Depot Snapshot Stress Replays
         * @description Stress-Replay des IST-Depots aus einem gespeicherten Depot-Snapshot
         *     (``scope`` = ``current_holdings_snapshot``). Positionen ohne eindeutige
         *     Anlageklasse -> keine Szenariozahlen (fail-closed, ausgewiesen).
         */
        get: operations["get_depot_snapshot_stress_replays_mandates__mandate_id__depot_snapshots__snapshot_id__stress_replays_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/documents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Documents */
        get: operations["list_documents_mandates__mandate_id__documents_get"];
        put?: never;
        /** Create Document */
        post: operations["create_document_mandates__mandate_id__documents_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/documents/{doc_id}/onsite-signature": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Open Onsite Signature */
        post: operations["open_onsite_signature_mandates__mandate_id__documents__doc_id__onsite_signature_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/documents/{doc_id}/pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Document Pdf
         * @description Liefert die archivierten PDF-Bytes genau dieser Version zurueck.
         *
         *     Dokumenten-Archiv (2026-08-20): getrennt von /reports/*.pdf
         *     (routers/pdf_reports.py), die IMMER frisch aus den aktuellen Daten
         *     rendern -- dieser Endpoint liefert stattdessen die zum
         *     Generierungszeitpunkt tatsaechlich abgelegten Bytes einer aelteren
         *     Version unveraendert zurueck (FINMA-Nachweis: "was wurde dem Kunden
         *     damals gezeigt").
         */
        get: operations["get_document_pdf_mandates__mandate_id__documents__doc_id__pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/documents/{doc_id}/sign": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Sign Document */
        post: operations["sign_document_mandates__mandate_id__documents__doc_id__sign_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/financial-coverage-attestation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Financial Coverage Attestation */
        get: operations["get_financial_coverage_attestation_mandates__mandate_id__financial_coverage_attestation_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/financial-coverage-attestations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Financial Coverage Attestation */
        post: operations["create_financial_coverage_attestation_mandates__mandate_id__financial_coverage_attestations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/goals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Goals */
        get: operations["list_goals_mandates__mandate_id__goals_get"];
        put?: never;
        /** Create Goal */
        post: operations["create_goal_mandates__mandate_id__goals_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/goals/calculate-max-pension-spending": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Calculate Max Pension Spending */
        post: operations["calculate_max_pension_spending_mandates__mandate_id__goals_calculate_max_pension_spending_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/goals/order": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Reorder Goals
         * @description Schreibt die vollstaendige Ziel-Reihenfolge atomar (ADR-10c).
         *
         *     Muss VOR ``/goals/{goal_id}`` registriert sein, sonst faengt die
         *     Einzelziel-Route den Pfad ``order`` ab.
         */
        put: operations["reorder_goals_mandates__mandate_id__goals_order_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/goals/{goal_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Goal */
        put: operations["update_goal_mandates__mandate_id__goals__goal_id__put"];
        post?: never;
        /** Delete Goal */
        delete: operations["delete_goal_mandates__mandate_id__goals__goal_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/goals/{goal_id}/revision-decisions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Goal Revision Decisions
         * @description Append-only Historie der Herabstufungs-Entscheidungen eines Ziels,
         *     juengste zuerst, je mit Gueltigkeit gegen den AKTUELLEN Zielstand.
         */
        get: operations["list_goal_revision_decisions_mandates__mandate_id__goals__goal_id__revision_decisions_get"];
        put?: never;
        /**
         * Create Goal Revision Decision
         * @description Ziel als nachrangiges Wunschziel einstufen (GoalRevisionDecisionV1).
         *
         *     Die Engine schlaegt das nur vor (lokal keine zulaessige Allokation mit
         *     ausreichender Sicherheit gefunden); wirksam wird es erst mit dieser
         *     expliziten, begruendeten Berater-Entscheidung. Fail-closed vor jeder
         *     Mutation: Begruendungsqualitaet (422), Engine-Evidenz der aktuellen
         *     Strategie zum aktuellen Zielstand mit Vorschlag (409), keine bereits
         *     wirksame Decision (409).
         */
        post: operations["create_goal_revision_decision_mandates__mandate_id__goals__goal_id__revision_decisions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/onsite-signature/{transaction_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Onsite Signature */
        get: operations["get_onsite_signature_mandates__mandate_id__onsite_signature__transaction_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/onsite-signature/{transaction_id}/abort": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Onsite Abort */
        post: operations["onsite_abort_mandates__mandate_id__onsite_signature__transaction_id__abort_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/onsite-signature/{transaction_id}/challenge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Onsite Issue Challenge
         * @description Sendet den Einmalcode an den Kundenkanal. Die Antwort enthaelt ihn nie.
         */
        post: operations["onsite_issue_challenge_mandates__mandate_id__onsite_signature__transaction_id__challenge_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/onsite-signature/{transaction_id}/deliver": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Onsite Deliver Copy */
        post: operations["onsite_deliver_copy_mandates__mandate_id__onsite_signature__transaction_id__deliver_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/onsite-signature/{transaction_id}/finalize": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Onsite Finalize */
        post: operations["onsite_finalize_mandates__mandate_id__onsite_signature__transaction_id__finalize_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/onsite-signature/{transaction_id}/identity-check": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Onsite Identity Check */
        post: operations["onsite_identity_check_mandates__mandate_id__onsite_signature__transaction_id__identity_check_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/onsite-signature/{transaction_id}/witness": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Onsite Witness */
        post: operations["onsite_witness_mandates__mandate_id__onsite_signature__transaction_id__witness_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/optimizer-runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Optimizer Runs
         * @description V3 Sprint 2: Liste der persistierten Solver-Laufe fuer ein Mandat.
         *
         *     Sortiert absteigend nach run_at (neueste zuerst). Default-Pagination
         *     50/Anfrage. Wenn der Solver in keinem Modus lief, ist die Liste leer.
         */
        get: operations["list_optimizer_runs_mandates__mandate_id__optimizer_runs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/planning-assumptions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Planning Assumptions Ui */
        get: operations["get_planning_assumptions_ui_mandates__mandate_id__planning_assumptions_get"];
        /** Upsert Planning Assumptions */
        put: operations["upsert_planning_assumptions_mandates__mandate_id__planning_assumptions_put"];
        /** Create Planning Assumptions */
        post: operations["create_planning_assumptions_mandates__mandate_id__planning_assumptions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/planning-assumptions/current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Planning Assumptions */
        get: operations["get_planning_assumptions_mandates__mandate_id__planning_assumptions_current_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/portfolio-data/assessment": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Portfolio Data Assessment
         * @description PORTFOLIO-DATA-001: komponentenweise Depot-Frische, Abgleich-Status und
         *     Gate je Aktion (Entwurf, Finalisierung, PDF, Signatur, Handoff). Mit einer
         *     nicht freigegebenen Policy (heute PROPOSED) nur Anzeige: ``enforced``
         *     False, ``would_block`` zeigt, was eine aktive Policy sperren wuerde.
         */
        get: operations["get_portfolio_data_assessment_mandates__mandate_id__portfolio_data_assessment_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/portfolio-handoffs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Portfolio Handoffs */
        get: operations["list_portfolio_handoffs_mandates__mandate_id__portfolio_handoffs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/portfolio-handoffs/{handoff_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Cancel Portfolio Handoff */
        post: operations["cancel_portfolio_handoff_mandates__mandate_id__portfolio_handoffs__handoff_id__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/portfolio-handoffs/{handoff_id}/mark-executed": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Mark Portfolio Handoff Executed */
        post: operations["mark_portfolio_handoff_executed_mandates__mandate_id__portfolio_handoffs__handoff_id__mark_executed_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/portfolio/refresh-prices": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Refresh Portfolio Live Prices
         * @description Sprint U-P11b (2026-05-22): Live-Preise für die Produkte dieses
         *     Mandates via Marktdaten-Aggregator (yfinance/stooq-Fallback) holen
         *     und in price_history persistieren.
         *
         *     Engerer Scope als /admin/prices/refresh — nur Produkte aus dem
         *     aktuellsten RecommendationRun des Mandates werden aktualisiert.
         *
         *     Returns Summary mit processed/inserted/updated/unchanged/failed +
         *     Failure-Liste pro Produkt.
         */
        post: operations["refresh_portfolio_live_prices_mandates__mandate_id__portfolio_refresh_prices_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/protocol-bausteine": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Mandate Selections */
        get: operations["list_mandate_selections_mandates__mandate_id__protocol_bausteine_get"];
        /**
         * Replace Mandate Selections
         * @description Replace-Semantik: die uebergebene Liste IST die neue Selektion.
         *     Vorhandene Eintraege fuer das Mandat werden entfernt, die neuen gesetzt.
         */
        put: operations["replace_mandate_selections_mandates__mandate_id__protocol_bausteine_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/recommendations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Recommendations */
        get: operations["list_recommendations_mandates__mandate_id__recommendations_get"];
        put?: never;
        /** Create Recommendation Run */
        post: operations["create_recommendation_run_mandates__mandate_id__recommendations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/recommendations/current/payload": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Current Recommendation Payload */
        get: operations["get_current_recommendation_payload_mandates__mandate_id__recommendations_current_payload_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/recommendations/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Generate Recommendation Run Endpoint */
        post: operations["generate_recommendation_run_endpoint_mandates__mandate_id__recommendations_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/recommendations/{run_id}/eligibility-overrides": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Eligibility Overrides */
        get: operations["list_eligibility_overrides_mandates__mandate_id__recommendations__run_id__eligibility_overrides_get"];
        put?: never;
        /** Request Eligibility Override */
        post: operations["request_eligibility_override_mandates__mandate_id__recommendations__run_id__eligibility_overrides_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/recommendations/{run_id}/eligibility-overrides/{override_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Approve Eligibility Override */
        post: operations["approve_eligibility_override_mandates__mandate_id__recommendations__run_id__eligibility_overrides__override_id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/recommendations/{run_id}/finalize": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Finalize Recommendation */
        put: operations["finalize_recommendation_mandates__mandate_id__recommendations__run_id__finalize_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/recommendations/{run_id}/holdings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Holdings */
        get: operations["list_holdings_mandates__mandate_id__recommendations__run_id__holdings_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/recommendations/{run_id}/payload": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Recommendation Payload By Id */
        get: operations["get_recommendation_payload_by_id_mandates__mandate_id__recommendations__run_id__payload_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/recommendations/{run_id}/portfolio-handoff-preview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Preview Portfolio Handoff
         * @description HANDOFF-PREVIEW-PARITY-001: Handelsliste read-only aus derselben
         *     Funktion wie die Weiterleitung (kein Persistieren, kein Audit-Eintrag).
         *     Ablehnungen kommen als 409 mit ``reason_code``, damit die Anzeige den
         *     Grund (z.B. fehlende Neugeld-Bestaetigung) ausweisen kann.
         */
        get: operations["preview_portfolio_handoff_mandates__mandate_id__recommendations__run_id__portfolio_handoff_preview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/recommendations/{run_id}/portfolio-handoffs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Portfolio Handoff */
        post: operations["create_portfolio_handoff_mandates__mandate_id__recommendations__run_id__portfolio_handoffs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/recommendations/{run_id}/positions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Positions */
        get: operations["list_positions_mandates__mandate_id__recommendations__run_id__positions_get"];
        put?: never;
        /** Add Position */
        post: operations["add_position_mandates__mandate_id__recommendations__run_id__positions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/recommendations/{run_id}/positions/{position_id}/holding": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Upsert Position Holding */
        put: operations["upsert_position_holding_mandates__mandate_id__recommendations__run_id__positions__position_id__holding_put"];
        post?: never;
        /** Delete Position Holding */
        delete: operations["delete_position_holding_mandates__mandate_id__recommendations__run_id__positions__position_id__holding_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/report-notes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Report Notes
         * @description U-P28: Berater-Overrides fuer den Advisory-Report.
         *
         *     Leere Zeile (noch nichts gepflegt) → leere Response mit nur `mandate_id`
         *     gesetzt. Die Sub-App und das PDF konsumieren denselben Aggregator und
         *     fallen pro Feld auf den Auto-Default-Text zurueck.
         */
        get: operations["get_report_notes_mandates__mandate_id__report_notes_get"];
        /**
         * Put Report Notes
         * @description U-P28: Upsert der Berater-Overrides.
         *
         *     Auth: nur Berater (require_advisor) — Kunden sehen den Report
         *     read-only. Audit-Anchor (`last_edited_by` + `last_edited_at`) wird bei
         *     jedem PUT aktualisiert; das `created_at` bleibt beim ersten Insert.
         */
        put: operations["put_report_notes_mandates__mandate_id__report_notes_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/reports/advisory-report.pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Advisory Report Pdf
         * @description Sprint U-P26 PR A: institutioneller Advisory-Report als A4-PDF.
         *
         *     Konsumiert denselben Aggregator wie die React-Sub-App
         *     (`services.advisory_report.compute_advisory_report`), spiegelt also
         *     1:1 dieselben Daten. PR A liefert Cover + Disclaimer + Inhalts-
         *     verzeichnis + Page-Chrome; Sektionen 4-15 folgen in U-P26 PR B-F.
         */
        get: operations["get_advisory_report_pdf_mandates__mandate_id__reports_advisory_report_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/reports/anlagestrategie.pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Anlagestrategie Pdf
         * @description Generiert Anlagestrategie-PDF fuer das Mandat.
         */
        get: operations["get_anlagestrategie_pdf_mandates__mandate_id__reports_anlagestrategie_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/reports/assetallocation.pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Assetallocation Pdf
         * @description Reines Asset-Allocation-PDF fuer die Asset-Allocation-Maske.
         */
        get: operations["get_assetallocation_pdf_mandates__mandate_id__reports_assetallocation_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/reports/backtest.pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Backtest Pdf
         * @description Strategie-Backtest-PDF: Wealth-Index + Drawdown + Kennzahlen.
         *
         *     Optional Benchmark-Mix (Summe wird auf 10000 bps normalisiert).
         *     Bewusst nur Rebalanced-Pfad im PDF (Buy-and-Hold via Modal verfügbar).
         *     resolution=daily nutzt die tägliche EOD-Serie (mit Annual-Fallback).
         *
         *     Bug-#8b: optionale strategy_fee_bps/benchmark_fee_bps zeigen einen
         *     Brutto-vs-Netto-Vergleich im PDF.
         */
        get: operations["get_backtest_pdf_mandates__mandate_id__reports_backtest_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/reports/contract-signoff.pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Contract Signoff Pdf
         * @description Final customer sign-off for the documented advisory decision.
         */
        get: operations["get_contract_signoff_pdf_mandates__mandate_id__reports_contract_signoff_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/reports/cost-disclosure.pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Cost Disclosure Pdf
         * @description FIDLEG Art. 8/9 Ex-ante Kostenausweis als Standalone-PDF.
         *
         *     Verwendet denselben Service wie der JSON-Endpoint
         *     /mandates/{id}/cost-disclosure/ex-ante (PR 1, Single-Source-of-Truth).
         *     Der DepotCheck-PDF enthaelt den Kostenausweis als Subsection — dieses
         *     PDF ist das eigenstaendige Dokument, das dem Kunden vor Auftrags-
         *     ausfuehrung ausgehaendigt werden kann.
         *
         *     CERT-COST-PUBLICATION-001 (2026-10-09):
         *     - COST-PUBLICATION-GATE-001: ein pending Kostenausweis (keine Empfehlung
         *       vorhanden) war bisher trotzdem als normales HTTP-200-Kunden-PDF
         *       exportierbar, ununterscheidbar von einem zertifizierten Dokument.
         *       Dieser Alias liefert jetzt 409 mit stabilem Reason-Code, solange keine
         *       belastbare Kostenbasis existiert (spec Section 5.2).
         *     - COST-ARTIFACT-EVIDENCE-001: render-once/archive-once ueber das bereits
         *       bestehende services.document_archive (gleiches Muster wie
         *       Anlagestrategie/Risikoprofil/Portfolio/Protokoll weiter oben in dieser
         *       Datei) -- identische Fachdaten liefern dieselben archivierten Bytes
         *       statt bei jedem GET frisch zu rendern; Response-Header tragen die
         *       Dokument-/Snapshot-/Byte-Hash-Identitaet.
         */
        get: operations["get_cost_disclosure_pdf_mandates__mandate_id__reports_cost_disclosure_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/reports/depotcheck.pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Depotcheck Pdf
         * @description Depotcheck-PDF: reine Analyse des empfohlenen Zielportfolios.
         *
         *     DEPOT-E2E-SNAPSHOT-001 (CIO-Entscheid): das PDF liest einen gespeicherten,
         *     an einen Depot-Snapshot gebundenen Depot-Check -- ``analysis_snapshot_id``
         *     oder, in einem Klick, den des aktuellen Bestands (Berater: Depot-Snapshot
         *     und Depot-Check werden idempotent gespeichert). Unvollstaendige Bewertung
         *     -> 409 mit Grund. Nur ohne erfassten Depotbestand: reine SOLL-Analyse,
         *     gekennzeichnet, ohne Snapshot-Bindung.
         */
        get: operations["get_depotcheck_pdf_mandates__mandate_id__reports_depotcheck_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/reports/portfolio.pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Portfolio Pdf
         * @description Sprint 11 Phase 6: Portfolio-PDF mit Positionen + Soll-vs-IST + Drift.
         */
        get: operations["get_portfolio_pdf_mandates__mandate_id__reports_portfolio_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/reports/protokoll.pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Protokoll Pdf
         * @description Beratungsprotokoll-PDF mit AdvisoryLog und Unterschrift.
         */
        get: operations["get_protokoll_pdf_mandates__mandate_id__reports_protokoll_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/reports/risikoprofil.pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Risikoprofil Pdf
         * @description Generiert Risikoprofil-PDF fuer das Mandat (FINMA W305-konform).
         */
        get: operations["get_risikoprofil_pdf_mandates__mandate_id__reports_risikoprofil_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/reports/vertrag.pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Vertrag Pdf
         * @description Sprint 12: Vertrags-PDF (ContractDocument). Optional ?document_id=...
         */
        get: operations["get_vertrag_pdf_mandates__mandate_id__reports_vertrag_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/risk-assessments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Risk Assessments */
        get: operations["list_risk_assessments_mandates__mandate_id__risk_assessments_get"];
        put?: never;
        /** Create Risk Assessment */
        post: operations["create_risk_assessment_mandates__mandate_id__risk_assessments_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/risk-assessments/current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Current Risk Assessment */
        get: operations["get_current_risk_assessment_mandates__mandate_id__risk_assessments_current_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/risk-assessments/{ra_id}/override": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Override Risk Assessment */
        post: operations["override_risk_assessment_mandates__mandate_id__risk_assessments__ra_id__override_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/risk-capacity-plausibility": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Risk Capacity Plausibility
         * @description RISK-CAPACITY-PLAUSIBILITY-001: Fragebogen-Angaben zur Risikofaehigkeit
         *     gegen die erfassten Finanzdaten. Reiner Hinweis -- aendert das Profil nicht,
         *     blockiert nichts.
         */
        get: operations["get_risk_capacity_plausibility_mandates__mandate_id__risk_capacity_plausibility_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/risk-capacity-plausibility/evaluations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Risk Capacity Plausibility Evaluations
         * @description RISK-CAPACITY-EVALUATION-SNAPSHOT-001: gebundene, unveraenderliche
         *     Bewertungen (neueste zuerst) mit Replay (Hash, Regel-Nachrechnung,
         *     Aktualitaet). Betragsfrei; die Zeilen werden nie ueberschrieben.
         */
        get: operations["list_risk_capacity_plausibility_evaluations_mandates__mandate_id__risk_capacity_plausibility_evaluations_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/risk-profile/sign": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Sign Risk Profile
         * @description FIDLEG-Eignungspruefung: Berater erfasst die Bestaetigung des aktuellen
         *     Risikoprofils (Fallback A, Methode 'advisor_recorded' = Beweisniveau
         *     'advisor_attested', KEINE elektronische Kundensignatur). Reine
         *     DOKUMENTATION -- aendert die Eignungs-Konformitaet (Audit is_compliant)
         *     NICHT.
         *
         *     RISK-PROFILE-SIGNOFF-001: schreibt einen append-only RiskProfileSignoffV1,
         *     gebunden an Assessment-Version, wirksames Profil und die verifizierte
         *     Override-Decision (oder 'no_override'). Nicht verifizierbare Decision,
         *     veraltete Erwartungswerte oder ein paralleler Override -> 409 vor jeder
         *     Wirkung.
         */
        post: operations["sign_risk_profile_mandates__mandate_id__risk_profile_sign_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/strategy-snapshots": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Snapshots */
        get: operations["list_snapshots_mandates__mandate_id__strategy_snapshots_get"];
        put?: never;
        /** Create Snapshot */
        post: operations["create_snapshot_mandates__mandate_id__strategy_snapshots_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/strategy-snapshots/latest/drift": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Drift */
        get: operations["get_drift_mandates__mandate_id__strategy_snapshots_latest_drift_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/suitability-checks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Suitability Checks */
        get: operations["list_suitability_checks_mandates__mandate_id__suitability_checks_get"];
        put?: never;
        /** Create Suitability Check */
        post: operations["create_suitability_check_mandates__mandate_id__suitability_checks_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/target-allocation": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Create Target Allocation */
        post: operations["create_target_allocation_mandates__mandate_id__target_allocation_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/target-allocation/current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Current Allocation */
        get: operations["get_current_allocation_mandates__mandate_id__target_allocation_current_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/target-allocation/current/analysis-integrity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Current Allocation Analysis Integrity
         * @description GOAL-ANALYSIS-INTEGRITY-001 / SHADOW-ANALYSIS-INTEGRITY-001: Status der
         *     gespeicherten Zielanalyse und des Shadow-Containers der aktuellen
         *     Soll-Allokation fuer den ruhigen Berater-Hinweis. Read-only, wirft nie
         *     wegen einer Integritaetsverletzung (die erscheint als ``integrity_mismatch``).
         */
        get: operations["get_current_allocation_analysis_integrity_mandates__mandate_id__target_allocation_current_analysis_integrity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/target-allocation/current/payload": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Current Allocation Payload */
        get: operations["get_current_allocation_payload_mandates__mandate_id__target_allocation_current_payload_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/target-allocation/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Generate Target Allocation Endpoint */
        post: operations["generate_target_allocation_endpoint_mandates__mandate_id__target_allocation_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/target-allocation/sensitivity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Goal Target Sensitivity
         * @description Phase 6 FE-Optimizer-Panel: ein einzelnes Goal um delta_pct verschieben
         *     und neuen Solver-Lauf zurueckliefern (mit gepinntem Seed = identische
         *     Scenarios = sauberes Apples-to-Apples-Delta).
         *
         *     Gibt 409 wenn OPTIMIZER_MODE != 'stochastic' oder kein Risikoprofil.
         *     Gibt 404 wenn Goal nicht zum Mandanten gehoert.
         *
         *     FINMA-Trace: jeder Aufruf wird als SENSITIVITY-Eintrag im AuditLog
         *     persistiert (mandate, goal, delta).
         */
        post: operations["goal_target_sensitivity_mandates__mandate_id__target_allocation_sensitivity_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/triggers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Triggers */
        get: operations["list_triggers_mandates__mandate_id__triggers_get"];
        put?: never;
        /** Create Trigger */
        post: operations["create_trigger_mandates__mandate_id__triggers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/triggers/system-refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Refresh System Triggers */
        post: operations["refresh_system_triggers_mandates__mandate_id__triggers_system_refresh_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/triggers/{trigger_id}/frequency": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Trigger Frequency
         * @description REVIEW-STATE-004 (Kontrollrunde 2026-09-24): erlaubt dem Berater, das
         *     Intervall eines Zeit-Triggers (z.B. den System-Jahresreview auf
         *     "halbjährlich" bei erhöhtem Risiko) explizit zu setzen. Ohne diesen
         *     Endpoint gab es keine Moeglichkeit, ein Intervall dauerhaft zu aendern --
         *     `refresh_system_review_triggers` hat den System-Review-Trigger vorher bei
         *     JEDEM Refresh hart auf "jährlich" zurueckgesetzt.
         */
        put: operations["update_trigger_frequency_mandates__mandate_id__triggers__trigger_id__frequency_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/mandates/{mandate_id}/triggers/{trigger_id}/resolve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Resolve Trigger
         * @description REVIEW-STATE-003 (Codex-Audit 2026-08-27): resolve() verwarf bisher
         *     das Pflichtfeld `decision` komplett (nur `triggered_notes` wurde
         *     gelesen), pruefte weder Status noch Faelligkeit vor der Mutation und war
         *     dadurch beliebig oft replaybar -- jeder Aufruf verschob die naechste
         *     Jahresfrist aus der aktuellen Serverzeit neu, ohne Entscheidnachweis.
         *
         *     Jetzt: (1) nur tatsaechlich ausgeloeste oder faellige Trigger duerfen
         *     aufgeloest werden, (2) `decision` wird gelesen UND append-only mit
         *     Actor/Zeitpunkt/vorherigem Faelligkeitsanker persistiert, (3) die Mutation
         *     ist ein atomares Compare-and-Set gegen den zuvor gelesenen Status -- ein
         *     paralleler oder frueher zweiter Resolve trifft auf 409 statt die Frist
         *     ein zweites Mal zu verschieben.
         */
        put: operations["resolve_trigger_mandates__mandate_id__triggers__trigger_id__resolve_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/me/calendar-feed-token": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Issue My Calendar Feed Token
         * @description Erzeugt (bzw. rotiert) den persoenlichen .ics-Abo-Token. Der Klartext
         *     wird ausschliesslich in dieser Antwort zurueckgegeben -- der Berater muss
         *     ihn direkt in Outlook als 'Internetkalender abonnieren' hinterlegen. Ein
         *     bereits bestehendes Abo mit dem vorherigen Token wird durch die Rotation
         *     invalidiert.
         */
        post: operations["issue_my_calendar_feed_token_me_calendar_feed_token_post"];
        /** Revoke My Calendar Feed Token */
        delete: operations["revoke_my_calendar_feed_token_me_calendar_feed_token_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/onsite-signature/policy": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Onsite Signature Policy */
        get: operations["get_onsite_signature_policy_onsite_signature_policy_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/optimizer-policies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Optimizer Policies Read
         * @description Sprint U-P15: Read-only Policy-Liste für Advisor-UI (A/B-Backtest-
         *     Selektoren). Im Gegensatz zu /admin/optimizer-policies erfordert dieser
         *     Endpoint kein Admin-Recht — er liefert nur die schlanke Liste ohne
         *     HouseMatrix-Detail-Rows.
         */
        get: operations["list_optimizer_policies_read_optimizer_policies_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/optimizer-policies/current": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Current Policy */
        get: operations["get_current_policy_optimizer_policies_current_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/erasure-cases": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Open Erasure Case */
        post: operations["open_erasure_case_privacy_erasure_cases_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/erasure-cases/{case_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Erasure Case */
        get: operations["get_erasure_case_privacy_erasure_cases__case_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/erasure-cases/{case_id}/execute": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Execute Erasure Case */
        post: operations["execute_erasure_case_privacy_erasure_cases__case_id__execute_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/erasure-cases/{case_id}/refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Refresh Erasure Case */
        post: operations["refresh_erasure_case_privacy_erasure_cases__case_id__refresh_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/legal-holds": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Legal Holds */
        get: operations["list_legal_holds_privacy_legal_holds_get"];
        put?: never;
        /** Propose Legal Hold */
        post: operations["propose_legal_hold_privacy_legal_holds_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/legal-holds/{hold_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Approve Legal Hold */
        post: operations["approve_legal_hold_privacy_legal_holds__hold_id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/legal-holds/{hold_id}/extend": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Extend Legal Hold */
        post: operations["extend_legal_hold_privacy_legal_holds__hold_id__extend_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/legal-holds/{hold_id}/release": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Release Legal Hold */
        post: operations["release_legal_hold_privacy_legal_holds__hold_id__release_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/policies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Policies */
        get: operations["list_policies_privacy_policies_get"];
        put?: never;
        /** Propose Policy */
        post: operations["propose_policy_privacy_policies_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/policies/{policy_id}/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Approve Policy */
        post: operations["approve_policy_privacy_policies__policy_id__approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/retention-expiry": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Run Retention Expiry */
        post: operations["run_retention_expiry_privacy_retention_expiry_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/roles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Roles */
        get: operations["list_roles_privacy_roles_get"];
        put?: never;
        /** Grant Role */
        post: operations["grant_role_privacy_roles_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/roles/{designation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Revoke Role */
        delete: operations["revoke_role_privacy_roles__designation_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/privacy/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Privacy Status */
        get: operations["privacy_status_privacy_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/product-universe": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Product Universe Entries */
        get: operations["list_product_universe_entries_product_universe_get"];
        put?: never;
        /** Create Product Universe Entry */
        post: operations["create_product_universe_entry_product_universe_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/product-universe/{entry_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Product Universe Entry */
        put: operations["update_product_universe_entry_product_universe__entry_id__put"];
        post?: never;
        /** Delete Product Universe Entry */
        delete: operations["delete_product_universe_entry_product_universe__entry_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Products
         * @description Sprint U-95 (2026-06-05): ESG/SFDR-Filter ergaenzt.
         *     Fondsuniversum (2026-08-05): Freitext-Suche (q) + Tenant-Scoping ergaenzt
         *     -- zeigt den globalen Katalog PLUS die eigenen, privat erfassten Fonds
         *     des aufrufenden Users' Tenants (nie die eines anderen Tenants).
         *
         *     Berater kann nach SFDR-Klassifizierung (Art. 6/8/9) und ESG-Rating
         *     filtern um Anlageprodukte zu finden die zu den ESG-Preferences des
         *     Kunden passen. Filter sind additiv (AND-Verknuepfung).
         */
        get: operations["list_products_products_get"];
        put?: never;
        /**
         * Create Product
         * @description Fondsuniversum (2026-08-05, User-Direktive): manuell erfasste Fonds
         *     (kotiert MIT isin/symbol, oder nicht-kotiert OHNE -- beide Felder sind
         *     bereits optional auf Product) werden serverseitig dem Tenant des
         *     erfassenden Admins zugeordnet -- NIE aus dem Client-Payload uebernommen
         *     (ProductCreate hat gar kein tenant_id-Feld), sonst waere ein Tenant-
         *     Spoofing moeglich (Firma A koennte sich als Firma B ausgeben). So kann
         *     jedes Assetmanagement seine eigenen Fonds erfassen, ohne dass sie fuer
         *     andere Tenants sichtbar werden (siehe _active_products_query).
         *
         *     2026-08-05 (Live-Smoketest-Fund): products.isin hat einen GLOBALEN
         *     Unique-Index (ux_products_isin_active, ueber alle Tenants hinweg --
         *     eine ISIN identifiziert ein real existierendes Wertpapier, unabhaengig
         *     davon, welcher Tenant es erfasst hat). Ohne diesen Vorab-Check wuerde
         *     ein Kollisionsversuch (auch durch einen VOELLIG ANDEREN Tenant, dessen
         *     private Eintraege man gar nicht sehen kann) mit einem rohen 500 statt
         *     einer verstaendlichen Fehlermeldung crashen.
         */
        post: operations["create_product_products_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/eligibility-drafts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Product Eligibility Drafts
         * @description ELIG-GOVERNANCE-001 (2026-10-22): offene Entwurfs-Eignungsregeln der
         *     eigenen Verwaltung (fuer den Status "Entwurf -- Freigabe ausstehend" im
         *     Fondsuniversum) plus die Angabe, ob die Einzelberater-Ausnahme fuer den
         *     aktuellen Benutzer ueberhaupt in Frage kommt.
         */
        get: operations["list_product_eligibility_drafts_products_eligibility_drafts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/eodhd/apply": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Apply Product Reference Data */
        post: operations["apply_product_reference_data_products_eodhd_apply_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/eodhd/auto-apply": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Auto Apply Product Reference Data */
        post: operations["auto_apply_product_reference_data_products_eodhd_auto_apply_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/eodhd/resolve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Resolve Product Reference Data */
        post: operations["resolve_product_reference_data_products_eodhd_resolve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Import Products Bulk
         * @description Fondsuniversum Bulk-API-Import: fuer externe Asset-Manager-Systeme,
         *     die ihren Fondskatalog programmatisch pushen wollen. Nutzt dieselbe
         *     Bearer-Token-Authentifizierung wie jeder andere Endpoint (kein
         *     separates API-Key-System noetig) -- ein Asset Manager erhaelt einen
         *     Tenant-User-Account, meldet sich ueber POST /auth/login an und ruft
         *     diesen Endpoint mit dem erhaltenen Token auf. Siehe _import_products
         *     fuer die Upsert-/Isolationslogik.
         */
        post: operations["import_products_bulk_products_import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/import/csv": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Import Products Csv
         * @description Fondsuniversum CSV-Import: erlaubt einem Asset Manager, seinen
         *     Fondskatalog per Datei-Upload statt Einzel-Erfassung einzuspielen.
         *     Spalten-Reihenfolge ist egal (Header-basiertes Mapping), Trennzeichen
         *     wird automatisch erkannt (Komma oder Semikolon -- Schweizer/deutsches
         *     Excel exportiert standardmaessig mit Semikolon). Siehe
         *     /products/import/csv/template fuer die erwarteten Spaltennamen.
         */
        post: operations["import_products_csv_products_import_csv_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/import/csv/template": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Download Products Csv Template
         * @description CSV-Vorlage mit den vom Import erwarteten Spaltennamen -- je ein
         *     Beispiel fuer einen kotierten (mit ISIN/Symbol) und einen
         *     nicht-kotierten Fonds (ISIN/Symbol leer).
         */
        get: operations["download_products_csv_template_products_import_csv_template_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/market-data/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Product Market Data Status */
        get: operations["get_product_market_data_status_products_market_data_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/openfigi/apply": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Apply Product Id Mapping */
        post: operations["apply_product_id_mapping_products_openfigi_apply_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/openfigi/auto-apply": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Auto Apply Product Id Mappings */
        post: operations["auto_apply_product_id_mappings_products_openfigi_auto_apply_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/openfigi/resolve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Resolve Product Id Mapping */
        post: operations["resolve_product_id_mapping_products_openfigi_resolve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/{product_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Product
         * @description Sprint U-P10: Admin editiert Produkt-Metadaten + Diversifikations-Tiefe.
         *
         *     Alle Felder optional; nur gesetzte werden ueberschrieben. JSON-Strings
         *     (country/sector/currency_exposure_json) werden bereits am Schema-Rand
         *     validiert (siehe schemas/review.py::ProductUpdate -- PROD-DOMAIN-001,
         *     2026-09-05): Form (dict[str,number]), Non-Negativitaet, Summe ~10000bps.
         *     services/product_exposures.py::_parse_or_proxy bleibt zusaetzlich
         *     fault-tolerant fuer bereits vor dem Fix gespeicherte Legacy-Daten.
         */
        put: operations["update_product_products__product_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/{product_id}/eligibility-rule/approve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Approve Product Eligibility Rule
         * @description ELIG-GOVERNANCE-001 (2026-10-21/22): Freigabe der beim Erfassen/Import
         *     eines Tenant-Produkts angelegten Entwurfs-Eignungsregel
         *     (services/product_eligibility.py::author_tenant_product_rule). Bis dahin
         *     ist das Produkt `indeterminate` und fuer Generate nicht waehlbar.
         *
         *     Standard Vier-Augen: 409, wenn der Genehmiger die Regel selbst verfasst
         *     hat. Einzelberater-Ausnahme (fail-closed): Selbstfreigabe nur mit
         *     single_approver_attestation=true + Begruendung UND genau einer
         *     freigabeberechtigten Person in der Verwaltung; gespeichert als
         *     approval_mode='single_approver_attested' (Teil des rule_hash, Audit-Log).
         *     409 auch, wenn keine Entwurfsregel offen ist.
         */
        post: operations["approve_product_eligibility_rule_products__product_id__eligibility_rule_approve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/products/{product_id}/market-override": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Set Product Market Override */
        put: operations["set_product_market_override_products__product_id__market_override_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/protocol-bausteine": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Bausteine
         * @description Berater sieht: eigene Bausteine + global (advisor_id IS NULL).
         *     Admin sieht: alles -- aber IMMER nur innerhalb des eigenen Tenants (siehe
         *     _apply_tenant_filter_to_baustein_query; SEC 2026-07-23).
         */
        get: operations["list_bausteine_protocol_bausteine_get"];
        put?: never;
        /** Create Baustein */
        post: operations["create_baustein_protocol_bausteine_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/protocol-bausteine/{baustein_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Baustein */
        put: operations["update_baustein_protocol_bausteine__baustein_id__put"];
        post?: never;
        /** Delete Baustein */
        delete: operations["delete_baustein_protocol_bausteine__baustein_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/tax/estimate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Estimate Tax */
        post: operations["estimate_tax_tax_estimate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/tax/jurisdictions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Tax Jurisdictions */
        get: operations["get_tax_jurisdictions_tax_jurisdictions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/tenants": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Tenants
         * @description Listet alle aktiven Tenants. Tier 2 only.
         */
        get: operations["list_tenants_tenants_get"];
        put?: never;
        /**
         * Create Tenant
         * @description Erstellt einen neuen Tenant (Lizenz-Nehmer).
         *
         *     Pre-Check: settings.tenant_admin_ui_enabled muss True sein (Tier 2).
         */
        post: operations["create_tenant_tenants_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/tenants/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get My Tenant
         * @description 2026-08-01 (Onboarding): liefert die eigene Firma (current_user.
         *     tenant_id) -- TIER-UNABHAENGIG, im Gegensatz zu GET /tenants/{id}
         *     (Tier 2 only via _check_tenant_admin_ui_enabled). Muss VOR der
         *     /{tenant_id}-Route registriert sein, sonst matcht FastAPI 'me' als
         *     tenant_id-Pfadparameter.
         *
         *     2026-08-09 (Roadmap #24-Rest): liefert zusaetzlich die aktuelle
         *     Auslastung (current_users/current_mandates), damit das Frontend eine
         *     Soft-Limit-Warnung VOR dem harten 409-Block anzeigen kann.
         */
        get: operations["get_my_tenant_tenants_me_get"];
        /**
         * Update My Tenant
         * @description 2026-08-01 (Onboarding): erlaubt einem normalen Firmen-Admin (nicht
         *     super_admin), Firmenname/Standort der EIGENEN Firma zu pflegen --
         *     z.B. nachtraeglich, falls bei der Ersteinrichtung (/auth/bootstrap-admin)
         *     nichts oder etwas Falsches angegeben wurde. Bewusst schmaleres Schema
         *     (TenantSelfServiceUpdate) als das super_admin-only PUT /tenants/{id}:
         *     kein Zugriff auf hosting_tier/license_status/max_users etc.
         */
        put: operations["update_my_tenant_tenants_me_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/tenants/{tenant_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Tenant
         * @description Liest einen einzelnen Tenant.
         */
        get: operations["get_tenant_tenants__tenant_id__get"];
        /**
         * Update Tenant
         * @description Partial-Update eines Tenants. Tier 2 only.
         */
        put: operations["update_tenant_tenants__tenant_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/tenants/{tenant_id}/users/{user_id}/assign": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Assign User To Tenant
         * @description Weist einen User einem Tenant zu (Super-Admin only).
         */
        put: operations["assign_user_to_tenant_tenants__tenant_id__users__user_id__assign_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/users": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Users */
        get: operations["list_users_users_get"];
        put?: never;
        /** Create User */
        post: operations["create_user_users_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/users/invite": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Invite User
         * @description E1 (2026-06-14): Mitarbeiter-Onboarding per Einladungslink.
         *
         *     Legt einen Account OHNE nutzbares Passwort an (Mitarbeiter setzt es selbst
         *     via Token). Tenant wird vom anlegenden Admin geerbt -> harte Firmen-Trennung.
         *     Der Klartext-Token wird NUR EINMAL zurueckgegeben (gespeichert wird nur der Hash).
         *     Nach Annahme erzwingt das 2FA-Hard-Gate beim ersten Login das Enrollment.
         */
        post: operations["invite_user_users_invite_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/users/{user_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update User */
        put: operations["update_user_users__user_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/users/{user_id}/adviser-registration": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Adviser Registration */
        get: operations["get_adviser_registration_users__user_id__adviser_registration_get"];
        /** Upsert Adviser Registration */
        put: operations["upsert_adviser_registration_users__user_id__adviser_registration_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/users/{user_id}/invite": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Revoke Invite
         * @description E1 (2026-06-14): Offene Einladung zurückziehen. Der noch nie aktivierte
         *     Account wird soft-gelöscht (Link tot, kein verwaister Account).
         */
        delete: operations["revoke_invite_users__user_id__invite_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/users/{user_id}/invite/resend": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Resend Invite
         * @description E1 (2026-06-14): Einladung erneut senden — neuer Token + Ablauf für einen
         *     noch NICHT aktivierten Account (z.B. Link verloren / abgelaufen).
         */
        post: operations["resend_invite_users__user_id__invite_resend_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/users/{user_id}/password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Reset User Password */
        put: operations["reset_user_password_users__user_id__password_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/wealth-inflows/{inflow_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Update Wealth Inflow */
        put: operations["update_wealth_inflow_wealth_inflows__inflow_id__put"];
        post?: never;
        /** Delete Wealth Inflow */
        delete: operations["delete_wealth_inflow_wealth_inflows__inflow_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AbortRequest */
        AbortRequest: {
            /**
             * Reason Code
             * @enum {string}
             */
            reason_code: "OFFLINE_ABORT" | "CUSTOMER_DECLINED" | "ADVISOR_CANCELLED";
        };
        /** AdviserRegistrationCreate */
        AdviserRegistrationCreate: {
            /** Notes */
            notes?: string | null;
            /** Ombudsman Affiliated Since */
            ombudsman_affiliated_since?: string | null;
            /** Ombudsman Body */
            ombudsman_body?: string | null;
            /** Ombudsman Membership Number */
            ombudsman_membership_number?: string | null;
            /** Qualifications Json */
            qualifications_json?: string | null;
            /**
             * Register Body
             * @default FINMA Beraterregister
             */
            register_body?: string;
            /** Register Number */
            register_number?: string | null;
            /**
             * Register Status
             * @default Aktiv
             */
            register_status?: string;
            /** Register Valid Until */
            register_valid_until?: string | null;
            /** Registered At */
            registered_at?: string | null;
        };
        /** AdviserRegistrationResponse */
        AdviserRegistrationResponse: {
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /** Notes */
            notes: string | null;
            /** Ombudsman Affiliated Since */
            ombudsman_affiliated_since: string | null;
            /** Ombudsman Body */
            ombudsman_body: string | null;
            /** Ombudsman Membership Number */
            ombudsman_membership_number: string | null;
            /** Register Body */
            register_body: string;
            /** Register Number */
            register_number: string | null;
            /** Register Status */
            register_status: string;
            /** Register Valid Until */
            register_valid_until: string | null;
            /** Registered At */
            registered_at: string | null;
            /** User Id */
            user_id: string;
        };
        /**
         * AdvisoryLogCreate
         * @description Pflicht-Felder für FINMA-konformes Beratungsprotokoll (Sprint U-FINMA-2.1).
         *
         *     Mindestlängen: `description` ≥ 30, `decision` ≥ 10 (außer bei reinem
         *     Diskussions-Eintrag), `topics` ≥ 1.
         */
        AdvisoryLogCreate: {
            /**
             * Client Signed
             * @default false
             */
            client_signed?: boolean;
            /** Client Signed At */
            client_signed_at?: string | null;
            /**
             * Communication Channel
             * @description Medium des Gesprächs. Entscheidet über Hinweispflichten.
             * @enum {string}
             */
            communication_channel: "persoenlich" | "video" | "telefon" | "schriftlich" | "hybrid";
            /**
             * Conflict Disclosure Ids
             * @description IDs der offengelegten ConflictOfInterestDisclosures.
             */
            conflict_disclosure_ids?: string[];
            /**
             * Cost Disclosure Given
             * @description Ex-ante Kosten kommuniziert? FIDLEG-Pflicht.
             */
            cost_disclosure_given: boolean;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Decision */
            decision?: ("Keine Transaktion" | "Transaktion empfohlen" | "Strategie angepasst" | "Profil angepasst" | "Override bestätigt" | "Kein Handlungsbedarf") | null;
            /**
             * Description
             * @description Inhalt des Gesprächs: besprochene Themen, Argumente, Kundenposition. Min 30 Zeichen für FINMA-Nachvollziehbarkeit.
             */
            description: string;
            /** Document Id */
            document_id?: string | null;
            /**
             * Duration Minutes
             * @description Dauer 1-600 Minuten. Sehr kurze oder lange Termine sollten manuell begründet sein.
             */
            duration_minutes: number;
            /** Entry Date */
            entry_date?: string | null;
            /**
             * Entry Datetime
             * @description ISO-Zeitpunkt des Gesprächs (Y-m-dTH:M:S.fZ).
             */
            entry_datetime: string;
            /**
             * Entry Type
             * @enum {string}
             */
            entry_type: "Jahresreview" | "Quartalscheck" | "Strategie-Anpassung" | "Override-Entscheid" | "Ereignis-Reaktion" | "Drift-Entscheid" | "Zieländerung" | "Restriktionsänderung" | "Initialer Beratungsabschluss" | "Eignungsprüfung" | "Sonstiges";
            /**
             * Language
             * @default de
             * @enum {string}
             */
            language?: "de" | "fr" | "it" | "en";
            /** Location */
            location?: string | null;
            /**
             * Participants
             * @description Anwesende neben dem Berater.
             */
            participants?: components["schemas"]["AdvisoryParticipant"][];
            /** Recommendation Run Id */
            recommendation_run_id?: string | null;
            /**
             * Risk Warnings Given
             * @description Konkret erteilte Risiko-Hinweise (FIDLEG-Pflicht).
             */
            risk_warnings_given?: string[];
            /** Status */
            status?: ("Empfohlen" | "Beschlossen" | "Umgesetzt" | "Abgelehnt" | "Überarbeitung nötig") | null;
            /** Suitability Check Id */
            suitability_check_id?: string | null;
            /** Title */
            title: string;
            /**
             * Topics
             * @description Strukturierte Themen-Liste (min 1 Eintrag).
             */
            topics: string[];
            /** Trigger Id */
            trigger_id?: string | null;
        };
        /** AdvisoryLogResponse */
        AdvisoryLogResponse: {
            /** Advisor Id */
            advisor_id: string;
            /** Client Signed */
            client_signed: number;
            /** Client Signed At */
            client_signed_at: string | null;
            /** Communication Channel */
            communication_channel?: string | null;
            /** Conflict Disclosure Ids */
            conflict_disclosure_ids?: string[];
            /**
             * Cost Disclosure Given
             * @default 0
             */
            cost_disclosure_given?: number;
            /** Cost Disclosure Snapshot */
            cost_disclosure_snapshot?: Record<string, unknown> | null;
            /** Created At */
            created_at: string;
            /** Decision */
            decision: string | null;
            /** Description */
            description: string | null;
            /** Document Id */
            document_id: string | null;
            /** Duration Minutes */
            duration_minutes?: number | null;
            /** Entry Date */
            entry_date: string;
            /** Entry Datetime */
            entry_datetime?: string | null;
            /** Entry Type */
            entry_type: string;
            /** Id */
            id: string;
            /** Integrity Hash */
            integrity_hash?: string | null;
            /** Integrity Verified */
            integrity_verified?: boolean | null;
            /** Language */
            language?: string | null;
            /** Last Read At */
            last_read_at?: string | null;
            /** Last Read By */
            last_read_by?: string | null;
            /** Location */
            location?: string | null;
            /** Mandate Id */
            mandate_id: string;
            /** Participants */
            participants?: Record<string, unknown>[];
            /** Recommendation Run Id */
            recommendation_run_id: string | null;
            /** Retain Until */
            retain_until?: string | null;
            /** Risk Warnings Given */
            risk_warnings_given?: string[];
            /** Status */
            status: string;
            /** Suitability Check Id */
            suitability_check_id?: string | null;
            /** Superseded By Id */
            superseded_by_id?: string | null;
            /** Supersedes Id */
            supersedes_id?: string | null;
            /** Title */
            title: string;
            /** Topics */
            topics?: string[];
            /** Trigger Id */
            trigger_id: string | null;
            /** Updated At */
            updated_at: string;
            /**
             * Version
             * @default 1
             */
            version?: number;
        };
        /**
         * AdvisoryLogUpdate
         * @description Update erzeugt eine *neue* Version, der alte Eintrag wird marked-as-
         *     superseded (kein In-Place-Update — FINMA-Audit-Trail-Pflicht).
         */
        AdvisoryLogUpdate: {
            /** Client Signed */
            client_signed?: boolean | null;
            /** Client Signed At */
            client_signed_at?: string | null;
            /** Decision */
            decision?: ("Keine Transaktion" | "Transaktion empfohlen" | "Strategie angepasst" | "Profil angepasst" | "Override bestätigt" | "Kein Handlungsbedarf") | null;
            /** Description */
            description?: string | null;
            /** Recommendation Run Id */
            recommendation_run_id?: string | null;
            /** Risk Warnings Given */
            risk_warnings_given?: string[] | null;
            /** Status */
            status?: ("Empfohlen" | "Beschlossen" | "Umgesetzt" | "Abgelehnt" | "Überarbeitung nötig") | null;
            /** Topics */
            topics?: string[] | null;
        };
        /**
         * AdvisoryParticipant
         * @description Ein Anwesender neben dem Berater. FINMA-Tracking für Datenschutz +
         *     Auskunftspflicht.
         */
        AdvisoryParticipant: {
            /** Name */
            name: string;
            /** Note */
            note?: string | null;
            /**
             * Role
             * @enum {string}
             */
            role: "client" | "co_advisor" | "partner" | "guardian" | "third_party";
        };
        /** AllocationBandOverridePayload */
        AllocationBandOverridePayload: {
            /** Max Bps */
            max_bps?: number | null;
            /** Min Bps */
            min_bps?: number | null;
            /** Target Bps */
            target_bps?: number | null;
        };
        /** AllocationBucketResponse */
        AllocationBucketResponse: {
            /** Asset Class */
            asset_class: string;
            /** Band Max Bps */
            band_max_bps: number;
            /** Band Min Bps */
            band_min_bps: number;
            /** Current Amount Rappen */
            current_amount_rappen: number;
            /** Current Weight Bps */
            current_weight_bps: number;
            /** Delta Weight Bps */
            delta_weight_bps: number;
            /** Target Amount Rappen */
            target_amount_rappen: number;
            /** Target Weight Bps */
            target_weight_bps: number;
        };
        /** AllocationMethodCandidateResponse */
        AllocationMethodCandidateResponse: {
            /** Constraint Violations */
            constraint_violations?: string[];
            /** Feasible */
            feasible?: boolean | null;
            /** Method */
            method: string;
            /** Objective Value Milli */
            objective_value_milli?: number | null;
            /** Role */
            role: string;
            /** Status */
            status?: string | null;
            /** Terminal Wealth P10 Rappen */
            terminal_wealth_p10_rappen?: number | null;
            /** Terminal Wealth P50 Rappen */
            terminal_wealth_p50_rappen?: number | null;
            /** Terminal Wealth P90 Rappen */
            terminal_wealth_p90_rappen?: number | null;
            /** Weights Bps */
            weights_bps: {
                [key: string]: number;
            };
        };
        /**
         * AllocationMethodComparisonResponse
         * @description V3 Sprint 1 Shadow-Stochastic: Methodenvergleich House Matrix vs. Solver.
         *
         *     Wird nur befuellt, wenn settings.optimizer_mode == 'shadow_stochastic'.
         *     objective_value_milli_* und objective_delta_pct sind nur dann gesetzt, wenn
         *     beide Methoden Apples-to-Apples unter demselben Context bewertet wurden
         *     (Sprint 1b/Commit 3 — siehe V3-Codeplan §5.6).
         */
        AllocationMethodComparisonResponse: {
            /** Active Method */
            active_method: string;
            /** Active Weights Bps */
            active_weights_bps: {
                [key: string]: number;
            };
            /** Advisory Note */
            advisory_note: string;
            /** Candidates */
            candidates?: components["schemas"]["AllocationMethodCandidateResponse"][];
            /** Objective Delta Pct */
            objective_delta_pct?: number | null;
            /** Objective Value Milli Active */
            objective_value_milli_active?: number | null;
            /** Objective Value Milli Shadow */
            objective_value_milli_shadow?: number | null;
            /** Shadow Method */
            shadow_method?: string | null;
            /** Shadow Status */
            shadow_status?: string | null;
            /** Shadow Weights Bps */
            shadow_weights_bps?: {
                [key: string]: number;
            } | null;
            /** Weight Deltas Bps */
            weight_deltas_bps?: {
                [key: string]: number;
            };
        };
        /** AllocationPreferencesPayload */
        AllocationPreferencesPayload: {
            /** Assetclasses */
            assetClasses?: Record<string, unknown>;
            /** Banddeviationreason */
            bandDeviationReason?: string | null;
            /** Bands */
            bands?: {
                [key: string]: components["schemas"]["AllocationBandOverridePayload"];
            };
            /** Cmacurrencymismatchreason */
            cmaCurrencyMismatchReason?: string | null;
            /** Geo */
            geo?: Record<string, unknown>;
            /** Limits */
            limits?: Record<string, unknown>;
            /** Policy */
            policy?: Record<string, unknown>;
            /** Product */
            product?: Record<string, unknown>;
            /** Simulation */
            simulation?: Record<string, unknown>;
            /** Tiltreasons */
            tiltReasons?: Record<string, unknown>;
            /** Tilts */
            tilts?: Record<string, unknown>;
        };
        /** AllocationSensitivityRequest */
        AllocationSensitivityRequest: {
            /** Goal Id */
            goal_id: string;
            /**
             * Horizon Delta Years
             * @default 0
             */
            horizon_delta_years?: number;
            /** Target Delta Pct */
            target_delta_pct: number;
        };
        /** AllocationSensitivityResponse */
        AllocationSensitivityResponse: {
            /** Allocation Context Hash */
            allocation_context_hash?: string | null;
            /**
             * Analysis Basis
             * @default live_reoptimization_common_scenarios_current_inputs_v3
             */
            analysis_basis?: string;
            /** Baseline Model Input Hash */
            baseline_model_input_hash?: string | null;
            /** Baseline Reserve Funding Ledger */
            baseline_reserve_funding_ledger?: Record<string, unknown> | null;
            /** Capital Market Assumptions Id */
            capital_market_assumptions_id?: string | null;
            /** Constraint Basis */
            constraint_basis?: string | null;
            /** Delta Objective Pct */
            delta_objective_pct: number | null;
            /** Delta Objective Unavailable Reason */
            delta_objective_unavailable_reason?: string | null;
            /** Delta Pct */
            delta_pct: number;
            /** External Foundation Basis */
            external_foundation_basis?: string | null;
            /** Fx Basis */
            fx_basis?: Record<string, unknown> | null;
            /** Goal Id */
            goal_id: string;
            /**
             * Horizon Delta Years
             * @default 0
             */
            horizon_delta_years?: number;
            /** Horizon Years Baseline */
            horizon_years_baseline?: number | null;
            /** Horizon Years New */
            horizon_years_new?: number | null;
            /** Live Model Input Hash */
            live_model_input_hash?: string | null;
            /** Modified Model Input Hash */
            modified_model_input_hash?: string | null;
            /** Modified Reserve Funding Ledger */
            modified_reserve_funding_ledger?: Record<string, unknown> | null;
            /** Objective Value Milli Baseline */
            objective_value_milli_baseline: number | null;
            /** Objective Value Milli New */
            objective_value_milli_new: number | null;
            /** Scenario Pairing Basis */
            scenario_pairing_basis?: string | null;
            /** Solver Horizon Years Baseline */
            solver_horizon_years_baseline?: number | null;
            /** Solver Horizon Years New */
            solver_horizon_years_new?: number | null;
            /** Solver Seed */
            solver_seed?: number | null;
            /** Status Baseline */
            status_baseline: string;
            /** Status New */
            status_new: string;
            /** Target Amount Rappen Baseline */
            target_amount_rappen_baseline?: number | null;
            /** Target Amount Rappen New */
            target_amount_rappen_new?: number | null;
            /** Target Return Bps Baseline */
            target_return_bps_baseline?: number | null;
            /** Target Return Bps New */
            target_return_bps_new?: number | null;
            /** Wealth Basis */
            wealth_basis?: string | null;
            /** Weights Bps Baseline */
            weights_bps_baseline: {
                [key: string]: number;
            };
            /** Weights Bps New */
            weights_bps_new: {
                [key: string]: number;
            };
        };
        /** AllocationSimulationEventResponse */
        AllocationSimulationEventResponse: {
            /** Breached Buckets */
            breached_buckets: string[];
            /** Mode */
            mode: string;
            /** Notes */
            notes: string;
            /** Turnover Rappen */
            turnover_rappen: number;
            /** Year */
            year: number;
        };
        /** AllocationSimulationResponse */
        AllocationSimulationResponse: {
            /** Current Mix Series Rappen */
            current_mix_series_rappen: number[];
            /** Downside Series Rappen */
            downside_series_rappen: number[];
            /** External Reserve Balance Series Rappen */
            external_reserve_balance_series_rappen?: number[];
            /** Horizon Years */
            horizon_years: number;
            /** Inflation Series Bps */
            inflation_series_bps: number[];
            /** Real Target Series Rappen */
            real_target_series_rappen: number[];
            /** Rebalance Mode */
            rebalance_mode: string;
            /** Rebalancing Events */
            rebalancing_events: components["schemas"]["AllocationSimulationEventResponse"][];
            /** Reserve Accounting Basis */
            reserve_accounting_basis?: string | null;
            /** Start Year */
            start_year: number;
            /** Stress Multiplier */
            stress_multiplier: number;
            /** Target Mix Series Rappen */
            target_mix_series_rappen: number[];
            /** Upside Series Rappen */
            upside_series_rappen: number[];
            /** Year Labels */
            year_labels: number[];
        };
        /** AllocationSubBucketResponse */
        AllocationSubBucketResponse: {
            /** Asset Class */
            asset_class: string;
            /** Rationale */
            rationale: string;
            /** Risky Fraction Bps */
            risky_fraction_bps?: number | null;
            /** Sub Asset Class */
            sub_asset_class: string;
            /** Target Weight Bps */
            target_weight_bps: number;
            /** Within Bucket Weight Bps */
            within_bucket_weight_bps?: number | null;
        };
        /** AssetClassAssumptionResponse */
        AssetClassAssumptionResponse: {
            /** Asset Class */
            asset_class: string;
            /** Current Weight Bps */
            current_weight_bps: number;
            /** Expected Return Bps */
            expected_return_bps: number;
            /** Expected Volatility Bps */
            expected_volatility_bps: number;
            /** Liquidity Profile */
            liquidity_profile: string;
            /** Market Data Role */
            market_data_role: string;
            /** Risky Fraction Bps */
            risky_fraction_bps: number;
            /** Target Weight Bps */
            target_weight_bps: number;
        };
        /** AuditLogEntry */
        AuditLogEntry: {
            /** Action */
            action: string;
            /** Client Id */
            client_id?: string | null;
            /** Created At */
            created_at: string;
            /** Field Name */
            field_name?: string | null;
            /** Id */
            id: string;
            /** Integrity Hash */
            integrity_hash?: string | null;
            /** Mandate Id */
            mandate_id?: string | null;
            /** New Value */
            new_value?: string | null;
            /** Old Value */
            old_value?: string | null;
            /** Record Id */
            record_id: string;
            /** Table Name */
            table_name: string;
            /** User Id */
            user_id?: string | null;
            /** User Name */
            user_name: string;
        };
        /** AuditLogPage */
        AuditLogPage: {
            /** Entries */
            entries: components["schemas"]["AuditLogEntry"][];
            /** Limit */
            limit: number;
            /** Offset */
            offset: number;
            /** Total */
            total: number;
        };
        /** BausteinCreate */
        BausteinCreate: {
            /** Category */
            category?: string | null;
            /**
             * Content Md
             * @default
             */
            content_md?: string;
            /**
             * Sort Order
             * @default 0
             */
            sort_order?: number;
            /** Title */
            title: string;
        };
        /** BausteinResponse */
        BausteinResponse: {
            /** Advisor Id */
            advisor_id: string | null;
            /** Category */
            category: string | null;
            /** Content Md */
            content_md: string;
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /** Is Active */
            is_active: number;
            /** Sort Order */
            sort_order: number;
            /** Tenant Id */
            tenant_id: string | null;
            /** Title */
            title: string;
            /** Updated At */
            updated_at: string;
        };
        /** BausteinUpdate */
        BausteinUpdate: {
            /** Category */
            category?: string | null;
            /** Content Md */
            content_md?: string | null;
            /** Is Active */
            is_active?: number | null;
            /** Sort Order */
            sort_order?: number | null;
            /** Title */
            title?: string | null;
        };
        /** Body_import_products_csv_products_import_csv_post */
        Body_import_products_csv_products_import_csv_post: {
            /** File */
            file: string;
        };
        /** BootstrapAdminRequest */
        BootstrapAdminRequest: {
            /** Company Name */
            company_name?: string | null;
            /** Default Presentation Mode */
            default_presentation_mode?: string | null;
            /** Email */
            email?: string | null;
            /** Full Name */
            full_name: string;
            /** Home Jurisdiction */
            home_jurisdiction?: string | null;
            /** Password */
            password: string;
            /** Username */
            username: string;
        };
        /** BootstrapStatusResponse */
        BootstrapStatusResponse: {
            /** Can Create Admin */
            can_create_admin: boolean;
            /** Setup Required */
            setup_required: boolean;
        };
        /** BuildingBlockResponse */
        BuildingBlockResponse: {
            /** Advisory */
            advisory: number;
            /** Asset Class */
            asset_class: string;
            /** Contribution Alternative Bps */
            contribution_alternative_bps: number | null;
            /** Contribution Standard Bps */
            contribution_standard_bps: number | null;
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /** Is Active */
            is_active: number;
            /** Jurisdiction */
            jurisdiction?: string | null;
            /** Policy Id */
            policy_id: string;
            /** Risky Fraction Bps */
            risky_fraction_bps: number;
            /** Sub Asset Class */
            sub_asset_class: string;
            /** Universe */
            universe: string;
            /** Updated At */
            updated_at: string;
        };
        /**
         * CalendarFeedTokenResponse
         * @description REVIEW-CALENDAR-001: Klartext-Token wird NUR in dieser Antwort
         *     zurueckgegeben (analog Passwort-Reset-Token) -- danach ist nur noch der
         *     Hash gespeichert.
         */
        CalendarFeedTokenResponse: {
            /** Feed Path */
            feed_path: string;
            /** Token */
            token: string;
        };
        /** CapitalMarketAssumptionCreate */
        CapitalMarketAssumptionCreate: {
            /** Alternatives Excess Kurt Bps */
            alternatives_excess_kurt_bps?: number | null;
            /** Alternatives Gold Return Bps */
            alternatives_gold_return_bps?: number | null;
            /** Alternatives Gold Vol Bps */
            alternatives_gold_vol_bps?: number | null;
            /** Alternatives Risk Premium Bps */
            alternatives_risk_premium_bps?: number | null;
            /** Alternatives Skewness Bps */
            alternatives_skewness_bps?: number | null;
            /**
             * Assumption Set Name
             * @default Standard
             */
            assumption_set_name?: string;
            /** Bonds Chf Ig Return Bps */
            bonds_chf_ig_return_bps?: number | null;
            /** Bonds Chf Ig Vol Bps */
            bonds_chf_ig_vol_bps?: number | null;
            /** Bonds Excess Kurt Bps */
            bonds_excess_kurt_bps?: number | null;
            /** Bonds Fx Hedged Return Bps */
            bonds_fx_hedged_return_bps?: number | null;
            /** Bonds Fx Hedged Vol Bps */
            bonds_fx_hedged_vol_bps?: number | null;
            /** Bonds Home Ig Return Bps */
            bonds_home_ig_return_bps?: number | null;
            /** Bonds Home Ig Vol Bps */
            bonds_home_ig_vol_bps?: number | null;
            /** Bonds Hy Return Bps */
            bonds_hy_return_bps?: number | null;
            /** Bonds Hy Vol Bps */
            bonds_hy_vol_bps?: number | null;
            /** Bonds Ns Beta0 Bps */
            bonds_ns_beta0_bps?: number | null;
            /** Bonds Ns Beta1 Bps */
            bonds_ns_beta1_bps?: number | null;
            /** Bonds Ns Beta2 Bps */
            bonds_ns_beta2_bps?: number | null;
            /** Bonds Ns Lambda X100 */
            bonds_ns_lambda_x100?: number | null;
            /** Bonds Skewness Bps */
            bonds_skewness_bps?: number | null;
            /** Computed At */
            computed_at?: string | null;
            /** Computed By */
            computed_by?: string | null;
            /** Correlation Matrix Json */
            correlation_matrix_json?: string | null;
            /** Equities Excess Kurt Bps */
            equities_excess_kurt_bps?: number | null;
            /** Equities Skewness Bps */
            equities_skewness_bps?: number | null;
            /** Equity Ch Return Bps */
            equity_ch_return_bps?: number | null;
            /** Equity Ch Vol Bps */
            equity_ch_vol_bps?: number | null;
            /** Equity Em Return Bps */
            equity_em_return_bps?: number | null;
            /** Equity Em Vol Bps */
            equity_em_vol_bps?: number | null;
            /** Equity Home Return Bps */
            equity_home_return_bps?: number | null;
            /** Equity Home Vol Bps */
            equity_home_vol_bps?: number | null;
            /** Equity Intl Return Bps */
            equity_intl_return_bps?: number | null;
            /** Equity Intl Vol Bps */
            equity_intl_vol_bps?: number | null;
            /** Equity Kgv Alpha X100 */
            equity_kgv_alpha_x100?: number | null;
            /** Equity Kgv Current X10 */
            equity_kgv_current_x10?: number | null;
            /** Equity Kgv Fair X10 */
            equity_kgv_fair_x10?: number | null;
            /** Inflation Path Json */
            inflation_path_json?: string | null;
            /** Liquidity Excess Kurt Bps */
            liquidity_excess_kurt_bps?: number | null;
            /** Liquidity Return Bps */
            liquidity_return_bps?: number | null;
            /** Liquidity Skewness Bps */
            liquidity_skewness_bps?: number | null;
            /** Liquidity Vol Bps */
            liquidity_vol_bps?: number | null;
            /** Notes */
            notes?: string | null;
            /** Real Estate Ch Return Bps */
            real_estate_ch_return_bps?: number | null;
            /** Real Estate Ch Vol Bps */
            real_estate_ch_vol_bps?: number | null;
            /** Real Estate Excess Kurt Bps */
            real_estate_excess_kurt_bps?: number | null;
            /** Real Estate Home Return Bps */
            real_estate_home_return_bps?: number | null;
            /** Real Estate Home Vol Bps */
            real_estate_home_vol_bps?: number | null;
            /** Real Estate Risk Premium Bps */
            real_estate_risk_premium_bps?: number | null;
            /** Real Estate Skewness Bps */
            real_estate_skewness_bps?: number | null;
            /**
             * Source
             * @default Portfolio Management intern
             */
            source?: string | null;
            /** Source Date */
            source_date?: string | null;
            /** Source Detail */
            source_detail?: string | null;
            /** Status */
            status?: ("provisional" | "data_derived" | "committee_approved") | null;
            /** Sub Asset Class Assumptions Json */
            sub_asset_class_assumptions_json?: string | null;
            /** Valid From */
            valid_from: string;
            /** Valid Until */
            valid_until?: string | null;
        };
        /** CapitalMarketAssumptionResponse */
        CapitalMarketAssumptionResponse: {
            /** Alternatives Excess Kurt Bps */
            alternatives_excess_kurt_bps?: number | null;
            /** Alternatives Gold Return Bps */
            alternatives_gold_return_bps: number | null;
            /** Alternatives Gold Vol Bps */
            alternatives_gold_vol_bps: number | null;
            /** Alternatives Risk Premium Bps */
            alternatives_risk_premium_bps?: number | null;
            /** Alternatives Skewness Bps */
            alternatives_skewness_bps?: number | null;
            /** Assumption Set Name */
            assumption_set_name: string;
            /** Bonds Chf Ig Return Bps */
            bonds_chf_ig_return_bps: number | null;
            /** Bonds Chf Ig Vol Bps */
            bonds_chf_ig_vol_bps: number | null;
            /** Bonds Excess Kurt Bps */
            bonds_excess_kurt_bps?: number | null;
            /** Bonds Fx Hedged Return Bps */
            bonds_fx_hedged_return_bps: number | null;
            /** Bonds Fx Hedged Vol Bps */
            bonds_fx_hedged_vol_bps: number | null;
            /** Bonds Home Ig Return Bps */
            bonds_home_ig_return_bps?: number | null;
            /** Bonds Home Ig Vol Bps */
            bonds_home_ig_vol_bps?: number | null;
            /** Bonds Hy Return Bps */
            bonds_hy_return_bps: number | null;
            /** Bonds Hy Vol Bps */
            bonds_hy_vol_bps: number | null;
            /** Bonds Ns Beta0 Bps */
            bonds_ns_beta0_bps?: number | null;
            /** Bonds Ns Beta1 Bps */
            bonds_ns_beta1_bps?: number | null;
            /** Bonds Ns Beta2 Bps */
            bonds_ns_beta2_bps?: number | null;
            /** Bonds Ns Lambda X100 */
            bonds_ns_lambda_x100?: number | null;
            /** Bonds Skewness Bps */
            bonds_skewness_bps?: number | null;
            /** Computed At */
            computed_at?: string | null;
            /** Computed By */
            computed_by?: string | null;
            /** Correlation Matrix Json */
            correlation_matrix_json: string | null;
            /** Created At */
            created_at: string;
            /** Equities Excess Kurt Bps */
            equities_excess_kurt_bps?: number | null;
            /** Equities Skewness Bps */
            equities_skewness_bps?: number | null;
            /** Equity Ch Return Bps */
            equity_ch_return_bps: number | null;
            /** Equity Ch Vol Bps */
            equity_ch_vol_bps: number | null;
            /** Equity Em Return Bps */
            equity_em_return_bps: number | null;
            /** Equity Em Vol Bps */
            equity_em_vol_bps: number | null;
            /** Equity Home Return Bps */
            equity_home_return_bps?: number | null;
            /** Equity Home Vol Bps */
            equity_home_vol_bps?: number | null;
            /** Equity Intl Return Bps */
            equity_intl_return_bps: number | null;
            /** Equity Intl Vol Bps */
            equity_intl_vol_bps: number | null;
            /** Equity Kgv Alpha X100 */
            equity_kgv_alpha_x100?: number | null;
            /** Equity Kgv Current X10 */
            equity_kgv_current_x10?: number | null;
            /** Equity Kgv Fair X10 */
            equity_kgv_fair_x10?: number | null;
            /** Id */
            id: string;
            /** Inflation Path Json */
            inflation_path_json: string | null;
            /** Is Current */
            is_current: number;
            /** Jurisdiction */
            jurisdiction?: string | null;
            /** Liquidity Excess Kurt Bps */
            liquidity_excess_kurt_bps?: number | null;
            /** Liquidity Return Bps */
            liquidity_return_bps: number | null;
            /** Liquidity Skewness Bps */
            liquidity_skewness_bps?: number | null;
            /** Liquidity Vol Bps */
            liquidity_vol_bps: number | null;
            /** Notes */
            notes: string | null;
            /** Real Estate Ch Return Bps */
            real_estate_ch_return_bps: number | null;
            /** Real Estate Ch Vol Bps */
            real_estate_ch_vol_bps: number | null;
            /** Real Estate Excess Kurt Bps */
            real_estate_excess_kurt_bps?: number | null;
            /** Real Estate Home Return Bps */
            real_estate_home_return_bps?: number | null;
            /** Real Estate Home Vol Bps */
            real_estate_home_vol_bps?: number | null;
            /** Real Estate Risk Premium Bps */
            real_estate_risk_premium_bps?: number | null;
            /** Real Estate Skewness Bps */
            real_estate_skewness_bps?: number | null;
            /** Source */
            source: string | null;
            /** Source Date */
            source_date?: string | null;
            /** Source Detail */
            source_detail?: string | null;
            /** Status */
            status?: string | null;
            /** Sub Asset Class Assumptions Json */
            sub_asset_class_assumptions_json: string | null;
            /** Tenant Id */
            tenant_id?: string | null;
            /** Valid From */
            valid_from: string;
            /** Valid Until */
            valid_until: string | null;
            /** Version */
            version: number;
        };
        /** CashflowCreate */
        CashflowCreate: {
            /** Amount Rappen */
            amount_rappen: number;
            /**
             * Cashflow Type
             * @enum {string}
             */
            cashflow_type: "Income" | "Expense";
            /**
             * Currency
             * @default CHF
             */
            currency?: string;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /**
             * Frequency
             * @default jährlich
             */
            frequency?: string;
            /** Gross Amount Rappen */
            gross_amount_rappen?: number | null;
            /**
             * Is Inflation Linked
             * @default false
             */
            is_inflation_linked?: boolean;
            /** Label */
            label: string;
            /**
             * Nature
             * @default wiederkehrend
             * @enum {string}
             */
            nature?: "wiederkehrend" | "einmalig";
            /** Notes */
            notes?: string | null;
            /** Tax Amount Rappen */
            tax_amount_rappen?: number | null;
            /**
             * Timing Precision
             * @description Nur Dokumentationsangabe ('day'|'month') zum Referenzdatum eines einmaligen Cashflows -- KEINE Wirkung auf die Projektionsrechnung. Die Jahresprojektion verbucht den vollen Betrag im Kalenderjahr des Datums (WITHDRAWAL-TIMING-001).
             */
            timing_precision?: string | null;
            /** Valid From */
            valid_from?: string | null;
            /** Valid Until */
            valid_until?: string | null;
        };
        /** CashflowPensionTransfer */
        CashflowPensionTransfer: {
            /** Currency */
            currency: string;
            /** Gross Withdrawal Rappen */
            gross_withdrawal_rappen: number;
            /** Linked Inflow Id */
            linked_inflow_id?: string | null;
            /** Lumpsum Tax Rappen */
            lumpsum_tax_rappen: number;
            /** Net Advisory Inflow Rappen */
            net_advisory_inflow_rappen: number;
            /** Origin */
            origin: string;
            /** Pension Type */
            pension_type: string;
            /** Source Label */
            source_label: string;
            /** Source Position Id */
            source_position_id: string;
            /** Tax Source */
            tax_source: string;
            /** Year */
            year: number;
        };
        /** CashflowProjectionResponse */
        CashflowProjectionResponse: {
            /** Client Id */
            client_id: string;
            /** Pension Ledger Hash */
            pension_ledger_hash?: string | null;
            /**
             * Pension Transfers
             * @default []
             */
            pension_transfers?: components["schemas"]["CashflowPensionTransfer"][];
            /** Start Year */
            start_year: number;
            /** Years */
            years: components["schemas"]["CashflowYearRow"][];
        };
        /** CashflowResponse */
        CashflowResponse: {
            /** Amount Rappen */
            amount_rappen: number;
            /** Cashflow Type */
            cashflow_type: string;
            /** Client Id */
            client_id: string;
            /** Created At */
            created_at: string;
            /** Currency */
            currency: string;
            /** Frequency */
            frequency: string;
            /** Gross Amount Rappen */
            gross_amount_rappen: number | null;
            /** Id */
            id: string;
            /** Is Active */
            is_active: number;
            /** Is Included */
            is_included: number;
            /** Is Inflation Linked */
            is_inflation_linked: number;
            /** Label */
            label: string;
            /** Nature */
            nature: string;
            /** Notes */
            notes: string | null;
            /** Tax Amount Rappen */
            tax_amount_rappen: number | null;
            /**
             * Timing Precision
             * @description Nur Dokumentationsangabe ('day'|'month') zum Referenzdatum eines einmaligen Cashflows -- KEINE Wirkung auf die Projektionsrechnung. Die Jahresprojektion verbucht den vollen Betrag im Kalenderjahr des Datums (WITHDRAWAL-TIMING-001).
             */
            timing_precision: string | null;
            /** Updated At */
            updated_at: string;
            /** Valid From */
            valid_from: string | null;
            /** Valid Until */
            valid_until: string | null;
        };
        /** CashflowSummaryResponse */
        CashflowSummaryResponse: {
            /**
             * Capital Inflow Rappen
             * @default 0
             */
            capital_inflow_rappen?: number;
            /**
             * Capital Net Rappen
             * @default 0
             */
            capital_net_rappen?: number;
            /**
             * Capital Outflow Rappen
             * @default 0
             */
            capital_outflow_rappen?: number;
            /** Client Id */
            client_id: string;
            /** Client Name */
            client_name: string;
            /**
             * Recurring Expense Rappen
             * @default 0
             */
            recurring_expense_rappen?: number;
            /**
             * Recurring Income Rappen
             * @default 0
             */
            recurring_income_rappen?: number;
            /**
             * Recurring Net Rappen
             * @default 0
             */
            recurring_net_rappen?: number;
            /** Summary Year */
            summary_year: number;
            /** Surplus Chf */
            surplus_chf: number;
            /** Surplus Rappen */
            surplus_rappen: number;
            /** Total Expense Chf */
            total_expense_chf: number;
            /** Total Expense Rappen */
            total_expense_rappen: number;
            /** Total Income Chf */
            total_income_chf: number;
            /** Total Income Rappen */
            total_income_rappen: number;
        };
        /** CashflowUpdate */
        CashflowUpdate: {
            /** Amount Rappen */
            amount_rappen?: number | null;
            /** Cashflow Type */
            cashflow_type?: ("Income" | "Expense") | null;
            /** Currency */
            currency?: string | null;
            /** Data Classification */
            data_classification?: ("synthetic" | "real") | null;
            /** Frequency */
            frequency?: string | null;
            /** Gross Amount Rappen */
            gross_amount_rappen?: number | null;
            /** Is Active */
            is_active?: boolean | null;
            /** Is Included */
            is_included?: boolean | null;
            /** Is Inflation Linked */
            is_inflation_linked?: boolean | null;
            /** Label */
            label?: string | null;
            /** Nature */
            nature?: string | null;
            /** Notes */
            notes?: string | null;
            /** Tax Amount Rappen */
            tax_amount_rappen?: number | null;
            /**
             * Timing Precision
             * @description Nur Dokumentationsangabe ('day'|'month') zum Referenzdatum eines einmaligen Cashflows -- KEINE Wirkung auf die Projektionsrechnung. Die Jahresprojektion verbucht den vollen Betrag im Kalenderjahr des Datums (WITHDRAWAL-TIMING-001).
             */
            timing_precision?: string | null;
            /** Valid From */
            valid_from?: string | null;
            /** Valid Until */
            valid_until?: string | null;
        };
        /** CashflowYearRow */
        CashflowYearRow: {
            /**
             * Capital Inflow Rappen
             * @default 0
             */
            capital_inflow_rappen?: number;
            /**
             * Capital Outflow Rappen
             * @default 0
             */
            capital_outflow_rappen?: number;
            /** Expense Rappen */
            expense_rappen: number;
            /** Income Rappen */
            income_rappen: number;
            /** Net Rappen */
            net_rappen: number;
            /**
             * Pension Payout Rappen
             * @default 0
             */
            pension_payout_rappen?: number;
            /**
             * Recurring Expense Rappen
             * @default 0
             */
            recurring_expense_rappen?: number;
            /**
             * Recurring Income Rappen
             * @default 0
             */
            recurring_income_rappen?: number;
            /** Year */
            year: number;
        };
        /** ClientCreate */
        ClientCreate: {
            /** Advisor Id */
            advisor_id: string;
            /** Canton */
            canton?: string | null;
            /** Civil Status */
            civil_status?: string | null;
            /**
             * Client Classification
             * @default Privatkunde
             * @enum {string}
             */
            client_classification?: "Privatkunde" | "Professioneller Kunde" | "Institutioneller Kunde";
            /** Client Number */
            client_number: string;
            /**
             * Country Of Residence
             * @default CH
             */
            country_of_residence?: string;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Date Of Birth */
            date_of_birth?: string | null;
            /** Employer */
            employer?: string | null;
            /** First Name */
            first_name: string;
            /**
             * Household Type
             * @default Einzelperson
             * @enum {string}
             */
            household_type?: "Einzelperson" | "Paar" | "Familie";
            /** Investment Horizon End */
            investment_horizon_end?: string | null;
            /** Investment Horizon Start */
            investment_horizon_start?: string | null;
            /**
             * Is Professional Opt Out
             * @default false
             */
            is_professional_opt_out?: boolean;
            /**
             * Is Qualified Investor
             * @default false
             */
            is_qualified_investor?: boolean;
            /**
             * Language
             * @default DE
             * @enum {string}
             */
            language?: "DE" | "FR" | "IT" | "EN";
            /** Last Name */
            last_name: string;
            /** Notes */
            notes?: string | null;
            /** Partner Date Of Birth */
            partner_date_of_birth?: string | null;
            /** Partner First Name */
            partner_first_name?: string | null;
            /** Partner Last Name */
            partner_last_name?: string | null;
            /** Partner Profession */
            partner_profession?: string | null;
            /** Partner Salutation */
            partner_salutation?: string | null;
            /** Profession */
            profession?: string | null;
            /** Salutation */
            salutation?: ("Herr" | "Frau" | "Divers") | null;
        };
        /** ClientDueDiligenceResponse */
        ClientDueDiligenceResponse: {
            /** Acting For Own Account */
            acting_for_own_account: number;
            /** Beneficial Owner Name */
            beneficial_owner_name: string | null;
            /** Client Id */
            client_id: string;
            /** Created At */
            created_at: string;
            /** Fatca Crs Self Certified */
            fatca_crs_self_certified: number;
            /** Id */
            id: string;
            /** Id Document Expiry */
            id_document_expiry: string | null;
            /** Id Document Issuing Country */
            id_document_issuing_country: string | null;
            /** Id Document Number */
            id_document_number: string | null;
            /** Id Document Type */
            id_document_type: string | null;
            /** Pep Details */
            pep_details: string | null;
            /** Pep Status */
            pep_status: number;
            /** Source Of Wealth */
            source_of_wealth: string | null;
            /** Updated At */
            updated_at: string;
        };
        /** ClientDueDiligenceUpdate */
        ClientDueDiligenceUpdate: {
            /**
             * Acting For Own Account
             * @default true
             */
            acting_for_own_account?: boolean;
            /** Beneficial Owner Name */
            beneficial_owner_name?: string | null;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /**
             * Fatca Crs Self Certified
             * @default false
             */
            fatca_crs_self_certified?: boolean;
            /** Id Document Expiry */
            id_document_expiry?: string | null;
            /** Id Document Issuing Country */
            id_document_issuing_country?: string | null;
            /** Id Document Number */
            id_document_number?: string | null;
            /** Id Document Type */
            id_document_type?: string | null;
            /** Pep Details */
            pep_details?: string | null;
            /**
             * Pep Status
             * @default false
             */
            pep_status?: boolean;
            /** Source Of Wealth */
            source_of_wealth?: string | null;
        };
        /**
         * ClientErasureRequest
         * @description DSG Art. 32 -- Pflichtbegruendung fuer eine Loeschungs-/Erasure-
         *     Anfrage. Wiederverwendet dieselbe Qualitaets-Pruefung wie
         *     Risikoprofil-Overrides (min. 20 Zeichen, keine Floskel, >=3
         *     bedeutungsvolle Worte) -- eine so folgenreiche, irreversible Aktion
         *     verdient dieselbe FIDLEG-Audit-Tauglichkeit wie ein Profil-Override.
         */
        ClientErasureRequest: {
            /** Reason */
            reason: string;
        };
        /** ClientErasureResponse */
        ClientErasureResponse: {
            /** Client Id */
            client_id: string;
            /** Erased At */
            erased_at: string;
            /** Mandate Ids */
            mandate_ids: string[];
            /**
             * Pii Keys Shredded
             * @default 0
             */
            pii_keys_shredded?: number;
            /** Redacted */
            redacted: {
                [key: string]: number;
            };
            /** Status */
            status: string;
            /**
             * Unsealed Append Only Rows
             * @default {}
             */
            unsealed_append_only_rows?: {
                [key: string]: number;
            };
        };
        /** ClientResponse */
        ClientResponse: {
            /** Advisor Id */
            advisor_id: string;
            /** Canton */
            canton: string | null;
            /** Civil Status */
            civil_status: string | null;
            /** Client Classification */
            client_classification: string;
            /** Client Number */
            client_number: string;
            /** Country Of Residence */
            country_of_residence: string;
            /** Created At */
            created_at: string;
            /** Date Of Birth */
            date_of_birth: string | null;
            /** Employer */
            employer: string | null;
            /** First Name */
            first_name: string;
            /** Household Type */
            household_type: string;
            /** Id */
            id: string;
            /** Investment Horizon End */
            investment_horizon_end: string | null;
            /** Investment Horizon Start */
            investment_horizon_start: string | null;
            /** Is Professional Opt Out */
            is_professional_opt_out: number;
            /** Is Qualified Investor */
            is_qualified_investor: number;
            /** Language */
            language: string;
            /** Last Name */
            last_name: string;
            /** Notes */
            notes: string | null;
            /** Partner Date Of Birth */
            partner_date_of_birth: string | null;
            /** Partner First Name */
            partner_first_name: string | null;
            /** Partner Last Name */
            partner_last_name: string | null;
            /** Partner Profession */
            partner_profession: string | null;
            /** Partner Salutation */
            partner_salutation: string | null;
            /** Profession */
            profession: string | null;
            /** Salutation */
            salutation: string | null;
            /** Updated At */
            updated_at: string;
        };
        /** ClientTaxResidencyCreate */
        ClientTaxResidencyCreate: {
            /** Country Code */
            country_code: string;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /**
             * Is Primary
             * @default false
             */
            is_primary?: boolean;
            /** Tax Id Number */
            tax_id_number?: string | null;
        };
        /** ClientTaxResidencyResponse */
        ClientTaxResidencyResponse: {
            /** Client Id */
            client_id: string;
            /** Country Code */
            country_code: string;
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /** Is Primary */
            is_primary: number;
            /** Tax Id Number */
            tax_id_number: string | null;
        };
        /** ClientUpdate */
        ClientUpdate: {
            /** Advisor Id */
            advisor_id?: string | null;
            /** Canton */
            canton?: string | null;
            /** Civil Status */
            civil_status?: string | null;
            /** Country Of Residence */
            country_of_residence?: string | null;
            /** Data Classification */
            data_classification?: ("synthetic" | "real") | null;
            /** Date Of Birth */
            date_of_birth?: string | null;
            /** Employer */
            employer?: string | null;
            /** First Name */
            first_name?: string | null;
            /** Household Type */
            household_type?: ("Einzelperson" | "Paar" | "Familie") | null;
            /** Investment Horizon End */
            investment_horizon_end?: string | null;
            /** Investment Horizon Start */
            investment_horizon_start?: string | null;
            /** Language */
            language?: ("DE" | "FR" | "IT" | "EN") | null;
            /** Last Name */
            last_name?: string | null;
            /** Notes */
            notes?: string | null;
            /** Partner Date Of Birth */
            partner_date_of_birth?: string | null;
            /** Partner First Name */
            partner_first_name?: string | null;
            /** Partner Last Name */
            partner_last_name?: string | null;
            /** Partner Profession */
            partner_profession?: string | null;
            /** Partner Salutation */
            partner_salutation?: string | null;
            /** Profession */
            profession?: string | null;
            /** Salutation */
            salutation?: ("Herr" | "Frau" | "Divers") | null;
        };
        /** CmaPolicyApprovalOut */
        CmaPolicyApprovalOut: {
            /** Approved At */
            approved_at: string;
            /** Approver Id */
            approver_id: string;
            /** Content Hash */
            content_hash: string;
            /** Id */
            id: string;
            /** Rationale */
            rationale: string;
        };
        /** CmaPolicyComponentIn */
        CmaPolicyComponentIn: {
            /** Asset Key */
            asset_key: string;
            /** Component */
            component: string;
            /** Confidence */
            confidence?: string | null;
            /** Horizon Years */
            horizon_years: number;
            /** Method */
            method: string;
            /** Range Max Bps */
            range_max_bps: number;
            /** Range Min Bps */
            range_min_bps: number;
            /** Sign */
            sign: string;
            /** Source */
            source: string;
            /**
             * Unit
             * @default bps_pa
             */
            unit?: string;
            /** Value Bps */
            value_bps: number;
        };
        /** CmaPolicyComponentOut */
        CmaPolicyComponentOut: {
            /** Asset Key */
            asset_key: string;
            /** Component */
            component: string;
            /** Confidence */
            confidence?: string | null;
            /** Horizon Years */
            horizon_years: number;
            /** Id */
            id: string;
            /** Method */
            method: string;
            /** Range Max Bps */
            range_max_bps: number;
            /** Range Min Bps */
            range_min_bps: number;
            /** Sign */
            sign: string;
            /** Source */
            source: string;
            /**
             * Unit
             * @default bps_pa
             */
            unit?: string;
            /** Value Bps */
            value_bps: number;
        };
        /** CmaPolicyComponentsReplace */
        CmaPolicyComponentsReplace: {
            /** Components */
            components: components["schemas"]["CmaPolicyComponentIn"][];
        };
        /** CmaPolicyCreate */
        CmaPolicyCreate: {
            /** Base Currency */
            base_currency?: string | null;
            /** Capital Market Assumptions Id */
            capital_market_assumptions_id: string;
            /** Components */
            components?: components["schemas"]["CmaPolicyComponentIn"][];
            /** Correlation Policy Ref */
            correlation_policy_ref?: string | null;
            /** Data As Of */
            data_as_of?: string | null;
            /** Exception Rule */
            exception_rule?: string | null;
            /** Expiry Rule */
            expiry_rule?: string | null;
            /** Fee Basis */
            fee_basis?: string | null;
            /** Impact Report Ref */
            impact_report_ref?: string | null;
            /** Method Version */
            method_version?: string | null;
            /** Policy Id */
            policy_id: string;
            /** Rationale */
            rationale?: string | null;
            /** Return Basis */
            return_basis?: string | null;
            /** Rollback Rule */
            rollback_rule?: string | null;
            /** Sources */
            sources?: Record<string, unknown>[];
            /** Supersedes Id */
            supersedes_id?: string | null;
            /** Valid From */
            valid_from?: string | null;
            /** Valid Until */
            valid_until?: string | null;
        };
        /** CmaPolicyDecision */
        CmaPolicyDecision: {
            /** Rationale */
            rationale: string;
        };
        /** CmaPolicyModelStatus */
        CmaPolicyModelStatus: {
            /** Enforced */
            enforced: boolean;
            /** Explanation */
            explanation: string;
        };
        /** CmaPolicyOut */
        CmaPolicyOut: {
            /** Activated At */
            activated_at?: string | null;
            /** Activated By */
            activated_by?: string | null;
            /** Approvals */
            approvals?: components["schemas"]["CmaPolicyApprovalOut"][];
            /** Approved At */
            approved_at?: string | null;
            /** Base Currency */
            base_currency?: string | null;
            /** Capital Market Assumptions Id */
            capital_market_assumptions_id: string;
            /** Components */
            components?: components["schemas"]["CmaPolicyComponentOut"][];
            /** Content Hash */
            content_hash?: string | null;
            /** Correlation Policy Ref */
            correlation_policy_ref?: string | null;
            /** Created At */
            created_at: string;
            /** Created By */
            created_by: string;
            /** Data As Of */
            data_as_of?: string | null;
            /** Exception Rule */
            exception_rule?: string | null;
            /** Expiry Rule */
            expiry_rule?: string | null;
            /** Fee Basis */
            fee_basis?: string | null;
            /** Id */
            id: string;
            /** Impact Report Ref */
            impact_report_ref?: string | null;
            /** Method Version */
            method_version?: string | null;
            /** Policy Id */
            policy_id: string;
            /** Rationale */
            rationale?: string | null;
            /** Retired At */
            retired_at?: string | null;
            /** Return Basis */
            return_basis?: string | null;
            /** Revocation Reason */
            revocation_reason?: string | null;
            /** Revoked At */
            revoked_at?: string | null;
            /** Revoked By */
            revoked_by?: string | null;
            /** Rollback Rule */
            rollback_rule?: string | null;
            /** Sources Json */
            sources_json?: string | null;
            /** Status */
            status: string;
            /** Supersedes Id */
            supersedes_id?: string | null;
            /** Valid From */
            valid_from?: string | null;
            /** Valid Until */
            valid_until?: string | null;
            /** Validated At */
            validated_at?: string | null;
            /** Validated By */
            validated_by?: string | null;
            /** Version */
            version: number;
        };
        /**
         * ConflictAcknowledgeRequest
         * @description Die Kenntnisnahme des Kunden protokollieren.
         */
        ConflictAcknowledgeRequest: {
            /**
             * Acknowledged At
             * @description Zeitpunkt der Kenntnisnahme (ISO). Ohne Angabe die Serverzeit.
             */
            acknowledged_at?: string | null;
        };
        /**
         * ConflictAttachDocumentRequest
         * @description Das Offenlegungsdokument nachtraeglich ablegen.
         */
        ConflictAttachDocumentRequest: {
            /**
             * Document Id
             * @description Referenz auf das abgelegte Offenlegungsdokument. Ein bereits abgelegtes wird nicht ersetzt -- die Referenz ist Teil des Nachweises.
             */
            document_id: string;
        };
        /**
         * ConflictDiscloseRequest
         * @description Die Offenlegung an den Kunden protokollieren.
         */
        ConflictDiscloseRequest: {
            /**
             * Disclosed At
             * @description Zeitpunkt der tatsaechlichen Offenlegung (ISO). Ohne Angabe die Serverzeit. Darf nicht in der Zukunft liegen und nicht vor der Erfassung des Konflikts -- ein Gespraech von gestern nachzutragen ist legitim, ein Datum zu erfinden nicht.
             */
            disclosed_at?: string | null;
            /**
             * Document Id
             * @description Das abgelegte Offenlegungsdokument. Optional, weil es beim Protokollieren noch fehlen kann -- der Konflikt bleibt dann `evidence_incomplete` statt `resolved`, statt die Offenlegung ganz zu verweigern.
             */
            document_id?: string | null;
        };
        /** ConflictDisclosureCreate */
        ConflictDisclosureCreate: {
            /**
             * Conflict Type
             * @enum {string}
             */
            conflict_type: "Retrozession / Inducement" | "Eigenhandel / Eigenbestand" | "Konzernverbindung" | "Persönliches Interesse Berater" | "Sonstiger Interessenkonflikt";
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Description */
            description: string;
            /** Document Id */
            document_id?: string | null;
            /** Inducement Amount Rappen */
            inducement_amount_rappen?: number | null;
            /** Inducement Frequency */
            inducement_frequency?: string | null;
            /** Inducement Provider */
            inducement_provider?: string | null;
            /** Mitigation Action */
            mitigation_action?: string | null;
            /** Reimbursed To Client */
            reimbursed_to_client?: boolean | null;
            /** Waiver Document Id */
            waiver_document_id?: string | null;
        };
        /** ConflictDisclosureResponse */
        ConflictDisclosureResponse: {
            /** Client Acknowledged */
            client_acknowledged: number;
            /** Client Acknowledged At */
            client_acknowledged_at?: string | null;
            /** Conflict Type */
            conflict_type: string;
            /** Created At */
            created_at: string;
            /** Description */
            description: string;
            /** Disclosed At */
            disclosed_at: string | null;
            /** Disclosed By */
            disclosed_by: string;
            /** Disclosed To Client */
            disclosed_to_client: number;
            /** Document Id */
            document_id?: string | null;
            /** Id */
            id: string;
            /** Inducement Amount Rappen */
            inducement_amount_rappen: number | null;
            /** Inducement Frequency */
            inducement_frequency?: string | null;
            /** Inducement Provider */
            inducement_provider: string | null;
            /** Mandate Id */
            mandate_id: string;
            /** Missing Evidence */
            missing_evidence?: string[];
            /** Mitigation Action */
            mitigation_action: string | null;
            /**
             * Reimbursed To Client
             * @default 0
             */
            reimbursed_to_client?: number;
            /** Resolution State */
            resolution_state?: string | null;
            /** Updated At */
            updated_at: string;
            /** Waiver Document Id */
            waiver_document_id?: string | null;
        };
        /**
         * ConflictMitigateRequest
         * @description Die getroffene Massnahme protokollieren (FIDLEG Art. 25/26).
         */
        ConflictMitigateRequest: {
            /**
             * Mitigation Action
             * @description Was konkret getan wurde. Mindestlaenge, damit kein leerer Platzhalter als Massnahme durchgeht.
             */
            mitigation_action: string;
        };
        /** ContractDocumentCreate */
        ContractDocumentCreate: {
            /** Content Json */
            content_json?: string | null;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /**
             * Document Type
             * @enum {string}
             */
            document_type: "Beratungsvertrag" | "Anlagestrategie" | "Anlagerezept" | "Beratungsprotokoll" | "Risikoprofilierung" | "Override-Zustimmung" | "Eignungsprüfung" | "Sonstiges" | "Kostenausweis";
            /** Title */
            title: string;
        };
        /** ContractDocumentResponse */
        ContractDocumentResponse: {
            /** Checksum Sha256 */
            checksum_sha256: string | null;
            /** Created At */
            created_at: string;
            /** Created By */
            created_by: string;
            /** Created By Name */
            created_by_name?: string | null;
            /** Document Type */
            document_type: string;
            /**
             * Has Pdf
             * @default false
             */
            has_pdf?: boolean;
            /** Id */
            id: string;
            /** Mandate Id */
            mandate_id: string;
            /** Pdf Path */
            pdf_path: string | null;
            /** Signature Advisor Image */
            signature_advisor_image?: string | null;
            /** Signature Advisor Signed At */
            signature_advisor_signed_at?: string | null;
            /** Signature Advisor Signer Name */
            signature_advisor_signer_name?: string | null;
            /** Signature Client Image */
            signature_client_image?: string | null;
            /** Signature Client Signed At */
            signature_client_signed_at?: string | null;
            /** Signature Client Signer Name */
            signature_client_signer_name?: string | null;
            /** Signed At */
            signed_at: string | null;
            /** Signed By Advisor */
            signed_by_advisor: number;
            /** Signed By Client */
            signed_by_client: number;
            /** Status */
            status: string;
            /** Supersedes Id */
            supersedes_id: string | null;
            /** Title */
            title: string;
            /** Updated At */
            updated_at: string;
            /** Version */
            version: number;
        };
        /**
         * ContractDocumentSign
         * @description 2026-08-05 (User-Direktive, E-Signing): signed_by_advisor/client waren
         *     reine Checkbox-Flags ohne echte Signatur. signature_image + signer_name
         *     sind jetzt Pflicht -- ein Aufruf signiert GENAU EINEN Unterzeichner
         *     (Berater ODER Kunde), weil jeder sein eigenes Signatur-Bild hat; beide in
         *     einem Aufruf waere nicht eindeutig zuordenbar.
         */
        ContractDocumentSign: {
            /** Signature Image */
            signature_image: string;
            /**
             * Signed By Advisor
             * @default false
             */
            signed_by_advisor?: boolean;
            /**
             * Signed By Client
             * @default false
             */
            signed_by_client?: boolean;
            /** Signer Name */
            signer_name: string;
        };
        /**
         * CostDisclosureResponse
         * @description Ex-ante Kostenausweis-Payload, FIDLEG-konform.
         *
         *     data_pending=True wenn fuer das Mandat noch keine Empfehlung vorliegt;
         *     cost_items ist dann leer, warnings beschreibt den Grund.
         */
        CostDisclosureResponse: {
            /**
             * Advisory Wealth Rappen
             * @default 0
             */
            advisory_wealth_rappen?: number;
            /** As Of */
            as_of?: string | null;
            /**
             * Audit Degraded
             * @description True, wenn der Ausweis nicht belastbar ist (ungueltiger Nachweis oder fehlgeschlagene Berechnung) -- nie client-ready.
             * @default false
             */
            audit_degraded?: boolean;
            /**
             * Content Hash
             * @description SHA-256 ueber den kanonisierten Payload, nur bei `evidence_frozen=True`. Beim Lesen nachgerechnet; stimmt er nicht, wird der Snapshot verworfen statt ausgeliefert.
             */
            content_hash?: string | null;
            /** Cost Items */
            cost_items?: components["schemas"]["CostItem"][];
            /**
             * Currency
             * @default CHF
             */
            currency?: string;
            /** Data Pending */
            data_pending: boolean;
            /**
             * Evidence Error
             * @description Maschinenlesbarer Grund bei `evidence_status='blocked'`: snapshot_malformed | snapshot_schema_unsupported | snapshot_run_mismatch | snapshot_context_mismatch | snapshot_hash_mismatch.
             */
            evidence_error?: string | null;
            /**
             * Evidence Frozen
             * @description True, wenn dieser Ausweis der bei der FINALISIERUNG eingefrorene Nachweis des Laufs ist und damit reproduzierbar. False heisst live gerechnet -- fuer Entwuerfe erwartet, bei einem freigegebenen Lauf ein Hinweis in `warnings` (COST-CONTEXT-001b).
             * @default false
             */
            evidence_frozen?: boolean;
            /**
             * Evidence Status
             * @description Diskriminierter Nachweis-Status (COST-SNAPSHOT-BINDING-001): 'certified' = eingefrorener, an Lauf/Version/Hash gebundener Nachweis; 'preview' = Entwurf, live; 'legacy_unverified' = freigegebener Lauf ohne Snapshot, live; 'blocked' = Snapshot vorhanden, aber ungueltig (keine Zahlen, siehe `evidence_error`); 'pending' = keine Empfehlung/Kostenbasis.
             */
            evidence_status?: ("certified" | "preview" | "legacy_unverified" | "blocked" | "pending") | null;
            /** Fidleg Basis */
            fidleg_basis: string;
            /**
             * Frozen At
             * @description Zeitpunkt des Einfrierens (ISO), nur bei `evidence_frozen=True`.
             */
            frozen_at?: string | null;
            /**
             * Has Estimates
             * @default false
             */
            has_estimates?: boolean;
            /**
             * Invested Amount Rappen
             * @default 0
             */
            invested_amount_rappen?: number;
            /**
             * Is Complete
             * @default false
             */
            is_complete?: boolean;
            /**
             * Product Cost Coverage Bps
             * @default 0
             */
            product_cost_coverage_bps?: number;
            /**
             * Snapshot Schema Version
             * @description Schema-Version des verifizierten Snapshots (nur 'certified').
             */
            snapshot_schema_version?: number | null;
            /** Source Run Id */
            source_run_id?: string | null;
            /**
             * Source Run Status
             * @description Status des Empfehlungslaufs, auf dem dieser Ausweis beruht ('Final' = freigegeben, 'Draft' = vorlaeufig). Ohne dieses Feld ist ein Ausweis auf Entwurfsbasis von einem freigegebenen nicht zu unterscheiden (COST-CONTEXT-001a).
             */
            source_run_status?: string | null;
            totals: components["schemas"]["CostTotals"];
            /** Warnings */
            warnings?: string[];
        };
        /** CostItem */
        CostItem: {
            /** Amount Rappen */
            amount_rappen: number;
            /** Basis Label */
            basis_label: string;
            /** Basis Rappen */
            basis_rappen: number;
            /** Category */
            category: string;
            /**
             * Frequency
             * @description 'einmalig' oder 'jaehrlich'
             */
            frequency: string;
            /**
             * Included In Total
             * @default true
             */
            included_in_total?: boolean;
            /**
             * Is Estimate
             * @default false
             */
            is_estimate?: boolean;
            /**
             * Key
             * @description Stabiler Identifier des Kostenpostens
             */
            key: string;
            /** Label */
            label: string;
            /**
             * Rate Bps
             * @description Satz in Basispunkten, sofern ein fixer Prozentsatz auf eine Basis angewendet wird. None fuer Positionen ohne Satzbezug (z.B. Retrozessionen -- absolute, offengelegte Betraege ohne Raten-Basis).
             */
            rate_bps?: number | null;
            /**
             * Requires Resolution
             * @description True, wenn der Posten einen rechtlich UNGEKLAERTEN Zustand ausweist, der eine Beraterhandlung verlangt (aktuell: eine einbehaltene Retrozession ohne dokumentierten Kundenverzicht, BGE 132 III 460). Das Feld steht hier, weil Pydantic unbekannte Felder beim Serialisieren still verwirft -- ohne diese Zeile waere das Kennzeichen im Service gesetzt und im API-Payload unsichtbar.
             * @default false
             */
            requires_resolution?: boolean;
            /** Source */
            source: string;
        };
        /** CostTotals */
        CostTotals: {
            /** Annual Bps */
            annual_bps?: number | null;
            /**
             * Annual Rappen
             * @default 0
             */
            annual_rappen?: number;
            /** First Year Bps */
            first_year_bps?: number | null;
            /**
             * First Year Rappen
             * @default 0
             */
            first_year_rappen?: number;
            /** One Time Bps */
            one_time_bps?: number | null;
            /**
             * One Time Rappen
             * @default 0
             */
            one_time_rappen?: number;
        };
        /** CustomerConfirmRequest */
        CustomerConfirmRequest: {
            /** Challenge Id */
            challenge_id: string;
            /** Code */
            code: string;
            /** Consent Text Hash */
            consent_text_hash: string;
            /** Displayed Document Hash */
            displayed_document_hash: string;
        };
        /** DriftResult */
        DriftResult: {
            /** Advisory Assets Rappen */
            advisory_assets_rappen: number;
            /** Bands */
            bands: Record<string, unknown>;
            /** Chart Conservative */
            chart_conservative: unknown[];
            /** Chart Spi Proxy */
            chart_spi_proxy: unknown[];
            /** Chart Strategy */
            chart_strategy: unknown[];
            /** Chart Years */
            chart_years: unknown[];
            /** Delta */
            delta: Record<string, unknown>;
            /** Drifted */
            drifted: Record<string, unknown>;
            /** Has Drift Data */
            has_drift_data: boolean;
            /** Original */
            original: Record<string, unknown>;
            /** Risk Profile Label */
            risk_profile_label: string;
            /** Snapshot Date */
            snapshot_date: string;
            /** Snapshot Id */
            snapshot_id: string;
            /** Status */
            status: Record<string, unknown>;
        };
        /**
         * EligibilityOverrideApprovalRequest
         * @description ELIG-OVERRIDE-SINGLE-APPROVER-001: only relevant when the requester
         *     confirms their own request (sole person entitled to approve).
         */
        EligibilityOverrideApprovalRequest: {
            /** Attestation Reason */
            attestation_reason?: string | null;
            /**
             * Single Approver Attestation
             * @default false
             */
            single_approver_attestation?: boolean;
        };
        /** EligibilityOverrideRequest */
        EligibilityOverrideRequest: {
            /** Expected Decision Hash */
            expected_decision_hash?: string | null;
            /** Product Id */
            product_id: string;
            /** Reason Text */
            reason_text: string;
        };
        /** ErasureCaseOpen */
        ErasureCaseOpen: {
            /** Client Id */
            client_id: string;
            /** Relationship End Date */
            relationship_end_date?: string | null;
        };
        /** FXRateResponse */
        FXRateResponse: {
            /** Currency */
            currency: string;
            /** Rate */
            rate: number;
            /** Source */
            source: string;
            /** Updated At */
            updated_at: string;
            /** Valid From */
            valid_from: string;
        };
        /** FinalizeRequest */
        FinalizeRequest: {
            /** Qes Receipt */
            qes_receipt?: Record<string, unknown> | null;
        };
        /**
         * FinancialCoverageAttestationCreate
         * @description RISK-CAPACITY-PLAUSIBILITY-001 Restbefund A (PR #653): Berater bestaetigt,
         *     dass Einnahmen, Ausgaben und Verpflichtungen des Haushalts vollstaendig
         *     erfasst sind. Alle Kategorien sind Pflichtangaben (explizit ja/nein);
         *     nur eine vollstaendig bejahte, aktuelle Bestaetigung zaehlt als Evidence.
         *     Fachliche Pruefung (Stichtag, Quelle, Personen) in
         *     services/financial_coverage_attestation.create_attestation().
         */
        FinancialCoverageAttestationCreate: {
            /** As Of Date */
            as_of_date: string;
            /** Expenses Complete */
            expenses_complete: boolean;
            /** Household Persons */
            household_persons: string[];
            /** Income Complete */
            income_complete: boolean;
            /** Irregular Expenses Reviewed */
            irregular_expenses_reviewed: boolean;
            /** Note */
            note?: string | null;
            /** Obligations Complete */
            obligations_complete: boolean;
            /** Source */
            source: string;
        };
        /** GoalAnalysisResponse */
        GoalAnalysisResponse: {
            /** Achievement Score */
            achievement_score: number;
            /** Evaluation Note */
            evaluation_note?: string | null;
            /** Frequency */
            frequency?: string | null;
            /** Funded Ratio P50 */
            funded_ratio_p50?: number | null;
            /** Goal Id */
            goal_id: string;
            /** Goal Scope */
            goal_scope: string;
            /** Goal Type */
            goal_type: string;
            /** Hardness */
            hardness?: string | null;
            /** Horizon Years */
            horizon_years?: number | null;
            /** Is Ongoing */
            is_ongoing?: number | null;
            /** Label */
            label: string;
            /** Median Achievement Pct */
            median_achievement_pct?: number | null;
            /** Path Success Rate Pct */
            path_success_rate_pct?: number | null;
            /** Pessimistic Shortfall Rappen */
            pessimistic_shortfall_rappen?: number | null;
            /** Projected Value P10 Rappen */
            projected_value_p10_rappen?: number | null;
            /** Projected Value P50 Rappen */
            projected_value_p50_rappen?: number | null;
            /** Projected Value P90 Rappen */
            projected_value_p90_rappen?: number | null;
            /** Projected Value Rappen */
            projected_value_rappen: number;
            /** Rank */
            rank: number;
            /** Start Date */
            start_date?: string | null;
            /** Status */
            status: string;
            /** Success Probability */
            success_probability?: number | null;
            /** Success Probability Pct */
            success_probability_pct?: number | null;
            /** Success Probability Source */
            success_probability_source?: string | null;
            /** Success Rate Pct */
            success_rate_pct?: number | null;
            /** Success Weight Bps */
            success_weight_bps?: number | null;
            /** Target Amount Rappen */
            target_amount_rappen: number;
            /** Target Date */
            target_date?: string | null;
            /** Target Return Bps */
            target_return_bps?: number | null;
            /** Target Wealth Rappen */
            target_wealth_rappen?: number | null;
            /** Timing Label */
            timing_label?: string | null;
            /** Value Mode */
            value_mode?: string | null;
            /** Weight Bps */
            weight_bps: number;
        };
        /** GoalCreate */
        GoalCreate: {
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Frequency */
            frequency?: string | null;
            /**
             * Goal Family
             * @enum {string}
             */
            goal_family: "Vermögen" | "Cashflow" | "Rendite" | "Maximierung";
            /**
             * Goal Scope
             * @default Beratungsvermögen
             * @enum {string}
             */
            goal_scope?: "Beratungsvermögen" | "Gesamtvermögen";
            /**
             * Goal Type
             * @enum {string}
             */
            goal_type: "Kapitalerhalt" | "Vermögensziel" | "Vermoegensziel" | "Einmalige_Ausgabe" | "Wiederkehrende_Ausgabe" | "Pensionsausgabe" | "Renditeziel" | "Maximierung";
            /**
             * Hardness
             * @default Primär
             */
            hardness?: string;
            /** Horizon Years */
            horizon_years?: number | null;
            /**
             * Is Ongoing
             * @default false
             */
            is_ongoing?: boolean;
            /** Label */
            label: string;
            /** Linked Position Id */
            linked_position_id?: string | null;
            /** Notes */
            notes?: string | null;
            /** Pension Pillar */
            pension_pillar?: ("AHV" | "BVG" | "3a" | "1e" | "FZG") | null;
            /**
             * Probability Pct
             * @default 100
             */
            probability_pct?: number;
            /** Rank */
            rank: number;
            /** Start Date */
            start_date?: string | null;
            /** Success Probability Min X100 */
            success_probability_min_x100?: number | null;
            /** Target Amount Rappen */
            target_amount_rappen?: number | null;
            /** Target Date */
            target_date?: string | null;
            /** Target Return Bps */
            target_return_bps?: number | null;
            /** Target Wealth Rappen */
            target_wealth_rappen?: number | null;
            /**
             * Value Mode
             * @default nominal
             * @enum {string}
             */
            value_mode?: "nominal" | "real";
            /** Weight Bps */
            weight_bps?: number | null;
        };
        /**
         * GoalOrderUpdate
         * @description Vollstaendige Ziel-Reihenfolge eines Mandats (GOAL-RANK-HARDNESS-ROUNDTRIP-001).
         *
         *     ``goal_ids``: alle aktiven Ziele genau einmal, in neuer Prioritaet.
         *     ``expected_goal_ids``: optional die zuletzt gesehene Reihenfolge (CAS).
         */
        GoalOrderUpdate: {
            /** Expected Goal Ids */
            expected_goal_ids?: string[] | null;
            /** Goal Ids */
            goal_ids: string[];
        };
        /** GoalResponse */
        GoalResponse: {
            /** Achievement Score */
            achievement_score: number | null;
            /** Client Id */
            client_id: string;
            /** Created At */
            created_at: string;
            /** Frequency */
            frequency: string | null;
            /** Goal Family */
            goal_family: string;
            /** Goal Scope */
            goal_scope: string;
            /** Goal Type */
            goal_type: string;
            /** Hardness */
            hardness: string;
            /** Horizon Years */
            horizon_years: number | null;
            /** Id */
            id: string;
            /** Is Active */
            is_active: number;
            /** Is Included */
            is_included: number;
            /** Is Ongoing */
            is_ongoing: number;
            /** Label */
            label: string;
            /** Last Scored At */
            last_scored_at: string | null;
            /** Linked Position Id */
            linked_position_id: string | null;
            /** Mandate Id */
            mandate_id: string;
            /** Notes */
            notes: string | null;
            /** Pension Pillar */
            pension_pillar?: string | null;
            /** Probability Pct */
            probability_pct?: number | null;
            /** Rank */
            rank: number;
            /** Start Date */
            start_date: string | null;
            /** Success Probability Min X100 */
            success_probability_min_x100?: number | null;
            /** Target Amount Rappen */
            target_amount_rappen: number | null;
            /** Target Date */
            target_date: string | null;
            /** Target Return Bps */
            target_return_bps: number | null;
            /** Target Wealth Rappen */
            target_wealth_rappen: number | null;
            /** Updated At */
            updated_at: string;
            /** Value Mode */
            value_mode: string;
            /** Weight Bps */
            weight_bps: number | null;
        };
        /**
         * GoalRevisionDecisionCreate
         * @description GOAL-REVISION-DECISION-001: Berater stuft ein Ziel als nachrangiges
         *     Wunschziel ein. Die Begruendung wird wie eine Override-Begruendung
         *     geprueft (services.override_reason_quality); die Engine-Evidenz liest
         *     der Server aus der aktuellen Strategie, nie aus dem Request.
         */
        GoalRevisionDecisionCreate: {
            /** Reason */
            reason: string;
        };
        /** GoalUpdate */
        GoalUpdate: {
            /** Data Classification */
            data_classification?: ("synthetic" | "real") | null;
            /** Frequency */
            frequency?: string | null;
            /** Goal Family */
            goal_family?: string | null;
            /** Goal Scope */
            goal_scope?: string | null;
            /** Goal Type */
            goal_type?: string | null;
            /** Hardness */
            hardness?: string | null;
            /** Horizon Years */
            horizon_years?: number | null;
            /** Is Active */
            is_active?: boolean | null;
            /** Is Included */
            is_included?: boolean | null;
            /** Is Ongoing */
            is_ongoing?: boolean | null;
            /** Label */
            label?: string | null;
            /** Linked Position Id */
            linked_position_id?: string | null;
            /** Notes */
            notes?: string | null;
            /** Pension Pillar */
            pension_pillar?: ("AHV" | "BVG" | "3a" | "1e" | "FZG") | null;
            /** Probability Pct */
            probability_pct?: number | null;
            /** Rank */
            rank?: number | null;
            /** Start Date */
            start_date?: string | null;
            /** Success Probability Min X100 */
            success_probability_min_x100?: number | null;
            /** Target Amount Rappen */
            target_amount_rappen?: number | null;
            /** Target Date */
            target_date?: string | null;
            /** Target Return Bps */
            target_return_bps?: number | null;
            /** Target Wealth Rappen */
            target_wealth_rappen?: number | null;
            /** Value Mode */
            value_mode?: string | null;
            /** Weight Bps */
            weight_bps?: number | null;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** HouseMatrixResponse */
        HouseMatrixResponse: {
            /** Alt Max Bps */
            alt_max_bps: number;
            /** Alt Min Bps */
            alt_min_bps: number;
            /** Alt Target Bps */
            alt_target_bps: number;
            /** Bonds Max Bps */
            bonds_max_bps: number;
            /** Bonds Min Bps */
            bonds_min_bps: number;
            /** Bonds Target Bps */
            bonds_target_bps: number;
            /** Equity Max Bps */
            equity_max_bps: number;
            /** Equity Min Bps */
            equity_min_bps: number;
            /** Equity Minimum Bps */
            equity_minimum_bps: number;
            /** Equity Target Bps */
            equity_target_bps: number;
            /** Id */
            id: string;
            /** Liq Max Bps */
            liq_max_bps: number;
            /** Liq Min Bps */
            liq_min_bps: number;
            /** Liq Target Bps */
            liq_target_bps: number;
            /** Max Risky Fraction Bps */
            max_risky_fraction_bps: number;
            /** Policy Id */
            policy_id: string;
            /** Profile Name */
            profile_name: string;
            /** Real Estate Max Bps */
            real_estate_max_bps: number;
            /** Real Estate Min Bps */
            real_estate_min_bps: number;
            /** Real Estate Target Bps */
            real_estate_target_bps: number;
            /** Score From */
            score_from: number;
            /** Score To */
            score_to: number;
        };
        /** HouseMatrixRowInput */
        HouseMatrixRowInput: {
            /** Alt Max Bps */
            alt_max_bps: number;
            /** Alt Min Bps */
            alt_min_bps: number;
            /** Alt Target Bps */
            alt_target_bps: number;
            /** Bonds Max Bps */
            bonds_max_bps: number;
            /** Bonds Min Bps */
            bonds_min_bps: number;
            /** Bonds Target Bps */
            bonds_target_bps: number;
            /** Equity Max Bps */
            equity_max_bps: number;
            /** Equity Min Bps */
            equity_min_bps: number;
            /**
             * Equity Minimum Bps
             * @default 0
             */
            equity_minimum_bps?: number;
            /** Equity Target Bps */
            equity_target_bps: number;
            /** Liq Max Bps */
            liq_max_bps: number;
            /** Liq Min Bps */
            liq_min_bps: number;
            /** Liq Target Bps */
            liq_target_bps: number;
            /** Max Risky Fraction Bps */
            max_risky_fraction_bps: number;
            /** Profile Name */
            profile_name: string;
            /** Real Estate Max Bps */
            real_estate_max_bps: number;
            /** Real Estate Min Bps */
            real_estate_min_bps: number;
            /** Real Estate Target Bps */
            real_estate_target_bps: number;
            /** Score From */
            score_from: number;
            /** Score To */
            score_to: number;
        };
        /**
         * HouseMatrixRowsReplace
         * @description Bulk-Update: ersetzt ALLE Rows einer Policy auf einmal (Atomic).
         */
        HouseMatrixRowsReplace: {
            /** Rows */
            rows: components["schemas"]["HouseMatrixRowInput"][];
        };
        /** IdentityCheckRequest */
        IdentityCheckRequest: {
            /** Id Document Country */
            id_document_country: string;
            /** Id Document Kind */
            id_document_kind: string;
            /** Id Document Valid */
            id_document_valid: boolean;
            /** Method */
            method: string;
            /**
             * Result
             * @enum {string}
             */
            result: "verified" | "failed";
        };
        /** InviteAccept */
        InviteAccept: {
            /** Password */
            password: string;
            /** Token */
            token: string;
        };
        /**
         * InviteCreate
         * @description Admin legt einen Mitarbeiter-Account OHNE Passwort an; der Mitarbeiter
         *     setzt es selbst per Einladungslink (E1, 2026-06-14).
         */
        InviteCreate: {
            /** Email */
            email?: string | null;
            /** Full Name */
            full_name: string;
            /**
             * Role
             * @default advisor
             * @enum {string}
             */
            role?: "admin" | "advisor" | "readonly" | "portfolio_management";
            /** Tenant Id */
            tenant_id?: string | null;
            /** Username */
            username: string;
        };
        /** InvitePreview */
        InvitePreview: {
            /** Full Name */
            full_name: string;
            /** Username */
            username: string;
        };
        /** InviteResponse */
        InviteResponse: {
            /**
             * Email Sent
             * @default false
             */
            email_sent?: boolean;
            /** Invite Expires At */
            invite_expires_at: string;
            /** Invite Token */
            invite_token: string;
            /** User Id */
            user_id: string;
            /** Username */
            username: string;
        };
        /** JurisdictionHomeBiasDefaultCreate */
        JurisdictionHomeBiasDefaultCreate: {
            /**
             * Is Provisional
             * @default 1
             */
            is_provisional?: number;
            /** Preference Key */
            preference_key: string;
            /** Preference Value */
            preference_value: string;
            /** Rationale Text */
            rationale_text?: string | null;
            /** Sort Order */
            sort_order?: number | null;
            /** Split Bps */
            split_bps: number;
            /** Sub Asset Class */
            sub_asset_class: string;
        };
        /** JurisdictionHomeBiasDefaultResponse */
        JurisdictionHomeBiasDefaultResponse: {
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /** Is Provisional */
            is_provisional: number;
            /** Jurisdiction Code */
            jurisdiction_code: string;
            /** Preference Key */
            preference_key: string;
            /** Preference Value */
            preference_value: string;
            /** Rationale Text */
            rationale_text?: string | null;
            /** Sort Order */
            sort_order?: number | null;
            /** Split Bps */
            split_bps: number;
            /** Sub Asset Class */
            sub_asset_class: string;
            /** Updated At */
            updated_at: string;
        };
        /** JurisdictionHomeBiasDefaultUpdate */
        JurisdictionHomeBiasDefaultUpdate: {
            /** Is Provisional */
            is_provisional?: number | null;
            /** Preference Key */
            preference_key?: string | null;
            /** Preference Value */
            preference_value?: string | null;
            /** Rationale Text */
            rationale_text?: string | null;
            /** Sort Order */
            sort_order?: number | null;
            /** Split Bps */
            split_bps?: number | null;
            /** Sub Asset Class */
            sub_asset_class?: string | null;
        };
        /** JurisdictionProfileResponse */
        JurisdictionProfileResponse: {
            /** Code */
            code: string;
            /** Created At */
            created_at: string;
            /** Display Name */
            display_name: string;
            /** Home Currency */
            home_currency: string;
            /** Id */
            id: string;
            /** Is Active */
            is_active: number;
            /** Is Provisional */
            is_provisional: number;
            /** Notes */
            notes?: string | null;
            /** Status */
            status: string;
            /** Updated At */
            updated_at: string;
        };
        /**
         * JurisdictionProfileUpdate
         * @description Partial-Update-Body fuer PUT /jurisdictions/{code}. Nicht gesetzte
         *     Felder (exclude_unset) bleiben unveraendert -- code/home_currency/
         *     created_by/created_at sind hier bewusst NICHT editierbar (Stammdaten-
         *     Identitaet einer Jurisdiktion aendert sich nicht ueber dieses Update).
         */
        JurisdictionProfileUpdate: {
            /** Display Name */
            display_name?: string | null;
            /** Is Active */
            is_active?: number | null;
            /** Notes */
            notes?: string | null;
            /** Status */
            status?: string | null;
        };
        /** KnowledgeCreate */
        KnowledgeCreate: {
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /**
             * Exp Alternatives
             * @default Keine
             * @enum {string}
             */
            exp_alternatives?: "Keine" | "< 2 Jahre" | "2–5 Jahre" | "> 5 Jahre";
            /**
             * Exp Bonds
             * @default Keine
             * @enum {string}
             */
            exp_bonds?: "Keine" | "< 2 Jahre" | "2–5 Jahre" | "> 5 Jahre";
            /**
             * Exp Derivatives
             * @default Keine
             * @enum {string}
             */
            exp_derivatives?: "Keine" | "< 2 Jahre" | "2–5 Jahre" | "> 5 Jahre";
            /**
             * Exp Equities
             * @default Keine
             * @enum {string}
             */
            exp_equities?: "Keine" | "< 2 Jahre" | "2–5 Jahre" | "> 5 Jahre";
            /**
             * Exp Funds
             * @default Keine
             * @enum {string}
             */
            exp_funds?: "Keine" | "< 2 Jahre" | "2–5 Jahre" | "> 5 Jahre";
            /**
             * Exp Structured
             * @default Keine
             * @enum {string}
             */
            exp_structured?: "Keine" | "< 2 Jahre" | "2–5 Jahre" | "> 5 Jahre";
            /**
             * Knowledge Level
             * @default Mittel
             * @enum {string}
             */
            knowledge_level?: "Keine" | "Gering" | "Mittel" | "Hoch";
            /** Next Review At */
            next_review_at?: string | null;
        };
        /** KnowledgeResponse */
        KnowledgeResponse: {
            /** Client Id */
            client_id: string;
            /** Confirmed At */
            confirmed_at: string;
            /** Confirmed By */
            confirmed_by: string;
            /** Created At */
            created_at: string;
            /** Exp Alternatives */
            exp_alternatives: string;
            /** Exp Bonds */
            exp_bonds: string;
            /** Exp Derivatives */
            exp_derivatives: string;
            /** Exp Equities */
            exp_equities: string;
            /** Exp Funds */
            exp_funds: string;
            /** Exp Structured */
            exp_structured: string;
            /** Id */
            id: string;
            /** Is Current */
            is_current: number;
            /** Knowledge Level */
            knowledge_level: string;
            /** Next Review At */
            next_review_at: string | null;
            /** Valid From */
            valid_from: string;
            /** Valid To */
            valid_to: string | null;
            /** Version */
            version: number;
        };
        /** LegalHoldExtension */
        LegalHoldExtension: {
            /** Expires At */
            expires_at?: string | null;
            /** Review Date */
            review_date: string;
        };
        /** LegalHoldProposal */
        LegalHoldProposal: {
            /** Case Reference */
            case_reference: string;
            /** Client Id */
            client_id: string;
            /** Expires At */
            expires_at?: string | null;
            /** Legal Reason */
            legal_reason: string;
            /** Review Date */
            review_date: string;
            /** Scope */
            scope: string[];
        };
        /** LiveRebalancingBucketResponse */
        LiveRebalancingBucketResponse: {
            /** Asset Class */
            asset_class: string;
            /** Band Max Bps */
            band_max_bps: number;
            /** Band Min Bps */
            band_min_bps: number;
            /** Breach Bps */
            breach_bps: number;
            /** Breached */
            breached: boolean;
            /** Current Market Value Rappen */
            current_market_value_rappen: number;
            /** Current Weight Bps */
            current_weight_bps: number;
            /** Delta Weight Bps */
            delta_weight_bps: number;
            /** Rebalance Amount Rappen */
            rebalance_amount_rappen: number;
            /** Target Market Value Rappen */
            target_market_value_rappen: number;
            /** Target Weight Bps */
            target_weight_bps: number;
        };
        /** LiveRebalancingPositionResponse */
        LiveRebalancingPositionResponse: {
            /** Asset Class */
            asset_class: string;
            /** Current Market Value Rappen */
            current_market_value_rappen: number;
            /** Current Units Milli */
            current_units_milli?: number | null;
            /** Current Weight Bps */
            current_weight_bps: number;
            /** Delta Weight Bps */
            delta_weight_bps: number;
            /** Holding As Of Date */
            holding_as_of_date?: string | null;
            /** Holding Avg Cost Price Rappen */
            holding_avg_cost_price_rappen?: number | null;
            /** Holding Custody Account Number */
            holding_custody_account_number?: string | null;
            /** Holding Depot Bank */
            holding_depot_bank?: string | null;
            /** Holding Market Value Rappen */
            holding_market_value_rappen?: number | null;
            /** Holding Notes */
            holding_notes?: string | null;
            /**
             * Holding Present
             * @default false
             */
            holding_present?: boolean;
            /** Holding Source */
            holding_source?: string | null;
            /** Holding Units Milli */
            holding_units_milli?: number | null;
            /** Id */
            id: string;
            /** Implied Units Milli */
            implied_units_milli?: number | null;
            /** Latest Price Date */
            latest_price_date?: string | null;
            /** Latest Price Rappen */
            latest_price_rappen?: number | null;
            /** Price Age Days */
            price_age_days?: number | null;
            /** Price Change Bps */
            price_change_bps?: number | null;
            /** Price Is Fresh */
            price_is_fresh?: boolean | null;
            /** Product Id */
            product_id: string;
            /** Product Name */
            product_name: string;
            /** Rebalance Action */
            rebalance_action: string;
            /** Rebalance Action Code */
            rebalance_action_code: string;
            /** Rebalance Action Label */
            rebalance_action_label: string;
            /** Rebalance Amount Rappen */
            rebalance_amount_rappen: number;
            /** Reference Price Date */
            reference_price_date?: string | null;
            /** Reference Price Rappen */
            reference_price_rappen?: number | null;
            /**
             * Reference Recalibrated
             * @default false
             */
            reference_recalibrated?: boolean;
            /** Run Target Amount Rappen */
            run_target_amount_rappen?: number | null;
            /** Sub Asset Class */
            sub_asset_class?: string | null;
            /** Target Amount Rappen */
            target_amount_rappen: number;
            /** Target Weight Bps */
            target_weight_bps: number;
            /** Valuation Basis */
            valuation_basis?: string | null;
        };
        /** LiveRebalancingResponse */
        LiveRebalancingResponse: {
            /** Action Summary */
            action_summary: string[];
            /** As Of Date */
            as_of_date?: string | null;
            /** Breached Asset Classes */
            breached_asset_classes: string[];
            /** Bucket Drifts */
            bucket_drifts: components["schemas"]["LiveRebalancingBucketResponse"][];
            /**
             * Holding Positions Count
             * @default 0
             */
            holding_positions_count?: number;
            /**
             * Implied Positions Count
             * @default 0
             */
            implied_positions_count?: number;
            /** Live Total Value Rappen */
            live_total_value_rappen: number;
            /** Market Data Quality */
            market_data_quality?: Record<string, unknown>;
            /** Methodology */
            methodology: string;
            /** Missing Prices Count */
            missing_prices_count: number;
            /** Position Drifts */
            position_drifts: components["schemas"]["LiveRebalancingPositionResponse"][];
            /** Priced Positions Count */
            priced_positions_count: number;
            /**
             * Recalibrated Positions Count
             * @default 0
             */
            recalibrated_positions_count?: number;
            /** Reference Anchor Date */
            reference_anchor_date?: string | null;
            /** Stale Positions Count */
            stale_positions_count: number;
            /** Turnover Required Rappen */
            turnover_required_rappen: number;
        };
        /** LoginRequest */
        LoginRequest: {
            /** Password */
            password: string;
            /** Totp Code */
            totp_code?: string | null;
            /** Username */
            username: string;
        };
        /** MandateBausteinSelectionItem */
        MandateBausteinSelectionItem: {
            /** Baustein Id */
            baustein_id: string;
            /** Custom Override Md */
            custom_override_md?: string | null;
            /**
             * Sort Order
             * @default 0
             */
            sort_order?: number;
        };
        /** MandateBausteinSelectionResponse */
        MandateBausteinSelectionResponse: {
            /** Baustein Id */
            baustein_id: string;
            /** Category */
            category?: string | null;
            /** Content Md */
            content_md?: string | null;
            /** Created At */
            created_at: string;
            /** Custom Override Md */
            custom_override_md: string | null;
            /** Id */
            id: string;
            /** Mandate Id */
            mandate_id: string;
            /** Sort Order */
            sort_order: number;
            /** Title */
            title?: string | null;
            /** Updated At */
            updated_at: string;
        };
        /** MandateBausteinSelectionUpdate */
        MandateBausteinSelectionUpdate: {
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Selections */
            selections: components["schemas"]["MandateBausteinSelectionItem"][];
        };
        /** MandateCreate */
        MandateCreate: {
            /**
             * Advisory Language
             * @default DE
             * @enum {string}
             */
            advisory_language?: "DE" | "FR" | "IT" | "EN";
            /**
             * Base Currency
             * @default CHF
             */
            base_currency?: string;
            /** Client Birth Year */
            client_birth_year?: number | null;
            /** Client Sex */
            client_sex?: ("M" | "F") | null;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Depot Account Number */
            depot_account_number?: string | null;
            /** Depot Bank */
            depot_bank?: string | null;
            /**
             * Investment Universe
             * @default Standard
             */
            investment_universe?: ("Standard" | "Alternativ") | null;
            /** Jurisdiction */
            jurisdiction?: string | null;
            /** Mandate Number */
            mandate_number: string;
            /**
             * Mandate Type
             * @default Anlageberatung
             * @enum {string}
             */
            mandate_type?: "Vermögensverwaltung" | "Anlageberatung" | "Finanzplanung" | "Reporting only";
            /** Opened At */
            opened_at?: string | null;
            /**
             * Tax Estimate In Cashflow Enabled
             * @default false
             */
            tax_estimate_in_cashflow_enabled?: boolean | null;
            /** Tax Jurisdiction */
            tax_jurisdiction?: string | null;
            /** Tax Overrides Json */
            tax_overrides_json?: string | null;
            /**
             * Use Mortality Simulation
             * @default false
             */
            use_mortality_simulation?: boolean | null;
        };
        /** MandateResponse */
        MandateResponse: {
            /** Advisory Language */
            advisory_language: string;
            /** Base Currency */
            base_currency: string;
            /** Client Birth Year */
            client_birth_year?: number | null;
            /** Client Id */
            client_id: string;
            /** Client Sex */
            client_sex?: string | null;
            /** Closed At */
            closed_at: string | null;
            /** Created At */
            created_at: string;
            /** Default Building Blocks Json */
            default_building_blocks_json?: string | null;
            /** Depot Account Number */
            depot_account_number: string | null;
            /** Depot Bank */
            depot_bank: string | null;
            /** Hidden Report Sections */
            hidden_report_sections?: string | null;
            /** Id */
            id: string;
            /**
             * Investment Universe
             * @default Standard
             */
            investment_universe?: string | null;
            /** Jurisdiction */
            jurisdiction?: string | null;
            /** Life Expectancy Year */
            life_expectancy_year?: number | null;
            /** Mandate Number */
            mandate_number: string;
            /** Mandate Type */
            mandate_type: string;
            /** Opened At */
            opened_at: string;
            /** Retirement Year */
            retirement_year?: number | null;
            /** Status */
            status: string;
            /**
             * Tax Estimate In Cashflow Enabled
             * @default false
             */
            tax_estimate_in_cashflow_enabled?: boolean | null;
            /** Tax Jurisdiction */
            tax_jurisdiction?: string | null;
            /** Tax Overrides Json */
            tax_overrides_json?: string | null;
            /** Updated At */
            updated_at: string;
            /**
             * Use Mortality Simulation
             * @default false
             */
            use_mortality_simulation?: boolean | null;
        };
        /** MandateUpdate */
        MandateUpdate: {
            /** Advisory Language */
            advisory_language?: ("DE" | "FR" | "IT" | "EN") | null;
            /** Base Currency */
            base_currency?: string | null;
            /** Client Birth Year */
            client_birth_year?: number | null;
            /** Client Sex */
            client_sex?: ("M" | "F") | null;
            /** Closed At */
            closed_at?: string | null;
            /** Data Classification */
            data_classification?: ("synthetic" | "real") | null;
            /** Default Building Blocks Json */
            default_building_blocks_json?: string | null;
            /** Depot Account Number */
            depot_account_number?: string | null;
            /** Depot Bank */
            depot_bank?: string | null;
            /** Hidden Report Sections */
            hidden_report_sections?: string | null;
            /** Investment Universe */
            investment_universe?: ("Standard" | "Alternativ") | null;
            /** Jurisdiction */
            jurisdiction?: string | null;
            /** Life Expectancy Year */
            life_expectancy_year?: number | null;
            /** Mandate Type */
            mandate_type?: ("Vermögensverwaltung" | "Anlageberatung" | "Finanzplanung" | "Reporting only") | null;
            /** Retirement Year */
            retirement_year?: number | null;
            /** Status */
            status?: ("Aktiv" | "Inaktiv" | "Archiviert") | null;
            /** Tax Estimate In Cashflow Enabled */
            tax_estimate_in_cashflow_enabled?: boolean | null;
            /** Tax Jurisdiction */
            tax_jurisdiction?: string | null;
            /** Tax Overrides Json */
            tax_overrides_json?: string | null;
            /** Use Mortality Simulation */
            use_mortality_simulation?: boolean | null;
        };
        /** MaxPensionSpendingRequest */
        MaxPensionSpendingRequest: {
            /** Life Expectancy Year */
            life_expectancy_year: number;
            /** Retirement Year */
            retirement_year: number;
            /**
             * Safety Margin Pct
             * @default 0
             */
            safety_margin_pct?: number;
            /**
             * Value Mode
             * @default real
             * @enum {string}
             */
            value_mode?: "nominal" | "real";
        };
        /** MaxPensionSpendingResponse */
        MaxPensionSpendingResponse: {
            /** Advisory Wealth Rappen */
            advisory_wealth_rappen: number;
            /** Expected Return Bps */
            expected_return_bps: number;
            /** Expected Volatility Bps */
            expected_volatility_bps: number;
            /** Inflation Bps */
            inflation_bps: number;
            /** Life Expectancy Year */
            life_expectancy_year: number;
            /** Max Annual Chf Rappen */
            max_annual_chf_rappen: number;
            /** Max Monthly Chf Rappen */
            max_monthly_chf_rappen: number;
            /** Real Return Bps */
            real_return_bps: number;
            /** Reasoning */
            reasoning: string[];
            /** Retirement Year */
            retirement_year: number;
            /** Safety Margin Pct */
            safety_margin_pct: number;
            /** Value Mode */
            value_mode: string;
            /** Years In Retirement */
            years_in_retirement: number;
        };
        /** MonteCarloGoalSummaryResponse */
        MonteCarloGoalSummaryResponse: {
            /** Evaluation Note */
            evaluation_note?: string | null;
            /** Funded Ratio P50 */
            funded_ratio_p50: number;
            /** Goal Id */
            goal_id: string;
            /** Label */
            label: string;
            /** Median Achievement Pct */
            median_achievement_pct: number;
            /** Pessimistic Shortfall Rappen */
            pessimistic_shortfall_rappen: number;
            /** Projected Value P10 Rappen */
            projected_value_p10_rappen: number;
            /** Projected Value P50 Rappen */
            projected_value_p50_rappen: number;
            /** Projected Value P90 Rappen */
            projected_value_p90_rappen: number;
            /** Score */
            score: number;
            /** Success Rate Pct */
            success_rate_pct: number;
            /** Years */
            years: number;
        };
        /** MonteCarloResponse */
        MonteCarloResponse: {
            /** Current Annualized Return P50 Bps */
            current_annualized_return_p50_bps: number;
            /** Current Depletion Median Year */
            current_depletion_median_year?: number | null;
            /** Current Depletion Probability Pct */
            current_depletion_probability_pct?: number | null;
            /** Current Goal Summaries */
            current_goal_summaries?: components["schemas"]["MonteCarloGoalSummaryResponse"][];
            /** Current P10 Series Rappen */
            current_p10_series_rappen: number[];
            /** Current P50 Series Rappen */
            current_p50_series_rappen: number[];
            /** Current P90 Series Rappen */
            current_p90_series_rappen: number[];
            /** External Reserve Balance Series Rappen */
            external_reserve_balance_series_rappen?: number[];
            /** Goal Summaries */
            goal_summaries: components["schemas"]["MonteCarloGoalSummaryResponse"][];
            /** Horizon Years */
            horizon_years: number;
            /** Model Basis */
            model_basis?: Record<string, unknown>;
            /** Reserve Accounting Basis */
            reserve_accounting_basis?: string | null;
            /** Seed */
            seed: number;
            /** Simulations */
            simulations: number;
            /** Start Year */
            start_year: number;
            /** Target Annualized Return P50 Bps */
            target_annualized_return_p50_bps: number;
            /** Target Cvar 95 1Y Bps */
            target_cvar_95_1y_bps: number;
            /** Target Depletion Median Year */
            target_depletion_median_year?: number | null;
            /** Target Depletion Probability Pct */
            target_depletion_probability_pct?: number | null;
            /** Target Downside Probability Pct */
            target_downside_probability_pct: number;
            /** Target Loss Probability 1Y Pct */
            target_loss_probability_1y_pct: number;
            /** Target Max Drawdown P50 Bps */
            target_max_drawdown_p50_bps: number;
            /** Target Max Drawdown P95 Bps */
            target_max_drawdown_p95_bps: number;
            /** Target P10 Series Rappen */
            target_p10_series_rappen: number[];
            /** Target P50 Series Rappen */
            target_p50_series_rappen: number[];
            /** Target P90 Series Rappen */
            target_p90_series_rappen: number[];
            /** Target Var 95 1Y Bps */
            target_var_95_1y_bps: number;
            /** Total Current P10 Series Rappen */
            total_current_p10_series_rappen?: number[];
            /** Total Current P50 Series Rappen */
            total_current_p50_series_rappen?: number[];
            /** Total Current P90 Series Rappen */
            total_current_p90_series_rappen?: number[];
            /** Total Target P10 Series Rappen */
            total_target_p10_series_rappen?: number[];
            /** Total Target P50 Series Rappen */
            total_target_p50_series_rappen?: number[];
            /** Total Target P90 Series Rappen */
            total_target_p90_series_rappen?: number[];
            /** Year Labels */
            year_labels: number[];
        };
        /** NationalityCreate */
        NationalityCreate: {
            /** Country Code */
            country_code: string;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /**
             * Is Primary
             * @default false
             */
            is_primary?: boolean;
        };
        /** NationalityResponse */
        NationalityResponse: {
            /** Client Id */
            client_id: string;
            /** Country Code */
            country_code: string;
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /** Is Primary */
            is_primary: number;
        };
        /** OpenRequest */
        OpenRequest: {
            /** Device App Version */
            device_app_version: string;
            /** Displayed Document Hash */
            displayed_document_hash: string;
            /** Language */
            language: string;
        };
        /** OptHistoryCreate */
        OptHistoryCreate: {
            /**
             * Client Requested
             * @default true
             */
            client_requested?: boolean;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Document Id */
            document_id?: string | null;
            /** Event Type */
            event_type: string;
            /**
             * From Classification
             * @enum {string}
             */
            from_classification: "Privatkunde" | "Professioneller Kunde" | "Institutioneller Kunde";
            /** From Professional Opt Out */
            from_professional_opt_out?: boolean | null;
            /** From Qualified Investor */
            from_qualified_investor?: boolean | null;
            /** Notes */
            notes?: string | null;
            /**
             * To Classification
             * @enum {string}
             */
            to_classification: "Privatkunde" | "Professioneller Kunde" | "Institutioneller Kunde";
            /** To Professional Opt Out */
            to_professional_opt_out?: boolean | null;
            /** To Qualified Investor */
            to_qualified_investor?: boolean | null;
        };
        /** OptHistoryResponse */
        OptHistoryResponse: {
            /** Client Id */
            client_id: string;
            /** Client Requested */
            client_requested: number;
            /** Created At */
            created_at: string;
            /** Documented At */
            documented_at: string;
            /** Documented By */
            documented_by: string;
            /** Event Type */
            event_type: string;
            /** From Classification */
            from_classification: string;
            /** From Professional Opt Out */
            from_professional_opt_out?: number | null;
            /** From Qualified Investor */
            from_qualified_investor?: number | null;
            /** Id */
            id: string;
            /** Notes */
            notes: string | null;
            /** To Classification */
            to_classification: string;
            /** To Professional Opt Out */
            to_professional_opt_out?: number | null;
            /** To Qualified Investor */
            to_qualified_investor?: number | null;
        };
        /**
         * OptimizerConstraintResponse
         * @description V3 Sprint 1d (Plan §6): strukturierter Constraint-Slack pro Constraint.
         *
         *     Nur in shadow_stochastic / stochastic Modus befuellt; sonst leere Liste.
         */
        OptimizerConstraintResponse: {
            /** Code */
            code: string;
            /** Is Binding */
            is_binding: boolean;
            /** Is Violated */
            is_violated: boolean;
            /** Label */
            label: string;
            /** Limit Bps */
            limit_bps: number;
            /** Slack Bps */
            slack_bps: number;
            /** Value Bps */
            value_bps: number;
        };
        /**
         * OptimizerGoalDriverResponse
         * @description V3 Sprint 1d (Plan §6): Goal-Driver fuer 'welches Ziel treibt den Solver'.
         *
         *     rank ist der 1-basierte Rang in absteigender Sortierung (1 = groesster
         *     Treiber), gebildet aus dem ROHEN Beitrag -- nicht aus einem der Felder
         *     unten. Nur in shadow_stochastic / stochastic Modus befuellt.
         *
         *     OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001 (2026-10-13)
         *     -------------------------------------------------------
         *     `services/portfolio_engine_optimizer_integration.py` berechnete das
         *     verlustfreie Paar (`_decimal`, `_binary64_hex`) bereits -- aber dieses
         *     Schema deklarierte es NICHT, und Pydantic verwirft unbekannte Felder beim
         *     Serialisieren STILL. Gemessen: beide Felder kamen nie an einem Konsumenten
         *     an, und der Monolith zeigte das verlustbehaftete Milli-Feld.
         *
         *     Die Folge war die Pathologie, die das Audit beschreibt -- vier materiell
         *     verschiedene Zustaende mit demselben Nachweis:
         *
         *         roh 0        -> milli 0     "vollstaendig erfuellt"
         *         roh 4e-12    -> milli 0     "minimaler Miss"
         *         roh 4e-5     -> milli 0     "kleiner materieller Shortfall"
         *         roh 0.00049  -> milli 0     "groesserer materieller Shortfall"
         *
         *     Nachgemessen am echten Konverter: die verlustfreien Felder unterscheiden
         *     alle fuenf Testwerte (5 von 5), das Milli-Feld keinen (1 von 5).
         */
        OptimizerGoalDriverResponse: {
            /**
             * Evaluation Scope
             * @default weighted_loss_component_under_priority_scope
             */
            evaluation_scope?: string;
            /** Goal Id */
            goal_id: string;
            /** Hardness Key */
            hardness_key: string;
            /** Label */
            label: string;
            /** Rank */
            rank: number;
            /** Target Kind */
            target_kind: string;
            /** Weight Bps */
            weight_bps: number;
            /** Weighted Objective Contribution Binary64 Hex */
            weighted_objective_contribution_binary64_hex?: string | null;
            /** Weighted Objective Contribution Decimal */
            weighted_objective_contribution_decimal?: string | null;
            /** Weighted Objective Contribution Milli */
            weighted_objective_contribution_milli?: number | null;
        };
        /** OptimizerPolicyCreate */
        OptimizerPolicyCreate: {
            /** Fee Model Json */
            fee_model_json?: string | null;
            /** House Matrix Rows */
            house_matrix_rows?: components["schemas"]["HouseMatrixRowInput"][];
            /**
             * Max Alternatives Bps
             * @default 1000
             */
            max_alternatives_bps?: number;
            /**
             * Max Real Estate Bps
             * @default 2000
             */
            max_real_estate_bps?: number;
            /**
             * Min Liquidity Bps
             * @default 0
             */
            min_liquidity_bps?: number;
            /** Notes */
            notes?: string | null;
            /**
             * Optimizer Engine
             * @default goal_based_v1
             */
            optimizer_engine?: string;
            /** Policy Name */
            policy_name: string;
        };
        /** OptimizerPolicyDetailResponse */
        OptimizerPolicyDetailResponse: {
            /** Created At */
            created_at: string;
            /** Created By */
            created_by: string;
            /** Fee Model Json */
            fee_model_json?: string | null;
            /** House Matrix Rows */
            house_matrix_rows?: components["schemas"]["HouseMatrixResponse"][];
            /** Id */
            id: string;
            /** Is Current */
            is_current: number;
            /** Max Alternatives Bps */
            max_alternatives_bps: number;
            /** Max Real Estate Bps */
            max_real_estate_bps: number;
            /** Min Liquidity Bps */
            min_liquidity_bps: number;
            /** Notes */
            notes?: string | null;
            /** Optimizer Engine */
            optimizer_engine: string;
            /** Policy Name */
            policy_name: string;
            /** Updated At */
            updated_at: string;
            /** Valid From */
            valid_from: string;
            /** Valid To */
            valid_to?: string | null;
            /** Version */
            version: number;
        };
        /** OptimizerPolicyResponse */
        OptimizerPolicyResponse: {
            /** Created At */
            created_at: string;
            /** Created By */
            created_by: string;
            /** Fee Model Json */
            fee_model_json?: string | null;
            /** Id */
            id: string;
            /** Is Current */
            is_current: number;
            /** Max Alternatives Bps */
            max_alternatives_bps: number;
            /** Max Real Estate Bps */
            max_real_estate_bps: number;
            /** Min Liquidity Bps */
            min_liquidity_bps: number;
            /** Notes */
            notes?: string | null;
            /** Optimizer Engine */
            optimizer_engine: string;
            /** Policy Name */
            policy_name: string;
            /** Updated At */
            updated_at: string;
            /** Valid From */
            valid_from: string;
            /** Valid To */
            valid_to?: string | null;
            /** Version */
            version: number;
        };
        /**
         * OptimizerPolicyUpdate
         * @description Editiert nur Policy-Level-Felder. House-Matrix-Rows via separatem Endpoint.
         */
        OptimizerPolicyUpdate: {
            /** Fee Model Json */
            fee_model_json?: string | null;
            /** Max Alternatives Bps */
            max_alternatives_bps?: number | null;
            /** Max Real Estate Bps */
            max_real_estate_bps?: number | null;
            /** Min Liquidity Bps */
            min_liquidity_bps?: number | null;
            /** Notes */
            notes?: string | null;
            /** Optimizer Engine */
            optimizer_engine?: string | null;
            /** Policy Name */
            policy_name?: string | null;
        };
        /**
         * OptimizerRunResponse
         * @description V3 Sprint 2: ein einzelner persistierter Solver-Lauf.
         */
        OptimizerRunResponse: {
            /** Constraint Violations Json */
            constraint_violations_json?: string | null;
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /** Mandate Id */
            mandate_id: string;
            /** Method */
            method: string;
            /** N Iterations */
            n_iterations: number;
            /** N Paths */
            n_paths: number;
            /** N Starts Attempted */
            n_starts_attempted: number;
            /** Objective Contract Hash */
            objective_contract_hash?: string | null;
            /** Objective Contract Json */
            objective_contract_json?: string | null;
            /** Objective Contract Version */
            objective_contract_version?: string | null;
            /** Objective Value Milli */
            objective_value_milli?: number | null;
            /** Optimizer Mode */
            optimizer_mode: string;
            /** Reasoning Json */
            reasoning_json?: string | null;
            /** Restart Results Json */
            restart_results_json?: string | null;
            /** Robustification Json */
            robustification_json?: string | null;
            /** Role */
            role: string;
            /** Run At */
            run_at: string;
            /** Seed */
            seed: number;
            /** Set By */
            set_by?: string | null;
            /** Status */
            status: string;
            /** Stress Evaluations Json */
            stress_evaluations_json?: string | null;
            /** Target Allocation Id */
            target_allocation_id?: string | null;
            /** Weights Bps Json */
            weights_bps_json: string;
        };
        /** PlanningAssumptionCreate */
        PlanningAssumptionCreate: {
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Inflation Assumption Bps */
            inflation_assumption_bps?: number | null;
            /** Life Expectancy Partner */
            life_expectancy_partner?: number | null;
            /** Life Expectancy Primary */
            life_expectancy_primary?: number | null;
            /** Notes */
            notes?: string | null;
            /**
             * Pension Indexation Bps
             * @description NICHT rechenwirksam (Stand PENSION-INDEXATION-001): wird persistiert und validiert, aber aktuell von KEINER Monte-Carlo-Simulation, Ziel-Projektion oder keinem Reporting-/PDF-Pfad konsumiert. Rein fuer kuenftige Verwendung gespeichert -- hat null Effekt auf heutige Berechnungsergebnisse.
             */
            pension_indexation_bps?: number | null;
            /** Retirement Age Partner */
            retirement_age_partner?: number | null;
            /** Retirement Age Primary */
            retirement_age_primary?: number | null;
        };
        /** PlanningAssumptionResponse */
        PlanningAssumptionResponse: {
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /** Inflation Assumption Bps */
            inflation_assumption_bps: number | null;
            /** Is Current */
            is_current: number;
            /** Life Expectancy Partner */
            life_expectancy_partner: number | null;
            /** Life Expectancy Primary */
            life_expectancy_primary: number | null;
            /** Mandate Id */
            mandate_id: string;
            /** Notes */
            notes: string | null;
            /**
             * Pension Indexation Bps
             * @description NICHT rechenwirksam (Stand PENSION-INDEXATION-001): wird persistiert, aber aktuell von keiner Simulation, Projektion oder keinem Reporting-Pfad konsumiert.
             */
            pension_indexation_bps: number | null;
            /** Retirement Age Partner */
            retirement_age_partner: number | null;
            /** Retirement Age Primary */
            retirement_age_primary: number | null;
            /** Updated At */
            updated_at: string;
            /** Valid From */
            valid_from: string;
            /** Version */
            version: number;
        };
        /** PolicyProposal */
        PolicyProposal: {
            /**
             * Data Category
             * @default *
             */
            data_category?: string;
            /** Disposition */
            disposition: string;
            /** Evidence Type */
            evidence_type: string;
            /** Legal Basis */
            legal_basis?: string | null;
            /** Matrix */
            matrix: Record<string, unknown>;
            /** Retention Months */
            retention_months?: number | null;
            /** Retention Trigger */
            retention_trigger?: string | null;
        };
        /** PortfolioHandoffCancel */
        PortfolioHandoffCancel: {
            /** Cancelled Reason */
            cancelled_reason: string;
        };
        /**
         * PortfolioHandoffCreate
         * @description Weiterleitung der aktuellen Handelsliste an die ausfuehrende Stelle
         *     (Depotbank / internes Asset Management). Die Trade-Zahlen werden NICHT
         *     vom Client uebernommen -- der Router berechnet den Snapshot serverseitig
         *     aus dem angegebenen run_id ueber denselben Code-Pfad wie die
         *     Handelsliste-Anzeige im Review (siehe models/portfolio_handoff.py).
         */
        PortfolioHandoffCreate: {
            /**
             * Confirm No Existing Holdings
             * @default false
             */
            confirm_no_existing_holdings?: boolean;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Note */
            note?: string | null;
            /** Recipient Channel */
            recipient_channel?: string | null;
            /** Recipient Name */
            recipient_name: string;
        };
        /**
         * PortfolioHandoffMarkExecuted
         * @description HANDOFF-EXECUTION-001: ein leerer Klick ist kein Ausfuehrungsnachweis.
         *
         *     Ohne Broker-/Custody-Anbindung ist die einzige moegliche Evidence eine
         *     manuelle Bestaetigung mit der Auftrags-/Bestaetigungsreferenz der
         *     ausfuehrenden Stelle und dem Ausfuehrungsdatum. Der Server speichert sie
         *     ausdruecklich als ``manual_attestation`` -- nie als Fill-Evidence.
         */
        PortfolioHandoffMarkExecuted: {
            /** Executed Note */
            executed_note?: string | null;
            /**
             * Executed On
             * Format: date
             */
            executed_on: string;
            /** External Order Reference */
            external_order_reference: string;
        };
        /**
         * PortfolioHandoffPreviewResponse
         * @description HANDOFF-PREVIEW-PARITY-001: read-only Vorschau der Handelsliste.
         *
         *     Dieselbe Funktion wie die Snapshot-Erzeugung (``snapshot_handoff``), ohne
         *     Persistieren. ``trades`` und ``snapshot_sha256`` entsprechen bei gleichen
         *     Eingaben exakt dem Snapshot einer anschliessenden Weiterleitung.
         */
        PortfolioHandoffPreviewResponse: {
            /** Confirm No Existing Holdings */
            confirm_no_existing_holdings: boolean;
            /**
             * Holdings Basis
             * @enum {string}
             */
            holdings_basis: "recorded_depot" | "confirmed_no_holdings";
            /** Live Total Value Rappen */
            live_total_value_rappen: number;
            /** Position Count */
            position_count: number;
            /** Recommendation Run Id */
            recommendation_run_id: string;
            /** Snapshot Sha256 */
            snapshot_sha256: string;
            /** Trades */
            trades: Record<string, unknown>[];
        };
        /** PortfolioHandoffResponse */
        PortfolioHandoffResponse: {
            /** Cancelled At */
            cancelled_at: string | null;
            /** Cancelled By */
            cancelled_by: string | null;
            /** Cancelled Reason */
            cancelled_reason: string | null;
            /** Created At */
            created_at: string;
            /** Created By */
            created_by: string;
            /** Executed At */
            executed_at: string | null;
            /** Executed By */
            executed_by: string | null;
            /** Executed Note */
            executed_note: string | null;
            /** Execution Confirmed On */
            execution_confirmed_on?: string | null;
            /** Execution Evidence Kind */
            execution_evidence_kind?: string | null;
            /** Execution External Reference */
            execution_external_reference?: string | null;
            /** Holdings Basis */
            holdings_basis?: ("recorded_depot" | "confirmed_no_holdings") | null;
            /** Id */
            id: string;
            /** Live Total Value Rappen */
            live_total_value_rappen: number;
            /** Mandate Id */
            mandate_id: string;
            /** Note */
            note: string | null;
            /** Position Count */
            position_count: number;
            /** Recipient Channel */
            recipient_channel: string | null;
            /** Recipient Name */
            recipient_name: string;
            /** Recommendation Run Id */
            recommendation_run_id: string | null;
            /** Snapshot Sha256 */
            snapshot_sha256?: string | null;
            /**
             * Status
             * @enum {string}
             */
            status: "Vorbereitet" | "Gesendet" | "Ausgeführt" | "Storniert";
            /** Trade List Snapshot Json */
            trade_list_snapshot_json: string;
            /** Updated At */
            updated_at: string;
        };
        /**
         * ProductBulkImportRequest
         * @description Fondsuniversum Bulk-API-Import (2026-08-05): programmatische
         *     Schnittstelle fuer externe Asset-Manager-Systeme -- Feldmenge ist
         *     identisch zu ProductCreate (auch hier gibt es bewusst kein
         *     tenant_id-Feld, siehe ProductCreate/create_product).
         */
        ProductBulkImportRequest: {
            /** Products */
            products: components["schemas"]["ProductCreate"][];
        };
        /** ProductCreate */
        ProductCreate: {
            /**
             * Asset Class
             * @enum {string}
             */
            asset_class: "Aktien" | "Obligationen" | "Immobilien" | "Alternative" | "Liquidität";
            /** Climate Benchmark */
            climate_benchmark?: string | null;
            /** Country Exposure Json */
            country_exposure_json?: string | null;
            /** Credit Rating */
            credit_rating?: string | null;
            /**
             * Currency
             * @default CHF
             */
            currency?: string;
            /** Currency Exposure Json */
            currency_exposure_json?: string | null;
            /** Duration Years X10 */
            duration_years_x10?: number | null;
            /** Esg Rating */
            esg_rating?: string | null;
            /** Esg Score X10 */
            esg_score_x10?: number | null;
            /** Isin */
            isin?: string | null;
            /** Liquidity Tier */
            liquidity_tier?: string | null;
            /** Product Name */
            product_name: string;
            /** Product Type */
            product_type: string;
            /** Provider */
            provider?: string | null;
            /** Sector Exposure Json */
            sector_exposure_json?: string | null;
            /** Sfdr Class */
            sfdr_class?: ("6" | "8" | "9") | null;
            /** Sub Asset Class */
            sub_asset_class?: string | null;
            /** Suitability Max Position Bps */
            suitability_max_position_bps?: number | null;
            /** Suitability Profile From */
            suitability_profile_from: number;
            /** Suitability Profile To */
            suitability_profile_to: number;
            /**
             * Suitability Prohibited
             * @default false
             */
            suitability_prohibited?: boolean;
            /**
             * Suitability Requires Appropriateness
             * @default false
             */
            suitability_requires_appropriateness?: boolean;
            /**
             * Suitability Requires Override
             * @default false
             */
            suitability_requires_override?: boolean;
            /** Suitability Service Modes */
            suitability_service_modes?: ("investment_advice" | "portfolio_management" | "financial_planning" | "reporting_only")[];
            /** Symbol */
            symbol?: string | null;
            /** Ter Bps */
            ter_bps?: number | null;
            /** Theme Tags */
            theme_tags?: string | null;
        };
        /**
         * ProductEligibilityApprovalRequest
         * @description ELIG-GOVERNANCE-001 (2026-10-22): Body fuer POST /products/{id}/
         *     eligibility-rule/approve. Standard ist Vier-Augen (leerer Body). Die
         *     Einzelberater-Ausnahme verlangt ausdruecklich
         *     single_approver_attestation=true UND eine Begruendung; ob sie zulaessig
         *     ist (genau eine freigabeberechtigte Person), prueft der Server.
         */
        ProductEligibilityApprovalRequest: {
            /** Attestation Reason */
            attestation_reason?: string | null;
            /**
             * Single Approver Attestation
             * @default false
             */
            single_approver_attestation?: boolean;
        };
        /** ProductEligibilityApprovalResponse */
        ProductEligibilityApprovalResponse: {
            /** Approval Mode */
            approval_mode: string;
            /** Approved Rule Ids */
            approved_rule_ids: string[];
            /** Product Id */
            product_id: string;
        };
        /** ProductEligibilityDraftItem */
        ProductEligibilityDraftItem: {
            /** Authored By Current User */
            authored_by_current_user: boolean;
            /** Product Id */
            product_id: string;
            /** Rule Ids */
            rule_ids: string[];
        };
        /** ProductEligibilityDraftsResponse */
        ProductEligibilityDraftsResponse: {
            /** Approver Count */
            approver_count: number;
            /** Current User Is Sole Approver */
            current_user_is_sole_approver: boolean;
            /** Drafts */
            drafts: components["schemas"]["ProductEligibilityDraftItem"][];
        };
        /** ProductIdMappingApplyRequest */
        ProductIdMappingApplyRequest: {
            /**
             * Candidate Index
             * @default 0
             */
            candidate_index?: number;
            /** Currency */
            currency?: string | null;
            /** Exchange Code */
            exchange_code?: string | null;
            /** Isin */
            isin?: string | null;
            /** Mic Code */
            mic_code?: string | null;
            /**
             * Overwrite Symbol
             * @default false
             */
            overwrite_symbol?: boolean;
            /** Preferred Figi */
            preferred_figi?: string | null;
            /** Product Id */
            product_id: string;
            /** Symbol */
            symbol?: string | null;
        };
        /** ProductIdMappingApplyResponse */
        ProductIdMappingApplyResponse: {
            applied: components["schemas"]["ProductIdMappingCandidate"];
            /** Preview Warning */
            preview_warning?: string | null;
            product: components["schemas"]["ProductResponse"];
        };
        /** ProductIdMappingBatchApplyRequest */
        ProductIdMappingBatchApplyRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run?: boolean;
            /**
             * Limit
             * @default 20
             */
            limit?: number;
            /**
             * Overwrite Symbol
             * @default false
             */
            overwrite_symbol?: boolean;
        };
        /** ProductIdMappingBatchApplyResponse */
        ProductIdMappingBatchApplyResponse: {
            /** Applied */
            applied: number;
            /** Dry Run */
            dry_run: boolean;
            /** Failed */
            failed: number;
            /** Items */
            items?: components["schemas"]["ProductIdMappingBatchItem"][];
            /** Processed */
            processed: number;
            /** Skipped */
            skipped: number;
        };
        /** ProductIdMappingBatchItem */
        ProductIdMappingBatchItem: {
            applied_candidate?: components["schemas"]["ProductIdMappingCandidate"] | null;
            /** Detail */
            detail?: string | null;
            /** Isin */
            isin?: string | null;
            /** Product Id */
            product_id: string;
            /** Product Name */
            product_name: string;
            /** Status */
            status: string;
        };
        /** ProductIdMappingCandidate */
        ProductIdMappingCandidate: {
            /** Composite Figi */
            composite_figi?: string | null;
            /** Exch Code */
            exch_code?: string | null;
            /** Figi */
            figi?: string | null;
            /** Market Sector */
            market_sector?: string | null;
            /** Name */
            name?: string | null;
            /** Security Description */
            security_description?: string | null;
            /** Security Type */
            security_type?: string | null;
            /** Security Type2 */
            security_type2?: string | null;
            /** Share Class Figi */
            share_class_figi?: string | null;
            /** Ticker */
            ticker?: string | null;
        };
        /** ProductIdMappingPreviewRequest */
        ProductIdMappingPreviewRequest: {
            /** Currency */
            currency?: string | null;
            /** Exchange Code */
            exchange_code?: string | null;
            /** Isin */
            isin?: string | null;
            /** Mic Code */
            mic_code?: string | null;
            /** Product Id */
            product_id?: string | null;
            /** Symbol */
            symbol?: string | null;
        };
        /** ProductIdMappingPreviewResponse */
        ProductIdMappingPreviewResponse: {
            /** Api Key Used */
            api_key_used: boolean;
            /** Candidates */
            candidates?: components["schemas"]["ProductIdMappingCandidate"][];
            /** Error */
            error?: string | null;
            /** Request Job */
            request_job: Record<string, unknown>;
            /** Resolved From */
            resolved_from: Record<string, unknown>;
            /** Source */
            source: string;
            /** Warning */
            warning?: string | null;
        };
        /** ProductImportResponse */
        ProductImportResponse: {
            /** Created */
            created: number;
            /** Failed */
            failed: number;
            /** Items */
            items?: components["schemas"]["ProductImportResultItem"][];
            /** Processed */
            processed: number;
            /** Updated */
            updated: number;
        };
        /** ProductImportResultItem */
        ProductImportResultItem: {
            /** Error */
            error?: string | null;
            /** Product Id */
            product_id?: string | null;
            /** Product Name */
            product_name?: string | null;
            /** Row */
            row: number;
            /**
             * Status
             * @enum {string}
             */
            status: "created" | "updated" | "failed";
        };
        /** ProductMarketOverrideRequest */
        ProductMarketOverrideRequest: {
            /** Lookup Mode Override */
            lookup_mode_override?: ("direct" | "proxy" | "synthetic_par") | null;
            /** Lookup Symbol Override */
            lookup_symbol_override?: string | null;
        };
        /** ProductMarketOverrideResponse */
        ProductMarketOverrideResponse: {
            /** Id */
            id: string;
            /** Lookup Mode Override */
            lookup_mode_override?: string | null;
            /** Lookup Symbol Override */
            lookup_symbol_override?: string | null;
            /** Product Name */
            product_name: string;
            /** Resolved Market Profile */
            resolved_market_profile: Record<string, unknown>;
        };
        /** ProductReferenceApplyRequest */
        ProductReferenceApplyRequest: {
            /**
             * Candidate Index
             * @default 0
             */
            candidate_index?: number;
            /** Currency */
            currency?: string | null;
            /** Exchange Code */
            exchange_code?: string | null;
            /** Isin */
            isin?: string | null;
            /**
             * Overwrite Currency
             * @default false
             */
            overwrite_currency?: boolean;
            /**
             * Overwrite Name
             * @default false
             */
            overwrite_name?: boolean;
            /**
             * Overwrite Symbol
             * @default false
             */
            overwrite_symbol?: boolean;
            /** Product Id */
            product_id: string;
            /** Product Name */
            product_name?: string | null;
            /** Symbol */
            symbol?: string | null;
        };
        /** ProductReferenceApplyResponse */
        ProductReferenceApplyResponse: {
            applied: components["schemas"]["ProductReferenceCandidate"];
            /** Preview Warning */
            preview_warning?: string | null;
            product: components["schemas"]["ProductResponse"];
        };
        /** ProductReferenceBatchApplyRequest */
        ProductReferenceBatchApplyRequest: {
            /**
             * Dry Run
             * @default false
             */
            dry_run?: boolean;
            /**
             * Limit
             * @default 20
             */
            limit?: number;
            /**
             * Overwrite Currency
             * @default false
             */
            overwrite_currency?: boolean;
            /**
             * Overwrite Name
             * @default false
             */
            overwrite_name?: boolean;
            /**
             * Overwrite Symbol
             * @default false
             */
            overwrite_symbol?: boolean;
        };
        /** ProductReferenceBatchApplyResponse */
        ProductReferenceBatchApplyResponse: {
            /** Applied */
            applied: number;
            /** Dry Run */
            dry_run: boolean;
            /** Failed */
            failed: number;
            /** Items */
            items?: components["schemas"]["ProductReferenceBatchItem"][];
            /** Processed */
            processed: number;
            /** Skipped */
            skipped: number;
        };
        /** ProductReferenceBatchItem */
        ProductReferenceBatchItem: {
            applied_candidate?: components["schemas"]["ProductReferenceCandidate"] | null;
            /** Detail */
            detail?: string | null;
            /** Isin */
            isin?: string | null;
            /** Product Id */
            product_id: string;
            /** Product Name */
            product_name: string;
            /** Status */
            status: string;
            /** Symbol */
            symbol?: string | null;
        };
        /** ProductReferenceCandidate */
        ProductReferenceCandidate: {
            /** Country */
            country?: string | null;
            /** Currency */
            currency?: string | null;
            /** Exchange Code */
            exchange_code?: string | null;
            /** Instrument Type */
            instrument_type?: string | null;
            /** Isin */
            isin?: string | null;
            /**
             * Match Score
             * @default 0
             */
            match_score?: number;
            /** Name */
            name?: string | null;
            /** Symbol */
            symbol?: string | null;
        };
        /** ProductReferencePreviewRequest */
        ProductReferencePreviewRequest: {
            /** Currency */
            currency?: string | null;
            /** Exchange Code */
            exchange_code?: string | null;
            /** Isin */
            isin?: string | null;
            /** Product Id */
            product_id?: string | null;
            /** Product Name */
            product_name?: string | null;
            /** Symbol */
            symbol?: string | null;
        };
        /** ProductReferencePreviewResponse */
        ProductReferencePreviewResponse: {
            /** Api Key Used */
            api_key_used: boolean;
            /** Candidates */
            candidates?: components["schemas"]["ProductReferenceCandidate"][];
            /** Query Used */
            query_used: Record<string, unknown>;
            /** Resolved From */
            resolved_from: Record<string, unknown>;
            /** Source */
            source: string;
            /** Warning */
            warning?: string | null;
        };
        /** ProductResponse */
        ProductResponse: {
            /** Asset Class */
            asset_class: string;
            /** Climate Benchmark */
            climate_benchmark?: string | null;
            /** Composite Figi */
            composite_figi?: string | null;
            /** Country Exposure Json */
            country_exposure_json?: string | null;
            /** Created At */
            created_at: string;
            /** Credit Rating */
            credit_rating?: string | null;
            /** Currency */
            currency: string;
            /** Currency Exposure Json */
            currency_exposure_json?: string | null;
            /** Duration Years X10 */
            duration_years_x10?: number | null;
            /** Esg Data Seed Fields */
            readonly esg_data_seed_fields: string[];
            /** Esg Data Status */
            readonly esg_data_status: string;
            /** Esg Rating */
            esg_rating: string | null;
            /** Esg Score X10 */
            esg_score_x10?: number | null;
            /** Exchange Code */
            exchange_code?: string | null;
            /** Figi */
            figi?: string | null;
            /** Id */
            id: string;
            /** Is Active */
            is_active: number;
            /** Isin */
            isin: string | null;
            /** Liquidity Tier */
            liquidity_tier?: string | null;
            /** Lookup Mode Override */
            lookup_mode_override?: string | null;
            /** Lookup Symbol Override */
            lookup_symbol_override?: string | null;
            /** Mapping Provider */
            mapping_provider?: string | null;
            /** Mapping Resolved At */
            mapping_resolved_at?: string | null;
            /** Market Sector */
            market_sector?: string | null;
            /** Product Name */
            product_name: string;
            /** Product Type */
            product_type: string;
            /** Provider */
            provider: string | null;
            /** Reference Data Provider */
            reference_data_provider?: string | null;
            /** Reference Data Refreshed At */
            reference_data_refreshed_at?: string | null;
            /** Sector Exposure Json */
            sector_exposure_json?: string | null;
            /** Security Type */
            security_type?: string | null;
            /** Security Type2 */
            security_type2?: string | null;
            /** Sfdr Class */
            sfdr_class: string | null;
            /** Share Class Figi */
            share_class_figi?: string | null;
            /** Sub Asset Class */
            sub_asset_class: string | null;
            /** Symbol */
            symbol: string | null;
            /** Tenant Id */
            tenant_id?: string | null;
            /** Ter Bps */
            ter_bps: number | null;
            /** Theme Tags */
            theme_tags?: string[] | null;
            /** Updated At */
            updated_at: string;
        };
        /** ProductUniverseEntryCreate */
        ProductUniverseEntryCreate: {
            /** Jurisdiction */
            jurisdiction: string;
            /** Override Ter Bps */
            override_ter_bps?: number | null;
            /** Product Id */
            product_id: string;
        };
        /** ProductUniverseEntryResponse */
        ProductUniverseEntryResponse: {
            /** Created At */
            created_at: string;
            /** Created By */
            created_by: string;
            /** Id */
            id: string;
            /** Jurisdiction */
            jurisdiction: string;
            /** Override Ter Bps */
            override_ter_bps: number | null;
            /** Product Id */
            product_id: string;
            /** Tenant Id */
            tenant_id: string;
            /** Updated At */
            updated_at: string;
        };
        /** ProductUniverseEntryUpdate */
        ProductUniverseEntryUpdate: {
            /** Override Ter Bps */
            override_ter_bps?: number | null;
        };
        /**
         * ProductUpdate
         * @description Sprint U-P10: Berater editiert Produkt-Metadaten (Admin-RBAC).
         *     Alle Felder optional — nur gesetzte werden geupdated.
         */
        ProductUpdate: {
            /** Asset Class */
            asset_class?: ("Aktien" | "Obligationen" | "Immobilien" | "Alternative" | "Liquidität") | null;
            /** Climate Benchmark */
            climate_benchmark?: string | null;
            /** Country Exposure Json */
            country_exposure_json?: string | null;
            /** Credit Rating */
            credit_rating?: string | null;
            /** Currency */
            currency?: string | null;
            /** Currency Exposure Json */
            currency_exposure_json?: string | null;
            /** Duration Years X10 */
            duration_years_x10?: number | null;
            /** Esg Rating */
            esg_rating?: string | null;
            /** Esg Score X10 */
            esg_score_x10?: number | null;
            /** Is Active */
            is_active?: number | null;
            /** Liquidity Tier */
            liquidity_tier?: string | null;
            /** Product Name */
            product_name?: string | null;
            /** Provider */
            provider?: string | null;
            /** Sector Exposure Json */
            sector_exposure_json?: string | null;
            /** Sfdr Class */
            sfdr_class?: ("6" | "8" | "9") | null;
            /** Sub Asset Class */
            sub_asset_class?: string | null;
            /** Ter Bps */
            ter_bps?: number | null;
            /** Theme Tags */
            theme_tags?: string | null;
        };
        /** RecommendationGenerateRequest */
        RecommendationGenerateRequest: {
            /** Depot Bank */
            depot_bank?: string | null;
            preferences?: components["schemas"]["AllocationPreferencesPayload"] | null;
            /**
             * Run Type
             * @default Optimizer
             * @enum {string}
             */
            run_type?: "Initial" | "Review" | "WhatIf" | "Optimizer";
            /** Target Allocation Id */
            target_allocation_id?: string | null;
        };
        /** RecommendationGenerateResponse */
        RecommendationGenerateResponse: {
            /** Advisory Wealth Rappen */
            advisory_wealth_rappen: number;
            /** Average Ter Bps */
            average_ter_bps: number;
            /**
             * Average Ter Coverage Bps
             * @default 0
             */
            average_ter_coverage_bps?: number;
            /**
             * Context Status
             * @default current
             */
            context_status?: string;
            /** Expected Return Bps */
            expected_return_bps: number;
            /** Expected Volatility Bps */
            expected_volatility_bps: number;
            /** Implementation Steps */
            implementation_steps: string[];
            /** Investable Advisory Wealth Rappen */
            investable_advisory_wealth_rappen?: number | null;
            live_rebalancing?: components["schemas"]["LiveRebalancingResponse"] | null;
            /** Market Data Quality */
            market_data_quality?: Record<string, unknown>;
            /**
             * Missing Ter Positions Count
             * @default 0
             */
            missing_ter_positions_count?: number;
            /** Positions */
            positions: components["schemas"]["RecommendationPositionDetailResponse"][];
            run: components["schemas"]["RecommendationRunResponse"];
            /** Target Allocation Id */
            target_allocation_id: string;
            /** Warnings */
            warnings: string[];
        };
        /** RecommendationHoldingResponse */
        RecommendationHoldingResponse: {
            /** As Of Date */
            as_of_date: string | null;
            /** Avg Cost Price Rappen */
            avg_cost_price_rappen: number | null;
            /** Created At */
            created_at: string;
            /** Custody Account Number */
            custody_account_number: string | null;
            /** Depot Bank */
            depot_bank: string | null;
            /** Id */
            id: string;
            /** Market Value Rappen */
            market_value_rappen: number | null;
            /** Notes */
            notes: string | null;
            /** Product Id */
            product_id: string;
            /** Recommendation Position Id */
            recommendation_position_id: string;
            /** Run Id */
            run_id: string;
            /** Source */
            source: string;
            /** Units Milli */
            units_milli: number | null;
            /** Updated At */
            updated_at: string;
        };
        /** RecommendationHoldingUpsert */
        RecommendationHoldingUpsert: {
            /** As Of Date */
            as_of_date?: string | null;
            /** Avg Cost Price Rappen */
            avg_cost_price_rappen?: number | null;
            /** Custody Account Number */
            custody_account_number?: string | null;
            /** Depot Bank */
            depot_bank?: string | null;
            /** Market Value Rappen */
            market_value_rappen?: number | null;
            /** Notes */
            notes?: string | null;
            /**
             * Source
             * @default manual
             * @enum {string}
             */
            source?: "manual" | "custody_import";
            /** Units Milli */
            units_milli?: number | null;
        };
        /** RecommendationPositionCreate */
        RecommendationPositionCreate: {
            /** Product Id */
            product_id: string;
            /** Rationale */
            rationale?: string | null;
            /** Target Amount Rappen */
            target_amount_rappen?: number | null;
            /** Target Weight Bps */
            target_weight_bps: number;
        };
        /** RecommendationPositionDetailResponse */
        RecommendationPositionDetailResponse: {
            /** Asset Class */
            asset_class: string;
            /** Currency */
            currency: string;
            /** Current Market Value Rappen */
            current_market_value_rappen?: number | null;
            /** Current Units Milli */
            current_units_milli?: number | null;
            /** Current Weight Bps */
            current_weight_bps?: number | null;
            /** Delta Weight Bps */
            delta_weight_bps?: number | null;
            /** Exchange Code */
            exchange_code?: string | null;
            /** Figi */
            figi?: string | null;
            /** Holding As Of Date */
            holding_as_of_date?: string | null;
            /** Holding Avg Cost Price Rappen */
            holding_avg_cost_price_rappen?: number | null;
            /** Holding Custody Account Number */
            holding_custody_account_number?: string | null;
            /** Holding Depot Bank */
            holding_depot_bank?: string | null;
            /** Holding Market Value Rappen */
            holding_market_value_rappen?: number | null;
            /** Holding Notes */
            holding_notes?: string | null;
            /**
             * Holding Present
             * @default false
             */
            holding_present?: boolean;
            /** Holding Source */
            holding_source?: string | null;
            /** Holding Units Milli */
            holding_units_milli?: number | null;
            /** Id */
            id: string;
            /** Implied Units Milli */
            implied_units_milli?: number | null;
            /** Isin */
            isin: string | null;
            /** Latest Price Date */
            latest_price_date?: string | null;
            /** Latest Price Rappen */
            latest_price_rappen?: number | null;
            /** Lookup Mode */
            lookup_mode?: string | null;
            /** Lookup Symbol */
            lookup_symbol?: string | null;
            /** Mapping Provider */
            mapping_provider?: string | null;
            /** Mapping Resolved At */
            mapping_resolved_at?: string | null;
            /** Price Age Days */
            price_age_days?: number | null;
            /** Price Change Bps */
            price_change_bps?: number | null;
            /** Price Is Fresh */
            price_is_fresh?: boolean | null;
            /** Price Source */
            price_source?: string | null;
            /** Pricing Note */
            pricing_note?: string | null;
            /** Product Id */
            product_id: string;
            /** Product Name */
            product_name: string;
            /** Product Type */
            product_type: string;
            /** Provider */
            provider: string | null;
            /** Rationale */
            rationale: string | null;
            /** Rebalance Action */
            rebalance_action?: string | null;
            /** Rebalance Action Code */
            rebalance_action_code?: string | null;
            /** Rebalance Action Label */
            rebalance_action_label?: string | null;
            /** Rebalance Amount Rappen */
            rebalance_amount_rappen?: number | null;
            /** Reference Data Provider */
            reference_data_provider?: string | null;
            /** Reference Data Refreshed At */
            reference_data_refreshed_at?: string | null;
            /** Reference Lookup Mode */
            reference_lookup_mode?: string | null;
            /** Reference Price Date */
            reference_price_date?: string | null;
            /** Reference Price Fetched At */
            reference_price_fetched_at?: string | null;
            /** Reference Price Rappen */
            reference_price_rappen?: number | null;
            /** Reference Price Source */
            reference_price_source?: string | null;
            /** Reference Recalibrated */
            reference_recalibrated?: boolean | null;
            /** Run Id */
            run_id: string;
            /**
             * Source Sub Asset Classes
             * @default []
             */
            source_sub_asset_classes?: string[];
            /** Sub Asset Class */
            sub_asset_class: string | null;
            /** Symbol */
            symbol: string | null;
            /** Target Amount Rappen */
            target_amount_rappen: number | null;
            /** Target Weight Bps */
            target_weight_bps: number;
            /** Ter Bps */
            ter_bps: number | null;
            /** Valuation Basis */
            valuation_basis?: string | null;
        };
        /** RecommendationPositionResponse */
        RecommendationPositionResponse: {
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /** Product Id */
            product_id: string;
            /** Rationale */
            rationale: string | null;
            /** Reference Lookup Mode */
            reference_lookup_mode?: string | null;
            /** Reference Price Date */
            reference_price_date?: string | null;
            /** Reference Price Fetched At */
            reference_price_fetched_at?: string | null;
            /** Reference Price Rappen */
            reference_price_rappen?: number | null;
            /** Reference Price Source */
            reference_price_source?: string | null;
            /** Run Id */
            run_id: string;
            /** Target Amount Rappen */
            target_amount_rappen: number | null;
            /** Target Weight Bps */
            target_weight_bps: number;
            /** Updated At */
            updated_at: string;
            /** Warnings */
            warnings?: string[];
        };
        /** RecommendationRunCreate */
        RecommendationRunCreate: {
            /** Assessment Id */
            assessment_id?: string | null;
            /** Capital Market Assumptions Id */
            capital_market_assumptions_id?: string | null;
            /** Fee Assumptions Json */
            fee_assumptions_json?: string | null;
            /** Objective Summary */
            objective_summary?: string | null;
            /**
             * Other Assets Included
             * @default false
             */
            other_assets_included?: boolean;
            /** Policy Id */
            policy_id: string;
            /**
             * Run Type
             * @enum {string}
             */
            run_type: "Initial" | "Review" | "WhatIf" | "Optimizer";
            /** Target Allocation Id */
            target_allocation_id?: string | null;
            /** Weighting Regime */
            weighting_regime?: ("Equal-Weight" | "Ranked-Weight" | "Custom") | null;
        };
        /** RecommendationRunResponse */
        RecommendationRunResponse: {
            /** Assessment Id */
            assessment_id: string | null;
            /** Client Id */
            client_id: string;
            /** Created At */
            created_at: string;
            /** Created By */
            created_by: string;
            /** Id */
            id: string;
            /** Mandate Id */
            mandate_id: string;
            /** Objective Summary */
            objective_summary: string | null;
            /** Other Assets Included */
            other_assets_included: number;
            /** Policy Id */
            policy_id: string;
            /** Result Status */
            result_status: string;
            /** Run Type */
            run_type: string;
            /** Target Allocation Id */
            target_allocation_id: string | null;
            /** Updated At */
            updated_at: string;
            /** Weighting Regime */
            weighting_regime: string | null;
        };
        /** RefreshTokenRequest */
        RefreshTokenRequest: {
            /** Refresh Token */
            refresh_token: string;
        };
        /**
         * ReportNotesHistoryEntry
         * @description Sprint U-37b (2026-06-04): Ein Edit-Snapshot aus
         *     previous_versions_json.
         */
        ReportNotesHistoryEntry: {
            /** Changes */
            changes?: {
                [key: string]: {
                    [key: string]: string | null;
                };
            };
            /** Edited At */
            edited_at: string;
            /** Edited By */
            edited_by: string;
        };
        /**
         * ReportNotesResponse
         * @description GET /mandates/{id}/report-notes — leere Felder bleiben None.
         */
        ReportNotesResponse: {
            /** Aa Anmerkungen */
            aa_anmerkungen?: string | null;
            /** Branchen Analyse */
            branchen_analyse?: string | null;
            /** Created At */
            created_at?: string | null;
            /** Id */
            id?: string | null;
            /** Last Edited At */
            last_edited_at?: string | null;
            /** Last Edited By */
            last_edited_by?: string | null;
            /** Mandate Id */
            mandate_id: string;
            /** Previous Versions */
            previous_versions?: components["schemas"]["ReportNotesHistoryEntry"][];
            /**
             * Previous Versions Total
             * @default 0
             */
            previous_versions_total?: number;
            /** Updated At */
            updated_at?: string | null;
            /** Vorgehen Block Optimierungen */
            vorgehen_block_optimierungen?: string | null;
            /** Vorgehen Block Zielstrategie */
            vorgehen_block_zielstrategie?: string | null;
            /** Vorgehen Dokumente */
            vorgehen_dokumente?: string[];
            /** Vorgehen Naechster Termin */
            vorgehen_naechster_termin?: string | null;
            /** Vorgehen Offene Fragen */
            vorgehen_offene_fragen?: string[];
            /** Vorgehen Todos */
            vorgehen_todos?: string[];
            /** Waehrungen Erklaerung */
            waehrungen_erklaerung?: string | null;
        };
        /**
         * ReportNotesUpdate
         * @description PUT /mandates/{id}/report-notes — Upsert-Payload.
         *
         *     RESOURCE-002 (Codex-Audit 2026-08-27): alle neun Felder waren ohne
         *     Zeichen-/Item-/Itemlaengengrenze -- ein 4-MiB-Freitext oder 200'000
         *     To-dos wurden klaglos akzeptiert. jeder PUT haengt zudem einen
         *     Vorher/Nachher-Snapshot an die append-only Historie an
         *     (services/notes_versioning.py), die vollstaendig ausgeliefert wird --
         *     wiederholte grosse Edits vervielfachen die gespeicherte/ausgelieferte
         *     Groesse dauerhaft. Diese Feldschranken decken nur die akuteste
         *     Einzelfeld-Groesse ab; die weitergehenden Forderungen des Audits
         *     (normalisierte Notes-Tabelle, History-Pagination, Retention-/Legal-
         *     Hold-Policy, Tenant-Speicherquota) sind ein groesseres, separates
         *     Vorhaben und bewusst NICHT Teil dieses Fixes.
         */
        ReportNotesUpdate: {
            /** Aa Anmerkungen */
            aa_anmerkungen?: string | null;
            /** Branchen Analyse */
            branchen_analyse?: string | null;
            /** Data Classification */
            data_classification?: ("synthetic" | "real") | null;
            /** Vorgehen Block Optimierungen */
            vorgehen_block_optimierungen?: string | null;
            /** Vorgehen Block Zielstrategie */
            vorgehen_block_zielstrategie?: string | null;
            /** Vorgehen Dokumente */
            vorgehen_dokumente?: string[] | null;
            /** Vorgehen Naechster Termin */
            vorgehen_naechster_termin?: string | null;
            /** Vorgehen Offene Fragen */
            vorgehen_offene_fragen?: string[] | null;
            /** Vorgehen Todos */
            vorgehen_todos?: string[] | null;
            /** Waehrungen Erklaerung */
            waehrungen_erklaerung?: string | null;
        };
        /** ReviewTriggerCreate */
        ReviewTriggerCreate: {
            /** Frequency */
            frequency?: string | null;
            /** Next Due At */
            next_due_at?: string | null;
            /** Threshold Bps */
            threshold_bps?: number | null;
            /** Trigger Name */
            trigger_name: string;
            /**
             * Trigger Type
             * @enum {string}
             */
            trigger_type: "Zeit" | "Markt" | "Ereignis";
        };
        /**
         * ReviewTriggerFrequencyUpdate
         * @description REVIEW-STATE-004 (Kontrollrunde 2026-09-24): erlaubt dem Berater, das
         *     Wiederholungsintervall eines Zeit-Triggers explizit zu setzen (z.B.
         *     "halbjährlich" statt des Default-"jährlich" bei erhöhtem Risiko), ohne
         *     dass der naechste System-Trigger-Refresh es kommentarlos auf "jährlich"
         *     zuruecksetzt.
         */
        ReviewTriggerFrequencyUpdate: {
            /**
             * Frequency
             * @enum {string}
             */
            frequency: "monatlich" | "quartalsweise" | "halbjährlich" | "jährlich" | "einmalig";
        };
        /** ReviewTriggerResolve */
        ReviewTriggerResolve: {
            /**
             * Decision
             * @enum {string}
             */
            decision: "Erledigt" | "Massnahme eingeleitet" | "Kein Handlungsbedarf" | "Vertagt";
            /** Triggered Notes */
            triggered_notes?: string | null;
        };
        /** ReviewTriggerResponse */
        ReviewTriggerResponse: {
            /** Calendar Exported */
            calendar_exported: number;
            /** Created At */
            created_at: string;
            /** Frequency */
            frequency: string | null;
            /** Id */
            id: string;
            /** Is System */
            is_system: number;
            /** Last Triggered At */
            last_triggered_at: string | null;
            /** Mandate Id */
            mandate_id: string;
            /** Next Due At */
            next_due_at: string | null;
            /** Previous Next Due At */
            previous_next_due_at?: string | null;
            /** Resolution Decision */
            resolution_decision?: string | null;
            /** Resolved At */
            resolved_at?: string | null;
            /** Resolved By */
            resolved_by?: string | null;
            /** Status */
            status: string;
            /** Threshold Bps */
            threshold_bps: number | null;
            /** Trigger Name */
            trigger_name: string;
            /** Trigger Type */
            trigger_type: string;
            /** Triggered At */
            triggered_at: string | null;
            /** Triggered Notes */
            triggered_notes: string | null;
            /** Triggered Value */
            triggered_value: string | null;
            /** Updated At */
            updated_at: string;
        };
        /** RiskAssessmentAnswerResponse */
        RiskAssessmentAnswerResponse: {
            /** Answer Label */
            answer_label: string;
            /** Answer Points */
            answer_points: number;
            /** Created At */
            created_at: string;
            /** Id */
            id: string;
            /** Question Number */
            question_number: number;
            /** Question Section */
            question_section: string;
        };
        /** RiskAssessmentCreate */
        RiskAssessmentCreate: {
            /** Answers */
            answers?: Record<string, unknown>[] | null;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Income Sources Json */
            income_sources_json?: string | null;
            /**
             * Investment Horizon Label
             * @enum {string}
             */
            investment_horizon_label: "Bis 2 Jahre" | "2 bis 3 Jahre" | "4 bis 5 Jahre" | "6 bis 7 Jahre" | "8 bis 11 Jahre" | "Mehr als 12 Jahre" | "0 bis 4 Jahre" | "5 bis 7 Jahre" | "12 Jahre und mehr" | "1 bis 3 Jahre" | "3 bis 5 Jahre" | "5 bis 10 Jahre" | "10 Jahre und mehr";
            /** Investment Horizon Years */
            investment_horizon_years: number;
            /** Knowledge Instruments Json */
            knowledge_instruments_json?: string | null;
            /** Knowledge Services Json */
            knowledge_services_json?: string | null;
            /** Q Income Points */
            q_income_points: number;
            /** Q Investment Goal Points */
            q_investment_goal_points: number;
            /** Q Obligations Points */
            q_obligations_points: number;
            /** Q Risk Behavior Points */
            q_risk_behavior_points: number;
            /** Q Risk Preference Points */
            q_risk_preference_points: number;
            /** Q Savings Points */
            q_savings_points: number;
            /** Q Wealth Points */
            q_wealth_points: number;
        };
        /** RiskAssessmentOverride */
        RiskAssessmentOverride: {
            /** Expected Assessment Version */
            expected_assessment_version?: number | null;
            /** Expected Override Decision Id */
            expected_override_decision_id?: string | null;
            /**
             * Override Client Confirmed
             * @default false
             */
            override_client_confirmed?: boolean;
            /**
             * Override Profile
             * @enum {string}
             */
            override_profile: "Kapitalschutz" | "Defensiv" | "Ausgewogen" | "Wachstumsorientiert" | "Dynamisch" | "Aktien";
            /** Override Reason */
            override_reason: string;
            /** Override Score X10 */
            override_score_x10: number;
            /**
             * Override Warning Delivered
             * @default false
             */
            override_warning_delivered?: boolean;
            /** Override Warning Document Id */
            override_warning_document_id?: string | null;
            /** Remediation */
            remediation?: "legacy_remediation" | null;
        };
        /** RiskAssessmentResponse */
        RiskAssessmentResponse: {
            /**
             * Answers
             * @default []
             */
            answers?: components["schemas"]["RiskAssessmentAnswerResponse"][];
            /** Assessed At */
            assessed_at: string;
            /** Assessed By */
            assessed_by: string;
            /** Client Signed At */
            client_signed_at?: string | null;
            /** Client Signed Method */
            client_signed_method?: string | null;
            /** Created At */
            created_at: string;
            /** Final Profile */
            final_profile: string;
            /** Final Score X10 */
            final_score_x10: number;
            /** Id */
            id: string;
            /** Income Sources Json */
            income_sources_json?: string | null;
            /** Investment Horizon Label */
            investment_horizon_label: string;
            /** Investment Horizon Years */
            investment_horizon_years: number;
            /** Is Current */
            is_current: number;
            /** Is Overridden */
            is_overridden: number;
            /** Knowledge Instruments Json */
            knowledge_instruments_json?: string | null;
            /** Knowledge Services Json */
            knowledge_services_json?: string | null;
            /** Mandate Id */
            mandate_id: string;
            /** Override At */
            override_at: string | null;
            /** Override Client Confirmed */
            override_client_confirmed: number | null;
            /** Override Decision Hash */
            override_decision_hash?: string | null;
            /** Override Decision Id */
            override_decision_id?: string | null;
            /** Override Profile */
            override_profile: string | null;
            /** Override Reason */
            override_reason: string | null;
            /** Override Score X10 */
            override_score_x10: number | null;
            /** Override Warning Delivered */
            override_warning_delivered: number | null;
            /** Q Income Points */
            q_income_points: number;
            /** Q Investment Goal Points */
            q_investment_goal_points: number;
            /** Q Obligations Points */
            q_obligations_points: number;
            /** Q Risk Behavior Points */
            q_risk_behavior_points: number;
            /** Q Risk Preference Points */
            q_risk_preference_points: number;
            /** Q Savings Points */
            q_savings_points: number;
            /** Q Wealth Points */
            q_wealth_points: number;
            /** Risk Capacity Profile */
            risk_capacity_profile: string;
            /** Risk Capacity Score X10 */
            risk_capacity_score_x10: number;
            /** Risk Capacity Total */
            risk_capacity_total: number;
            /** Risk Willingness Profile */
            risk_willingness_profile: string;
            /** Risk Willingness Score X10 */
            risk_willingness_score_x10: number;
            /** Risk Willingness Total */
            risk_willingness_total: number;
            /** Signoff Hash */
            signoff_hash?: string | null;
            /** Signoff Id */
            signoff_id?: string | null;
            /** Signoff State */
            signoff_state?: string | null;
            /** Signoff Status */
            signoff_status?: string | null;
            /** Valid From */
            valid_from: string;
            /** Version */
            version: number;
        };
        /** RiskProfileSignRequest */
        RiskProfileSignRequest: {
            /** Document Id */
            document_id?: string | null;
            /** Expected Assessment Version */
            expected_assessment_version?: number | null;
            /** Expected Override Decision Id */
            expected_override_decision_id?: string | null;
            /** Expected Signoff Id */
            expected_signoff_id?: string | null;
            /** Note */
            note?: string | null;
        };
        /** RoleGrant */
        RoleGrant: {
            /** Privacy Role */
            privacy_role: string;
            /** User Id */
            user_id: string;
        };
        /** StrategySnapshotCreate */
        StrategySnapshotCreate: {
            /** Advisor Note */
            advisor_note?: string | null;
            /** Advisory Assets Rappen */
            advisory_assets_rappen: number;
            /** Band Alternatives Hi Bps */
            band_alternatives_hi_bps?: number | null;
            /** Band Alternatives Lo Bps */
            band_alternatives_lo_bps?: number | null;
            /** Band Bonds Hi Bps */
            band_bonds_hi_bps?: number | null;
            /** Band Bonds Lo Bps */
            band_bonds_lo_bps?: number | null;
            /** Band Equities Hi Bps */
            band_equities_hi_bps?: number | null;
            /** Band Equities Lo Bps */
            band_equities_lo_bps?: number | null;
            /** Band Liquidity Hi Bps */
            band_liquidity_hi_bps?: number | null;
            /** Band Liquidity Lo Bps */
            band_liquidity_lo_bps?: number | null;
            /** Band Real Estate Hi Bps */
            band_real_estate_hi_bps?: number | null;
            /** Band Real Estate Lo Bps */
            band_real_estate_lo_bps?: number | null;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Goals Summary Json */
            goals_summary_json?: string | null;
            /** Risk Profile Label */
            risk_profile_label: string;
            /** Risk Profile Score */
            risk_profile_score: number;
            /** Snapshot Date */
            snapshot_date: string;
            /** Soll Alternatives Bps */
            soll_alternatives_bps: number;
            /** Soll Bonds Bps */
            soll_bonds_bps: number;
            /** Soll Equities Bps */
            soll_equities_bps: number;
            /** Soll Liquidity Bps */
            soll_liquidity_bps: number;
            /** Soll Real Estate Bps */
            soll_real_estate_bps: number;
        };
        /** StrategySnapshotResponse */
        StrategySnapshotResponse: {
            /** Advisor Note */
            advisor_note: string | null;
            /** Advisory Assets Rappen */
            advisory_assets_rappen: number;
            /** Band Alternatives Hi Bps */
            band_alternatives_hi_bps: number | null;
            /** Band Alternatives Lo Bps */
            band_alternatives_lo_bps: number | null;
            /** Band Bonds Hi Bps */
            band_bonds_hi_bps: number | null;
            /** Band Bonds Lo Bps */
            band_bonds_lo_bps: number | null;
            /** Band Equities Hi Bps */
            band_equities_hi_bps: number | null;
            /** Band Equities Lo Bps */
            band_equities_lo_bps: number | null;
            /** Band Liquidity Hi Bps */
            band_liquidity_hi_bps: number | null;
            /** Band Liquidity Lo Bps */
            band_liquidity_lo_bps: number | null;
            /** Band Real Estate Hi Bps */
            band_real_estate_hi_bps: number | null;
            /** Band Real Estate Lo Bps */
            band_real_estate_lo_bps: number | null;
            /** Created At */
            created_at: string;
            /** Created By */
            created_by: string;
            /** Goals Summary Json */
            goals_summary_json: string | null;
            /** Id */
            id: string;
            /** Mandate Id */
            mandate_id: string;
            /** Risk Profile Label */
            risk_profile_label: string;
            /** Risk Profile Score */
            risk_profile_score: number;
            /** Snapshot Date */
            snapshot_date: string;
            /** Soll Alternatives Bps */
            soll_alternatives_bps: number;
            /** Soll Bonds Bps */
            soll_bonds_bps: number;
            /** Soll Equities Bps */
            soll_equities_bps: number;
            /** Soll Liquidity Bps */
            soll_liquidity_bps: number;
            /** Soll Real Estate Bps */
            soll_real_estate_bps: number;
            /** Updated At */
            updated_at: string;
        };
        /** SubAssetClassAssumptionResponse */
        SubAssetClassAssumptionResponse: {
            /** Approval Status */
            approval_status?: string | null;
            /** Asset Class */
            asset_class: string;
            /** Evidence Sha256 */
            evidence_sha256?: string | null;
            /** Expected Return Bps */
            expected_return_bps: number;
            /** Expected Volatility Bps */
            expected_volatility_bps: number;
            /** Source */
            source: string;
            /** Sub Asset Class */
            sub_asset_class: string;
        };
        /** SuitabilityCheckCreate */
        SuitabilityCheckCreate: {
            /** Advisory Log Id */
            advisory_log_id?: string | null;
            /**
             * Client Acknowledged
             * @default false
             */
            client_acknowledged?: boolean;
            /** Client Acknowledged At */
            client_acknowledged_at?: string | null;
            /**
             * Client Proceeding Despite
             * @default false
             */
            client_proceeding_despite?: boolean;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Document Id */
            document_id?: string | null;
            /**
             * Duty Type
             * @enum {string}
             */
            duty_type: "Eignungsprüfung" | "Angemessenheitsprüfung" | "Keine Prüfung";
            /** Knowledge Assessment Id */
            knowledge_assessment_id?: string | null;
            /** Missing Information Json */
            missing_information_json?: string | null;
            /** Recommendation Run Id */
            recommendation_run_id?: string | null;
            /**
             * Result
             * @enum {string}
             */
            result: "Geeignet" | "Nicht geeignet" | "Angemessen" | "Nicht angemessen" | "Unvollständige Information" | "Geeignet mit Einschränkung";
            /** Result Notes */
            result_notes?: string | null;
            /** Risk Assessment Id */
            risk_assessment_id?: string | null;
            /**
             * Warning Delivered
             * @default false
             */
            warning_delivered?: boolean;
            /** Warning Delivered At */
            warning_delivered_at?: string | null;
        };
        /** SuitabilityCheckResponse */
        SuitabilityCheckResponse: {
            /** Checked At */
            checked_at: string;
            /** Checked By */
            checked_by: string;
            /** Client Acknowledged */
            client_acknowledged: number;
            /** Client Id */
            client_id: string;
            /** Client Proceeding Despite */
            client_proceeding_despite: number;
            /** Created At */
            created_at: string;
            /** Duty Type */
            duty_type: string;
            /** Id */
            id: string;
            /** Mandate Id */
            mandate_id: string;
            /** Result */
            result: string;
            /** Result Notes */
            result_notes: string | null;
            /** Warning Delivered */
            warning_delivered: number;
            /** Warning Delivered At */
            warning_delivered_at: string | null;
        };
        /** TargetAllocationCreate */
        TargetAllocationCreate: {
            /** Band Alternatives Max Bps */
            band_alternatives_max_bps: number;
            /** Band Alternatives Min Bps */
            band_alternatives_min_bps: number;
            /** Band Bonds Max Bps */
            band_bonds_max_bps: number;
            /** Band Bonds Min Bps */
            band_bonds_min_bps: number;
            /** Band Equities Max Bps */
            band_equities_max_bps: number;
            /** Band Equities Min Bps */
            band_equities_min_bps: number;
            /** Band Liquidity Max Bps */
            band_liquidity_max_bps: number;
            /** Band Liquidity Min Bps */
            band_liquidity_min_bps: number;
            /** Band Real Estate Max Bps */
            band_real_estate_max_bps: number;
            /** Band Real Estate Min Bps */
            band_real_estate_min_bps: number;
            /** Based On Assessment Id */
            based_on_assessment_id?: string | null;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Expected Current Allocation Id */
            expected_current_allocation_id?: string | null;
            /** Expected Current Allocation Version */
            expected_current_allocation_version?: number | null;
            /** Override Reason */
            override_reason?: string | null;
            /** Policy Id */
            policy_id: string;
            /** Risky Fraction Bps */
            risky_fraction_bps?: number | null;
            /** Target Alternatives Bps */
            target_alternatives_bps: number;
            /** Target Bonds Bps */
            target_bonds_bps: number;
            /** Target Equities Bps */
            target_equities_bps: number;
            /** Target Liquidity Bps */
            target_liquidity_bps: number;
            /** Target Real Estate Bps */
            target_real_estate_bps: number;
        };
        /** TargetAllocationGenerateRequest */
        TargetAllocationGenerateRequest: {
            preferences?: components["schemas"]["AllocationPreferencesPayload"] | null;
        };
        /** TargetAllocationGenerateResponse */
        TargetAllocationGenerateResponse: {
            /** Advisory Wealth Rappen */
            advisory_wealth_rappen: number;
            allocation_method_comparison?: components["schemas"]["AllocationMethodComparisonResponse"] | null;
            /** Annual Net Cashflow Rappen */
            annual_net_cashflow_rappen: number;
            /** Asset Class Assumptions */
            asset_class_assumptions: components["schemas"]["AssetClassAssumptionResponse"][];
            /** Asset Class Risky Weights Bps */
            asset_class_risky_weights_bps: {
                [key: string]: number;
            };
            /** Buckets */
            buckets: components["schemas"]["AllocationBucketResponse"][];
            /**
             * Capital Inflow Rappen
             * @default 0
             */
            capital_inflow_rappen?: number;
            /** Capital Market Assumption Set */
            capital_market_assumption_set?: string | null;
            /** Capital Market Source */
            capital_market_source?: string | null;
            /**
             * Capital Net Cashflow Rappen
             * @default 0
             */
            capital_net_cashflow_rappen?: number;
            /**
             * Capital Outflow Rappen
             * @default 0
             */
            capital_outflow_rappen?: number;
            /** Cashflow Projection Series Rappen */
            cashflow_projection_series_rappen: number[];
            /** Cma Currency Guard */
            cma_currency_guard?: Record<string, unknown> | null;
            /** Current Goal Analysis */
            current_goal_analysis?: components["schemas"]["GoalAnalysisResponse"][];
            /** Expected Return Bps */
            expected_return_bps: number;
            /** Expected Volatility Bps */
            expected_volatility_bps: number;
            /**
             * External Reserve Rappen
             * @default 0
             */
            external_reserve_rappen?: number;
            /** Goal Achievability */
            goal_achievability?: Record<string, unknown>[];
            /** Goal Achievability Basis Id */
            goal_achievability_basis_id?: string | null;
            /** Goal Analysis */
            goal_analysis: components["schemas"]["GoalAnalysisResponse"][];
            /**
             * Goal Analysis Basis Id
             * @default implementation_projection_v2
             */
            goal_analysis_basis_id?: string;
            /** House Matrix Bands */
            house_matrix_bands?: {
                [key: string]: {
                    [key: string]: number;
                };
            };
            /** House Matrix Profile */
            house_matrix_profile: string;
            /** Investable Advisory Wealth Rappen */
            investable_advisory_wealth_rappen?: number | null;
            /** Knowledge Asset Class Check */
            knowledge_asset_class_check?: Record<string, unknown> | null;
            /** Limiting Factor */
            limiting_factor?: string | null;
            live_rebalancing?: components["schemas"]["LiveRebalancingResponse"] | null;
            /** Messages */
            messages?: Record<string, unknown>[];
            /** Model Basis */
            model_basis?: Record<string, unknown>;
            monte_carlo: components["schemas"]["MonteCarloResponse"];
            /** Objective Contract Evidence */
            objective_contract_evidence?: Record<string, unknown> | null;
            /** Optimizer Constraints */
            optimizer_constraints?: components["schemas"]["OptimizerConstraintResponse"][];
            /** Optimizer Goal Driver Evidence */
            optimizer_goal_driver_evidence?: Record<string, unknown> | null;
            /** Optimizer Goal Drivers */
            optimizer_goal_drivers?: components["schemas"]["OptimizerGoalDriverResponse"][];
            /** Pension Transfer Ledger Snapshot */
            pension_transfer_ledger_snapshot?: Record<string, unknown> | null;
            /** Projection Horizon */
            projection_horizon?: Record<string, unknown> | null;
            /** Reasoning */
            reasoning: string[];
            /** Recurring Cashflow Projection Series Rappen */
            recurring_cashflow_projection_series_rappen?: number[];
            /**
             * Recurring Expense Rappen
             * @default 0
             */
            recurring_expense_rappen?: number;
            /**
             * Recurring Income Rappen
             * @default 0
             */
            recurring_income_rappen?: number;
            /**
             * Recurring Net Cashflow Rappen
             * @default 0
             */
            recurring_net_cashflow_rappen?: number;
            /** Reporting Model Basis Replay */
            reporting_model_basis_replay?: Record<string, unknown> | null;
            /** Reserve Funding Ledger */
            reserve_funding_ledger?: Record<string, unknown> | null;
            /** Reserve Funding Ledger Replay */
            reserve_funding_ledger_replay?: Record<string, unknown> | null;
            /** Reserve Needed Rappen */
            reserve_needed_rappen: number;
            /** Reserve Split */
            reserve_split?: Record<string, unknown> | null;
            /** Reserve Split Replay */
            reserve_split_replay?: Record<string, unknown> | null;
            /** Risk Budget Bps */
            risk_budget_bps: number;
            /** Risk Capacity Plausibility */
            risk_capacity_plausibility?: Record<string, unknown> | null;
            /** Risky Fraction Headroom Bps */
            risky_fraction_headroom_bps: number;
            /** Risky Fraction Total Bps */
            risky_fraction_total_bps: number;
            /** Score Bucket */
            score_bucket: number;
            simulation: components["schemas"]["AllocationSimulationResponse"];
            /** Strategy Base Rappen */
            strategy_base_rappen?: number | null;
            /** Stress Evaluations */
            stress_evaluations?: Record<string, unknown> | null;
            /** Sub Allocations */
            sub_allocations: components["schemas"]["AllocationSubBucketResponse"][];
            /** Sub Asset Class Assumptions Reference */
            sub_asset_class_assumptions_reference: components["schemas"]["SubAssetClassAssumptionResponse"][];
            target_allocation: components["schemas"]["TargetAllocationResponse"];
            /** Total Wealth Rappen */
            total_wealth_rappen: number;
            /** Uncertain Inflow Sensitivity */
            uncertain_inflow_sensitivity?: Record<string, unknown> | null;
        };
        /** TargetAllocationResponse */
        TargetAllocationResponse: {
            /** Advisory Wealth At Generation Rappen */
            advisory_wealth_at_generation_rappen?: number | null;
            /** Allocation Context Hash */
            allocation_context_hash?: string | null;
            /** Approved At */
            approved_at: string | null;
            /** Approved By */
            approved_by: string | null;
            /** Band Alternatives Max Bps */
            band_alternatives_max_bps: number;
            /** Band Alternatives Min Bps */
            band_alternatives_min_bps: number;
            /** Band Bonds Max Bps */
            band_bonds_max_bps: number;
            /** Band Bonds Min Bps */
            band_bonds_min_bps: number;
            /** Band Equities Max Bps */
            band_equities_max_bps: number;
            /** Band Equities Min Bps */
            band_equities_min_bps: number;
            /** Band Liquidity Max Bps */
            band_liquidity_max_bps: number;
            /** Band Liquidity Min Bps */
            band_liquidity_min_bps: number;
            /** Band Real Estate Max Bps */
            band_real_estate_max_bps: number;
            /** Band Real Estate Min Bps */
            band_real_estate_min_bps: number;
            /** Based On Assessment Id */
            based_on_assessment_id: string | null;
            /** Capital Market Assumptions Id */
            capital_market_assumptions_id?: string | null;
            /**
             * Context Artifacts Required
             * @default 0
             */
            context_artifacts_required?: number;
            /** Created At */
            created_at: string;
            /** Effective Constraints Json */
            effective_constraints_json?: string | null;
            /** External Reserve At Generation Rappen */
            external_reserve_at_generation_rappen?: number | null;
            /** Goal Achievability Json */
            goal_achievability_json?: string | null;
            /** Goal Driver Evidence Json */
            goal_driver_evidence_json?: string | null;
            /** Id */
            id: string;
            /** Input Snapshot Hash */
            input_snapshot_hash?: string | null;
            /** Is Current */
            is_current: number;
            /** Limiting Factor */
            limiting_factor?: string | null;
            /** Mandate Id */
            mandate_id: string;
            /** Manual Override Warnings */
            manual_override_warnings?: string[];
            /** Optimization Iterations */
            optimization_iterations?: number | null;
            /** Optimization Method */
            optimization_method?: string | null;
            /** Optimization Objective Value Milli */
            optimization_objective_value_milli?: number | null;
            /** Optimization Run Id */
            optimization_run_id?: string | null;
            /** Optimization Seed */
            optimization_seed?: number | null;
            /** Optimization Status */
            optimization_status?: string | null;
            /** Optimizer Reasoning Json */
            optimizer_reasoning_json?: string | null;
            /** Policy Id */
            policy_id: string;
            /** Preferences Json */
            preferences_json?: string | null;
            /** Reserve Funding Ledger Hash */
            reserve_funding_ledger_hash?: string | null;
            /** Reserve Needed At Generation Rappen */
            reserve_needed_at_generation_rappen?: number | null;
            /** Risk Budget Bps At Generation */
            risk_budget_bps_at_generation?: number | null;
            /** Risky Fraction Bps */
            risky_fraction_bps: number | null;
            /** Risky Fraction Bps At Generation */
            risky_fraction_bps_at_generation?: number | null;
            /** Set At */
            set_at: string;
            /** Set By */
            set_by: string;
            /** Shadow Optimization Json */
            shadow_optimization_json?: string | null;
            /** Stress Evaluations Json */
            stress_evaluations_json?: string | null;
            /** Sub Allocations Json */
            sub_allocations_json?: string | null;
            /** Target Alternatives Bps */
            target_alternatives_bps: number;
            /** Target Bonds Bps */
            target_bonds_bps: number;
            /** Target Equities Bps */
            target_equities_bps: number;
            /** Target Liquidity Bps */
            target_liquidity_bps: number;
            /** Target Real Estate Bps */
            target_real_estate_bps: number;
            /** Total Wealth At Generation Rappen */
            total_wealth_at_generation_rappen?: number | null;
            /** Updated At */
            updated_at: string;
            /** Version */
            version: number;
        };
        /**
         * TaxEstimateResult
         * @description Deterministic tax estimate result.
         *
         *     The result can represent a full estimate or one component estimate. The
         *     component fields always add up to total_tax_rappen.
         */
        TaxEstimateResult: {
            /** Assumptions */
            assumptions?: string[];
            /** Breakdown */
            breakdown?: Record<string, unknown>;
            /**
             * Capital Gains Tax Rappen
             * @default 0
             */
            capital_gains_tax_rappen?: number;
            /** Country Code */
            country_code: string;
            /**
             * Currency
             * @default CHF
             */
            currency?: string;
            /**
             * Effective Tax Bps
             * @default 0
             */
            effective_tax_bps?: number;
            /**
             * Income Tax Rappen
             * @default 0
             */
            income_tax_rappen?: number;
            /**
             * Marginal Tax Bps
             * @default 0
             */
            marginal_tax_bps?: number;
            /** Region */
            region?: string | null;
            /** Tariff Version */
            tariff_version: string;
            /**
             * Total Tax Rappen
             * @default 0
             */
            total_tax_rappen?: number;
            /**
             * Wealth Tax Effective Bps
             * @description Wealth tax (a stock levy) as bps of taxable wealth. Reported separately from effective_tax_bps/marginal_tax_bps, which cover only income+capital-gains (flow) tax on a flow basis -- blending a stock levy into a flow-basis rate produces a number with no coherent unit and materially understates the true flow burden.
             * @default 0
             */
            wealth_tax_effective_bps?: number;
            /**
             * Wealth Tax Rappen
             * @default 0
             */
            wealth_tax_rappen?: number;
            /** Year */
            year: number;
        };
        /** TaxJurisdictionListItem */
        TaxJurisdictionListItem: {
            /** Country Code */
            country_code: string;
            /** Currency */
            currency: string;
            /** Display Name */
            display_name: string;
            /** Supported Regions */
            supported_regions?: string[];
            /** Version */
            version: string;
        };
        /**
         * TaxProfileInput
         * @description Input for a deterministic tax estimate.
         *
         *     Amounts are expressed in rappen/cents of the local currency. Percentages in
         *     responses are expressed in basis points.
         */
        TaxProfileInput: {
            /**
             * Capital Gains Rappen
             * @default 0
             */
            capital_gains_rappen?: number;
            /**
             * Capital Gains Realization
             * @default private
             * @enum {string}
             */
            capital_gains_realization?: "private" | "business";
            /** Country Code */
            country_code: string;
            /**
             * Currency
             * @default CHF
             */
            currency?: string;
            /**
             * Marital Status
             * @default single
             * @enum {string}
             */
            marital_status?: "single" | "married" | "partnership";
            /** Municipality */
            municipality?: string | null;
            /**
             * Region
             * @description Canton/state/region code
             */
            region?: string | null;
            /** Religion */
            religion?: string | null;
            /**
             * Taxable Income Rappen
             * @default 0
             */
            taxable_income_rappen?: number;
            /**
             * Taxable Wealth Rappen
             * @default 0
             */
            taxable_wealth_rappen?: number;
            /**
             * Year
             * @default 2026
             */
            year?: number;
        };
        /**
         * TenantCreate
         * @description Request-Body fuer POST /tenants (super_admin only).
         */
        TenantCreate: {
            /** Default Presentation Mode */
            default_presentation_mode?: string | null;
            /**
             * Default Retrocession Reimbursement
             * @default false
             */
            default_retrocession_reimbursement?: boolean;
            /**
             * Discretionary Management Licensed
             * @default false
             */
            discretionary_management_licensed?: boolean;
            /** Display Name */
            display_name: string;
            /** Home Jurisdiction */
            home_jurisdiction?: string | null;
            /**
             * Hosting Tier
             * @default tier1
             */
            hosting_tier?: string;
            /**
             * License Status
             * @default trial
             */
            license_status?: string;
            /** License Valid Until */
            license_valid_until?: string | null;
            /** Max Mandates */
            max_mandates?: number | null;
            /**
             * Max Users
             * @default 1
             */
            max_users?: number | null;
            /** Slug */
            slug: string;
            /** Storage Quota Mb */
            storage_quota_mb?: number | null;
        };
        /**
         * TenantResponse
         * @description Public Tenant-Response fuer API-Endpoints.
         */
        TenantResponse: {
            /** Avv Signed At */
            avv_signed_at?: string | null;
            /** Created At */
            created_at: string;
            /** Default Presentation Mode */
            default_presentation_mode?: string | null;
            /**
             * Default Retrocession Reimbursement
             * @default 0
             */
            default_retrocession_reimbursement?: number;
            /**
             * Discretionary Management Licensed
             * @default 1
             */
            discretionary_management_licensed?: number;
            /** Display Name */
            display_name: string;
            /** Finma Outsourcing Notified At */
            finma_outsourcing_notified_at?: string | null;
            /** Home Jurisdiction */
            home_jurisdiction?: string | null;
            /** Hosting Tier */
            hosting_tier: string;
            /** Id */
            id: string;
            /** Is Active */
            is_active: number;
            /** License Status */
            license_status: string;
            /** License Valid Until */
            license_valid_until?: string | null;
            /** Max Mandates */
            max_mandates?: number | null;
            /** Max Users */
            max_users?: number | null;
            /** Slug */
            slug: string;
            /** Storage Quota Mb */
            storage_quota_mb?: number | null;
            /** Updated At */
            updated_at: string;
        };
        /**
         * TenantSelfResponse
         * @description 2026-08-09 (Roadmap #24-Rest, Soft-Limit-Warn-UI): Response fuer
         *     GET /tenants/me -- erweitert TenantResponse um die aktuelle Auslastung,
         *     damit das Frontend eine Warnschwelle (z.B. ab 80%) anzeigen kann, BEVOR
         *     der harte 409-Block (services/quota.py::assert_within_quota) greift.
         *     Nur hier, nicht auf TenantResponse selbst, da list_tenants/get_tenant
         *     (Operator-Endpoints) das nicht pro Zeile brauchen und die zusaetzlichen
         *     COUNT-Queries dort unnoetigen Overhead waeren.
         */
        TenantSelfResponse: {
            /** Avv Signed At */
            avv_signed_at?: string | null;
            /** Created At */
            created_at: string;
            /**
             * Current Mandates
             * @default 0
             */
            current_mandates?: number;
            /**
             * Current Users
             * @default 0
             */
            current_users?: number;
            /** Default Presentation Mode */
            default_presentation_mode?: string | null;
            /**
             * Default Retrocession Reimbursement
             * @default 0
             */
            default_retrocession_reimbursement?: number;
            /**
             * Discretionary Management Licensed
             * @default 1
             */
            discretionary_management_licensed?: number;
            /** Display Name */
            display_name: string;
            /** Finma Outsourcing Notified At */
            finma_outsourcing_notified_at?: string | null;
            /** Home Jurisdiction */
            home_jurisdiction?: string | null;
            /** Hosting Tier */
            hosting_tier: string;
            /** Id */
            id: string;
            /** Is Active */
            is_active: number;
            /** License Status */
            license_status: string;
            /** License Valid Until */
            license_valid_until?: string | null;
            /** Max Mandates */
            max_mandates?: number | null;
            /** Max Users */
            max_users?: number | null;
            /** Slug */
            slug: string;
            /** Storage Quota Mb */
            storage_quota_mb?: number | null;
            /** Updated At */
            updated_at: string;
        };
        /**
         * TenantSelfServiceUpdate
         * @description 2026-08-01 (Onboarding): Request-Body fuer PUT /tenants/me.
         *
         *     Bewusst SCHMALER als TenantUpdate (kein hosting_tier/license_status/
         *     max_users etc.) -- ein normaler Firmen-Admin (nicht super_admin) darf
         *     NUR die eigene Firmenidentitaet/den eigenen Standort pflegen, keine
         *     Lizenz-/Kapazitaets-Parameter. Funktioniert TIER-UNABHAENGIG (im
         *     Gegensatz zu PUT /tenants/{id}, das in Tier 1/3 per
         *     settings.tenant_admin_ui_enabled deaktiviert ist).
         */
        TenantSelfServiceUpdate: {
            /** Default Presentation Mode */
            default_presentation_mode?: string | null;
            /** Display Name */
            display_name?: string | null;
            /** Home Jurisdiction */
            home_jurisdiction?: string | null;
        };
        /**
         * TenantUpdate
         * @description Request-Body fuer PUT /tenants/{id} (Partial-Update).
         */
        TenantUpdate: {
            /** Avv Signed At */
            avv_signed_at?: string | null;
            /** Default Presentation Mode */
            default_presentation_mode?: string | null;
            /** Default Retrocession Reimbursement */
            default_retrocession_reimbursement?: boolean | null;
            /** Discretionary Management Licensed */
            discretionary_management_licensed?: boolean | null;
            /** Display Name */
            display_name?: string | null;
            /** Finma Outsourcing Notified At */
            finma_outsourcing_notified_at?: string | null;
            /** Home Jurisdiction */
            home_jurisdiction?: string | null;
            /** Hosting Tier */
            hosting_tier?: string | null;
            /** Is Active */
            is_active?: number | null;
            /** License Status */
            license_status?: string | null;
            /** License Valid Until */
            license_valid_until?: string | null;
            /** Max Mandates */
            max_mandates?: number | null;
            /** Max Users */
            max_users?: number | null;
            /** Storage Quota Mb */
            storage_quota_mb?: number | null;
        };
        /** TokenResponse */
        TokenResponse: {
            /** Access Token */
            access_token: string;
            /** Refresh Token */
            refresh_token?: string | null;
            /** Tenant Default Presentation Mode */
            tenant_default_presentation_mode?: string | null;
            /**
             * Token Type
             * @default bearer
             */
            token_type?: string;
            user: components["schemas"]["UserResponse"];
        };
        /** UserCreate */
        UserCreate: {
            /** Email */
            email?: string | null;
            /** Full Name */
            full_name: string;
            /** Password */
            password: string;
            /**
             * Role
             * @default advisor
             * @enum {string}
             */
            role?: "admin" | "advisor" | "readonly" | "portfolio_management";
            /** Tenant Id */
            tenant_id?: string | null;
            /** Username */
            username: string;
        };
        /** UserPasswordReset */
        UserPasswordReset: {
            /** New Password */
            new_password: string;
        };
        /** UserResponse */
        UserResponse: {
            /** Created At */
            created_at: string;
            /** Email */
            email: string | null;
            /** Full Name */
            full_name: string;
            /** Id */
            id: string;
            /**
             * Invite Pending
             * @default false
             */
            invite_pending?: boolean;
            /** Is Active */
            is_active: number;
            /** Last Login At */
            last_login_at: string | null;
            /**
             * Must Change Password
             * @default 0
             */
            must_change_password?: number;
            /** Role */
            role: string;
            /**
             * Totp Enabled
             * @default 0
             */
            totp_enabled?: number;
            /** Username */
            username: string;
        };
        /** UserUpdate */
        UserUpdate: {
            /** Email */
            email?: string | null;
            /** Full Name */
            full_name?: string | null;
            /** Is Active */
            is_active?: boolean | null;
            /** Role */
            role?: ("admin" | "advisor" | "readonly" | "portfolio_management") | null;
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, unknown>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /** WealthInflowCreate */
        WealthInflowCreate: {
            /** Amount Rappen */
            amount_rappen: number;
            /**
             * Certainty
             * @default sicher
             */
            certainty?: ("sicher" | "unsicher") | null;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Duration Years */
            duration_years?: number | null;
            /** Expected Year */
            expected_year: number;
            /** Frequency */
            frequency?: ("einmalig" | "jaehrlich" | "monatlich") | null;
            /**
             * Is Recurring
             * @default 0
             */
            is_recurring?: number;
            /** Label */
            label: string;
            /** Linked Position Id */
            linked_position_id?: string | null;
            /** Mandate Id */
            mandate_id?: string | null;
            /** Notes */
            notes?: string | null;
            /**
             * Source Type
             * @enum {string}
             */
            source_type: "Erbschaft" | "Bonus" | "Saeule3b" | "Verkaufserloes" | "Andere";
            /**
             * Value Mode
             * @default nominal
             * @enum {string}
             */
            value_mode?: "nominal" | "real";
        };
        /** WealthInflowResponse */
        WealthInflowResponse: {
            /** Amount Rappen */
            amount_rappen: number;
            /**
             * Certainty
             * @default sicher
             */
            certainty?: string;
            /** Client Id */
            client_id: string;
            /** Created At */
            created_at: string;
            /** Duration Years */
            duration_years: number | null;
            /** Expected Year */
            expected_year: number;
            /** Frequency */
            frequency: string | null;
            /** Id */
            id: string;
            /** Is Active */
            is_active: number;
            /** Is Recurring */
            is_recurring: number;
            /** Label */
            label: string;
            /** Linked Position Id */
            linked_position_id?: string | null;
            /** Mandate Id */
            mandate_id: string | null;
            /** Notes */
            notes: string | null;
            /** Source Type */
            source_type: string;
            /** Updated At */
            updated_at: string;
            /** Value Mode */
            value_mode: string;
        };
        /** WealthInflowUpdate */
        WealthInflowUpdate: {
            /** Amount Rappen */
            amount_rappen?: number | null;
            /** Certainty */
            certainty?: ("sicher" | "unsicher") | null;
            /** Data Classification */
            data_classification?: ("synthetic" | "real") | null;
            /** Duration Years */
            duration_years?: number | null;
            /** Expected Year */
            expected_year?: number | null;
            /** Frequency */
            frequency?: ("einmalig" | "jaehrlich" | "monatlich") | null;
            /** Is Active */
            is_active?: number | null;
            /** Is Recurring */
            is_recurring?: number | null;
            /** Label */
            label?: string | null;
            /** Linked Position Id */
            linked_position_id?: string | null;
            /** Notes */
            notes?: string | null;
            /** Source Type */
            source_type?: ("Erbschaft" | "Bonus" | "Saeule3b" | "Verkaufserloes" | "Andere") | null;
            /** Value Mode */
            value_mode?: ("nominal" | "real") | null;
        };
        /** WealthPositionCreate */
        WealthPositionCreate: {
            /**
             * Alloc Alternatives Bps
             * @default 0
             */
            alloc_alternatives_bps?: number;
            /**
             * Alloc Bonds Bps
             * @default 0
             */
            alloc_bonds_bps?: number;
            /**
             * Alloc Equities Bps
             * @default 0
             */
            alloc_equities_bps?: number;
            /**
             * Alloc Liquidity Bps
             * @default 0
             */
            alloc_liquidity_bps?: number;
            /**
             * Alloc Real Estate Bps
             * @default 0
             */
            alloc_real_estate_bps?: number;
            /** Asset Expected Return Bps */
            asset_expected_return_bps?: number | null;
            /** Asset Liquidity */
            asset_liquidity?: ("Liquide (< 30 Tage)" | "Eingeschränkt (30–180 Tage)" | "Illiquid (> 180 Tage)" | "Gebunden") | null;
            /** Asset Location */
            asset_location?: string | null;
            /** Asset Subtype */
            asset_subtype?: string | null;
            /** Asset Valuation Method */
            asset_valuation_method?: ("Selbstschätzung" | "Fachgutachten" | "Versicherungswert" | "Marktpreis" | "PK-Ausweis") | null;
            /**
             * Assignment
             * @default Anderes Vermögen
             * @enum {string}
             */
            assignment?: "Beratungsvermögen" | "Anderes Vermögen" | "Verbindlichkeit";
            /**
             * Currency
             * @default CHF
             */
            currency?: string;
            /**
             * Current Value Rappen
             * @default 0
             */
            current_value_rappen?: number;
            /**
             * Data Classification
             * @default synthetic
             * @enum {string}
             */
            data_classification?: "synthetic" | "real";
            /** Depot Account Number */
            depot_account_number?: string | null;
            /** Depot Bank */
            depot_bank?: string | null;
            /** Goal Funding Method */
            goal_funding_method?: ("Verkauf" | "Belehnung" | "Ignorieren" | "Automatisch") | null;
            /**
             * Is Available For Goal Funding
             * @default false
             */
            is_available_for_goal_funding?: boolean;
            /** Label */
            label: string;
            /** Liquidity Available From */
            liquidity_available_from?: string | null;
            /** Liquidity Instrument */
            liquidity_instrument?: ("Kontoguthaben" | "Sparkonto" | "Festgeld" | "Kassenobligation" | "Geldmarktfonds") | null;
            /** Liquidity Interest Rate Bps */
            liquidity_interest_rate_bps?: number | null;
            /**
             * Mortgage Amortization Rappen
             * @default 0
             */
            mortgage_amortization_rappen?: number;
            /** Mortgage Amortization Type */
            mortgage_amortization_type?: ("Direkt" | "Indirekt (Säule 3a)" | "Keine") | null;
            /** Mortgage Bank */
            mortgage_bank?: string | null;
            /** Mortgage Interest Rate Bps */
            mortgage_interest_rate_bps?: number | null;
            /** Mortgage Linked Property Id */
            mortgage_linked_property_id?: string | null;
            /** Mortgage Maturity Date */
            mortgage_maturity_date?: string | null;
            /** Mortgage Type */
            mortgage_type?: ("Festhypothek" | "SARON" | "Gemischt") | null;
            /** Notes */
            notes?: string | null;
            /** Pension Institution */
            pension_institution?: string | null;
            /** Pension Interest Rate Bps */
            pension_interest_rate_bps?: number | null;
            /** Pension Lumpsum Tax Bps */
            pension_lumpsum_tax_bps?: number | null;
            /** Pension Lumpsum Tax Rappen */
            pension_lumpsum_tax_rappen?: number | null;
            /** Pension Maturity Date */
            pension_maturity_date?: string | null;
            /** Pension Maturity Value Rappen */
            pension_maturity_value_rappen?: number | null;
            /** Pension Payout Form */
            pension_payout_form?: ("Rente" | "Kapital" | "Gemischt" | "Offen") | null;
            /** Pension Retirement Age */
            pension_retirement_age?: number | null;
            /** Pension Technical Rate Bps */
            pension_technical_rate_bps?: number | null;
            /** Pension Type */
            pension_type?: ("BVG" | "Säule 3a" | "Freizügigkeit" | "Säule 3b" | "Lebensversicherung") | null;
            /** Pension Vehicle */
            pension_vehicle?: ("Konto" | "Wertschriften" | "Police") | null;
            /**
             * Pension Wef Possible
             * @default false
             */
            pension_wef_possible?: boolean;
            /**
             * Position Type
             * @enum {string}
             */
            position_type: "Depot" | "Liquidität" | "Immobilien" | "Vorsorge" | "Alternative" | "Hypothek" | "Custom";
            /** Property Address */
            property_address?: string | null;
            /**
             * Property Rental Income Rappen
             * @default 0
             */
            property_rental_income_rappen?: number;
            /**
             * Property Rental Inflation Linked
             * @default 0
             */
            property_rental_inflation_linked?: number;
            /** Property Usage */
            property_usage?: ("Selbstgenutzt" | "Renditeobjekt" | "Ferienimmobilie" | "Gemischt") | null;
            /** Property Zip City */
            property_zip_city?: string | null;
            /** Valuation Date */
            valuation_date?: string | null;
        };
        /** WealthPositionResponse */
        WealthPositionResponse: {
            /** Alloc Alternatives Bps */
            alloc_alternatives_bps: number;
            /** Alloc Bonds Bps */
            alloc_bonds_bps: number;
            /** Alloc Equities Bps */
            alloc_equities_bps: number;
            /** Alloc Liquidity Bps */
            alloc_liquidity_bps: number;
            /** Alloc Real Estate Bps */
            alloc_real_estate_bps: number;
            /** Asset Expected Return Bps */
            asset_expected_return_bps: number | null;
            /** Asset Liquidity */
            asset_liquidity: string | null;
            /** Asset Subtype */
            asset_subtype: string | null;
            /** Asset Valuation Method */
            asset_valuation_method: string | null;
            /** Assignment */
            assignment: string;
            /** Client Id */
            client_id: string;
            /** Created At */
            created_at: string;
            /** Currency */
            currency: string;
            /** Current Value Rappen */
            current_value_rappen: number;
            /** Depot Account Number */
            depot_account_number: string | null;
            /** Depot Bank */
            depot_bank: string | null;
            /** Goal Funding Method */
            goal_funding_method: string | null;
            /** Id */
            id: string;
            /** Is Active */
            is_active: number;
            /** Is Available For Goal Funding */
            is_available_for_goal_funding: number;
            /** Label */
            label: string;
            /** Liquidity Available From */
            liquidity_available_from?: string | null;
            /** Liquidity Instrument */
            liquidity_instrument: string | null;
            /** Liquidity Interest Rate Bps */
            liquidity_interest_rate_bps: number | null;
            /** Mortgage Amortization Rappen */
            mortgage_amortization_rappen: number;
            /** Mortgage Amortization Type */
            mortgage_amortization_type: string | null;
            /** Mortgage Bank */
            mortgage_bank: string | null;
            /** Mortgage Interest Rate Bps */
            mortgage_interest_rate_bps: number | null;
            /** Mortgage Linked Property Id */
            mortgage_linked_property_id: string | null;
            /** Mortgage Maturity Date */
            mortgage_maturity_date: string | null;
            /** Mortgage Type */
            mortgage_type: string | null;
            /** Notes */
            notes: string | null;
            /** Pension Institution */
            pension_institution: string | null;
            /** Pension Interest Rate Bps */
            pension_interest_rate_bps?: number | null;
            /** Pension Lumpsum Tax Bps */
            pension_lumpsum_tax_bps?: number | null;
            /** Pension Lumpsum Tax Rappen */
            pension_lumpsum_tax_rappen?: number | null;
            /** Pension Maturity Date */
            pension_maturity_date?: string | null;
            /** Pension Maturity Value Rappen */
            pension_maturity_value_rappen?: number | null;
            /** Pension Payout Form */
            pension_payout_form: string | null;
            /** Pension Retirement Age */
            pension_retirement_age: number | null;
            /** Pension Technical Rate Bps */
            pension_technical_rate_bps?: number | null;
            /** Pension Type */
            pension_type: string | null;
            /** Pension Vehicle */
            pension_vehicle?: string | null;
            /** Pension Wef Possible */
            pension_wef_possible: number;
            /** Position Type */
            position_type: string;
            /** Property Address */
            property_address: string | null;
            /** Property Rental Income Rappen */
            property_rental_income_rappen: number;
            /**
             * Property Rental Inflation Linked
             * @default 0
             */
            property_rental_inflation_linked?: number;
            /** Property Usage */
            property_usage: string | null;
            /** Property Zip City */
            property_zip_city: string | null;
            /** Updated At */
            updated_at: string;
            /** Valuation Date */
            valuation_date: string | null;
        };
        /** WealthPositionUpdate */
        WealthPositionUpdate: {
            /** Alloc Alternatives Bps */
            alloc_alternatives_bps?: number | null;
            /** Alloc Bonds Bps */
            alloc_bonds_bps?: number | null;
            /** Alloc Equities Bps */
            alloc_equities_bps?: number | null;
            /** Alloc Liquidity Bps */
            alloc_liquidity_bps?: number | null;
            /** Alloc Real Estate Bps */
            alloc_real_estate_bps?: number | null;
            /** Asset Expected Return Bps */
            asset_expected_return_bps?: number | null;
            /** Asset Liquidity */
            asset_liquidity?: ("Liquide (< 30 Tage)" | "Eingeschränkt (30–180 Tage)" | "Illiquid (> 180 Tage)" | "Gebunden") | null;
            /** Asset Location */
            asset_location?: string | null;
            /** Asset Subtype */
            asset_subtype?: string | null;
            /** Asset Valuation Method */
            asset_valuation_method?: ("Selbstschätzung" | "Fachgutachten" | "Versicherungswert" | "Marktpreis" | "PK-Ausweis") | null;
            /** Assignment */
            assignment?: string | null;
            /** Currency */
            currency?: string | null;
            /** Current Value Rappen */
            current_value_rappen?: number | null;
            /** Data Classification */
            data_classification?: ("synthetic" | "real") | null;
            /** Depot Account Number */
            depot_account_number?: string | null;
            /** Depot Bank */
            depot_bank?: string | null;
            /** Goal Funding Method */
            goal_funding_method?: ("Verkauf" | "Belehnung" | "Ignorieren" | "Automatisch") | null;
            /** Is Active */
            is_active?: boolean | null;
            /** Is Available For Goal Funding */
            is_available_for_goal_funding?: boolean | null;
            /** Label */
            label?: string | null;
            /** Liquidity Available From */
            liquidity_available_from?: string | null;
            /** Liquidity Instrument */
            liquidity_instrument?: ("Kontoguthaben" | "Sparkonto" | "Festgeld" | "Kassenobligation" | "Geldmarktfonds") | null;
            /** Liquidity Interest Rate Bps */
            liquidity_interest_rate_bps?: number | null;
            /** Mortgage Amortization Rappen */
            mortgage_amortization_rappen?: number | null;
            /** Mortgage Amortization Type */
            mortgage_amortization_type?: ("Direkt" | "Indirekt (Säule 3a)" | "Keine") | null;
            /** Mortgage Bank */
            mortgage_bank?: string | null;
            /** Mortgage Interest Rate Bps */
            mortgage_interest_rate_bps?: number | null;
            /** Mortgage Linked Property Id */
            mortgage_linked_property_id?: string | null;
            /** Mortgage Maturity Date */
            mortgage_maturity_date?: string | null;
            /** Mortgage Type */
            mortgage_type?: ("Festhypothek" | "SARON" | "Gemischt") | null;
            /** Notes */
            notes?: string | null;
            /** Pension Institution */
            pension_institution?: string | null;
            /** Pension Interest Rate Bps */
            pension_interest_rate_bps?: number | null;
            /** Pension Lumpsum Tax Bps */
            pension_lumpsum_tax_bps?: number | null;
            /** Pension Lumpsum Tax Rappen */
            pension_lumpsum_tax_rappen?: number | null;
            /** Pension Maturity Date */
            pension_maturity_date?: string | null;
            /** Pension Maturity Value Rappen */
            pension_maturity_value_rappen?: number | null;
            /** Pension Payout Form */
            pension_payout_form?: ("Rente" | "Kapital" | "Gemischt" | "Offen") | null;
            /** Pension Retirement Age */
            pension_retirement_age?: number | null;
            /** Pension Technical Rate Bps */
            pension_technical_rate_bps?: number | null;
            /** Pension Type */
            pension_type?: ("BVG" | "Säule 3a" | "Freizügigkeit" | "Säule 3b" | "Lebensversicherung") | null;
            /** Pension Vehicle */
            pension_vehicle?: ("Konto" | "Wertschriften" | "Police") | null;
            /** Pension Wef Possible */
            pension_wef_possible?: boolean | null;
            /** Property Address */
            property_address?: string | null;
            /** Property Rental Income Rappen */
            property_rental_income_rappen?: number | null;
            /** Property Rental Inflation Linked */
            property_rental_inflation_linked?: number | null;
            /** Property Usage */
            property_usage?: ("Selbstgenutzt" | "Renditeobjekt" | "Ferienimmobilie" | "Gemischt") | null;
            /** Property Zip City */
            property_zip_city?: string | null;
            /** Valuation Date */
            valuation_date?: string | null;
        };
        /** WealthSummaryResponse */
        WealthSummaryResponse: {
            /** Advisory Wealth Chf */
            advisory_wealth_chf: number;
            /** Advisory Wealth Rappen */
            advisory_wealth_rappen: number;
            /** Client Classification */
            client_classification: string | null;
            /** Client Id */
            client_id: string;
            /** Client Name */
            client_name: string;
            /** Gross Wealth Chf */
            gross_wealth_chf: number;
            /** Gross Wealth Rappen */
            gross_wealth_rappen: number;
            /** Liabilities Chf */
            liabilities_chf: number;
            /** Liabilities Rappen */
            liabilities_rappen: number;
            /** Net Worth Chf */
            net_worth_chf: number;
            /** Net Worth Rappen */
            net_worth_rappen: number;
        };
        /** WitnessRequest */
        WitnessRequest: {
            /** Confirmed */
            confirmed: boolean;
            /** Statement Hash */
            statement_hash: string;
            /** Statement Version */
            statement_version: string;
        };
        /** _ChangePassword */
        _ChangePassword: {
            /** Current Password */
            current_password: string;
            /** New Password */
            new_password: string;
        };
        /** _PasswordResetConfirm */
        _PasswordResetConfirm: {
            /** New Password */
            new_password: string;
            /** Token */
            token: string;
        };
        /** _PasswordResetRequest */
        _PasswordResetRequest: {
            /** Email */
            email?: string | null;
            /** Username */
            username?: string | null;
        };
        /** _RevokeAllSessionsRequest */
        _RevokeAllSessionsRequest: {
            /** Tenant Id */
            tenant_id?: string | null;
        };
        /** _TwoFACodeRequest */
        _TwoFACodeRequest: {
            /** Code */
            code: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    health__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_market_data_status_admin_market_data_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    list_optimizer_policies_admin_optimizer_policies_get: {
        parameters: {
            query?: {
                include_historic?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OptimizerPolicyResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_optimizer_policy_admin_optimizer_policies_post: {
        parameters: {
            query?: {
                activate?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OptimizerPolicyCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OptimizerPolicyDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_optimizer_policy_detail_admin_optimizer_policies__policy_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OptimizerPolicyDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_optimizer_policy_admin_optimizer_policies__policy_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OptimizerPolicyUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OptimizerPolicyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    activate_optimizer_policy_admin_optimizer_policies__policy_id__activate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OptimizerPolicyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    clone_optimizer_policy_admin_optimizer_policies__policy_id__clone_post: {
        parameters: {
            query?: {
                new_name?: string | null;
            };
            header?: never;
            path: {
                policy_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OptimizerPolicyDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    replace_house_matrix_rows_admin_optimizer_policies__policy_id__house_matrix_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["HouseMatrixRowsReplace"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OptimizerPolicyDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_mapping_gaps_admin_prices_mapping_gaps_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    refresh_prices_admin_prices_refresh_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_price_status_admin_prices_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_annual_returns_admin_system_annual_returns_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    backfill_annual_returns_endpoint_admin_system_annual_returns_backfill_post: {
        parameters: {
            query?: {
                from_year?: number | null;
                to_year?: number | null;
                overwrite?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upsert_annual_return_admin_system_annual_returns__year___asset_class__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                year: number;
                asset_class: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": Record<string, unknown>;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    backfill_asset_class_prices_endpoint_admin_system_asset_class_prices_backfill_post: {
        parameters: {
            query?: {
                from_year?: number | null;
                to_year?: number | null;
                overwrite?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_asset_class_prices_status_admin_system_asset_class_prices_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_audit_log_admin_system_audit_log_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
                action?: string | null;
                q?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuditLogPage"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_backups_admin_system_backups_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    purge_demo_client_admin_system_clients__client_id__purge_demo_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_compliance_status_admin_system_compliance_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    backup_database_admin_system_db_backup_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    database_integrity_admin_system_db_integrity_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    optimize_database_admin_system_db_optimize_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    create_foundation_example_admin_system_foundation_example_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    purge_foundation_example_admin_system_foundation_example_purge_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    refresh_fx_rates_now_admin_system_fx_rates_refresh_now_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_recent_logs_admin_system_logs_recent_get: {
        parameters: {
            query?: {
                lines?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_provider_health_registry_admin_system_market_data_provider_health_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reset_provider_health_registry_admin_system_market_data_provider_health_reset_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": Record<string, unknown> | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_market_data_purge_history_admin_system_market_data_purge_history_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    purge_market_data_cache_now_admin_system_market_data_purge_now_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    refresh_market_data_now_admin_system_market_data_refresh_now_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_optimizer_mode_admin_system_optimizer_mode_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    set_optimizer_mode_admin_system_optimizer_mode_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": Record<string, unknown>;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_paths_admin_system_paths_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    cleanup_recommendation_runs_endpoint_admin_system_recommendation_runs_cleanup_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": Record<string, unknown> | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_shadow_comparison_aggregate_admin_system_shadow_comparison_aggregate_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_shadow_comparison_admin_system_shadow_comparison__mandate_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_support_bundle_endpoint_admin_system_support_bundle_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    twofa_disable_auth_2fa_disable_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["_TwoFACodeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    twofa_enable_auth_2fa_enable_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["_TwoFACodeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    twofa_recovery_regenerate_auth_2fa_recovery_regenerate_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    twofa_recovery_status_auth_2fa_recovery_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    twofa_setup_auth_2fa_setup_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    twofa_status_auth_2fa_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    revoke_all_sessions_endpoint_auth_admin_revoke_all_sessions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["_RevokeAllSessionsRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    bootstrap_admin_auth_bootstrap_admin_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BootstrapAdminRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    bootstrap_status_auth_bootstrap_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BootstrapStatusResponse"];
                };
            };
        };
    };
    change_password_auth_change_password_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["_ChangePassword"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    invite_accept_auth_invite_accept_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InviteAccept"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    invite_preview_auth_invite__token__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                token: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InvitePreview"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    login_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    logout_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    me_auth_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserResponse"];
                };
            };
        };
    };
    password_reset_confirm_auth_password_reset_confirm_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["_PasswordResetConfirm"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    password_reset_request_auth_password_reset_request_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["_PasswordResetRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    refresh_access_token_auth_refresh_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RefreshTokenRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TokenResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_current_building_blocks_building_blocks_current_get: {
        parameters: {
            query?: {
                jurisdiction?: string;
                investment_universe?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BuildingBlockResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_my_review_calendar_feed_calendar_reviews_ics_get: {
        parameters: {
            query: {
                token: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_cma_capital_market_assumptions_put: {
        parameters: {
            query?: {
                jurisdiction?: string;
                tenant_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CapitalMarketAssumptionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CapitalMarketAssumptionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_current_cma_capital_market_assumptions_current_get: {
        parameters: {
            query?: {
                jurisdiction?: string;
                tenant_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CapitalMarketAssumptionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    approve_capital_market_assumption_capital_market_assumptions__id__approve_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CapitalMarketAssumptionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    client_portal_mandate_report_client_portal_mandates__mandate_id__report_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    client_portal_sign_risk_profile_client_portal_mandates__mandate_id__risk_profile_sign_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    client_portal_me_client_portal_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    client_confirm_onsite_signature_client_portal_onsite_signature__transaction_id__confirm_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                transaction_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CustomerConfirmRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_clients_clients_get: {
        parameters: {
            query?: {
                search?: string;
                advisor_id?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ClientResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_client_clients_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ClientCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ClientResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_client_clients__client_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ClientResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_client_clients__client_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ClientUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ClientResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_client_clients__client_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cashflow_projection_clients__client_id__cashflow_projection_get: {
        parameters: {
            query?: {
                horizon_years?: number | null;
                indexation?: boolean;
            };
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CashflowProjectionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cashflow_summary_clients__client_id__cashflow_summary_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CashflowSummaryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_cashflows_clients__client_id__cashflows_get: {
        parameters: {
            query?: {
                include_inactive?: boolean;
            };
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CashflowResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_cashflow_clients__client_id__cashflows_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CashflowCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CashflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cashflows_derived_clients__client_id__cashflows_derived_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_cashflow_clients__client_id__cashflows__cf_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
                cf_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CashflowUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CashflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_cashflow_clients__client_id__cashflows__cf_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
                cf_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_client_login_clients__client_id__client_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": Record<string, unknown>;
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_data_clients__client_id__data_export_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_due_diligence_clients__client_id__due_diligence_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ClientDueDiligenceResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upsert_due_diligence_clients__client_id__due_diligence_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ClientDueDiligenceUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ClientDueDiligenceResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    erase_client_clients__client_id__erase_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ClientErasureRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ClientErasureResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_knowledge_clients__client_id__knowledge_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KnowledgeResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_knowledge_clients__client_id__knowledge_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["KnowledgeCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["KnowledgeResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_mandates_clients__client_id__mandates_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MandateResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_mandate_clients__client_id__mandates_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MandateCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MandateResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_nationalities_clients__client_id__nationalities_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NationalityResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_nationality_clients__client_id__nationalities_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NationalityCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NationalityResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_opt_history_clients__client_id__opt_history_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OptHistoryResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_opt_history_clients__client_id__opt_history_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OptHistoryCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OptHistoryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_tax_residencies_clients__client_id__tax_residencies_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ClientTaxResidencyResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_tax_residency_clients__client_id__tax_residencies_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ClientTaxResidencyCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ClientTaxResidencyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_wealth_inflows_clients__client_id__wealth_inflows_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WealthInflowResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_wealth_inflow_clients__client_id__wealth_inflows_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WealthInflowCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WealthInflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_wealth_positions_clients__client_id__wealth_positions_get: {
        parameters: {
            query?: {
                include_inactive?: boolean;
            };
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WealthPositionResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_wealth_position_clients__client_id__wealth_positions_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WealthPositionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WealthPositionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_wealth_position_clients__client_id__wealth_positions__wp_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
                wp_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WealthPositionUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WealthPositionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_wealth_position_clients__client_id__wealth_positions__wp_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
                wp_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    wealth_summary_clients__client_id__wealth_summary_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                client_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WealthSummaryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_policies_cma_policies_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CmaPolicyOut"][];
                };
            };
        };
    };
    create_policy_cma_policies_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CmaPolicyCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CmaPolicyOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_model_status_cma_policies_model_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CmaPolicyModelStatus"];
                };
            };
        };
    };
    get_policy_cma_policies__policy_row_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_row_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CmaPolicyOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    activate_policy_cma_policies__policy_row_id__activate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_row_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CmaPolicyOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    approve_policy_cma_policies__policy_row_id__approve_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_row_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CmaPolicyDecision"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CmaPolicyOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    replace_components_cma_policies__policy_row_id__components_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_row_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CmaPolicyComponentsReplace"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CmaPolicyOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    retire_policy_cma_policies__policy_row_id__retire_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_row_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CmaPolicyOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    revoke_policy_cma_policies__policy_row_id__revoke_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_row_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CmaPolicyDecision"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CmaPolicyOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    validate_policy_cma_policies__policy_row_id__validate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_row_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CmaPolicyOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    active_triggers_dashboard_active_triggers_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    dashboard_summary_dashboard_summary_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    upsert_fx_rates_fx_rates_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FXRateResponse"][];
                };
            };
        };
    };
    list_current_fx_rates_fx_rates_current_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["FXRateResponse"][];
                };
            };
        };
    };
    health_root_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, unknown>;
                };
            };
        };
    };
    health_db_health_db_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, unknown>;
                };
            };
        };
    };
    health_live_health_live_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, unknown>;
                };
            };
        };
    };
    health_ready_health_ready_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, unknown>;
                };
            };
        };
    };
    get_house_matrix_for_score_house_matrix__score__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                score: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HouseMatrixResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_jurisdictions_jurisdictions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JurisdictionProfileResponse"][];
                };
            };
        };
    };
    get_jurisdiction_jurisdictions__code__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JurisdictionProfileResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_jurisdiction_jurisdictions__code__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["JurisdictionProfileUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JurisdictionProfileResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    compute_cma_candidate_jurisdictions__code__cma_compute_candidate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CapitalMarketAssumptionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_home_bias_defaults_jurisdictions__code__home_bias_defaults_get: {
        parameters: {
            query?: {
                preference_key?: string | null;
            };
            header?: never;
            path: {
                code: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JurisdictionHomeBiasDefaultResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_home_bias_default_jurisdictions__code__home_bias_defaults_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["JurisdictionHomeBiasDefaultCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JurisdictionHomeBiasDefaultResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_home_bias_default_jurisdictions__code__home_bias_defaults__row_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code: string;
                row_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["JurisdictionHomeBiasDefaultUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["JurisdictionHomeBiasDefaultResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_home_bias_default_jurisdictions__code__home_bias_defaults__row_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code: string;
                row_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_mandate_mandates__mandate_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MandateResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_mandate_mandates__mandate_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MandateUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MandateResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_advisory_log_mandates__mandate_id__advisory_log_get: {
        parameters: {
            query?: {
                include_history?: boolean;
            };
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdvisoryLogResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_advisory_log_entry_mandates__mandate_id__advisory_log_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AdvisoryLogCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdvisoryLogResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_advisory_log_from_report_generation_mandates__mandate_id__advisory_log_from_report_generation_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdvisoryLogResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_advisory_log_entry_mandates__mandate_id__advisory_log__log_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                log_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdvisoryLogResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_advisory_log_entry_mandates__mandate_id__advisory_log__log_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                log_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AdvisoryLogUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdvisoryLogResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_advisory_report_mandates__mandate_id__advisory_report_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_backtest_ab_mandates__mandate_id__backtest_ab_get: {
        parameters: {
            query: {
                policy_a: string;
                policy_b: string;
            };
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_strategy_backtest_mandates__mandate_id__backtest_strategy_get: {
        parameters: {
            query?: {
                start_year?: number | null;
                end_year?: number | null;
                benchmark_equities_bps?: number | null;
                benchmark_bonds_bps?: number | null;
                benchmark_real_estate_bps?: number | null;
                benchmark_alternatives_bps?: number | null;
                benchmark_liquidity_bps?: number | null;
                resolution?: string;
                strategy_fee_bps?: number | null;
                benchmark_fee_bps?: number | null;
                benchmark_sub_assets?: string | null;
            };
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_backtest_stress_replays_mandates__mandate_id__backtest_stress_replays_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_conflicts_mandates__mandate_id__conflict_disclosures_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConflictDisclosureResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_conflicts_mandates__mandate_id__conflicts_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConflictDisclosureResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_conflict_mandates__mandate_id__conflicts_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConflictDisclosureCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConflictDisclosureResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    acknowledge_conflict_mandates__mandate_id__conflicts__conflict_id__acknowledge_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                conflict_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConflictAcknowledgeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConflictDisclosureResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    attach_conflict_document_mandates__mandate_id__conflicts__conflict_id__attach_document_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                conflict_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConflictAttachDocumentRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConflictDisclosureResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    disclose_conflict_mandates__mandate_id__conflicts__conflict_id__disclose_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                conflict_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConflictDiscloseRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConflictDisclosureResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    mitigate_conflict_mandates__mandate_id__conflicts__conflict_id__mitigate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                conflict_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ConflictMitigateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConflictDisclosureResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_ex_ante_cost_disclosure_mandates__mandate_id__cost_disclosure_ex_ante_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CostDisclosureResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_depot_check_mandates__mandate_id__depot_check_get: {
        parameters: {
            query?: {
                analysis_snapshot_id?: string | null;
            };
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_depot_snapshot_mandates__mandate_id__depot_snapshots_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_depot_check_analysis_mandates__mandate_id__depot_snapshots__snapshot_id__depot_check_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                snapshot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_depot_snapshot_stress_replays_mandates__mandate_id__depot_snapshots__snapshot_id__stress_replays_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                snapshot_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_documents_mandates__mandate_id__documents_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContractDocumentResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_document_mandates__mandate_id__documents_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContractDocumentCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContractDocumentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    open_onsite_signature_mandates__mandate_id__documents__doc_id__onsite_signature_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                doc_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["OpenRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_document_pdf_mandates__mandate_id__documents__doc_id__pdf_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                doc_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    sign_document_mandates__mandate_id__documents__doc_id__sign_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                doc_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ContractDocumentSign"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContractDocumentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_financial_coverage_attestation_mandates__mandate_id__financial_coverage_attestation_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_financial_coverage_attestation_mandates__mandate_id__financial_coverage_attestations_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FinancialCoverageAttestationCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_goals_mandates__mandate_id__goals_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GoalResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_goal_mandates__mandate_id__goals_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GoalCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GoalResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    calculate_max_pension_spending_mandates__mandate_id__goals_calculate_max_pension_spending_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MaxPensionSpendingRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MaxPensionSpendingResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reorder_goals_mandates__mandate_id__goals_order_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GoalOrderUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GoalResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_goal_mandates__mandate_id__goals__goal_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                goal_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GoalUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GoalResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_goal_mandates__mandate_id__goals__goal_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                goal_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_goal_revision_decisions_mandates__mandate_id__goals__goal_id__revision_decisions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                goal_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_goal_revision_decision_mandates__mandate_id__goals__goal_id__revision_decisions_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                goal_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["GoalRevisionDecisionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_onsite_signature_mandates__mandate_id__onsite_signature__transaction_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                transaction_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    onsite_abort_mandates__mandate_id__onsite_signature__transaction_id__abort_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                transaction_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AbortRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    onsite_issue_challenge_mandates__mandate_id__onsite_signature__transaction_id__challenge_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                transaction_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    onsite_deliver_copy_mandates__mandate_id__onsite_signature__transaction_id__deliver_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                transaction_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    onsite_finalize_mandates__mandate_id__onsite_signature__transaction_id__finalize_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                transaction_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["FinalizeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    onsite_identity_check_mandates__mandate_id__onsite_signature__transaction_id__identity_check_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                transaction_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IdentityCheckRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    onsite_witness_mandates__mandate_id__onsite_signature__transaction_id__witness_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                transaction_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WitnessRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_optimizer_runs_mandates__mandate_id__optimizer_runs_get: {
        parameters: {
            query?: {
                limit?: number;
                offset?: number;
            };
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OptimizerRunResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_planning_assumptions_ui_mandates__mandate_id__planning_assumptions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upsert_planning_assumptions_mandates__mandate_id__planning_assumptions_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlanningAssumptionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_planning_assumptions_mandates__mandate_id__planning_assumptions_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlanningAssumptionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlanningAssumptionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_planning_assumptions_mandates__mandate_id__planning_assumptions_current_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlanningAssumptionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_portfolio_data_assessment_mandates__mandate_id__portfolio_data_assessment_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_portfolio_handoffs_mandates__mandate_id__portfolio_handoffs_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PortfolioHandoffResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_portfolio_handoff_mandates__mandate_id__portfolio_handoffs__handoff_id__cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                handoff_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PortfolioHandoffCancel"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PortfolioHandoffResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    mark_portfolio_handoff_executed_mandates__mandate_id__portfolio_handoffs__handoff_id__mark_executed_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                handoff_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PortfolioHandoffMarkExecuted"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PortfolioHandoffResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    refresh_portfolio_live_prices_mandates__mandate_id__portfolio_refresh_prices_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_mandate_selections_mandates__mandate_id__protocol_bausteine_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MandateBausteinSelectionResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    replace_mandate_selections_mandates__mandate_id__protocol_bausteine_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MandateBausteinSelectionUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MandateBausteinSelectionResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_recommendations_mandates__mandate_id__recommendations_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationRunResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_recommendation_run_mandates__mandate_id__recommendations_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecommendationRunCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationRunResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_current_recommendation_payload_mandates__mandate_id__recommendations_current_payload_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationGenerateResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    generate_recommendation_run_endpoint_mandates__mandate_id__recommendations_generate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecommendationGenerateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationGenerateResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_eligibility_overrides_mandates__mandate_id__recommendations__run_id__eligibility_overrides_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    request_eligibility_override_mandates__mandate_id__recommendations__run_id__eligibility_overrides_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["EligibilityOverrideRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    approve_eligibility_override_mandates__mandate_id__recommendations__run_id__eligibility_overrides__override_id__approve_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                run_id: string;
                override_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["EligibilityOverrideApprovalRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    finalize_recommendation_mandates__mandate_id__recommendations__run_id__finalize_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationRunResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_holdings_mandates__mandate_id__recommendations__run_id__holdings_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationHoldingResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_recommendation_payload_by_id_mandates__mandate_id__recommendations__run_id__payload_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationGenerateResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    preview_portfolio_handoff_mandates__mandate_id__recommendations__run_id__portfolio_handoff_preview_get: {
        parameters: {
            query?: {
                confirm_no_existing_holdings?: boolean;
            };
            header?: never;
            path: {
                mandate_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PortfolioHandoffPreviewResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_portfolio_handoff_mandates__mandate_id__recommendations__run_id__portfolio_handoffs_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PortfolioHandoffCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PortfolioHandoffResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_positions_mandates__mandate_id__recommendations__run_id__positions_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationPositionResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    add_position_mandates__mandate_id__recommendations__run_id__positions_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                run_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecommendationPositionCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationPositionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upsert_position_holding_mandates__mandate_id__recommendations__run_id__positions__position_id__holding_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                run_id: string;
                position_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RecommendationHoldingUpsert"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RecommendationHoldingResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_position_holding_mandates__mandate_id__recommendations__run_id__positions__position_id__holding_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                run_id: string;
                position_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_report_notes_mandates__mandate_id__report_notes_get: {
        parameters: {
            query?: {
                history_limit?: number;
                history_offset?: number;
            };
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReportNotesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_report_notes_mandates__mandate_id__report_notes_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReportNotesUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReportNotesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_advisory_report_pdf_mandates__mandate_id__reports_advisory_report_pdf_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/pdf": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_anlagestrategie_pdf_mandates__mandate_id__reports_anlagestrategie_pdf_get: {
        parameters: {
            query?: {
                expected_allocation_id?: string | null;
            };
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/pdf": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_assetallocation_pdf_mandates__mandate_id__reports_assetallocation_pdf_get: {
        parameters: {
            query?: {
                expected_allocation_id?: string | null;
            };
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/pdf": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_backtest_pdf_mandates__mandate_id__reports_backtest_pdf_get: {
        parameters: {
            query?: {
                start_year?: number | null;
                end_year?: number | null;
                benchmark_equities_bps?: number | null;
                benchmark_bonds_bps?: number | null;
                benchmark_real_estate_bps?: number | null;
                benchmark_alternatives_bps?: number | null;
                benchmark_liquidity_bps?: number | null;
                resolution?: string;
                strategy_fee_bps?: number | null;
                benchmark_fee_bps?: number | null;
            };
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/pdf": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_contract_signoff_pdf_mandates__mandate_id__reports_contract_signoff_pdf_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/pdf": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_cost_disclosure_pdf_mandates__mandate_id__reports_cost_disclosure_pdf_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/pdf": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_depotcheck_pdf_mandates__mandate_id__reports_depotcheck_pdf_get: {
        parameters: {
            query?: {
                analysis_snapshot_id?: string | null;
            };
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/pdf": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_portfolio_pdf_mandates__mandate_id__reports_portfolio_pdf_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/pdf": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_protokoll_pdf_mandates__mandate_id__reports_protokoll_pdf_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/pdf": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_risikoprofil_pdf_mandates__mandate_id__reports_risikoprofil_pdf_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/pdf": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_vertrag_pdf_mandates__mandate_id__reports_vertrag_pdf_get: {
        parameters: {
            query?: {
                document_id?: string | null;
            };
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/pdf": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_risk_assessments_mandates__mandate_id__risk_assessments_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskAssessmentResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_risk_assessment_mandates__mandate_id__risk_assessments_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RiskAssessmentCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskAssessmentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_current_risk_assessment_mandates__mandate_id__risk_assessments_current_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskAssessmentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    override_risk_assessment_mandates__mandate_id__risk_assessments__ra_id__override_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                ra_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RiskAssessmentOverride"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RiskAssessmentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_risk_capacity_plausibility_mandates__mandate_id__risk_capacity_plausibility_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_risk_capacity_plausibility_evaluations_mandates__mandate_id__risk_capacity_plausibility_evaluations_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    sign_risk_profile_mandates__mandate_id__risk_profile_sign_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["RiskProfileSignRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_snapshots_mandates__mandate_id__strategy_snapshots_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategySnapshotResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_snapshot_mandates__mandate_id__strategy_snapshots_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["StrategySnapshotCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StrategySnapshotResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_drift_mandates__mandate_id__strategy_snapshots_latest_drift_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DriftResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_suitability_checks_mandates__mandate_id__suitability_checks_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuitabilityCheckResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_suitability_check_mandates__mandate_id__suitability_checks_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SuitabilityCheckCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuitabilityCheckResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_target_allocation_mandates__mandate_id__target_allocation_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TargetAllocationCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TargetAllocationResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_current_allocation_mandates__mandate_id__target_allocation_current_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TargetAllocationResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_current_allocation_analysis_integrity_mandates__mandate_id__target_allocation_current_analysis_integrity_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_current_allocation_payload_mandates__mandate_id__target_allocation_current_payload_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TargetAllocationGenerateResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    generate_target_allocation_endpoint_mandates__mandate_id__target_allocation_generate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TargetAllocationGenerateRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TargetAllocationGenerateResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    goal_target_sensitivity_mandates__mandate_id__target_allocation_sensitivity_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AllocationSensitivityRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AllocationSensitivityResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_triggers_mandates__mandate_id__triggers_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewTriggerResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_trigger_mandates__mandate_id__triggers_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReviewTriggerCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewTriggerResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    refresh_system_triggers_mandates__mandate_id__triggers_system_refresh_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewTriggerResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_trigger_frequency_mandates__mandate_id__triggers__trigger_id__frequency_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                trigger_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReviewTriggerFrequencyUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewTriggerResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resolve_trigger_mandates__mandate_id__triggers__trigger_id__resolve_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                mandate_id: string;
                trigger_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReviewTriggerResolve"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReviewTriggerResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    issue_my_calendar_feed_token_me_calendar_feed_token_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CalendarFeedTokenResponse"];
                };
            };
        };
    };
    revoke_my_calendar_feed_token_me_calendar_feed_token_delete: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    get_onsite_signature_policy_onsite_signature_policy_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    list_optimizer_policies_read_optimizer_policies_get: {
        parameters: {
            query?: {
                include_historic?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OptimizerPolicyResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_current_policy_optimizer_policies_current_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    open_erasure_case_privacy_erasure_cases_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ErasureCaseOpen"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_erasure_case_privacy_erasure_cases__case_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                case_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    execute_erasure_case_privacy_erasure_cases__case_id__execute_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                case_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    refresh_erasure_case_privacy_erasure_cases__case_id__refresh_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                case_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_legal_holds_privacy_legal_holds_get: {
        parameters: {
            query?: {
                client_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    propose_legal_hold_privacy_legal_holds_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LegalHoldProposal"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    approve_legal_hold_privacy_legal_holds__hold_id__approve_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                hold_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    extend_legal_hold_privacy_legal_holds__hold_id__extend_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                hold_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LegalHoldExtension"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    release_legal_hold_privacy_legal_holds__hold_id__release_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                hold_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_policies_privacy_policies_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    propose_policy_privacy_policies_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PolicyProposal"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    approve_policy_privacy_policies__policy_id__approve_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                policy_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    run_retention_expiry_privacy_retention_expiry_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    list_roles_privacy_roles_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    grant_role_privacy_roles_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RoleGrant"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    revoke_role_privacy_roles__designation_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                designation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    privacy_status_privacy_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    list_product_universe_entries_product_universe_get: {
        parameters: {
            query?: {
                jurisdiction?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductUniverseEntryResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_product_universe_entry_product_universe_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductUniverseEntryCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductUniverseEntryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_product_universe_entry_product_universe__entry_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                entry_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductUniverseEntryUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductUniverseEntryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_product_universe_entry_product_universe__entry_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                entry_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_products_products_get: {
        parameters: {
            query?: {
                asset_class?: string;
                /** @description SFDR-Klassifizierung (Sustainable Finance Disclosure Regulation). Erlaubte Werte: '6' (Standard, keine ESG-Werbung), '8' (ESG-Werbung mit nachhaltigen Merkmalen), '9' (Nachhaltigkeits-Ziel als Anlage-Ziel). Sprint U-95 (2026-06-05). */
                sfdr_class?: string | null;
                /** @description ESG-Rating-Filter (case-insensitive exact match). Sprint U-95 (2026-06-05). */
                esg_rating?: string | null;
                /** @description Freitext-Suche ueber Produktname/Anbieter/ISIN/Symbol (case-insensitive, Substring). Fondsuniversum (2026-08-05). */
                q?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_product_products_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_product_eligibility_drafts_products_eligibility_drafts_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductEligibilityDraftsResponse"];
                };
            };
        };
    };
    apply_product_reference_data_products_eodhd_apply_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductReferenceApplyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductReferenceApplyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    auto_apply_product_reference_data_products_eodhd_auto_apply_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductReferenceBatchApplyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductReferenceBatchApplyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resolve_product_reference_data_products_eodhd_resolve_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductReferencePreviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductReferencePreviewResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    import_products_bulk_products_import_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductBulkImportRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductImportResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    import_products_csv_products_import_csv_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_import_products_csv_products_import_csv_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductImportResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_products_csv_template_products_import_csv_template_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    get_product_market_data_status_products_market_data_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    apply_product_id_mapping_products_openfigi_apply_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductIdMappingApplyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductIdMappingApplyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    auto_apply_product_id_mappings_products_openfigi_auto_apply_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductIdMappingBatchApplyRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductIdMappingBatchApplyResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resolve_product_id_mapping_products_openfigi_resolve_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductIdMappingPreviewRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductIdMappingPreviewResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_product_products__product_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                product_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    approve_product_eligibility_rule_products__product_id__eligibility_rule_approve_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                product_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["ProductEligibilityApprovalRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductEligibilityApprovalResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    set_product_market_override_products__product_id__market_override_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                product_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProductMarketOverrideRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProductMarketOverrideResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_bausteine_protocol_bausteine_get: {
        parameters: {
            query?: {
                category?: string | null;
                include_inactive?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BausteinResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_baustein_protocol_bausteine_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BausteinCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BausteinResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_baustein_protocol_bausteine__baustein_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                baustein_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BausteinUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BausteinResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_baustein_protocol_bausteine__baustein_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                baustein_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    estimate_tax_tax_estimate_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TaxProfileInput"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaxEstimateResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_tax_jurisdictions_tax_jurisdictions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TaxJurisdictionListItem"][];
                };
            };
        };
    };
    list_tenants_tenants_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantResponse"][];
                };
            };
        };
    };
    create_tenant_tenants_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TenantCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_my_tenant_tenants_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantSelfResponse"];
                };
            };
        };
    };
    update_my_tenant_tenants_me_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TenantSelfServiceUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_tenant_tenants__tenant_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_tenant_tenants__tenant_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TenantUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TenantResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    assign_user_to_tenant_tenants__tenant_id__users__user_id__assign_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                tenant_id: string;
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": Record<string, unknown>;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_users_users_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserResponse"][];
                };
            };
        };
    };
    create_user_users_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UserCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    invite_user_users_invite_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InviteCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InviteResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_user_users__user_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UserUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_adviser_registration_users__user_id__adviser_registration_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdviserRegistrationResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upsert_adviser_registration_users__user_id__adviser_registration_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AdviserRegistrationCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdviserRegistrationResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    revoke_invite_users__user_id__invite_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resend_invite_users__user_id__invite_resend_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InviteResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reset_user_password_users__user_id__password_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UserPasswordReset"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_wealth_inflow_wealth_inflows__inflow_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                inflow_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["WealthInflowUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WealthInflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_wealth_inflow_wealth_inflows__inflow_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                inflow_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
