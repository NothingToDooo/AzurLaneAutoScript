from module.config.code_generator import CodeGenerator


def test_code_generator_write_preserves_exact_line_endings(tmp_path) -> None:
    output = tmp_path / "generated.py"
    generator = CodeGenerator()
    generator.add("first")
    generator.add("last", newline=False)

    assert generator.write(output.as_posix()) is None
    assert output.read_bytes() == b"first\nlast"
