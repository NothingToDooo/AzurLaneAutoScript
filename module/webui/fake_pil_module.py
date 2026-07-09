import sys
from types import ModuleType


def import_fake_pil_module():
    fake_pil_module = ModuleType("PIL")
    image_module = ModuleType("PIL.Image")
    vars(image_module)["Image"] = type("MockPILImage", (), {"__init__": None})
    vars(fake_pil_module)["Image"] = image_module
    sys.modules["PIL"] = fake_pil_module
    sys.modules["PIL.Image"] = image_module


def remove_fake_pil_module():
    sys.modules.pop("PIL", None)
    sys.modules.pop("PIL.Image", None)
