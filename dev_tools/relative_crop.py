import time
from pathlib import Path

import numpy as np
from PIL import Image

from module.base.utils import load_image, rgb2gray
from module.config.config import AzurLaneConfig
from module.map_detection.view import View
from module.os.config import OSConfig


class Config:
    """在这里粘贴地图配置。"""


def main() -> None:
    cfg = AzurLaneConfig("alas").merge(OSConfig())

    # 保存临时图片的目录。
    folder = "./screenshots/relative_crop"
    # 在这里填写截图路径。
    file = ""

    image = load_image(file)
    grids = View(cfg)
    grids.load(np.array(image))
    grids.predict()
    grids.show()

    Path(folder).mkdir(parents=True, exist_ok=True)
    for grid in grids:
        # 更多 relative_crop 区域可参考 module/map/grid_predictor.py。
        # 这里用于 `predict_enemy_genre`。
        piece = rgb2gray(grid.relative_crop((-0.5, -1, 0.5, 0), shape=(60, 60)))

        file = f"{int(time.time())}_{grid.location[0]}_{grid.location[1]}.png"
        file = Path(folder) / file
        Image.fromarray(piece).save(file)


if __name__ == "__main__":
    main()
