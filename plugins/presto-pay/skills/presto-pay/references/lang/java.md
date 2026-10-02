# Java: presto-pay-sdk

Written against **com.prestouniverse:presto-pay-sdk 0.2.1**. Source and full docs:
https://github.com/prestoconnect/presto-pay-sdk-java

- Java 8+, zero runtime dependencies. Works from Kotlin and other JVM languages.
- `PrestoPayClient` is thread-safe: build one and share it (a Spring `@Bean`).
- Requests are immutable builders: `PaymentInitRequest.builder()...build()`. `prestoMrn` is set with
  `.merchantRefNum(...)`.
- Responses use accessor methods: `payment.paymentUrl()`, `result.paymentStatus()`.
- Status, method and error codes are `String`s. Constants are `public static final String` fields named like the
  wire values: `TxnType.WebPay`, `PaymentStatus.Authorised`, `PaymentMethod.PmPgCard`. Error codes are
  UPPER_SNAKE: `ErrorCode.PAYMENT_NOT_FOUND`. Compare with `Constant.equals(value)`, which is null-safe.
- All exceptions are unchecked and extend `PrestoPayException`.
- Don't use anything under `com.prestouniverse.pay.internal`; it isn't public API.

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

Maven:

```xml
<dependency>
  <groupId>com.prestouniverse</groupId>
  <artifactId>presto-pay-sdk</artifactId>
  <version>0.2.1</version>
</dependency>
```

Gradle: `implementation("com.prestouniverse:presto-pay-sdk:0.2.1")`

## Keys

The Java SDK reads the merchant private key from a **PKCS#12 keystore** (`.p12`). Give the user these commands to
run themselves; `keytool` ships with the JDK:

```bash
keytool -genkeypair -alias merchant -keyalg RSA -keysize 2048 -validity 99999 \
  -dname "CN=Your Company" -storetype PKCS12 -keystore merchant.p12
keytool -exportcert -alias merchant -keystore merchant.p12 -file merchant.der
```

- `merchant.p12` holds the private key: secret, out of source control, password in a secret store.
- `merchant.der` is the public key in the DER format Presto requires: the user sends it to Presto, once for
  staging and once for production.

Presto's certificate (`presto.der`) is read with `PrestoPayKeys.publicKeyFromX509(...)`.

## Client

Prefer configuration from the environment:

```java
PrestoPayClient presto = PrestoPayClient.fromEnv();
```

| Variable | Required | Value |
|----------|----------|-------|
| `PRESTOPAY_ENV` | This or `PRESTOPAY_BASE_URL` | `staging` or `production` |
| `PRESTOPAY_BASE_URL` | This or `PRESTOPAY_ENV` | A gateway base URL, overriding `PRESTOPAY_ENV` |
| `PRESTOPAY_MID` | Yes | The merchant's `mid` |
| `PRESTOPAY_KEYSTORE_PATH` | Yes | Path to the `.p12` keystore |
| `PRESTOPAY_KEYSTORE_PASSWORD` | Yes | The keystore's password |
| `PRESTOPAY_KEYSTORE_ALIAS` | No | Only if the keystore holds more than one private key |
| `PRESTOPAY_PUBLIC_KEY_PATH` | Yes | Path to Presto's `.der` certificate |

A missing variable throws `PrestoPayConfigException` naming it. `fromEnv()` uses default timeouts and retries.

`prestoMrn` is not a client setting; it goes on every request. Add your own setting for it, such as
`PRESTOPAY_MRN` (Spring: `prestopay.mrn`).

Builder, for keys from a secret store or the app's own settings:

```java
import com.prestouniverse.pay.Environment;
import com.prestouniverse.pay.PrestoPayClient;
import com.prestouniverse.pay.PrestoPayKeys;

PrivateKey privateKey = PrestoPayKeys.privateKeyFromPkcs12(
    new ByteArrayInputStream(keystoreBytes), keystorePassword); // char[]; add an alias if there are several keys
Arrays.fill(keystorePassword, '\0');

PrestoPayClient presto = PrestoPayClient.builder()
    .environment(Environment.STAGING) // or Environment.PRODUCTION
    .merchantId(mid)
    .privateKey(privateKey)
    .prestoPublicKey(PrestoPayKeys.publicKeyFromX509(Paths.get(prestoCertPath)))
    .build();
```

`PrestoPayKeys` also takes `Path`s. Bad keys or a wrong password fail in `build()`, not on the first payment.

## Checkout

### Start a payment

```java
import com.prestouniverse.pay.payments.PaymentInitRequest;
import com.prestouniverse.pay.payments.PaymentInitResponse;
import com.prestouniverse.pay.payments.PaymentMethod;
import com.prestouniverse.pay.payments.TxnType;

PaymentInitRequest request = PaymentInitRequest.builder()
    .merchantRefNum(prestoMrn)
    .txnType(TxnType.WebPay)
    .txnRefNum(order.getTxnRefNum())
    .displayDesc("Order " + order.getId())
    .amount(order.getTotalMinorUnits()) // int, minor units: 10_000 is MYR 100.00
    .currencyCode("MYR")
    .notifyUrl(baseUrl + "/presto/notify")
    .redirectUrl(baseUrl + "/presto/return/" + order.getTxnRefNum())
    // .allowedPaymentMethods(PaymentMethod.PmPgCard) // only for your own method selection page
    .build();

PaymentInitResponse payment = presto.payments().init(request);

order.setPaymentRefNum(payment.paymentRefNum());
order.setPaymentStatus(payment.paymentStatus());
orders.save(order);

if (payment.paymentUrl() == null || payment.paymentUrl().isEmpty()) {
    throw new IllegalStateException("Presto returned no paymentUrl for " + order.getTxnRefNum());
}
return "redirect:" + payment.paymentUrl(); // Spring MVC; or response.sendRedirect(...)
```

`build()` throws `PrestoPayConfigException` (with `field()`) when a required field is missing or invalid.
Optional: `.receiptName(...)`, `.receiptEmail(...)`. Convert money from `BigDecimal` to minor units explicitly
(`amount.movePointRight(2).intValueExact()` for MYR).

If the outcome is unknown, resend `init` with the same request. Java has no "may have taken effect" flag; decide
from the exception type:

```java
PaymentInitResponse payment;
try {
    payment = presto.payments().init(request);
} catch (PrestoPayTransportException | PrestoPayResponseException | PrestoPaySignatureException e) {
    payment = presto.payments().init(request); // same txnRefNum: returns the existing payment
} catch (PrestoPayApiException e) {
    if (e.httpStatus() < 500) {
        throw e; // Presto refused the request; nothing happened
    }
    payment = presto.payments().init(request);
}
```

### Query the status

```java
import com.prestouniverse.pay.payments.PaymentQueryRequest;
import com.prestouniverse.pay.payments.PaymentQueryResponse;
import com.prestouniverse.pay.payments.PaymentStatus;

PaymentQueryResponse result = presto.payments().query(PaymentQueryRequest.builder()
    .merchantRefNum(prestoMrn)
    .txnRefNum(txnRefNum) // or .paymentRefNum(...)
    .build());

if (PaymentStatus.Authorised.equals(result.paymentStatus())) {
    // paid
} else if (PaymentStatus.PendingAuthorise.equals(result.paymentStatus())) {
    // processing: check again shortly
} else {
    // not paid, or a status this SDK version doesn't know
}
```

Other constants: `Failed`, `Cancelled`, `Expired`, `PendingReverse`, `Reversed`, `PendingRefund`,
`PartialRefunded`, `Refunded`. Don't map statuses to a Java `enum` that throws on unknown values; keep the
`String`, or map unknown values to an `UNKNOWN` constant.

`method()` on each `paymentDetails()` entry is a `String`; store and show an unknown code as it is. Any code can
be passed to `allowedPaymentMethods(...)` as a string.

### One update function for return page and webhook

Both callers pass the query result to one order service. In a `@Transactional` method, lock the order or use a
conditional update, reject stale status changes, save the new status, and insert a fulfillment job with a unique
order key when the status first becomes `PaymentStatus.Authorised`. Process the job after commit and make its
fulfillment action idempotent and retryable. Calling `fulfilment.fulfil(order)` after saving the paid status can
leave an order unfulfilled if fulfillment fails.

## Webhooks

`presto.webhooks().parse(rawBody)` takes the raw body `String` and returns a `NotifyEvent` with `eventCode()`,
`success()`, `mid()`, `prestoMrn()`, `paymentRefNum()`, `txnRefNum()`, `eventRefNum()`, `amount()`,
`currencyCode()` and `paymentDetails()`. It checks the signature, required fields, the client's `mid`, and the
15-minute window.

It throws `PrestoPaySignatureException` (bad signature, another `mid`, stale timestamp: answer 401) or
`PrestoPayResponseException` (malformed body: answer 200 with `NotifyAck.ok()`). Replies are `NotifyAck.ok()`
(`{"resend":false}`) and `NotifyAck.resend()` (`{"resend":true}`), sent as `application/json`.

Spring MVC:

```java
import com.prestouniverse.pay.exception.PrestoPayException;
import com.prestouniverse.pay.exception.PrestoPayResponseException;
import com.prestouniverse.pay.exception.PrestoPaySignatureException;
import com.prestouniverse.pay.webhooks.NotifyAck;
import com.prestouniverse.pay.webhooks.NotifyEvent;

@PostMapping(value = "/presto/notify", consumes = MediaType.APPLICATION_JSON_VALUE)
public ResponseEntity<String> notify(@RequestBody String rawBody) {
    NotifyEvent event;
    try {
        event = presto.webhooks().parse(rawBody);
    } catch (PrestoPaySignatureException e) {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
    } catch (PrestoPayResponseException e) {
        return ack(NotifyAck.ok());
    }

    try {
        PaymentQueryResponse payment = presto.payments().query(PaymentQueryRequest.builder()
            .merchantRefNum(event.prestoMrn())
            .paymentRefNum(event.paymentRefNum())
            .build());
        webhookService.handleOnce(event.eventRefNum(), event.txnRefNum(), payment.paymentStatus());
    } catch (RuntimeException e) {
        return ack(NotifyAck.resend());
    }
    return ack(NotifyAck.ok());
}

private static ResponseEntity<String> ack(String body) {
    return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(body);
}
```

`handleOnce` is `@Transactional`: insert `eventRefNum` into a table with a unique constraint, return quietly on
a duplicate-key exception (a redelivery), otherwise call `applyPaymentStatus`.

Take the body as `@RequestBody String`, never a DTO. With the Servlet API, read `request.getReader()` to the end.
Exclude the route from Spring Security's CSRF protection and from authentication.

Several `mid`s: each client accepts webhooks only for its own `mid`. Give each merchant its own `notifyUrl`, such
as `/presto/notify/{mid}`, and parse with that merchant's client.

Webhook-only service without the private key:

```java
WebhookVerifier verifier = WebhookVerifier.builder()
    .prestoPublicKey(PrestoPayKeys.publicKeyFromX509(Paths.get("presto.der")))
    .merchantId(mid)
    .build();
NotifyEvent event = verifier.parse(rawBody);
```

Freshness window: `PrestoPayClient.builder().webhookMaxTimestampAge(Duration)`, or `maxTimestampAge(...)` /
`disableTimestampCheck()` on `WebhookVerifier.Builder`. Change it only with `eventRefNum` dedup in place.

## Refunds and errors

```java
PaymentReverseResponse reversal = presto.payments().reverse(PaymentReverseRequest.builder()
    .merchantRefNum(prestoMrn)
    .paymentRefNum(paymentRefNum) // or .txnRefNum(...)
    .reversalRefNum(order.getTxnRefNum() + "-reversal")
    .remark("Customer cancelled") // optional
    .build());

PaymentRefundResponse refund = presto.payments().refund(PaymentRefundRequest.builder()
    .merchantRefNum(prestoMrn)
    .paymentRefNum(paymentRefNum)
    .refundRefNum(order.getTxnRefNum() + "-refund-" + n)
    .remark("Customer request") // required
    .amount(2_500)              // optional: leave it out for a full refund
    .build());
```

`query` then shows `reversalStatus()` (`ReversalStatus.Reversing`, `Failed`, `Success`), `refundStatus()`
(`RefundStatus.Refunding`, `Failed`, `Success`) and `refundDetails()` (each with `refundRefNum()`,
`refundStatus()`).

| Exception | Useful methods |
|-----------|----------------|
| `PrestoPayConfigException` | `field()` |
| `PrestoPayTransportException` | `requestNotSent()` |
| `PrestoPayApiException` | `errorCode()`, `errorMessage()`, `httpStatus()`, `isSystemError()`, `rawBody()` |
| `PrestoPaySignatureException` | `side()`, `canonicalString()` |
| `PrestoPayResponseException` | `source()`, `rawBody()` |

```java
} catch (PrestoPayApiException e) {
    if (ErrorCode.PAYMENT_NOT_FOUND.equals(e.errorCode())) { ... }
}
```

Unknown outcome on `reverse` / `refund` (a transport, response or signature exception, or an API exception with
`httpStatus() >= 500`): `query` by `paymentRefNum` first, and look for your `refundRefNum` in `refundDetails()` or
at `reversalStatus()`. Retry only if it didn't take effect.

Retries are built in: `query` on network errors and 5xx; `init` / `reverse` / `refund` only when
`requestNotSent()` is true. Default: 2 retries (200 ms, 400 ms), 5 s connect timeout, 30 s read timeout. Change
with `.retryPolicy(RetryPolicy.of(3, Duration.ofMillis(500)))` (or `RetryPolicy.none()`), `.connectTimeout(...)`,
`.readTimeout(...)`.

## Production

- `Environment.PRODUCTION` (or `PRESTOPAY_ENV=production`) with production credentials.
- Timeouts below the servlet container's or load balancer's request timeout.
- One Presto certificate per client (`prestoPublicKey`). During an announced key rotation, follow Presto's
  instructions for the switch-over time.
- Custom HTTP: implement `HttpTransport` and pass it to `.transport(...)`. Wrap `HttpTransport.jdkDefault()` to
  add logging. A transport must return non-2xx responses rather than throw, never follow redirects or resend, and
  set `requestNotSent = true` only when the request certainly never left the process. Examples with Spring
  `RestClient`, JDK 11 `HttpClient` and OkHttp:
  https://github.com/prestoconnect/presto-pay-sdk-java/tree/main/sample/custom-transport
- Troubleshooting names: `ErrorCode.EXCEEDED_VALIDITY_PERIOD` (`1005`), `ErrorCode.INVALID_SIGNATURE` /
  `ErrorCode.SIGNATURE_VERIFICATION_FAILED` (`1006`/`1007`; `Canonicalizer.canonicalizeJson(json)` rebuilds the
  signed string from a raw body), `ErrorCode.INVALID_MID`, `ErrorCode.INVALID_MERCHANT_REFERENCE`,
  `ErrorCode.DUPLICATE_TXN_REF_NUM` (`1203`). `PrestoPaySignatureException.canonicalString()` holds what was
  verified.

## Framework notes

Runnable Spring Boot checkout against Presto staging:
https://github.com/prestoconnect/presto-pay-sdk-java/tree/main/sample/my-store

**Spring Boot.** One `@Bean PrestoPayClient` in a `@Configuration` class, built from `PrestoPayClient.fromEnv()` or
from `@ConfigurationProperties` (`prestopay.environment`, `prestopay.mid`, `prestopay.mrn`,
`prestopay.keystore-path`, `prestopay.keystore-password`, `prestopay.public-key-path`). Inject it into services.
Webhook controller as above; in Spring Security, `csrf(c -> c.ignoringRequestMatchers("/presto/notify"))` and
`permitAll()` for that path.

**Spring WebFlux.** The client is blocking; call it on `Schedulers.boundedElastic()`. Read the webhook body with
`@RequestBody String` (or `Mono<String>`).

**Jakarta / Servlet, Quarkus, Micronaut.** Same pattern: one application-scoped client, raw `String` body for the
webhook.

**Kotlin.** Use the builders as is; compare statuses with `PaymentStatus.Authorised == result.paymentStatus()`.

**Testing.** `PrestoPayClient`, `PaymentsClient` and the response classes are `final`, and responses can't be
constructed outside the SDK. Wrap the calls you use in a small interface of your own (for example
`PaymentGateway.startPayment(...)` returning your own value type with `paymentUrl` and `paymentRefNum`, and
`paymentStatus(txnRefNum)` returning the status `String`), implement it with the SDK, and fake it in tests. Keep
business logic, such as `applyPaymentStatus`, on plain `String` statuses. Cover an unknown status such as
`"SomethingNew"`.
