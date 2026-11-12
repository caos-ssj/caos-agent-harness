"""CAOS semantic terminal palette (`night`, `ember`, `mono`) with 8 curses pairs and NO_COLOR fallback."""
from __future__ import annotations

import os

SKINS = {
    "night": {   # copper obsidian: the same palette as the dashboard and the CLI (`style.py`)
        "amber": (209, "#EE9A3E"),
        "champagne": (180, "#E2B076"),
        "bone": (255, "#F5F2EC"),
        "silver": (249, "#BBB3A8"),
        "dim": (245, "#948C81"),
        "sage": (78, "#6BC78E"),
        "coral": (167, "#E87066"),
        "steel": (110, "#7FA6D6"),
    },
    "ember": {
        "amber": (208, "#FF8700"),
        "champagne": (222, "#FFD7AF"),
        "bone": (252, "#D0D0D0"),
        "silver": (246, "#949494"),
        "dim": (243, "#767676"),
        "sage": (114, "#87D787"),
        "coral": (203, "#FF5F5F"),
        "steel": (111, "#87AFFF"),
    },
    "mono": None,
}

PAIR_KEYS = ("amber", "champagne", "bone", "silver", "dim", "sage", "coral", "steel")


def apply_curses_skin(curses_mod, skin_name: str) -> dict[str, int]:
    """Configures up to 8 semantic curses color pairs or clean monochrome attributes."""
    attrs = {
        "": curses_mod.A_NORMAL,
        "bone": curses_mod.A_BOLD,
        "bold": curses_mod.A_BOLD,
        "dim": curses_mod.A_DIM,
        "silver": curses_mod.A_NORMAL,
        "amber": curses_mod.A_BOLD,
        "amberb": curses_mod.A_BOLD,
        "champagne": curses_mod.A_BOLD,
        "sage": curses_mod.A_NORMAL,
        "sageb": curses_mod.A_BOLD,
        "coral": curses_mod.A_BOLD,
        "coralb": curses_mod.A_BOLD,
        "steel": curses_mod.A_NORMAL,
        "steelb": curses_mod.A_BOLD,
        "rev": curses_mod.A_REVERSE,
        "plan_bar": curses_mod.A_BOLD,
        "act_bar": curses_mod.A_REVERSE | curses_mod.A_BOLD,
    }
    pal = SKINS.get(skin_name)
    color = bool(
        pal
        and curses_mod.has_colors()
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM") != "dumb"
    )
    if not color:
        return attrs

    try:
        curses_mod.use_default_colors()
        bg = -1
    except curses_mod.error:
        bg = curses_mod.COLOR_BLACK

    hi = curses_mod.COLORS >= 256
    fallback_8 = {
        "amber": curses_mod.COLOR_YELLOW,
        "champagne": curses_mod.COLOR_YELLOW,
        "bone": curses_mod.COLOR_WHITE,
        "silver": curses_mod.COLOR_WHITE,
        "dim": curses_mod.COLOR_WHITE,
        "sage": curses_mod.COLOR_GREEN,
        "coral": curses_mod.COLOR_RED,
        "steel": curses_mod.COLOR_CYAN,
    }
    pair_ids: dict[str, int] = {}
    for idx, key in enumerate(PAIR_KEYS, 1):
        fg = pal[key][0] if hi else fallback_8[key]
        try:
            curses_mod.init_pair(idx, fg, bg)
            pair_ids[key] = curses_mod.color_pair(idx)
        except curses_mod.error:
            pair_ids[key] = 0

    attrs.update({
        "": pair_ids.get("bone", curses_mod.A_NORMAL),
        "bone": pair_ids.get("bone", 0) | curses_mod.A_BOLD,
        "bold": pair_ids.get("bone", 0) | curses_mod.A_BOLD,
        "silver": pair_ids.get("silver", 0),
        "dim": pair_ids.get("dim", 0) | (curses_mod.A_DIM if not hi else 0),
        "amber": pair_ids.get("amber", 0),
        "amberb": pair_ids.get("amber", 0) | curses_mod.A_BOLD,
        "champagne": pair_ids.get("champagne", 0) | curses_mod.A_BOLD,
        "sage": pair_ids.get("sage", 0),
        "sageb": pair_ids.get("sage", 0) | curses_mod.A_BOLD,
        "coral": pair_ids.get("coral", 0),
        "coralb": pair_ids.get("coral", 0) | curses_mod.A_BOLD,
        "steel": pair_ids.get("steel", 0),
        "steelb": pair_ids.get("steel", 0) | curses_mod.A_BOLD,
        "plan_bar": pair_ids.get("steel", 0) | curses_mod.A_BOLD,
        "act_bar": pair_ids.get("amber", 0) | curses_mod.A_BOLD,
    })
    return attrs


def draw_rows(scr, rows: list, attrs: dict[str, int], cursor: tuple[int, int] | None, w: int, h: int, curses_mod) -> None:
    """Renders composed styled rows cleanly inside terminal bounds."""
    for y, row in enumerate(rows[:h]):
        x = 0
        for text, sty in row:
            if x >= w - 1:
                break
            try:
                scr.addstr(y, x, text[: w - 1 - x], attrs.get(sty, 0))
            except curses_mod.error:
                pass
            x += len(text)
    if cursor:
        try:
            scr.move(*cursor)
        except curses_mod.error:
            pass
    curses_mod.curs_set(1 if cursor else 0)
