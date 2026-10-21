#!/usr/bin/env bash
# Reconstruct E6 scenes as their renders finish.
cd "$(dirname "$0")/../.."
while :; do
  .venv/bin/python experiments/synth/run_suite.py --exp glasses --scenes data/synth_glasses
  n=$(wc -l < results/synth/glasses.jsonl 2>/dev/null || echo 0)
  [ "$n" -ge 24 ] && break
  sleep 120
done
