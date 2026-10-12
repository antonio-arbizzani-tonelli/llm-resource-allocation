# Frozen Python reference cases

These four input/reference pairs were exported against the validated Python
3.14.3 reference. They are synthetic verification inputs.

| Case | Purpose |
|---|---|
| `minimal_coherent_gh`, `minimal_coherent_agh` | Coherent Stage-1 decisions and objectives. |
| `frozen_batch_d0039_gh`, `frozen_batch_d0039_agh` | Historical literal frozen-query trajectory, including final infeasibility and AGH rejection. |

Each `.txt` supplies exact numeric transport version 1. Each `.json` retains
the independently produced Python expected decisions, objective and trace.
The historical filenames are stable identifiers for those unchanged goldens.

After building from the repository root:

```bash
cpp/build/release/pacs_serial gh < cpp/tests/fixtures/minimal_coherent_gh.txt
cpp/build/release/pacs_serial agh < cpp/tests/fixtures/minimal_coherent_agh.txt
python scripts/check_cpp_parity.py --frozen-only
```

The native executable runs the inputs without Python. Automatic comparison
uses the installed Python package and the retained expectations; expectations
must not be regenerated from C++. Add `--wsl Ubuntu` for Windows Python/WSL
execution. The [native guide](../../README.md) explains the complete live suite.
