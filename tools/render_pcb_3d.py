#!/usr/bin/env python3
"""3D render of an Altium .PcbDoc: board substrate, artwork texture and the
component bodies that are embedded in the file as compressed STEP models.

Everything drawn comes from the design file itself:
  * board outline  - Board Regions stream
  * top/bottom art - copper, pads, overlay from the same file
  * components     - STEP (AP203/214) models stored in the PcbDoc "Models"
                     stream, placed with the MODEL.2D / MODEL.3D transforms
                     recorded per body in ComponentBodies6

Missing model -> the part is simply not drawn (never substituted).

    python3 render_pcb_3d.py board.PcbDoc out.png --az 35 --el 28 --ppm 18
"""
import argparse, math, os, sys, zlib, struct
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from altium_pcb import PcbDoc, SCALE
import render_pcb_2d as r2

# ---------------------------------------------------------------- STEP -> tris
def read_step_shape(path):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    r = STEPControl_Reader()
    if r.ReadFile(path) != 1:
        raise RuntimeError('STEP read failed: ' + path)
    r.TransferRoots()
    sh = r.OneShape()
    BRepMesh_IncrementalMesh(sh, 0.12, False, 0.35, True)
    return sh


def tessellate(sh):
    from OCP.BRep import BRep_Tool
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopLoc import TopLoc_Location
    import OCP.TopoDS as TD
    verts, faces = [], []
    ex = TopExp_Explorer(sh, TopAbs_FACE)
    loc = TopLoc_Location()
    while ex.More():
        f = TD.TopoDS.Face(ex.Current())
        tri = BRep_Tool.Triangulation_s(f, loc)
        if tri is not None:
            base = len(verts)
            trsf = loc.Transformation()
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(trsf)
                verts.append((p.X(), p.Y(), p.Z()))
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                faces.append((base + a - 1, base + b - 1, base + c - 1))
        ex.Next()
    if not verts:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int32)
    return np.array(verts, dtype=np.float64), np.array(faces, dtype=np.int32)


class ModelCache:
    def __init__(self, doc, workdir):
        import olefile
        self.doc = doc
        self.dir = workdir
        os.makedirs(workdir, exist_ok=True)
        o = olefile.OleFileIO(doc.path)
        names = ['/'.join(e) for e in o.listdir(streams=True) if e[0] == 'Models']
        # Models/Data lists, per model id, the properties including NAME=...
        self.by_id = {}
        md = o.openstream('Models/Data').read()
        pos = 0
        while pos < len(md) - 4:
            ln = struct.unpack_from('<I', md, pos)[0]
            if ln == 0 or pos + 4 + ln > len(md):
                break
            txt = md[pos + 4:pos + 4 + ln].decode('cp1252', 'replace')
            props = {}
            for part in txt.replace('\x00', '').split('|'):
                if '=' in part:
                    k, v = part.split('=', 1)
                    props[k.upper()] = v
            if 'ID' in props:
                self.by_id[props['ID'].upper()] = props
            pos += 4 + ln
        # numeric streams are the models themselves, in the same order
        nums = sorted([n for n in names if n.split('/')[-1].isdigit()],
                      key=lambda s: int(s.split('/')[-1]))
        self.streams = nums
        self.cache = {}

    def model(self, model_id, index_hint=None):
        mid = model_id.upper()
        if mid in self.cache:
            return self.cache[mid]
        props = self.by_id.get(mid, {})
        st = self._stream_for(mid, index_hint)
        if st is None:
            self.cache[mid] = (None, None, props)
            return self.cache[mid]
        import olefile
        o = olefile.OleFileIO(self.doc.path)
        raw = o.openstream(st).read()
        path = os.path.join(self.dir, mid.strip('{}') + '.step')
        try:
            txt = zlib.decompress(raw)
        except Exception:
            txt = raw
        if not txt.lstrip().startswith(b'ISO-10303'):
            self.cache[mid] = (None, None, props)
            return self.cache[mid]
        with open(path, 'wb') as fh:
            fh.write(txt)
        v, f = tessellate(read_step_shape(path))
        self.cache[mid] = (v, f, props)
        return self.cache[mid]

    def _stream_for(self, mid, hint):
        # order of Models/Data entries matches Models/0,1,2,...
        order = list(self.by_id.keys())
        if mid in order:
            i = order.index(mid)
            if i < len(self.streams):
                return self.streams[i]
        if hint is not None and 0 <= hint < len(self.streams):
            return self.streams[hint]
        return None


def rot_mat(rx, ry, rz):
    rx, ry, rz = np.radians([rx, ry, rz])
    Rx = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
    Ry = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]])
    Rz = np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def mil(v, dflt=0.0):
    s = str(v).replace('mil', '').strip()
    try:
        return float(s) * 0.0254
    except Exception:
        return dflt


def body_instances(doc, cache):
    """Return list of (verts, faces, color) in board millimetres, z-up."""
    comps = doc.components
    out = []
    missing = 0
    moved = 0
    for b in doc.bodies:
        p = {k.upper(): v for k, v in b['props'].items()}
        mid = p.get('MODELID', '')
        v, f, mprops = cache.model(mid)
        if v is None or len(v) == 0:
            missing += 1
            continue
        dx = mil(p.get('MODEL.2D.X', '0mil'))
        dy = mil(p.get('MODEL.2D.Y', '0mil'))
        dz = mil(p.get('MODEL.3D.DZ', '0mil'))
        rx = float(p.get('MODEL.3D.ROTX', 0) or 0)
        ry = float(p.get('MODEL.3D.ROTY', 0) or 0)
        rz = float(p.get('MODEL.3D.ROTZ', 0) or 0)
        stand = mil(p.get('STANDOFFHEIGHT', '0mil'))
        # NOTE: the recorded MODEL.2D position is used verbatim.  Library
        # models may carry their own origin offset (the CR1220 holder in this
        # design sits 34 mm off its own origin and the designer compensated in
        # the placement), so re-centring the geometry would move it wrongly.
        R = rot_mat(rx, ry, rz)
        wv = (v @ R.T) + np.array([dx, -dy, dz + stand])
        col = p.get('BODYCOLOR3D')
        try:
            c_int = int(col)
            color = (c_int & 0xFF, (c_int >> 8) & 0xFF, (c_int >> 16) & 0xFF)
        except Exception:
            color = (150, 150, 155)
        out.append((wv, f, color))
    return out, missing, moved


# ---------------------------------------------------------------- rendering
def look_at(az, el):
    a, e = math.radians(az), math.radians(el)
    fwd = np.array([math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), -math.sin(e)])
    up_world = np.array([0, 0, 1.0])
    right = np.cross(fwd, up_world)
    if np.linalg.norm(right) < 1e-9:
        right = np.array([1.0, 0, 0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    return fwd, right, up


def project(P, fwd, right, up, center, scale, W, H):
    x = (P - center) @ right
    y = (P - center) @ up
    d = (P - center) @ fwd
    return np.stack([W / 2 + x * scale, H / 2 - y * scale, d], axis=1)


def shade(normals, base, light):
    lam = np.clip(normals @ light, 0, 1)
    amb = 0.42
    spec = np.clip(normals @ ((light + np.array([0, 0, 1.0])) / np.linalg.norm(light + np.array([0, 0, 1.0]))), 0, 1) ** 24
    rgb = np.array(base, dtype=np.float64)
    out = rgb[None, :] * (amb + 0.78 * lam[:, None]) + 255 * 0.22 * spec[:, None]
    return np.clip(out, 0, 255)


def warp_artwork(art, view, cam, W, H, SS):
    """Return the artwork image warped into screen space (RGBA)."""
    # artwork pixel (ai, aj) -> board mm -> screen
    s = view.s
    def board_to_art_xy(x, y):
        px = (x - view.minx + view.m) * s
        py = (view.maxy - y + view.m) * s
        if view.flip:
            px = view.w - px
        return px, py
    # screen = a*x + b*y + c   (linear in board mm)
    fwd, right, up = cam
    # screen x depends on right·(x,y,0) ; screen y on up·(x,y,0)
    ax, ay = right[0], right[1]
    bx, by = up[0], up[1]
    # inverse: board mm from artwork pixel
    A = np.array([[ax, ay], [-bx, -by]])   # screen delta (sx, sy) = A * (dx, dy)
    Ainv = np.linalg.inv(A)
    # board->screen offset: we need centre/scale; use the same project() as the
    # renderer, evaluated at the board origin, with z = thickness (top face)
    return Ainv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pcbdoc')
    ap.add_argument('out')
    ap.add_argument('--az', type=float, default=38)
    ap.add_argument('--el', type=float, default=30)
    ap.add_argument('--ppm', type=float, default=16, help='artwork pixels per mm')
    ap.add_argument('--width', type=int, default=2200)
    ap.add_argument('--side', choices=['top', 'bottom'], default='top')
    ap.add_argument('--thickness', type=float, default=1.6)
    ap.add_argument('--ss', type=int, default=2, help='supersampling')
    ap.add_argument('--shadow', action='store_true', default=True)
    a = ap.parse_args()

    doc = PcbDoc(a.pcbdoc)
    work = os.path.join(os.path.dirname(os.path.abspath(a.out)), '_stepcache',
                        os.path.basename(a.pcbdoc).replace('.PcbDoc', ''))
    cache = ModelCache(doc, work)
    insts, missing, moved = body_instances(doc, cache)
    print(f'models: {len(insts)} bodies drawn, {missing} missing, {moved} repositioned')

    art, view = r2.draw_side(doc, side=a.side, px_per_mm=a.ppm, with_bg=False,
                             margin_mm=0.0)

    # world geometry
    top_z = a.thickness
    pces = []
    light = np.array([0.42, -0.55, 0.72]); light /= np.linalg.norm(light)

    allpts = []
    for (v, f, c) in insts:
        allpts.append(v)
    if not allpts:
        raise SystemExit('no component models')
    allv = np.vstack(allpts)
    outline = np.array(doc.board_outline, dtype=float)
    pts_for_frame = np.vstack([allv, np.column_stack([outline, np.zeros(len(outline))]),
                               np.column_stack([outline, np.full(len(outline), top_z)])])
    center = (pts_for_frame.min(0) + pts_for_frame.max(0)) / 2
    size = (pts_for_frame.max(0) - pts_for_frame.min(0))
    fwd, right, up = look_at(a.az, a.el)
    ext_x = np.abs(pts_for_frame - center) @ np.abs(right)
    ext_y = np.abs(pts_for_frame - center) @ np.abs(up)
    span_x, span_y = 2 * ext_x.max(), 2 * ext_y.max()
    W = a.width
    H = int(W * span_y / span_x)
    scale = W / span_x
    SS = a.ss
    Wc, Hc = W * SS, H * SS

    img = Image.new('RGB', (Wc, Hc), (13, 15, 18))
    d = ImageDraw.Draw(img)

    # ---- background gradient
    grad = Image.new('L', (1, Hc))
    for i in range(Hc):
        v = int(30 * (1 - i / Hc) + 8)
        grad.putpixel((0, i), v)
    grad = grad.resize((Wc, Hc))
    img = Image.merge('RGB', (grad.point(lambda x: int(x * 0.7)),
                              grad.point(lambda x: int(x * 0.85)),
                              grad.point(lambda x: x)))
    d = ImageDraw.Draw(img)

    def pr(P):
        return project(P, fwd, right, up, center, scale * SS, Wc, Hc)

    # ---- board substrate: side walls
    sil = np.column_stack([outline, np.full(len(outline), top_z)])
    sil0 = np.column_stack([outline, np.zeros(len(outline))])
    p_top = pr(sil); p_bot = pr(sil0)
    for i in range(len(outline)):
        j = (i + 1) % len(outline)
        quad = [tuple(p_top[i][:2]), tuple(p_top[j][:2]), tuple(p_bot[j][:2]), tuple(p_bot[i][:2])]
        e1 = sil[j] - sil[i]; e2 = sil0[i] - sil[i]
        n = np.cross(e1 / (np.linalg.norm(e1) + 1e-9), e2 / (np.linalg.norm(e2) + 1e-9))
        c = shade(np.array([n / (np.linalg.norm(n) + 1e-9)]), (26, 92, 58), light)[0]
        d.polygon(quad, fill=tuple(int(x) for x in c))

    # ---- top face: warped artwork
    mask = Image.new('L', (Wc, Hc), 0)
    ImageDraw.Draw(mask).polygon([tuple(p) for p in p_top[:, :2]], fill=255)
    # affine: artwork px -> screen px
    s = view.s
    # board (x,y) -> art px
    def art_px(x, y):
        px = (x - view.minx + view.m) * s
        py = (view.maxy - y + view.m) * s
        if view.flip:
            px = view.w - px
        return px, py
    o1 = np.array(art_px(0.0, 0.0)); o2 = np.array(art_px(1.0, 0.0)); o3 = np.array(art_px(0.0, 1.0))
    t1 = pr(np.array([[0.0, 0.0, top_z]]))[0][:2]
    t2 = pr(np.array([[1.0, 0.0, top_z]]))[0][:2]
    t3 = pr(np.array([[0.0, 1.0, top_z]]))[0][:2]
    # screen = M * (art_px - o1) + t1  ->  art_px = M^-1 * (screen - t1) + o1
    M = np.column_stack([(t2 - t1), (t3 - t1)])     # board mm -> screen px
    B = np.column_stack([(o2 - o1), (o3 - o1)])     # board mm -> artwork px
    T = M @ np.linalg.inv(B)                        # artwork px -> screen px
    Tinv = np.linalg.inv(T)
    # PIL AFFINE maps output (x,y) -> input (a x + b y + c, d x + e y + f)
    cA = o1 - Tinv @ t1
    coeffs = (Tinv[0, 0], Tinv[0, 1], cA[0], Tinv[1, 0], Tinv[1, 1], cA[1])
    warped = art.transform((Wc, Hc), Image.AFFINE, coeffs, resample=Image.BICUBIC)
    img.paste(warped.convert('RGB'), (0, 0), Image.composite(warped.split()[-1], Image.new('L', (Wc, Hc), 0), mask))

    # ---- component bodies, painter's algorithm (far -> near)
    tris = []
    for (v, f, c) in insts:
        P = pr(v)
        tri_pts = P[f]
        depth = tri_pts[:, :, 2].mean(axis=1)
        v0 = v[f[:, 0]]; v1 = v[f[:, 1]]; v2 = v[f[:, 2]]
        n = np.cross(v1 - v0, v2 - v0)
        ln = np.linalg.norm(n, axis=1)
        ln[ln == 0] = 1
        n = n / ln[:, None]
        # flip normals that point away from the viewer
        if n.mean(axis=0) @ fwd > 0:
            n = -n
        cols = shade(n, c, light)
        for k in range(len(f)):
            tris.append((depth[k], tri_pts[k, :, :2], cols[k]))
    tris.sort(key=lambda t: -t[0])
    for depth, pts, col in tris:
        d.polygon([tuple(p) for p in pts], fill=tuple(int(x) for x in col))

    out = img.resize((W, H), Image.LANCZOS)
    out.save(a.out)
    print(a.out, out.size)


if __name__ == '__main__':
    main()
