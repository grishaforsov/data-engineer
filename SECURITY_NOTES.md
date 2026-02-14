# Security Notes

This project is an internal utility. Before company-wide rollout, apply controls below.

## Current Risks

- DB credentials are entered in UI and kept in Streamlit session state.
- SQL guardrails are best-effort and should not replace DB-side permissions.
- Destructive option still exists for admins (`clear_before`), so strict RBAC is required.

## Minimum Controls For Internal Use

- Restrict network access (VPN, internal segment, allowlist).
- Expose app only to trusted engineers.
- Use least-privilege DB accounts.
- Separate read-only source users from write-only destination users.
- Disable or gate destructive operations for non-admin users.
- Add basic request logging (who, when, source, destination, table, row count).

## Recommended Next Improvements

- Replace local env-based auth with SSO/internal auth proxy.
- Add RBAC by environment/schema/table (not only app-level role).
- Add SQL allowlist policy (approved datasets/tables), not only keyword checks.
- Add approval flow for `clear_before` actions.
- Add retention policy for logs and operational metrics.

## Operational Guidance

- Use this tool for ETL-lite tasks, migrations, and ad-hoc loads.
- Avoid using it as a public ingestion endpoint.
- For large/critical pipelines, prefer scheduled, versioned ETL jobs.
