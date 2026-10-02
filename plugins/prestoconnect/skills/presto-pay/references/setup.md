# Setup

Keys, credentials and client configuration. Install commands, key-generation commands and client code are in
the language file's "Install", "Keys" and "Client" sections.

## Contents

- [What the merchant needs](#what-the-merchant-needs)
- [The merchant's key pair](#the-merchants-key-pair)
- [Configuration](#configuration)
- [The client](#the-client)
- [Several merchants](#several-merchants)
- [Secrets hygiene](#secrets-hygiene)

## What the merchant needs

| Item | Comes from | Used for |
|------|------------|----------|
| Merchant ID (`mid`) | Presto | Set once on the client; sent with every request |
| Presto merchant reference (`prestoMrn`) | Presto | Sent on every request; identifies the shop or outlet. One `mid` can have several |
| Presto certificate (`.der`) | Presto | Verifying Presto's responses and webhooks |
| Merchant private key | The merchant generates it | Signing every request |
| Merchant public key (`.der`) | The merchant generates it, then sends it to Presto | Presto verifies the merchant's signatures with it |

Staging and production are separate: each has its own `mid`, `prestoMrn` and Presto certificate, and the
merchant registers a public key for each. Values from one environment never work in the other, and mixing them
is the most common cause of signature errors.

If the user doesn't have these yet, write the integration against environment variables with placeholder values
and tell them exactly which values to request from Presto. Never make up a `mid` or `prestoMrn`.

## The merchant's key pair

The merchant generates its own RSA 2048-bit key pair. Presto never issues or sees the private key.

1. Generate the pair with the commands in the language file (`openssl`, or `keytool` for Java). The certificate
   is valid for 99999 days, so the pair never needs regenerating and re-registering.
2. Send the public key to Presto as a DER-encoded X.509 certificate (`merchant.der`). Public keys are exchanged
   only as DER, in both directions.
3. Receive Presto's certificate (`presto.der`) for the same environment.

Suggest the user run the generation commands themselves, on the machine or secret store where the key will live,
rather than having the agent create a private key inside the project directory. If a key does get created in the
repository, make sure it is ignored by git before anything is committed.

A merchant may already have a PKCS#12 keystore (`.p12`). The SDKs read those; some use RC2-40 encryption that
the OpenSSL 3 command line rejects without its legacy provider, so prefer the SDK's own loader over converting.

## Configuration

Read every value from the environment or a secret store, through the app's existing settings mechanism. Where the
SDK has a from-environment loader, prefer it. The variables share a `PRESTOPAY_` prefix across languages
(`PRESTOPAY_ENV`, `PRESTOPAY_MID`, the key variables); the exact names are in the language file.

`prestoMrn` is not a client setting in any SDK, because it is per request. Add an app setting for it, for example
`PRESTOPAY_MRN`, next to the others.

Also add app settings for the public base URL used to build `redirectUrl` and `notifyUrl`, so the same code works
locally (tunnel URL), in staging and in production.

When you add configuration:

- Add the variable names with placeholder values to `.env.example` (or the project's equivalent), never to a
  committed `.env`.
- Add key file patterns (`*.pem`, `*.p12`, `*.der` for the merchant's own files, `.env`) to `.gitignore` if not
  already covered. Presto's certificate is public, but keeping key material in one ignored place is simpler.
- Select the environment explicitly (`staging` or `production`) from configuration. Default to staging in
  development configs; never fall back to production silently.

## The client

- Create one client per process at startup and reuse it. Constructing it loads and checks the keys, so bad keys or
  a wrong password fail at startup rather than on the first payment, and per-request construction wastes work.
- Put it where the framework keeps singletons: a Spring bean, a Laravel/Symfony service, a FastAPI lifespan
  object, a Flask extension, a Go struct field passed to handlers, a module-level instance in Node.
- In pre-forking servers, build it after the fork.
- The same client verifies webhooks; it checks the webhook's `mid` against the client's `mid`.

## Several merchants

A platform serving several merchants builds **one client per `mid`**, for example in a map keyed by `mid`, loaded
from the platform's merchant table. Don't pass `mid` per request; the SDKs don't support it, by design. Several
`prestoMrn`s under one `mid` need only one client; pass the right `prestoMrn` per request.

For webhooks, either give each merchant its own `notifyUrl` (for example `/presto/notify/{mid}`) and verify with
that merchant's client, or, where the SDK supports it, verify one endpoint against a set of merchant IDs. The
language file's "Webhooks" section says which. One Presto key signs webhooks for every merchant, so the `mid`
check is what proves an event is for this merchant, not the signature alone.

## Secrets hygiene

- Private key, keystore password and any PEM text: environment or secret store only. Not in source, committed
  config, Docker images, logs, error messages, or the agent's replies.
- Don't print or echo key contents while debugging. To check a key matches, compare public key fingerprints.
- Most SDKs redact card, receipt and customer details from error bodies or messages by default. Keep that on in production.
