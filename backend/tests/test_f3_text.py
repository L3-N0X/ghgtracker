import pytest

from ghgtracker.vision.f3_text import parse_f3_text


def test_vanilla_lines() -> None:
    text = "\n".join(
        [
            "XYZ: 1656.654 / 88.00000 / -1815.475",
            "Block: 1656 88 -1816",
            "Facing: east (Towards positive X) (-93.6 / 5.6)",
            "minecraft:overworld FC: 0",
            "Biome: minecraft:snowy_plains",
        ]
    )
    parsed = parse_f3_text(text)
    assert (parsed.x, parsed.y, parsed.z) == (1656.654, 88.0, -1815.475)
    assert parsed.confirmed
    assert parsed.dimension == "overworld"
    assert parsed.biome == "minecraft:snowy_plains"
    assert parsed.facing == "east"


@pytest.mark.parametrize(
    ("xyz_line", "block_line", "expected"),
    [
        # " / " read as "7"
        ("XYZ: 1656.654 7 88.00000 7 -1815.475", "Block: 1656 88 -1816", (1656.654, 88, -1815.475)),
        # separator glued onto the number: only the Block line can tell
        ("XYZ: 0.500 773.00000 70.500", "Block: 0 73 0", (0.5, 73.0, 0.5)),
        # BetterF3 double spaces lost by the OCR, Block digits merged as well
        ("XYZ: 321.77243.00000 289.343", "Block: 32143289", (321.772, 43.0, 289.343)),
        ("XY2: -290.809 62.93750 2179.992", "Block: -291 62 2179", (-290.809, 62.9375, 2179.992)),
    ],
)
def test_ocr_mistakes(xyz_line: str, block_line: str, expected: tuple[float, float, float]) -> None:
    parsed = parse_f3_text(f"{xyz_line}\n{block_line}")
    assert (parsed.x, parsed.y, parsed.z) == expected
    assert parsed.confirmed


def test_unconfirmed_reading() -> None:
    # A dropped minus sign: the Block line disagrees, so the reading stays unconfirmed.
    parsed = parse_f3_text("XYZ: 342.657 / -69.00000 / 371.448\nBlock: 342 69 371")
    assert parsed.has_position and not parsed.confirmed


def test_no_xyz_line() -> None:
    parsed = parse_f3_text("Facing: south\nCPU: 16x AMD\nTargeted Block: 1657 89 -1816")
    assert not parsed.has_position and not parsed.confirmed
    assert parsed.facing == "south"


def test_names_with_ocr_typos() -> None:
    parsed = parse_f3_text(
        "Biome: mineoraft:deserti\nDimension: minecraft:the_nether\nFacing: West (Towards"
    )
    assert parsed.biome == "minecraft:desert"
    assert parsed.dimension == "nether"
    assert parsed.facing == "west"
