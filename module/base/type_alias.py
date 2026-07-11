from collections.abc import Sequence
from os import PathLike

import numpy as np
from numpy.typing import NDArray

type Scalar = int | float | np.integer | np.floating
type NumericArray = NDArray[np.integer] | NDArray[np.floating]
type Point = tuple[Scalar, Scalar] | Sequence[Scalar] | NumericArray
type Area = tuple[Scalar, Scalar, Scalar, Scalar] | Sequence[Scalar] | NumericArray
type Color = tuple[Scalar, Scalar, Scalar] | Sequence[Scalar] | NumericArray
type Size = tuple[int, int] | Sequence[int] | NDArray[np.integer]
type ImageArray = NDArray[np.uint8]
type FloatImageArray = NDArray[np.float64]
type BoolArray = NDArray[np.bool_]
type FilePath = str | PathLike[str]
