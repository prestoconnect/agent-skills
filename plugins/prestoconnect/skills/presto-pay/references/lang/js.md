# JavaScript / TypeScript: @prestouniverse/presto-pay-sdk

Written against **@prestouniverse/presto-pay-sdk 0.2.2**. Source and full docs:
https://github.com/prestoconnect/presto-pay-sdk-js

- Node 18.20+, Cloudflare Workers, Vercel Edge. Zero runtime dependencies (Web Crypto).
- **Server-side only, ESM-only.** It refuses to load in a browser, because the private key must never reach
  client code. Never import it from a React/Vue/Svelte client component, a `"use client"` file, or code bundled
  for the browser. On Node 18.20–22.11, CommonJS code loads it with `await import(...)`.
- Request and response properties are the wire names: `txnRefNum`, `prestoMrn`, `paymentUrl`.
- Constants are frozen objects whose keys are the wire values: `TxnType.WebPay`, `PaymentStatus.Authorised`,
  `PaymentMethod.PmPgCard`. Error codes are PascalCase: `ErrorCode.PaymentNotFound`. Status and method fields
  are `string`.
- Recognise errors with `isPrestoPayError(error)` and `error.name`, not `instanceof` (two copies of the package
  in a bundle break `instanceof`).

## Contents

- [Install](#install)
- [Keys](#keys)
- [Client](#client)
- [Checkout](#checkout)
- [Webhooks](#webhooks)
- [Refunds and errors](#refunds-and-errors)
- [Production](#production)
- [Framework notes](#framework-notes)

## Install

```bash
npm install @prestouniverse/presto-pay-sdk@^0.2.2
```

Or `pnpm add` / `yarn add` / `bun add`, matching the project's lockfile.

## Keys

The merchant generates its own key pair. Give the user these commands to run themselves:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out merchant-key.pem
openssl req -new -x509 -key merchant-key.pem -days 99999 -subj "/CN=Your Company" -outform DER -out merchant.der
```

- `merchant-key.pem` is the private key in the unencrypted PKCS#8 PEM format the SDK reads
  (`-----BEGIN PRIVATE KEY-----`): secret, out of source control. The SDK doesn't read PKCS#12, PKCS#1
  (`BEGIN RSA PRIVATE KEY`) or encrypted PEM.
- `merchant.der` is the public key in the DER format Presto requires: the user sends it to Presto, once for
  staging and once for production.

To use an existing `.p12`, convert once:

```bash
openssl pkcs12 -in merchant.p12 -nocerts -nodes -out merchant-key.pem
```

OpenSSL 3 may print `unsupported` and exit 1 after writing the key; if the file has a `BEGIN PRIVATE KEY` block,
it worked. Don't pipe this command into another one.

Environment variables hold text, so convert Presto's `.der` certificate to PEM for `PRESTOPAY_PUBLIC_KEY`:

```bash
openssl x509 -inform der -in presto.der -out presto.pem
```

## Client

Prefer configuration from the environment:

```ts
import { createPrestoPay, fromEnv } from '@prestouniverse/presto-pay-sdk';

export const presto = createPrestoPay(fromEnv(process.env));
```

| Variable | Value |
|----------|-------|
| `PRESTOPAY_ENV` or `PRESTOPAY_BASE_URL` | `staging` or `production`, or a gateway base URL (wins if both are set) |
| `PRESTOPAY_MID` | The merchant's `mid` |
| `PRESTOPAY_PRIVATE_KEY` | The text of `merchant-key.pem`, with real line breaks |
| `PRESTOPAY_PUBLIC_KEY` | Presto's certificate as PEM text, with real line breaks |

`fromEnv` accepts any string record: `process.env`, a Workers `env` binding, Vercel's env. Other options:
`createPrestoPay({ ...fromEnv(process.env), deadlineMs: 20_000 })`.

`prestoMrn` is not a client setting; it goes on every call. Add your own variable for it, such as
`PRESTOPAY_MRN`.

Explicit construction:

```ts
import { readFileSync } from 'node:fs';
import { createPrestoPay } from '@prestouniverse/presto-pay-sdk';

export const presto = createPrestoPay({
  environment: 'staging', // or 'production'
  merchantId: process.env.PRESTOPAY_MID!,
  privateKey: readFileSync(process.env.PRESTOPAY_PRIVATE_KEY_FILE!, 'utf8'),
  prestoPublicKey: readFileSync(process.env.PRESTOPAY_PUBLIC_KEY_FILE!), // DER bytes or PEM text
});
```

Create the client once in a server-only module (for example `src/server/presto.ts` or `lib/presto.server.ts`)
and import it where needed. In Workers, create it lazily from the `env` binding on first request and cache it in
module scope.

Never expose these variables to the client bundle: no `NEXT_PUBLIC_`, `VITE_`, `PUBLIC_` or `REACT_APP_` prefix.

## Checkout

### Start a payment

```ts
import { PaymentMethod, TxnType } from '@prestouniverse/presto-pay-sdk';

const payment = await presto.payments.init({
  prestoMrn: process.env.PRESTOPAY_MRN!,
  txnType: TxnType.WebPay,
  txnRefNum: order.txnRefNum,
  displayDesc: `Order ${order.id}`,
  amount: order.totalMinorUnits, // integer minor units: 10_000 is MYR 100.00
  currencyCode: 'MYR',
  notifyUrl: `${baseUrl}/presto/notify`,
  redirectUrl: `${baseUrl}/presto/return/${order.txnRefNum}`,
  // allowedPaymentMethods: [PaymentMethod.PmPgCard], // only for your own method selection page
});

await orders.update(order.id, {
  paymentRefNum: payment.paymentRefNum,
  paymentStatus: payment.paymentStatus,
});

if (!payment.paymentUrl) throw new Error(`Presto returned no paymentUrl for ${order.txnRefNum}`);
res.redirect(303, payment.paymentUrl); // Express; Next.js: redirect(payment.paymentUrl)
```

A missing or invalid field throws `PrestoPayConfigError` (with `field`) before anything is sent. `amount` must be
an integer. Keep money in integer minor units throughout the app; if prices are stored as decimal strings,
convert with a decimal library, not float arithmetic. Optional: `receiptName`, `receiptEmail`.

If the outcome is unknown, resend `init` with the same request:

```ts
import { mayHaveSucceeded } from '@prestouniverse/presto-pay-sdk';

let payment;
try {
  payment = await presto.payments.init(request);
} catch (error) {
  if (!mayHaveSucceeded(error)) throw error;
  payment = await presto.payments.init(request); // same txnRefNum: returns the existing payment
}
```

### Query the status

```ts
import { PaymentStatus } from '@prestouniverse/presto-pay-sdk';

const result = await presto.payments.query({
  prestoMrn: process.env.PRESTOPAY_MRN!,
  txnRefNum, // or paymentRefNum
});

if (result.paymentStatus === PaymentStatus.Authorised) {
  // paid
} else if (result.paymentStatus === PaymentStatus.PendingAuthorise) {
  // processing: check again shortly
} else {
  // not paid, or a status this SDK version doesn't know
}
```

Other constants: `Failed`, `Cancelled`, `Expired`, `PendingReverse`, `Reversed`, `PendingRefund`,
`PartialRefunded`, `Refunded`.

`method` on each `paymentDetails` entry is a `string`; give any `switch` on it a `default` that stores and shows
an unknown code as it is. The `PaymentMethod` type accepts any string, so a new code needs no cast.

### One update function for return page and webhook

Both callers pass the query result to one order service. In a database transaction, use a conditional update or
row lock to prevent concurrent paid transitions, reject stale status changes, and insert a fulfillment job with a
unique order key when the status first becomes `PaymentStatus.Authorised`. Commit before running fulfillment.
Make the job retryable and fulfillment idempotent. Updating `paymentStatus` and then calling `fulfil(order)` can
leave a paid order unfulfilled if fulfillment fails.

## Webhooks

`presto.webhooks.verify(body)` is async and takes a `string`, a `Uint8Array` / `Buffer`, or an unread `Request`.
It returns a `WebhookEvent` with `eventCode`, `success`, `mid`, `prestoMrn`, `paymentRefNum`, `txnRefNum`,
`eventRefNum`, `amount`, `currencyCode` and `paymentDetails`.

Replies: `NotifyAck.ok` (`{"resend":false}`) and `NotifyAck.resend` (`{"resend":true}`) as JSON strings, or
`NotifyAck.okResponse()` / `NotifyAck.resendResponse()` as Fetch `Response`s. `NotifyAck.forError(error)` /
`NotifyAck.forErrorResponse(error)` pick `ok` for a webhook that failed verification and `resend` for anything
else. Check for `PrestoPaySignatureError` first and answer 401.

Express (raw body on this route only; mount it before any global `express.json()` or exclude the route):

```ts
import express from 'express';
import { isPrestoPayError, NotifyAck } from '@prestouniverse/presto-pay-sdk';

app.post('/presto/notify', express.raw({ type: '*/*' }), async (req, res) => {
  let event;
  try {
    event = await presto.webhooks.verify(req.body);
  } catch (error) {
    if (isPrestoPayError(error) && error.name === 'PrestoPaySignatureError') {
      res.sendStatus(401);
    } else {
      res.type('json').send(NotifyAck.forError(error));
    }
    return;
  }

  try {
    const payment = await presto.payments.query({
      prestoMrn: event.prestoMrn,
      paymentRefNum: event.paymentRefNum,
    });
    // In one transaction: insert event.eventRefNum under a unique constraint; on conflict it's a redelivery,
    // so skip; otherwise apply payment.paymentStatus to the order for event.txnRefNum.
    await handleWebhookOnce(event.eventRefNum, event.txnRefNum, payment.paymentStatus);
  } catch {
    res.type('json').send(NotifyAck.resend);
    return;
  }
  res.type('json').send(NotifyAck.ok);
});
```

Fetch-style handler (Next.js App Router, Workers, Hono via `c.req.raw`, Remix, SvelteKit, Astro):

```ts
import { isPrestoPayError, NotifyAck } from '@prestouniverse/presto-pay-sdk';

export async function POST(request: Request): Promise<Response> {
  let event;
  try {
    event = await presto.webhooks.verify(request);
  } catch (error) {
    if (isPrestoPayError(error) && error.name === 'PrestoPaySignatureError') {
      return new Response(null, { status: 401 });
    }
    return NotifyAck.forErrorResponse(error);
  }
  try {
    const payment = await presto.payments.query({
      prestoMrn: event.prestoMrn,
      paymentRefNum: event.paymentRefNum,
    });
    await handleWebhookOnce(event.eventRefNum, event.txnRefNum, payment.paymentStatus);
  } catch {
    return NotifyAck.resendResponse();
  }
  return NotifyAck.okResponse();
}
```

Don't read the body (`request.json()`, `request.text()`) before passing the `Request`; or read it once with
`await request.text()` and pass the string.

Several `mid`s on one endpoint, or a webhook-only service without the private key:

```ts
import { createWebhookVerifier } from '@prestouniverse/presto-pay-sdk';

const verifier = createWebhookVerifier({
  merchantId: ['MID_A', 'MID_B'],
  prestoPublicKey: prestoCertPemOrDer,
});
const event = await verifier.verify(request); // event.mid picks the client to query with
```

Freshness window: `webhooks: { maxTimestampAgeMs }` on `createPrestoPay`, or `maxTimestampAgeMs` on
`createWebhookVerifier`. Widen only with `eventRefNum` dedup in place.

## Refunds and errors

```ts
const reversal = await presto.payments.reverse({
  prestoMrn,
  paymentRefNum, // or txnRefNum
  reversalRefNum: `${order.txnRefNum}-reversal`,
  remark: 'Customer cancelled', // optional
});

const refund = await presto.payments.refund({
  prestoMrn,
  paymentRefNum,
  refundRefNum: `${order.txnRefNum}-refund-${n}`,
  remark: 'Customer request', // required
  amount: 2_500, // optional: leave it out for a full refund
});
```

`query` then shows `reversalStatus` (`ReversalStatus.Reversing`, `Failed`, `Success`), `refundStatus`
(`RefundStatus.Refunding`, `Failed`, `Success`) and `refundDetails` (each with `refundRefNum`, `refundStatus`).

Every error extends `PrestoPayError` with `operation`, `mayHaveTakenEffect` and `reconcileBy`:

| `name` | Useful properties |
|--------|-------------------|
| `PrestoPayConfigError` | `field` |
| `PrestoPayTransportError` | `requestNotSent` |
| `PrestoPayApiError` | `kind` (`'http'` / `'business'`), `httpStatus`, `errorCode`, `errorMessage`, `rawBody`; `canonical` on `1006`/`1007`; `clockOffsetMs` on `1005` |
| `PrestoPaySignatureError` | `source`, `canonical` |
| `PrestoPayResponseError` | `source`, `rawBody` |

```ts
import { ErrorCode, isPrestoPayError, type PrestoPayApiError } from '@prestouniverse/presto-pay-sdk';

if (
  isPrestoPayError(error) &&
  error.name === 'PrestoPayApiError' &&
  (error as PrestoPayApiError).errorCode === ErrorCode.PaymentNotFound
) {
  // ...
}
```

`isPrestoPayError` narrows to the base `PrestoPayError`, so cast after checking `name` to read subclass
properties.

Unknown outcome on `reverse` / `refund`: query before anything else.

```ts
try {
  await presto.payments.refund(refundRequest);
} catch (error) {
  if (!isPrestoPayError(error) || !error.mayHaveTakenEffect || !error.reconcileBy) throw error;
  const current = await presto.payments.query({ prestoMrn, ...error.reconcileBy });
  // Look for refundRequest.refundRefNum in current.refundDetails before deciding anything.
}
```

Retries are built in: `query` on network errors and 5xx (honouring `Retry-After`); `init` / `reverse` / `refund`
only when `requestNotSent`. Default: 2 retries, 200 ms to 5 s backoff, `deadlineMs` 30 000 for the whole call.
Tune with `retryReads: { maxRetries, initialBackoffMs }` and `deadlineMs`. Each call also takes
`{ signal }` (an `AbortSignal`) as a second argument.

## Production

- `environment: 'production'` (or `PRESTOPAY_ENV=production`) with production credentials.
- `deadlineMs` below the platform's function timeout (Vercel, Lambda, Workers).
- `redactErrorBodies` stays at its default (`true`) so logs don't hold card or customer details.
- Key rotation: `prestoPublicKey: [oldCert, newCert]` during Presto's announced overlap.
- Custom `fetch` option for proxies or tracing; it must not follow redirects or retry on its own.
- Troubleshooting names: `ErrorCode.ExceededValidityPeriod` (`1005`, see `error.clockOffsetMs`),
  `ErrorCode.InvalidSignature` / `ErrorCode.SignatureVerificationFailed` (`1006`/`1007`, see `error.canonical`;
  `canonicalize(body)` rebuilds it), `ErrorCode.InvalidMid`, `ErrorCode.InvalidMerchantReference`,
  `ErrorCode.DuplicateTxnRefNum` (`1203`).
- "The SDK refuses to load" in a Workers or Edge build: the bundler resolves the `browser` export condition ahead
  of `workerd` / `edge-light`; fix the condition order.
- An endpoint the SDK doesn't model: `presto.raw.post('/path', body)`; leave out `mid`, `ts` and `signature`.

## Framework notes

Runnable Express checkout against Presto staging:
https://github.com/prestoconnect/presto-pay-sdk-js/tree/main/sample/my-store

**Express.** `express.raw({ type: '*/*' })` on the webhook route only. If the app mounts `express.json()`
globally, register the webhook route before it or skip JSON parsing for that path.

**Next.js App Router.** Client in a server-only module (add `import 'server-only'`). Checkout as a Server Action
or Route Handler that calls `redirect(payment.paymentUrl)`. Webhook in `app/presto/notify/route.ts` exporting
`POST`, passing the `Request` to `verify`. Return page as a Server Component that `query`s by the `txnRefNum` in
the path. Set `export const dynamic = 'force-dynamic'` on routes that query, so results aren't cached.

**Next.js Pages Router.** Disable the body parser on the webhook API route
(`export const config = { api: { bodyParser: false } }`) and read the raw body from the request stream.

**Cloudflare Workers.** Build the client from the `env` binding with `fromEnv(env)` on first use; keep secrets in
`wrangler secret`, not `wrangler.toml` `vars`. Pass the `Request` to `verify`.

**NestJS.** Enable `rawBody: true` in `NestFactory.create` and use `req.rawBody` in the webhook controller.

**Fastify.** Add a content type parser for `application/json` that keeps the body as a `Buffer` on the webhook
route (`parseAs: 'buffer'`), and pass that buffer.

**Testing.** The client is a plain object; inject it or a fake with `payments.init` / `payments.query` into the
code under test (vitest/jest mocks). Cover an unknown status such as `'SomethingNew'`.
