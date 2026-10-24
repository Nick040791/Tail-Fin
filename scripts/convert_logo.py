#!/usr/bin/env python3
"""
Tail-Fin Logo Converter Script
Generates transparent PNG, original PNG, multi-resolution ICO, and scalable vector SVG files.
"""

import os
import sys
import re
import base64
import subprocess
import numpy as np
from PIL import Image

def convert_logo(src_img: str, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    print(f"Loading {src_img}...")
    
    im = Image.open(src_img).convert("RGB")
    arr = np.array(im)
    h, w, _ = arr.shape
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    
    # Antialiased circular mask
    Y, X = np.ogrid[:h, :w]
    dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
    radius = w / 2.0
    alpha = np.clip((radius + 0.2 - dist) / 1.4, 0.0, 1.0) * 255.0
    alpha = np.round(alpha).astype(np.uint8)
    
    rgba = np.dstack([arr, alpha])
    im_transparent = Image.fromarray(rgba, "RGBA")
    
    # 1. logo.png (transparent)
    png_path = os.path.join(output_dir, "logo.png")
    im_transparent.save(png_path, "PNG")
    print(f"  ✓ Saved {png_path}")
    
    # 2. logo-square.png (original framing)
    sq_png_path = os.path.join(output_dir, "logo-square.png")
    im.save(sq_png_path, "PNG")
    print(f"  ✓ Saved {sq_png_path}")
    
    # 3. logo.ico (multi-size favicon / Windows icon)
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_path = os.path.join(output_dir, "logo.ico")
    im_transparent.save(ico_path, format="ICO", sizes=ico_sizes)
    print(f"  ✓ Saved {ico_path}")
    
    # 4. logo.svg (vector curves via vtracer if available)
    vtracer_bin = os.path.expanduser("~/.cargo/bin/vtracer")
    svg_path = os.path.join(output_dir, "logo.svg")
    if os.path.exists(vtracer_bin):
        tmp_vtracer = "/tmp/vtracer_out.svg"
        subprocess.run([
            vtracer_bin,
            "--input", png_path,
            "--output", tmp_vtracer,
            "--colormode", "color",
            "--mode", "spline",
            "--filter_speckle", "4"
        ], check=True)
        with open(tmp_vtracer, "r", encoding="utf-8") as f:
            svg_data = f.read()
        if 'viewBox=' not in svg_data:
            svg_data = re.sub(
                rf'<svg([^>]*)width="{w}"\s+height="{h}"([^>]*)>',
                rf'<svg\1viewBox="0 0 {w} {h}" width="{w}" height="{h}"\2>',
                svg_data
            )
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg_data)
        print(f"  ✓ Saved {svg_path} (vector paths)")
    
    # 5. logo-hd.svg (lossless embedded SVG with vector clipping)
    with open(png_path, "rb") as f:
        b64_png = base64.b64encode(f.read()).decode("ascii")
    hd_svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
  <defs>
    <clipPath id="circle-clip">
      <circle cx="{cx + 0.5}" cy="{cy + 0.5}" r="{radius}"/>
    </clipPath>
  </defs>
  <image clip-path="url(#circle-clip)" width="{w}" height="{h}" xlink:href="data:image/png;base64,{b64_png}"/>
</svg>
'''
    hd_svg_path = os.path.join(output_dir, "logo-hd.svg")
    with open(hd_svg_path, "w", encoding="utf-8") as f:
        f.write(hd_svg)
    print(f"  ✓ Saved {hd_svg_path} (lossless vector-clip SVG)")

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "/home/mrnicholas/Downloads/Integrated-Apps/logo.jpeg"
    out = sys.argv[2] if len(sys.argv) > 2 else "/home/mrnicholas/Dev/Tail-Fin/design/icon"
    convert_logo(src, out)
