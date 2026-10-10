"""Locate a known TFT arena after a VOD zoom or pan.

The result is a visual guide only. Feature matches never identify players,
champions, occupancy, or a new arena skin.
"""
from __future__ import annotations

from pathlib import Path
import math


class ArenaRegistrar:
    def __init__(self, root: Path, profiles: list[dict]):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.cv2 = self.np = None
            self.references = []
            return
        self.cv2, self.np = cv2, np
        # The arena texture survives this reduction in the reviewed VODs;
        # it cuts feature work while coordinates remain in canonical 1080p.
        self.width, self.height = 480, 270
        self.canonical_scale = 1920 / self.width
        self.detector = cv2.ORB_create(nfeatures=1500)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        mask = np.zeros((self.height, self.width), np.uint8)
        mask[30:218, 85:390] = 255
        self.references = []
        for profile in profiles:
            path = root / 'configs/ui/arena-references' / (profile['id'].split('-arena-')[0] + '-960.jpg')
            if profile['id'].startswith('pond-'):
                path = root / 'configs/ui/arena-references/pond-960.jpg'
            if not path.is_file():
                continue
            gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if gray is None or gray.shape != (540, 960):
                continue
            gray = cv2.resize(gray, (self.width, self.height), interpolation=cv2.INTER_AREA)
            points, descriptors = self.detector.detectAndCompute(gray, mask)
            if descriptors is not None:
                self.references.append((profile, points, descriptors))

    def observe(self, image):
        if self.cv2 is None or image.size != (1920, 1080):
            return None
        cv2, np = self.cv2, self.np
        target = cv2.cvtColor(np.asarray(image.resize((self.width, self.height))), cv2.COLOR_RGB2GRAY)
        mask = np.zeros((self.height, self.width), np.uint8)
        mask[:225, 75:450] = 255
        target_points, target_descriptors = self.detector.detectAndCompute(target, mask)
        if target_descriptors is None:
            return None
        best = None
        for profile, points, descriptors in self.references:
            pairs = self.matcher.knnMatch(descriptors, target_descriptors, k=2)
            matches = [pair[0] for pair in pairs
                       if len(pair) == 2 and pair[0].distance < .75 * pair[1].distance]
            if len(matches) < 18:
                continue
            source = np.float32([points[row.queryIdx].pt for row in matches])
            destination = np.float32([target_points[row.trainIdx].pt for row in matches])
            transform, inliers = cv2.estimateAffinePartial2D(
                source, destination, method=cv2.RANSAC, ransacReprojThreshold=1.5)
            if transform is None or inliers is None:
                continue
            count = int(inliers.sum())
            scale = math.hypot(transform[0, 0], transform[1, 0])
            rotation = math.degrees(math.atan2(transform[1, 0], transform[0, 0]))
            if count < 18 or count / len(matches) < .43 or not .70 <= scale <= 1.90 or abs(rotation) > 5:
                continue
            if best is None or count > best[0]:
                best = (count, profile, transform, scale, rotation)
        if best is None:
            return None
        count, profile, transform, scale, rotation = best
        def project(point):
            x, y = point
            factor = self.canonical_scale
            return [round(float(transform[0, 0] * x + transform[0, 1] * y + factor * transform[0, 2]), 1),
                    round(float(transform[1, 0] * x + transform[1, 1] * y + factor * transform[1, 2]), 1)]
        def rows(key):
            result = []
            for left, right, y in profile.get(key, []):
                a, b, middle = project((left, y)), project((right, y)), project(((left + right) / 2, y))
                result.append([a[0], b[0], middle[1]])
            return result
        opposite = bool(profile.get('enemy_board_visible'))
        return dict(status='arena_candidate_match', profile=profile['id'],
                    registration='orb_affine_candidate_v1', inlier_count=count,
                    scale=round(scale, 3), rotation_degrees=round(rotation, 2),
                    upper=[project(point) for point in profile.get('upper_reserve', [])] if opposite else [],
                    lower=[project(point) for point in profile['lower_reserve']],
                    enemy_rows=rows('enemy_board_rows') if opposite else [],
                    own_rows=rows('own_board_rows'), enemy_board_visible=opposite,
                    owner_verified=False, training_label=False)
