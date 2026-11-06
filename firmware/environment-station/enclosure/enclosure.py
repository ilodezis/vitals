"""Enclosure for the bedroom climate station, generated as STL.

Layout (looking at the front, the box hangs on a wall):
  * Two bays side by side at the bottom: the SCD41 on the left, the ESP32-C3 on
    the right. The sensor bay is closed by a partition and a roof, so the
    ESP32's warm air cannot reach the sensor; a notch in the roof next to the
    partition, open towards the lid, lets the wires drop in. A plug on the lid
    fills the front of the notch when the lid is shut, leaving only the back
    end where the wires pass.
  * The SCD41 does not breathe through vents. Its metal cap pokes into a window
    in the front lid, slightly recessed. A pusher on the back wall, tipped with
    a foam pad, presses the board's back so its front face seals against the
    lid around the window.
  * The ESP32-C3 stands upright on a rib with its USB-C socket flush with the
    bottom of the box, so the cable plugs in from outside. The wall around the
    socket is thinned so the plug seats fully. The rib carries a stop above the
    board's top edge, so pushing a plug in cannot slide the board up; a pulled
    cable is taken by the bottom wall.
  * Slots look the same on both side walls. The ESP32 bay and the space above
    the roof work as a chimney: air comes in low on the right and leaves high
    on both sides. The low slots on the left face the sealed sensor bay, so
    they are blind recesses that only keep the two sides looking alike.
  * No slots on the top face: dust would settle into them and fall onto the
    boards, and the high side slots already let the warm air out.
  * The Wi-Fi antenna sticker goes on the back wall above the bays.
  * Two parts: the body (back and sides) and the lid, held by two 2.2 mm
    countersunk self-tapping screws in opposite corners. The back is flat for
    adhesive mounting strips.

Assembly: plug the Dupont wires onto both boards; stick a foam pad on the
pusher and foam tape on the rib; put the ESP32's USB socket into its opening at
a slant and swing the board back onto the rib, under the stop; lay the SCD41
in its frame on the lid; drop the wires into the roof notch, push them to its
back end and lay them over the partition; close the lid, holding the SCD41 in
its frame with a finger through the window (the frame is a loose fit and holds
nothing on its own), and screw it down. The window goes bottom left: the screws
also line up with the lid turned round, but then the pusher misses the sensor.

Coordinates: x to the right, y up, z out of the wall towards the room. The back
of the body lies at z = 0. All sizes are millimetres, measured with a caliper on
the real modules. The STL files are not in these coordinates: each part is laid
the way it prints, so the slicer needs no turning. The body stands on its back,
the lid lies outer face down.

Usage (needs numpy and manifold3d):
    python enclosure.py                  # checks the fit, writes out/body.stl and out/lid.stl
    python enclosure.py --preview FILE   # also writes the meshes and layout as JSON
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np
from manifold3d import CrossSection, JoinType, Manifold

SEGMENTS = 64

# --- Outer shell ---
WIDTH = 50.0
HEIGHT = 66.0
DEPTH = 36.0  # body and lid together
WALL = 2.0
LID_T = 2.0
CORNER_R = 5.0
BODY_D = DEPTH - LID_T  # the lid sits on the body's front rim

# --- SCD41 module (blue breakout board, header on the back) ---
SCD_BOARD_W = 13.15  # across
SCD_BOARD_L = 21.59  # along, from the pin end to the far end
SCD_BOARD_T = 1.61
SCD_CAP_SIDE = 8.0  # metal cap
SCD_BASE = 10.2  # green base under the cap
SCD_BASE_FROM_END = 1.65  # far end of the board to the green base
SCD_CAP_ABOVE_BOARD = 7.9 - SCD_BOARD_T  # cap top above the board's front face
SCD_BEHIND_BOARD = 22.5 - 7.9  # header plus Dupont housing behind the board
SCD_CAP_CENTER = SCD_BOARD_L - SCD_BASE_FROM_END - SCD_BASE / 2  # from the pin end
SCD_FRONT_PARTS = 8.5  # pins, resistors and capacitor, from the pin end; stops short of the window
# The board's pin-end corner on the lid; the pins point up so the wires leave
# through the roof notch.
SCD_X = 5.0
SCD_TOP = 5.0 + SCD_BOARD_L

# --- SCD41 fit ---
WINDOW = SCD_BASE + 2 * 0.6  # square opening around the green base
WINDOW_CHAMFER = 1.0
CAP_RECESS = 0.8  # cap top sits this far below the outer surface
CLEARANCE = 0.25  # gap between a board edge and its frame, per side
FRAME_WALL = 1.2
FRAME_HEIGHT = 2.5  # above the board seat; the board itself is 1.61
PARTS_RELIEF = 1.5  # pocket under the solder joints and SMD parts

# --- ESP32-C3 SuperMini ---
C3_W = 17.6
C3_W_MAX = 17.78  # across the solder at the edge pins; used for clearances
C3_L = 22.4
C3_PCB_T = 1.2
C3_TOTAL_BEHIND = 18.75 - 4.55  # header plus Dupont housing behind the board
USB_W = 8.82
USB_H = 4.55 - C3_PCB_T  # socket height above the board
USB_LEN = 7.3
USB_OVERHANG = 23.75 - C3_L  # how far the socket sticks out past the board edge
USB_OFFSET = (13.55 - USB_W / 2) - C3_W / 2  # socket centre right of board centre
USB_CLEARANCE = 0.3  # per side, around the socket in the bottom wall
BOTTOM_SKIN = 1.2  # bottom wall thickness around the socket
C3_X = 22.5  # left edge of the board
C3_BOTTOM = BOTTOM_SKIN + 0.1  # board edge, so the socket face ends flush
C3_BACK_Z = 24.2  # back face of the board; leaves room for the wires behind it
TAPE = 1.0  # double-sided foam tape between the rib and the board, 0.8 to 1 mm
STOP_GAP = 0.1  # between the board's top edge and the stop
USB_X = C3_X + C3_W / 2 + USB_OFFSET
USB_Z = C3_BACK_Z + C3_PCB_T + USB_H / 2
RIB_W = 10.0  # fits between the two header rows

# --- Sensor bay: partition and roof ---
PARTITION_X = 20.4
PARTITION_T = 1.6
BAY_TOP = 31.0  # underside of the roof
ROOF_T = 1.6
NOTCH_W = 6.0  # wire notch in the roof, next to the partition
NOTCH_BACK = 6.0  # the notch runs from this z to the lid
PLUG_BACK = 14.0  # the lid's plug fills the notch from this z; the wires lie behind it
PLUG_CLEARANCE = 0.3  # per side, between the plug and the notch

# --- Pusher that holds the SCD41 against the lid ---
PUSHER = 6.0  # square
PUSHER_PAD = 2.0  # foam pad on its tip: two layers of the same 1 mm foam tape
# How much the pad is pressed when the lid is shut, for 1 mm tape. Tape sold as
# 1 mm is often 0.8: the pad then still takes 0.4 mm, a quarter of its thickness.
PUSHER_SQUEEZE = 0.8

# --- Screws, lid lip, vents ---
POST_R = 3.2
POST_INSET = WALL + POST_R
PILOT_R = 0.9  # for the 2.2 mm screws sold as "M2 self-tapping"
PILOT_DEPTH = 12.0
SCREW_R = 1.4  # clearance hole in the lid, so the screw only bites the post
SCREW_HEAD_R = 2.3  # countersunk head up to 4.6 mm
LIP_CLEARANCE = 0.3
EDGE_CHAMFER = 0.4  # on the lid's outer edge, hides the first-layer flare
LIP_T = 1.2
LIP_D = 3.0
VENT_H = 1.6
VENT_Z = (18.0, 30.0)
VENTS_LOW = (8.0, 12.0, 16.0, 20.0)  # right wall open, left wall blind
VENTS_HIGH = (44.0, 48.0, 52.0, 56.0)  # open on both side walls
VENT_BLIND = 1.0  # depth of the blind slots

# --- Antenna sticker (back wall, above the bays) ---
ANTENNA = (42.0, 12.0)
ANTENNA_X = 4.0
ANTENNA_Y = 40.0

PETG_DENSITY = 1.27  # g/cm3; weights below assume a solid print, an upper bound
OUT_DIR = Path(__file__).resolve().parent / "out"


def box(x0: float, y0: float, z0: float, x1: float, y1: float, z1: float) -> Manifold:
    return Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def rounded_rect(x0: float, y0: float, x1: float, y1: float, r: float) -> CrossSection:
    inner = CrossSection.square([x1 - x0 - 2 * r, y1 - y0 - 2 * r]).translate([x0 + r, y0 + r])
    return inner.offset(r, JoinType.Round, circular_segments=SEGMENTS)


def slab(section: CrossSection, z0: float, z1: float) -> Manifold:
    return section.extrude(z1 - z0).translate([0, 0, z0])


def cylinder_z(x: float, y: float, z0: float, z1: float, r: float, r_top: float | None = None) -> Manifold:
    top = r if r_top is None else r_top
    return Manifold.cylinder(z1 - z0, r, top, SEGMENTS).translate([x, y, z0])


def post_centres() -> list[tuple[float, float]]:
    """Screw posts in two opposite corners: top left and bottom right."""
    return [(POST_INSET, HEIGHT - POST_INSET), (WIDTH - POST_INSET, POST_INSET)]


def scd41_mount() -> tuple[Manifold, Manifold]:
    """Boss and frame for the SCD41, plus the material to cut away.

    Built in local coordinates: the board's pin-end corner at the origin, the
    board running along +y, z = 0 on the outer face of the wall and +z inwards.
    The lid prints outer face down, so nothing needs supports.
    """
    seat_z = CAP_RECESS + SCD_CAP_ABOVE_BOARD  # inner face the board rests on
    solid = box(
        -CLEARANCE - FRAME_WALL,
        -CLEARANCE - FRAME_WALL,
        0,
        SCD_BOARD_W + CLEARANCE + FRAME_WALL,
        SCD_BOARD_L + CLEARANCE + FRAME_WALL,
        seat_z + FRAME_HEIGHT,
    )
    # Pocket the board drops into.
    cut = box(
        -CLEARANCE,
        -CLEARANCE,
        seat_z,
        SCD_BOARD_W + CLEARANCE,
        SCD_BOARD_L + CLEARANCE,
        seat_z + FRAME_HEIGHT + 1,
    )
    # Relief under the pin end, where solder joints and SMD parts stick out.
    cut += box(-CLEARANCE, -CLEARANCE, seat_z - PARTS_RELIEF, SCD_BOARD_W + CLEARANCE, SCD_FRONT_PARTS, seat_z + 1)
    # Window for the cap and its green base, with a chamfer on the outside.
    cx, cy = SCD_BOARD_W / 2, SCD_CAP_CENTER
    cut += box(cx - WINDOW / 2, cy - WINDOW / 2, -1, cx + WINDOW / 2, cy + WINDOW / 2, seat_z + 1)
    side_out = WINDOW + 2 * WINDOW_CHAMFER + 1  # at z = -0.5
    chamfer = Manifold.cylinder(WINDOW_CHAMFER + 0.5, side_out / math.sqrt(2), WINDOW / math.sqrt(2), 4)
    cut += chamfer.rotate([0, 0, 45]).translate([cx, cy, -0.5])
    return solid, cut


def scd41_seat_z() -> float:
    """z of the lid's inner face under the SCD41 board, in body coordinates."""
    return DEPTH - (CAP_RECESS + SCD_CAP_ABOVE_BOARD)


def body() -> Manifold:
    outline = slab(rounded_rect(0, 0, WIDTH, HEIGHT, CORNER_R), 0, BODY_D)
    shell = outline - slab(rounded_rect(WALL, WALL, WIDTH - WALL, HEIGHT - WALL, CORNER_R - WALL), WALL, BODY_D + 1)

    for x, y in post_centres():
        shell += cylinder_z(x, y, WALL, BODY_D, POST_R)
        # Tie the post into the corner so no thin gap is left behind it.
        cx = 0 if x < WIDTH / 2 else WIDTH
        cy = 0 if y < HEIGHT / 2 else HEIGHT
        shell += box(min(cx, x), min(cy, y), WALL, max(cx, x), max(cy, y), BODY_D) ^ outline
        shell -= cylinder_z(x, y, BODY_D - PILOT_DEPTH, BODY_D + 1, PILOT_R)

    # Partition and roof of the sensor bay. Where the lid's lip comes down along
    # the walls, their front edges step back out of its way.
    lip_z = BODY_D - LIP_D - 0.2
    lip_in = WALL + LIP_CLEARANCE + LIP_T + 0.2
    px0, px1 = PARTITION_X, PARTITION_X + PARTITION_T
    roof_top = BAY_TOP + ROOF_T
    shell += box(px0, WALL, WALL, px1, roof_top, lip_z)
    shell += box(px0, lip_in, lip_z, px1, roof_top, BODY_D - 0.3)
    shell += box(WALL, BAY_TOP, WALL, px1, roof_top, lip_z)
    shell += box(lip_in, BAY_TOP, lip_z, px1, roof_top, BODY_D - 0.3)
    shell -= box(px0 - NOTCH_W, BAY_TOP - 1, NOTCH_BACK, px0, roof_top + 1, BODY_D + 1)

    # Pusher behind the SCD41's sensor; its pad presses the board onto the lid.
    px, py = SCD_X + SCD_BOARD_W / 2, SCD_TOP - SCD_CAP_CENTER
    pusher_end = scd41_seat_z() - SCD_BOARD_T - PUSHER_PAD + PUSHER_SQUEEZE
    shell += box(px - PUSHER / 2, py - PUSHER / 2, WALL, px + PUSHER / 2, py + PUSHER / 2, pusher_end)

    # Rib the ESP32 rests on, between its two header rows, ending in a stop
    # above the board's top edge so pushing a plug in cannot slide it up.
    rib_x = C3_X + C3_W / 2
    top = C3_BOTTOM + C3_L
    rx0, rx1 = rib_x - RIB_W / 2, rib_x + RIB_W / 2
    shell += box(rx0, C3_BOTTOM + 5, WALL, rx1, top + STOP_GAP + 3, C3_BACK_Z - TAPE)
    shell += box(rx0, top + STOP_GAP, WALL, rx1, top + STOP_GAP + 3, C3_BACK_Z + C3_PCB_T)

    # USB-C opening, with the wall thinned around it so the plug seats fully.
    # The thinned pocket reaches behind the board too, so the header plastic
    # clears the floor wherever along the edge the headers sit.
    shell -= box(C3_X - 0.5, BOTTOM_SKIN, C3_BACK_Z - 3.0, C3_X + C3_W_MAX + 0.5, WALL + 1, USB_Z + USB_H / 2 + 0.4)
    ow, oh = USB_W + 2 * USB_CLEARANCE, USB_H + 2 * USB_CLEARANCE
    opening = rounded_rect(USB_X - ow / 2, USB_Z - oh / 2, USB_X + ow / 2, USB_Z + oh / 2, oh / 2 - 0.01)
    shell -= _usb_cut(opening)

    for y in VENTS_LOW + VENTS_HIGH:
        depth = VENT_BLIND if y in VENTS_LOW else WALL + 1
        shell -= box(-1, y, VENT_Z[0], depth, y + VENT_H, VENT_Z[1])
        shell -= box(WIDTH - WALL - 1, y, VENT_Z[0], WIDTH + 1, y + VENT_H, VENT_Z[1])
    return shell


def _usb_cut(opening: CrossSection) -> Manifold:
    """The socket's outline, drawn with z as its second axis, pushed through the
    bottom wall along y."""
    # Rotating +90 degrees about x maps (x, y, z) to (x, -z, y): the outline's
    # second axis becomes z and the extrusion runs down from y = WALL + 1.
    return opening.extrude(WALL + 2).rotate([90, 0, 0]).translate([0, WALL + 1, 0])


def lid() -> Manifold:
    full = rounded_rect(0, 0, WIDTH, HEIGHT, CORNER_R)
    c = EDGE_CHAMFER
    inset = rounded_rect(c, c, WIDTH - c, HEIGHT - c, CORNER_R - c)
    part = slab(full, BODY_D, DEPTH - c)
    part += Manifold.batch_hull([slab(full, DEPTH - c - 0.01, DEPTH - c), slab(inset, DEPTH - 0.01, DEPTH)])

    # Lip that keys the lid into the body's opening.
    o = WALL + LIP_CLEARANCE
    lip = slab(rounded_rect(o, o, WIDTH - o, HEIGHT - o, CORNER_R - o), BODY_D - LIP_D, BODY_D)
    i = o + LIP_T
    lip -= slab(rounded_rect(i, i, WIDTH - i, HEIGHT - i, CORNER_R - i), BODY_D - LIP_D - 1, BODY_D + 1)
    for x, y in post_centres():
        reach = POST_R + 0.6
        left, low = x < WIDTH / 2, y < HEIGHT / 2
        lip -= box(
            0 if left else x - reach,
            0 if low else y - reach,
            BODY_D - LIP_D - 1,
            x + reach if left else WIDTH,
            y + reach if low else HEIGHT,
            BODY_D + 1,
        )
    part += lip

    # The SCD41 mount, flipped so its pins point up and its face points out.
    solid, cut = scd41_mount()

    def place(m: Manifold) -> Manifold:
        return m.rotate([180, 0, 0]).translate([SCD_X, SCD_TOP, DEPTH])

    part = (part + place(solid)) - place(cut)

    # Tie the SCD41 frame to the lip where they run close, so no thin slit is
    # left between them for the slicer to choke on.
    fx0 = SCD_X - CLEARANCE - FRAME_WALL
    fy0 = SCD_TOP - SCD_BOARD_L - CLEARANCE - FRAME_WALL
    fx1 = SCD_X + SCD_BOARD_W + CLEARANCE + FRAME_WALL
    fy1 = SCD_TOP + CLEARANCE + FRAME_WALL
    lip_inner = o + LIP_T
    if fx0 - lip_inner < 1.0:
        part += box(lip_inner - 0.3, fy0, BODY_D - LIP_D, fx0 + 0.3, fy1, BODY_D)
    if fy0 - lip_inner < 1.0:
        part += box(fx0, lip_inner - 0.3, BODY_D - LIP_D, fx1, fy0 + 0.3, BODY_D)

    # Plug for the front of the roof notch. It reaches past the roof on both
    # faces, so it still closes the notch if the lid sits slightly off.
    nx0, nx1 = PARTITION_X - NOTCH_W, PARTITION_X
    part += box(
        nx0 + PLUG_CLEARANCE, BAY_TOP - 1.4, PLUG_BACK, nx1 - PLUG_CLEARANCE, BAY_TOP + ROOF_T + 1.4, BODY_D
    )

    for x, y in post_centres():
        part -= cylinder_z(x, y, BODY_D - 1, DEPTH + 1, SCREW_R)
        part -= cylinder_z(x, y, DEPTH - (SCREW_HEAD_R - SCREW_R), DEPTH + 0.01, SCREW_R, SCREW_HEAD_R)
    return part


def layout() -> dict:
    """Where the bought parts sit, for the preview page."""
    return {
        "shell": {"w": WIDTH, "h": HEIGHT, "d": DEPTH, "wall": WALL, "lidT": LID_T, "bodyD": BODY_D},
        "scd": {
            "x": SCD_X,
            "top": SCD_TOP,
            "w": SCD_BOARD_W,
            "l": SCD_BOARD_L,
            "t": SCD_BOARD_T,
            "seatZ": scd41_seat_z(),
            "cap": SCD_CAP_SIDE,
            "base": SCD_BASE,
            "capH": SCD_CAP_ABOVE_BOARD,
            "capCenter": SCD_CAP_CENTER,
            "behind": SCD_BEHIND_BOARD,
        },
        "c3": {
            "x": C3_X,
            "bottom": C3_BOTTOM,
            "w": C3_W,
            "l": C3_L,
            "t": C3_PCB_T,
            "backZ": C3_BACK_Z,
            "behind": C3_TOTAL_BEHIND,
            "usbX": USB_X,
            "usbZ": USB_Z,
            "usbW": USB_W,
            "usbH": USB_H,
            "usbLen": USB_LEN,
            "usbOver": USB_OVERHANG,
            "tape": TAPE,
        },
        "partition": {"x": PARTITION_X, "t": PARTITION_T, "bayTop": BAY_TOP, "roofT": ROOF_T, "notchW": NOTCH_W},
        "pusher": {
            "x": SCD_X + SCD_BOARD_W / 2,
            "y": SCD_TOP - SCD_CAP_CENTER,
            "size": PUSHER,
            "end": scd41_seat_z() - SCD_BOARD_T - PUSHER_PAD + PUSHER_SQUEEZE,
            "pad": PUSHER_PAD,
        },
        "posts": [list(p) for p in post_centres()],
        "antenna": {"l": ANTENNA[0], "w": ANTENNA[1], "x": ANTENNA_X, "y": ANTENNA_Y},
        "screw": {"r": SCREW_R, "head": SCREW_HEAD_R, "len": 10.0},
    }


def _usb_socket() -> Manifold:
    """The ESP32's USB-C socket as a solid, rounded like the real one."""
    y0 = C3_BOTTOM - USB_OVERHANG
    outline = rounded_rect(USB_X - USB_W / 2, USB_Z - USB_H / 2, USB_X + USB_W / 2, USB_Z + USB_H / 2, USB_H / 2 - 0.05)
    return outline.extrude(USB_LEN).rotate([90, 0, 0]).translate([0, y0 + USB_LEN, 0])


def bought_parts() -> dict[str, Manifold]:
    """Boxes for everything that goes inside, at its assembled position."""
    parts = {}
    c3_top = C3_BOTTOM + C3_L
    parts["ESP32 board"] = box(C3_X, C3_BOTTOM, C3_BACK_Z, C3_X + C3_W_MAX, c3_top, C3_BACK_Z + C3_PCB_T)
    parts["ESP32 USB socket"] = _usb_socket()
    # The header rows are 8 pins (20.32 mm) on a 22.4 mm edge; where along the
    # edge they sit was not measured, so check both extremes.
    for label, y0 in (("flush with the USB edge", C3_BOTTOM), ("flush with the top edge", c3_top - 20.32)):
        for x0 in (C3_X, C3_X + C3_W_MAX - 2.54):
            parts[f"ESP32 header {label} at x={x0:.1f}"] = box(x0, y0, C3_BACK_Z - 2.5, x0 + 2.54, y0 + 20.32, C3_BACK_Z)
        parts[f"ESP32 Dupont housing, header {label}"] = box(
            C3_X, y0 + 2.54, C3_BACK_Z - C3_TOTAL_BEHIND, C3_X + 2.6, y0 + 2.54 + 10.2, C3_BACK_Z
        )
    seat = scd41_seat_z()
    sy0 = SCD_TOP - SCD_BOARD_L
    cx, cy = SCD_X + SCD_BOARD_W / 2, SCD_TOP - SCD_CAP_CENTER
    parts["SCD41 board"] = box(SCD_X, sy0, seat - SCD_BOARD_T, SCD_X + SCD_BOARD_W, SCD_TOP, seat)
    parts["SCD41 green base"] = box(cx - SCD_BASE / 2, cy - SCD_BASE / 2, seat, cx + SCD_BASE / 2, cy + SCD_BASE / 2, seat + 0.8)
    parts["SCD41 cap"] = box(cx - SCD_CAP_SIDE / 2, cy - SCD_CAP_SIDE / 2, seat, cx + SCD_CAP_SIDE / 2, cy + SCD_CAP_SIDE / 2, seat + SCD_CAP_ABOVE_BOARD)
    parts["SCD41 header and Dupont housing"] = box(
        cx - 5.1, SCD_TOP - 2.9, seat - SCD_BOARD_T - SCD_BEHIND_BOARD, cx + 5.1, SCD_TOP - 0.3, seat - SCD_BOARD_T
    )
    return parts


def check_fit(body_part: Manifold, lid_part: Manifold) -> None:
    """Refuse to write STL files if anything bought collides with a printed part."""
    problems = []
    for name, solid in bought_parts().items():
        for part_name, part in (("body", body_part), ("lid", lid_part)):
            overlap = (part ^ solid).volume()
            if overlap > 0.01:
                problems.append(f"{name} cuts into the {part_name} by {overlap:.2f} mm3")
    overlap = (body_part ^ lid_part).volume()
    if overlap > 0.01:
        problems.append(f"the lid cuts into the body by {overlap:.2f} mm3")
    window_start = SCD_CAP_CENTER - WINDOW / 2
    if window_start - SCD_FRONT_PARTS < 0.5:
        problems.append("the parts pocket under the SCD41 runs into its window: a leak path for warm air")
    if problems:
        raise SystemExit("Fit check failed:\n  " + "\n  ".join(problems))
    print("fit check: nothing collides")


def mesh_json(part: Manifold) -> dict:
    mesh = part.to_mesh()
    verts = np.asarray(mesh.vert_properties, dtype=np.float32)[:, :3]
    tris = np.asarray(mesh.tri_verts, dtype=np.uint32)
    return {
        "pos": base64.b64encode(np.ascontiguousarray(verts).tobytes()).decode(),
        "idx": base64.b64encode(np.ascontiguousarray(tris).tobytes()).decode(),
    }


def write_stl(part: Manifold, path: Path) -> None:
    mesh = part.to_mesh()
    verts = np.asarray(mesh.vert_properties)[:, :3]
    tris = np.asarray(mesh.tri_verts)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(b"\0" * 80)
        fh.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            va, vb, vc = verts[a], verts[b], verts[c]
            n = np.cross(vb - va, vc - va)
            length = np.linalg.norm(n)
            n = n / length if length else n
            fh.write(struct.pack("<12fH", *n, *va, *vb, *vc, 0))


def print_pose(name: str, part: Manifold) -> Manifold:
    """The part as it sits on the print bed: flat face down at z = 0."""
    if name == "lid":
        part = part.rotate([180, 0, 0])  # outer face down; y flips, x stays
    lo = part.bounding_box()[:3]
    return part.translate([-lo[0], -lo[1], -lo[2]])


def describe(name: str, part: Manifold) -> dict:
    lo, hi = part.bounding_box()[:3], part.bounding_box()[3:]
    size = [round(h - l, 1) for l, h in zip(lo, hi)]
    grams = part.volume() / 1000 * PETG_DENSITY
    print(f"{name}: {' x '.join(map(str, size))} mm, {grams:.1f} g PETG if solid, genus {part.genus()}")
    return {"size": size, "grams": round(grams, 1)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", type=Path, help="write meshes and layout as JSON")
    args = parser.parse_args()

    parts = {"body": body(), "lid": lid()}
    check_fit(parts["body"], parts["lid"])
    info = {}
    for name, part in parts.items():
        write_stl(print_pose(name, part), OUT_DIR / f"{name}.stl")
        info[name] = describe(name, part)

    if args.preview:
        data = {
            "layout": layout(),
            "info": info,
            "meshes": {name: mesh_json(part) for name, part in parts.items()},
        }
        args.preview.write_text(json.dumps(data), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
