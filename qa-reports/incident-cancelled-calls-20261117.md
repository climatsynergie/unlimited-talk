# Incident: cancelled/expired preparations, 17 November 2026

## Findings and status

**Confirmed external authentication failure; owner identifies Twilio billing issue. Recovery NOT VERIFIED.** At19:16UTC both the live Voice key and a distinct pre-existing restricted read-only key for the same account received HTTP401/code70051. Owner subsequently confirmed a payment issue. No payment, account/key change, deployment, restart, live call, or application-data mutation was performed.

Read-only live observations: revision0e18ba6 remained READY at schema0012, calling enabled, services healthy and host load low. For the five supplied examples, the four cancelled reservations have no parent/child call SID and no consumption timestamp. They were cancelled by the dialer before authorization, correlated with device error20101 for the affected agents. The expired reservation also never reached provider authorization. These specific clients were not dialled. This does not imply every cancelled call in all history is unconnected.

The seven most recent matching-number records contain six such cancellations and one expired preparation. Over the18:00UTC creation-hour cohort there were155 completed,34 failed,25 no-answer,7 cancelled,1 expired and1 busy records at the snapshot. A latest cancelled-only display is not evidence that most of that whole hour was cancelled, and the provider failure can still block new attempts after its onset.

A newly generated JWT verified locally using the configured HMAC secret with expected issuer/subject, headers and1980s validity. This checks internal consistency only, not provider acceptance. The unchanged profile file mtime was1November. An independent root-network GET to the provider, with credentials kept in memory and never printed, confirmed401 on numbers/account/alerts; the separate old read key also returned401 on its permitted individual-number resource. Account status could not be retrieved; an earlier diagnostic field named `account_status:401` represented an error-body HTTP status, **not** an account status value. No claim of account suspension is derived solely from that field.

Official references: [20101 — invalid access token](https://www.twilio.com/docs/api/errors/20101); [70051 — authorization failed](https://www.twilio.com/docs/api/errors/70051). Those codes alone do not prove a specific billing condition; payment identification came from the owner.

## Evidence and execution outcomes

Each execution's command, timestamp, exit, log/hash is retained below. PASS on a read-only diagnostic means the diagnostic completed; **it does not mean telephony is working**. Provider authentication remained FAIL/401 at the last observation.

### cancelled-calls-readonly-20261117 — PASS, exit 0

```sh
ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 /root/qa-cancelled-calls-20261117-readonly.py
```

[metadata](evidence/cancelled-calls-readonly-20261117.json), [output](evidence/cancelled-calls-readonly-20261117.log).

### cancelled-calls-provider-auth-20261117 — FAIL, exit 1

```sh
ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 /root/qa-cancelled-calls-20261117-auth-check.py
```

[metadata](evidence/cancelled-calls-provider-auth-20261117.json), [output](evidence/cancelled-calls-provider-auth-20261117.log).

### cancelled-calls-provider-auth-final-20261117 — FAIL, exit 1

```sh
ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 /root/qa-cancelled-calls-20261117-auth-check.py
```

[metadata](evidence/cancelled-calls-provider-auth-final-20261117.json), [output](evidence/cancelled-calls-provider-auth-final-20261117.log).

### cancelled-calls-provider-read-root-20261117 — PASS, exit 0

```sh
ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 /root/qa-cancelled-calls-20261117-provider-read.py
```

[metadata](evidence/cancelled-calls-provider-read-root-20261117.json), [output](evidence/cancelled-calls-provider-read-root-20261117.log).

### cancelled-calls-provider-confirm-20261117 — PASS, exit 0

```sh
ssh -i /home/codexdev/.ssh/unlimited-talk-staging -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=12 root@143.198.41.24 python3 /root/qa-cancelled-calls-20261117-provider-confirm.py
```

[metadata](evidence/cancelled-calls-provider-confirm-20261117.json), [output](evidence/cancelled-calls-provider-confirm-20261117.log).

The first JWT diagnostic failed because it assumed an `iat` claim; this SDK emits `nbf`. The corrected diagnostic verified the signature/claims, then timed out attempting a provider read from the deliberately isolated API container. This is not recorded as a provider401 result. The subsequent root-network reads obtained actual provider401 responses. All failed diagnostics are retained.

## Recovery remaining

Owner regularizes billing and confirms the provider account is active. Recheck provider authentication read-only; then one human agent refreshes the application and performs an authorized validation call before the team resumes. No automated redial was scheduled. The listed unconnected recipients remain to be recalled. Real recovery, audio, incoming and outgoing acceptance after payment: **NOT TESTED**.
