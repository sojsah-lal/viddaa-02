"""Render the 1024x1024 app icon (docs/icon.png) in the same style as the videos."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame  # noqa: E402

from engine import common as C  # noqa: E402

S = 1024
OUT = Path(__file__).resolve().parent.parent / "docs" / "icon.png"


def main():
    pygame.init()
    surf = pygame.Surface((S, S))
    surf.fill(C.BG)
    cx, cy = S / 2, S / 2
    colors = [C.hex_to_rgb(h) for h in ("#FF4D6D", "#FFD24D", "#7CFF4D", "#4DD2FF")]
    gap = math.radians(55)
    for i, (r, col) in enumerate(zip((150, 230, 310, 390), colors)):
        a = math.radians(-90 + i * 70)
        C.aa_arc(surf, col, cx, cy, r, 30, a + gap / 2, a + 2 * math.pi - gap / 2)
    bx, by = cx + 60, cy + 40
    for back in range(6, 0, -1):
        C.aa_circle(surf, (*C.lighten(colors[0], 0.2), int(120 * (1 - back / 7))), bx - back * 22, by + back * 14,
                    52 * (1 - back / 10))
    C.aa_circle(surf, (*colors[0], 90), bx, by, 76)
    C.aa_circle(surf, C.WHITE, bx, by, 58)
    pygame.image.save(surf, str(OUT))
    print(OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
