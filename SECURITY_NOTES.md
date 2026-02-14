# Security Notes

This project is an internal utility. Before company-wide rollout, apply controls below.

## Current Risks

- No built-in authentication or role-based access control in app UI.
- Users can run arbitrary SQL in `Query(DB) -> DB` mode.
- Destructive option exists: clear destination table before load.
- DB credentials are entered in UI and kept in Streamlit session state.
- No centralized audit log for who executed which load.

## Minimum Controls For Internal Use

- Restrict network access (VPN, internal segment, allowlist).
- Expose app only to trusted engineers.
- Use least-privilege DB accounts.
- Separate read-only source users from write-only destination users.
- Disable or gate destructive operations for non-admin users.
- Add basic request logging (who, when, source, destination, table, row count).

## Recommended Next Improvements

- Add app authentication (SSO or internal auth proxy).
- Add RBAC by environment/schema/table.
- Add SQL guardrails (allowlist/denylist, max rows/time).
- Add approval flow for `clear_before` actions.
- Add retention policy for logs and operational metrics.

## Operational Guidance

- Use this tool for ETL-lite tasks, migrations, and ad-hoc loads.
- Avoid using it as a public ingestion endpoint.
- For large/critical pipelines, prefer scheduled, versioned ETL jobs.
