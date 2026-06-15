# Payment Service Runbook

This runbook covers issues related to payment gateway timeouts and unreachable provider connections in `payment-service`.

## Incidents Covered
* `Payment Gateway Timeout`
* `Provider Unreachable`

## Investigation Steps
1. Verify if the internet egress gateway is functional.
2. Check the status page of the third-party payment provider (e.g. Stripe, PayPal) for outages.
3. Check the latency of outward HTTP requests in the application performance monitoring dashboard.

## Remediation Steps
* **For Payment Gateway Timeout**:
  * Implement retry policies with exponential backoff.
  * Adjust timeout configs in HTTP client settings from 5s to 15s to allow for gateway processing delays.
* **For Provider Unreachable**:
  * Check dns resolution for the provider API domain name.
  * Notify the payment provider support team if their system is completely unresponsive.
  * Route payments through the backup provider endpoint.
