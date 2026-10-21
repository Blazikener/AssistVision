# AssistVision camera glasses

A clip-on, photos-only camera for an ordinary spectacle frame. One button press
takes a 13-frame burst while the wearer turns their head across the plate; the
laptop downloads it and compares the served and cleared bursts. No load cell, so
the output is **% eaten**, not grams.

| Path | What |
|---|---|
| `cad/glasses_mount.py` | Parametric CadQuery source (edit `temple_t`/`temple_h` for your frame) |
| `cad/out/*.stl` | Print-ready parts; `*__assembly_pose.stl` and the STEP are the assembled layout |
| `render/render_glasses.py` | Blender studio renders and turntable frames |
| `tutorial/tutorial.html` → `AssistVision_glasses_build_guide.pdf` (built with Chrome headless) | Illustrated build guide |
| `../firmware/assistvision_glasses/` | XIAO ESP32S3 Sense firmware (`/status`, `/trigger`, `/capture`, `/frame?i=`, `/camera`) |
| `../../src/glasses_client.py` | Host client: `meal --id ... --phase served|cleared` |

Regenerate:

```bash
python hardware/glasses/cad/glasses_mount.py            # needs cadquery (numpy<2)
blender -b -P hardware/glasses/render/render_glasses.py -- --mode hero --out hero.png
google-chrome --headless --print-to-pdf=guide.pdf hardware/glasses/tutorial/tutorial.html
```

Status: firmware compiles (ESP32 Arduino core 3.3.12, `esp32:esp32:XIAO_ESP32S3:PSRAM=opi`);
CAD solids are valid; host client passes 4/4 tests against a fake device. Nothing
has been flashed or worn yet: board dimensions come from the Seeed wiki and the
temple-arm size (3.5 x 8 mm) is an assumption to check against your frame.
