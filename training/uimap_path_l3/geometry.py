"""Screen edges, tensor coordinates and board-plane coordinates never share an implicit transform."""
from dataclasses import dataclass
import numpy as np
from . import legacy
from uimap_lite_l2.common import decisions, require

PIXEL_SCALE = np.array([1920., 1080., 1920., 1080.])


def panel_decisions(raw, policy, frame_id):
    rows = decisions(raw, policy)
    for row in rows:
        row.update(frame_id=frame_id, coordinate_space='screen_pixel_edges_1920x1080',
                   precision_validated=False, child_rois_authorized=False)
        if not row['geometry_valid']:
            row['rejection'] = 'invalid_or_inverted_extent_no_clamping'
        elif not row['visibility_above_threshold']:
            row['rejection'] = 'visibility_unresolved'
        else:
            row['rejection'] = 'coarse_only_not_pixel_certified'
    return rows


def checked_corners(values, size=(1920,1080)):
    p = np.asarray(values, dtype=np.float64)
    require(p.shape == (4,) and np.isfinite(p).all(), 'invalid corners')
    l,t,r,b = p
    require(0 <= l < r <= size[0] and 0 <= t < b <= size[1], 'out-of-frame/inverted corners')
    return p


def raster_crop(values, size=(1920,1080)):
    """[left,right) × [top,bottom); validate before integer rounding, never clip silently."""
    l,t,r,b = checked_corners(values, size)
    return [int(np.floor(l)), int(np.floor(t)), int(np.ceil(r)), int(np.ceil(b))]


def project_regions(source_box, observed_box, regions):
    """Diagnostic affine propagation only. It does not certify the observed box."""
    a = checked_corners(source_box); b = checked_corners(observed_box)
    scale = (b[2:] - b[:2]) / (a[2:] - a[:2])
    result = []
    for region in regions:
        r = checked_corners(region)
        require(np.all(r[:2] >= a[:2]) and np.all(r[2:] <= a[2:]), 'child outside its own panel')
        p = np.r_[b[:2] + (r[:2]-a[:2])*scale, b[:2] + (r[2:]-a[:2])*scale]
        result.append(checked_corners(p).tolist())
    return result


def authorize_regions(frame_id, observation, expected_space, independent_error_bound_px, expected_panel):
    """A neural score/low average error is never an error bound for this frame."""
    same = observation.get('frame_id') == frame_id
    space = (observation.get('coordinate_space') == expected_space and
             observation.get('panel') == expected_panel and expected_panel in ('bench','shop'))
    certified = (observation.get('precision_validated') is True and
                 independent_error_bound_px is not None and
                 np.isfinite(independent_error_bound_px) and 0 <= independent_error_bound_px <= 2.)
    allowed = same and space and certified and observation.get('accepted_as_coarse') is True
    return dict(allowed=bool(allowed), frame_matches=same, space_matches=space,
                independently_certified=bool(certified), activation_written=False)


def board_status():
    # L2/L3 locate bench/shop ENVELOPES, not floor landmarks or cell centers.
    return dict(status='unresolved', transform=None, ground_points=None, cells=None,
                reason='board_plane_landmarks_not_observed', derived_from_bench_or_shop=False)


def checked_homography(source, destination):
    """Geometry-only diagnostic for four ordered planar points; not a board detector."""
    a = np.asarray(source, dtype=np.float64); b = np.asarray(destination, dtype=np.float64)
    require(a.shape == b.shape == (4,2) and np.isfinite(a).all() and np.isfinite(b).all(), 'point schema')
    def convex(p):
        e = np.roll(p,-1,axis=0)-p
        cross = e[:,0]*np.roll(e[:,1],-1)-e[:,1]*np.roll(e[:,0],-1)
        return np.all(cross > 1e-6) or np.all(cross < -1e-6)
    require(convex(a) and convex(b), 'degenerate/crossing quadrilateral')
    # Normalize coordinates before DLT; reject ill-conditioned correspondences.
    def normal(p):
        center = p.mean(0); s = np.sqrt(2.) / np.sqrt(((p-center)**2).sum(1)).mean()
        t = np.array([[s,0,-s*center[0]],[0,s,-s*center[1]],[0,0,1.]])
        return (p-center)*s,t
    x,ta=normal(a);y,tb=normal(b);rows=[]
    for (u,v),(p,q) in zip(x,y):
        rows.extend([[-u,-v,-1,0,0,0,p*u,p*v,p],[0,0,0,-u,-v,-1,q*u,q*v,q]])
    _,s,vt=np.linalg.svd(np.asarray(rows))
    require(s[-1]>1e-8 and s[0]/s[-1]<1e6, 'ill-conditioned planar mapping')
    h=np.linalg.inv(tb)@vt[-1].reshape(3,3)@ta
    require(abs(h[2,2])>1e-12, 'invalid homography normalization')
    return h/h[2,2]


def transform_points(h, points):
    h=np.asarray(h,dtype=np.float64);p=np.asarray(points,dtype=np.float64)
    require(h.shape==(3,3) and p.ndim==2 and p.shape[1]==2 and np.isfinite(h).all() and np.isfinite(p).all(), 'transform schema')
    out=np.c_[p,np.ones(len(p))]@h.T
    require(np.all(abs(out[:,2])>1e-9),'point at projective infinity')
    return out[:,:2]/out[:,2:3]
