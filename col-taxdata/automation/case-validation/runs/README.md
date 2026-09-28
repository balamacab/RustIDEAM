# Case runs

Each executed case attempt receives a unique run directory:

```text
TC-<id>/
└── R-<utc>-<suffix>/
    ├── snapshot.yaml
    └── result.yaml
```

`snapshot.yaml` is persisted immediately before execution and fixes the exact identity of what is being tested.

`result.yaml` is persisted once after the attempt. Both are immutable historical evidence. A later product change or rerun creates a new run directory.
