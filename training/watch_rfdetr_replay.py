"""Watch a TFT replay with RF-DETR Large predictions in one live window.

Predictions are observations, never labels. The video clock runs independently
from inference; the overlay displays the age of the last analyzed frame.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
import sys
import time
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

import cv2
import numpy as np
import torch
from torchvision.ops import nms

from benchmark_large_hud_detectors import load_model, predict
from build_joint_hud_unit_experiment import ROI
from evaluate_reviewed_unit_locator_experiment import starts
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/hud_mapper'))
from hm.champion_belief import ChampionBelief, TemporalVisualHypotheses
from preview_user_reviewed_46_replay import locate_unit_candidates


WIDTH, HEIGHT = 1920, 1080
DISPLAY_WIDTH = 1280
BODY_REGION = (170, 55, 1700, 860)
TILE, STRIDE = 512, 416
COLORS = {0: (50, 230, 75), 1: (0, 220, 255), 2: (0, 220, 255),
          3: (0, 220, 255), 4: (0, 220, 255), 5: (0, 220, 255),
          6: (0, 220, 255)}
LABELS = {0: "corpo", 1: "estagio", 2: "ouro", 3: "nivel", 4: "xp",
          5: "hp painel", 6: "card loja"}
# Each side has exactly four rows of seven hexes. The own-board coordinates
# come from configs/ui/match001-board-bench-v1.json and match the game's visible
# placement grid at 8W7Wfnf36M8 830 s. The opponent half is an extrapolation.
ROW_PROJECTIONS = {
    "adversario": ((560, 1258, 144), (618, 1330, 219),
                   (557, 1275, 296), (620, 1350, 380)),
    "meu_lado": ((560, 1258, 444), (618, 1330, 519),
                 (557, 1275, 596), (620, 1350, 680)),
}
def fit_board_projection(rows):
    """Fit one continuous board surface to measured in-game cell centers."""
    basis, locations = [], []
    for row, (left, right, y) in enumerate(rows):
        for col in range(7):
            u, v = col + (row % 2) / 2, row
            basis.append((1, u, v, u * v, v * v))
            locations.append((left + (right - left) * col / 6, y))
    return np.linalg.lstsq(np.asarray(basis), np.asarray(locations), rcond=None)[0]


BOARD_PROJECTIONS = {side: fit_board_projection(rows)
                     for side, rows in ROW_PROJECTIONS.items()}


def project_board(side, u, v):
    point = np.asarray((1, u, v, u * v, v * v)) @ BOARD_PROJECTIONS[side]
    if side == "meu_lado":
        # Matched against the game's visible border in the blue 4K arena.
        point[0] -= 3.7
        point[1] = 440 + (point[1] - 440) * 0.9306 + 7.6
    return point


def hex_polygon(side, row, col):
    """Project shared hex vertices; neighboring cells cannot diverge."""
    u, v = col + (row % 2) / 2, row
    offsets = ((0, -2/3), (1/2, -1/3), (1/2, 1/3),
               (0, 2/3), (-1/2, 1/3), (-1/2, -1/3))
    return np.asarray([project_board(side, u + du, v + dv)
                       for du, dv in offsets], dtype=np.float32)


HEX_TILES = tuple((side, row, col, hex_polygon(side, row, col))
                  for side in ROW_PROJECTIONS for row in range(4)
                  for col in range(7))
assert len(HEX_TILES) == 56
BENCH_RECT = (345, 730, 1405, 870)


def detect_floor_quad(frame):
    """Locate straight terrain boundaries independently of arena colors."""
    small = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 130)
    lines = cv2.HoughLinesP(edges[50:550, 300:960], 1, np.pi / 720,
                            threshold=90, minLineLength=100,
                            maxLineGap=25)
    if lines is None:
        return None
    top, bottom, left, right = [], [], [], []
    for ax, ay, bx, by in lines.reshape(-1, 4):
        ax, bx, ay, by = ax + 300, bx + 300, ay + 50, by + 50
        dx, dy = bx - ax, by - ay
        midx, midy = (ax + bx) / 2, (ay + by) / 2
        if abs(dx) >= 380 and abs(dy) <= 12:
            if 95 <= midy <= 145:
                top.append(midy)
            if 460 <= midy <= 515:
                bottom.append(midy)
        if abs(dy) < 210 or abs(dx) > 0.38 * abs(dy):
            continue
        slope = dx / dy
        line = (abs(dy), midx, midy, slope)
        if 365 <= midx <= 455 and -0.3 <= slope <= -0.05:
            left.append(line)
        if 815 <= midx <= 925 and 0.05 <= slope <= 0.3:
            right.append(line)
    if not (top and bottom and left and right):
        return None
    y0, y1 = float(np.median(top)), float(np.median(bottom))
    if not 300 <= y1 - y0 <= 430:
        return None

    def side_at(candidates, y):
        strongest = sorted(candidates, reverse=True)[:6]
        return float(np.median([x + slope * (y - middle)
                                for _, x, middle, slope in strongest]))

    corners = np.asarray(((side_at(left, y0), y0),
                          (side_at(right, y0), y0),
                          (side_at(right, y1), y1),
                          (side_at(left, y1), y1)), dtype=np.float32)
    widths = corners[[1, 2], 0] - corners[[0, 3], 0]
    if np.any(widths < 350) or np.any(widths > 650):
        return None
    return corners * 1.5


def tiles_from_floor(quad):
    """Place the complete 8x7 lattice inside a measured terrain quadrilateral."""
    source = np.asarray(((0, 0), (1, 0), (1, 1), (0, 1)), dtype=np.float32)
    transform = cv2.getPerspectiveTransform(source, np.asarray(quad, np.float32))

    def project(u, v):
        point = cv2.perspectiveTransform(
            np.asarray([[[u, v]]], np.float32), transform)[0, 0]
        return point

    tiles = []
    for global_row in range(8):
        side = "adversario" if global_row < 4 else "meu_lado"
        local_row = global_row if global_row < 4 else global_row - 4
        for col in range(7):
            # Keep the marker centers inside the playable floor. Hough lines
            # often follow the outer trim, which is wider than the hex field.
            u = 0.11 + (col + (global_row % 2) / 2) / 8.3
            v = (global_row + 0.5) / 8
            offsets = ((0, -2/3), (1/2, -1/3), (1/2, 1/3),
                       (0, 2/3), (-1/2, 1/3), (-1/2, -1/3))
            polygon = np.asarray([project(u + du / 8.3, v + dv / 8)
                                  for du, dv in offsets], dtype=np.float32)
            tiles.append((side, local_row, col, polygon))
    return tuple(tiles)


class BoardLayout:
    """Keep each arena's measured terrain base until a camera cut."""

    def __init__(self):
        self.tiles = HEX_TILES
        self.source = "grade_visivel"
        self.reference_matrix = np.eye(3, dtype=np.float64)
        self.last_reset = -1
        self.frames = 0
        self.last_attempt = -20

    @staticmethod
    def visible_reference_arena(frame):
        sample = frame[490:700:12, 630:1270:12]
        blue_minus_red = sample[:, :, 0].astype(np.int16) - sample[:, :, 2]
        return sample.size > 0 and float(np.median(blue_minus_red)) > 75

    def update(self, frame, reset_count, terrain_matrix):
        self.frames += 1
        changed = reset_count != self.last_reset
        if not changed and (self.source != "grade_de_referencia" or
                            self.frames - self.last_attempt < 12):
            return self.tiles
        self.last_reset = reset_count
        self.last_attempt = self.frames
        if self.visible_reference_arena(frame):
            self.tiles = HEX_TILES
            self.source = "grade_visivel"
            self.reference_matrix = np.eye(3, dtype=np.float64)
            return self.tiles
        quad = detect_floor_quad(frame)
        if quad is not None:
            self.tiles = tiles_from_floor(quad)
            self.source = "bordas_do_terreno"
            # The measured quad is already in current screen coordinates.
            # Subsequent optical flow is relative to this frame, not frame zero.
            self.reference_matrix = terrain_matrix.copy()
        else:
            self.tiles = HEX_TILES
            self.source = "grade_de_referencia"
            self.reference_matrix = np.eye(3, dtype=np.float64)
        return self.tiles

    def current_matrix(self, terrain_matrix):
        return terrain_matrix @ np.linalg.inv(self.reference_matrix)


class TerrainTelemetry:
    """Track fixed arena details through camera motion, never unit identities."""

    def __init__(self):
        self.previous = None
        self.points = None
        self.transform = np.eye(3, dtype=np.float64)
        self.anchors = 0
        self.resets = 0

    @staticmethod
    def landmarks(gray):
        mask = np.zeros(gray.shape, dtype=np.uint8)
        # Arena edges and bench: mostly terrain, away from moving combat units.
        mask[35:275, 95:190] = 255
        mask[35:275, 410:505] = 255
        mask[245:300, 125:475] = 255
        mask[35:90, 190:410] = 255
        return cv2.goodFeaturesToTrack(gray, maxCorners=240, qualityLevel=0.015,
                                       minDistance=7, mask=mask)

    def update(self, frame):
        small = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if self.previous is None or self.points is None or len(self.points) < 20:
            self.previous = gray
            self.points = self.landmarks(gray)
            self.anchors = 0 if self.points is None else len(self.points)
            return self.transform.copy()
        next_points, status, _ = cv2.calcOpticalFlowPyrLK(
            self.previous, gray, self.points, None, winSize=(21, 21),
            maxLevel=2, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 18, 0.03))
        good = status.reshape(-1).astype(bool) if status is not None else np.zeros(len(self.points), bool)
        old = self.points[good].reshape(-1, 2)
        new = next_points[good].reshape(-1, 2) if next_points is not None else np.empty((0, 2))
        affine, inliers = (cv2.estimateAffinePartial2D(old, new, method=cv2.RANSAC,
                                                       ransacReprojThreshold=2.5)
                           if len(old) >= 12 else (None, None))
        valid = affine is not None and inliers is not None and int(inliers.sum()) >= 12
        valid = valid and float(inliers.mean()) >= 0.55
        if valid:
            scale = float(np.hypot(affine[0, 0], affine[1, 0]))
            motion = float(np.hypot(affine[0, 2], affine[1, 2]))
            valid = 0.97 <= scale <= 1.03 and motion <= 15
        if valid:
            step = np.eye(3, dtype=np.float64)
            step[:2, :2] = affine[:, :2]
            step[:2, 2] = affine[:, 2] * 3
            self.transform = step @ self.transform
            self.anchors = int(inliers.sum())
            self.points = new[inliers.reshape(-1).astype(bool)].reshape(-1, 1, 2)
        else:
            # Different terrain or a camera cut: return to the screen baseline.
            self.transform = np.eye(3, dtype=np.float64)
            self.resets += 1
            self.anchors = 0
            self.points = None
        self.previous = gray
        if self.points is None or len(self.points) < 50:
            self.points = self.landmarks(gray)
        return self.transform.copy()


class ArenaVisualIndex:
    """Group repeated terrain views without claiming who owns an arena."""

    REGIONS = ((250, 170, 420, 570), (1500, 170, 1680, 570),
               (450, 130, 850, 230), (1100, 130, 1450, 230),
               (520, 805, 780, 870), (1050, 805, 1340, 870))

    def __init__(self):
        self.features = {}
        self.current_id = None
        self.current_visit = None
        self.last_reset = None
        self.next_id = 1
        self.next_visit = 1

    @classmethod
    def feature(cls, frame):
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        values = []
        for x0, y0, x1, y1 in cls.REGIONS:
            patch = cv2.resize(lab[y0:y1, x0:x1], (24, 24),
                               interpolation=cv2.INTER_AREA)
            for half in np.array_split(patch, 2, axis=0):
                for tile in np.array_split(half, 2, axis=1):
                    values.extend(np.median(tile.reshape(-1, 3), axis=0) / 255)
        return np.asarray(values, dtype=np.float32)

    def update(self, frame, reset_count, layout_source):
        if layout_source == "grade_de_referencia":
            self.current_id = None
            self.current_visit = None
            return None, None
        if self.current_id is not None and reset_count == self.last_reset:
            return self.current_id, self.current_visit
        value = self.feature(frame)
        distances = sorted((float(np.linalg.norm(value - prior)), key)
                           for key, prior in self.features.items())
        if distances and distances[0][0] <= 0.35:
            self.current_id = distances[0][1]
        else:
            self.current_id = f"arena_{self.next_id}"
            self.features[self.current_id] = value
            self.next_id += 1
        self.last_reset = reset_count
        self.current_visit = f"visita_{self.next_visit}"
        self.next_visit += 1
        return self.current_id, self.current_visit


def transform_point(point, matrix):
    x, y = point
    projected = matrix @ np.asarray((x, y, 1.0))
    return float(projected[0] / projected[2]), float(projected[1] / projected[2])


def intersection_over_union(first, second):
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    overlap = max(0, right - left) * max(0, bottom - top)
    a = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    b = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    return overlap / max(1, a + b - overlap)


def grid_location(box, terrain_matrix=None, tiles=HEX_TILES):
    """Nearest visual hex to the proposal's feet; never an identity label."""
    x = (box[0] + box[2]) / 2
    y = box[3]
    if terrain_matrix is not None:
        x, y = transform_point((x, y), np.linalg.inv(terrain_matrix))
    x0, y0, x1, y1 = BENCH_RECT
    body_center_y = (box[1] + box[3]) / 2
    if x0 <= x <= x1 and y0 <= y <= y1 and body_center_y >= 680:
        slot = min(8, max(0, int((x - x0) * 9 / (x1 - x0))))
        return "banco", f"B-{'ABCDEFGHI'[slot]}"
    for side, row, col, polygon in tiles:
        if cv2.pointPolygonTest(polygon, (x, y), False) >= 0:
            prefix = "E:" if side == "adversario" else ""
            return side, f"{prefix}{'ABCD'[row]}{col + 1}"
    # A detector box may include a few pixels of shadow below the feet.
    # Keep that proposal on the nearest tile only within one half-cell.
    nearest = min(tiles, key=lambda tile: np.linalg.norm(
        tile[3].mean(axis=0) - np.asarray((x, y))))
    if np.linalg.norm(nearest[3].mean(axis=0) - np.asarray((x, y))) <= 65:
        side, row, col, _ = nearest
        prefix = "E:" if side == "adversario" else ""
        return side, f"{prefix}{'ABCD'[row]}{col + 1}"
    return "fora", "fora"


def health_bar_owner(frame, box):
    """Classify a straight green or red health stroke, if one is visible."""
    x0, y0, x1, y1 = [round(v) for v in box]
    x0, x1 = max(0, x0), min(WIDTH, x1)
    y0, y1 = max(0, y0 - 12), min(HEIGHT, round(y0 + max(26, (y1 - y0) * 0.22)))
    if x1 - x0 < 25 or y1 - y0 < 4:
        return None
    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    hue, saturation, value = cv2.split(hsv)
    min_width = max(30, round((x1 - x0) * 0.33))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (min_width, 1))
    for owner, band in (("adversario", (hue <= 10) | (hue >= 170)),
                        ("meu_lado", (hue >= 38) & (hue <= 85))):
        colored = (band & (saturation > 135) & (value > 125)).astype("uint8")
        straight = cv2.morphologyEx(colored, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(straight, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        if any((lambda r: r[2] >= min_width and 1 <= r[3] <= 10)(
                cv2.boundingRect(c)) for c in contours):
            return owner
    return None


class BodyTracker:
    """Associate generic body proposals across sampled frames; never name them."""

    def __init__(self):
        self.next_id = 1
        self.tracks = []
        self.epoch = None

    def update(self, detections, frame, stamp, terrain_matrix, tiles, epoch):
        if self.epoch is not None and epoch != self.epoch:
            # A camera cut can put another player's units at the same pixels.
            self.tracks.clear()
        self.epoch = epoch
        candidates = []
        for row in detections:
            if row["class"] != 0:
                continue
            zone, cell = grid_location(row["box"], terrain_matrix, tiles)
            if zone == "fora":
                continue
            # The visible bench can belong to a spectated rival. A red detail
            # inside a body crop cannot identify that player's ownership.
            owner = None if zone == "banco" else health_bar_owner(frame, row["box"])
            candidates.append({**row, "zone": zone, "cell": cell,
                               "bar": owner is not None, "bar_owner": owner})
        pairs = []
        for ti, track in enumerate(self.tracks):
            for di, detection in enumerate(candidates):
                votes = track["owner_votes"]
                known_owner = (max(votes, key=votes.get)
                               if max(votes.values()) >= 2 else None)
                if (known_owner and detection["bar_owner"] and
                        known_owner != detection["bar_owner"]):
                    continue
                if track["zone"] == "banco" and detection["bar_owner"] == "adversario":
                    continue
                overlap = intersection_over_union(track["box"], detection["box"])
                tx = (track["box"][0] + track["box"][2]) / 2
                ty = (track["box"][1] + track["box"][3]) / 2
                dx = (detection["box"][0] + detection["box"][2]) / 2
                dy = (detection["box"][1] + detection["box"][3]) / 2
                distance = ((tx - dx) ** 2 + (ty - dy) ** 2) ** 0.5
                limit = max(50, min(160, 0.8 * max(
                    track["box"][2] - track["box"][0],
                    track["box"][3] - track["box"][1])))
                if overlap >= 0.15 or distance <= limit:
                    pairs.append((overlap * 2 + 1 - distance / limit, ti, di))
        matched_tracks, matched_detections = set(), set()
        for _, ti, di in sorted(pairs, reverse=True):
            if ti in matched_tracks or di in matched_detections:
                continue
            track, detection = self.tracks[ti], candidates[di]
            if detection["cell"] == track["pending_cell"]:
                track["pending_reads"] += 1
            else:
                track["pending_cell"] = detection["cell"]
                track["pending_reads"] = 1
            if track["pending_reads"] >= 2 and detection["cell"] != track["cell"]:
                track["cell"] = detection["cell"]
                track["zone"] = detection["zone"]
                track["cell_history"].append((round(stamp, 2), detection["cell"]))
            track.update(box=detection["box"], score=detection["score"],
                         bar=detection["bar"], stamp=stamp, misses=0)
            if detection["bar_owner"]:
                track["owner_votes"][detection["bar_owner"]] += 1
            track["hits"] += 1
            track["bar_hits"] += int(detection["bar"])
            track["history"].append((round((detection["box"][0] + detection["box"][2]) / 2),
                                     round(detection["box"][3])))
            matched_tracks.add(ti)
            matched_detections.add(di)
        for ti, track in enumerate(self.tracks):
            if ti not in matched_tracks:
                track["misses"] += 1
        for di, detection in enumerate(candidates):
            if di in matched_detections:
                continue
            box = detection["box"]
            self.tracks.append({"id": self.next_id, "box": box,
                                "score": detection["score"],
                                "zone": detection["zone"], "cell": detection["cell"],
                                "origin_cell": detection["cell"],
                                "pending_cell": detection["cell"],
                                "pending_reads": 1,
                                "cell_history": deque([(round(stamp, 2), detection["cell"])],
                                                      maxlen=24),
                                "bar": detection["bar"],
                                "owner_votes": {"meu_lado": int(detection["bar_owner"] == "meu_lado"),
                                                "adversario": int(detection["bar_owner"] == "adversario")},
                                "bar_hits": int(detection["bar"]),
                                "hits": 1, "misses": 0,
                                "stamp": stamp, "history": deque(
                                    [(round((box[0] + box[2]) / 2), round(box[3]))],
                                    maxlen=8)})
            self.next_id += 1
        self.tracks = [track for track in self.tracks if track["misses"] <= 2]
        return [{**track, "history": list(track["history"]),
                 "cell_history": list(track["cell_history"]),
                 "owner": (max(track["owner_votes"], key=track["owner_votes"].get)
                           if max(track["owner_votes"].values()) > 0 else None),
                 "stable": track["hits"] >= 2 and track["misses"] == 0,
                 "strong_cue": track["hits"] >= 2 and
                 track["bar_hits"] >= 2 and track["score"] >= 0.35}
                for track in self.tracks if track["misses"] == 0]


class PlayerRosterMemory:
    """Keep spatial histories separate for each visible player.

    Names are supplied by the caller's player identification, never inferred
    from a unit box. An unresolved player cannot contaminate a known roster.
    """

    def __init__(self):
        self.players = {}
        self.unresolved_arenas = {}
        self.sold = {}
        self.sold_ids = set()

    def bind_identity(self, player, track_id, champion_id, evidence):
        if evidence not in ("user_confirmed", "shop_transfer_confirmed"):
            raise ValueError("A visual guess cannot become a champion identity")
        item = self.players.get(player, {}).get(str(track_id))
        if item is None:
            return False
        item["champion_id"] = champion_id
        item["identity_source"] = evidence
        return True

    def confirm_sale(self, player, track_id, stamp, evidence):
        if evidence not in ("user_confirmed", "sell_action_confirmed"):
            raise ValueError("Disappearance alone cannot confirm a sale")
        item = self.players.get(player, {}).pop(str(track_id), None)
        if item is None:
            return None
        item.update(status="vendido", sold_at=round(stamp, 2),
                    sale_evidence=evidence)
        self.sold_ids.add((player, track_id))
        self.sold.setdefault(player, []).append(item)
        return item

    def observe(self, tracks, stamp, ally_player, opponent_player,
                arena_owner, arena_visit):
        for track in tracks:
            if not track["stable"]:
                continue
            if track["zone"] == "banco":
                player = arena_owner
                assignment = "dono_da_arena_confirmado" if player else "nao_resolvido"
            elif track["owner"] == "adversario":
                player = opponent_player
                assignment = "barra_adversaria"
            elif track["owner"] == "meu_lado":
                player = ally_player
                assignment = "barra_aliada"
            else:
                # Position alone cannot say whose arena is on screen. A
                # Little Legend may visit another player's board as well.
                player = None
                assignment = "nao_resolvido"
            track["player_key"] = player
            track["player_assignment"] = assignment if player else "nao_resolvido"
            if not player:
                if track["zone"] == "banco" and arena_visit:
                    unknown = self.unresolved_arenas.setdefault(arena_visit, {})
                    unknown[str(track["id"])] = dict(
                        track_id=track["id"], cell=track["cell"],
                        last_seen=round(stamp, 2),
                        champion_id=None, owner_status="nao_resolvido")
                continue
            if (player, track["id"]) in self.sold_ids:
                continue
            roster = self.players.setdefault(player, {})
            item = roster.setdefault(str(track["id"]), {
                "track_id": track["id"], "origin_cell": track["origin_cell"],
                "cell": track["cell"], "zone": track["zone"],
                "champion_id": None, "identity_source": None,
                "cell_history": [], "status": "observado"})
            item["cell"] = track["cell"]
            item["zone"] = track["zone"]
            item["cell_history"] = track["cell_history"]
            item["last_seen"] = round(stamp, 2)
            item["assignment"] = assignment
        return {player: list(roster.values())
                for player, roster in self.players.items()}


@torch.inference_mode()
def observe(model, frame, threshold: float, body_locator: str = 'rf'):
    """Run the same regional protocol as the held-out evaluation at 1080p."""
    boxes = []
    for region, (rx0, ry0, rx1, ry1) in ROI.items():
        crop = frame[ry0:ry1, rx0:rx1]
        for category, box, score in predict("rfdetr-large", model, crop):
            if category == 0 or score < threshold:
                continue
            x0, y0, x1, y1 = box
            boxes.append({"class": category, "box": [x0 + rx0, y0 + ry0,
                                                       x1 + rx0, y1 + ry0],
                          "score": round(score, 3), "region": region})

    if body_locator == 'bar':
        for candidate in locate_unit_candidates(frame):
            boxes.append({"class": 0, "box": candidate['box'], "score": 1.0,
                          "region": "health_bar_anchored",
                          "bar_kind": candidate['bar_kind']})
    elif body_locator == 'rf':
        rx0, ry0, rx1, ry1 = BODY_REGION
        board = frame[ry0:ry1, rx0:rx1]
        body_boxes, body_scores = [], []
        for top in starts(board.shape[0], TILE, STRIDE):
            for left in starts(board.shape[1], TILE, STRIDE):
                tile = board[top:top + TILE, left:left + TILE]
                for category, box, score in predict("rfdetr-large", model, tile):
                    if category != 0 or score < threshold:
                        continue
                    x0, y0, x1, y1 = box
                    body_boxes.append([x0 + left + rx0, y0 + top + ry0,
                                       x1 + left + rx0, y1 + top + ry0])
                    body_scores.append(score)
        if body_boxes:
            keep = nms(torch.tensor(body_boxes, dtype=torch.float32),
                       torch.tensor(body_scores), 0.5).tolist()
            for i in keep:
                boxes.append({"class": 0, "box": body_boxes[i],
                              "score": round(body_scores[i], 3), "region": "board_and_bench"})
    else:
        raise ValueError(f'Unknown body locator: {body_locator}')
    return boxes


def infer(requests, shared, lock, stop, ready, weights: Path, log: Path,
          threshold: float, ally_player: str | None,
          opponent_player: str | None, arena_owner: str | None,
          champion_weights: Path | None, probability_catalog: Path | None,
          stage: str | None, level: int | None, body_locator: str):
    try:
        model = load_model("rfdetr-large", weights)
        classifier = None
        belief = None
        if champion_weights:
            from ultralytics import YOLO
            classifier = YOLO(str(champion_weights))
        if probability_catalog:
            belief = ChampionBelief(json.loads(probability_catalog.read_text(encoding='utf-8')))
        tracker = BodyTracker()
        roster_memory = PlayerRosterMemory()
        visual_history = TemporalVisualHypotheses()
        ready.set()
        with log.open("w", encoding="utf-8") as output:
            while not stop.is_set():
                try:
                    stamp, frame, terrain_matrix, anchor_count, tiles, layout_source, epoch, arena_id, arena_visit = requests.get(timeout=0.2)
                except Empty:
                    continue
                started = time.monotonic()
                boxes = observe(model, frame, threshold, body_locator)
                tracks = tracker.update(boxes, frame, stamp, terrain_matrix, tiles, epoch)
                if classifier:
                    selected, crops = [], []
                    for track in tracks:
                        if not track['stable'] or not track['bar']:
                            continue
                        x0, y0, x1, y1 = [round(v) for v in track['box']]
                        x0, y0 = max(0, x0), max(0, y0)
                        x1, y1 = min(WIDTH, x1), min(HEIGHT, y1)
                        if x1 - x0 < 24 or y1 - y0 < 24:
                            continue
                        selected.append(track)
                        crops.append(frame[y0:y1, x0:x1])
                    if crops:
                        guesses = classifier.predict(crops, device=0 if torch.cuda.is_available() else 'cpu', imgsz=224,
                            batch=min(16, len(crops)), verbose=False)
                        for track, guess in zip(selected, guesses):
                            top = guess.probs.top5
                            candidates = [dict(unit_id=classifier.names[int(i)],
                                score_uncalibrated=float(guess.probs.data[int(i)]))
                                for i in top]
                            track['visual_candidates'] = candidates
                            track['temporal_identity'] = visual_history.update(
                                track['id'], candidates)
                            if belief:
                                track['contextual_identity'] = belief.rank(candidates,
                                    level=level, stage=stage)
                player_rosters = roster_memory.observe(
                    tracks, stamp, ally_player, opponent_player, arena_owner,
                    arena_visit)
                torch.cuda.synchronize()
                row = {"video_seconds": round(stamp, 3),
                       "inference_seconds": round(time.monotonic() - started, 3),
                       "boxes": boxes, "tracks": tracks,
                       "player_rosters": player_rosters,
                       "sold_records": roster_memory.sold,
                       "unresolved_arenas": roster_memory.unresolved_arenas,
                       "arena_id": arena_id,
                       "arena_visit": arena_visit,
                       "champion_model": str(champion_weights) if champion_weights else None,
                       "champion_probability": (belief.shop_slot(level=level, stage=stage)
                                                if belief else None),
                       "model": "rfdetr-large",
                       "body_locator": body_locator,
                       "classification_device": ('cuda' if classifier and torch.cuda.is_available()
                                                 else 'cpu' if classifier else None),
                       "grid": layout_source,
                       "terrain_anchors": anchor_count,
                       "terrain_transform": terrain_matrix.round(4).tolist(),
                       "game_telemetry_used": False}
                output.write(json.dumps(row, ensure_ascii=False) + "\n")
                output.flush()
                with lock:
                    shared["latest"] = row
                    shared["error"] = None
    except Exception as exc:
        with lock:
            shared["error"] = f"{type(exc).__name__}: {exc}"
        ready.set()


def offer(requests, stamp, frame, terrain_matrix, anchor_count, tiles,
          layout_source, epoch, arena_id, arena_visit):
    try:
        requests.put_nowait((stamp, frame.copy(), terrain_matrix.copy(),
                             anchor_count, tiles, layout_source, epoch,
                             arena_id, arena_visit))
    except Full:
        try:
            requests.get_nowait()
        except Empty:
            pass
        requests.put_nowait((stamp, frame.copy(), terrain_matrix.copy(),
                             anchor_count, tiles, layout_source, epoch,
                             arena_id, arena_visit))


def enemy_health_bars(frame):
    """Count red combat bars above the board without using arena colors."""
    crop = frame[90:450, 650:1370]
    hue, saturation, value = cv2.split(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV))
    red = (((hue <= 10) | (hue >= 170)) &
           (saturation >= 130) & (value >= 80)).astype(np.uint8)
    strokes = cv2.morphologyEx(red, cv2.MORPH_OPEN,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (42, 1)))
    contours, _ = cv2.findContours(strokes, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    return sum(1 for contour in contours
               if (lambda r: r[2] >= 42 and 1 <= r[3] <= 12)(
                   cv2.boundingRect(contour)))


def draw_grid(output, ratio, terrain_matrix, tiles, show_opponent=False):
    for side, row, col, polygon in tiles:
        if side == "adversario" and not show_opponent:
            continue
        cx, cy = transform_point(polygon.mean(axis=0), terrain_matrix)
        center = (round(cx * ratio), round(cy * ratio) + 46)
        color = (95, 205, 230) if side == "meu_lado" else (175, 130, 205)
        cv2.circle(output, center, 3, color, 1, cv2.LINE_AA)
        label = f"{'ABCD'[row]}{col + 1}"
        cv2.putText(output, label, (center[0] + 5, center[1] - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.26, color, 1, cv2.LINE_AA)


def draw_bench_labels(output, ratio):
    x0, y0, x1, y1 = BENCH_RECT
    for slot, letter in enumerate("ABCDEFGHI"):
        x = round((x0 + (slot + 0.5) * (x1 - x0) / 9) * ratio)
        y = round((y0 + 0.82 * (y1 - y0)) * ratio) + 46
        cv2.putText(output, f"B-{letter}", (x - 8, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.28, (185, 215, 215),
                    1, cv2.LINE_AA)


def overlay(frame, observation, stamp, error, display_fps,
            show_opponent=False, terrain_matrix=None, anchor_count=0,
            tiles=HEX_TILES, layout_source="grade_de_referencia"):
    ratio = DISPLAY_WIDTH / WIDTH
    video = cv2.resize(frame, (DISPLAY_WIDTH, round(HEIGHT * ratio)),
                       interpolation=cv2.INTER_AREA)
    output = cv2.copyMakeBorder(video, 46, 0, 0, 0, cv2.BORDER_CONSTANT,
                                value=(22, 22, 22))
    terrain_matrix = (np.eye(3, dtype=np.float64) if terrain_matrix is None
                      else terrain_matrix)
    if layout_source != "grade_de_referencia":
        draw_grid(output, ratio, terrain_matrix, tiles, show_opponent)
    draw_bench_labels(output, ratio)
    if observation:
        age = max(0.0, stamp - observation["video_seconds"])
        raw_bodies = sum(row["class"] == 0 for row in observation["boxes"])
        stable = sum(row["stable"] for row in observation["tracks"])
        stronger = sum(row["strong_cue"] for row in observation["tracks"])
        visible = sum(row["strong_cue"] or (row["stable"] and row["bar"] and
                      row["score"] >= 0.3) for row in observation["tracks"])
        hud = len(observation["boxes"]) - raw_bodies
        grid_mode = "28+28 combate" if show_opponent else "28 preparo"
        arena = observation.get("arena_id") or "arena?"
        headline = (f"RF-DETR {arena} | {grid_mode} | {stamp/60:.1f} min | "
                    f"terreno {anchor_count} pts | "
                    f"corpos {raw_bodies}  visiveis {visible}  HUD {hud} | "
                    f"inferencia {observation['inference_seconds']*1000:.0f} ms | "
                    f"atraso {age:.1f}s | video {display_fps:.0f} FPS")
    else:
        headline = "RF-DETR Large carregando; video em tempo real"
    if error:
        headline = f"ERRO RF-DETR: {error[:115]}"
    cv2.putText(output, headline, (12, 29), cv2.FONT_HERSHEY_SIMPLEX,
                0.53, (245, 245, 245), 1, cv2.LINE_AA)
    if not observation:
        return output
    for row in observation["boxes"]:
        category = row["class"]
        if category not in COLORS or category == 0:
            continue
        x0, y0, x1, y1 = [round(value * ratio) for value in row["box"]]
        y0 += 46
        y1 += 46
        color = COLORS[category]
        cv2.rectangle(output, (x0, y0), (x1, y1), color, 2)
        label = f"{LABELS[category]} {row['score']:.2f}"
        cv2.putText(output, label, (max(x0, 1), max(y0 - 5, 58)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)
    for track in observation["tracks"]:
        if not (track["strong_cue"] or (track["stable"] and track["bar"] and
                track["score"] >= 0.3)):
            continue
        x0, y0, x1, y1 = [round(value * ratio) for value in track["box"]]
        y0 += 46
        y1 += 46
        stable = track["stable"]
        strong = track["strong_cue"]
        color = (60, 235, 90) if strong else ((0, 155, 245) if stable else (120, 120, 150))
        cv2.rectangle(output, (x0, y0), (x1, y1), color, 2 if strong else 1)
        if stable:
            route = (track["cell"] if track["origin_cell"] == track["cell"]
                     else f"{track['origin_cell']}>{track['cell']}")
            label = f"#{track['id']} {route}"
            candidates = (track.get('contextual_identity') or {}).get('hypotheses') or []
            temporal = track.get('temporal_identity') or {}
            if temporal.get('unit_id'):
                label += f" {temporal['unit_id'].removeprefix('DA_18_')}?"
                label += f" {temporal['votes_for_displayed']}/{temporal['window_observations']}"
            elif candidates:
                label += f" {candidates[0]['unit_id'].removeprefix('DA_18_')}?"
            cv2.putText(output, label, (max(x0, 1), max(y0 - 5, 58)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)
        if strong and len(track["history"]) > 1:
            points = np.array([(round(x * ratio), round(y * ratio) + 46)
                               for x, y in track["history"]], dtype=np.int32)
            cv2.polylines(output, [points], False, color, 2, cv2.LINE_AA)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("weights", type=Path)
    parser.add_argument("log", type=Path)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--display-fps", type=float, default=22.0)
    parser.add_argument("--infer-interval", type=float, default=0.5)
    parser.add_argument("--threshold", type=float, default=0.15)
    parser.add_argument("--timestamp-offset", type=float, default=0.0,
                        help="Original VOD time when playing a 1080p excerpt")
    parser.add_argument("--ally-player", default=None,
                        help="Player proven to own the green health bars")
    parser.add_argument("--opponent-player", default=None,
                        help="Player proven to own the red health bars")
    parser.add_argument("--arena-owner", default=None,
                        help="Player proven to own the visible bench")
    parser.add_argument("--champion-weights", type=Path, default=None)
    parser.add_argument("--probability-catalog", type=Path, default=None)
    parser.add_argument("--stage", default=None,
                        help="Independently read stage for this excerpt")
    parser.add_argument("--level", type=int, default=None,
                        help="Independently read player level for this excerpt")
    parser.add_argument("--body-locator", choices=('rf', 'bar'), default='rf',
                        help="RF body boxes or game health-bar anchored crops")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--snapshot", type=Path, default=None,
                        help="Save one annotated frame after an inference result")
    parser.add_argument("--snapshot-after", type=float, default=0.0,
                        help="Minimum elapsed video time before the snapshot")
    args = parser.parse_args()
    if not args.video.is_file() or not args.weights.is_file():
        raise FileNotFoundError("Video or model weights are missing")
    if args.champion_weights and not args.champion_weights.is_file():
        raise FileNotFoundError(args.champion_weights)
    if args.probability_catalog and not args.probability_catalog.is_file():
        raise FileNotFoundError(args.probability_catalog)
    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise RuntimeError(f"Video nao abriu: {args.video}")
    source_fps = capture.get(cv2.CAP_PROP_FPS)
    if not 1 <= source_fps <= 120:
        raise RuntimeError(f"FPS invalido: {source_fps}")
    capture.set(cv2.CAP_PROP_POS_MSEC, args.start * 1000)
    first_frame = int(round(args.start * source_fps))
    requests = Queue(maxsize=1)
    shared = {"latest": None, "error": None}
    lock, stop, ready = Lock(), Event(), Event()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    worker = Thread(target=infer, args=(requests, shared, lock, stop, ready,
                                        args.weights, args.log, args.threshold,
                                        args.ally_player, args.opponent_player,
                                        args.arena_owner, args.champion_weights,
                                        args.probability_catalog, args.stage,
                                        args.level, args.body_locator),
                    daemon=True)
    worker.start()
    if not ready.wait(timeout=90):
        stop.set()
        raise TimeoutError("RF-DETR nao terminou de carregar em 90 segundos")
    with lock:
        startup_error = shared["error"]
    if startup_error:
        raise RuntimeError(startup_error)
    title = "Agente TFT | RF-DETR Large ao vivo"
    if not args.headless:
        cv2.namedWindow(title, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(title, DISPLAY_WIDTH, 766)
    start_wall = time.monotonic()
    last_offer = -1.0
    shown = 0
    latest_video_second = args.start + args.timestamp_offset
    telemetry = TerrainTelemetry()
    layout = BoardLayout()
    arena_index = ArenaVisualIndex()
    last_enemy_bar_time = float("-inf")
    force_opponent = False
    snapshot_saved = False
    try:
        while True:
            elapsed = time.monotonic() - start_wall
            if elapsed >= args.duration:
                break
            target = first_frame + int(elapsed * source_fps)
            current = int(capture.get(cv2.CAP_PROP_POS_FRAMES))
            while current < target - 1:
                if not capture.grab():
                    return
                current += 1
            ok, original = capture.read()
            if not ok:
                break
            frame = (original if original.shape[:2] == (HEIGHT, WIDTH)
                     else cv2.resize(original, (WIDTH, HEIGHT),
                                     interpolation=cv2.INTER_AREA))
            stamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if stamp <= 0:
                stamp = args.start + elapsed
            stamp += args.timestamp_offset
            latest_video_second = stamp
            telemetry_matrix = telemetry.update(frame)
            tiles = layout.update(frame, telemetry.resets, telemetry_matrix)
            terrain_matrix = layout.current_matrix(telemetry_matrix)
            arena_id, arena_visit = arena_index.update(
                frame, telemetry.resets, layout.source)
            if enemy_health_bars(frame) >= 1:
                last_enemy_bar_time = elapsed
            show_opponent = force_opponent or elapsed - last_enemy_bar_time <= 5
            if elapsed - last_offer >= args.infer_interval:
                offer(requests, stamp, frame, terrain_matrix, telemetry.anchors,
                      tiles, layout.source, telemetry.resets, arena_id,
                      arena_visit)
                last_offer = elapsed
            with lock:
                observation, error = shared["latest"], shared["error"]
            if error and args.headless:
                raise RuntimeError(error)
            if not args.headless:
                fps = shown / max(0.01, elapsed)
                preview = overlay(frame, observation, stamp, error,
                                  fps, show_opponent, terrain_matrix,
                                  telemetry.anchors, tiles, layout.source)
                if args.snapshot and not snapshot_saved and elapsed >= args.snapshot_after and observation and (
                        0 <= stamp - observation['video_seconds'] <= 0.5):
                    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
                    if not cv2.imwrite(str(args.snapshot), preview):
                        raise OSError(f'Could not save preview: {args.snapshot}')
                    snapshot_saved = True
                cv2.imshow(title, preview)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key in (ord("c"), ord("C")):
                    force_opponent = not force_opponent
            shown += 1
            next_display = shown / args.display_fps
            delay = next_display - (time.monotonic() - start_wall)
            if delay > 0:
                time.sleep(min(delay, 0.03))
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        capture.release()
        if not args.headless:
            cv2.destroyWindow(title)
        worker.join(timeout=3)
        print(json.dumps({"video_seconds_reached": round(latest_video_second, 2),
                          "displayed_frames": shown, "wall_seconds": round(
                              time.monotonic() - start_wall, 2),
                          "log": str(args.log)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
