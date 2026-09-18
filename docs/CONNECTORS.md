# Connector Development

Northstar has two provider boundaries:

- **Live connectors** authenticate against a read-only provider API and participate in
  manual refresh, scheduled synchronization, freshness, sync-run, reconciliation, and
  credential-replacement workflows.
- **Import sources** accept a provider's native statement when a suitable read-only API
  is unavailable. Their parser and persistence remain provider-specific, while source
  discovery and upload behavior are metadata-driven.

Do not add provider checks to generic services or React pages. If a provider needs new
behavior, express it through its connector definition or extend the common contract only
when the behavior applies to more than one provider.

## Adding a live connector

1. Add the provider value to `Broker` in `backend/app/models/enums.py` and to the frontend
   `Broker` type and `brokerMetadata` in `frontend/src/domain/brokers.ts`.
2. Implement `BrokerConnector` under `backend/app/integrations/connectors/`. It must:
   validate credentials; return normalized current positions; return idempotent activity;
   and return an account snapshot. Use the shared retry helpers and raise only safe
   connector errors.
3. Add one `ConnectorDefinition` in
   `backend/app/integrations/connectors/registry.py`. That definition owns credential
   order/labels, setup copy, display metadata, valuation provenance, synchronization
   cadence, freshness threshold, and any one-time activity cursor.
4. Add mocked contract tests for authentication, permissions, pagination/history limits,
   rate limits, normalized positions/activity, snapshot totals, and stable external IDs.

The registry automatically makes the connector available to credential validation,
Connections guides, sync-all, the correct scheduled synchronization group, provider-aware
freshness checks, and the shared synchronization engine. Those core areas should not
require provider-specific edits.

Current scheduling modes are `intraday` (the configured 1–2 hour portfolio interval) and
`daily` (05:30 UTC). Use `daily` for reporting APIs such as IBKR Activity Flex, whose
underlying data is only refreshed once per day.

## Adding a provider-native import

1. Add the provider to the backend/frontend broker domain and frontend metadata.
2. Implement a provider-specific parser/import service with bounded uploads, validation
   before commit, stable transaction IDs, overlapping-file deduplication, canonical
   instrument resolution, dated FX, and safe errors.
3. Add its authenticated upload route.
4. Add one `ImportSourceDefinition` in `backend/app/integrations/import_sources.py`.
   This supplies the source guide, accepted file types, multi-file behavior, upload copy,
   and endpoint to the generic Connections UI.
5. Test native files, malformed/oversized files, repeat and overlapping imports, atomic
   rollback, tenant ownership, P/L, valuation provenance, and history-only behavior.

## Contract rules

- Integrations are read-only. Never request or enable trading/withdrawal permissions.
- Preserve provider IDs, original currency, timestamps, and raw meaning while returning
  normalized domain objects.
- Never infer missing transactions, dividends, prices, or P/L.
- Keep synchronization idempotent and preserve the last known good portfolio on failure.
- Do not expose credentials or provider payloads in exceptions, logs, or API responses.
- A source must not be marked reconciled unless the provider exposes an independent
  account total.
- Add new generic capability fields only when the core must change its behavior; do not
  branch on a broker name in shared services.
