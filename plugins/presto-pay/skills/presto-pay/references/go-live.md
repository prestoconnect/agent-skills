# Go live, troubleshoot, review

The production checklist, symptoms and fixes, and how to review an existing integration. SDK-specific names
(error classes, options, staging smoke test) are in the language file's "Production" section.

## Contents

- [Going live checklist](#going-live-checklist)
- [Troubleshooting](#troubleshooting)
- [Reviewing an existing integration](#reviewing-an-existing-integration)

## Going live checklist

Keys and configuration:

- [ ] A separate key pair for production, with its public key registered with Presto.
- [ ] Production environment selected, with the production `mid`, `prestoMrn` and Presto certificate. No staging
      value anywhere in production configuration.
- [ ] Private key and its password loaded from a secret store or environment, not from source control or the
      image.
- [ ] `notifyUrl` and `redirectUrl` built from the production public base URL; `notifyUrl` is a public HTTPS URL
      Presto can reach.
- [ ] Host clock synced with NTP.

Behaviour:

- [ ] One client per process (per `mid`), created at startup.
- [ ] Amounts sent as integers in minor units.
- [ ] `txnRefNum` unique per payment attempt; `paymentRefNum` stored before the redirect.
- [ ] Return page `query`s the payment and never trusts the redirect or its parameters.
- [ ] Webhook handler verifies the raw body, returns 401 for signature errors, `query`s the payment,
      deduplicates on `eventRefNum` under a unique constraint in the same transaction as the order update, and
      replies "resend" when its own processing fails.
- [ ] Return page and webhook share one idempotent update function; fulfilment happens once.
- [ ] After an unknown outcome: `init` resent with the same `txnRefNum`; `reverse` / `refund` only after a
      `query`.
- [ ] Unknown status, payment method and error codes handled without crashing.
- [ ] `errorCode` and `errorMessage` logged for API errors; error body redaction left on.
- [ ] Refunds behind admin authorization, with an audit trail.

Testing:

- [ ] Unit tests with the client stubbed: paid, pending, failed, expired, unknown status, duplicate webhook,
      signature error, `query` failure inside the webhook.
- [ ] One full payment on staging: `init`, pay on Presto's page, return page, webhook received and
      deduplicated, then a refund or reversal. Run the SDK's staging smoke test if it has one, and strict mode in
      staging where the SDK offers it.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `1005` on every call | Host clock more than 15 minutes off | Sync with NTP. The SDKs use a fixed UTC+08:00 offset whatever the host time zone, so time zone settings aren't the cause |
| `1006` / `1007` | Private key doesn't match the public key registered for this environment, or staging/production mixed | Check which key is loaded; compare public key fingerprints with what was sent to Presto. The SDK's error exposes the canonical string it signed |
| Signature error on a payment *response* | Wrong Presto certificate for this environment, or Presto rotated its key | Use the certificate for this environment. During an announced rotation, configure both old and new certificates where the SDK accepts several (see the language file) |
| `1102` / `1106` | `mid` / `prestoMrn` not valid for this environment | Use the values for this environment |
| Webhooks never arrive | `notifyUrl` not reachable: `localhost`, private address, firewall, wrong path | Public URL; tunnel such as ngrok in development; check the route accepts POST and isn't behind login or CSRF |
| Webhooks fail signature verification | Body parsed or re-serialized before verifying; `mid` not configured on the verifier; clock off; wrong certificate | Verify the raw bytes; add the `mid`; NTP; certificate for this environment |
| Order paid twice / fulfilled several times | No `eventRefNum` dedup, or return page and webhook both fulfil | Unique constraint on `eventRefNum`; one update function that fulfils only on the transition into `Authorised` |
| Shopper paid but order shows unpaid | Return page trusts the redirect but `query` failed, or webhook replied OK without processing | `query` on the return page and show "processing" for `PendingAuthorise`; reply "resend" when processing fails |
| `paymentUrl` missing after `init` | Gateway returned no URL | Treat as a failure; don't redirect. Log the response and check the `txnType` |
| Amount 100 times off | Major units sent instead of minor | Convert to integer minor units |
| An endpoint the SDK doesn't cover | | Each SDK has a raw signed-call escape hatch; see the language file. Don't hand-sign |

## Reviewing an existing integration

Go through the code in this order, and report each finding with file and line, what can go wrong in money terms,
and the fix:

1. **Signing.** Any hand-written signing, canonical strings, direct HTTP calls to the gateway, or a
   non-official Presto library. Replace with the SDK.
2. **Secrets.** Private keys, keystore passwords or PEM text in the repository, committed config, images or
   logs. If one is committed, the key must be treated as compromised: generate a new pair and register it.
3. **Status source.** Anything that marks an order paid from the redirect, redirect parameters, the webhook's
   `eventCode` / `success`, or the `init` response, instead of `query`.
4. **Webhook.** Raw-body verification, 401 on signature errors, correct OK / resend replies, `eventRefNum`
   dedup with a unique constraint, CSRF exemption.
5. **Idempotency.** One update path for return page and webhook; fulfilment once; no generic retries around
   `reverse` / `refund`; `query` before retrying after an unknown outcome.
6. **Money.** Integer minor units everywhere, no floats; refunds authorized and audited.
7. **Configuration.** Environment chosen explicitly; staging and production values separated; one client per
   process per `mid`.
8. **Robustness.** Unknown statuses, methods and error codes handled; deadline below the server timeout; errors
   logged with `errorCode`.
9. **SDK version.** Compare with the version in the language file and the SDK's changelog.

Rank the findings by impact: lost or double-moved money and leaked keys first, then missed payments, then
robustness.
