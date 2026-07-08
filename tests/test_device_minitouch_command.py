from module.device.method.minitouch import Command, CommandBuilder


class _Device:
    orientation = 0
    max_x = 1280
    max_y = 720

    def __init__(self) -> None:
        self.sent: list[CommandBuilder] = []

    def minitouch_send(self, builder: CommandBuilder) -> str:
        self.sent.append(builder)
        return builder.to_minitouch()


def test_command_formats_minitouch_protocol() -> None:
    assert Command("c").to_minitouch() == "c\n"
    assert Command("r").to_minitouch() == "r\n"
    assert Command("w", ms=25).to_minitouch() == "w 25\n"
    assert Command("u", contact=1).to_minitouch() == "u 1\n"
    assert Command("d", contact=1, position=(10, 20), pressure=50).to_minitouch() == "d 1 10 20 50\n"
    assert Command("m", contact=1, position=(30, 40), pressure=60).to_minitouch() == "m 1 30 40 60\n"


def test_command_builder_keeps_existing_sequence_format() -> None:
    builder = CommandBuilder(_Device())

    result = builder.down(400, 300).commit().wait(20).move(410, 310).commit().up().to_minitouch()

    assert result == "d 0 400 300 100\nc\nw 20\nm 0 410 310 100\nc\nu 0\n"
    assert builder.delay == 20
