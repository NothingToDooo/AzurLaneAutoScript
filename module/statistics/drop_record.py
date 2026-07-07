import threading
import time
from pathlib import Path

from module.base.utils import save_image
from module.logger import logger
from module.statistics.utils import pack


class DropImage:
    def __init__(self, recorder, genre, save, info=""):
        """
        Args:
            recorder (DropRecorder):
            genre:
            save:
            info:
        """
        self.recorder = recorder
        self.genre = str(genre)
        self.save = bool(save)
        self.info = info
        self.images = []

    def add(self, image):
        """
        Args:
            image (np.ndarray):
        """
        if self:
            self.images.append(image)
            logger.info(f"Drop record added, genre={self.genre}, amount={self.count}")

    def handle_add(self, main, before=None):
        """
        Handle wait before and after adding screenshot.

        Args:
            main (ModuleBase):
            before (int, float, tuple): Sleep before adding.
        """
        if before is None:
            before = main.config.WAIT_BEFORE_SAVING_SCREEN_SHOT

        if self:
            main.handle_info_bar()
            main.device.sleep(before)
            main.device.screenshot()
            self.add(main.device.image)

    def clear(self):
        self.images = []

    @property
    def count(self):
        return len(self.images)

    def __bool__(self):
        return self.save

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self:
            self.recorder.commit(images=self.images, genre=self.genre, save=self.save, info=self.info)


class DropRecorder:
    def __init__(self, config):
        """
        Args:
            config (AzurLaneConfig):
        """
        self.config = config

    def _save(self, image, genre, filename):
        """
        Args:
            image: 要保存的图片。
            genre (str): 子目录名称。
            filename (str): 文件名，例如 'xxx.png'。

        Returns:
            bool: 是否保存成功。
        """
        try:
            folder = Path(str(self.config.DropRecord_SaveFolder)) / genre
            Path(folder).mkdir(parents=True, exist_ok=True)
            file = folder / filename
            save_image(image, str(file))
            logger.info(f"Image save success, file: {file}")
        except (OSError, TypeError, ValueError) as e:
            logger.warning(f"Image save failed, {e}")
        else:
            return True

        return False

    def commit(self, images, genre, save=False, info=""):
        """
        Args:
            images (list): List of images in numpy array.
            genre (str):
            save (bool): Whether to save image to local file system.
            info (str): Extra info append to filename.

        Returns:
            bool: Whether a record was committed.
        """
        if len(images) == 0:
            return False

        save = bool(save)
        logger.info(f"Drop record commit, genre={genre}, amount={len(images)}, save={save}")
        image = pack(images)
        now = int(time.time() * 1000)

        filename = f"{now}_{info}.png" if info else f"{now}.png"

        if save:
            save_thread = threading.Thread(target=self._save, args=(image, genre, filename))
            save_thread.start()

        return True

    def new(self, genre, method="do_not", info=""):
        """
        Args:
            genre (str):
            method (str): Whether to save image.
            info (str): Extra info append to filename.

        Returns:
            DropImage:
        """
        save = "save" in method
        return DropImage(recorder=self, genre=genre, save=save, info=info)
