# Refunds, reversals and errors

Undoing payments, the SDK's error types, and what to do when you don't know whether a call worked. Code is in the
language file's "Refunds and errors" section.

## Contents

- [Reverse or refund](#reverse-or-refund)
- [Request fields](#request-fields)
- [Errors](#errors)
- [When you don't know whether it worked](#when-you-dont-know-whether-it-worked)
- [Retries and deadlines](#retries-and-deadlines)
- [Error codes](#error-codes)

## Reverse or refund

**`reverse`** undoes a whole payment. What happens depends on the payment's status:

- `PendingAuthorise` (not paid yet): the payment is cancelled; its status becomes `Cancelled`. This is the way to
  cancel a checkout the shopper abandoned.
- `Expired`: fails with `1219` (invalid status for reversal). There is nothing to undo.
- Paid (`Authorised`): the gateway decides. It refuses once the payment has settled (`1220`) or its reversal
  window has passed (`1221`). Use `refund` then.

**`refund`** returns all or part of a paid payment's amount. Omit `amount` for a full refund.

- On an unpaid (`PendingAuthorise`) payment it fails with `1227`; use `reverse` instead.
- It can be requested for any payment method; the gateway decides the outcome. Some methods are settled manually
  or offline, so an accepted refund request doesn't mean the refund is complete. Check `refundStatus` with
  `query` (`Refunding`, `Success`, `Failed`), or wait for the `Refunded` webhook (and `query`), before telling
  anyone the money is back.
- Several partial refunds are allowed up to the paid amount; each needs its own `refundRefNum`. Exceeding it
  fails with `1235` or `1236`.

A practical choice for a "cancel / refund this order" feature: `query` first, then `reverse` if the status is
`PendingAuthorise`, otherwise `refund`; fall back from `reverse` to `refund` on `1220` or `1221`.

Refunds move money out of the merchant's account. Put them behind the app's admin authorization, log who
requested each one, and don't build an endpoint that refunds based on unauthenticated input.

## Request fields

| Operation | Required | Optional |
|-----------|----------|----------|
| `reverse` | `prestoMrn`, `reversalRefNum`, and `paymentRefNum` or `txnRefNum` | `remark`, `notifyUrl` |
| `refund` | `prestoMrn`, `paymentRefNum`, `refundRefNum`, `remark` | `amount` (minor units; omit for full), `notifyUrl` |

`reversalRefNum` and `refundRefNum` are the merchant's own references, at most 50 characters, unique per attempt.
Derive them from something stable (`order-123-refund-1`) and store them before calling, so a retry after an
unknown outcome can find the earlier attempt.

## Errors

Every SDK has one base error type and the same five kinds. Names differ per language; see the language file.

| Kind | When | Useful details |
|------|------|----------------|
| Config / validation | Invalid options or request input, bad keys | The field name |
| Transport | Network failure or timeout | Whether the request was never sent |
| API | Non-200 HTTP status, or `success: false` from the gateway | HTTP status, `errorCode`, `errorMessage` |
| Signature | A response or webhook failed verification, wrong webhook `mid`, stale webhook timestamp | Where it came from |
| Response | Malformed body, missing required field, echo mismatch | The raw body (redacted) |

Most SDKs also mark each error with whether the operation **may have taken effect**, and the key to reconcile
with; use that flag where it exists. Where it doesn't (the language file says so), apply the rules in the next
section to the error type.

Log `errorCode` and `errorMessage` from API errors; Presto support asks for them. Don't log raw bodies or
canonical strings in production unless redacted; most SDKs redact or omit them by default (see the language file).

Compare error codes against the SDK's error code constants. Unknown codes arrive as plain strings.

## When you don't know whether it worked

For `init`, `reverse` and `refund`, these failures leave the outcome unknown ("may have taken effect"):

- a transport failure after the request may have been sent (including a timeout);
- an HTTP 5xx;
- a 200 response that fails parsing, signature verification, field mapping or the echo check.

A `success: false` business error means nothing happened. The same failures on `query` also mean nothing
happened.

What to do:

- **`init`: resend with the same `txnRefNum` and the same fields.** Safe: if the first call reached Presto, you
  get the existing payment and its current status back instead of a second payment.
- **`reverse` and `refund`: `query` first.** Sending one twice could reverse or refund twice. Look at
  `reversalStatus` / `refundStatus` (and `refundDetails` for partial refunds, matched on your `refundRefNum`).
  Retry only if the first request didn't take effect. If you can't tell, record the attempt as "unknown" and
  surface it to a person, rather than retrying automatically.
- **`1203` on `init`**: a record with that `txnRefNum` exists, state unknown. `query` it; never treat `1203` as
  "paid".

## Retries and deadlines

The SDKs already retry safely, so don't wrap payment calls in a generic retry library or an HTTP client that
retries requests:

- `init`, `reverse` and `refund` are retried automatically only when the request was certainly never sent (DNS
  failure, connection refused, TLS failure before the body was written).
- `query` is read-only and is retried on transport errors and 5xx.
- Every attempt gets a fresh timestamp and signature.
- All attempts share one overall deadline (30 seconds by default in most SDKs). Set it below the web server's or
  job runner's own timeout, so the SDK's error reaches your code rather than the process being killed mid-call.

## Error codes

Load-bearing ones:

| Code | Meaning | What to do |
|------|---------|------------|
| `1005` | Request timestamp outside the gateway's 15-minute window | Fix the host clock (NTP). Not a signing problem |
| `1006`, `1007` | Gateway couldn't verify the request signature | The private key doesn't match the public key registered for this environment, or staging and production are mixed |
| `1102`, `1106` | Invalid `mid` / invalid merchant reference (`prestoMrn`) | Wrong value for this environment |
| `1201` | Invalid input | Check the request fields |
| `1203` | A payment with this `txnRefNum` exists, state unknown | `query` it |
| `1212` | Payment not found | Check the reference and environment |
| `1219` | Invalid status for reversal (for example `Expired`) | Nothing to reverse |
| `1220`, `1221` | Reversal not allowed: settled, or window passed | `refund` instead |
| `1224`, `1226` | Reversal / refund already in progress | `query` later; don't resend |
| `1227` | Invalid status for refund (for example unpaid) | `reverse` an unpaid payment instead |
| `1228` | Refund window has passed | Contact Presto |
| `1235`, `1236` | Refund amount exceeds the payment / refundable amount | Check what was already refunded |

Other codes, by group: `10xx` request and auth, `11xx` merchant, `12xx` payment, `14xx` user. Presto can add codes;
handle unknown ones as a generic failure and log them.
