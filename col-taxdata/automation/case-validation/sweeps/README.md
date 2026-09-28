# Tester sweeps

Each Tester invocation creates one sweep directory:

```text
SW-<utc>-<suffix>/
├── discovery.yaml
└── result.yaml
```

`discovery.yaml` is created before case execution and freezes the complete candidate set observed at sweep start.

`result.yaml` is created once after the sweep and records one disposition for every discovery candidate: executed with a run reference, or skipped with an explicit reason.

Both files are immutable after creation.
