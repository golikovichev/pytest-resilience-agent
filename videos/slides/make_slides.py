"""Slide deck for the pytest-resilience-agent demo video.

10 slides, 180 seconds total, story arc:
  01 title             15s
  02 problem           18s
  03 the gap           15s
  04 lark failures     18s
  05 generator         22s
  06 pytest run        22s
  07 resolution loop   18s
  08 architecture      22s
  09 built with        15s
  10 tagout            15s

Run: python videos/slides/make_slides.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
W, H = 1920, 1080

# Palette
BG_TOP = (16, 18, 32)
BG_BOT = (8, 10, 18)
FG = (244, 244, 248)
FG_DIM = (170, 174, 188)
INDIGO = (140, 170, 255)
EMBER = (250, 155, 80)
EMBER_DEEP = (215, 110, 55)
PURPLE = (200, 130, 230)
TEAL = (130, 210, 200)
RED_SOFT = (240, 130, 130)
GREEN_SOFT = (140, 220, 150)
RIBBON_BG = (18, 20, 32)
RIBBON_BORDER = (38, 42, 60)
PANEL = (14, 16, 26)


def f_inter(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    name_map = {
        "Regular": "Inter-Regular.ttf",
        "SemiBold": "Inter-SemiBold.ttf",
        "Bold": "Inter-Bold.ttf",
        "DisplayBold": "InterDisplay-Bold.ttf",
        "DisplayBlack": "InterDisplay-Black.ttf",
    }
    candidates = [
        Path(r"C:\Users\golik\AppData\Local\Microsoft\Windows\Fonts")
        / name_map.get(weight, "Inter-Regular.ttf"),
        Path(r"C:\Windows\Fonts\segoeuib.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def f_mono(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Users\golik\AppData\Local\Microsoft\Windows\Fonts\JetBrainsMono-Regular.ttf"),
        Path(r"C:\Windows\Fonts\consola.ttf"),
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def gradient_bg(img: Image.Image) -> None:
    px = img.load()
    for y in range(H):
        t = y / H
        r = int(BG_TOP[0] * (1 - t) + BG_BOT[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOT[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOT[2] * t)
        for x in range(W):
            px[x, y] = (r, g, b)


def ember_glow(img: Image.Image, cx: int, cy: int, radius: int = 320) -> None:
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for i in range(8, 0, -1):
        alpha = i / 8
        r_i = int(radius * (1 - i / 10))
        col = (
            int(EMBER[0] * alpha * 0.28),
            int(EMBER[1] * alpha * 0.16),
            int(EMBER[2] * alpha * 0.06),
        )
        gd.ellipse([cx - r_i, cy - r_i, cx + r_i, cy + r_i], fill=col)
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    base = Image.new("RGB", (W, H))
    base.paste(img)
    base = Image.blend(base, glow, 0.55)
    img.paste(base)


def shield_mark(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 100) -> None:
    """A simple shield mark suggesting resilience / protection."""
    s = size
    outer = [
        (cx, cy - s),
        (cx - int(s * 0.7), cy - int(s * 0.5)),
        (cx - int(s * 0.7), cy + int(s * 0.2)),
        (cx, cy + s),
        (cx + int(s * 0.7), cy + int(s * 0.2)),
        (cx + int(s * 0.7), cy - int(s * 0.5)),
    ]
    draw.polygon(outer, fill=EMBER)
    inner = [
        (cx, cy - int(s * 0.6)),
        (cx - int(s * 0.42), cy - int(s * 0.3)),
        (cx - int(s * 0.42), cy + int(s * 0.1)),
        (cx, cy + int(s * 0.55)),
        (cx + int(s * 0.42), cy + int(s * 0.1)),
        (cx + int(s * 0.42), cy - int(s * 0.3)),
    ]
    draw.polygon(inner, fill=EMBER_DEEP)
    # Center check
    check = [
        (cx - int(s * 0.18), cy),
        (cx - int(s * 0.05), cy + int(s * 0.18)),
        (cx + int(s * 0.25), cy - int(s * 0.18)),
    ]
    draw.line(check, fill=(255, 235, 200), width=8)


def gradient_text(img: Image.Image, text: str, font_obj, y: int, c1=EMBER, c2=INDIGO) -> None:
    bbox = ImageDraw.Draw(img).textbbox((0, 0), text, font=font_obj)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (W - tw) // 2
    grad = Image.new("RGB", (tw, th))
    gd = ImageDraw.Draw(grad)
    for i in range(tw):
        t = i / max(tw - 1, 1)
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        gd.rectangle([i, 0, i + 1, th], fill=(r, g, b))
    mask = Image.new("L", (tw, th), 0)
    md = ImageDraw.Draw(mask)
    md.text((-bbox[0], -bbox[1]), text, font=font_obj, fill=255)
    img.paste(grad, (x, y), mask)


def slide_chrome(draw: ImageDraw.ImageDraw, slide_num: str) -> None:
    for i in range(4):
        intensity = 1.0 - i / 4
        col = tuple(int(c * intensity) for c in EMBER)
        draw.rectangle([0, i, W, i + 1], fill=col)
    rib_y = H - 56
    draw.rectangle([0, rib_y, W, H], fill=RIBBON_BG)
    draw.line([(0, rib_y), (W, rib_y)], fill=RIBBON_BORDER, width=1)
    draw.text((40, rib_y + 16), "pytest-resilience-agent", fill=EMBER, font=f_inter(20, "SemiBold"))
    draw.text((290, rib_y + 18), "DevNetwork AI + ML Hackathon 2026", fill=FG_DIM, font=f_inter(18))
    right = "Lark + TrueFoundry tracks"
    bb = draw.textbbox((0, 0), right, font=f_inter(18))
    draw.text((W - (bb[2] - bb[0]) - 40, rib_y + 18), right, fill=FG_DIM, font=f_inter(18))
    draw.text((W - 90, 26), f"{slide_num} / 10", fill=FG_DIM, font=f_inter(16, "SemiBold"))


def base_slide(slide_num: str) -> Image.Image:
    img = Image.new("RGB", (W, H), BG_BOT)
    gradient_bg(img)
    draw = ImageDraw.Draw(img)
    slide_chrome(draw, slide_num)
    return img


def section_header(draw: ImageDraw.ImageDraw, title: str, subtitle: str = "") -> int:
    draw.text((60, 36), title, fill=FG, font=f_inter(34, "Bold"))
    if subtitle:
        draw.text((60, 86), subtitle, fill=FG_DIM, font=f_inter(20))
    draw.rectangle([60, 130, 60 + 80, 133], fill=EMBER)
    return 170


# ===========================================================================
# Slide 01 - title
# ===========================================================================


def slide_01_title() -> None:
    img = Image.new("RGB", (W, H), BG_BOT)
    gradient_bg(img)
    ember_glow(img, W // 2, 280, radius=380)
    draw = ImageDraw.Draw(img)
    slide_chrome(draw, "01")
    shield_mark(draw, W // 2, 280, size=100)
    gradient_text(img, "pytest-resilience-agent", f_inter(140, "DisplayBlack"), 420)
    draw = ImageDraw.Draw(img)
    accent_x = (W - 220) // 2
    for i in range(4):
        alpha = 1.0 - i * 0.2
        col = tuple(int(c * alpha) for c in EMBER)
        draw.rectangle([accent_x, 620 + i, accent_x + 220, 620 + i + 1], fill=col)
    sub = "Auto-generated resilience tests for LLM applications"
    sf = f_inter(46, "SemiBold")
    bb = draw.textbbox((0, 0), sub, font=sf)
    draw.text(((W - (bb[2] - bb[0])) // 2, 670), sub, fill=INDIGO, font=sf)
    tag = "Lark MCP  +  TrueFoundry AI Gateway  +  pytest  +  respx"
    tf = f_inter(26)
    bb = draw.textbbox((0, 0), tag, font=tf)
    draw.text(((W - (bb[2] - bb[0])) // 2, 770), tag, fill=FG_DIM, font=tf)
    img.save(HERE / "beat-01-title.png")
    print("wrote beat-01-title.png")


# ===========================================================================
# Slide 02 - problem
# ===========================================================================


def slide_02_problem() -> None:
    img = base_slide("02")
    draw = ImageDraw.Draw(img)
    y = section_header(
        draw, "The 2:14am problem", "your LLM feature ships, your eval suite is green"
    )
    bullets = [
        ("02:14", "Saturday. PagerDuty fires. Your LLM agent stopped responding."),
        ("Root cause", "primary model browned out, fallback never engaged."),
        ("Eval suite", "still 100% green. It scored a clean path."),
        ("The gap", "no test injected chaos at the gateway layer."),
    ]
    body_f = f_inter(28)
    label_f = f_inter(28, "Bold")
    label_col_x = 80
    text_col_x = 360
    yy = y + 50
    for label, text in bullets:
        draw.text((label_col_x, yy), label, fill=EMBER, font=label_f)
        draw.text((text_col_x, yy), text, fill=FG, font=body_f)
        yy += 80
    img.save(HERE / "beat-02-problem.png")
    print("wrote beat-02-problem.png")


# ===========================================================================
# Slide 03 - the gap
# ===========================================================================


def slide_03_gap() -> None:
    img = base_slide("03")
    draw = ImageDraw.Draw(img)
    y = section_header(
        draw,
        "Eval frameworks score the clean path",
        "production failure modes are a different axis",
    )
    mid_x = W // 2
    left_box = (60, y + 60, mid_x - 30, H - 130)
    right_box = (mid_x + 30, y + 60, W - 60, H - 130)
    draw.rectangle(left_box, fill=PANEL, outline=RIBBON_BORDER, width=2)
    draw.rectangle(right_box, fill=PANEL, outline=RIBBON_BORDER, width=2)
    head_f = f_inter(34, "Bold")
    body_f = f_inter(26)
    draw.text((90, y + 90), "Eval frameworks", fill=INDIGO, font=head_f)
    draw.text((90, y + 150), "spec into eval into score", fill=FG_DIM, font=body_f)
    pts_left = [
        "predict failures you can imagine",
        "best for new feature gates",
        "DeepEval, Opik, pytest-evals",
    ]
    yy = y + 230
    for pt in pts_left:
        draw.ellipse([90, yy + 12, 102, yy + 24], fill=INDIGO)
        draw.text((120, yy), pt, fill=FG, font=body_f)
        yy += 70
    draw.text((mid_x + 60, y + 90), "Resilience tests", fill=EMBER, font=head_f)
    draw.text((mid_x + 60, y + 150), "chaos into agent into contract", fill=FG_DIM, font=body_f)
    pts_right = [
        "inject what production throws",
        "best for regression on infra",
        "pytest-resilience-agent",
    ]
    yy = y + 230
    for pt in pts_right:
        draw.ellipse([mid_x + 60, yy + 12, mid_x + 72, yy + 24], fill=EMBER)
        draw.text((mid_x + 90, yy), pt, fill=FG, font=body_f)
        yy += 70
    foot = "Both axes matter. They compose without overlap."
    ff = f_inter(28, "SemiBold")
    bb = draw.textbbox((0, 0), foot, font=ff)
    draw.text(((W - (bb[2] - bb[0])) // 2, H - 110), foot, fill=FG_DIM, font=ff)
    img.save(HERE / "beat-03-gap.png")
    print("wrote beat-03-gap.png")


# ===========================================================================
# Slide 04 - Lark lists failures
# ===========================================================================


def slide_04_lark() -> None:
    img = base_slide("04")
    draw = ImageDraw.Draw(img)
    y = section_header(
        draw,
        "Step 1. Lark MCP lists failing tests",
        "real signal from your project, not an imagined failure",
    )
    panel_x0, panel_y0 = 60, y + 40
    panel_x1, panel_y1 = W - 60, H - 100
    draw.rectangle(
        [panel_x0, panel_y0, panel_x1, panel_y1], fill=PANEL, outline=RIBBON_BORDER, width=1
    )
    mono = f_mono(22)
    header = "$  pytest-resilience-agent --lark-url http://lark.local discover"
    draw.text((panel_x0 + 30, panel_y0 + 30), header, fill=GREEN_SOFT, font=mono)
    rows = [
        (
            "test_summarise_keeps_responding_when_gateway_429",
            "httpx.HTTPStatusError: 429 Too Many Requests",
        ),
        ("test_summarise_falls_back_when_primary_5xx", "httpx.HTTPStatusError: 502 Bad Gateway"),
        (
            "test_summarise_surfaces_clean_error_on_persistent_outage",
            "httpx.HTTPStatusError: 503 Service Unavailable",
        ),
    ]
    yy = panel_y0 + 100
    for name, fail in rows:
        draw.text((panel_x0 + 30, yy), name, fill=INDIGO, font=mono)
        draw.text((panel_x0 + 30, yy + 36), "  last_failure: " + fail, fill=RED_SOFT, font=mono)
        yy += 100
    img.save(HERE / "beat-04-lark.png")
    print("wrote beat-04-lark.png")


# ===========================================================================
# Slide 05 - generator
# ===========================================================================


def slide_05_generator() -> None:
    img = base_slide("05")
    draw = ImageDraw.Draw(img)
    y = section_header(
        draw,
        "Step 2. Generator picks chaos scenarios",
        "regex rules map failure text to scenario set; deterministic, auditable",
    )
    panel_x0, panel_y0 = 60, y + 40
    panel_x1, panel_y1 = W - 60, H - 100
    draw.rectangle(
        [panel_x0, panel_y0, panel_x1, panel_y1], fill=PANEL, outline=RIBBON_BORDER, width=1
    )
    mono = f_mono(22)
    lines = [
        ("kw", "# generator.py - rule table"),
        ("fg", ""),
        ("str", '  (r"\\b429\\b|too many requests",  ["rate_limit"]),'),
        ("str", '  (r"\\b502\\b|bad gateway",        ["llm_5xx"]),'),
        ("str", '  (r"\\b503\\b|service unavail",    ["partial_outage"]),'),
        ("str", '  (r"\\b504\\b|timeout",            ["llm_timeout"]),'),
        ("str", '  (r"\\b402\\b|quota|cost",         ["cost_exceeded"]),'),
        ("str", '  (r"connect.*(error|refused)",     ["network_blip"]),'),
        ("str", '  (r"empty|truncated|stream",       ["stream_stall"]),'),
        ("str", '  (r"mcp|tool.*error|jsonrpc",      ["mcp_error"]),'),
        ("str", '  (r"wrong.*model|mismatch",        ["wrong_model_returned"]),'),
        ("fg", ""),
        ("kw", "# 429 in failure text -> rate_limit scenario"),
        ("kw", "# 502 in failure text -> llm_5xx scenario"),
        ("kw", "# 503 in failure text -> partial_outage scenario"),
    ]
    palette = {"kw": PURPLE, "str": EMBER, "fg": FG}
    yy = panel_y0 + 30
    for kind, text in lines:
        draw.text((panel_x0 + 30, yy), text, fill=palette[kind], font=mono)
        yy += 34
    img.save(HERE / "beat-05-generator.png")
    print("wrote beat-05-generator.png")


# ===========================================================================
# Slide 06 - pytest run
# ===========================================================================


def slide_06_pytest() -> None:
    img = base_slide("06")
    draw = ImageDraw.Draw(img)
    y = section_header(
        draw,
        "Step 3. respx injects faults at HTTP layer",
        "the agent under test sees a real broken gateway, not a mocked client",
    )
    panel_x0, panel_y0 = 60, y + 40
    panel_x1, panel_y1 = W - 60, H - 100
    draw.rectangle(
        [panel_x0, panel_y0, panel_x1, panel_y1], fill=PANEL, outline=RIBBON_BORDER, width=1
    )
    mono = f_mono(22)
    lines = [
        ("green", "$  pytest test_summarise_keeps_responding_resilience.py -v"),
        ("fg", ""),
        ("fg", "test_summarise_keeps_responding_resilience PASSED  [100%]"),
        ("fg", ""),
        ("kw", "# under the hood:"),
        ("fg", "  chaos.enter()           respx mock starts"),
        ("fg", "  rate_limit applied      first POST returns 429 + Retry-After"),
        ("fg", "  agent retries           second POST returns 200"),
        ("fg", "  contract verified       reply.content non-empty"),
        ("fg", "  chaos.exit()            respx mock stops"),
        ("fg", ""),
        ("green", "  1 passed in 0.18s"),
    ]
    palette = {"kw": PURPLE, "green": GREEN_SOFT, "fg": FG}
    yy = panel_y0 + 30
    for kind, text in lines:
        draw.text((panel_x0 + 30, yy), text, fill=palette[kind], font=mono)
        yy += 38
    img.save(HERE / "beat-06-pytest.png")
    print("wrote beat-06-pytest.png")


# ===========================================================================
# Slide 07 - resolution loop
# ===========================================================================


def slide_07_loop() -> None:
    img = base_slide("07")
    draw = ImageDraw.Draw(img)
    y = section_header(
        draw,
        "Step 4. Report resolution back to Lark",
        "failure UI shows the new pytest path next to the original failure",
    )
    panel_x0, panel_y0 = 60, y + 40
    panel_x1, panel_y1 = W - 60, H - 100
    draw.rectangle(
        [panel_x0, panel_y0, panel_x1, panel_y1], fill=PANEL, outline=RIBBON_BORDER, width=1
    )
    mono = f_mono(24)
    lines = [
        ("green", "Round-trip summary"),
        ("fg", ""),
        ("fg", "rate_limit       test_summarise_keeps_responding...   PASS"),
        ("fg", "llm_5xx          test_summarise_falls_back_when...    PASS"),
        ("fg", "partial_outage   test_summarise_surfaces_clean_err... PASS"),
        ("fg", ""),
        ("green", "Resolutions reported to Lark: 3 / 3"),
        ("fg", ""),
        ("kw", "# the loop closes:"),
        ("fg", "  failure observed -> test generated -> chaos verified -> resolution logged"),
    ]
    palette = {"green": GREEN_SOFT, "kw": PURPLE, "fg": FG}
    yy = panel_y0 + 40
    for kind, text in lines:
        draw.text((panel_x0 + 30, yy), text, fill=palette[kind], font=mono)
        yy += 44
    img.save(HERE / "beat-07-loop.png")
    print("wrote beat-07-loop.png")


# ===========================================================================
# Slide 08 - architecture
# ===========================================================================


def slide_08_arch() -> None:
    img = base_slide("08")
    draw = ImageDraw.Draw(img)
    section_header(
        draw, "Architecture", "one pytest plugin, two MCP integrations, transport-layer chaos"
    )
    head_f = f_inter(24, "Bold")
    body_f = f_inter(20)
    boxes = [
        ("pytest test", "@mark.resilience\nscenarios=[...]", 150, 280, 450, 480, INDIGO),
        ("ChaosController", "respx mock router\n9 chaos scenarios", 480, 280, 780, 480, EMBER),
        ("App under test", "your LLM agent\ncode, unchanged", 810, 280, 1110, 480, GREEN_SOFT),
        (
            "TrueFoundry Gateway",
            "OpenAI-compatible\nfallback chain\nretries",
            1140,
            280,
            1440,
            480,
            INDIGO,
        ),
        ("Lark MCP", "list_failing_tests\nreport_resolved", 1470, 280, 1770, 480, PURPLE),
    ]
    for label, sub, x0, y0, x1, y1, col in boxes:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=14, fill=PANEL, outline=col, width=2)
        draw.text((x0 + 20, y0 + 30), label, fill=col, font=head_f)
        for i, line in enumerate(sub.split("\n")):
            draw.text((x0 + 20, y0 + 90 + i * 36), line, fill=FG_DIM, font=body_f)
    # Arrows
    arrows = [
        (450, 380, 480, 380),
        (780, 380, 810, 380),
        (1110, 380, 1140, 380),
        (1440, 380, 1470, 380),
    ]
    for x0, y0, x1, y1 in arrows:
        draw.line([(x0, y0), (x1, y1)], fill=FG_DIM, width=3)
        draw.polygon([(x1, y1), (x1 - 12, y1 - 6), (x1 - 12, y1 + 6)], fill=FG_DIM)
    # Bottom note
    note = "respx intercepts every httpx call. Same scenarios work for OpenAI SDK, Anthropic SDK, raw httpx."
    nf = f_inter(24)
    bb = draw.textbbox((0, 0), note, font=nf)
    draw.text(((W - (bb[2] - bb[0])) // 2, 680), note, fill=FG_DIM, font=nf)
    img.save(HERE / "beat-08-arch.png")
    print("wrote beat-08-arch.png")


# ===========================================================================
# Slide 09 - built with
# ===========================================================================


def slide_09_built() -> None:
    img = base_slide("09")
    draw = ImageDraw.Draw(img)
    y = section_header(
        draw, "Built with", "everything ships in the repo; clone and run with zero accounts"
    )
    chips = [
        "Python 3.11+",
        "pytest 8",
        "respx",
        "httpx",
        "FastAPI",
        "Lark MCP",
        "TrueFoundry",
        "OpenTelemetry",
        "Rich",
        "Pydantic",
    ]
    chip_f = f_inter(28, "SemiBold")
    chip_y = y + 80
    widths = []
    for c in chips:
        bb = draw.textbbox((0, 0), c, font=chip_f)
        widths.append(bb[2] - bb[0] + 60)
    # Two rows so chips fit
    row1 = chips[:5]
    row2 = chips[5:]
    w1 = [widths[i] for i in range(5)]
    w2 = [widths[i] for i in range(5, len(chips))]
    gap = 28
    total_w1 = sum(w1) + gap * (len(row1) - 1)
    total_w2 = sum(w2) + gap * (len(row2) - 1)
    cx = (W - total_w1) // 2
    for c, w in zip(row1, w1, strict=True):
        draw.rounded_rectangle(
            [cx, chip_y, cx + w, chip_y + 70], radius=16, outline=EMBER, width=2, fill=PANEL
        )
        bb = draw.textbbox((0, 0), c, font=chip_f)
        tw = bb[2] - bb[0]
        draw.text((cx + (w - tw) // 2, chip_y + 18), c, fill=FG, font=chip_f)
        cx += w + gap
    cx = (W - total_w2) // 2
    chip_y2 = chip_y + 110
    for c, w in zip(row2, w2, strict=True):
        draw.rounded_rectangle(
            [cx, chip_y2, cx + w, chip_y2 + 70], radius=16, outline=INDIGO, width=2, fill=PANEL
        )
        bb = draw.textbbox((0, 0), c, font=chip_f)
        tw = bb[2] - bb[0]
        draw.text((cx + (w - tw) // 2, chip_y2 + 18), c, fill=FG, font=chip_f)
        cx += w + gap
    foot = "16 tests passing, 9 chaos scenarios, full loop in one command."
    ff = f_inter(28, "SemiBold")
    bb = draw.textbbox((0, 0), foot, font=ff)
    draw.text(((W - (bb[2] - bb[0])) // 2, chip_y2 + 160), foot, fill=GREEN_SOFT, font=ff)
    img.save(HERE / "beat-09-built.png")
    print("wrote beat-09-built.png")


# ===========================================================================
# Slide 10 - tagout
# ===========================================================================


def slide_10_tagout() -> None:
    img = Image.new("RGB", (W, H), BG_BOT)
    gradient_bg(img)
    ember_glow(img, W // 2, 240, radius=380)
    draw = ImageDraw.Draw(img)
    slide_chrome(draw, "10")
    shield_mark(draw, W // 2, 240, size=100)
    gradient_text(img, "pytest-resilience-agent", f_inter(120, "DisplayBlack"), 380)
    draw = ImageDraw.Draw(img)
    accent_x = (W - 220) // 2
    for i in range(4):
        alpha = 1.0 - i * 0.2
        col = tuple(int(c * alpha) for c in EMBER)
        draw.rectangle([accent_x, 560 + i, accent_x + 220, 560 + i + 1], fill=col)
    url = "github.com/golikovichev/pytest-resilience-agent"
    uf = f_inter(44, "SemiBold")
    bb = draw.textbbox((0, 0), url, font=uf)
    uw = bb[2] - bb[0]
    ux = (W - uw) // 2
    draw.text((ux, 610), url, fill=INDIGO, font=uf)
    draw.rectangle([ux, 670, ux + uw, 673], fill=INDIGO)
    chips = ["Lark MCP", "TrueFoundry Gateway", "9 chaos scenarios", "pytest plugin"]
    cf = f_inter(22, "SemiBold")
    chip_y = 740
    widths = [
        draw.textbbox((0, 0), c, font=cf)[2] - draw.textbbox((0, 0), c, font=cf)[0] + 40
        for c in chips
    ]
    gap = 22
    total_w = sum(widths) + gap * (len(chips) - 1)
    cx = (W - total_w) // 2
    for c, w in zip(chips, widths, strict=True):
        draw.rounded_rectangle(
            [cx, chip_y, cx + w, chip_y + 50], radius=12, outline=RIBBON_BORDER, width=2, fill=PANEL
        )
        bb = draw.textbbox((0, 0), c, font=cf)
        tw = bb[2] - bb[0]
        draw.text((cx + (w - tw) // 2, chip_y + 11), c, fill=FG, font=cf)
        cx += w + gap
    thanks = "Thanks for watching"
    tf = f_inter(34, "Bold")
    bb = draw.textbbox((0, 0), thanks, font=tf)
    draw.text(((W - (bb[2] - bb[0])) // 2, 850), thanks, fill=FG, font=tf)
    img.save(HERE / "beat-10-tagout.png")
    print("wrote beat-10-tagout.png")


def main() -> None:
    slide_01_title()
    slide_02_problem()
    slide_03_gap()
    slide_04_lark()
    slide_05_generator()
    slide_06_pytest()
    slide_07_loop()
    slide_08_arch()
    slide_09_built()
    slide_10_tagout()


if __name__ == "__main__":
    main()
