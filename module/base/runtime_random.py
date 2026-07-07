import numpy as np


class RuntimeRandom:
    """运行期随机源，供非可复现实验的路径复用。"""

    def __init__(self, seed: int | None = None) -> None:
        self._generator = np.random.default_rng(seed)

    def uniform(self, low=0.0, high=None, size=None):
        return self._generator.uniform(low=low, high=high, size=size)

    def chance(self, probability: float = 0.5) -> bool:
        if not 0.0 <= probability <= 1.0:
            raise ValueError("probability must be between 0 and 1")
        return bool(self._generator.random() < probability)


runtime_random = RuntimeRandom()
