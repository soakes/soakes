#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["fonttools==4.67.0", "brotli==1.2.0", "uharfbuzz==0.56.3"]
# ///
"""Build the profile README graphics in assets/.

    profile-banner.svg    name, role and focus areas, with a terminal card that dry-runs the
                          site playbook and comes back with nothing to change
    profile-journey.svg   ten roles since 2000 as stops on one route over the Earth's horizon
    profile-bring.svg     the four oakes.me.uk stats drawn to scale, and the six things I bring
    profile-stack.svg     the oakes.me.uk Stack orbit, with the whole toolbox on the Earth below
    profile-principles.svg  the five engineering principles as stages on one pipeline
    project-<name>.svg    a card for each public project, which the README links to its repo

They share the oakes.me.uk colours, a seeded starfield and, bar the stats and the cards, the
dotted Earth from the soakes/cv README hero with London lit, so the profile, the CV and the site
look like one thing. The facts come from soakes/cv data/cv.yml (stats, journey eras,
stack_orbit, what_i_bring, the projects and the role dates); when those change there, change
them here and rebuild.

land.ts beside this script is a verbatim copy of soakes/cv src/lib/site/land.ts, the land bitmap
the site's globe is drawn from. icons.json holds the simple-icons paths for the Stack orbit
(CC0-1.0, version recorded in the file); the logos keep their brand colours.

The banner's terminal types itself out with CSS on a loop: each command is typed a character at
a time by stepping a cover off it, and its output appears once it's run. With reduced motion, or
wherever animation doesn't run, every graphic shows its finished state instead.

Edit the copy, data or layout here and run `make readme-graphics` rather than editing the SVGs.
Text is measured with HarfBuzz on the embedded Inter, so paragraphs wrap where a browser would
wrap them and anything that won't fit stops the build. Inter and JetBrains Mono (SIL Open Font License 1.1)
are the Google Fonts builds kept on assets.netspeedy.io and pinned by checksum in FAMILIES, subset
here to the characters each SVG renders. fontTools is pinned too, so a rebuild with the same copy
gives the same bytes. It runs under `uv run`, and the first run needs network access to download
the fonts.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import random
import re
import urllib.request
import xml.etree.ElementTree as ET
from functools import cache
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
import uharfbuzz as hb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ASSETS = ROOT / "assets"
LAND = HERE / "land.ts"
ICONS = HERE / "icons.json"
WIDTH = 1200
# assets.netspeedy.io's Cloudflare zone turns away urllib's default user agent.
USER_AGENT = "netspeedy-readme-hero"

# oakes.me.uk colour tokens (soakes/cv src/styles/site.css).
BG = "#060B13"
INK = "#F1F5FA"
INK_2 = "#B5C0CD"
INK_3 = "#808D9E"
CYAN = "#1FC7FF"
CYAN_2 = "#8FE4FF"
AMBER = "#FCBB39"
AMBER_2 = "#FDE1A7"
GREEN = "#3CD788"
# Terminal surfaces. The body is a flat colour because typing works by stepping a cover of the
# same colour off each command.
TERM_BODY = "#0A1019"
TERM_BAR = "#0F1622"
TERM_EDGE = "#223047"

# Fonts: css class -> (source font, its sha256, weight range, embedded family name). The
# sources are the Google Fonts builds of Inter 4.001 and JetBrains Mono 2.211, kept on
# assets.netspeedy.io and cached after the first download. A new version goes up there
# under a new filename, so these files never change.
FONT_HOST = "https://assets.netspeedy.io/versioned/fonts"
FONT_CACHE = Path.home() / ".cache" / "netspeedy-fonts"
FAMILIES = {
    "sans": (
        "inter-opsz-wght.4.001.ttf",
        "29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031",
        "400 800",
        "Profile Sans",
    ),
    "mono": (
        "jetbrains-mono-wght.2.211.ttf",
        "48715a42ec242c21e9f02692891e147d022299a52e48d5e413e1a942193ffeda",
        "400 700",
        "Profile Mono",
    ),
}
FONT_CSS = (
    ".sans{font-family:'Profile Sans',-apple-system,'Segoe UI','Helvetica Neue',Arial,"
    "sans-serif;font-optical-sizing:auto;}"
    ".mono{font-family:'Profile Mono','SF Mono',Menlo,Consolas,monospace;}"
)
TWINKLE_CSS = (
    ".tw{animation:tw 5.2s ease-in-out infinite;transform-box:fill-box;transform-origin:center}"
    ".tw1{animation-duration:6.4s}.tw2{animation-duration:4.6s}.tw3{animation-duration:7.3s}"
    "@keyframes tw{0%,100%{opacity:.85}50%{opacity:.15}}"
)

COPY_X = 64.0
COPY_RIGHT = 660.0  # nothing in a copy column may run past this

# Starfield: seeded, so rebuilding gives the same sky. No star sits behind copy or a scene.
STAR_SEED = 5
STARS = 120
TWINKLING = 18

# The Earth, from the soakes/cv README hero: an orthographic view of the land lattice, centred
# on the cv hero's (9, 27) unless a graphic turns it. Each graphic sizes it and says where
# London lands.
LONDON = (51.507, -0.128)
STEP = 0.66  # land lattice spacing in degrees
CV_VIEW = (9.0, 27.0)
HORIZON_VIEW = (-18.5, -0.13)  # London near the top of the disc, so it reads as a horizon

# soakes/cv data/cv.yml: public_site.stats, journey.eras, stack_orbit and experience start dates.
STATS = {
    "years": ("25+", "YEARS IN PRODUCTION"),
    "vms": ("2,500", "VMS UNDER AUTOMATION"),
    "zones": ("300+", "DNS ZONES MANAGED"),
    "roles": ("40+", "ANSIBLE ROLES AUTHORED"),
}
ROLES = [2000.83, 2002.58, 2004.25, 2009.17, 2011.25, 2015.17, 2017.58, 2018.83, 2024.75, 2025.83]
ERAS = [
    (2000.83, "2000", ["ISP and telecoms", "foundations"], "start"),
    (2011.25, "2011", ["Automation, networks", "and build platforms"], "middle"),
    (2024.75, "2024", ["Platforms, automation", "and AI infrastructure"], "middle"),
]
NOW = 2026.9
ORBIT_CORE = ("Linux", "linux")
ORBIT_INNER = [
    ("Ansible", "ansible", "#ff4747"),
    ("Docker", "docker", "#2496ed"),
    ("Terraform", "terraform", "#9b6dff"),
    ("Kubernetes", "kubernetes", "#5a8ff0"),
    ("Python", "python", "#5a9bd8"),
    ("Go", "go", "#00add8"),
]
ORBIT_OUTER = [
    ("Debian", "debian", "#e2445f"),
    ("GitHub Actions", "githubactions", "#3d93ff"),
    ("Ubuntu", "ubuntu", "#e95420"),
    ("Packer", "packer", "#02a8ef"),
    ("Red Hat", "redhat", "#ff4242"),
    ("GitLab CI", "gitlab", "#fc6d26"),
    ("Bash", "gnubash", "#5cbf2e"),
    ("Proxmox", "proxmox", "#e57000"),
    ("Puppet", "puppet", "#ffae1a"),
    ("Jenkins", "jenkins", "#e2604f"),
    ("Nutanix", "nutanix", "#4a8be6"),
    ("Nginx", "nginx", "#22b35c"),
]


# Fonts


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def font_source(name: str, sha256: str) -> bytes:
    """A pinned source font from FONT_HOST, checked against its sha256 and cached."""
    cached = FONT_CACHE / name
    if cached.exists():
        data = cached.read_bytes()
        if hashlib.sha256(data).hexdigest() == sha256:
            return data
    data = fetch(f"{FONT_HOST}/{name}")
    if hashlib.sha256(data).hexdigest() != sha256:
        raise SystemExit(f"{FONT_HOST}/{name} doesn't match its pinned sha256")
    FONT_CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def subset_font(source: bytes, text: str) -> bytes:
    """The variable font cut down to the given characters, as woff2.

    Every axis is kept: trimming them with fontTools' instancer moved the headline's
    pixels. The source's head timestamp is kept too, so the same text always gives the
    same bytes.
    """
    font = TTFont(io.BytesIO(source), recalcTimestamp=False)
    options = subset.Options()
    options.hinting = False
    subsetter = subset.Subsetter(options)
    subsetter.populate(text=text)
    subsetter.subset(font)
    font.flavor = "woff2"
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def collect_chars(svg: str) -> dict[str, set[str]]:
    """Characters rendered by each font class, inherited through groups."""
    chars: dict[str, set[str]] = {name: set() for name in FAMILIES}

    def family_of(element: ET.Element, inherited: str | None) -> str | None:
        for cls in (element.get("class") or "").split():
            if cls in FAMILIES:
                return cls
        return inherited

    def walk(element: ET.Element, inherited: str | None, in_text: bool) -> None:
        tag = element.tag.split("}")[-1]
        family = family_of(element, inherited)
        if tag in ("style", "title", "desc", "script"):
            return
        is_text = in_text or tag in ("text", "tspan", "textPath")
        if is_text and tag in ("text", "tspan", "textPath") and element.text:
            if family is None:
                raise SystemExit(f"text without a font class: {element.text!r}")
            chars[family].update(element.text)
        for child in element:
            walk(child, family, is_text)
            if is_text and child.tail and child.tail.strip():
                chars[family or "sans"].update(child.tail)

    walk(ET.fromstring(svg), None, False)
    return chars


def font_faces(svg: str) -> str:
    """One @font-face per family, subset to exactly the characters the SVG renders."""
    chars = collect_chars(svg)
    faces = []
    for cls, (name, sha256, weights, local) in FAMILIES.items():
        used = chars[cls]
        if not used:
            continue
        text = "".join(sorted((used - set("\n\t\r")) | {" "}))
        data = base64.b64encode(subset_font(font_source(name, sha256), text)).decode()
        faces.append(
            f"@font-face{{font-family:'{local}';font-weight:{weights};"
            f"font-style:normal;src:url(data:font/woff2;base64,{data}) "
            "format('woff2');}"
        )
    return "".join(faces)


@cache
def shaper(weight: float, size: float) -> tuple[hb.Font, int]:
    name, sha256, _, _ = FAMILIES["sans"]
    face = hb.Face(font_source(name, sha256))
    font = hb.Font(face)
    # font-optical-sizing:auto follows the px size, within Inter's 14..32 range.
    font.set_variations({"wght": weight, "opsz": min(max(size, 14), 32)})
    return font, face.upem


def text_width(text: str, size: float, weight: float = 400, spacing: float = 0.0) -> float:
    """The advance of Inter text as a browser lays it out: shaped with kerning, plus CSS
    letter-spacing after every character."""
    if not text:
        return 0.0
    font, upem = shaper(weight, size)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf, {"kern": True, "liga": True, "calt": True})
    return sum(pos.x_advance for pos in buf.glyph_positions) * size / upem + spacing * len(text)


def wrap(text: str, size: float, width: float, weight: float = 400) -> list[str]:
    """Inter text broken into lines no wider than `width`, a word at a time."""
    lines = [""]
    for word in text.split():
        trial = f"{lines[-1]} {word}".strip()
        if lines[-1] and text_width(trial, size, weight) > width:
            lines.append(word)
        else:
            lines[-1] = trial
    if any(text_width(line, size, weight) > width for line in lines):
        raise SystemExit(f"a word in {text!r} is wider than {width:.0f}px")
    return lines


# Small helpers


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def num(value: float) -> str:
    """One decimal place, without a trailing .0."""
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def mono_width(chars: int, size: float, spacing: float = 0.0) -> float:
    """JetBrains Mono advances exactly 0.6 em; letter-spacing applies per glyph."""
    return chars * (size * 0.6 + spacing)


def gradient(kind: str, attrs: str, stops: list[tuple[str, str, str]]) -> list[str]:
    lines = [f"    <{kind} {attrs}>"]
    for offset, colour, opacity in stops:
        alpha = f' stop-opacity="{opacity}"' if opacity else ""
        lines.append(f'      <stop offset="{offset}" stop-color="{colour}"{alpha} />')
    return [*lines, f"    </{kind}>"]


def pct(seconds: float, loop: float) -> str:
    return f"{min(max(seconds / loop * 100, 0), 100):.2f}%"


def poly(points: list[tuple[float, float]]) -> str:
    return "M" + "L".join(f"{num(x)} {num(y)}" for x, y in points)


Box = tuple[float, float, float, float]


# The Earth


@cache
def land_bitmap() -> tuple[bytes, int, int]:
    """Decode the run-length encoded equirectangular land bitmap in land.ts."""
    source = LAND.read_text(encoding="utf-8")
    width = int(re.search(r"LAND_WIDTH = (\d+)", source).group(1))
    height = int(re.search(r"LAND_HEIGHT = (\d+)", source).group(1))
    raw = base64.b64decode(re.search(r'LAND_RLE =\s*"([^"]+)"', source).group(1))
    bits = bytearray(width * height)
    pos = 0
    for row in range(height):
        col = 0
        land = False
        while col < width and pos < len(raw):
            run = raw[pos]
            pos += 1
            if land and run:
                start = row * width + col
                bits[start : start + run] = b"\x01" * run
            col += run
            land = not land
    return bytes(bits), width, height


def is_land(lat: float, lon: float) -> bool:
    bits, width, height = land_bitmap()
    row = min(height - 1, max(0, int((90 - lat) / 180 * height)))
    col = int((lon + 180) / 360 * width) % width
    return bits[row * width + col] == 1


@cache
def lattice() -> tuple[tuple[float, float], ...]:
    """Equal-area land lattice: rings of latitude, alternate rings offset half a step."""
    points = []
    ring = 0
    lat = -90 + STEP / 2
    while lat < 90:
        count = max(1, round(360 * math.cos(math.radians(lat)) / STEP))
        offset = (ring & 1) * 0.5
        for k in range(count):
            lon = -180 + (k + offset) * 360 / count
            if is_land(lat, lon):
                points.append((lat, lon))
        lat += STEP
        ring += 1
    return tuple(points)


class Earth:
    """The dotted Earth at a given radius, turned to `view` and placed so London is at `london`."""

    def __init__(self, radius: float, london: tuple[float, float], view: tuple[float, float]):
        self.radius = radius
        self.lon0 = view[1]
        self.sin0, self.cos0 = math.sin(math.radians(view[0])), math.cos(math.radians(view[0]))
        vx, vy, _ = self.vec(*LONDON)
        self.london = london
        self.cx, self.cy = london[0] - radius * vx, london[1] + radius * vy

    def vec(self, lat: float, lon: float) -> tuple[float, float, float]:
        """Orthographic view; z > 0 faces the viewer."""
        phi, dlon = math.radians(lat), math.radians(lon - self.lon0)
        x = math.cos(phi) * math.sin(dlon)
        y = self.cos0 * math.sin(phi) - self.sin0 * math.cos(phi) * math.cos(dlon)
        z = self.sin0 * math.sin(phi) + self.cos0 * math.cos(phi) * math.cos(dlon)
        return x, y, z

    def screen(self, vec: tuple[float, float, float]) -> tuple[float, float]:
        return self.cx + self.radius * vec[0], self.cy - self.radius * vec[1]

    def dots(self, height: float, hidden: list[Box]) -> str:
        """Land dots in four depth bands, each one path of round-capped stubs. Dots off the
        card or under something opaque are left out."""
        bands: dict[int, list[tuple[float, float]]] = {0: [], 1: [], 2: [], 3: []}
        for lat, lon in lattice():
            vec = self.vec(lat, lon)
            if vec[2] <= 0.02:
                continue
            x, y = self.screen(vec)
            if not (-4 <= x <= WIDTH + 4 and -4 <= y <= height + 4):
                continue
            if any(x0 + 2 <= x <= x1 - 2 and y0 + 2 <= y <= y1 - 2 for x0, y0, x1, y1 in hidden):
                continue
            band = 0 if vec[2] < 0.22 else 1 if vec[2] < 0.42 else 2 if vec[2] < 0.62 else 3
            bands[band].append((x, y))
        style = {0: (0.24, 1.2), 1: (0.42, 1.4), 2: (0.6, 1.55), 3: (0.76, 1.65)}
        paths = []
        for band, points in bands.items():
            if not points:
                continue
            points.sort(key=lambda p: (round(p[1]), p[0]))
            moves = []
            px = py = 0.0
            for x, y in points:
                # "h.01", not "h0": some renderers drop zero-length subpaths.
                moves.append(f"m{num(x - px)} {num(y - py)}h.01")
                px, py = x + 0.01, y
            opacity, width = style[band]
            paths.append(
                f'<path d="M0 0{"".join(moves)}" fill="none" stroke="#D3E4F4" '
                f'stroke-opacity="{opacity}" stroke-width="{width}" stroke-linecap="round" />'
            )
        return "".join(paths)

    def graticule(self) -> str:
        """Meridians every 30 degrees and three parallels, visible face only."""
        paths = []

        def line(points: list[tuple[float, float]]) -> None:
            segments, current = [], []
            for lat, lon in points:
                vec = self.vec(lat, lon)
                if vec[2] > 0:
                    current.append(self.screen(vec))
                elif current:
                    segments.append(current)
                    current = []
            if current:
                segments.append(current)
            paths.extend(poly(s) for s in segments if len(s) > 1)

        for lon in range(-180, 180, 30):
            line([(lat, lon) for lat in range(-84, 85, 3)])
        for lat in (0, 30, 60):
            line([(lat, lon) for lon in range(-180, 181, 3)])
        return (
            f'<path d="{"".join(paths)}" fill="none" stroke="{CYAN_2}" stroke-opacity="0.07" '
            'stroke-width="0.8" />'
        )

    def draw(self, height: float, hidden: list[Box]) -> tuple[list[str], list[str], str]:
        """Defs, elements and CSS: atmosphere, body, land and graticule, rim, and London lit if
        it's on the card."""
        r, cx, cy = self.radius, self.cx, self.cy
        lx, ly = self.london
        rim = r / (r + 70)
        defs = [
            *gradient(
                "radialGradient",
                f'id="atmo" gradientUnits="userSpaceOnUse" cx="{num(cx)}" cy="{num(cy)}" '
                f'r="{num(r + 70)}"',
                [
                    (f"{rim - 0.004:.4f}", CYAN, "0"),
                    (f"{rim:.4f}", CYAN, "0.34"),
                    (f"{rim + 0.03:.4f}", CYAN, "0.1"),
                    ("1", CYAN, "0"),
                ],
            ),
            *gradient(
                "radialGradient",
                f'id="earth" gradientUnits="userSpaceOnUse" cx="{num(cx - 120)}" '
                f'cy="{num(cy - 260)}" r="{num(r + 40)}"',
                [("0", "#0E2036", ""), ("0.62", "#081322", ""), ("0.93", "#0A1B2E", ""),
                 ("1", "#103551", "")],
            ),
            f'    <clipPath id="globeClip"><circle cx="{num(cx)}" cy="{num(cy)}" r="{num(r)}" />'
            "</clipPath>",
        ]
        els = [
            f'    <circle class="rim" cx="{num(cx)}" cy="{num(cy)}" r="{num(r + 70)}" '
            'fill="url(#atmo)" />',
            f'    <circle cx="{num(cx)}" cy="{num(cy)}" r="{num(r)}" fill="url(#earth)" />',
            f'    <g clip-path="url(#globeClip)">{self.graticule()}{self.dots(height, hidden)}</g>',
            f'    <circle cx="{num(cx)}" cy="{num(cy)}" r="{num(r)}" fill="none" stroke="{CYAN}" '
            'stroke-opacity="0.55" stroke-width="1.3" />',
        ]
        css = (
            ".rim{animation:rim 9s ease-in-out infinite}"
            "@keyframes rim{0%,100%{opacity:.75}50%{opacity:1}}"
        )
        if ly - 20 < height:
            defs += gradient(
                "radialGradient",
                'id="londonGlow" cx="0.5" cy="0.5" r="0.5"',
                [("0", AMBER, "0.75"), ("0.35", AMBER, "0.22"), ("1", AMBER, "0")],
            )
            els += [
                f'    <circle cx="{num(lx)}" cy="{num(ly)}" r="20" fill="url(#londonGlow)" />',
                f'    <circle class="lon" cx="{num(lx)}" cy="{num(ly)}" r="3.4" fill="none" '
                f'stroke="{AMBER}" stroke-width="1.1" />',
                f'    <circle class="lon lon2" cx="{num(lx)}" cy="{num(ly)}" r="3.4" fill="none" '
                f'stroke="{AMBER}" stroke-width="1.1" />',
                f'    <circle cx="{num(lx)}" cy="{num(ly)}" r="3.6" fill="{AMBER_2}" />',
            ]
            css += (
                ".lon{transform-box:fill-box;transform-origin:center;opacity:0;"
                "animation:lon 3.6s ease-out infinite}.lon2{animation-delay:-1.8s}"
                "@keyframes lon{0%{opacity:.85;transform:scale(1)}"
                "100%{opacity:0;transform:scale(5.5)}}"
            )
        return defs, els, css


# Ground


def stars(height: float, free: list[Box]) -> list[str]:
    rng = random.Random(STAR_SEED)
    placed, tries = [], 0
    while len(placed) < STARS and tries < STARS * 60:
        tries += 1
        x, y = rng.uniform(8, WIDTH - 8), rng.uniform(8, height - 8)
        if any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in free):
            continue
        radius = rng.choice([0.55, 0.6, 0.7, 0.8, 0.9, 1.0, 1.15])
        placed.append((x, y, radius, rng.uniform(0.18, 0.6)))
    twinkling = "".join(
        f'<circle class="tw tw{i % 4}" cx="{num(x)}" cy="{num(y)}" r="{num(r + 0.25)}" '
        f'fill="#DDF2FF" opacity="{o + 0.25:.2f}" '
        f'style="animation-delay:-{rng.uniform(0, 6):.1f}s" />'
        for i, (x, y, r, o) in enumerate(placed[:TWINKLING])
    )
    plain = "".join(
        f'<circle cx="{num(x)}" cy="{num(y)}" r="{num(r)}" opacity="{o:.2f}" />'
        for x, y, r, o in placed[TWINKLING:]
    )
    return [f'    <g fill="#CFE6FF">{plain}</g>', f"    <g>{twinkling}</g>"]


def ground(
    height: float,
    free: list[Box],
    earth: Earth | None = None,
    hidden: list[Box] | None = None,
    glow: Box | None = None,
) -> tuple[list[str], list[str], str]:
    """The card every graphic sits on: the heroes' sky (navy, an indigo nebula top left, a cyan
    one bottom right, seeded stars kept off `free`), then either the Earth or a soft glow behind
    the scene. Returns defs, body and the CSS it animates."""
    defs = [
        *gradient(
            "linearGradient",
            'id="ground" x1="0" y1="0" x2="0.35" y2="1"',
            [("0", "#081020", ""), ("0.55", BG, ""), ("1", "#0B1424", "")],
        ),
        *gradient(
            "radialGradient",
            'id="nebIndigo" cx="0.5" cy="0.5" r="0.5"',
            [("0", "#3B4BB8", "0.32"), ("1", "#3B4BB8", "0")],
        ),
        *gradient(
            "radialGradient",
            'id="nebCyan" cx="0.5" cy="0.5" r="0.5"',
            [("0", "#0A9FE0", "0.34"), ("1", "#0A9FE0", "0")],
        ),
        f'    <clipPath id="frame"><rect x="1" y="1" width="{WIDTH - 2}" height="{num(height - 2)}" '
        'rx="20" /></clipPath>',
    ]
    scene = [
        f'    <rect width="{WIDTH}" height="{num(height)}" fill="url(#ground)" />',
        '    <ellipse cx="190" cy="-30" rx="540" ry="250" fill="url(#nebIndigo)" />',
        f'    <ellipse cx="1040" cy="{num(height)}" rx="580" ry="280" fill="url(#nebCyan)" '
        'opacity="0.55" />',
        *stars(height, free),
    ]
    css = TWINKLE_CSS
    if earth:
        e_defs, e_els, e_css = earth.draw(height, hidden or [])
        defs += e_defs
        scene += e_els
        css += e_css
    if glow:
        x0, y0, x1, y1 = glow
        defs += gradient(
            "radialGradient",
            'id="screenGlow" cx="0.5" cy="0.5" r="0.5"',
            [("0", "#1FA8E8", "0.16"), ("1", "#1FA8E8", "0")],
        )
        scene.append(
            f'    <ellipse cx="{num((x0 + x1) / 2)}" cy="{num((y0 + y1) / 2)}" '
            f'rx="{num((x1 - x0) * 0.75)}" ry="{num((y1 - y0) * 0.85)}" fill="url(#screenGlow)" />'
        )
    body = [
        '  <g clip-path="url(#frame)">',
        *scene,
        "  </g>",
        f'  <rect x="0.75" y="0.75" width="{WIDTH - 1.5}" height="{num(height - 1.5)}" rx="20" '
        'fill="none" stroke="#1A2638" stroke-width="1.5" />',
    ]
    return defs, body, css


def document(
    height: float,
    title: str,
    desc: str,
    defs: list[str],
    css: str,
    body: list[str],
    width: float = WIDTH,
) -> str:
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {num(width)} {num(height)}" role="img" '
        'aria-labelledby="title desc">',
        f'  <title id="title">{esc(title)}</title>',
        f'  <desc id="desc">{esc(desc)}</desc>',
        "  <defs>",
        "    <style>",
        "      /* Inter and JetBrains Mono, SIL Open Font License 1.1, subset to the glyphs used "
        "here. */",
        "      __FONT_FACES__",
        f"      {FONT_CSS}",
        "      .live{animation:live 2.4s ease-in-out infinite}"
        "@keyframes live{0%,100%{opacity:1}50%{opacity:.35}}",
        f"      {css}",
        "      @media (prefers-reduced-motion: reduce){",
        "        *{animation:none !important}",
        "      }",
        "    </style>",
        *defs,
        "  </defs>",
        *body,
        "</svg>",
    ]
    return "\n".join(lines) + "\n"


# Copy column


def copy_defs() -> list[str]:
    return [
        *gradient(
            "linearGradient",
            'id="nameG" x1="0" y1="0" x2="1" y2="0"',
            [("0", "#FFFFFF", ""), ("1", "#D5E6F5", "")],
        ),
        *gradient(
            "linearGradient",
            'id="roleG" x1="0" y1="0" x2="1" y2="0"',
            [("0", CYAN_2, ""), ("0.55", CYAN, ""), ("1", "#2BA4F0", "")],
        ),
    ]


def pill(
    y: float,
    label: str,
    size: float = 11.5,
    x: float = COPY_X,
    dot: str = GREEN,
    live: bool = True,
) -> list[str]:
    """A mono label in a rounded pill with a dot, pulsing when it's `live`."""
    width = mono_width(len(label), size, 1.5) - 1.5 + 40
    pulse = ' class="live"' if live else ""
    return [
        f'  <rect x="{num(x)}" y="{num(y)}" width="{num(width)}" height="28" rx="14" '
        f'fill="#0E1726" fill-opacity="0.9" stroke="{TERM_EDGE}" />',
        f'  <circle{pulse} cx="{num(x + 16)}" cy="{num(y + 14)}" r="3.4" fill="{dot}" />',
        f'  <text class="mono" x="{num(x + 28)}" y="{num(y + 18.2)}" font-size="{size}" '
        f'letter-spacing="1.5" fill="{INK_2}">{esc(label)}</text>',
    ]


def copy_block(
    label: str, first: str, second: str, lead: list[str], y: float, right: float = COPY_RIGHT
) -> list[str]:
    """The banner's copy treatment a size down: a pill, a one- or two-line heading, a lead."""
    widths = [text_width(first, 40, 800, -1.2), text_width(second, 40, 800, -1.2)]
    widths += [text_width(text, 16) for text in lead]
    if COPY_X + max(widths) > right:
        raise SystemExit(f"'{first}' block runs past the copy column")
    els = [
        *pill(y, label),
        f'  <text class="sans" x="{num(COPY_X - 2)}" y="{num(y + 84)}" font-size="40" '
        f'font-weight="800" letter-spacing="-1.2" fill="url(#nameG)">{esc(first)}</text>',
    ]
    if second:
        els.append(
            f'  <text class="sans" x="{num(COPY_X - 2)}" y="{num(y + 130)}" font-size="40" '
            f'font-weight="800" letter-spacing="-1.2" fill="url(#roleG)">{esc(second)}</text>'
        )
    top = y + (172 if second else 124)
    for i, text in enumerate(lead):
        els.append(
            f'  <text class="sans" x="{num(COPY_X)}" y="{num(top + 24 * i)}" font-size="16" '
            f'fill="{INK_2}">{esc(text)}</text>'
        )
    return els


# Terminal window and typing (the banner's card)


def window(x: float, y: float, w: float, h: float, title: str) -> tuple[list[str], list[str]]:
    """A terminal window: its defs (including the `screen` clip for the body below the title
    bar) and its frame."""
    bar = 36
    defs = [
        *gradient(
            "linearGradient",
            f'id="edge" gradientUnits="userSpaceOnUse" x1="{num(x)}" y1="0" x2="{num(x + w)}" '
            'y2="0"',
            [("0", CYAN, "0"), ("0.2", CYAN, "0.9"), ("0.8", AMBER, "0.9"), ("1", AMBER, "0")],
        ),
        f'    <clipPath id="win"><rect x="{num(x)}" y="{num(y)}" width="{num(w)}" '
        f'height="{num(h)}" rx="14" /></clipPath>',
        # Inset from the frame, so a cover stepping right never paints over the window's edge.
        f'    <clipPath id="screen"><rect x="{num(x + 1.5)}" y="{num(y + bar + 1)}" '
        f'width="{num(w - 3)}" height="{num(h - bar - 2.5)}" rx="12.5" /></clipPath>',
        '    <filter id="lift" x="-10%" y="-15%" width="120%" height="140%">'
        '<feDropShadow dx="0" dy="16" stdDeviation="18" flood-color="#000" flood-opacity="0.45" />'
        "</filter>",
    ]
    # The shadow is its own layer: run through the filter, the body's colour shifts a shade and
    # the typing covers would show against it.
    els = [
        f'  <rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" rx="14" '
        f'fill="{TERM_BODY}" filter="url(#lift)" />',
        f'  <rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" rx="14" '
        f'fill="{TERM_BODY}" />',
        '  <g clip-path="url(#win)">',
        f'    <rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{bar}" fill="{TERM_BAR}" />',
        f'    <path d="M{num(x)} {num(y + bar + 0.5)}H{num(x + w)}" stroke="{TERM_EDGE}" />',
        f'    <rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="1.5" fill="url(#edge)" />',
        "  </g>",
        f'  <rect x="{num(x + 0.5)}" y="{num(y + 0.5)}" width="{num(w - 1)}" height="{num(h - 1)}" '
        f'rx="13.5" fill="none" stroke="{TERM_EDGE}" />',
    ]
    for i, colour in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        els.append(
            f'  <circle cx="{num(x + 20 + 19 * i)}" cy="{num(y + bar / 2)}" r="5.5" '
            f'fill="{colour}" fill-opacity="0.88" />'
        )
    els.append(
        f'  <text class="mono" x="{num(x + w / 2)}" y="{num(y + bar / 2 + 4)}" '
        f'text-anchor="middle" font-size="11.5" fill="{INK_3}">{esc(title)}</text>'
    )
    return defs, els


def tick(x: float, y: float, cw: float, size: float, colour: str) -> str:
    """A check mark drawn in one mono cell (JetBrains Mono has no U+2713)."""
    return (
        f'<path d="M{num(x + cw * 0.12)} {num(y - size * 0.34)}l{num(cw * 0.28)} '
        f'{num(size * 0.26)} {num(cw * 0.52)} -{num(size * 0.56)}" fill="none" '
        f'stroke="{colour}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />'
    )


def span(text: str, colour: str) -> str:
    return f'<tspan fill="{colour}">{esc(text)}</tspan>'


def session(
    rows: list[tuple],
    x: float,
    y: float,
    size: float,
    line: float,
    inner: float,
    cps: float = 24.0,
    hold: float = 6.5,
) -> tuple[list[str], str]:
    """Lay out a terminal session from its first baseline and give it a typing loop.

    Rows are ("cmd", text), ("out", [(text, colour), ...]), ("ticks", words), ("wait", seconds),
    ("gap", px) and ("idle",). Every element's resting state is the finished session; the
    keyframes hide rows until their turn, step a cover off each command, and clear the screen
    before the loop restarts.
    """
    cw = size * 0.6
    prompt = [("~", INK_3), (" ❯", CYAN)]
    prompt_chars = sum(len(t) for t, _ in prompt) + 1
    t = 0.7
    baseline = y
    placed = []  # (kind, start, typing start, typing end, markup, text x, baseline, chars)
    for row in rows:
        kind = row[0]
        if kind == "gap":
            baseline += row[1]
            continue
        if kind == "wait":
            t += row[1]
            continue
        if kind in ("cmd", "idle"):
            text = row[1] if kind == "cmd" else ""
            if (prompt_chars + len(text)) * cw > inner:
                raise SystemExit(f"'{text}' is wider than the terminal")
            spans = "".join(span(s, c) for s, c in prompt)
            markup = (
                f'<text class="mono" x="{num(x)}" y="{num(baseline)}" font-size="{size}" '
                f'xml:space="preserve">{spans} {span(text, INK)}</text>'
            )
            t0 = t + 0.3
            t1 = t0 + len(text) / cps
            placed.append((kind, t, t0, t1, markup, x + prompt_chars * cw, baseline, len(text)))
            t = t1 + (0.45 if kind == "cmd" else 0)
        elif kind == "out":
            if sum(len(s) for s, _ in row[1]) * cw > inner:
                raise SystemExit("an output line is wider than the terminal")
            markup = (
                f'<text class="mono" x="{num(x)}" y="{num(baseline)}" font-size="{size}" '
                f'xml:space="preserve">{"".join(span(s, c) for s, c in row[1])}</text>'
            )
            placed.append(("out", t, t, t, markup, 0, baseline, 0))
            t += 0.08
        elif kind == "ticks":
            parts, col = [], 0
            for word in row[1]:
                parts.append(tick(x + col * cw, baseline, cw, size, GREEN))
                parts.append(
                    f'<text class="mono" x="{num(x + (col + 2) * cw)}" y="{num(baseline)}" '
                    f'font-size="{size}" fill="{INK}">{esc(word)}</text>'
                )
                col += 2 + len(word) + 2
            if (col - 2) * cw > inner:
                raise SystemExit("the ticks line is wider than the terminal")
            placed.append(("out", t, t, t, "".join(parts), 0, baseline, 0))
            t += 0.08
        baseline += line

    loop = round(t + hold, 1)
    reset = loop - 0.45
    css, els = [], []
    for i, (kind, start, t0, t1, markup, cx, base, n) in enumerate(placed):
        cls = f"r{i}"
        show = pct(start, loop)
        before = pct(max(start - 0.01, 0), loop)
        css.append(
            f".{cls}{{animation:{cls} {loop}s linear infinite}}"
            f"@keyframes {cls}{{0%,{before}{{opacity:0}}{show},{pct(reset, loop)}{{opacity:1}}"
            f"{pct(reset + 0.25, loop)},100%{{opacity:0}}}}"
        )
        inner_els = [markup]
        top = base - size * 1.02
        if kind == "cmd" and n:
            css.append(
                f".{cls}c{{opacity:0;animation:{cls}c {loop}s linear infinite}}"
                f"@keyframes {cls}c{{0%,{pct(t0, loop)}{{opacity:1;transform:translateX(0);"
                f"animation-timing-function:steps({n},end)}}"
                f"{pct(t1, loop)},100%{{opacity:1;transform:translateX({num(n * cw)}px)}}}}"
                f".{cls}k{{opacity:0;animation:{cls}k {loop}s linear infinite}}"
                f"@keyframes {cls}k{{0%,{before}{{opacity:0}}{show},{pct(t1 + 0.4, loop)}"
                f"{{opacity:1}}{pct(t1 + 0.41, loop)},100%{{opacity:0}}}}"
            )
            inner_els.append(
                f'<g class="{cls}c"><rect x="{num(cx)}" y="{num(top)}" width="{num(n * cw + cw)}" '
                f'height="{num(size * 1.32)}" fill="{TERM_BODY}" />'
                f'<rect class="{cls}k" x="{num(cx)}" y="{num(top + 1)}" width="{num(cw)}" '
                f'height="{num(size * 1.22)}" fill="{CYAN}" fill-opacity="0.85" /></g>'
            )
        if kind == "idle":
            frames, s, on = [], start, True
            while s < reset:
                frames.append(f"{pct(s, loop)}{{opacity:{1 if on else 0}}}")
                s += 0.55
                on = not on
            css.append(
                f".{cls}k{{animation:{cls}k {loop}s step-end infinite}}"
                f"@keyframes {cls}k{{0%{{opacity:0}}{''.join(frames)}"
                f"{pct(reset, loop)},100%{{opacity:0}}}}"
            )
            inner_els.append(
                f'<rect class="{cls}k" x="{num(cx)}" y="{num(top + 1)}" width="{num(cw)}" '
                f'height="{num(size * 1.22)}" fill="{CYAN}" fill-opacity="0.85" />'
            )
        els.append(f'<g class="{cls}">{"".join(inner_els)}</g>')
    return els, "".join(css)


# Banner

PILL = "UK-BASED · 25+ YEARS IN PRODUCTION"
NAME = "Simon Oakes"
ROLE = "Senior Linux, DevOps & Platform Engineer"
TAGLINE = "Automation-first infrastructure. Production systems that stay calm."
FOCUS = ["AUTOMATION", "NETWORK", "SECURITY", "BUILD PLATFORMS", "AI"]
BANNER_SESSION = [
    ("cmd", "ansible-playbook site.yml --check --diff"),
    ("wait", 0.9),
    ("out", [("PLAY RECAP " + "*" * 28, INK_3)]),
    ("out", [("edge      : ", INK_2), ("ok=48 ", GREEN), ("  changed=0  failed=0", INK_3)]),
    ("out", [("platform  : ", INK_2), ("ok=112", GREEN), ("  changed=0  failed=0", INK_3)]),
    ("out", [("services  : ", INK_2), ("ok=96 ", GREEN), ("  changed=0  failed=0", INK_3)]),
    ("gap", 8),
    ("wait", 0.3),
    ("ticks", ["repeatable", "observable", "recoverable", "calm"]),
    ("gap", 6),
    ("idle",),
]


def build_banner() -> str:
    height = 360.0
    for text, size, weight, spacing in (
        (NAME, 68, 800, -2.2),
        (ROLE, 23, 600, -0.3),
        (TAGLINE, 16, 400, 0),
    ):
        if COPY_X + text_width(text, size, weight, spacing) > COPY_RIGHT:
            raise SystemExit(f"'{text}' runs past the copy column")
    size, line, pad = 14.0, 22.0, 22.0
    inner = 49 * size * 0.6 + 0.5  # the ticks line is the widest, at 49 cells
    ww = inner + 2 * pad
    wx, wy, wh = 1140 - ww, 58.0, 36 + 18 + line * 7 + 14 + 18
    w_defs, w_els = window(wx, wy, ww, wh, "~/infra — zsh")
    s_els, s_css = session(BANNER_SESSION, wx + pad, wy + 36 + 18 + size, size, line, inner)
    card = (wx, wy, wx + ww, wy + wh)
    g_defs, g_body, g_css = ground(
        height,
        [(36, 36, 620, 300), (wx - 16, wy - 16, wx + ww + 16, wy + wh + 34)],
        Earth(600, (858, 326), CV_VIEW),
        hidden=[card],
    )
    focus, fx = [], COPY_X
    for i, label in enumerate(FOCUS):
        if i:
            focus.append(f'<circle cx="{num(fx + 9.5)}" cy="278" r="2.2" fill="{AMBER}" />')
            fx += 20
        focus.append(f'<text x="{num(fx)}" y="282">{esc(label)}</text>')
        fx += mono_width(len(label), 12.5, 1.6)
    defs = [
        *g_defs,
        *w_defs,
        *copy_defs(),
        *gradient(
            "linearGradient",
            'id="rule" x1="0" y1="0" x2="1" y2="0"',
            [("0", CYAN, ""), ("1", AMBER, "")],
        ),
    ]
    body = [
        *g_body,
        "",
        "  <!-- Left: name, role and focus -->",
        *pill(54, PILL),
        f'  <text class="sans" x="{num(COPY_X - 3)}" y="150" font-size="68" font-weight="800" '
        f'letter-spacing="-2.2" fill="url(#nameG)">{esc(NAME)}</text>',
        f'  <text class="sans" x="{num(COPY_X)}" y="190" font-size="23" font-weight="600" '
        f'letter-spacing="-0.3" fill="url(#roleG)">{esc(ROLE)}</text>',
        f'  <text class="sans" x="{num(COPY_X)}" y="226" font-size="16" fill="{INK_2}">'
        f"{esc(TAGLINE)}</text>",
        f'  <path d="M{num(COPY_X)} 250.5H{num(COPY_X + text_width(TAGLINE, 16))}" stroke="#8FA3BF" '
        'stroke-opacity="0.18" />',
        f'  <rect x="{num(COPY_X)}" y="249.5" width="72" height="2" rx="1" fill="url(#rule)" />',
        f'  <g class="mono" font-size="12.5" letter-spacing="1.6" fill="{INK_3}">'
        f'{"".join(focus)}</g>',
        "",
        "  <!-- Right: a dry run that comes back clean -->",
        *w_els,
        f'  <g clip-path="url(#screen)">{"".join(s_els)}</g>',
    ]
    title = "Simon Oakes - Senior Linux, DevOps and Platform Engineer"
    desc = (
        "UK-based, 25+ years in production. Automation-first infrastructure; production systems "
        "that stay calm. A terminal dry-runs ansible-playbook site.yml with --check --diff and "
        "reports nothing changed: repeatable, observable, recoverable, calm. The dotted Earth "
        "rises beneath it with London lit."
    )
    return document(height, title, desc, defs, s_css + g_css, body)


# Journey


def build_journey() -> str:
    """Ten roles from 2000 to now as stops on one route over the Earth's horizon, the three eras
    labelled. A signal runs the route and each stop rings as it passes."""
    height = 400.0
    x0, x1, base, rise = 92.0, 1104.0, 270.0, 200.0
    loop, travel = 9.0, 5.5

    def at(year: float) -> tuple[float, float]:
        t = (year - 2000) / (NOW - 2000)
        return x0 + (x1 - x0) * t, base - rise * t * (1 - t)

    pts = [at(2000 + (NOW - 2000) * i / 80) for i in range(81)]
    d = poly(pts)
    length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    arrive = travel / loop * 100
    els = [
        f'<path d="{d}" fill="none" stroke="{CYAN}" stroke-opacity="0.5" stroke-width="1.2" />',
        f'<path class="trip" d="{d}" fill="none" stroke="{CYAN_2}" stroke-width="2.4" '
        f'stroke-linecap="round" stroke-dasharray="22 {num(length + 22)}" '
        f'stroke-dashoffset="{num(-length * 0.62)}" />',
    ]
    css = [
        f".trip{{animation:trip {loop}s linear infinite}}"
        f"@keyframes trip{{0%{{stroke-dashoffset:22;opacity:1}}{arrive:.1f}%"
        f"{{stroke-dashoffset:{num(-length)};opacity:1}}{arrive + 0.1:.1f}%,100%"
        f"{{stroke-dashoffset:{num(-length)};opacity:0}}}}",
        ".stop{opacity:0;transform-box:fill-box;transform-origin:center;"
        f"animation:stop {loop}s ease-out infinite}}"
        "@keyframes stop{0%{opacity:.9;transform:scale(1)}20%{opacity:0;transform:scale(2.6)}"
        "100%{opacity:0}}",
    ]
    eras = {e[0] for e in ERAS}
    for year in ROLES:
        x, y = at(year)
        when = (year - 2000) / (NOW - 2000) * travel
        big = year in eras
        colour = AMBER if big else CYAN
        els.append(
            f'<circle class="stop" cx="{num(x)}" cy="{num(y)}" r="{9 if big else 6}" fill="none" '
            f'stroke="{colour}" stroke-width="1.2" style="animation-delay:{when:.2f}s" />'
            f'<circle cx="{num(x)}" cy="{num(y)}" r="{4.2 if big else 3}" fill="{colour}" />'
        )
    for year, label, lines, anchor in ERAS:
        x, y = at(year)
        tx = x - 10 if anchor == "start" else x
        els.append(
            f'<text class="mono" x="{num(tx)}" y="{num(y + 30)}" text-anchor="{anchor}" '
            f'font-size="11" letter-spacing="1.4" fill="{AMBER}">{label}</text>'
            + "".join(
                f'<text class="sans" x="{num(tx)}" y="{num(y + 48 + 17 * k)}" '
                f'text-anchor="{anchor}" font-size="13.5" fill="{INK_2}">{esc(t)}</text>'
                for k, t in enumerate(lines)
            )
        )
    nx, ny = at(NOW)
    els.append(
        f'<circle class="live" cx="{num(nx)}" cy="{num(ny)}" r="5" fill="{GREEN}" />'
        f'<circle cx="{num(nx)}" cy="{num(ny)}" r="10" fill="none" stroke="{GREEN}" '
        'stroke-opacity="0.5" />'
        f'<text class="mono" x="{num(nx)}" y="{num(ny - 18)}" text-anchor="middle" font-size="11" '
        f'letter-spacing="1.4" fill="{GREEN}">NOW</text>'
    )
    # London sits just below the card, so the Earth is a low horizon under the route.
    g_defs, g_body, g_css = ground(
        height, [(36, 30, 720, 170), (60, 160, 1140, 340)], Earth(1500, (600, 436), HORIZON_VIEW)
    )
    body = [
        *g_body,
        *copy_block(
            "10 ROLES SINCE 2000",
            "The journey so far.",
            "",
            ["Ten roles across ISPs, telecoms, media and platform engineering, from 2000 to now."],
            34,
            right=WIDTH - COPY_X,
        ),
        *[f"  {e}" for e in els],
    ]
    desc = (
        "The journey so far: ten roles across ISPs, telecoms, media and platform engineering, "
        "from 2000 to now, as stops on one route over the Earth. ISP and telecoms foundations "
        "from 2000; automation, networks and build platforms from 2011; platforms, automation "
        "and AI infrastructure from 2024."
    )
    title = "Simon Oakes - the journey so far"
    return document(height, title, desc, [*g_defs, *copy_defs()], "".join(css) + g_css, body)


# Panels


def panel_defs() -> list[str]:
    return gradient(
        "linearGradient",
        'id="panelEdge" x1="0" y1="0" x2="1" y2="0"',
        [("0", CYAN, "0"), ("0.2", CYAN, "0.75"), ("0.8", AMBER, "0.75"), ("1", AMBER, "0")],
    )


def panel(box: Box) -> str:
    """A card on the ground: translucent navy, a hairline edge, and the banner terminal's
    cyan-to-amber line along the top."""
    x0, y0, x1, y1 = box
    return (
        f'<rect x="{num(x0)}" y="{num(y0)}" width="{num(x1 - x0)}" height="{num(y1 - y0)}" '
        f'rx="14" fill="#0B1322" fill-opacity="0.88" stroke="{TERM_EDGE}" />'
        f'<rect x="{num(x0 + 18)}" y="{num(y0)}" width="{num(x1 - x0 - 36)}" height="1.5" '
        'fill="url(#panelEdge)" />'
    )


def grid(top: float, heights: list[float], cols: int = 3, gap: float = 18.0) -> list[Box]:
    """Boxes for cards laid out in rows across the copy column's width; each row is as tall as
    its tallest card, so neighbours line up."""
    width = (WIDTH - 2 * COPY_X - (cols - 1) * gap) / cols
    boxes, y = [], top
    for start in range(0, len(heights), cols):
        row = max(heights[start : start + cols])
        for k in range(len(heights[start : start + cols])):
            x = COPY_X + k * (width + gap)
            boxes.append((x, y, x + width, y + row))
        y += row + gap
    return boxes


# What I bring

CAPABILITIES = [
    ("Stabilise", "pulse",
     "Understand the platform, find the real failure modes and reduce operational noise."),
    ("Automate", "cycle",
     "Replace fragile manual steps with code, pipelines, checks and repeatable workflows."),
    ("Modernise", "arrow",
     "Move systems forward without losing reliability, recovery, or the people operating them."),
    ("Mentor", "people",
     "Raise the bar across the engineering function as escalation point, reviewer and teacher."),
    ("Tool", "prompt",
     "Small Go and Python CLIs that fit shells, CI, cron and systemd. Built for operators."),
    ("AI-assist", "spark",
     "Use AI where it improves clarity: summarisation, reporting and human-in-the-loop "
     "operations."),
]
# Line icons on a 24px grid, stroked in cyan.
GLYPHS = {
    "pulse": "M2 12h4.5l2.5-6.5 4 13 2.5-6.5H22",
    "cycle": "M19.5 12a7.5 7.5 0 0 1-13.4 4.6M4.5 12a7.5 7.5 0 0 1 13.4-4.6M18.6 3.2v4.6H14"
    "M5.4 20.8v-4.6H10",
    "arrow": "M5 19 18 6M9 5.5h9.5V15",
    "people": "M3.5 20c0-3.2 2.4-5.6 5.5-5.6s5.5 2.4 5.5 5.6M9 11.4a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 "
    "0 0 0 6.4ZM16.5 14.6c2.4.4 4 2.5 4 5.4M15.5 5.3a2.9 2.9 0 0 1 0 5.6",
    "prompt": "M4.5 7 9.5 12l-5 5M12.5 18h7",
    "spark": "M12 3.5c.7 4.4 2.6 6.3 7 7-4.4.7-6.3 2.6-7 7-.7-4.4-2.6-6.3-7-7 4.4-.7 6.3-2.6 7-7Z",
}


def glyph(x: float, y: float, key: str) -> str:
    """A capability icon in a 36px tile with its top-left corner at (x, y)."""
    return (
        f'<rect x="{num(x)}" y="{num(y)}" width="36" height="36" rx="9" fill="#0E1726" '
        f'stroke="{TERM_EDGE}" />'
        f'<path transform="translate({num(x + 6)} {num(y + 6)})" d="{GLYPHS[key]}" fill="none" '
        f'stroke="{CYAN}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />'
    )


def build_bring() -> str:
    """The site's four stats drawn to scale, above the six things I bring as cards: a ruler of
    the years since 2000 with the eras marked, 2,500 dots for the VMs, 300 for the DNS zones and
    40 tiles for the Ansible roles. Each field fills left to right on a loop; at rest every field
    is full."""
    w, loop = 280.0, 7.0
    cells = [(556.0, 54.0), (856.0, 54.0), (556.0, 216.0), (856.0, 216.0)]
    css = ["@keyframes fill{0%{opacity:.12}8%{opacity:1}88%{opacity:1}100%{opacity:.12}}"]
    els, defs = [], []

    def head(x: float, y: float, key: str) -> str:
        value, label = STATS[key]
        return (
            f'<text class="sans" x="{num(x)}" y="{num(y + 34)}" font-size="36" font-weight="800" '
            f'letter-spacing="-1" fill="{INK}">{esc(value)}</text>'
            f'<text class="mono" x="{num(x)}" y="{num(y + 56)}" font-size="10.5" '
            f'letter-spacing="1.4" fill="{INK_3}">{esc(label)}</text>'
        )

    def field(x: float, y: float, height: float, pattern: str, strips: int, cls: str) -> str:
        """A patterned dot field revealed left to right in strips."""
        sw = w / strips
        css.append(f".{cls}{{animation:fill {loop}s ease-out infinite both}}")
        return "".join(
            f'<rect class="{cls}" x="{num(x + i * sw)}" y="{num(y)}" width="{num(sw)}" '
            f'height="{num(height)}" fill="url(#{pattern})" '
            f'style="animation-delay:{i * 0.08:.2f}s" />'
            for i in range(strips)
        )

    # Years: a ruler from 2000 to now, the era starts in amber.
    x, y = cells[0]
    base = y + 112
    ruler = [
        head(x, y, "years"),
        f'<path d="M{num(x)} {num(base)}H{num(x + w)}" stroke="{INK_3}" stroke-opacity="0.5" />',
    ]
    for year in range(2000, 2027):
        tx = x + (year - 2000) / (NOW - 2000) * w
        era = year in (2000, 2011, 2024)
        ruler.append(
            f'<path d="M{num(tx)} {num(base)}v-{20 if era else 8}" '
            f'stroke="{AMBER if era else INK_3}" stroke-opacity="{1 if era else 0.6}" '
            f'stroke-width="{1.6 if era else 1}" />'
        )
        if era:
            ruler.append(
                f'<text class="mono" x="{num(tx)}" y="{num(base + 16)}" text-anchor="middle" '
                f'font-size="10" fill="{AMBER}">{year}</text>'
            )
    ruler.append(
        f'<circle class="live" cx="{num(x + w)}" cy="{num(base - 4)}" r="3.4" fill="{GREEN}" />'
        f'<text class="mono" x="{num(x + w)}" y="{num(base - 14)}" text-anchor="middle" '
        f'font-size="10" fill="{GREEN}">NOW</text>'
    )
    els.append("".join(ruler))

    # 2,500 VMs: 100 x 25 dots.
    x, y = cells[1]
    p = w / 100
    defs.append(
        f'    <pattern id="vm" width="{p:.2f}" height="{p:.2f}" patternUnits="userSpaceOnUse" '
        f'x="{num(x)}" y="{num(y + 70)}"><circle cx="{p / 2:.2f}" cy="{p / 2:.2f}" r="0.78" '
        f'fill="{CYAN}" /></pattern>'
    )
    els.append(head(x, y, "vms") + field(x, y + 70, p * 25, "vm", 20, "vm"))

    # 300 DNS zones: 50 x 6 dots.
    x, y = cells[2]
    p = w / 50
    defs.append(
        f'    <pattern id="zone" width="{p:.2f}" height="{p:.2f}" patternUnits="userSpaceOnUse" '
        f'x="{num(x)}" y="{num(y + 74)}"><circle cx="{p / 2:.2f}" cy="{p / 2:.2f}" r="1.7" '
        f'fill="{CYAN_2}" /></pattern>'
    )
    els.append(head(x, y, "zones") + field(x, y + 74, p * 6, "zone", 10, "zn"))

    # 40 Ansible roles: 20 x 2 tiles, each lighting in turn.
    x, y = cells[3]
    tiles = [head(x, y, "roles")]
    pitch = w / 20
    for i in range(40):
        col, row = i % 20, i // 20
        tiles.append(
            f'<rect class="tl" x="{num(x + col * pitch + 1)}" y="{num(y + 74 + row * pitch)}" '
            f'width="{num(pitch - 3.5)}" height="{num(pitch - 3.5)}" rx="2.5" fill="{GREEN}" '
            f'fill-opacity="0.85" style="animation-delay:{i * 0.05:.2f}s" />'
        )
    css.append(f".tl{{animation:fill {loop}s ease-out infinite both}}")
    els.append("".join(tiles))

    # The six things I bring, as cards under the stats.
    top = 372.0
    width = (WIDTH - 2 * COPY_X - 2 * 18) / 3
    bodies = [wrap(body, 15, width - 44) for _, _, body in CAPABILITIES]
    boxes = grid(top, [86 + 22 * (len(lines) - 1) + 26 for lines in bodies])
    cards = []
    for (title, icon, _), lines, (x0, y0, _, _) in zip(CAPABILITIES, bodies, boxes):
        cards.append(
            panel(boxes[len(cards)])
            + glyph(x0 + 22, y0 + 22, icon)
            + f'<text class="sans" x="{num(x0 + 72)}" y="{num(y0 + 46)}" font-size="19" '
            f'font-weight="700" fill="{INK}">{esc(title)}</text>'
            + "".join(
                f'<text class="sans" x="{num(x0 + 22)}" y="{num(y0 + 86 + 22 * k)}" '
                f'font-size="15" fill="{INK_2}">{esc(line)}</text>'
                for k, line in enumerate(lines)
            )
        )
    height = boxes[-1][3] + 40

    # No Earth here: behind the dot fields it made them harder to read.
    stats_box = (536.0, 40.0, 1150.0, 350.0)
    g_defs, g_body, g_css = ground(
        height, [(36, 40, 520, 320), stats_box, (40, top - 10, 1160, height - 20)], glow=stats_box
    )
    body = [
        *g_body,
        *copy_block(
            "IN PRODUCTION SINCE 2000",
            "Twenty-five years,",
            "by the numbers.",
            ["From ISP and telecoms foundations to platforms,", "automation and AI infrastructure."],
            72,
        ),
        f'  <path d="M{num(cells[0][0] - 20)} 196H1136" stroke="#8FA3BF" stroke-opacity="0.12" />',
        f'  <path d="M{num(cells[1][0] - 10)} 50V340" stroke="#8FA3BF" stroke-opacity="0.12" />',
        *[f"  {e}" for e in els],
        *[f"  {c}" for c in cards],
    ]
    abilities = "; ".join(f"{t}: {b}" for t, _, b in CAPABILITIES)
    desc = (
        "Twenty-five years, by the numbers: 25+ years in production since 2000, 2,500 VMs "
        "under automation, 300+ DNS zones managed and 40+ Ansible roles authored, each drawn "
        f"to scale. What I bring. {abilities}"
    )
    title = "Simon Oakes - what I bring"
    defs = [*g_defs, *copy_defs(), *panel_defs(), *defs]
    return document(height, title, desc, defs, "".join(css) + g_css, body)


# Stack


TOOLBOX = [
    ("LINUX", ["Debian", "Ubuntu", "Red Hat-family systems", "macOS", "Windows Server",
               "systemd"]),
    ("AUTOMATION", ["Ansible", "Terraform", "Packer", "Puppet", "Bash", "PowerShell"]),
    ("CI/CD", ["GitHub Actions", "GitLab CI", "Jenkins", "Nexus", "SonarQube"]),
    ("RUNTIME", ["Docker", "Docker Compose", "Kubernetes", "HAProxy", "Nginx"]),
    ("CODE", ["Go", "Python", "Flask", "API integrations"]),
    ("NETWORK", ["BGP", "OSPF", "DNS", "VLANs", "NAT", "WireGuard", "IPsec", "MikroTik",
                 "Cisco", "RTBH"]),
    ("SERVICES", ["Postfix", "Dovecot", "BIND", "Apache", "FreeRADIUS", "monitoring",
                  "backup"]),
    ("PLATFORMS", ["Proxmox", "VMware", "XenServer", "KVM", "Nutanix", "NetApp",
                   "Pure Storage", "Nimble"]),
    ("AI", ["NVIDIA DGX Spark", "vLLM", "LiteLLM", "Hugging Face", "Azure OpenAI"]),
]
CHIP_SIZE, CHIP_PAD, CHIP_GAP = 12.0, 10.0, 8.0


@cache
def icon_paths() -> dict[str, str]:
    return json.loads(ICONS.read_text(encoding="utf-8"))["icons"]


def chip_rows(items: list[str], width: float) -> list[list[tuple[str, float]]]:
    """Items as mono chips, wrapped into rows that fit `width`."""
    rows: list[list[tuple[str, float]]] = [[]]
    used = 0.0
    for item in items:
        w = mono_width(len(item), CHIP_SIZE) + 2 * CHIP_PAD
        if rows[-1] and used + CHIP_GAP + w > width:
            rows.append([])
            used = 0.0
        used += (CHIP_GAP if rows[-1] else 0) + w
        rows[-1].append((item, w))
    return rows


def build_stack() -> str:
    """oakes.me.uk's Stack orbit, Linux at the core and two rings of tools turning slowly in
    opposite directions with each logo kept upright, and the whole toolbox in panels on the
    Earth beneath it, London lit between them."""
    cx, cy, r_in, r_out, sat = 890.0, 192.0, 92.0, 158.0, 19.0
    css = [
        ".spinO{animation:spin 140s linear infinite}"
        ".upO{animation:spin 140s linear infinite reverse}"
        ".spinI{animation:spin 96s linear infinite reverse}"
        ".upI{animation:spin 96s linear infinite}"
        "@keyframes spin{to{transform:rotate(360deg)}}"
        ".pkO{animation:pk 11s linear infinite}.pkI{animation:pk 7s linear infinite reverse}"
        "@keyframes pk{to{stroke-dashoffset:-100}}"
    ]
    rings = []
    for radius, items, offset, spin, up, pk in (
        (r_out, ORBIT_OUTER, 15, "spinO", "upO", "pkO"),
        (r_in, ORBIT_INNER, 0, "spinI", "upI", "pkI"),
    ):
        parts = [
            f'<circle cx="{num(cx)}" cy="{num(cy)}" r="{num(radius)}" fill="none" '
            f'stroke="{CYAN_2}" stroke-opacity="0.22" stroke-width="1" />',
            f'<circle class="{pk}" cx="{num(cx)}" cy="{num(cy)}" r="{num(radius)}" fill="none" '
            f'stroke="{CYAN_2}" stroke-width="2" stroke-linecap="round" pathLength="100" '
            'stroke-dasharray="4 96" stroke-dashoffset="-30" />',
        ]
        for k, (label, slug, colour) in enumerate(items):
            a = math.radians(-90 + offset + 360 * k / len(items))
            sx, sy = cx + radius * math.cos(a), cy + radius * math.sin(a)
            scale = sat * (1.25 if slug == "go" else 0.95) / 24
            parts.append(
                f'<g class="{up}" style="transform-origin:{num(sx)}px {num(sy)}px">'
                f"<title>{esc(label)}</title>"
                f'<circle cx="{num(sx)}" cy="{num(sy)}" r="{num(sat)}" fill="#0C1422" '
                f'stroke="{colour}" stroke-opacity="0.55" stroke-width="1.2" />'
                f'<path transform="translate({num(sx - 12 * scale)} {num(sy - 12 * scale)}) '
                f'scale({scale:.4f})" d="{icon_paths()[slug]}" fill="{colour}" /></g>'
            )
        rings.append(
            f'  <g class="{spin}" style="transform-origin:{num(cx)}px {num(cy)}px">'
            f'{"".join(parts)}</g>'
        )
    core = (
        f'  <circle cx="{num(cx)}" cy="{num(cy)}" r="70" fill="url(#coreGlow)" />'
        f'<circle cx="{num(cx)}" cy="{num(cy)}" r="34" fill="#0E1726" stroke="{CYAN}" '
        'stroke-opacity="0.6" stroke-width="1.3" />'
        f"<title>{ORBIT_CORE[0]}</title>"
        f'<path transform="translate({num(cx - 15)} {num(cy - 15)}) scale(1.25)" '
        f'd="{icon_paths()[ORBIT_CORE[1]]}" fill="{INK}" />'
    )

    # The toolbox, one panel per group, on the Earth below the orbit.
    top = 486.0
    width = (WIDTH - 2 * COPY_X - 2 * 18) / 3
    layouts = [chip_rows(items, width - 40) for _, items in TOOLBOX]
    boxes = grid(top, [52 + 32 * len(rows) + 12 for rows in layouts])
    panels = []
    for (label, _), rows, box in zip(TOOLBOX, layouts, boxes):
        x0, y0 = box[0], box[1]
        parts = [
            panel(box),
            f'<text class="mono" x="{num(x0 + 20)}" y="{num(y0 + 32)}" font-size="11.5" '
            f'letter-spacing="1.6" fill="{CYAN_2}">{esc(label)}</text>',
        ]
        for r, row in enumerate(rows):
            x, y = x0 + 20, y0 + 48 + 32 * r
            for item, w in row:
                parts.append(
                    f'<rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="24" rx="6" '
                    f'fill="#0E1726" stroke="{TERM_EDGE}" />'
                    f'<text class="mono" x="{num(x + CHIP_PAD)}" y="{num(y + 16.4)}" '
                    f'font-size="{num(CHIP_SIZE)}" fill="{INK_2}">{esc(item)}</text>'
                )
                x += w + CHIP_GAP
        panels.append("".join(parts))
    height = boxes[-1][3] + 40

    orbit = (cx - r_out - 30, cy - r_out - 30, cx + r_out + 30, cy + r_out + 30)
    g_defs, g_body, g_css = ground(
        height,
        [(36, 40, 520, 300), orbit, (40, top - 10, 1160, height)],
        Earth(1500, (890, 440), HORIZON_VIEW),
        # Dots in the slivers between panels only add bytes, so the land stops at their top.
        hidden=[(-10, top - 8, WIDTH + 10, height + 10)],
    )
    defs = [
        *g_defs,
        *copy_defs(),
        *panel_defs(),
        *gradient(
            "radialGradient",
            'id="coreGlow" cx="0.5" cy="0.5" r="0.5"',
            [("0", CYAN, "0.32"), ("1", CYAN, "0")],
        ),
    ]
    body = [
        *g_body,
        *copy_block(
            "USED IN PRODUCTION",
            "The stack I reach for,",
            "battle-tested.",
            [
                "Linux at the core, automation and CI around it,",
                "and the platforms underneath, all used in production.",
            ],
            72,
        ),
        *rings,
        core,
        *[f"  {p}" for p in panels],
    ]
    inner = ", ".join(label for label, _, _ in ORBIT_INNER)
    outer = ", ".join(label for label, _, _ in ORBIT_OUTER)
    toolbox = "; ".join(f"{label.title()}: {', '.join(items)}" for label, items in TOOLBOX)
    desc = (
        f"The stack I reach for, battle-tested. Linux at the core; {inner} on the inner ring; "
        f"{outer} on the outer ring. The toolbox. {toolbox}."
    )
    title = "Simon Oakes - the stack"
    return document(height, title, desc, defs, "".join(css) + g_css, body)


# Project cards

# One card per public project, linked from the README to its repository. The copy is from
# soakes/cv data/cv.yml (public_site.projects), and the accent is the one each project's own
# README hero uses.
PROJECTS = [
    {
        "name": "blackhole-threats",
        "kicker": "NETWORK DEFENCE AUTOMATION",
        "accent": "#FF4D63",
        "lang": ("Go", "go", "#00add8"),
        "body": "Turns threat feeds into BGP blackhole routes through GoBGP, and keeps a feed's "
        "last good routes when it fails.",
        "facts": [("BUILT IN", "Go, with GoBGP"), ("SHIPS AS", "Signed APT repository and a GHCR "
                                                   "image")],
        "install": ["sudo apt install blackhole-threats",
                    "sudo systemctl enable --now blackhole-threats"],
    },
    {
        "name": "telegram-message-exporter",
        "kicker": "CHAT RECOVERY",
        "accent": "#2CA5E0",
        "lang": ("Python", "python", "#5a9bd8"),
        "body": "Recovers deleted chats from the encrypted cache Telegram for macOS keeps on "
        "disk, entirely offline.",
        "facts": [("BUILT IN", "Python, with SQLCipher"), ("EXPORTS", "HTML, Markdown and CSV")],
        "install": ["pip install git+https://github.com/soakes/telegram-message-exporter",
                    "telegram-exporter discover --root recovery/telegram"],
    },
    {
        "name": "s3ctl",
        "kicker": "S3 PROVISIONING",
        "accent": "#4BD8FF",
        "lang": ("Go", "go", "#00add8"),
        "body": "Provisions S3 buckets, each with its own IAM user and key scoped to that bucket "
        "alone, and plans every change first.",
        "facts": [("BUILT IN", "Go"), ("SHIPS AS", "Homebrew tap, signed APT repository and GHCR")],
        "install": ["brew tap netspeedy/s3ctl", "brew install s3ctl"],
    },
    {
        "name": "s3mirror",
        "kicker": "BUCKET MIRRORING",
        "accent": "#9B73FF",
        "lang": ("Python", "python", "#5a9bd8"),
        "body": "Mirrors every bucket between S3-compatible endpoints, copying only new or "
        "changed objects, in parallel.",
        "facts": [("BUILT IN", "Python, with boto3"), ("SHIPS AS", "Homebrew tap and a GHCR "
                                                       "image")],
        "install": ["brew tap netspeedy/s3mirror", "brew install s3mirror"],
    },
    {
        "name": "zquota",
        "kicker": "QUOTA MONITORING",
        "accent": "#2BD4BD",
        "lang": ("Python", "python", "#5a9bd8"),
        "body": "Shows Z.ai quota use and exactly when each window resets, with exit codes cron "
        "can act on.",
        "facts": [("BUILT IN", "Python, standard library only"), ("SHIPS AS", "Homebrew tap, "
                                                                   "signed APT repository and pip")],
        "install": ["brew tap netspeedy/zquota", "brew install zquota"],
    },
    {
        "name": "joflux",
        "kicker": "REPOSITORY MIGRATION",
        "accent": "#F5B841",
        "lang": ("Python", "python", "#5a9bd8"),
        "body": "Moves a whole GitHub organisation into Forgejo or Codeberg in five stages, and "
        "never deletes the originals.",
        "facts": [("BUILT IN", "Python, standard library only"), ("SHIPS AS", "Homebrew tap")],
        "install": ["brew tap netspeedy/joflux", "brew install joflux"],
    },
]
# A card is 600 wide inside an 8px transparent margin, so two side by side at 49% of the
# README's width leave an even gap between and below them.
CARD_W, CARD_H, CARD_M, CARD_PAD = 600.0, 336.0, 8.0, 26.0


def build_project(project: dict) -> str:
    """A project card: category, name and language, two lines on what it does, what it's built
    in and how it ships, and the command that installs it."""
    m, w, h = CARD_M, CARD_W, CARD_H
    left, inner = m + CARD_PAD, w - 2 * CARD_PAD
    accent = project["accent"]
    body = wrap(project["body"], 17, inner)
    if len(body) > 2:
        raise SystemExit(f"{project['name']}: the description runs past two lines")
    for command in project["install"]:
        if mono_width(len(command) + 2, 12.5) > inner - 28:
            raise SystemExit(f"{project['name']}: '{command}' is wider than the card")
    rng = random.Random(project["name"])
    stars = "".join(
        f'<circle cx="{num(rng.uniform(m + 8, m + w - 8))}" cy="{num(rng.uniform(m + 8, m + h - 8))}" '
        f'r="{num(rng.choice([0.55, 0.7, 0.85, 1.0]))}" opacity="{rng.uniform(0.15, 0.5):.2f}" />'
        for _ in range(26)
    )
    label, slug, colour = project["lang"]
    lx, ly = m + w - CARD_PAD - 20, m + 44
    scale = 20 * (1.25 if slug == "go" else 0.95) / 24
    defs = [
        *copy_defs(),
        *gradient(
            "linearGradient",
            'id="ground" x1="0" y1="0" x2="0.35" y2="1"',
            [("0", "#09122A", ""), ("0.6", BG, ""), ("1", "#0B1424", "")],
        ),
        *gradient(
            "radialGradient",
            'id="accentGlow" cx="0.5" cy="0.5" r="0.5"',
            [("0", accent, "0.24"), ("1", accent, "0")],
        ),
        *gradient(
            "linearGradient",
            'id="accentEdge" x1="0" y1="0" x2="1" y2="0"',
            [("0", accent, "0"), ("0.25", accent, "0.9"), ("0.75", accent, "0.9"),
             ("1", accent, "0")],
        ),
        f'    <clipPath id="card"><rect x="{num(m)}" y="{num(m)}" width="{num(w)}" '
        f'height="{num(h)}" rx="18" /></clipPath>',
    ]
    els = [
        '  <g clip-path="url(#card)">',
        f'    <rect x="{num(m)}" y="{num(m)}" width="{num(w)}" height="{num(h)}" fill="url(#ground)" />',
        f'    <ellipse cx="{num(m + w - 60)}" cy="{num(m + 10)}" rx="300" ry="180" '
        'fill="url(#accentGlow)" />',
        f'    <g fill="#CFE6FF">{stars}</g>',
        f'    <rect x="{num(m + 24)}" y="{num(m)}" width="{num(w - 48)}" height="1.5" '
        'fill="url(#accentEdge)" />',
        "  </g>",
        f'  <rect x="{num(m + 0.75)}" y="{num(m + 0.75)}" width="{num(w - 1.5)}" '
        f'height="{num(h - 1.5)}" rx="17.5" fill="none" stroke="#1A2638" stroke-width="1.5" />',
        *pill(m + 28, project["kicker"], x=left, dot=accent, live=False),
        f'  <g><title>{esc(label)}</title><circle cx="{num(lx)}" cy="{num(ly)}" r="20" '
        f'fill="#0C1422" stroke="{colour}" stroke-opacity="0.55" stroke-width="1.2" />'
        f'<path transform="translate({num(lx - 12 * scale)} {num(ly - 12 * scale)}) '
        f'scale({scale:.4f})" d="{icon_paths()[slug]}" fill="{colour}" /></g>',
        f'  <text class="sans" x="{num(left - 1)}" y="{num(m + 110)}" font-size="34" '
        f'font-weight="800" letter-spacing="-1" fill="url(#nameG)">{esc(project["name"])}</text>',
        *[
            f'  <text class="sans" x="{num(left)}" y="{num(m + 146 + 24 * k)}" font-size="17" '
            f'fill="{INK_2}">{esc(line)}</text>'
            for k, line in enumerate(body)
        ],
    ]
    for k, (name, value) in enumerate(project["facts"]):
        y = m + 212 + 24 * k
        if text_width(value, 14.5) > inner - 96:
            raise SystemExit(f"{project['name']}: '{value}' is wider than the card")
        els.append(
            f'  <text class="mono" x="{num(left)}" y="{num(y)}" font-size="10.5" '
            f'letter-spacing="1.4" fill="{INK_3}">{esc(name)}</text>'
            f'<text class="sans" x="{num(left + 96)}" y="{num(y)}" font-size="14.5" '
            f'fill="{INK}">{esc(value)}</text>'
        )
    sy = m + 250
    els.append(
        f'  <rect x="{num(left)}" y="{num(sy)}" width="{num(inner)}" height="60" rx="10" '
        f'fill="{TERM_BODY}" stroke="{TERM_EDGE}" />'
    )
    for k, command in enumerate(project["install"]):
        els.append(
            f'  <text class="mono" x="{num(left + 14)}" y="{num(sy + 25 + 20 * k)}" '
            f'font-size="12.5" xml:space="preserve"><tspan fill="{CYAN}">$</tspan>'
            f'<tspan fill="{INK}"> {esc(command)}</tspan></text>'
        )
    facts = ". ".join(f"{name.capitalize()}: {value}" for name, value in project["facts"])
    install = ", then ".join(project["install"])
    desc = f"{project['kicker'].capitalize()}. {project['body']} {facts}. Install: {install}."
    return document(
        h + 2 * m, project["name"], desc, defs, "", els, width=w + 2 * m
    )


# Engineering style

# soakes/cv data/cv.yml profile.principles.
PRINCIPLES = [
    "Automate the repeatable.",
    "Document the surprising.",
    "Design for recovery.",
    "Keep production calm.",
    "Make the next fix easier than the last one.",
]


# One icon and one word per principle; the icons are on the capability icons' 24px grid.
PRINCIPLE_ICONS = {
    "Automate the repeatable.": GLYPHS["cycle"],
    "Document the surprising.": "M6.5 3h7.5l4 4v14h-11.5ZM14 3v4h4M9.5 12h5M9.5 16h5",
    "Design for recovery.": "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16ZM12 8.6a3.4 3.4 0 1 0 0 6.8 3.4 "
    "3.4 0 0 0 0-6.8ZM6.4 6.4l3.2 3.2M17.6 6.4l-3.2 3.2M6.4 17.6l3.2-3.2M17.6 17.6l-3.2-3.2",
    "Keep production calm.": "M2.5 8.5c2.4-3 4.6-3 7 0s4.6 3 7 0c1.6-1.9 3.2-2.3 5-1.2M2.5 14.5c3-1.4 "
    "6.4-1.4 9.5 0s6.6 1.4 9.5 0M2.5 19.5h19",
    "Make the next fix easier than the last one.": "M3 20h5v-5h5v-5h5V5h3",
}
PRINCIPLE_WORDS = ["AUTOMATE", "DOCUMENT", "RECOVER", "STAY CALM", "IMPROVE"]
STYLE_LEAD = "The habits behind every playbook, pipeline and tool on this page."


def principle_icon(cx: float, cy: float, key: str, size: float) -> str:
    s = size / 24
    return (
        f'<path transform="translate({num(cx - 12 * s)} {num(cy - 12 * s)}) scale({s:.3f})" '
        f'd="{PRINCIPLE_ICONS[key]}" fill="none" stroke="{CYAN}" stroke-width="{1.7 / s:.2f}" '
        'stroke-linecap="round" stroke-linejoin="round" />'
    )


def build_style() -> str:
    """The five principles as stages on one pipeline, each with its icon and a one-word label,
    and a signal running left to right that rings each stage as it passes. A recap underneath
    reads like the banner's playbook run. At rest the signal sits part way along."""
    height, loop, travel = 440.0, 7.0, 4.2
    x0, x1, ty = 96.0, WIDTH - 96.0, 266.0
    xs = [x0 + 64 + i * (x1 - x0 - 128) / 4 for i in range(5)]
    length = x1 - x0
    els = [
        *pill(44, "ENGINEERING STYLE"),
        f'  <text class="sans" x="{num(COPY_X)}" y="{num(124)}" font-size="40" font-weight="800" '
        f'letter-spacing="-1.2" text-anchor="start"><tspan fill="url(#nameG)">How I work, </tspan>'
        '<tspan fill="url(#roleG)">in five lines.</tspan></text>',
        f'  <text class="sans" x="{num(COPY_X)}" y="{num(162)}" font-size="16" '
        f'fill="{INK_2}">{esc(STYLE_LEAD)}</text>',
        f'  <path d="M{num(x0)} {num(ty)}H{num(x1)}" stroke="url(#track)" stroke-width="1.6" '
        'stroke-opacity="0.6" />',
        f'  <path class="trip" d="M{num(x0)} {num(ty)}H{num(x1)}" stroke="{CYAN_2}" '
        f'stroke-width="3" stroke-linecap="round" stroke-dasharray="26 {num(length + 26)}" '
        f'stroke-dashoffset="{num(-length * 0.55)}" />',
    ]
    arrive = travel / loop * 100
    css = [
        f".trip{{animation:trip {loop}s linear infinite}}"
        f"@keyframes trip{{0%{{stroke-dashoffset:26;opacity:1}}{arrive:.1f}%{{stroke-dashoffset:"
        f"{num(-length)};opacity:1}}{arrive + 0.1:.1f}%,100%{{stroke-dashoffset:{num(-length)};"
        "opacity:0}}",
        ".ring{opacity:0;transform-box:fill-box;transform-origin:center;"
        f"animation:ring {loop}s ease-out infinite}}"
        "@keyframes ring{0%{opacity:.85;transform:scale(1)}18%{opacity:0;transform:scale(1.7)}"
        "100%{opacity:0}}",
    ]
    for i, (x, line) in enumerate(zip(xs, PRINCIPLES)):
        when = (x - x0) / length * travel
        lines = wrap(line, 16.5, 196, 600)
        els.append(
            f'  <circle cx="{num(x)}" cy="{num(ty)}" r="46" fill="url(#nodeGlow)" />'
            f'<circle class="ring" cx="{num(x)}" cy="{num(ty)}" r="30" fill="none" stroke="{CYAN}" '
            f'stroke-width="1.2" style="animation-delay:{when:.2f}s" />'
            f'<circle cx="{num(x)}" cy="{num(ty)}" r="30" fill="#0E1726" stroke="{TERM_EDGE}" '
            'stroke-width="1.4" />'
            + principle_icon(x, ty, line, 30)
            + f'<text class="mono" x="{num(x)}" y="{num(ty - 48)}" text-anchor="middle" '
            f'font-size="11" letter-spacing="1.6" fill="{CYAN_2}">{PRINCIPLE_WORDS[i]}</text>'
            + "".join(
                f'<text class="sans" x="{num(x)}" y="{num(ty + 62 + 22 * k)}" '
                f'text-anchor="middle" font-size="16.5" font-weight="600" fill="{INK}">'
                f"{esc(t)}</text>"
                for k, t in enumerate(lines)
            )
        )
    els.append(
        f'  <text class="mono" x="{num(WIDTH / 2)}" y="{num(404)}" font-size="12.5" '
        f'text-anchor="middle" xml:space="preserve"><tspan fill="{INK_3}">principles : </tspan>'
        f'<tspan fill="{GREEN}">ok=5</tspan><tspan fill="{INK_3}">  changed=0  failed=0</tspan>'
        "</text>"
    )
    box = (60.0, 190.0, WIDTH - 60.0, 380.0)
    g_defs, g_body, g_css = ground(height, [(36, 30, 760, 180), box], glow=box)
    defs = [
        *g_defs,
        *copy_defs(),
        *gradient(
            "linearGradient",
            f'id="track" gradientUnits="userSpaceOnUse" x1="{num(x0)}" y1="0" x2="{num(x1)}" y2="0"',
            [("0", CYAN, "0"), ("0.15", CYAN, ""), ("0.85", AMBER, ""), ("1", AMBER, "0")],
        ),
        *gradient(
            "radialGradient",
            'id="nodeGlow" cx="0.5" cy="0.5" r="0.5"',
            [("0", CYAN, "0.22"), ("1", CYAN, "0")],
        ),
    ]
    desc = "Engineering style: how I work, in five lines, as stages on one pipeline. " + " ".join(
        PRINCIPLES
    )
    title = "Simon Oakes - engineering style"
    return document(height, title, desc, defs, "".join(css) + g_css, [*g_body, *els])


def main() -> None:
    graphics = [
        ("profile-banner.svg", build_banner),
        ("profile-journey.svg", build_journey),
        ("profile-bring.svg", build_bring),
        ("profile-stack.svg", build_stack),
        ("profile-principles.svg", build_style),
    ]
    for project in PROJECTS:
        graphics.append((f"project-{project['name']}.svg", lambda p=project: build_project(p)))
    for name, build in graphics:
        svg = build()
        svg = svg.replace("__FONT_FACES__", font_faces(svg))
        # Only references count; a card may show a URL as text in its install command.
        if re.search(r'(?:href|src)="(?:https?:)?//|url\((?:["\']?)(?:https?:)?//', svg):
            raise SystemExit(f"external reference found in {name}")
        ET.fromstring(svg)  # well-formed, or this raises
        path = ASSETS / name
        path.write_text(svg, encoding="utf-8")
        print(f"Wrote {path.relative_to(ROOT)} ({len(svg.encode()) / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
