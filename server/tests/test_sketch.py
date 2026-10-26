"""Pass 1 of the sketch reading on synthetic hand-drawn diagrams (no model)."""

from inkbridge.sketch import read_sketch


def stroke(eid, pts, **extra):
    x0, y0 = pts[0]
    return {
        "id": eid,
        "type": "freedraw",
        "x": x0,
        "y": y0,
        "points": [[px - x0, py - y0] for px, py in pts],
        "pressures": [0.5] * len(pts),
        **extra,
    }


def loop(eid, x, y, w, h, gap=3):
    """A hand-drawn box: around the perimeter, ending a few px short of where it started."""
    pts = [(x, y)]
    for t in range(1, 11):
        pts.append((x + w * t / 10, y))
    for t in range(1, 11):
        pts.append((x + w, y + h * t / 10))
    for t in range(1, 11):
        pts.append((x + w - w * t / 10, y + h))
    for t in range(1, 11):
        pts.append((x, y + h - (h - gap) * t / 10))
    return stroke(eid, pts)


def line(eid, a, b, n=10):
    return stroke(
        eid, [(a[0] + (b[0] - a[0]) * t / n, a[1] + (b[1] - a[1]) * t / n) for t in range(n + 1)]
    )


def v_head(eid, tip, pointing="right", size=10):
    s = -1 if pointing == "right" else 1
    return stroke(
        eid, [(tip[0] + s * size, tip[1] - size), tip, (tip[0] + s * size, tip[1] + size)]
    )


def by_id(result, key):
    return {x["id"]: x for x in result[key]}


def test_two_boxes_and_an_arrow_with_a_separate_head():
    els = [
        loop("box1", 0, 0, 100, 60),
        loop("box2", 300, 0, 100, 60),
        line("shaft", (105, 30), (295, 30)),
        v_head("head", (295, 30)),
    ]
    out = read_sketch(els)
    nodes = by_id(out, "nodes")
    assert set(nodes) == {"N1", "N2"}
    assert nodes["N1"]["element_ids"] == ["box1"] and nodes["N2"]["element_ids"] == ["box2"]
    (arrow,) = out["arrows"]
    assert (arrow["from"], arrow["to"], arrow["head"]) == ("N1", "N2", "end")
    assert arrow["element_ids"] == ["shaft", "head"]
    assert arrow["confidence"] > 0.7
    assert out["unattached"] == []


def test_head_at_the_start_reverses_the_direction():
    # Drawn left to right, but the V is at the left end: the arrow points to the left box.
    els = [
        loop("box1", 0, 0, 100, 60),
        loop("box2", 300, 0, 100, 60),
        line("shaft", (105, 30), (295, 30)),
        v_head("head", (105, 30), pointing="left"),
    ]
    (arrow,) = read_sketch(els)["arrows"]
    assert (arrow["from"], arrow["to"], arrow["head"]) == ("N2", "N1", "end")
    assert arrow["tip"] == {"x": 105, "y": 30}


def test_a_hook_drawn_in_one_stroke_marks_the_head():
    # One stroke: the shaft to the right box, then back up-left (the head's barb).
    pts = [(105 + 19 * t, 30) for t in range(11)] + [(285, 22), (278, 15)]
    els = [loop("box1", 0, 0, 100, 60), loop("box2", 300, 0, 100, 60), stroke("hooked", pts)]
    (arrow,) = read_sketch(els)["arrows"]
    assert (arrow["from"], arrow["to"], arrow["head"]) == ("N1", "N2", "end")
    assert arrow["tip"] == {"x": 295, "y": 30}


def test_an_arrow_without_a_head_keeps_drawing_order_with_low_confidence():
    els = [
        loop("box1", 0, 0, 100, 60),
        loop("box2", 300, 0, 100, 60),
        line("shaft", (295, 30), (105, 30)),
    ]
    (arrow,) = read_sketch(els)["arrows"]
    assert (arrow["from"], arrow["to"], arrow["head"]) == ("N2", "N1", None)
    assert arrow["confidence"] <= 0.5


def test_ink_inside_a_box_is_its_label_not_an_arrow():
    els = [
        loop("box1", 0, 0, 100, 60),
        loop("box2", 300, 0, 100, 60),
        line("letter", (30, 20), (60, 40), n=3),  # handwriting inside box1
        line("shaft", (105, 30), (295, 30)),
        v_head("head", (295, 30)),
    ]
    out = read_sketch(els)
    assert by_id(out, "nodes")["N1"]["label_element_ids"] == ["letter"]
    assert len(out["arrows"]) == 1


def test_a_stroke_touching_one_node_is_unattached():
    els = [loop("box1", 0, 0, 100, 60), line("dangling", (105, 30), (250, 200))]
    out = read_sketch(els)
    assert out["arrows"] == [] and out["unattached"] == ["dangling"]


def test_small_loops_are_letters_not_nodes():
    els = [loop("o", 0, 0, 8, 8, gap=1), loop("box", 100, 0, 100, 60)]
    assert [n["element_ids"] for n in read_sketch(els)["nodes"]] == [["box"]]


def test_an_open_curve_is_not_a_node():
    u = stroke("u", [(0, 0), (0, 60), (100, 60), (100, 0)])  # three sides only
    assert read_sketch([u])["nodes"] == []


def test_nodes_are_numbered_in_reading_order():
    els = [
        loop("bottom", 0, 200, 100, 60),
        loop("top-right", 300, 0, 100, 60),
        loop("top-left", 0, 5, 100, 60),
    ]
    order = [n["element_ids"][0] for n in read_sketch(els)["nodes"]]
    assert order == ["top-left", "top-right", "bottom"]


def test_native_shapes_and_arrows_are_read_exactly():
    els = [
        {"id": "r", "type": "rectangle", "x": 0, "y": 0, "width": 100, "height": 50},
        {
            "id": "t",
            "type": "text",
            "x": 20,
            "y": 15,
            "width": 40,
            "height": 20,
            "text": "Start",
            "containerId": "r",
        },
        {"id": "d", "type": "diamond", "x": 0, "y": 200, "width": 100, "height": 80},
        {
            "id": "a",
            "type": "arrow",
            "x": 50,
            "y": 55,
            "points": [[0, 0], [0, 140]],
            "startArrowhead": None,
            "endArrowhead": "arrow",
        },
    ]
    out = read_sketch(els)
    nodes = by_id(out, "nodes")
    assert nodes["N1"]["label_text"] == "Start" and nodes["N1"]["confidence"] == 1.0
    (arrow,) = out["arrows"]
    assert (arrow["from"], arrow["to"], arrow["head"], arrow["confidence"]) == (
        "N1",
        "N2",
        "end",
        1.0,
    )


def test_deleted_elements_are_ignored():
    els = [loop("box1", 0, 0, 100, 60), {**loop("box2", 300, 0, 100, 60), "isDeleted": True}]
    assert len(read_sketch(els)["nodes"]) == 1


def test_a_three_node_chain_reads_two_arrows():
    els = [
        loop("a", 0, 0, 100, 60),
        loop("b", 300, 0, 100, 60),
        loop("c", 300, 200, 100, 60),
        line("ab", (105, 30), (295, 30)),
        v_head("abh", (295, 30)),
        line("bc", (350, 65), (350, 195)),
        stroke("bch", [(340, 185), (350, 195), (360, 185)]),
    ]
    out = read_sketch(els)
    pairs = sorted((a["from"], a["to"]) for a in out["arrows"])
    assert pairs == [("N1", "N2"), ("N2", "N3")]
    assert all(a["head"] == "end" for a in out["arrows"])


def test_marker_image_puts_labels_on_node_centres_and_arrow_tips():
    import io

    from PIL import Image

    from inkbridge.sketch_image import ARROW_COLOUR, NODE_COLOUR, PAD, render_markers

    els = [
        loop("box1", 0, 0, 100, 60),
        loop("box2", 300, 0, 100, 60),
        line("shaft", (105, 30), (295, 30)),
        v_head("head", (295, 30)),
    ]
    structure = read_sketch(els)
    png, markers = render_markers(els, structure)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    scale = 2.0  # a 400 px wide sketch is drawn at the maximum scale
    assert img.size == (round(400 * scale) + 2 * PAD, round(60 * scale) + 2 * PAD)
    at = {m["id"]: (m["x"], m["y"]) for m in markers}
    assert at["N1"] == (PAD + 50 * scale, PAD + 30 * scale)
    assert at["N2"] == (PAD + 350 * scale, PAD + 30 * scale)
    assert at["A1"] == (PAD + 295 * scale, PAD + 30 * scale)

    def colour_near(x, y):  # a badge pixel off the label glyph
        return img.getpixel((round(x), round(y) - 10))

    assert colour_near(*at["N1"]) == NODE_COLOUR
    assert colour_near(*at["N2"]) == NODE_COLOUR
    assert colour_near(*at["A1"]) == ARROW_COLOUR
    assert img.getpixel((2, 2)) == (255, 255, 255)


def test_marker_image_is_capped_in_width():
    from inkbridge.sketch_image import render_markers

    els = [loop("wide", 0, 0, 5000, 60)]
    png, _ = render_markers(els, read_sketch(els), max_width=1024)
    import io

    from PIL import Image

    assert Image.open(io.BytesIO(png)).size[0] <= 1024


def test_unattached_strokes_get_grey_markers():
    from inkbridge.sketch_image import render_markers

    els = [loop("box1", 0, 0, 100, 60), line("dangling", (105, 30), (250, 200))]
    _, markers = render_markers(els, read_sketch(els))
    (u,) = [m for m in markers if m["id"].startswith("U")]
    assert u["id"] == "U1" and u["element_id"] == "dangling"
