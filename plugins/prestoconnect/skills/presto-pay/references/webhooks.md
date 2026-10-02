# Webhooks

Presto POSTs a signed JSON body to the `notifyUrl` given on `init`, `reverse` or `refund`. Handler code for each
framework is in the language file's "Webhooks" section.

## Contents

- [What a webhook tells you](#what-a-webhook-tells-you)
- [The handler](#the-handler)
- [Verify the raw body](#verify-the-raw-body)
- [Choosing the reply](#choosing-the-reply)
- [Redeliveries: guard on the order](#redeliveries-guard-on-the-order)
- [Clock and freshness window](#clock-and-freshness-window)
- [Local development](#local-development)
- [Mistakes to avoid](#mistakes-to-avoid)

## What a webhook tells you

A webhook says that something happened to a payment, not the payment's resulting status:

- `eventCode`: what happened. `Authorised`, `Cancelled`, `Reversed`, `Refunded`, `Expired`, or a newer code.
- `success`: whether it worked. A `Refunded` event with `success: false` is a refund that failed, and the payment
  keeps its previous status, which the event doesn't carry.
- Also: `mid`, `prestoMrn`, `paymentRefNum`, `txnRefNum`, `eventRefNum`, `eventTs`, `amount`, `currencyCode`,
  and optionally `paymentDetails`.

So the handler calls `query` for the status. Never derive a status from `eventCode` and `success`.

## The handler

In order:

1. Read the **raw** request body.
2. Verify it with the SDK. On a signature error, reply **HTTP 401** with no body.
3. If verification fails because the body is malformed, reply HTTP 200 with the "OK / don't resend" ack. It would
   fail the same way on every redelivery.
4. `query` the payment by `prestoMrn` and `paymentRefNum` from the event, on every delivery.
5. Apply the status to the order through the same guarded function the return page uses (see
   [Redeliveries](#redeliveries-guard-on-the-order)), inserting the fulfillment job in the same transaction only
   when this call moved the order into `Authorised`.
6. Reply HTTP 200 with the OK ack, whether or not the order changed. If steps 4 or 5 failed (database down,
   `query` failed), reply HTTP 200 with the "resend" ack instead, so Presto delivers it again.

The ack bodies are `{"resend":false}` (handled) and `{"resend":true}` (deliver again), with content type
`application/json`. Use the SDK's ack helper rather than writing the JSON by hand.

The endpoint needs no session or login, and must be excluded from CSRF protection (Django `@csrf_exempt`, Laravel
`VerifyCsrfToken` exceptions, Spring Security `ignoringRequestMatchers`, and so on). The signature is what
authenticates it.

## Verify the raw body

The signature covers the exact bytes Presto sent. A framework that parses JSON into an object, and code that
re-serializes it, changes key order, spacing or number formatting, and the signature no longer matches. Read the
body as bytes or a string before any JSON middleware touches it:

- Express: `express.raw({ type: "application/json" })` on the webhook route only, or `express.text`.
- Next.js route handlers: `await request.text()`.
- Spring: `@RequestBody String` or `byte[]`, not a DTO.
- Laravel / Symfony: `$request->getContent()`.
- Django `request.body`, Flask `request.get_data()`, FastAPI `await request.body()`.
- Go: `io.ReadAll(r.Body)` with a size limit.

The SDK's verifier then checks, in order: the signature, the required fields, that `mid` is one of the merchant's
IDs, and that the timestamp is within 15 minutes of the server clock in either direction.

## Choosing the reply

| Situation | Reply | Why |
|-----------|-------|-----|
| Signature error: bad signature, another `mid`, stale timestamp | HTTP 401, no body | Not from Presto, or not for this merchant |
| Malformed body | HTTP 200, OK (`resend:false`) | It fails the same way every time; resending only builds a loop |
| Order already in that status | HTTP 200, OK | Redelivery, or the return page got there first |
| Processed successfully | HTTP 200, OK | Done |
| Own failure: database, `query` error, anything transient | HTTP 200, resend (`resend:true`) | Presto redelivers so the next attempt can succeed |

Never reply "resend" for a signature error or a malformed body. Some SDKs have a helper that picks OK or resend
from the exception; check for the signature error first, since 401 is the right answer there.

## Redeliveries: guard on the order

Presto resends with a backoff of 2, 4, 8, 16, 32, 64, 128, 256, 512 and 1024 minutes between attempts, up to 11
deliveries over about 34 hours. Each delivery carries a fresh timestamp, so it always passes the freshness check.
The return page may also update the same order first. Don't track events; check the order record:

- Apply the queried status in one conditional update, so only one caller can finalise the order:
  `UPDATE orders SET status = :new WHERE txn_ref_num = :ref AND status = 'PendingAuthorise'`.
- Fulfil only when that update changed a row and the new status is `Authorised`, and insert the fulfillment job
  in the same transaction. A crash rolls both back, so the redelivery can try again.
- Once the order is finalised, apply only the statuses that can follow payment (`PendingRefund`,
  `PartialRefunded`, `Refunded`, `PendingReverse`, `Reversed`), never fulfil again, and never let a stale result
  move it backwards (see [Payment statuses](checkout.md#payment-statuses)).

The condition must be in the update itself. An `if` that reads the order first and then writes lets the return
page and a webhook both pass the check when they arrive together. With the condition in the update, a redelivery
or a replay finds the order already in that status, changes nothing, and still gets the OK ack.

## Clock and freshness window

The verifier rejects a webhook whose timestamp is more than 15 minutes from the server's clock, as a signature
error. Keep the host clock in sync with NTP. If webhooks are queued before verification, the SDKs let you widen
or disable the window; do that only when the order update is guarded as above.

## Local development

`notifyUrl` must be reachable from the internet. `localhost` and private addresses don't work. Use a tunnel such
as ngrok and build `notifyUrl` from a configurable public base URL. The return page works on `localhost`, because
the shopper's own browser follows `redirectUrl`.

A service that only receives webhooks, without making payment calls, needs Presto's certificate and the merchant
IDs but not the private key; each SDK has a standalone verifier for that.

## Mistakes to avoid

- Parsing the JSON body, or binding it to a DTO, before verifying.
- Fulfilling the order from `eventCode` or `success` instead of `query`.
- Fulfilling on every delivery: up to 11 shipments for one payment. Guard on the order's status instead.
- Replying "resend" to a bad signature, which makes Presto retry something that can never succeed.
- Replying non-200 when your own processing fails: use the "resend" ack instead, so the reply means what you
  intend.
- Long work inside the handler. Do the `query` and the order update, then hand slow work (emails, fulfilment
  jobs) to a queue.
