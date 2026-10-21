#!/usr/bin/env bash
# Parallel-safe renderer: run several copies; each claims a scene with mkdir.
B=${BLENDER:-blender}
cd "$(dirname "$0")/../.."
for d in data/synth_glasses/*/; do
  d=${d%/}; [ -f "$d/gt.json" ] && continue
  mkdir "$d/.lock" 2>/dev/null || continue
  "$B" -b -P experiments/synth/render_scene.py -- --spec "$d/spec.json" --out "$d" > "$d/render.log" 2>&1 && echo "rendered $d"
done
