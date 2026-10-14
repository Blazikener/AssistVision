"""
Monocular depth models behind one interface.

Every model returns depth-or-disparity at the input resolution plus a flag
saying which it is, so the evaluation code never has to know model internals.

  kind = 'metric'    output is depth in metres
  kind = 'relative'  output is affine-invariant inverse depth (MiDaS family)
"""

import time

import numpy as np
import torch
from PIL import Image

MODELS = {
    # name: (hf repo, kind, params (M), training domain)
    "MiDaS-DPT-Hybrid": ("Intel/dpt-hybrid-midas", "relative", 123, "mixed (MIX 6)"),
    "MiDaS-DPT-Large": ("Intel/dpt-large", "relative", 342, "mixed (MIX 6)"),
    "DA-V1-S": ("LiheYoung/depth-anything-small-hf", "relative", 25, "62M unlabelled + 1.5M labelled"),
    "DA-V2-S": ("depth-anything/Depth-Anything-V2-Small-hf", "relative", 25, "synthetic + 62M pseudo-labelled"),
    "DA-V2-B": ("depth-anything/Depth-Anything-V2-Base-hf", "relative", 97, "synthetic + 62M pseudo-labelled"),
    "DA-V2-L": ("depth-anything/Depth-Anything-V2-Large-hf", "relative", 335, "synthetic + 62M pseudo-labelled"),
    "ZoeDepth-NYU": ("Intel/zoedepth-nyu", "metric", 345, "NYUv2 indoor"),
    "ZoeDepth-NYU-KITTI": ("Intel/zoedepth-nyu-kitti", "metric", 345, "NYUv2 + KITTI"),
    "DA-V2-Metric-Indoor-S": ("depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf", "metric", 25, "Hypersim (indoor)"),
    "DA-V2-Metric-Indoor-B": ("depth-anything/Depth-Anything-V2-Metric-Indoor-Base-hf", "metric", 97, "Hypersim (indoor)"),
    "DA-V2-Metric-Indoor-L": ("depth-anything/Depth-Anything-V2-Metric-Indoor-Large-hf", "metric", 335, "Hypersim (indoor)"),
    "DepthPro": ("apple/DepthPro-hf", "metric", 952, "mixed, metric + focal"),
}


class MonoDepth:
    def __init__(self, name, threads=None):
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        if threads:
            torch.set_num_threads(threads)
        self.name = name
        self.repo, self.kind, self.params_m, self.domain = MODELS[name]
        self.processor = AutoImageProcessor.from_pretrained(self.repo)
        self.model = AutoModelForDepthEstimation.from_pretrained(self.repo).eval()

    @torch.inference_mode()
    def __call__(self, rgb, fx=None):
        """rgb: HxWx3 uint8 RGB. fx: known focal (px), used by DepthPro if given.

        Returns (map HxW float32, seconds)."""
        h, w = rgb.shape[:2]
        img = Image.fromarray(rgb)
        inputs = self.processor(images=img, return_tensors="pt")
        t0 = time.perf_counter()
        out = self.model(**inputs)
        dt = time.perf_counter() - t0
        kwargs = {"target_sizes": [(h, w)]}
        if self.name == "DepthPro" and fx is not None:
            # DepthPro predicts its own field of view; with a calibrated camera
            # we pass the true focal so depth is not rescaled by a bad FOV guess.
            post = self.processor.post_process_depth_estimation(out, target_sizes=[(h, w)])
            pred = post[0]["predicted_depth"].float().numpy()
            fov_fx = float(post[0]["focal_length"]) if "focal_length" in post[0] else None
            if fov_fx:
                pred = pred * (fx / fov_fx)
            return pred.astype(np.float32), dt
        if "Zoe" in self.name:
            kwargs["source_sizes"] = [(h, w)]
        post = self.processor.post_process_depth_estimation(out, **kwargs)
        pred = post[0]["predicted_depth"].float().numpy()
        return pred.astype(np.float32), dt
