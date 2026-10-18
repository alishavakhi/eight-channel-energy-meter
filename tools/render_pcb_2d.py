#!/usr/bin/env python3
"""Render board artwork (top / bottom) from an Altium .PcbDoc.

Only geometry that is actually in the file is drawn: board outline (Board
Regions), copper tracks/arcs/fills/regions, pads, vias, drills and the overlay
(silkscreen) layer with its text.  Nothing is embellished.

    python3 render_pcb_2d.py board.PcbDoc out_dir --side top --dpi 900
"""
import argparse, math, os, sys
from PIL import Image, ImageDraw, ImageFont
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from altium_pcb import PcbDoc, SCALE, LAYERS

COPPER_LAYERS_TOP = ('Top Layer',)
COPPER_LAYERS_BOT = ('Bottom Layer',)
SILK_TOP = 'Top Overlay'
SILK_BOT = 'Bottom Overlay'

PALETTE = dict(
    board=(16, 58, 36),          # solder mask over bare FR4
    board_edge=(96, 208, 140),
    cu_top=(196, 74, 52),        # top copper
    cu_bot=(46, 104, 190),       # bottom copper
    pad=(214, 176, 62),
    pad_bot=(150, 176, 220),
    via=(198, 162, 58),
    drill=(10, 11, 13),
    silk=(236, 240, 244),
    silk_bot=(206, 214, 224),
    bg=(11, 13, 16),
)


def find_font(size):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, max(4, int(size)))
    return ImageFont.load_default()


class View:
    """Maps board millimetres to image pixels for one side."""

    def __init__(self, outline, px_per_mm, margin_mm=2.0, flip=False):
        xs = [p[0] for p in outline]; ys = [p[1] for p in outline]
        self.minx, self.maxx = min(xs), max(xs)
        self.miny, self.maxy = min(ys), max(ys)
        self.s = px_per_mm
        self.m = margin_mm
        self.flip = flip
        self.w = int(round((self.maxx - self.minx + 2 * margin_mm) * px_per_mm))
        self.h = int(round((self.maxy - self.miny + 2 * margin_mm) * px_per_mm))

    def __call__(self, x, y):
        px = (x - self.minx + self.m) * self.s
        py = (self.maxy - y + self.m) * self.s
        if self.flip:
            px = self.w - px
        return (px, py)

    def poly(self, pts):
        return [self(x, y) for (x, y) in pts]


def draw_side(doc, side='top', px_per_mm=12.0, bg=PALETTE['bg'],
              outline=None, margin_mm=2.0, with_silk=True, with_bg=True):
    outline = outline or doc.board_outline
    flip = (side == 'bottom')
    v = View(outline, px_per_mm, margin_mm, flip=flip)
    img = Image.new('RGBA', (v.w, v.h), bg + (255,) if with_bg else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cu = 'Top Layer' if side == 'top' else 'Bottom Layer'
    ov = SILK_TOP if side == 'top' else SILK_BOT
    col_cu = PALETTE['cu_top'] if side == 'top' else PALETTE['cu_bot']
    col_pad = PALETTE['pad'] if side == 'top' else PALETTE['pad_bot']
    col_silk = PALETTE['silk'] if side == 'top' else PALETTE['silk_bot']

    # --- board substrate
    d.polygon(v.poly(outline), fill=PALETTE['board'])

    # --- copper pour / regions on this copper layer
    for r in doc.regions:
        if r['layer'] != cu or len(r['pts']) < 3:
            continue
        d.polygon(v.poly(r['pts']), fill=col_cu)
        for hole in r['holes']:
            if len(hole) >= 3:
                d.polygon(v.poly(hole), fill=PALETTE['board'])

    # --- fills (rectangular copper)
    for f in doc.fills:
        if f['layer'] != cu:
            continue
        p = [v(f['x1'], f['y1']), v(f['x2'], f['y1']), v(f['x2'], f['y2']), v(f['x1'], f['y2'])]
        d.polygon(p, fill=col_cu)

    # --- tracks
    for t in doc.tracks:
        if t['layer'] != cu:
            continue
        w = max(1, int(round(t['w'] * v.s)))
        a, b = v(t['x1'], t['y1']), v(t['x2'], t['y2'])
        d.line([a, b], fill=col_cu, width=w)
        for (px, py) in (a, b):
            d.ellipse([px - w / 2, py - w / 2, px + w / 2, py + w / 2], fill=col_cu)

    # --- arcs
    for a_ in doc.arcs:
        if a_['layer'] != cu:
            continue
        w = max(1, int(round(a_['w'] * v.s)))
        sa, ea = a_['sa'], a_['ea']
        if ea < sa:
            ea += 360.0
        steps = max(6, int(abs(ea - sa) / 5))
        pts = []
        for i in range(steps + 1):
            th = math.radians(sa + (ea - sa) * i / steps)
            pts.append(v(a_['cx'] + a_['r'] * math.cos(th),
                         a_['cy'] + a_['r'] * math.sin(th)))
        d.line(pts, fill=col_cu, width=w, joint='curve')

    # --- pads
    for p in doc.pads:
        lid = p['layer_id']
        on = lid in (1, 74) if side == 'top' else lid in (32, 74)
        if not on:
            continue
        cx, cy = v(p['x'], p['y'])
        w = max(1.0, p['w'] * v.s); h = max(1.0, p['h'] * v.s)
        box = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
        shape = p['shape']
        if shape == 1:                       # round
            d.ellipse(box, fill=col_pad)
        elif shape == 3:                     # octagonal
            k = 0.29
            pts = [(cx - w / 2, cy - h * k), (cx - w * k, cy - h / 2),
                   (cx + w * k, cy - h / 2), (cx + w / 2, cy - h * k),
                   (cx + w / 2, cy + h * k), (cx + w * k, cy + h / 2),
                   (cx - w * k, cy + h / 2), (cx - w / 2, cy + h * k)]
            d.polygon(pts, fill=col_pad)
        else:                                # rectangular
            d.rectangle(box, fill=col_pad)
        if p['drill'] > 0:
            dr = max(1.0, p['drill'] * v.s)
            d.ellipse([cx - dr / 2, cy - dr / 2, cx + dr / 2, cy + dr / 2],
                      fill=PALETTE['drill'])

    # --- vias
    for vi in doc.vias:
        cx, cy = v(vi['x'], vi['y'])
        r = max(1.0, vi['dia'] * v.s / 2)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=PALETTE['via'])
        rr = max(0.8, vi['drill'] * v.s / 2)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=PALETTE['drill'])

    # --- silkscreen lines + text
    if with_silk:
        for t in doc.tracks:
            if t['layer'] != ov:
                continue
            w = max(1, int(round(t['w'] * v.s)))
            d.line([v(t['x1'], t['y1']), v(t['x2'], t['y2'])], fill=col_silk, width=w)
        for a_ in doc.arcs:
            if a_['layer'] != ov:
                continue
            w = max(1, int(round(a_['w'] * v.s)))
            sa, ea = a_['sa'], a_['ea']
            if ea < sa:
                ea += 360.0
            steps = max(6, int(abs(ea - sa) / 6))
            pts = [v(a_['cx'] + a_['r'] * math.cos(math.radians(sa + (ea - sa) * i / steps)),
                     a_['cy'] + a_['r'] * math.sin(math.radians(sa + (ea - sa) * i / steps)))
                   for i in range(steps + 1)]
            d.line(pts, fill=col_silk, width=w, joint='curve')
        for tx in doc.texts:
            if tx['layer'] != ov or not tx['text'].strip():
                continue
            hpx = max(3, int(round(tx['h'] * v.s)))
            font = find_font(hpx * 1.15)
            txt = tx['text']
            tw = d.textlength(txt, font=font)
            pad = int(hpx * 0.6) + 4
            tile = Image.new('RGBA', (int(tw) + pad, hpx + pad), (0, 0, 0, 0))
            td = ImageDraw.Draw(tile)
            td.text((pad // 2, pad // 2), txt, font=font, fill=col_silk)
            ang = tx['rot'] % 360
            if flip:
                ang = (-ang) % 360
            if abs(ang) > 0.5:
                tile = tile.rotate(ang, expand=True, resample=Image.BICUBIC)
            cx, cy = v(tx['x'], tx['y'])
            img.alpha_composite(tile, (int(cx - tile.width / 2), int(cy - tile.height / 2)))

    # --- board edge last, so nothing overdraws it
    d.line(v.poly(outline) + [v.poly(outline)[0]], fill=PALETTE['board_edge'],
           width=max(2, int(px_per_mm * 0.16)))
    return img, v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pcbdoc')
    ap.add_argument('out')
    ap.add_argument('--ppm', type=float, default=12.0, help='pixels per mm')
    ap.add_argument('--margin', type=float, default=2.0)
    ap.add_argument('--transparent', action='store_true')
    a = ap.parse_args()
    doc = PcbDoc(a.pcbdoc)
    os.makedirs(a.out, exist_ok=True)
    base = os.path.splitext(os.path.basename(a.pcbdoc))[0]
    for side in ('top', 'bottom'):
        img, v = draw_side(doc, side=side, px_per_mm=a.ppm, margin_mm=a.margin,
                           with_bg=not a.transparent)
        p = os.path.join(a.out, f"{base}-{side}.png")
        img.save(p)
        print(p, img.size)


if __name__ == '__main__':
    main()
