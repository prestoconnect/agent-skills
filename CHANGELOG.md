# Changelog

## Unreleased

- Webhook guidance now guards on the order record instead of deduplicating on `eventRefNum`: query on every
  delivery and apply the status with a conditional update that finalises the order only once and fulfils only on
  the change into `Authorised`. Updated `SKILL.md`, `webhooks.md`, `go-live.md`, every language file and the
  evaluation expectations.
- Renamed the plugin to `prestoconnect` so further skills can be added to it later, and moved the repository to `prestoconnect/agent-skills`. Install with `/plugin install prestoconnect@presto-pay`. The `presto-pay` skill itself is unchanged.

## 0.1.0

- First release: the `presto-pay` skill for integrating Presto Pay with the official SDKs for Go 0.3.2,
  Java 0.2.1, JavaScript 0.2.2, PHP 0.2.0 and Python 0.1.2. Covers setup, checkout, webhooks, refunds and
  errors, going live, troubleshooting and reviewing an existing integration.
