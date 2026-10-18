# Eight-Channel Energy Meter

A two-board electrical energy meter: a metering board that conditions eight
clamp-on current-transformer channels and one PCB current transformer into an
ADE7753 energy-measurement IC, and a controller board built around an ESP32 with
USB-C and RS-485.

Both boards are complete Altium Designer projects and are published here with 3D
renders generated from the design data.

![Metering board, top view](renders/em-metering-top.png)

---

## Overview

| Board | Size | Layers | Parts | Nets | Role |
|---|---|---|---|---|---|
| **Metering board** (`PCB_Down`) | 152 × 106 mm | 2 | 218 | 149 | Current/voltage sensing, metering, isolated supplies |
| **Controller board** (`PCB Up`) | 154.7 × 83.8 mm | 2 | 81 | 70 | ESP32 host, USB-C, RS-485, user I/O |

The two boards are joined by a 2×10 (2.54 mm) IDC ribbon cable
(`J1` metering side, `J1` controller side), so the mains-referenced metering
section can be kept physically separate from the low-voltage controller.

## Engineering purpose

The design measures eight independent load currents and one supply voltage and
turns them into energy readings:

* **Eight clamp-CT channels.** Eight ZMCT103C PCB-mounted current transformers,
  each with its own LM358 signal-conditioning stage (eight LM358 devices are
  placed — one dual op-amp per channel), feeding a 74HC4051 8:1 analog
  multiplexer.
* **A metering IC, not a microcontroller ADC.** The ADE7753 performs the
  active/reactive energy accumulation, RMS and frequency measurement in hardware;
  the multiplexer scans the eight current channels into its current input while
  the voltage channel measures the supply.
* **Isolation.** An AMC1100 isolated amplifier, a B0505S-1WR2 isolated DC/DC and
  three PC817 opto-couplers keep the mains-referenced side away from the logic side.
* **Power.** An HLK-PM01 AC/DC module provides the 5 V rail; an MC34063A switching
  regulator with its inductor generates the auxiliary rail; a P-channel MOSFET
  (AO3401A) provides reverse-polarity/load switching.
* **Field connection.** Two 13-way terminal blocks bring in the CT leads and the
  voltage sense connection.

The controller board adds the network-facing half: an ESP32-WROOM-32D, a CH340
USB-UART bridge on a USB-C receptacle, an RS-485 transceiver (MAX487), a 74HC595
output expander, a 74HC4051 input multiplexer, five keys, five LEDs and a 4-pin
header.

## Circuit description

The archive contains no schematic PDF export for either board, so the following
description is reconstructed from the placed parts and the net/part counts in the
design files. Where a detail is an inference it is marked as such.

**Metering board (`PCB_Down`)**

| Section | Parts | Notes |
|---|---|---|
| Current sensing | 8 × ZMCT103C clamp CTs (`T2`–`T13`), 1 × CT1005A PCB CT (`T4`) | One clamp channel per load; the CT1005A is a PCB-mount 5 A/5 mA part |
| Signal conditioning | 8 × LM358D, 100 R / 1 K / 10 K / 100 K resistor network, 33 nF / 100 nF / 0.1 nF capacitors | One dual op-amp per channel — burden, gain and anti-alias filtering *(per-channel topology is inferred from part counts; no schematic export exists)* |
| Channel selection | 74HC4051D (`U`), 8:1 analog multiplexer | Scans the eight conditioned channels into the metering IC |
| Metering | ADE7753 (`U3`, SSOP-20) | Active/reactive energy, RMS, frequency; one current + one voltage channel |
| Voltage sense / isolation | AMC1100DWV (`U6`, SOIC-8 with thermal pad) | Isolated amplifier on the voltage-sense path *(path assignment inferred)* |
| Isolated supply | B0505S-1WR2 (`PS1`), 5 V→5 V 1 W isolated DC/DC | Supplies the isolated measurement side |
| Auxiliary rail | MC34063AD + inductor | Switching regulator for the auxiliary rail |
| Mains input | HLK-PM01 AC/DC module | Off-line 5 V module |
| Isolation / status | 3 × PC817, 4 × C945, AO3401A, 1N4007, 1N4148, LED | Opto-coupled signalling to the controller side |
| Connectors | 2 × 13-way terminal blocks (`P1`, `P2`), 2×10 IDC (`J1`) | CT/voltage field wiring, ribbon to the controller board |

**Controller board (`PCB Up`)**

| Section | Parts | Notes |
|---|---|---|
| Host | ESP32-WROOM-32D (`U1`) | Wi-Fi/BT, SPI/UART/I²C master |
| USB | CH340 USB-UART + USB-C receptacle (`J1`, GCT USB1040) | Console and firmware download |
| Field bus | MAX487CPA RS-485 transceiver | Half-duplex bus, DIP/SOIC-8 |
| I/O expansion | 74HC595D shift register, 74HC4051D multiplexer, 74HC04 inverter | Indicator/relay drive and key/input scanning |
| User interface | 5 × keys (`KEY1`…`KEY_FLASH`), 5 × LEDs, 2 × SS8050, 2 × 5 V zener | Front-panel operation |
| Interconnect | 2×10 IDC (`J1`), 4-pin header | Ribbon to the metering board |

## Schematic and PCB summary

* **Metering board**: 152 × 106 mm outline with a stepped, ribbed edge profile
  (the board slides into enclosure slots), two copper layers, 4344 routed track
  segments, 136 vias, 1560 pads, 218 components, 149 nets, four 3 mm mounting
  screws. Components are placed on both sides — the metering IC and its
  conditioning network on the bottom, the CTs and terminals on the top.
* **Controller board**: 154.7 × 83.8 mm, two copper layers, 3300 track segments,
  147 vias, 547 pads, 81 components, 70 nets.
* Both are **two-layer, through-hole-plated** designs with no inner layers and no
  controlled-impedance stack-up.

Top and bottom artwork, generated from the `.PcbDoc` files in this repository:

| Metering board, top | Metering board, bottom |
|---|---|
| ![metering top](renders/em-metering-top.png) | ![metering bottom](renders/em-metering-bottom.png) |
| **Controller board, top** | **Controller board, bottom** |
| ![controller top](renders/em-controller-top.png) | ![controller bottom](renders/em-controller-bottom.png) |

## Design tools

* **Altium Designer** — `.PrjPcb` / `.SchDoc` / `.PcbDoc`. The documents use the
  `PCB 6.0 Binary File` container; the project logs (Altium ECO files, not
  republished) date the layout work to 21–30 June 2021.
* **Python 3 + Pillow + OpenCASCADE (OCP)** — the `tools/` in this repository read
  the binary PcbDoc directly and generate every image on this page.

## Repository contents

```
hardware/
  metering-board/    PCB_Down.PrjPcb, PCB_Down.SchDoc, PCB_Down.PcbDoc
  controller-board/  PCB Up.PrjPcb, pcb up.SchDoc, PCB Up.PcbDoc
renders/             top/bottom artwork and three 3D views per board
tools/               altium_pcb.py     - PcbDoc reader (OLE2 + record layout)
                     render_pcb_2d.py  - artwork renderer
                     render_pcb_3d.py  - STEP-body 3D renderer
```

## How to open / inspect the design

**Altium Designer.** Open `hardware/metering-board/PCB_Down.PrjPcb` and
`hardware/controller-board/PCB Up.PrjPcb`. The schematic sheets are the only
record of component values — the PCB documents store footprints and placement,
not values.

**Without Altium.** Regenerate any image on Linux:

```bash
pip install olefile pillow numpy cadquery-ocp
python3 tools/render_pcb_2d.py hardware/metering-board/PCB_Down.PcbDoc out/ --ppm 14
python3 tools/render_pcb_3d.py hardware/metering-board/PCB_Down.PcbDoc out/3d.png --az 34 --el 30
```

Structural summary of a board without rendering:

```bash
python3 tools/altium_pcb.py hardware/metering-board/PCB_Down.PcbDoc
```

## Bill of materials (active devices)

Read from the placed parts and the project's component libraries (`.SchDoc`);
values for the passives are in the schematic, not in the PCB.

| Board | Ref | Part | Package | Function |
|---|---|---|---|---|
| Metering | U3 | ADE7753 | SSOP-20 | Energy measurement IC |
| Metering | U6 | AMC1100DWV | SOIC-8 + thermal pad | Isolated amplifier |
| Metering | PS1 | B0505S-1WR2 | module | Isolated 5 V→5 V 1 W DC/DC |
| Metering | — | LM358D ×8 | SOIC-8 | Per-channel signal conditioning |
| Metering | — | 74HC4051D | SOIC-16 | 8:1 analog multiplexer |
| Metering | — | MC34063AD | SOIC-8 | Switching regulator |
| Metering | — | HLK-PM01 | module | Off-line AC/DC 5 V |
| Metering | T2–T13 | ZMCT103C ×8 | PCB CT | Clamp current transformers |
| Metering | T4 | CT1005A | PCB CT | 5 A / 5 mA current transformer |
| Metering | — | PC817 ×3, C945 ×4 | opto / SOT-23 | Isolated signalling, drivers |
| Controller | U1 | ESP32-WROOM-32D | module | Host MCU |
| Controller | — | CH340 | SOP-16 | USB-UART bridge |
| Controller | — | MAX487CPA | SOIC-8 | RS-485 transceiver |
| Controller | — | 74HC595D, 74HC4051D, 74HC04 | SOIC | I/O expansion |
| Controller | J1 | GCT USB1040 | USB-C | Programming/console connector |

## Limitations and missing pieces

* **No schematic export.** The archive has no PDF of either schematic sheet, and
  Altium cannot run on the machine this repository was prepared on. The `.SchDoc`
  sources are included, but a schematic image can only be produced in Altium. A
  500 × 351 preview bitmap is the only visual record of the sheet.
* **No firmware.** No ESP32 code, no calibration procedure and no communication
  protocol description exist in the archive.
* **No measurement data.** No accuracy figures, calibration records or test logs
  were found, so no accuracy class or error figure is claimed. (ADE7753-based
  designs can reach class-1 accuracy, but that is the silicon's capability, not a
  result of this design.)
* **Metering topology partly inferred.** Part counts and packages identify the
  silicon; the exact per-channel network (burden resistor values, filter corners)
  and the assignment of the AMC1100 to the voltage path are inferences from that
  evidence, not read from a schematic export.
* **Board outline matched to an off-the-shelf enclosure.** The metering board's
  stepped edge follows a BRT 80005-B1 extruded aluminium case; the enclosure
  drawing is third-party and is not published here.
* **Not manufactured/verified here.** Geometry, placement and net counts come from
  the design files as they were left; nothing was re-simulated or DRC-checked.

## Renders

| View | Controller board |
|---|---|
| 3/4 front | ![](renders/em-controller-3d-a.png) |
| 3/4 rear | ![](renders/em-controller-3d-b.png) |
| High angle | ![](renders/em-controller-3d-c.png) |

Component bodies are the STEP models embedded in the `.PcbDoc`; parts without an
embedded model are not drawn rather than substituted. The board surface shows the
copper, pad and silkscreen artwork from the same file. Colours are a rendering
choice, not the manufactured solder-mask colour.

**The metering board has no 3D views.** Of its 208 component bodies only 39 carry
an embedded STEP model, and the two 13-way terminal-block models are stored far
from their own origin, so they render floating off the board edge. Rather than
show a picture that misrepresents the assembly, this repository publishes the
exact 2D artwork for that board (top and bottom, above) and no 3D view of it.

## Authorship and credits

**Design:** Ali Shavakhi — circuit design, schematic capture, PCB layout and
project assembly for both boards, from his own project archive. The Altium ECO logs
in the original archive date the layout work to June 2021.

**Component libraries:** the symbols and footprints used in these designs come from
the shared Altium component libraries the project was built with. Each placed part
keeps its own library metadata, and those credits are left intact in the files:

* parts from the **ControTec** library, credited per component to
  *Abbas Basereh* and *Saeid Jorablo*;
* parts published by **PicPars** (`www.picpars.com`), credited to
  *Seyed Mohsen Ghasemian*;
* the remainder are stock Altium Limited library parts.

Those names identify the library authors, not the board designers; they appear as
`Designer` / `Publisher` parameters on individual components inside the `.PcbDoc`
and `.SchDoc` files. Nothing from those libraries is republished here as a separate
library.

The `tools/` scripts were written for this publication.

A third-party open-source energy-meter reference design (*YoMo*, C. Klemenjak et
al.) was stored next to this project in the same archive folder. It is **not** part
of this design and none of its files are republished here.

## Licence

MIT for the `tools/` source code — see [`LICENSE`](LICENSE). The hardware design
files are published for portfolio and reference use; see
[`LICENSE-SCOPE.md`](LICENSE-SCOPE.md) for what that covers.
