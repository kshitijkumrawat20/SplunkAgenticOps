# Database Incident Runbook

This runbook describes how to investigate and remediate database issues in `order-service`.

## Incidents Covered
* `Database Timeout`
* `Connection Pool Exhausted`
* `Query Timeout`

## Investigation Steps
1. Check if the database instance CPU utilization is above 90%.
2. Verify the number of active sessions using the query `SELECT count(*) FROM pg_stat_activity;`.
3. If `Connection Pool Exhausted` is present, look for unclosed database connections or slow-running queries holding connections.

## Remediation Steps
* **For Connection Pool Exhausted**:
  * Increase the maximum connections pool size in the service configuration.
  * Restart the `order-service` to clear stale connections.
* **For Database/Query Timeout**:
  * Verify indexing is applied on frequently searched query fields (e.g., `order_id`, `user_id`).
  * If write volume is extremely high, scale the database read replica.
