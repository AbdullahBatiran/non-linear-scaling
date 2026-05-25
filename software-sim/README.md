# Histogram Non-Linear Scaling

This package implements the fourth algorithm from `docs/Histogram Based Methods Description_1.pdf`.
It accepts an arbitrary NumPy image, builds a histogram, replaces each bin count with the integer
base-2 logarithm of that count, accumulates the modified histogram, and maps pixels through the
resulting LUT.

## Install

```bash
pip install -e .
```

## Usage

```python
import numpy as np
from histogram_nonlinear_scaling import nonlinear_histogram_scale

image = np.array([[0, 1, 1], [2, 3, 3]], dtype=np.uint16)
scaled = nonlinear_histogram_scale(image, input_levels=4)
```

For hardware-style 14-bit input and 8-bit output:

```python
scaled = nonlinear_histogram_scale(image, input_levels=2**14, output_max=255)
```

To inspect or reuse the conversion table:

```python
scaled, lut = nonlinear_histogram_scale(image, input_levels=2**14, return_lut=True)
```
