# Presto Pay agent skills

An [Agent Skill](https://agentskills.io) that teaches AI coding agents to integrate the **Presto Pay** payment
gateway correctly with the official Presto Pay SDKs for
[Go](https://github.com/prestoconnect/presto-pay-sdk-go),
[Java](https://github.com/prestoconnect/presto-pay-sdk-java),
[JavaScript/TypeScript](https://github.com/prestoconnect/presto-pay-sdk-js),
[PHP](https://github.com/prestoconnect/presto-pay-sdk-php) and
[Python](https://github.com/prestoconnect/presto-pay-sdk-python).

Ask your agent things like:

- "Add Presto Pay checkout to this app."
- "Handle the Presto Pay webhook and update the order."
- "Refund order 1234 through Presto."
- "We're going live with Presto next week. Review our integration."

The skill detects your language and framework, uses the SDK's real API, and keeps to the rules that protect your
money: status only from `query`, raw-body webhook verification, deduplicated webhooks, no blind refund retries,
and no secrets in source control.

## Install

### Claude Code

```
/plugin marketplace add prestoconnect/presto-pay-agent-skills
/plugin install presto-pay@presto-pay
```

### Other agents

The skill is the folder [`plugins/presto-pay/skills/presto-pay`](plugins/presto-pay/skills/presto-pay). Copy it
into your agent's skills directory, for example for a single project:

```bash
git clone --depth 1 https://github.com/prestoconnect/presto-pay-agent-skills
cp -r presto-pay-agent-skills/plugins/presto-pay/skills/presto-pay <your-agent-skills-dir>/presto-pay
```

The folder is self-contained, so it works wherever your agent reads `SKILL.md` skills.

## What you still need from Presto

The skill can't create these for you:

- A merchant ID (`mid`) and Presto merchant reference (`prestoMrn`), separately for staging and production.
- Presto's certificate (`.der`) for each environment.
- Registration of your public key, which the skill helps you generate.

## Contents

```
plugins/presto-pay/skills/presto-pay/
  SKILL.md                      rules, workflow, routing
  references/
    setup.md                    keys, credentials, configuration, several merchants
    checkout.md                 payment flow, statuses, payment methods
    webhooks.md                 raw-body verification, replies, deduplication
    refunds-and-errors.md       reverse vs refund, errors, unknown outcomes, retries
    go-live.md                  checklist, troubleshooting, reviewing an integration
    lang/{go,java,js,php,python}.md   SDK code per language and framework
```

## Development

```bash
python scripts/check_skills.py            # frontmatter, file references, SDK version pins
python scripts/check_skills.py --offline  # skip comparing pins with GitHub release tags
claude plugin validate .                  # marketplace manifest
claude plugin validate plugins/presto-pay # plugin manifest
```

When an SDK releases a version that changes its public API, update that language file and its
`Written against` line. `check_skills.py` fails while a pin is behind the latest release tag.

## License

Apache License 2.0. See [LICENSE](LICENSE).
