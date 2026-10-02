# Changelog

## Unreleased

- At the end of a full integration, the `presto-pay` skill now reminds the merchant to review every change
  before merging, since they own the code that moves their money, and to include a redelivered webhook in the
  staging payment.

## 0.2.0

- Webhook guidance now guards on the order record instead of deduplicating on `eventRefNum`: query on every
  delivery and apply the status with a conditional update that finalises the order only once and fulfils only on
  the change into `Authorised`. Updated `SKILL.md`, `webhooks.md`, `go-live.md`, every language file and the
  evaluation expectations.
- Renamed the plugin and the marketplace to `prestoconnect` so further skills can be added later, and moved the
  repository to `prestoconnect/agent-skills`. Install with `/plugin install prestoconnect@prestoconnect`. If you
  added the earlier `presto-pay` marketplace, remove it with `/plugin marketplace remove presto-pay` and add this
  repository again.
- Removed the 2026-10-02 evaluation write-up, which predated the webhook change.

## 0.1.0

- First release: the `presto-pay` skill for integrating Presto Pay with the official SDKs for Go 0.3.2,
  Java 0.2.1, JavaScript 0.2.2, PHP 0.2.0 and Python 0.1.2. Covers setup, checkout, webhooks, refunds and
  errors, going live, troubleshooting and reviewing an existing integration.
