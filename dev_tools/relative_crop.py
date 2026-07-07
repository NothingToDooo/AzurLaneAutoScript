import time
from pathlib import Path

import numpy as np
from PIL import Image

from module.base.utils import load_image, rgb2gray
from module.config.config import AzurLaneConfig
from module.map_detection.view import View


class Config:
    """
    Paste the config of map file here
    """


from module.os.config import OSConfig

cfg = AzurLaneConfig("alas").merge(OSConfig())

# Folder to save temp images
folder = "./screenshots/relative_crop"
# Put Screenshot here
file = ""

i = load_image(file)
grids = View(cfg)
grids.load(np.array(i))
grids.predict()
grids.show()


Path(folder).mkdir(parents=True, exist_ok=True)
for grid in grids:
    # Find more relative_crop area in module/map/grid_predictor.py
    # This one is for `predict_enemy_genre`
    piece = rgb2gray(grid.relative_crop((-0.5, -1, 0.5, 0), shape=(60, 60)))

    file = f"{int(time.time())}_{grid.location[0]}_{grid.location[1]}.png"
    file = Path(folder) / file
    Image.fromarray(piece).save(file)
