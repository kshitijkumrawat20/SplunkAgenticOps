# Redis Caching Runbook

This runbook covers issues related to cache failure and Redis connection issues in `cart-service`.

## Incidents Covered
* `Redis Connection Failed`
* `Cache Unavailable`

## Investigation Steps
1. Verify if the Redis service is running: `ping` the Redis cluster.
2. Check network latency between `cart-service` and the Redis cluster.
3. Check Redis memory limits: Run `INFO memory` to check if memory exhaustion has triggered eviction policies.

## Remediation Steps
* **For Redis Connection Failed**:
  * Check and restore network security groups/firewall configurations.
  * Restart the Redis cluster if offline.
* **For Cache Unavailable**:
  * Enable failover to a replica node.
  * Ensure the fallback mechanism in `cart-service` is active (the application should degrade gracefully by querying the primary database directly).
