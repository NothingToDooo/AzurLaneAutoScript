from module.os.map import OSMap
from module.os_handler.action_point import OCR_OS_ADAPTABILITY


class OpsiMonthBoss(OSMap):
    def get_adaptability(self) -> list[int]:
        adaptability = OCR_OS_ADAPTABILITY.ocr(self.device.image)
        if isinstance(adaptability, int):
            message = "OS adaptability OCR requires three regions"
            raise TypeError(message)
        return adaptability
