# Go: presto-pay-sdk-go

Written against **v0.3.2**. Source and full docs: https://github.com/prestoconnect/presto-pay-sdk-go

- Package `github.com/prestoconnect/presto-pay-sdk-go/prestopay`.
- Fields use Go casing of the wire names: `TxnRefNum`, `PrestoMRN`, `NotifyURL`, `PaymentURL`.
- Every call takes a `context.Context` first; pass the request's `r.Context()`.
- Status and method fields are plain `string`. Constants are prefixed by type: `prestopay.TxnTypeWebPay`,
  `prestopay.PaymentStatusAuthorised`, `prestopay.PaymentMethodPmPgCard`, `prestopay.ErrorCodePaymentNotFound`.
- Payment calls go through a `*prestopay.Client`; webhooks go through a separate `*prestopay.WebhookVerifier`.

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
go get github.com/prestoconnect/presto-pay-sdk-go@v0.3.2
```

## Keys

The merchant generates its own key pair. Give the user these commands to run themselves:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out merchant-key.pem
openssl req -new -x509 -key merchant-key.pem -days 99999 -subj "/CN=Your Company" -outform DER -out merchant.der
```

- `merchant-key.pem` is the private key in the PKCS#8 PEM format the SDK reads (`-----BEGIN PRIVATE KEY-----`):
  secret, out of source control.
- `merchant.der` is the public key in the DER format Presto requires: the user sends it to Presto, once for
  staging and once for production.

The SDK doesn't read PKCS#12. To use an existing `.p12`, convert it once:

```bash
openssl pkcs12 -in merchant.p12 -nocerts -nodes -out merchant-key.pem
```

Some keystores use an old algorithm that OpenSSL 3 refuses: it prints `unsupported` and exits 1, but only after
writing the key. If `merchant-key.pem` contains a `BEGIN PRIVATE KEY` block, it worked; `-legacy` gives a clean
exit. Don't pipe this command into another one.

Presto's certificate (`presto.der`) is read as is, DER or PEM.

## Client

Prefer configuration from the environment:

```go
cfg, err := prestopay.ConfigFromEnv(os.Getenv)
if err != nil {
    log.Fatal(err)
}
client, err := prestopay.New(cfg)
if err != nil {
    log.Fatal(err)
}

verifier, err := prestopay.NewWebhookVerifier(prestopay.WebhookConfig{
    MerchantIDs:      []string{cfg.MerchantID},
    PrestoPublicKeys: cfg.PrestoPublicKeys,
})
if err != nil {
    log.Fatal(err)
}
```

| Variable | Value |
|----------|-------|
| `PRESTOPAY_ENV` or `PRESTOPAY_BASE_URL` | `staging` or `production`, or a gateway base URL (wins if both are set) |
| `PRESTOPAY_MID` | The merchant's `mid` |
| `PRESTOPAY_PRIVATE_KEY` or `PRESTOPAY_PRIVATE_KEY_FILE` | PKCS#8 PEM private key, or a path to it |
| `PRESTOPAY_PUBLIC_KEY` or `PRESTOPAY_PUBLIC_KEY_FILE` | Presto's certificate, or a path to its `.der` file |

`ConfigFromEnv` takes any lookup function, so a secret-store reader works too. Set other `Config` fields
(`RetryReads`, `Deadline`, `HTTPClient`) on the returned value before `New`.

`prestoMrn` is not a client setting; it goes on every request. Add your own variable for it, such as
`PRESTOPAY_MRN`.

Explicit construction:

```go
client, err := prestopay.New(prestopay.Config{
    Environment:      prestopay.Staging, // or prestopay.Production
    MerchantID:       mid,
    PrivateKeyPEM:    privateKeyPEM,     // []byte from your secret store
    PrestoPublicKeys: [][]byte{prestoCert},
})
```

Build the client and verifier once in `main` and pass them to handlers (struct fields or closures). Bad keys fail
in `New`, not on the first payment.

## Checkout

### Start a payment

```go
payment, err := client.Payments.Init(r.Context(), prestopay.InitRequest{
    PrestoMRN:    prestoMRN,
    TxnType:      prestopay.TxnTypeWebPay,
    TxnRefNum:    order.TxnRefNum,
    DisplayDesc:  "Order " + order.ID,
    Amount:       order.TotalMinorUnits, // integer minor units: 10_000 is MYR 100.00
    CurrencyCode: "MYR",
    NotifyURL:    baseURL + "/presto/notify",
    RedirectURL:  baseURL + "/presto/return/" + order.TxnRefNum,
    // AllowedPaymentMethods: []string{prestopay.PaymentMethodPmPgCard}, // only for your own method selection page
})
if err != nil {
    return err
}

order.PaymentRefNum = payment.PaymentRefNum
order.PaymentStatus = payment.PaymentStatus
if err := orders.Save(r.Context(), order); err != nil {
    return err
}

if payment.PaymentURL == "" {
    return fmt.Errorf("presto returned no payment URL for %s", order.TxnRefNum)
}
http.Redirect(w, r, payment.PaymentURL, http.StatusSeeOther)
```

A missing or invalid field returns a `*prestopay.ConfigError` (with `Field`) before anything is sent. Optional:
`ReceiptName`, `ReceiptEmail`.

If the outcome is unknown, resend `Init` with the same request:

```go
payment, err := client.Payments.Init(ctx, req)
var pe prestopay.Error
if errors.As(err, &pe) && pe.MayHaveTakenEffect() {
    payment, err = client.Payments.Init(ctx, req) // same TxnRefNum: returns the existing payment
}
```

### Query the status

```go
result, err := client.Payments.Query(r.Context(), prestopay.QueryRequest{
    PrestoMRN: prestoMRN,
    TxnRefNum: txnRefNum, // or PaymentRefNum
})
if err != nil {
    return err
}

switch result.PaymentStatus {
case prestopay.PaymentStatusAuthorised:
    // paid
case prestopay.PaymentStatusPendingAuthorise:
    // processing: check again shortly
default:
    // not paid, or a status this SDK version doesn't know
}
```

Other constants: `PaymentStatusFailed`, `PaymentStatusCancelled`, `PaymentStatusExpired`,
`PaymentStatusPendingReverse`, `PaymentStatusReversed`, `PaymentStatusPendingRefund`,
`PaymentStatusPartialRefunded`, `PaymentStatusRefunded`.

`Method` on each `PaymentDetails` entry is a `string`; give any `switch` on it a `default` that stores and shows
an unknown code as it is. Any code can be passed in `AllowedPaymentMethods` as a string.

### One update function for return page and webhook

Both callers pass the `QueryResponse` to one order service. In a database transaction, lock the order or use a
conditional update, reject stale status changes, save the new status, and insert a fulfillment job with a unique
order key when the status first becomes `prestopay.PaymentStatusAuthorised`. Commit before processing the job.
Make fulfillment idempotent and retryable. Saving `PaymentStatus` and then calling `fulfil` can leave a paid
order unfulfilled if that call fails.

## Webhooks

`verifier.VerifyRequest(r)` reads the raw body itself, with a size limit, and returns a `prestopay.NotifyEvent`
with `EventCode`, `Success`, `MID`, `PrestoMRN`, `PaymentRefNum`, `TxnRefNum`, `EventRefNum`, `Amount`,
`CurrencyCode` and `PaymentDetails`. If the body was already read (a queue consumer, a framework), pass the exact
bytes to `verifier.Verify(body)`; never re-encode decoded JSON.

Replies: `prestopay.WriteAck(w, prestopay.AckOK)` writes HTTP 200 `{"resend":false}`;
`prestopay.AckResend` writes `{"resend":true}`. `prestopay.AckForError(err)` picks `AckOK` for a webhook that
failed verification and `AckResend` for anything else. Check for `*prestopay.SignatureError` first and answer 401.

```go
func (h *Handlers) PrestoNotify(w http.ResponseWriter, r *http.Request) {
    event, err := h.verifier.VerifyRequest(r)
    if err != nil {
        var sigErr *prestopay.SignatureError
        if errors.As(err, &sigErr) {
            w.WriteHeader(http.StatusUnauthorized)
            return
        }
        prestopay.WriteAck(w, prestopay.AckForError(err)) // malformed body: don't ask for a resend
        return
    }

    payment, err := h.client.Payments.Query(r.Context(), prestopay.QueryRequest{
        PrestoMRN:     event.PrestoMRN,
        PaymentRefNum: event.PaymentRefNum,
    })
    if err != nil {
        prestopay.WriteAck(w, prestopay.AckResend)
        return
    }

    // In one transaction: insert event.EventRefNum into a table with a unique constraint;
    // if it already exists, it's a redelivery, so skip; otherwise apply the result to the order.
    if err := h.orders.HandleWebhookOnce(r.Context(), event.EventRefNum, event.TxnRefNum, payment); err != nil {
        prestopay.WriteAck(w, prestopay.AckResend)
        return
    }
    prestopay.WriteAck(w, prestopay.AckOK)
}
```

Several `mid`s: `WebhookConfig.MerchantIDs` is a set; use `event.MID` to pick the matching client before you
`Query`. A verifier holds no private key, so a webhook-only service (see the Lambda example) needs only Presto's
certificate and the `mid`s.

Freshness window: `WebhookConfig.MaxTimestampAge` (zero means 15 minutes). Widen only with `EventRefNum` dedup in
place.

## Refunds and errors

```go
reversal, err := client.Payments.Reverse(ctx, prestopay.ReverseRequest{
    PrestoMRN:      prestoMRN,
    PaymentRefNum:  paymentRefNum, // or TxnRefNum
    ReversalRefNum: order.TxnRefNum + "-reversal",
    Remark:         "Customer cancelled", // optional
})

refund, err := client.Payments.Refund(ctx, prestopay.RefundRequest{
    PrestoMRN:     prestoMRN,
    PaymentRefNum: paymentRefNum,
    RefundRefNum:  fmt.Sprintf("%s-refund-%d", order.TxnRefNum, n),
    Remark:        "Customer request", // required
    Amount:        2_500,              // optional: leave it out for a full refund
})
```

`Query` then shows `ReversalStatus` (`ReversalStatusReversing`, `ReversalStatusFailed`, `ReversalStatusSuccess`),
`RefundStatus` (`RefundStatusRefunding`, `RefundStatusFailed`, `RefundStatusSuccess`) and `RefundDetails`
(each with `RefundRefNum`, `RefundStatus`).

Every error satisfies `prestopay.Error` (`Operation()`, `MayHaveTakenEffect()`, `ReconcileBy()`). Inspect with
`errors.As`:

| Type | Useful fields |
|------|---------------|
| `*prestopay.ConfigError` | `Field` |
| `*prestopay.TransportError` | `RequestNotSent` |
| `*prestopay.APIError` | `Kind` (`KindHTTP` / `KindBusiness`), `HTTPStatus`, `ErrorCode`, `ErrorMessage`, `RawBody`; `Canonical` on `1006`/`1007`; `ClockOffset` on `1005` |
| `*prestopay.SignatureError` | `Source`, `Canonical` |
| `*prestopay.ResponseError` | `Source`, `RawBody` |

```go
var apiErr *prestopay.APIError
if errors.As(err, &apiErr) && apiErr.ErrorCode == prestopay.ErrorCodePaymentNotFound {
    // ...
}
```

Unknown outcome on `Reverse` / `Refund`: query before anything else. `ReconcileBy()` returns a
`prestopay.ReconcileKey` with `TxnRefNum` or `PaymentRefNum`; add your `PrestoMRN`:

```go
_, err := client.Payments.Refund(ctx, req)
var pe prestopay.Error
if errors.As(err, &pe) && pe.MayHaveTakenEffect() {
    if key, ok := pe.ReconcileBy(); ok {
        current, qerr := client.Payments.Query(ctx, prestopay.QueryRequest{
            PrestoMRN:     req.PrestoMRN,
            TxnRefNum:     key.TxnRefNum,
            PaymentRefNum: key.PaymentRefNum,
        })
        // Look for req.RefundRefNum in current.RefundDetails before deciding anything.
        _, _ = current, qerr
    }
}
```

Retries: **off by default** in Go. Turn on `Query` retries with
`Config.RetryReads = prestopay.RetryReads{MaxRetries: 2, InitialBackoff: 200 * time.Millisecond, MaxBackoff: 2 * time.Second}`.
`Init`, `Reverse` and `Refund` are retried only when `RequestNotSent` is true. `Config.Deadline` (30 s default)
covers the whole call; the `ctx` can shorten it.

## Production

- `prestopay.Production` (or `PRESTOPAY_ENV=production`) with production credentials.
- `Config.Deadline`: below the server's own timeout.
- `Config.RetryReads` if you want `Query` retried.
- `Config.Strict`: on in staging to catch contract drift, off in production.
- `Error()` strings leave out `RawBody` and `Canonical` (card and customer details) unless
  `Config.ShowErrorBodies` is true. Keep it false in production.
- Key rotation: put both certificates in `PrestoPublicKeys` during Presto's announced overlap.
- `Config.HTTPClient` for proxies or tracing. Never set an `Idempotency-Key` or `X-Idempotency-Key` header in a
  custom transport: `net/http` then treats the POST as replayable and may send `Init`, `Reverse` or `Refund`
  twice.
- Troubleshooting names: `ErrorCodeClockSkew` (`1005`, see `APIError.ClockOffset`),
  `ErrorCodeInvalidSignature` / `ErrorCodeSignatureVerificationFailed` (`1006`/`1007`, see
  `APIError.Canonical`; `prestopay.Canonicalize(fields)` rebuilds it), `ErrorCodeInvalidMID`,
  `ErrorCodeInvalidMerchantReference`, `ErrorCodeDuplicateTxnRefNum` (`1203`).
- An endpoint the SDK doesn't model: `client.Raw.Post(ctx, path, body)`.

## Framework notes

Runnable examples: [net-http](https://github.com/prestoconnect/presto-pay-sdk-go/tree/main/examples/net-http)
(standard library, Go 1.22 method patterns such as `mux.HandleFunc("POST /presto/notify", ...)`),
[chi](https://github.com/prestoconnect/presto-pay-sdk-go/tree/main/examples/chi), and
[lambda](https://github.com/prestoconnect/presto-pay-sdk-go/tree/main/examples/lambda) (webhook-only, no private
key).

**net/http, chi, gorilla/mux, echo, gin.** `VerifyRequest(r)` works with any handler that has the
`*http.Request`. In gin use `c.Request` and `c.Writer`; in echo `c.Request()` and `c.Response()`. Make sure no
body-reading middleware runs on the webhook route before it, or read the body once and call `Verify(body)`.

**AWS Lambda.** Verify the event's raw body string with `verifier.Verify([]byte(req.Body))`; if API Gateway marks
it base64-encoded (`req.IsBase64Encoded`), decode first.

**Testing.** Define a small interface in your package for the calls you use (`Init`, `Query`, ...) and inject a
fake; a fake gateway server would need Presto's private key to sign responses. Include an unknown status string
such as `"SomethingNew"` in the cases.
