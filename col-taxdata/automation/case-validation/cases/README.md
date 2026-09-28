# Cases

Each generated case gets its own directory:

```text
TC-<id>/
├── case.yaml   # immutable definition, Generator create-only
└── state.yaml  # mutable lifecycle, Tester-owned
```

Do not place run history in the mutable state file. Run evidence belongs under `../runs/`.

The Generator may create a new case directory and append its reference to `TestCasePool.yaml`. The Tester owns subsequent lifecycle transitions in `state.yaml`.
