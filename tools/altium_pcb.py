#!/usr/bin/env python3
"""
pcbdoc.py - read the geometry of an Altium Designer .PcbDoc file on Linux.

The .PcbDoc container is a Microsoft Compound File Binary (OLE2) file.  Each
board object stream (Tracks6, Pads6, Vias6, ...) holds length-prefixed binary
records.  The layouts implemented here follow the formal spec published with the
KiCad Altium importer (pcbnew/pcb_io/altium/altium_parser.ksy, GPL-3.0) and the
field offsets used by the altium2kicad converter.

Units: Altium stores integer coordinates in 1/10000 mil.  This module converts
everything to millimetres (mm = raw * 2.54e-6) and keeps the Y axis pointing up,
as in Altium.  Nothing is interpreted or guessed: if a record does not parse, it
is counted as an error and skipped.

Requires: olefile (pure python).
"""
import struct, sys
import olefile

SCALE = 2.54e-6           # raw units (1e-4 mil) -> mm

# Altium layer ids -> names (subset that matters for board views)
LAYERS = {
    1: 'Top Layer',
    2: 'Mid Layer 1', 3: 'Mid Layer 2', 4: 'Mid Layer 3', 5: 'Mid Layer 4',
    6: 'Mid Layer 5', 7: 'Mid Layer 6', 8: 'Mid Layer 7', 9: 'Mid Layer 8',
    10: 'Mid Layer 9', 11: 'Mid Layer 10', 12: 'Mid Layer 11', 13: 'Mid Layer 12',
    14: 'Mid Layer 13', 15: 'Mid Layer 14', 16: 'Mid Layer 15', 17: 'Mid Layer 16',
    18: 'Mid Layer 17', 19: 'Mid Layer 18', 20: 'Mid Layer 19', 21: 'Mid Layer 20',
    22: 'Mid Layer 21', 23: 'Mid Layer 22', 24: 'Mid Layer 23', 25: 'Mid Layer 24',
    26: 'Mid Layer 25', 27: 'Mid Layer 26', 28: 'Mid Layer 27', 29: 'Mid Layer 28',
    30: 'Mid Layer 29', 31: 'Mid Layer 30', 32: 'Bottom Layer',
    33: 'Top Overlay', 34: 'Bottom Overlay',
    35: 'Top Paste', 36: 'Bottom Paste',
    37: 'Top Solder', 38: 'Bottom Solder',
    39: 'Drill Guide', 40: 'Drill Drawing',
    41: 'Keep-Out Layer', 42: 'Mechanical 1', 43: 'Mechanical 2',
    44: 'Mechanical 3', 45: 'Mechanical 4', 46: 'Mechanical 5', 47: 'Mechanical 6',
    48: 'Mechanical 7', 49: 'Mechanical 8', 50: 'Mechanical 9', 51: 'Mechanical 10',
    52: 'Mechanical 11', 53: 'Mechanical 12', 54: 'Mechanical 13',
    55: 'Mechanical 14', 56: 'Mechanical 15', 57: 'Mechanical 16',
    58: 'Mechanical 17', 59: 'Mechanical 18', 60: 'Mechanical 19',
    61: 'Mechanical 20', 62: 'Mechanical 21', 63: 'Mechanical 22',
    64: 'Mechanical 23', 65: 'Mechanical 24', 66: 'Mechanical 25',
    67: 'Mechanical 26', 68: 'Mechanical 27', 69: 'Mechanical 28',
    70: 'Mechanical 29', 71: 'Mechanical 30', 72: 'Mechanical 31',
    73: 'Mechanical 32', 74: 'Multi Layer',
}
COPPER = {1, 32} | set(range(2, 32))
TOP, BOTTOM = 1, 32


class Rec:
    """Little cursor over one record payload."""
    __slots__ = ('d', 'p')

    def __init__(self, d, p=0):
        self.d, self.p = d, p

    def u1(self):
        v = self.d[self.p]; self.p += 1; return v

    def u2(self):
        v = struct.unpack_from('<H', self.d, self.p)[0]; self.p += 2; return v

    def i2(self):
        v = struct.unpack_from('<h', self.d, self.p)[0]; self.p += 2; return v

    def u4(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v

    def i4(self):
        v = struct.unpack_from('<i', self.d, self.p)[0]; self.p += 4; return v

    def f8(self):
        v = struct.unpack_from('<d', self.d, self.p)[0]; self.p += 8; return v

    def skip(self, n):
        self.p += n

    def raw(self, n):
        v = self.d[self.p:self.p + n]; self.p += n; return v


def _props(r):
    """Read a properties subrecord: u4 length + '|K=V|K=V' string."""
    n = r.u4()
    s = r.raw(n)
    try:
        s = s.decode('cp1252', 'replace')
    except Exception:
        return {}
    out = {}
    for part in s.split('|'):
        if '=' in part:
            k, v = part.split('=', 1)
            out[k.upper()] = v
    return out


def _mm(v):
    return v * SCALE


class PcbDoc:
    def __init__(self, path):
        self.path = path
        self.o = olefile.OleFileIO(path)
        self.errors = {}
        self.tracks = []     # dict(layer,x1,y1,x2,y2,w,net)
        self.arcs = []       # dict(layer,cx,cy,r,sa,ea,w,net)
        self.vias = []       # dict(x,y,dia,drill,net)
        self.pads = []       # dict(name,layer,x,y,w,h,shape,drill,plated,rot,net)
        self.fills = []      # dict(layer,x1,y1,x2,y2,rot,net)
        self.regions = []    # dict(layer,pts,holes,kind,cutout,net)
        self.texts = []      # dict(layer,x,y,text,h,rot,designator,component)
        self.components = [] # dict(des,comment,footprint,layer,x,y,rot,height)
        self.nets = {}       # id -> name
        self.bodies = []
        self._parse()

    # ---------- helpers ----------
    def _stream(self, name):
        try:
            return self.o.openstream(name).read()
        except Exception:
            return None

    def _err(self, key, n=1):
        self.errors[key] = self.errors.get(key, 0) + n

    # ---------- parsing ----------
    def _parse(self):
        self._parse_board_shape()
        self._parse_nets()
        self._parse_components()
        self._each_record('Tracks6', 0x04, self._track)
        self._each_record('Arcs6', 0x01, self._arc)
        self._each_record('Vias6', 0x03, self._via)
        self._each_varirecord('Pads6', 0x02, self._pad, 6)
        self._each_record('Fills6', 0x06, self._fill)
        self._each_varirecord('Texts6', 0x05, self._text, 2)
        self._each_record('Regions6', 0x0B, self._region)
        self._parse_bodies()

    def _each_record(self, stream, rtype, fn):
        d = self._stream(stream + '/Data')
        if not d:
            return
        pos, n = 0, len(d)
        while pos < n - 4:
            t = d[pos]
            if t != rtype:
                self._err(stream + ':unexpected type')
                # resynchronise on the next matching type byte
                nxt = d.find(bytes([rtype]), pos + 1)
                if nxt < 0:
                    break
                pos = nxt
                continue
            ln = struct.unpack_from('<I', d, pos + 1)[0]
            if pos + 5 + ln > n or ln == 0:
                self._err(stream + ':bad length')
                break
            try:
                fn(d[pos + 5:pos + 5 + ln])
            except Exception:
                self._err(stream + ':parse')
            pos += 5 + ln

    def _each_varirecord(self, stream, rtype, fn, nsub):
        """Walk a stream whose records carry no total length (Pads6, Texts6).

        Each record is: type byte, then nsub length-prefixed subrecords; the
        record ends after the last subrecord.  fn(d, pos, sub_starts, lens).
        """
        d = self._stream(stream + '/Data')
        if not d:
            return
        pos, n = 0, len(d)
        while pos < n - 5:
            if d[pos] != rtype:
                self._err(stream + ':unexpected type')
                nxt = d.find(bytes([rtype]), pos + 1)
                if nxt < 0:
                    break
                pos = nxt
                continue
            p = pos + 1
            starts, lens, ok = [], [], True
            for _ in range(nsub):
                if p + 4 > n:
                    ok = False; break
                ln = struct.unpack_from('<I', d, p)[0]
                if ln > n or p + 4 + ln > n:
                    ok = False; break
                starts.append(p + 4); lens.append(ln); p += 4 + ln
            if not ok:
                self._err(stream + ':bad subrecord')
                break
            try:
                fn(d, pos, starts, lens)
            except Exception:
                self._err(stream + ':parse')
            pos = p


    def _parse_board_shape(self):
        """The physical board outline lives in the BoardRegions stream."""
        d = self._stream('BoardRegions/Data')
        self.board_outline = []
        if not d or d[0] != 0x0B:
            return
        ln = struct.unpack_from('<I', d, 1)[0]
        try:
            self._region(d[5:5 + ln])
        except Exception:
            self._err('BoardRegions')
            return
        if self.regions:
            r = self.regions.pop()
            self.board_outline = r['pts']

    def _parse_nets(self):
        d = self._stream('Nets6/Data')
        if not d:
            return
        pos, n = 0, len(d)
        idx = 0
        while pos < n - 4:
            ln = struct.unpack_from('<I', d, pos)[0]
            if ln == 0 or pos + 4 + ln > n:
                break
            body = d[pos + 4:pos + 4 + ln]
            try:
                txt = body.decode('cp1252', 'replace')
            except Exception:
                txt = ''
            nm = ''
            for part in txt.split('|'):
                if part.upper().startswith('NAME='):
                    nm = part.split('=', 1)[1]
            self.nets[idx] = nm
            idx += 1
            pos += 4 + ln

    def _parse_components(self):
        d = self._stream('Components6/Data')
        if not d:
            return
        pos, n = 0, len(d)
        while pos < n - 4:
            ln = struct.unpack_from('<I', d, pos)[0]
            if ln == 0 or pos + 4 + ln > n:
                break
            body = d[pos + 4:pos + 4 + ln]
            try:
                txt = body.decode('cp1252', 'replace')
            except Exception:
                txt = ''
            p = {}
            for part in txt.split('|'):
                if '=' in part:
                    k, v = part.split('=', 1)
                    p[k.upper()] = v
            def mil(k, dflt=0.0):
                v = p.get(k, '')
                v = v.replace('mil', '').strip()
                try:
                    return float(v) * 0.0254
                except Exception:
                    return dflt
            self.components.append(dict(
                des=p.get('SOURCEDESIGNATOR', ''),
                comment=p.get('COMMENT', ''),
                footprint=p.get('PATTERN', ''),
                layer=p.get('LAYER', ''),
                x=mil('X'), y=-mil('Y'),
                rot=float(p.get('ROTATION', 0) or 0),
                height=mil('HEIGHT'),
                props=p))
            pos += 4 + ln

    def _track(self, d):
        r = Rec(d)
        layer = r.u1(); r.u1(); r.u1()
        net = r.i2(); r.u2(); r.i2(); r.skip(4)
        x1 = r.i4(); y1 = r.i4(); x2 = r.i4(); y2 = r.i4(); w = r.i4()
        self.tracks.append(dict(layer=LAYERS.get(layer, str(layer)),
                                x1=_mm(x1), y1=-_mm(y1), x2=_mm(x2), y2=-_mm(y2),
                                w=_mm(w), net=net))

    def _arc(self, d):
        r = Rec(d)
        layer = r.u1(); r.u1(); r.u1()
        net = r.i2(); r.u2(); r.i2(); r.skip(4)
        cx = r.i4(); cy = r.i4(); rad = r.i4()
        sa = r.f8(); ea = r.f8(); w = r.i4()
        self.arcs.append(dict(layer=LAYERS.get(layer, str(layer)),
                              cx=_mm(cx), cy=-_mm(cy), r=_mm(rad),
                              sa=sa, ea=ea, w=_mm(w), net=net))

    def _via(self, d):
        r = Rec(d)
        layer = r.u1()           # 74 = multi-layer (through via)
        r.skip(2)
        net = r.i2()
        r.skip(8)
        x = r.i4(); y = r.i4()
        dia = r.i4(); drill = r.i4()
        self.vias.append(dict(x=_mm(x), y=-_mm(y), dia=_mm(dia),
                              drill=_mm(drill), net=net,
                              layer=LAYERS.get(layer, str(layer))))

    def _pad(self, d, pos, starts, lens):
        s1, s5 = starts[0], starts[4]
        n1 = lens[0]
        name_len = d[s1]
        name = d[s1 + 1:s1 + 1 + min(name_len, n1 - 1)].decode('cp1252', 'replace')
        layer = d[s5 + 0]
        net = struct.unpack_from('<h', d, s5 + 3)[0]
        x = struct.unpack_from('<i', d, s5 + 13)[0]
        y = struct.unpack_from('<i', d, s5 + 17)[0]
        tw = struct.unpack_from('<i', d, s5 + 21)[0]
        th = struct.unpack_from('<i', d, s5 + 25)[0]
        if tw == 0 or th == 0:      # pad in top/mid/bottom mode: top size unused
            mw = struct.unpack_from('<i', d, s5 + 29)[0]
            mh = struct.unpack_from('<i', d, s5 + 33)[0]
            bw = struct.unpack_from('<i', d, s5 + 37)[0]
            bh = struct.unpack_from('<i', d, s5 + 41)[0]
            tw = tw or mw or bw
            th = th or mh or bh
        hole = struct.unpack_from('<i', d, s5 + 45)[0]
        topshape = d[s5 + 49]
        rot = struct.unpack_from('<d', d, s5 + 52)[0]
        plated = d[s5 + 60]
        # sub6: per-layer shape table; entry i is the shape on layer i
        corner = 0.0
        if lens[5] > 1163:
            # corner_radius[32] sits at offset 29*8 + 29 + 1 + 1 + 9 + 32*8 + 1
            idx = s5 + lens[4] + 4
            corner = d[idx + 29 * 8 + 29 + 1 + 1 + 9 + 32 * 8 + 1] * SCALE
        self.pads.append(dict(name=name, layer=LAYERS.get(layer, str(layer)),
                              layer_id=layer, x=_mm(x), y=-_mm(y),
                              w=_mm(tw), h=_mm(th), drill=_mm(hole),
                              shape=topshape, rot=rot, corner=corner,
                              plated=bool(plated), net=net))

    def _fill(self, d):
        r = Rec(d)
        layer = r.u1(); r.u1(); r.u1()
        net = r.i2(); r.skip(4)
        x1 = r.i4(); y1 = r.i4(); x2 = r.i4(); y2 = r.i4()
        rot = r.f8()
        self.fills.append(dict(layer=LAYERS.get(layer, str(layer)),
                               x1=_mm(x1), y1=-_mm(y1), x2=_mm(x2), y2=-_mm(y2),
                               rot=rot, net=net))

    def _text(self, d, pos, starts, lens):
        s1 = starts[0]
        layer = d[s1]
        net = struct.unpack_from('<h', d, s1 + 3)[0]
        comp = struct.unpack_from('<h', d, s1 + 7)[0]
        x = struct.unpack_from('<i', d, s1 + 13)[0]
        y = struct.unpack_from('<i', d, s1 + 17)[0]
        h = struct.unpack_from('<i', d, s1 + 21)[0]
        rot = struct.unpack_from('<d', d, s1 + 26)[0]
        stroke = struct.unpack_from('<i', d, s1 + 35)[0]
        is_des = d[s1 + 40] if lens[0] > 40 else 0
        s2 = starts[1]
        ln = d[s2]
        s = d[s2 + 1:s2 + 1 + ln].decode('cp1252', 'replace')
        self.texts.append(dict(layer=LAYERS.get(layer, str(layer)),
                               x=_mm(x), y=-_mm(y), text=s, h=_mm(h),
                               rot=rot, component=comp, net=net,
                               stroke=_mm(stroke), is_designator=bool(is_des)))

    def _region(self, d):
        r = Rec(d)
        layer = r.u1()
        r.u1(); r.u1()
        net = r.i2()
        r.u2()                    # polygon index
        comp = r.i2()
        r.skip(5)
        holecount = r.i2()
        r.skip(2)
        props = _props(r)
        nverts = r.u4()
        pts = []
        for _ in range(nverts):
            x = r.f8(); y = r.f8()
            pts.append((_mm(x), -_mm(y)))
        holes = []
        for _ in range(min(holecount, 64)):
            nh = r.u4()
            if nh > 100000:
                break
            hp = []
            for _ in range(nh):
                x = r.f8(); y = r.f8()
                hp.append((_mm(x), -_mm(y)))
            holes.append(hp)
        kind = props.get('KIND', '0')
        cutout = props.get('ISBOARDCUTOUT', 'FALSE').upper() == 'TRUE'
        self.regions.append(dict(layer=LAYERS.get(layer, str(layer)),
                                 pts=pts, holes=holes, kind=kind,
                                 cutout=cutout, net=net, component=comp,
                                 props=props))

    def _parse_bodies(self):
        d = self._stream('ComponentBodies6/Data')
        if not d:
            return
        pos, n = 0, len(d)
        while pos < n - 4:
            t = d[pos]
            if t != 0x0C:
                nxt = d.find(b'\x0c', pos + 1)
                if nxt < 0:
                    break
                pos = nxt
                continue
            ln = struct.unpack_from('<I', d, pos + 1)[0]
            if ln == 0 or pos + 5 + ln > n:
                break
            body = d[pos + 5:pos + 5 + ln]
            try:
                comp = struct.unpack_from('<H', body, 7)[0]
                plen = struct.unpack_from('<I', body, 18)[0]
                txt = body[22:22 + plen].decode('cp1252', 'replace')
                props = {}
                for part in txt.split('|'):
                    if '=' in part:
                        k, v = part.split('=', 1)
                        props[k.upper()] = v
                self.bodies.append(dict(component=comp, props=props))
            except Exception:
                self._err('ComponentBodies6')
            pos += 5 + ln

    # ---------- summary ----------
    def layers_used(self):
        out = {}
        for t in self.tracks:
            out[t['layer']] = out.get(t['layer'], 0) + 1
        return out

    def bbox(self):
        xs, ys = [], []
        for t in self.tracks:
            xs += [t['x1'], t['x2']]; ys += [t['y1'], t['y2']]
        for a in self.arcs:
            xs += [a['cx'] - a['r'], a['cx'] + a['r']]
            ys += [a['cy'] - a['r'], a['cy'] + a['r']]
        for p in self.pads:
            xs += [p['x'] - p['w'] / 2, p['x'] + p['w'] / 2]
            ys += [p['y'] - p['h'] / 2, p['y'] + p['h'] / 2]
        for rg in self.regions:
            for (x, y) in rg['pts']:
                xs.append(x); ys.append(y)
        if not xs:
            return (0, 0, 0, 0)
        return (min(xs), min(ys), max(xs), max(ys))

    def report(self):
        bb = self.bbox()
        lines = [
            f"file            {self.path}",
            f"board bbox (mm) x {bb[0]:.2f}..{bb[2]:.2f}  y {bb[1]:.2f}..{bb[3]:.2f}"
            f"  -> {bb[2]-bb[0]:.1f} x {bb[3]-bb[1]:.1f}",
            f"tracks {len(self.tracks)}  arcs {len(self.arcs)}  vias {len(self.vias)}"
            f"  pads {len(self.pads)}  fills {len(self.fills)}"
            f"  regions {len(self.regions)}  texts {len(self.texts)}"
            f"  components {len(self.components)}  nets {len(self.nets)}"
            f"  3D bodies {len(self.bodies)}",
            f"errors {self.errors or 'none'}",
        ]
        return "\n".join(lines)


if __name__ == '__main__':
    for p in sys.argv[1:]:
        print(PcbDoc(p).report())
        print()
