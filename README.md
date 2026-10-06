# LLM Resource Allocation

Joint resource allocation for SLO-constrained LLM inference in heterogeneous
GPU clouds.

This initial commit contains the reviewed domain structures and mathematical
primitives. The package name `fastllm_replication` is retained to preserve the
existing imports and reviewed source files.

## Included modules

| Module | Responsibility |
| --- | --- |
| `domain/types.py` | Workload, model, GPU-tier, parallelism, and problem-instance data |
| `domain/validation.py` | Input domains and coefficient completeness |
| `domain/units.py` | Decimal KB-to-GB conversion |
| `math/error.py` | Effective error under a precision tier |
| `math/routing.py` | Routing decisions, demand balance, and routing consistency |
| `math/parallelism.py` | Joint TP/PP selection and GPU-count linking |
| `math/latency.py` | Time to first token, generation, and configuration delay |
| `math/mccormick.py` | Binary-continuous product and linearization diagnostics |
| `math/placement.py` | Composite decision state and auxiliary-variable consistency |
| `math/processing_delay.py` | Traffic-weighted processing delay and latency SLO checks |

The reviewed files are copied unchanged. Package initializers and minimal
project metadata make this subset importable on its own. Its mathematical
modules use only the Python standard library.

## Installation

Requires Python 3.13 or later.

```sh
python -m pip install -e .
```

For example:

```python
from fastllm_replication.math.error import compute_effective_error

effective_error = compute_effective_error(0.10, 1.15)
```

## Scientific basis and current scope

The primary formulation is *Scalable Joint Resource Allocation for
SLO-Constrained LLM Inference in Heterogeneous GPU Clouds*,
[arXiv:2604.07472v2](https://arxiv.org/abs/2604.07472v2).

The current subset represents decisions and evaluates formulas and constraint
diagnostics. Optimization models, solvers, allocation heuristics, experiment
data, and tests are outside this initial publication. No paper-calibrated
numerical results are claimed.
