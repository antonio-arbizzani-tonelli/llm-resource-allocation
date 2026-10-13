# Larger allocation instances: measured CPU performance

Completed timing jobs: **10/12**. Verified recorded files: **1654**.

Finished methods retain all samples and checks; a timeout label refers to the two-method worker job.

Supplemental native rows have independently checked final decisions; full Python algorithm parity is not claimed.

| Shape (queries x models x tiers) | Method | Verification | Job state | C++ median (s) | IQR (s) | Process median (s) | Python reference (s) |
|---|---|---|---|---:|---:|---:|---:|
| 16x4x4 | GH | full_python_reference | completed | 0.001641 | 0.000251 | 0.130480 | 0.102 |
| 16x4x4 | AGH | full_python_reference | completed | 0.040911 | 0.004472 | 0.126421 | 3.402 |
| 32x4x4 | GH | full_python_reference | completed | 0.002972 | 0.000053 | 0.109752 | 0.260 |
| 32x4x4 | AGH | full_python_reference | completed | 0.117819 | 0.002291 | 0.210773 | 12.576 |
| 64x4x4 | GH | full_python_reference | completed | 0.010349 | 0.000538 | 0.112380 | 0.865 |
| 64x4x4 | AGH | full_python_reference | completed | 0.713473 | 0.122482 | 0.877937 | 67.534 |
| 128x4x4 | GH | full_python_reference | completed | 0.043299 | 0.005358 | 0.178984 | 4.357 |
| 128x4x4 | AGH | full_python_reference | completed | 2.889289 | 0.757512 | 3.177422 | 340.978 |
| 256x4x4 | GH | full_python_reference | worker_error | 0.179057 | 0.029731 | 0.390215 | 16.826 |
| 32x8x4 | GH | full_python_reference | completed | 0.005267 | 0.000142 | 0.113351 | 0.544 |
| 32x8x4 | AGH | full_python_reference | completed | 0.246502 | 0.054054 | 0.400070 | 23.670 |
| 32x4x8 | GH | full_python_reference | completed | 0.006577 | 0.000397 | 0.123294 | 0.678 |
| 32x4x8 | AGH | full_python_reference | completed | 0.285071 | 0.014628 | 0.427872 | 30.083 |
| 64x8x8 | GH | full_python_reference | completed | 0.042866 | 0.011010 | 0.239964 | 3.941 |
| 64x8x8 | AGH | full_python_reference | completed | 1.922956 | 0.131011 | 2.085965 | 309.775 |
| 128x8x8 | GH | full_python_reference | worker_error | 0.143100 | 0.013213 | 0.438955 | 15.354 |
| 128x8x8 | AGH | independent_final_decision | supplemental_completed | 7.470639 | 0.386280 | 7.730650 | unavailable |
| 256x4x4 | AGH | independent_final_decision | supplemental_completed | 7.156380 | 0.210480 | 7.327007 | unavailable |

| Batch | Workload | Schedule | Actual team | Median core speedup | Efficiency | Median process speedup |
|---:|---|---|---:|---:|---:|---:|
| 32 | uniform | serial | 1 | 1.00 | 1.000 | 1.00 |
| 32 | uniform | static | 1 | 1.05 | 1.049 | 1.09 |
| 32 | uniform | static | 2 | 1.64 | 0.822 | 1.47 |
| 32 | uniform | static | 4 | 2.69 | 0.672 | 2.10 |
| 32 | uniform | static | 8 | 3.74 | 0.468 | 2.36 |
| 32 | uniform | dynamic | 1 | 0.97 | 0.966 | 0.97 |
| 32 | uniform | dynamic | 2 | 1.72 | 0.862 | 1.56 |
| 32 | uniform | dynamic | 4 | 2.84 | 0.709 | 2.10 |
| 32 | uniform | dynamic | 8 | 3.84 | 0.480 | 2.37 |
| 32 | mixed | serial | 1 | 1.00 | 1.000 | 1.00 |
| 32 | mixed | static | 1 | 1.09 | 1.094 | 1.13 |
| 32 | mixed | static | 2 | 1.12 | 0.560 | 1.13 |
| 32 | mixed | static | 4 | 1.90 | 0.475 | 1.57 |
| 32 | mixed | static | 8 | 3.08 | 0.385 | 2.13 |
| 32 | mixed | dynamic | 1 | 0.99 | 0.986 | 1.03 |
| 32 | mixed | dynamic | 2 | 1.70 | 0.851 | 1.43 |
| 32 | mixed | dynamic | 4 | 3.01 | 0.753 | 2.04 |
| 32 | mixed | dynamic | 8 | 4.20 | 0.525 | 2.27 |
| 64 | uniform | serial | 1 | 1.00 | 1.000 | 1.00 |
| 64 | uniform | static | 1 | 1.03 | 1.031 | 1.06 |
| 64 | uniform | static | 2 | 1.58 | 0.789 | 1.45 |
| 64 | uniform | static | 4 | 2.45 | 0.613 | 1.95 |
| 64 | uniform | static | 8 | 3.35 | 0.419 | 2.32 |
| 64 | uniform | dynamic | 1 | 0.96 | 0.958 | 0.96 |
| 64 | uniform | dynamic | 2 | 1.59 | 0.795 | 1.48 |
| 64 | uniform | dynamic | 4 | 2.40 | 0.599 | 1.87 |
| 64 | uniform | dynamic | 8 | 3.43 | 0.429 | 2.34 |
| 64 | mixed | serial | 1 | 1.00 | 1.000 | 1.00 |
| 64 | mixed | static | 1 | 1.06 | 1.061 | 1.11 |
| 64 | mixed | static | 2 | 1.11 | 0.554 | 1.14 |
| 64 | mixed | static | 4 | 1.79 | 0.449 | 1.55 |
| 64 | mixed | static | 8 | 2.94 | 0.367 | 2.14 |
| 64 | mixed | dynamic | 1 | 1.00 | 1.004 | 1.02 |
| 64 | mixed | dynamic | 2 | 1.66 | 0.831 | 1.46 |
| 64 | mixed | dynamic | 4 | 2.65 | 0.662 | 1.91 |
| 64 | mixed | dynamic | 8 | 3.93 | 0.491 | 2.26 |
| 128 | uniform | serial | 1 | 1.00 | 1.000 | 1.00 |
| 128 | uniform | static | 1 | 1.01 | 1.012 | 1.04 |
| 128 | uniform | static | 2 | 1.61 | 0.803 | 1.50 |
| 128 | uniform | static | 4 | 2.27 | 0.567 | 1.82 |
| 128 | uniform | static | 8 | 3.12 | 0.390 | 2.40 |
| 128 | uniform | dynamic | 1 | 1.00 | 0.999 | 1.01 |
| 128 | uniform | dynamic | 2 | 1.54 | 0.770 | 1.41 |
| 128 | uniform | dynamic | 4 | 2.40 | 0.600 | 2.02 |
| 128 | uniform | dynamic | 8 | 3.39 | 0.423 | 2.54 |
| 128 | mixed | serial | 1 | 1.00 | 1.000 | 1.00 |
| 128 | mixed | static | 1 | 1.04 | 1.039 | 1.06 |
| 128 | mixed | static | 2 | 1.07 | 0.535 | 1.09 |
| 128 | mixed | static | 4 | 1.81 | 0.453 | 1.62 |
| 128 | mixed | static | 8 | 2.71 | 0.339 | 2.09 |
| 128 | mixed | dynamic | 1 | 0.99 | 0.989 | 0.96 |
| 128 | mixed | dynamic | 2 | 1.59 | 0.795 | 1.45 |
| 128 | mixed | dynamic | 4 | 2.59 | 0.648 | 1.88 |
| 128 | mixed | dynamic | 8 | 3.71 | 0.464 | 2.29 |

- Python reference includes projection/independent validation and is timed once; C++ core uses five individual samples.
- OpenMP speedup uses serial execution in the identical campaign binary and the observed team size.
- Minimum, median and full-process times are separate; IQR describes samples, not a confidence interval.
- The empirical endpoint exponent describes this tested range, not a formal complexity bound.
- Synthetic menu values and modeled costs are not measured GPUs or cloud bills.
- A serial row from a stopped worker is a finished, checked method with retained samples; its job status remains explicit.
- Supplemental native rows validate final decisions/objectives in Python; full Python heuristic parity and its runtime are unavailable.
- The 40 Stage-2 stress jobs are outside this timing subset.
