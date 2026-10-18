"""Parse the text of an F3 screen (as read by OCR) into coordinates, dimension, biome, facing.

OCR engines make a few typical mistakes on the Minecraft font, which the parser knows about:

* the " / " between the XYZ values is often read as "7" or "1" (or dropped together with the
  spaces). XYZ values always have decimals, so plain integers are separators. The game prints X
  and Z with 3 decimals and Y with 5, which also splits values whose spaces got lost
  (BetterF3 separates them by double spaces instead of slashes).
* "Block: x y z" right below holds floor(XYZ). A reading that matches it is confirmed; that
  check also picks the right variant when a separator got glued onto a number ("773.0" -> 73.0).
  The Block values may lose their spaces too, so they are compared as one digit string.
* biome names get single letters wrong ("ptains"): they snap to the closest vanilla biome.
"""

from __future__ import annotations

import difflib
import itertools
import math
import re
from dataclasses import dataclass

LABEL = re.compile(r"[XK]\s*[YV]\s*[Z2]\s*[:;.]?", re.IGNORECASE)
DECIMAL = re.compile(r"-?\d+\.\d+")
F3_FORMAT = re.compile(r"(-?\d+\.\d{3})(-?\d+\.\d{5})(-?\d+\.\d{3})")
# "Block: x y z", not "Targeted Block" / "Highest Block".
BLOCK = re.compile(r"^\W*B[l1I][o0]ck\s*[:;]", re.IGNORECASE)
NUMERIC = str.maketrans({"O": "0", "o": "0", ",": ".", "—": "-", "–": "-", "−": "-"})

# "minecraft:" is often read as "mineoraft:" or similar.
NAMESPACED = r"m[il1]ne[co]r[ae]ft\s*[:;.]\s*([a-z_]+)"
BIOME = re.compile(r"B[il1][o0]me\s*[:;]?\s*" + NAMESPACED, re.IGNORECASE)
DIMENSION = re.compile(NAMESPACED + r"(?=\s*FC\b|\s*$)", re.IGNORECASE)
DIMENSION_LABEL = re.compile(r"D[il1]mension\s*[:;]?\s*" + NAMESPACED, re.IGNORECASE)
FACING = re.compile(r"Fac[il1]ng\s*[:;]?\s*(north|south|east|west)", re.IGNORECASE)

DIMENSIONS = {"overworld": "overworld", "the_nether": "nether", "the_end": "end"}
VANILLA_BIOMES = """
badlands bamboo_jungle basalt_deltas beach birch_forest cherry_grove cold_ocean crimson_forest
dark_forest deep_cold_ocean deep_dark deep_frozen_ocean deep_lukewarm_ocean deep_ocean desert
dripstone_caves end_barrens end_highlands end_midlands eroded_badlands flower_forest forest
frozen_ocean frozen_peaks frozen_river grove ice_spikes jagged_peaks jungle lukewarm_ocean
lush_caves mangrove_swamp meadow mushroom_fields nether_wastes ocean old_growth_birch_forest
old_growth_pine_taiga old_growth_spruce_taiga pale_garden plains river savanna savanna_plateau
small_end_islands snowy_beach snowy_plains snowy_slopes snowy_taiga soul_sand_valley
sparse_jungle stony_peaks stony_shore sunflower_plains swamp taiga the_end the_void warm_ocean
warped_forest windswept_forest windswept_gravelly_hills windswept_hills windswept_savanna
wooded_badlands
""".split()


@dataclass
class F3Text:
    x: float | None = None
    y: float | None = None
    z: float | None = None
    confirmed: bool = False  # XYZ matches the Block line
    biome: str | None = None
    dimension: str | None = None  # overworld / nether / end
    facing: str | None = None

    @property
    def has_position(self) -> bool:
        return self.x is not None


def parse_f3_text(text: str) -> F3Text:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result = F3Text()
    xyz, result.confirmed = _parse_xyz(lines)
    if xyz is not None:
        result.x, result.y, result.z = xyz
    for line in lines:
        if result.biome is None and (m := BIOME.search(line)):
            result.biome = f"minecraft:{_biome(m[1].lower())}"
        if result.dimension is None and (
            m := DIMENSION_LABEL.search(line) or DIMENSION.search(line)
        ):
            result.dimension = DIMENSIONS.get(m[1].lower())
        if result.facing is None and (m := FACING.search(line)):
            result.facing = m[1].lower()
    return result


def _biome(name: str) -> str:
    match = difflib.get_close_matches(name, VANILLA_BIOMES, n=1, cutoff=0.8)
    return match[0] if match else name


def _parse_xyz(lines: list[str]) -> tuple[tuple[float, float, float] | None, bool]:
    # Digits of the Block line ("Block: 7 111 10" -> "711110"), spaces may be lost by the OCR.
    block = next(
        (
            re.sub(r"[^\d-]", "", line[m.end() :].translate(NUMERIC))
            for line in lines
            if (m := BLOCK.search(line))
        ),
        None,
    )
    for line in lines:
        label = LABEL.search(line)
        if not label:
            continue
        rest = line[label.end() :].translate(NUMERIC)
        rest = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", rest)
        candidates: list[tuple[str, ...]] = []
        if strict := F3_FORMAT.match(re.sub(r"[^\d.-]", "", rest)):
            candidates.append(strict.groups())
        if len(decimals := DECIMAL.findall(rest)) >= 3:
            candidates.append(tuple(decimals[:3]))
        if not candidates:
            continue
        if block is not None:
            for candidate in candidates:
                for combo in itertools.product(*(_variants(t) for t in candidate)):
                    values = tuple(float(v) for v in combo)
                    if "".join(str(math.floor(v)) for v in values) == block:
                        return values, True  # type: ignore[return-value]
        return tuple(float(v) for v in candidates[0]), False  # type: ignore[return-value]
    return None, False


def _variants(token: str) -> list[str]:
    """The token, and the token without a leading separator misread as 7 or 1 ("/73.0")."""
    sign, digits = ("-", token[1:]) if token.startswith("-") else ("", token)
    out = [token]
    if digits[0] in "71" and digits.index(".") > 1:
        out.append(sign + digits[1:])
    return out
