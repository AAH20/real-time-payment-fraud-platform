# Production readiness boundary

Before a real payment decision:

- Complete PCI DSS scoping, tokenization, privacy and data-residency design.
- Establish payment-network, processor and jurisdictional requirements.
- Use temporal and out-of-time validation with representative class imbalance.
- Calibrate scores and evaluate fairness, appeal and customer-harm outcomes.
- Protect against label leakage, poisoning, evasion and feature manipulation.
- Deploy a resilient online feature store with freshness and completeness contracts.
- Prove P50/P95/P99 latency and throughput under peak traffic.
- Exercise model, feature store, region and stream-processing failure.
- Version rules, features, models, thresholds and decisions for replay.
- Require fraud operations and model-risk approval for promotion.
- Reconcile confirmed fraud, chargebacks, false declines and contribution with finance.

Synthetic benchmark accuracy is not a production fraud-performance claim.
