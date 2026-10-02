# Security policy

## Reporting a vulnerability

Email [developer@prestoconnect.io](mailto:developer@prestoconnect.io). Please don't open a public issue or pull
request for a security problem.

Report anything in these skills that could lead an agent to write unsafe payment code, for example guidance that:

- exposes a merchant's private key, keystore password or other secret;
- skips or weakens verification of Presto's responses or webhooks;
- marks an order paid without a confirmed `Authorised` status;
- moves money twice, such as a duplicate refund or reversal.

Include the skill and file, the prompt or code that shows the problem, and what an attacker or a mistake could
cause. Don't include real merchant credentials, private keys or shopper data.

For a vulnerability in an SDK itself, use the same address and name the SDK and version.
