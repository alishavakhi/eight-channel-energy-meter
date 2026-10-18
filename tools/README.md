# tools/

Three small Python programs that read an Altium `.PcbDoc` directly, so the design
can be inspected and rendered on a machine that has no Altium Designer. They were
written for this publication.

| File | What it does |
|---|---|
| `altium_pcb.py` | Opens the OLE2 container, walks the binary record streams (tracks, arcs, vias, pads, fills, regions, texts, components, nets, 3D bodies, board region) and exposes them as millimetre geometry. `python3 altium_pcb.py board.PcbDoc` prints a structural summary. |
| `render_pcb_2d.py` | Draws the copper, pads, drills, silkscreen and outline of one side as a PNG. `--ppm` sets pixels per millimetre, `--transparent` drops the background. |
| `render_pcb_3d.py` | 3D view: the board outline extruded to 1.6 mm with the artwork as its surface texture, plus every component whose STEP model is embedded in the file. Orthographic camera, `--az`/`--el` for the angle. |

## Requirements

```bash
pip install olefile pillow numpy cadquery-ocp
```

`cadquery-ocp` (OpenCASCADE) is only needed by `render_pcb_3d.py` — it tessellates
the STEP models embedded in the PcbDoc. `libGL.so.1` must be present
(`apt install libgl1` on Debian/Ubuntu).

## Examples

```bash
python3 altium_pcb.py ../hardware/metering-board/PCB_Down.PcbDoc

python3 render_pcb_2d.py ../hardware/metering-board/PCB_Down.PcbDoc out/ --ppm 14
python3 render_pcb_3d.py ../hardware/metering-board/PCB_Down.PcbDoc out/3d.png \
        --az 34 --el 30 --width 2000
```

## How it works, and what it does not do

The record layouts implemented in `altium_pcb.py` follow the formal description
published with the KiCad Altium importer (`pcbnew/pcb_io/altium/altium_parser.ksy`,
GPL-3.0) and the field offsets used by the `altium2kicad` converter. Coordinates
are stored in the file as integers in 1/10000 mil; everything here is converted to
millimetres (`mm = raw × 2.54e-6`) and the Y axis is flipped so that the board is
drawn the way it is seen.

Limitations, all of which matter for judging the renders:

* **Only what is in the file is drawn.** Parts whose 3D model is not embedded in
  the PcbDoc are not drawn at all — they are never substituted with a box.
* **Component bodies are centred on their component origin.** The recorded
  `MODEL.2D` placements in these documents are unreliable (the relay models are
  stored ~46 mm from their footprint, the Pi Zero mezzanine model ~250 mm), so the
  body's bounding-box centre is placed on the component instead. For parts that
  are stored correctly this agrees with the file to about 1 mm.
* **Board thickness** is taken as 1.6 mm (the usual 2-layer FR4 value); the
  PcbDoc's stack-up record is not parsed.
* **Schematic files are not parsed.** `.SchDoc` is a different, much larger format;
  nothing here reads it.
* **Colours are a rendering choice**, not the manufactured solder-mask/silkscreen
  colours.
* The 2D renderer draws pads from the pad record's top-side size. Pads defined per
  layer (`top`/`mid`/`bottom` mode) fall back to the mid then bottom size.

These programs are read-only: they never write to the design file.
