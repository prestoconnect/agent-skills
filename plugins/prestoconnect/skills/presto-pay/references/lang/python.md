# Python: presto-pay-sdk

Written against **presto-pay-sdk 0.1.2**. Source and full docs:
https://github.com/prestoconnect/presto-pay-sdk-python

- Python 3.11+. Imports as `presto_pay`.
- `PrestoPay` (sync) for Django, Flask, Celery and scripts; `AsyncPrestoPay` for FastAPI and other asyncio apps.
  Same API; with `AsyncPrestoPay`, `await` each payment call.
- Arguments are the wire field names in snake_case: `txnRefNum` → `txn_ref_num`.
- Results are frozen dataclasses with snake_case fields. Status and method fields are plain `str`.
- Constants are UPPER_SNAKE: `TxnType.WEB_PAY`, `PaymentStatus.AUTHORISED`, `PaymentMethod.PM_PG_CARD`.

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
pip install "presto-pay-sdk~=0.1.2"
```

Use the project's own tool: `uv add "presto-pay-sdk~=0.1.2"`, `poetry add presto-pay-sdk@^0.1.2`, or a line in
`requirements.txt`. Dependencies: `cryptography` and `httpx`.

## Keys

The merchant generates its own key pair. Give the user these commands to run themselves, rather than running them
for the user, so the private key is created where it will live:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out merchant-key.pem
openssl req -new -x509 -key merchant-key.pem -days 99999 -subj "/CN=Your Company" -outform DER -out merchant.der
```

- `merchant-key.pem` is the private key: secret, out of source control.
- `merchant.der` is the public key in the DER format Presto requires: the user sends it to Presto, once for
  staging and once for production.
- The 99999-day validity means the pair never needs regenerating and re-registering.
- The SDK also reads a `.p12` keystore (including RC2-40 encrypted ones) or an encrypted PEM; pass
  `private_key_password` for those.

Presto sends back its certificate as `presto.der`; the SDK reads it as is.

## Client

Prefer configuration from the environment:

```python
import os

from presto_pay import PrestoPay

presto = PrestoPay.from_env(os.environ)
```

| Variable | Value |
|----------|-------|
| `PRESTOPAY_ENV` or `PRESTOPAY_BASE_URL` | `staging` / `production`, or an explicit HTTPS base URL (set one, not both) |
| `PRESTOPAY_MID` | The merchant's `mid` |
| `PRESTOPAY_PRIVATE_KEY` or `PRESTOPAY_PRIVATE_KEY_FILE` | PEM text, or a path to a PEM, DER or `.p12` file |
| `PRESTOPAY_PRIVATE_KEY_PASSWORD` | The keystore or encrypted-PEM password, if any |
| `PRESTOPAY_PUBLIC_KEY` or `PRESTOPAY_PUBLIC_KEY_FILE` | Presto's certificate as PEM text, or a path to its `.der` file |

`prestoMrn` is not a client setting; it is passed on every call. Add your own variable for it, such as
`PRESTOPAY_MRN`, and read it in the app's settings.

`from_env` accepts any mapping (`os.environ`, a dict from a secrets manager, flattened Django settings) and the
constructor's other options as keyword arguments. A PEM stored on one line with literal `\n` is unescaped
automatically. `PRESTOPAY_PUBLIC_KEY` holds text, so for the binary `.der` either use `PRESTOPAY_PUBLIC_KEY_FILE`
or convert once: `openssl x509 -inform der -in presto.der -out presto.pem`.

Explicit construction, when the app already has its own settings object:

```python
from pathlib import Path

from presto_pay import PrestoPay

presto = PrestoPay(
    environment="staging",
    merchant_id=settings.presto_mid,
    private_key=Path(settings.presto_private_key_file),
    presto_public_key=Path(settings.presto_public_key_file),
)
```

A `str` for `presto_public_key` is treated as PEM text, so pass a `Path` for a file.

Create the client once per process and reuse it; bad keys or a wrong password fail at construction, not on the
first payment. In pre-forking servers (gunicorn, Celery), build it after the fork. Close it on shutdown with
`with` / `close()` (sync) or `async with` / `aclose()` (async).

## Checkout

### Start a payment

```python
from presto_pay import PaymentMethod, TxnType

payment = presto.payments.init(
    presto_mrn=settings.presto_mrn,
    txn_type=TxnType.WEB_PAY,
    txn_ref_num=order.txn_ref_num,
    display_desc=f"Order {order.id}",
    amount=order.total_minor_units,  # int, minor units: 10_000 is MYR 100.00
    currency_code="MYR",
    notify_url="https://shop.example/presto/notify",
    redirect_url=f"https://shop.example/presto/return/{order.txn_ref_num}",
    # allowed_payment_methods=[PaymentMethod.PM_PG_CARD],  # only for your own method selection page
)

order.payment_ref_num = payment.payment_ref_num
order.payment_status = payment.payment_status
order.save()

if payment.payment_url is None:
    raise RuntimeError(f"Presto returned no payment_url for {order.txn_ref_num}")
return redirect(payment.payment_url)
```

- `amount` must be an `int`; a `float` or `Decimal` raises `PrestoPayConfigError`, because `1200.0` would sign
  differently from `1200`. Convert from the app's money type explicitly.
- `init` validates before sending: `currency_code` with `amount`, `redirect_url` for `WEB_PAY`, `qr_value` and
  `payer_ref_num` not both. Failures raise `PrestoPayConfigError`, whose `field` names the argument.
- Optional: `receipt_name`, `receipt_email`.
- `strict=True` on the client enforces documented field lengths, such as 50 characters for `txn_ref_num`. Useful in
  staging and tests.

If the outcome is unknown, resend `init` with the same arguments:

```python
from presto_pay import PrestoPayError

try:
    payment = presto.payments.init(**init_args)
except PrestoPayError as exc:
    if not exc.may_have_taken_effect:
        raise
    payment = presto.payments.init(**init_args)  # same txn_ref_num: returns the existing payment
```

### Query the status

```python
from presto_pay import PaymentStatus

result = presto.payments.query(presto_mrn=settings.presto_mrn, txn_ref_num=txn_ref_num)
# or: presto.payments.query(presto_mrn=..., payment_ref_num=...)

if result.payment_status == PaymentStatus.AUTHORISED:
    ...  # paid
elif result.payment_status == PaymentStatus.PENDING_AUTHORISE:
    ...  # processing: check again shortly
else:
    ...  # not paid, or a status this SDK version doesn't know
```

Other `PaymentStatus` constants: `FAILED`, `CANCELLED`, `EXPIRED`, `PENDING_REVERSE`, `REVERSED`,
`PENDING_REFUND`, `PARTIAL_REFUNDED`, `REFUNDED`.

`result` fields: `payment_ref_num`, `txn_ref_num`, `payment_status`, `amount`, `currency_code`,
`payment_request_date`, `payment_finalised_date`, `payment_details` (tuple of `PaymentDetail` with `method`,
`amount`, card fields), refund and reversal fields, and `raw` (the full wire body). Empty gateway values are
`None`. Dates are strings; `parse_gateway_timestamp()` turns them into aware `datetime`s at UTC+08:00.

Payment method codes: `PaymentMethod.try_parse(detail.method)` returns `None` for a code the SDK doesn't list;
store and show the string as it is in that case. Any code can be passed to `allowed_payment_methods` as a plain
string.

### One update function for return page and webhook

Both callers pass the `QueryResult` to one order service. In one database transaction, lock the order or use a
conditional update, reject stale status changes, save the new status, and insert a fulfillment job with a unique
order key only when the status first becomes `PaymentStatus.AUTHORISED`. Commit before running fulfillment. The
job must be retryable and its fulfillment operation idempotent. Saving the paid status and then calling
`fulfil(order)` outside the transaction can leave a paid order unfulfilled if that call fails.

## Webhooks

`presto.webhooks.verify(body)` takes the raw `bytes` or `str` and refuses a parsed dict. It is synchronous even on
`AsyncPrestoPay`, because it does no I/O. It returns a `WebhookEvent` with `event_code`, `success`, `mid`,
`presto_mrn`, `payment_ref_num`, `txn_ref_num`, `event_ref_num`, `amount`, `currency_code` and
`payment_details`.

Raw body per framework: Django `request.body`, Flask `request.get_data()`, FastAPI / Starlette
`await request.body()`, aiohttp `await request.read()`.

Replies: `NotifyAck.OK` (`{"resend":false}`), `NotifyAck.RESEND` (`{"resend":true}`), content type
`NotifyAck.CONTENT_TYPE`. `NotifyAck.for_error(exc)` picks between them: `OK` for a malformed webhook body
(`PrestoPayResponseError` with `source == "webhook"`), `RESEND` for anything else, including a failed `query`
inside the handler. Catch `PrestoPaySignatureError` first and answer 401.

Flask, with the order update guarded on the order's current status:

```python
from flask import request
from presto_pay import NotifyAck, PrestoPaySignatureError


@app.post("/presto/notify")
def presto_notify():
    try:
        event = presto.webhooks.verify(request.get_data())
    except PrestoPaySignatureError:
        return "", 401
    except Exception as exc:
        return NotifyAck.for_error(exc), 200, {"Content-Type": NotifyAck.CONTENT_TYPE}

    try:
        payment = presto.payments.query(presto_mrn=event.presto_mrn, payment_ref_num=event.payment_ref_num)
        orders.apply_status(event.txn_ref_num, payment.payment_status)
        db.session.commit()
        body = NotifyAck.OK
    except Exception as exc:
        db.session.rollback()
        body = NotifyAck.for_error(exc)
    return body, 200, {"Content-Type": NotifyAck.CONTENT_TYPE}
```

`orders.apply_status` is the same function the return page calls: one conditional
`UPDATE orders SET status = ... WHERE txn_ref_num = ... AND status = 'PendingAuthorise'`, adding the fulfillment
job only when it changed a row and the new status is `Authorised`. A redelivery changes nothing.

Django: same shape with `request.body`, `@csrf_exempt`, `@require_POST`, `transaction.atomic()` around the
guarded order update, and `HttpResponse(body, content_type=NotifyAck.CONTENT_TYPE)`.

FastAPI: same shape with `presto.webhooks.verify(await request.body())`, `await presto.payments.query(...)`, and
`Response(body, media_type=NotifyAck.CONTENT_TYPE)`. With asyncpg, the conditional
`UPDATE ... WHERE status = 'PendingAuthorise' RETURNING txn_ref_num` inside `connection.transaction()` tells you
whether this call finalised the order.

Complete Django, Flask and FastAPI handlers:
https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/docs/webhooks.md

Several `mid`s on one endpoint, or a webhook-only service without the private key:

```python
from pathlib import Path

from presto_pay import create_webhook_verifier

verifier = create_webhook_verifier(
    merchant_id={"MID_ONE", "MID_TWO"},
    presto_public_key=Path("presto.der"),
)
event = verifier.verify(body)
```

Freshness window: `WebhookOptions(max_timestamp_age=...)` on the client, or `max_timestamp_age=` on
`create_webhook_verifier`; `None` disables it. Widen only with the guarded order update in place.

## Refunds and errors

```python
current = presto.payments.query(presto_mrn=presto_mrn, txn_ref_num=order.txn_ref_num)

presto.payments.reverse(
    presto_mrn=presto_mrn,
    payment_ref_num=current.payment_ref_num,
    reversal_ref_num=f"{order.txn_ref_num}-reversal",
    remark="Customer cancelled",
)

presto.payments.refund(
    presto_mrn=presto_mrn,
    payment_ref_num=current.payment_ref_num,
    refund_ref_num=f"{order.txn_ref_num}-refund-{n}",
    remark="Customer request",
    amount=2_500,  # omit for a full refund
)
```

Results: `ReverseResult`, `RefundResult`. After a reversal or refund, `query` exposes `reversal_status`
(`ReversalStatus` constants for `Reversing`, `Failed`, `Success`), `refund_status` (`RefundStatus` constants for
`Refunding`, `Failed`, `Success`) and `refund_details` (tuple of `RefundDetail`, each with `refund_ref_num` and
`refund_status`).

Errors, all subclasses of `PrestoPayError`, which carries `operation`, `may_have_taken_effect` and
`reconcile_by`:

| Class | Extra attributes |
|-------|------------------|
| `PrestoPayConfigError` | `field` |
| `PrestoPayTransportError` | `request_not_sent` |
| `PrestoPayApiError` | `kind` (`"http"` / `"business"`), `http_status`, `error_code`, `error_message`, `raw_body`; `canonical` on `1006`/`1007`; `clock_offset` on `1005` |
| `PrestoPaySignatureError` | `source`, `canonical` |
| `PrestoPayResponseError` | `source`, `raw_body` |

Compare codes with `ErrorCode`, for example `exc.error_code == ErrorCode.PAYMENT_NOT_FOUND`. Unknown codes are
plain strings. `str()` of an error never includes a body. `may_have_succeeded(exc)` checks the flag on any
exception.

Unknown outcome on `reverse` / `refund`: query before anything else.

```python
from presto_pay import PrestoPayError

try:
    presto.payments.refund(**refund_args)
except PrestoPayError as exc:
    if not exc.may_have_taken_effect or exc.reconcile_by is None:
        raise
    current = presto.payments.query(**exc.reconcile_by)
    # Look for refund_args["refund_ref_num"] in current.refund_details before deciding anything.
```

`reconcile_by` holds `presto_mrn` plus `txn_ref_num` after `init`, or `payment_ref_num` after `reverse` and
`refund`, ready to pass to `query`.

Retries are built in. `retry_reads=RetryReads(max_retries=2, initial_backoff=0.2, max_backoff=5.0)` tunes `query`
retries; `deadline` (30 s default) covers the whole call. Don't configure the `httpx` client to retry requests;
`httpx.HTTPTransport(retries=n)` is fine because it only retries failed connections.

## Production

- `environment="production"` (or `PRESTOPAY_ENV=production`) with production credentials.
- `deadline=`: set below the web server's or task's timeout.
- `strict=True` in staging rejects contract drift, such as a field longer than its documented maximum.
- `redact_error_bodies=True` is the default; keep it in production.
- Key rotation: `presto_public_key=[old, new]` during Presto's announced overlap.
- Custom `httpx.Client` / `httpx.AsyncClient` via `http_client=` for proxies, TLS or tracing; the SDK never closes
  a client you pass in.
- Troubleshooting names: `ErrorCode.CLOCK_SKEW` (`1005`, see `exc.clock_offset`), `ErrorCode.INVALID_SIGNATURE` /
  `ErrorCode.SIGNATURE_VERIFICATION_FAILED` (`1006`/`1007`, see `exc.canonical`), `ErrorCode.INVALID_MID`,
  `ErrorCode.INVALID_MERCHANT_REFERENCE`. `canonicalize(body)` rebuilds the signed string from a raw JSON body.
- An endpoint the SDK doesn't model: `presto.raw.post(path, body)` signs, sends, verifies and returns the parsed
  dict.

## Framework notes

Full handlers for each framework (including the webhook) are in the SDK's
[webhooks doc](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/docs/webhooks.md) and runnable
samples ([flask-store](https://github.com/prestoconnect/presto-pay-sdk-python/tree/main/sample/flask-store),
[fastapi-store](https://github.com/prestoconnect/presto-pay-sdk-python/tree/main/sample/fastapi-store)).

**Flask.** `PrestoPay`. Create it in the app factory and keep it on `app.extensions["presto"]` or a module-level
extension object. `redirect(payment.payment_url)` from the checkout view.

**FastAPI.** `AsyncPrestoPay`, created in the lifespan and closed with it, exposed through a dependency:

```python
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse

from presto_pay import AsyncPrestoPay


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.presto = AsyncPrestoPay.from_env(os.environ)
    async with app.state.presto:
        yield


app = FastAPI(lifespan=lifespan)


def get_presto(request: Request) -> AsyncPrestoPay:
    return request.app.state.presto


PrestoDep = Annotated[AsyncPrestoPay, Depends(get_presto)]


@app.post("/checkout/{order_id}")
async def checkout(order_id: str, presto: PrestoDep) -> RedirectResponse:
    payment = await presto.payments.init(...)
    if payment.payment_url is None:
        raise RuntimeError(f"Presto returned no payment_url for {order_id}")
    return RedirectResponse(payment.payment_url, status_code=303)
```

**Django.** `PrestoPay`, created once in an `AppConfig.ready()` or a cached module-level function such as
`functools.cache`, never per request. `from_env` accepts a dict built from Django settings. Return
`HttpResponseRedirect(payment.payment_url)`.

**Testing.** Stub the client at the boundary: pass a fake object with `payments.init` / `payments.query` into the
code under test, or `unittest.mock.create_autospec(PrestoPay)`. Build `QueryResult`-like objects for each status,
including an unknown string such as `"SomethingNew"`.
