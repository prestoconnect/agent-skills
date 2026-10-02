# Presto Connect agent skills

[Agent Skills](https://agentskills.io) from Presto Connect, shipped together as the `prestoconnect` plugin.

| Skill | Purpose |
| --- | --- |
| [`presto-pay`](plugins/prestoconnect/skills/presto-pay) | Integrate the Presto Pay payment gateway with the official SDKs |

Installing the plugin gives your agent every skill listed here, including ones added later.

## presto-pay

Teaches AI coding agents to integrate the **Presto Pay** payment gateway correctly with the official Presto Pay SDKs for
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
/plugin marketplace add prestoconnect/agent-skills
/plugin install prestoconnect@presto-pay
```

### Other agents

Each skill is a folder under [`plugins/prestoconnect/skills`](plugins/prestoconnect/skills). Copy the ones you want
into your agent's skills directory, for example `presto-pay` for a single project:

```bash
git clone --depth 1 https://github.com/prestoconnect/agent-skills
cp -r agent-skills/plugins/prestoconnect/skills/presto-pay <your-agent-skills-dir>/presto-pay
```

Each skill folder is self-contained, so it works wherever your agent reads `SKILL.md` skills.

## What you still need from Presto

For `presto-pay`, the skill can't create these for you:

- A merchant ID (`mid`) and Presto merchant reference (`prestoMrn`), separately for staging and production.
- Presto's certificate (`.der`) for each environment.
- Registration of your public key, which the skill helps you generate.

## Contents

```
.claude-plugin/marketplace.json     marketplace "presto-pay"
plugins/prestoconnect/              plugin "prestoconnect"; add new skills under skills/
plugins/prestoconnect/skills/presto-pay/
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
python scripts/run_evals.py --case go-webhook-raw-body-fix  # baseline and skill in separate fixture copies
claude plugin validate .                  # marketplace manifest
claude plugin validate plugins/prestoconnect # plugin manifest
```

The evaluation runner requires the Codex CLI and API access. It writes per-arm code, event logs, and results under
the ignored `evals/runs/` directory. Use `--case` to select cases, `--arm` for one side, and `--timeout` to limit
each run. The [2026-10-02 evaluation](evals/results-2026-10-02.md) records the current comparisons and limits.

When an SDK releases a version that changes its public API, update that language file and its
`Written against` line. The online check fails if a pin is behind or release tags cannot be read; use
`--offline` to check only local skill structure and pin syntax.

## License

Apache License 2.0. See [LICENSE](LICENSE).
