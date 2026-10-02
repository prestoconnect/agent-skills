# Checkout

How a Presto payment flows, what to send to `init`, and how to read the result. Field names here are the wire
names; each SDK uses its language's casing (`txnRefNum`, `txn_ref_num`, `TxnRefNum`). Code is in the language
file's "Checkout" section.

## Contents

- [The flow](#the-flow)
- [Identifiers](#identifiers)
- [Starting a payment](#starting-a-payment)
- [The return page](#the-return-page)
- [Payment statuses](#payment-statuses)
- [Payment methods](#payment-methods)
- [Mistakes to avoid](#mistakes-to-avoid)

## The flow

```
 Merchant server                  Presto                     Shopper's browser
     |---- 1. init ------------------>|                              |
     |<--- paymentUrl ----------------|                              |
     |---- 2. redirect to paymentUrl ------------------------------->|
     |                                |<---- 3. shopper pays --------|
     |                                |---- 4a. redirect to redirectUrl ------->|
     |<--- 4b. webhook to notifyUrl   |                              |
     |---- 5. query ----------------->|                              |
```

1. The server calls `init` with the order's reference and amount. Presto returns a `paymentUrl`.
2. The server redirects the shopper to `paymentUrl`.
3. The shopper chooses a payment method and pays on Presto's hosted page.
4. Presto sends the browser back to `redirectUrl` **and** POSTs a signed webhook to `notifyUrl`. The two are
   independent and arrive in either order; either may never arrive (closed tab, network failure).
5. On both, the server calls `query` for the status and updates the order through one shared, idempotent
   function. Whichever arrives first records the status; the other finds it already done.

## Identifiers

| Name | Created by | Purpose |
|------|------------|---------|
| `mid` | Presto | The merchant account. Set once on the client, not per request |
| `prestoMrn` | Presto | The shop or outlet. Sent on every request; one `mid` can have several |
| `txnRefNum` | Merchant | The merchant's reference for one payment, such as the order ID. Unique per payment, at most 50 characters |
| `paymentRefNum` | Presto | Presto's reference for the payment, returned by `init`. Store it with the order |
| `eventRefNum` | Presto | One webhook event. Stays the same on redelivery |
| `reversalRefNum`, `refundRefNum` | Merchant | The merchant's reference for a reversal or refund |

If an order can be paid more than once (the shopper abandons, then retries after the payment expired), use a new
`txnRefNum` per attempt, for example `order-123-2`, and keep the mapping to the order.

## Starting a payment

For a web checkout, call `init` with `txnType` `WebPay`:

| Field | Required | Notes |
|-------|----------|-------|
| `prestoMrn` | Yes | From configuration |
| `txnType` | Yes | `WebPay` for a browser checkout. `QrPay` and `MiniAppPay` exist for other channels; ask the user and Presto before using them |
| `txnRefNum` | Yes | Unique per payment, at most 50 characters |
| `displayDesc` | Yes | Shown to the shopper, for example `Order 123` |
| `amount` | Yes for a checkout | Integer, minor units: `10000` is MYR 100.00 |
| `currencyCode` | When `amount` is set | `MYR` |
| `redirectUrl` | Yes for `WebPay` | Where Presto sends the browser back. Put the order reference in it so the return page knows which order to query |
| `notifyUrl` | Recommended | The webhook endpoint. Must be publicly reachable; locally, use a tunnel such as ngrok |
| `allowedPaymentMethods` | No | Only when the merchant builds its own payment method selection page. Leave it out to let the shopper choose on Presto's page |
| `receiptName`, `receiptEmail` | No | Shopper details for the receipt |

After `init` succeeds:

- Save `paymentRefNum` and the initial status with the order **before** redirecting.
- Redirect to `paymentUrl`. If it is missing, treat it as a failure; don't redirect to an empty URL.
- A payment that isn't paid within 15 minutes of `init` becomes `Expired`.

If `init` fails with an error that says the outcome is unknown (a timeout after sending, a 5xx, an unverifiable
response), call `init` again with the **same** `txnRefNum` and the same fields. That is safe: if the first call
reached Presto, you get the existing payment back instead of a second one. See `refunds-and-errors.md`.

## The return page

The redirect proves only that the shopper came back. Never mark an order paid because the browser reached
`redirectUrl`, and never trust status-like query parameters on it, since anyone can type them.

1. Read the order reference from the URL path, then `query` by `txnRefNum` (or `paymentRefNum`).
2. Update the order through the same function the webhook uses.
3. Show the shopper one of three outcomes:
   - `Authorised`: paid, show the confirmation.
   - `PendingAuthorise`: still processing. Show a "processing" page that checks again after a few seconds
     (poll your own order record or `query` again), and stops after a sensible limit.
   - anything else: not paid. Offer to try again with a new payment.

## Payment statuses

The `paymentStatus` from `query` is a plain string. Compare it with the SDK's constants.

| Status | Meaning | What to do |
|--------|---------|------------|
| `PendingAuthorise` | Created; the shopper hasn't finished paying | Wait. Becomes `Expired` if not paid within 15 minutes of `init` |
| `Authorised` | Paid | Fulfil the order |
| `Failed` | The payment attempt failed | Don't fulfil |
| `Cancelled` | Cancelled before it was paid, for example by `reverse` | Don't fulfil |
| `Expired` | Not paid in time | Don't fulfil; start a new payment if the shopper returns |
| `PendingReverse` | A reversal is in progress | Query again later |
| `Reversed` | The payment was reversed | Treat the order as cancelled |
| `PendingRefund` | A refund is in progress | Query again later |
| `PartialRefunded` | Part of the amount was refunded | Update the order's refunded amount |
| `Refunded` | The full amount was refunded | Treat the order as refunded |

The gateway can add statuses. Store an unknown value as it is, treat it as not paid, and log it; don't throw.

Updates can land out of order: a slow return page may write a `query` result taken before the webhook's.
Don't let a stale result move an order backwards, for example `Authorised` overwriting a stored `Refunded`.
Compare with the stored status before writing, and fulfil only on the transition into `Authorised`.

## Payment methods

By default the shopper chooses a method on Presto's page, and the merchant passes no `allowedPaymentMethods`.
Pass it only when the merchant shows its own method selection page and sends the shopper's choice.

- Which methods work depends on the merchant's account: Presto enables them during onboarding. A code being
  listed doesn't make it available; tell the user to confirm with Presto.
- Codes are plain strings and the SDK constants are a convenience. A code the SDK doesn't list can be passed as a
  string and works once Presto enables it.
- `method` on each payment detail in a `query` result or webhook is also a plain string; handle unknown codes by
  storing and showing them as they are.
- Methods that need the shopper to log in to a Presto account: `Wallet`, `CashBack`, `Card` (a card saved to the
  Presto account), and the loyalty programmes `Subwallet_NearU`, `Subwallet_CARROTS`, `Subwallet_BUDDY`,
  `BigLife`, `BonusLink`, `GOrewards`, `RISE`, `PlusMiles`, `VSing`, `KLEAN`. Allowing only these locks out
  shoppers without a Presto account.
- `PmPgCard` is a card entered on Presto's page, no Presto account needed.
- Legacy, don't use in new code: `TouchNGo` (use `TouchNGoEWallet`), `BigLife`.

All codes: `Wallet`, `CashBack`, `Card`, `BigLife`, `BonusLink`, `RISE`, `PlusMiles`, `VSing`, `KLEAN`,
`GOrewards`, `Subwallet_NearU`, `Subwallet_CARROTS`, `Subwallet_BUDDY`, `TuneTalk`, `PmPgCard`, `Maybank`,
`Ambank`, `Rhb`, `HongLeong`, `Cimb`, `PublicBank`, `AffinBank`, `Bsn`, `AllianceBank`, `AgroBank`,
`BankIslam`, `BankOfChina`, `BankRakyat`, `BankMuamalat`, `BoostBank`, `HsbcBank`, `KuwaitFinanceHouse`,
`OcbcBank`, `AlRajhiBank`, `StandardChartered`, `UobBank`, `MbsbBank`, `HongLeongPex`, `UnionPay`,
`UnionPayQR`, `Boost`, `GrabPay`, `GrabPayLater`, `WeChatPayChina`, `TouchNGo`, `TouchNGoEWallet`,
`AliPayChina`, `LatitudePay`, `ApplePay`, `GooglePay`, `DuitNowQR`.

## Mistakes to avoid

- Marking the order paid on the redirect, or on the webhook's `success` flag, instead of on `query`.
- Floats or decimal strings for `amount`, or major units (`100` meaning MYR 100.00).
- Reusing a `txnRefNum` for a new payment attempt after the first one failed or expired.
- Not saving `paymentRefNum` before redirecting, so the webhook can't be matched back to the order.
- A `notifyUrl` of `localhost`: Presto can't reach it.
- Creating a new client per request: it reloads keys every time.
