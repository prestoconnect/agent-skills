# PHP: prestouniverse/presto-pay-sdk

Written against **prestouniverse/presto-pay-sdk 0.2.0**. Source and full docs:
https://github.com/prestoconnect/presto-pay-sdk-php

- PHP 8.2+, 64-bit. Needs `ext-curl`, `ext-json`, `ext-openssl`; a PSR-18 client is optional.
- Namespace `PrestoUniverse\PrestoPay`. Requests are immutable objects built with named arguments
  (`new InitRequest(prestoMrn: ..., txnRefNum: ...)`); results are `readonly` objects with public properties
  named like the wire fields (`$payment->paymentUrl`).
- Status and method values are `string`s. Constants are UPPER_SNAKE class constants: `PaymentStatus::AUTHORISED`,
  `PaymentMethod::PM_PG_CARD`, `ErrorCode::PAYMENT_NOT_FOUND`. `TxnType::WebPay` and `Environment::Staging` are
  enum cases.
- Payment calls go through `PrestoPay`; webhooks through a separate `Webhook\WebhookVerifier`.
- Don't use anything under `PrestoUniverse\PrestoPay\Internal`; it isn't public API.

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
composer require prestouniverse/presto-pay-sdk:^0.2.0
```

## Keys

The merchant generates its own key pair. Give the user these commands to run themselves:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out merchant-key.pem
openssl req -new -x509 -key merchant-key.pem -days 99999 -subj "/CN=Your Company" -outform DER -out merchant.der
```

- `merchant-key.pem` is the private key (PEM; an encrypted PEM works with its password): secret, out of source
  control, **outside the web root**, readable only by the PHP process.
- `merchant.der` is the public key in the DER format Presto requires: the user sends it to Presto, once for
  staging and once for production.

The SDK doesn't read PKCS#12. To use an existing `.p12`, convert once:

```bash
openssl pkcs12 -in merchant.p12 -nocerts -nodes -out merchant-key.pem
```

OpenSSL 3 may print `unsupported` and exit 1 after writing the key; if the file has a `BEGIN PRIVATE KEY` block,
it worked.

Presto's certificate (`presto.der`) is read as is with `PublicKey::fromFile()`.

## Client

`PrestoPay::fromEnv()` takes an array; it never reads `getenv()` or `$_ENV` itself:

```php
use PrestoUniverse\PrestoPay\PrestoPay;

$presto = PrestoPay::fromEnv([
    'PRESTOPAY_ENV' => $_ENV['PRESTOPAY_ENV'],
    'PRESTOPAY_MID' => $_ENV['PRESTOPAY_MID'],
    'PRESTOPAY_PRIVATE_KEY_FILE' => $_ENV['PRESTOPAY_PRIVATE_KEY_FILE'],
    'PRESTOPAY_PRIVATE_KEY_PASSWORD' => $_ENV['PRESTOPAY_PRIVATE_KEY_PASSWORD'] ?? '',
    'PRESTOPAY_PUBLIC_KEY_FILE' => $_ENV['PRESTOPAY_PUBLIC_KEY_FILE'],
]);
```

| Key | Value |
|-----|-------|
| `PRESTOPAY_ENV` | `staging` or `production`; `staging` if left out |
| `PRESTOPAY_BASE_URL` | A gateway base URL, used instead of `PRESTOPAY_ENV` |
| `PRESTOPAY_MID` | The merchant's `mid` |
| `PRESTOPAY_PRIVATE_KEY_FILE` or `PRESTOPAY_PRIVATE_KEY` | Path to the PEM private key, or its contents |
| `PRESTOPAY_PRIVATE_KEY_PASSWORD` | The key's password, if it's encrypted |
| `PRESTOPAY_PUBLIC_KEY_FILE` or `PRESTOPAY_PUBLIC_KEY` | Path to Presto's `.der` certificate, or its contents as PEM text (`openssl x509 -inform der -in presto.der -out presto.pem`) |

`prestoMrn` is not a client setting; it goes on every request. Add your own variable for it, such as
`PRESTOPAY_MRN`.

Explicit construction, plus the webhook verifier:

```php
use PrestoUniverse\PrestoPay\Environment;
use PrestoUniverse\PrestoPay\Key\PrivateKey;
use PrestoUniverse\PrestoPay\Key\PublicKey;
use PrestoUniverse\PrestoPay\PrestoPay;
use PrestoUniverse\PrestoPay\Webhook\WebhookVerifier;

$prestoKey = PublicKey::fromFile($prestoCertPath);

$presto = new PrestoPay(
    environment: Environment::Staging, // or Environment::Production
    merchantId: $mid,
    privateKey: PrivateKey::fromFile($privateKeyPath), // PrivateKey::fromPem($pem) for contents
    prestoPublicKeys: [$prestoKey],
);

$verifier = new WebhookVerifier([$mid], [$prestoKey]);
```

Build both once per process (a container singleton in a framework). Bad keys fail at construction.

## Checkout

### Start a payment

```php
use PrestoUniverse\PrestoPay\PaymentMethod;
use PrestoUniverse\PrestoPay\Request\InitRequest;
use PrestoUniverse\PrestoPay\TxnType;

$payment = $presto->payments()->init(new InitRequest(
    prestoMrn: $prestoMrn,
    txnType: TxnType::WebPay,
    txnRefNum: $order->txnRefNum,
    displayDesc: "Order {$order->id}",
    amount: $order->totalMinorUnits, // int, minor units: 10_000 is MYR 100.00
    currencyCode: 'MYR',
    notifyUrl: "{$baseUrl}/presto/notify",
    redirectUrl: "{$baseUrl}/presto/return/{$order->txnRefNum}",
    // allowedPaymentMethods: [PaymentMethod::PM_PG_CARD], // only for your own method selection page
));

$order->paymentRefNum = $payment->paymentRefNum;
$order->paymentStatus = $payment->paymentStatus;
$order->save();

if ($payment->paymentUrl === null) {
    throw new \RuntimeException("Presto returned no paymentUrl for {$order->txnRefNum}");
}
return redirect()->away($payment->paymentUrl); // Laravel; plain PHP: header('Location: ...', true, 303)
```

A missing or invalid field throws `ConfigException` before anything is sent. `amount` must be an `int`; never
pass a float, and convert decimal prices without float arithmetic (for example with `bcmul` or a money library).
Optional: `receiptName`, `receiptEmail`.

If the outcome is unknown, resend `init` with the same request:

```php
use PrestoUniverse\PrestoPay\Exception\PrestoPayException;

try {
    $payment = $presto->payments()->init($request);
} catch (PrestoPayException $error) {
    if (!$error->mayHaveTakenEffect()) {
        throw $error;
    }
    $payment = $presto->payments()->init($request); // same txnRefNum: returns the existing payment
}
```

### Query the status

```php
use PrestoUniverse\PrestoPay\PaymentStatus;
use PrestoUniverse\PrestoPay\Request\QueryRequest;

$result = $presto->payments()->query(new QueryRequest(prestoMrn: $prestoMrn, txnRefNum: $txnRefNum));
// or paymentRefNum: $paymentRefNum

if ($result->paymentStatus === PaymentStatus::AUTHORISED) {
    // paid
} elseif ($result->paymentStatus === PaymentStatus::PENDING_AUTHORISE) {
    // processing: check again shortly
} else {
    // not paid, or a status this SDK version doesn't know
}
```

Other constants: `FAILED`, `CANCELLED`, `EXPIRED`, `PENDING_REVERSE`, `REVERSED`, `PENDING_REFUND`,
`PARTIAL_REFUNDED`, `REFUNDED`. A PHP `match` on the status needs a `default` arm, or an unknown status throws
`UnhandledMatchError`.

`method` on each `paymentDetails` entry is a `string`; store and show an unknown code as it is. Any code can be
passed in `allowedPaymentMethods` as a string.

### One update function for return page and webhook

Both callers pass the query result to one order service. In a database transaction, lock the order or use a
conditional update, reject stale status changes, save the new status, and insert a fulfillment job with a unique
order key when the status first becomes `PaymentStatus::AUTHORISED`. Commit before processing the job. Make
fulfillment idempotent and retryable. Saving `paymentStatus` and then calling `fulfil` can leave a paid order
unfulfilled if fulfillment fails.

## Webhooks

`$verifier->verify($rawBody)` takes the raw body `string` and returns a `WebhookEvent` with `eventCode`,
`success`, `mid`, `prestoMrn`, `paymentRefNum`, `txnRefNum`, `eventRefNum`, `amount`, `currencyCode` and
`paymentDetails`. In a PSR-7 handler, `$verifier->verifyServerRequest($request)` while the body stream is unread.

Raw body: `file_get_contents('php://input')` in plain PHP, `$request->getContent()` in Laravel or Symfony. Never
`$request->all()`, `$request->json()` or `json_decode` then `json_encode`.

Replies: `NotifyAck::Ok->body()` (`{"resend":false}`) and `NotifyAck::Resend->body()` (`{"resend":true}`), sent
with `Content-Type: application/json`. `NotifyAck::forThrowable($error)` picks `Ok` for a webhook that failed
verification and `Resend` for anything else. Catch `SignatureException` first and answer 401.

Laravel:

```php
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use PrestoUniverse\PrestoPay\Exception\SignatureException;
use PrestoUniverse\PrestoPay\PrestoPay;
use PrestoUniverse\PrestoPay\Request\QueryRequest;
use PrestoUniverse\PrestoPay\Webhook\NotifyAck;
use PrestoUniverse\PrestoPay\Webhook\WebhookVerifier;

class PrestoPayWebhookController
{
    public function __construct(
        private readonly WebhookVerifier $verifier,
        private readonly PrestoPay $presto,
        private readonly OrderPayments $orderPayments,
    ) {}

    public function __invoke(Request $request)
    {
        try {
            $event = $this->verifier->verify($request->getContent());
        } catch (SignatureException $error) {
            return response('', 401);
        } catch (\Throwable $error) {
            return response(NotifyAck::forThrowable($error)->body(), 200)->header('Content-Type', 'application/json');
        }

        try {
            $payment = $this->presto->payments()->query(new QueryRequest(
                prestoMrn: $event->prestoMrn,
                paymentRefNum: $event->paymentRefNum,
            ));
            $this->orderPayments->applyStatus($event->txnRefNum, $payment->paymentStatus);
            $ack = NotifyAck::Ok;
        } catch (\Throwable $error) {
            $ack = NotifyAck::Resend;
        }

        return response($ack->body(), 200)->header('Content-Type', 'application/json');
    }
}
```

`applyStatus` is the same method the return page calls. Inside `DB::transaction`, it runs one conditional update
(`Order::where('txn_ref_num', $ref)->where('status', PaymentStatus::PENDING_AUTHORISE)->update([...])`) and
dispatches the fulfillment job only when that changed a row and the new status is `Authorised`. A redelivery
changes nothing. Exclude the route from CSRF: in Laravel 11+,
`$middleware->validateCsrfTokens(except: ['presto/notify'])` in `bootstrap/app.php`; in older versions, the
`$except` array of `VerifyCsrfToken`. Or define it in `routes/api.php`.

Symfony: same shape with `$request->getContent()`, `new Response($ack->body(), 200, ['Content-Type' =>
'application/json'])`, and Doctrine DBAL `$db->transactional(...)` around the same conditional
`UPDATE orders ... WHERE status = 'PendingAuthorise'`. Complete Laravel and Symfony
handlers: https://github.com/prestoconnect/presto-pay-sdk-php/blob/main/docs/webhooks.md

Several `mid`s: `new WebhookVerifier(['MID_A', 'MID_B'], [$prestoKey])`; use `$event->mid` to pick the matching
`PrestoPay` client before you query. A verifier holds no private key, so a webhook-only process or queue worker
doesn't need `PrestoPay`'s key.

Freshness window: third constructor argument, `maxTimestampAge` in seconds (default 900). Widen only with
the guarded order update in place.

## Refunds and errors

```php
use PrestoUniverse\PrestoPay\Request\RefundRequest;
use PrestoUniverse\PrestoPay\Request\ReverseRequest;

$reversal = $presto->payments()->reverse(new ReverseRequest(
    prestoMrn: $prestoMrn,
    reversalRefNum: "{$order->txnRefNum}-reversal",
    paymentRefNum: $order->paymentRefNum, // or txnRefNum:
    remark: 'Customer cancelled',         // optional
));

$refund = $presto->payments()->refund(new RefundRequest(
    prestoMrn: $prestoMrn,
    paymentRefNum: $order->paymentRefNum,
    refundRefNum: "{$order->txnRefNum}-refund-{$n}",
    remark: 'Customer request', // required
    amount: 2_500,              // optional: leave it out for a full refund
));
```

`query` then shows `reversalStatus` (`Reversing`, `Failed`, `Success`), `refundStatus` (`Refunding`, `Failed`,
`Success`) and `refundDetails` (each with `refundRefNum`, `refundStatus`). PHP has no constants for these; compare
with the strings.

Every exception extends `Exception\PrestoPayException` (a `\RuntimeException`) with `operation()`,
`mayHaveTakenEffect()` and `reconcileBy()`:

| Exception | Useful methods |
|-----------|----------------|
| `ConfigException` | |
| `TransportException` | `requestNotSent()` |
| `ApiException` | `errorCode()`, `errorMessage()`, `httpStatus()` |
| `SignatureException` | |
| `ResponseException` | |

Compare `errorCode()` with `ErrorCode` constants (`EXPIRED_TIMESTAMP`, `INVALID_SIGNATURE`,
`SIGNATURE_VERIFICATION_FAILED`, `INVALID_INPUT`, `DUPLICATE_TXN_REF_NUM`, `PAYMENT_NOT_FOUND`,
`INVALID_REVERSAL_STATUS`, `INVALID_REFUND_STATUS`) or with the code string for others (`'1220'`). Exception
messages never include gateway bodies or keys.

Unknown outcome on `reverse` / `refund`: query before anything else. `reconcileBy()` returns the
`paymentRefNum` the request used (`null` if you reversed by `txnRefNum`), so fall back to your stored references:

```php
try {
    $presto->payments()->refund($refundRequest);
} catch (PrestoPayException $error) {
    if (!$error->mayHaveTakenEffect()) {
        throw $error;
    }
    $current = $presto->payments()->query(new QueryRequest(
        prestoMrn: $prestoMrn,
        paymentRefNum: $error->reconcileBy() ?? $order->paymentRefNum,
    ));
    // Look for $refundRequest->refundRefNum in $current->refundDetails before deciding anything.
}
```

Retries are built in: `query` on network errors and 5xx; `init` / `reverse` / `refund` only when
`requestNotSent()`, which only the default cURL transport can detect. Defaults: `retryReads: 2`,
`initialBackoff: 0.2`, `maxBackoff: 2.0`, `deadline: 30.0` seconds, all constructor arguments.

## Production

- `Environment::Production` (or `PRESTOPAY_ENV=production`) with production credentials. `fromEnv` defaults to
  staging when `PRESTOPAY_ENV` is missing.
- `deadline` below PHP-FPM's `request_terminate_timeout` and `max_execution_time`.
- Key rotation: `prestoPublicKeys: [$old, $new]` (and the same list on `WebhookVerifier`) during Presto's
  announced overlap.
- Custom HTTP: implement `HttpTransport`, or wrap a PSR-18 client with `Http\Psr18Transport`. With PSR-18, every
  transport failure counts as possibly sent, so `init` / `reverse` / `refund` are never auto-retried; prefer the
  default cURL transport for payments. A transport must return non-2xx responses rather than throw and must not
  follow redirects or resend.
- Troubleshooting: `1005` (`ErrorCode::EXPIRED_TIMESTAMP`): NTP. `1006` / `1007`: key mismatch;
  `Canonicalizer::fromJson($json)` rebuilds the signed string from a raw body. `1102` / `1106`: wrong `mid` /
  `prestoMrn` for this environment.
- An endpoint the SDK doesn't model: `$presto->raw()->post('/path', $body)`.

## Framework notes

Runnable samples against Presto staging:
[plain PHP](https://github.com/prestoconnect/presto-pay-sdk-php/tree/main/sample/my-store),
[Laravel](https://github.com/prestoconnect/presto-pay-sdk-php/tree/main/sample/laravel-store),
[Symfony](https://github.com/prestoconnect/presto-pay-sdk-php/tree/main/sample/symfony-store).

**Laravel.** A `PrestoPayServiceProvider` registering `PrestoPay` and `WebhookVerifier` as singletons, built from
`config/prestopay.php`, which reads `env('PRESTOPAY_ENV')`, `env('PRESTOPAY_MID')`, `env('PRESTOPAY_MRN')`,
`env('PRESTOPAY_PRIVATE_KEY_FILE')`, `env('PRESTOPAY_PRIVATE_KEY_PASSWORD')` and
`env('PRESTOPAY_PUBLIC_KEY_FILE')`. Only call `env()` inside config files, so `config:cache` works. Put slow work
in queued jobs. Under Octane the singletons persist across requests, which is fine since they're immutable.

**Symfony.** Register `PrestoPay` (with `PrestoPay::fromEnv` as a factory, or explicit arguments) and
`WebhookVerifier` as services in `config/services.yaml`, with values from `%env(...)%`. Use secrets
(`bin/console secrets:set`) for the key password. Disable CSRF on the webhook route if a firewall adds it.

**WordPress / WooCommerce.** Register a REST route (`register_rest_route`) for the webhook and read
`$request->get_body()`. Store the key path in `wp-config.php` constants outside the web root.

**Testing.** `PrestoPay` and the result classes are final. Wrap the calls you use in a small interface of your
own and fake it, and keep business logic such as `applyPaymentStatus` on plain status strings. Cover an unknown
status such as `'SomethingNew'`.
