"""Centre selection for home thumbnails (INK-179, decision 0084). Boxes only, no images."""

from inkbridge.canvas import thumb_focus as tf
from inkbridge.canvas.thumb_focus import choose_focus, median_centre

EXTENT = (0.0, 0.0, 2000.0, 1000.0)


def box(x, y, w, h):
    return (float(x), float(y), float(x + w), float(y + h))


def test_median_centre_ignores_far_outlier():
    boxes = [box(0, 0, 10, 10), box(20, 0, 10, 10), box(40, 0, 10, 10), box(100000, 90000, 10, 10)]
    cx, cy = median_centre(boxes)
    assert (cx, cy) == (35.0, 5.0)  # median of 5, 25, 45, 100005 and of 5,5,5,90005


def test_nearest_chunk_to_median_centre_not_biggest_or_first():
    prims = [box(i * 10, 500, 5, 5) for i in range(100, 105)]  # centre around x=1020
    chunks = [box(0, 0, 900, 900), box(1000, 480, 60, 60), box(1500, 0, 400, 400)]
    assert choose_focus(prims, chunks, EXTENT) == chunks[1]


def test_two_equal_clusters_pick_top_left_deterministically():
    left, right = box(100, 100, 400, 300), box(1500, 100, 400, 300)
    prims = [box(100 + i * 10, 100, 5, 5) for i in range(5)] + [
        box(1500 + i * 10, 100, 5, 5) for i in range(5)
    ]
    first = choose_focus(prims, [left, right], EXTENT)
    assert first == left
    assert choose_focus(prims, [left, right], EXTENT) == first
    assert choose_focus(prims[::-1], [right, left], EXTENT) == left


def test_tiny_centre_chunk_grows_to_near_neighbours_only():
    core = box(980, 480, 40, 40)
    near = box(1050, 480, 40, 40)  # 30 away
    far = box(2900, 480, 40, 40)
    got = choose_focus([core, near, far], [core, near, far], (0.0, 0.0, 3000.0, 1000.0))
    assert got == (980.0, 480.0, 1090.0, 520.0)


def test_tiny_centre_skips_neighbour_over_cap():
    core = box(980, 480, 40, 40)
    # extent 2000 wide -> cap 500: this neighbour is within reach (gap 30) but the union is 670 wide
    wide = box(1050, 480, 600, 40)
    got = choose_focus([core, core, wide], [core, wide], EXTENT)
    assert got == core


def test_non_tiny_centre_chunk_returned_as_is():
    core = box(800, 300, 400, 400)
    neighbour = box(1210, 300, 100, 100)
    assert choose_focus([core, core, neighbour], [core, neighbour], EXTENT) == core


def test_no_chunks_floods_around_nearest_primitive():
    cluster = [box(1000 + i * 12, 500, 10, 10) for i in range(5)]
    stray = box(6000, 500, 10, 10)
    got = choose_focus(cluster + [stray], [], (0.0, 0.0, 7000.0, 1000.0))
    assert got == (1000.0, 500.0, 1058.0, 510.0)


def test_flood_stops_at_max():
    touching = [box(i * 10, 0, 10, 10) for i in range(100)]
    got = choose_focus(touching, [], (0.0, 0.0, 1000.0, 10.0))
    covered = (got[2] - got[0]) / 10
    assert covered <= tf.FLOOD_MAX + 1
    assert covered >= tf.FLOOD_MAX - 1


def test_empty_primitives_is_none():
    assert choose_focus([], [box(0, 0, 10, 10)], EXTENT) is None
