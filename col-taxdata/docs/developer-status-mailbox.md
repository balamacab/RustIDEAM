# Morichal status mailbox for scheduled Developers (#323)

The operator authorized a durable status channel, independent from GitHub source writes. It uses the existing Morichal SSH connector and a standard-library Python script, without an HTTP listener, GitHub credentials or background service.

- Deployed program: /home/user/col-taxdata-agent-status/mailbox.py
- Repository source: col-taxdata/ops/worker_status_mailbox.py
- Private event history: /home/user/col-taxdata-agent-status/events/DEV-1/ and events/DEV-2/
- Directories have mode 0700 and atomic JSON event files mode 0600.
- Events contain the server UTC timestamp, an agent-reported run ID/stage/details, sequence and a SHA-256 previous-hash chain.
- The inspect action validates the entire chain before reporting the latest status.

## Worker write contract

Human labels Desarrollo A/B mean only durable WORKER_ID=DEV-1/DEV-2. At activation start, call the Morichal SSH connector on server morichalserver using this command (substitute the durable identity for DEV-2):

    python3 /home/user/col-taxdata-agent-status/mailbox.py record --worker DEV-1 --stage STARTED --detail-json '{"notes":"scheduled worker started"}'

Copy the returned run_id for all later events in the same activation; include --run-id ID. Report PREFLIGHT after verified GitHub reconciliation, WORKING at source implementation, WAITING for a nonterminal state, DONE only after external CI and convergence acceptance. BLOCKED and FAILED require nonempty operation, error_class, exact_error and next_action strings and should include verifiable issue, claim_attempt, branch, main_sha, checks, PR/CI, steps, stack_excerpt and artifact_path when available. No secrets or corpus content in reports.

For example:

    python3 /home/user/col-taxdata-agent-status/mailbox.py record --worker DEV-1 --run-id ID --stage BLOCKED --detail-json '{"issue":59,"operation":"mcp__GitHub__add_comment_to_issue","error_class":"GITHUB_TOOL_SAFETY_DENIAL","exact_error":"This tool call was blocked by OpenAI safety checks","next_action":"Controller verify exact claim and recover safely"}'

If the status tool itself is rejected, report STATUS_CHANNEL_BLOCKED and the exact tool error in the worker response. Never claim status was persisted without a successful receipt.

## Controller inspection and scheduler recovery

At the beginning and end of each Controller activation, execute through the authorized Morichal SSH connector:

    python3 /home/user/col-taxdata-agent-status/mailbox.py inspect --stale-minutes 90

Compare the last report time and stage with native scheduler last_run_time and GitHub LIVE:
- NO_REPORT means no successful telemetry yet, not worker success.
- TELEMETRY_MISSING means a task ran after the most recent persisted report.
- INCOMPLETE_RUN means STARTED/PREFLIGHT/WORKING without a later terminal record for that run.
- BLOCKED/FAILED require a precise root cause, recovery decision and verification.
- DONE is merely self-reported until real source commits, PR, CI and convergence are confirmed.
- STALE means the reporting event is old; compare scheduler history before blaming the worker.

On the operator's explicit interactive authorization of October 17, 2026, the Controller may reactivate ONLY existing DEV-1 job 6ad191feb4f48191876e14abd67a2460 and DEV-2 job 6ad19213a750819193c2b223fdc4dbe0, by native automation control setting is_enabled=true if disabled. Preserve their schedules and prompts; do not create duplicates or touch unrelated jobs. The Developers themselves must not change any automation.

## Scope, retention and limitations

This is a self-reported coordination ledger. Both workers use the same Morichal SSH login; declared worker identity is not cryptographically authenticated. Hash chaining detects partial edits but not rewriting by a compromised same-account actor. Timestamp documents server write time, not proof that a scheduled worker ran. Morichal never acts as an alternate GitHub writer and does not touch production, crawler, or shared corpus. An unavailable Morichal plugin prevents reporting; the Controller can still detect missing telemetry by comparison with native scheduler history. The Controller is scheduled, not an always-on daemon.

Run isolated regressions with:

    python3 -m unittest discover -s col-taxdata/tests -p test_issue0323_status_mailbox.py -v
