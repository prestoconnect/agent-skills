---
name: presto-pay
description: Integrate the Presto Pay (Presto Connect) payment gateway into an app with the official Presto Pay SDK for Go, Java, JavaScript/TypeScript, PHP or Python. Use this skill whenever the user mentions Presto Pay, PrestoPay, Presto Connect, or Presto in a payments context, or the code imports a presto-pay-sdk package, even if they don't name the task (not for the Presto/Trino SQL engine). Covers installing the SDK, generating merchant keys and configuring mid, prestoMrn and the Presto .der certificate, adding a checkout or pay button (init and redirect), the return page, querying payment status, the notify webhook, refunds and reversals, handling errors, timeouts and retries, going live in production, troubleshooting signature or timestamp errors such as 1005, 1006 and 1007, and reviewing an existing Presto integration.
---

# Presto Pay

Presto Pay is a payment gateway. Presto publishes an official SDK for Go, Java, JavaScript/TypeScript,
PHP and Python. The SDK signs every request, verifies every response and webhook, and handles the gateway's
timestamps, so the merchant's code never touches the signature scheme. Your job is to wire the SDK into the
merchant's app so that money moves correctly: an order is fulfilled only when Presto says it was paid, nothing is
refunded twice, and no secret leaks.

## 1. Find the merchant's stack

Look at the project root and pick the language file you will read for code:

| Found | Language | Read |
|-------|----------|------|
| `go.mod` | Go | `references/lang/go.md` |
| `pom.xml`, `build.gradle`, `build.gradle.kts` | Java (or Kotlin on the JVM) | `references/lang/java.md` |
| `package.json` | JavaScript / TypeScript | `references/lang/js.md` |
| `composer.json` | PHP | `references/lang/php.md` |
| `pyproject.toml`, `requirements*.txt`, `setup.py` | Python | `references/lang/python.md` |

Also note the web framework (for example Spring Boot, chi, Express, Next.js, Laravel, Symfony, Django, Flask,
FastAPI) and match its idioms; each language file has notes for the common ones. Read only the one language
file you need. If the project has several backends or none yet, ask which one handles payments.

## 2. Read what the task needs

| Task | Read |
|------|------|
| Install the SDK, keys, credentials, client configuration, staging vs production, several merchants | `references/setup.md` |
| Start a payment, redirect to Presto, the return page, payment statuses, payment methods | `references/checkout.md` |
| The notify webhook: verify, deduplicate, reply | `references/webhooks.md` |
| Reverse, refund, errors, timeouts, retries, "did it go through?" | `references/refunds-and-errors.md` |
| Go live, troubleshooting, reviewing an existing integration | `references/go-live.md` |

Then read the matching sections of the language file for code. Use the SDK's real API from those files; don't
guess method names from other payment SDKs, because Presto's names differ (`txnRefNum`, `prestoMrn`, `NotifyAck`).

A request like "add Presto Pay to my app" means a full integration: setup, checkout and webhooks together. A
checkout without its webhook is incomplete, because the shopper may close the browser before returning.

## 3. Rules that protect the merchant's money

These hold in every language. Each one prevents a real failure mode, so keep them even when the user's request
doesn't mention them, and point out existing code that breaks them.

1. **Use the SDK for anything signed.** Never hand-write signing, canonical strings, timestamps or response
   verification, and never call the gateway's HTTP endpoints directly. The gateway rejects tiny differences
   (key order, `1200.0` vs `1200`, time zone), and the SDK is tested against it.
2. **The merchant owns its private key.** The merchant generates its own RSA key pair, sends Presto the public
   key as a `.der` file, and receives Presto's certificate as a `.der` file. Presto never issues the private key.
   Load the private key and any password from environment variables or a secret store. Never write them into
   source, config files that get committed, logs, or your chat replies. Add key files to `.gitignore`.
3. **Ask for credentials; don't invent them.** `mid`, `prestoMrn` and key paths come from the merchant and Presto.
   Use clearly named environment variables and tell the user which values they need to fill in.
4. **Staging and production are separate.** Each has its own `mid`, `prestoMrn` and Presto certificate, and the
   merchant registers its public key for each. Select the environment from configuration, never by default to
   production.
5. **Only `query` tells you the payment status.** The return page redirect only means the shopper came back, and
   a webhook says something happened, not the resulting status. Call `query` in both places and fulfil the order
   only on `Authorised`.
6. **Verify the raw webhook body.** Pass the exact bytes received to the SDK's webhook verifier before any JSON
   parsing or framework body binding, which changes the bytes and breaks the signature.
7. **Webhooks are delivered more than once.** Record each handled `eventRefNum` and skip repeats. Reply with the
   SDK's ack: "OK" when handled, "resend" when your own processing failed so Presto delivers it again.
8. **Return page and webhook race.** They arrive in either order. Route both through one idempotent "update order
   from query result" function.
9. **Amounts are integers in minor units.** `10000` is MYR 100.00. Never use floats for money.
10. **`txnRefNum` is unique per payment, at most 50 characters.** Usually the order ID; generate a new one for a
    new payment attempt on the same order.
11. **Don't blindly resend money-moving calls.** Resending `init` with the same `txnRefNum` is safe: it returns the
    existing payment. Resending `reverse` or `refund` could undo money twice, so on an unknown outcome `query`
    first and only try again if it didn't take effect.
12. **Expect codes the SDK doesn't know.** Presto adds statuses and payment methods without an SDK release. Treat
    unknown strings as "not paid / unknown", store them as they are, and never crash on them.
13. **One client per merchant, created once.** Build the client at startup and reuse it for every request. One
    client serves one `mid`; a platform with several merchants builds one client per `mid`.

## 4. Full integration workflow

1. Confirm the stack and framework, and what the merchant already has: a `mid` and `prestoMrn` from Presto,
   Presto's `.der` certificate, and their own key pair. If they have no key pair yet, give them the commands from
   the language file and tell them to send the `.der` public key to Presto.
2. Install the SDK at the version in the language file.
3. Add configuration through environment variables (the SDK's from-env loader where it has one). Add the
   variable names to `.env.example` or the project's equivalent with placeholder values, and key files to
   `.gitignore`.
4. Create one shared client at startup, in the framework's usual place for singletons.
5. Persist per order: `txnRefNum`, `paymentRefNum` (from `init`), the latest payment status, and the handled
   webhook `eventRefNum`s. Use the app's existing database layer.
6. Checkout endpoint: `init`, save `paymentRefNum`, redirect the shopper to `paymentUrl`.
7. Return page at `redirectUrl`: `query`, update the order, show paid / processing / not paid.
8. Webhook endpoint at `notifyUrl`: verify the raw body, skip handled events, `query`, update the order, reply
   with the ack.
9. Tests: stub the Presto client at the boundary and cover paid, pending, failed, duplicate webhook and
   unknown-status cases. Don't call the real gateway from unit tests.
10. Finish with a short list of what the merchant still has to do: fill in credentials, register their public
    key with Presto, expose `notifyUrl` publicly (a tunnel such as ngrok for local development), and run one
    staging payment end to end.

## 5. Reviewing an existing integration

Check the code against the rules in section 3 and the checklist in `references/go-live.md`. Report each problem
with the file and line, why it matters in money terms, and the fix.

## When this skill and the SDK disagree

The installed SDK is the source of truth. If an API in the language file doesn't exist in the merchant's
installed version, check the SDK's README for that version on GitHub (linked in the language file) and follow it.
