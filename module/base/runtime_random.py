import numpy as np

PROBABILITY_RANGE_MESSAGE = "probability must be between 0 and 1"


class RuntimeRandom:
    """运行期随机源，供非可复现实验的路径复用。"""

    def __init__(self, seed: int | None = None) -> None:
        self._generator = np.random.default_rng(seed)

    def uniform(self, low=0.0, high=None, size=None):
        if high is None:
            return self._generator.uniform(low=low, size=size)
        return self._generator.uniform(low=low, high=high, size=size)

    def chance(self, probability: float = 0.5) -> bool:
        if not 0.0 <= probability <= 1.0:
            raise ValueError(PROBABILITY_RANGE_MESSAGE)
        return bool(self._generator.random() < probability)


runtime_random = RuntimeRandom()
