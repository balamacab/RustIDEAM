# Compact controller memory (CM1)

CM1 is the durable, token-efficient memory layer for `col-taxdata` controller threads.

It is not legal/corpus evidence and it is not a replacement for live GitHub state.

## State model

```text
ETHOS.cm      = compact current controller operating principles
sessions/*.cm  = immutable historical controller deltas
INDEX.cm       = deterministic derived lookup index
SCHEMA.cm      = compact wire-format marker/layout table
GitHub live    = authority for current issue/PR/branch state
```

A controller bootstrap loads only `ETHOS.cm` plus `INDEX.cm`. Detailed session records are retrieved only when an exact key is relevant.

## Storage

```text
controller-memory/
├── SCHEMA.cm
├── ETHOS.cm
├── INDEX.cm
└── sessions/
    └── <sid>.cm
```

Session files are append-only. Existing session bytes must never be edited, deleted or renamed. The trusted repository policy rejects non-additive changes under `controller-memory/sessions/*.cm`.

`INDEX.cm` is rebuildable and may change whenever a new session is added.

## Controller ethos

`ETHOS.cm` is the small normative layer describing how a controller should evaluate before acting.

It is deliberately separate from historical session capsules:

- `ETHOS.cm` = current operating principles;
- `sessions/*.cm` = immutable record of what prior controllers knew/decided;
- live GitHub = current operational truth.

Wire format:

```text
CM1|H|<version>
P|<preferred>|<deprioritized>
R|<rule>|<target>
S|observation|conclusion|decision|authorization|execution|verified-integration
```

Current CM1 ethos principles encode, compactly:

```text
evidence > fluency
architecture > immediate unblock
live state > stale handoff
explicit uncertainty > guessed certainty
preserve history > rewrite convenience
root cause > symptom patch
semantic ownership > file proximity
reversible action > premature mutation
critical evaluation > agreement
verified convergence > closure
```

Rules additionally encode that absence of evidence is not authorization, speed is subordinate to correctness/coherence, and evidence may require challenging a user or prior controller while preserving the historical record.

`ETHOS.cm` is current normative state, so it may evolve. Every content change after initial creation must increment its header version exactly by one; trusted CI enforces this against the PR base revision. Git history preserves prior ethos versions, while material changes should also be recorded in a new immutable controller session.

The ethos is capped and intentionally terse. It must not contain explanations, examples, transcript history or confidential data.

## Session header

```text
CM1|S|sid|utc|main_sha|prev
```

- `sid`: `CYYMMDDTHHMMSSZXX`.
- `utc`: `YYYYMMDDTHHMMSSZ`.
- `main_sha`: exact 40-hex main SHA observed at capture.
- `prev`: prior relevant session id or `-`. It is contextual, not a mandatory global linear chain.

Every file name must be exactly `<sid>.cm`.

## Knowledge records

All records are positional and end with a sorted, unique comma-separated retrieval-key field.

```text
D|id|scope|sub|rel|obj|refs|keys
E|src|rel|dst|refs|keys
F|kind|sub|val|refs|keys
A|rank|act|cond|refs|keys
X|kind|refs|payload|keys
```

`X` is a bounded fallback for knowledge that cannot be represented compactly by the structured records. Normal handoffs should prefer D/E/F/A.

Recurring relation codes:

```text
1 owns
2 depends-on
3 blocks
4 supersedes
5 authoritative-for
6 optional-for
7 derived-from/rebuildable-from
8 immutable
9 live-authority
```

Recommended scope codes:

```text
0 controller
1 validation
2 runtime
3 product
4 cross-cutting
```

These values are deliberately positional/coded to reduce repeated natural-language tokens. Their encoding provides no confidentiality guarantee.

## Retrieval keys

Keys are exact identifiers, not free-text search.

Recommended prefixes:

```text
i<N>   GitHub issue
p<N>   pull request
d<N>   controller decision
t<id>  compact topic
b<N>   blocker/dependency subject
```

A record may carry multiple keys, sorted lexicographically. Example:

```text
D|42|0|rt|6|ff|i75|d42,i75,trt
```

The index maps each key to the session files that contain records tagged with that key.

## Derived index

```text
CM1|I|session_count|latest_sid|manifest_sha256
K|key|sid[,sid...]
```

The manifest SHA-256 is calculated deterministically over sorted:

```text
sid|sha256(session_bytes)\n
```

Therefore byte drift or session-set drift changes the source fingerprint.

## Commands

```bash
python3 tools/controller_memory.py bootstrap
python3 tools/controller_memory.py query i67
python3 tools/controller_memory.py verify
python3 tools/controller_memory.py rebuild
python3 tools/controller_memory.py handoff /tmp/C260925T190000Z00.cm
```

`bootstrap` validates the schema and returns only the compact ethos plus compact index. It does not expand historical session payloads.

`query` resolves an exact key through `INDEX.cm` and opens only the referenced session files. It returns only records carrying that key.

`handoff` validates a prepared capsule, requires filename/header identity, creates the destination with exclusive create-new semantics, and rebuilds the derived index. Existing sessions are never overwritten.

`verify` reparses all immutable sessions, rebuilds the expected index in memory and fails if the committed index differs.

## Handoff discipline

At controller checkpoint/handoff:

1. preserve only durable decision deltas, dependencies, blockers, invariants, restrictions, technical discoveries, validation boundaries and conditional next actions;
2. do not dump the chat transcript;
3. create one new CM1 session;
4. run `handoff` or otherwise add the new session create-only;
5. run `verify`;
6. hand the next controller the current main SHA, latest session id and `INDEX.cm` location.

A future controller inherits the current ethos at bootstrap, then revalidates current issue/PR state against GitHub before mutation. Historical session records remain historical even when live state changes.

## Privacy boundary

The repository is public. CM1 is compact for retrieval/token efficiency, not privacy.

Do not write secrets, credentials, private client payloads or confidential case data into controller memory. If confidential controller memory becomes necessary, move the persistence boundary to private storage/repository rather than treating compact codes as security.

## Evolution

CM1 intentionally starts with a bounded ethos + exact-key deterministic retrieval. No embeddings, vector database, model call or network service is required.

A later retrieval layer may build FTS/vector state from immutable CM sessions, but that state must remain derived/rebuildable and must not replace the session capsules as the historical source.
