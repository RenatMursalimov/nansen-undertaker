#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the 1280×640 GitHub social preview for Nansen Undertaker.

The file contains no user/wallet identifiers and doubles as the 0–3 second title card in the silent
demo. GitHub has no REST endpoint for setting a social preview; the generated PNG must be uploaded
once in Settings → General → Social preview.
"""

import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print('Pillow is required: pip install Pillow')
    raise SystemExit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# In the bot repo the generated public assets live under nansen/public/. In the exported repo
# this same script lives under tools/ and assets/ is already at repository root.
_PUBLIC_ROOT = (os.path.join(ROOT, 'nansen', 'public')
                if os.path.isdir(os.path.join(ROOT, 'nansen', 'public')) else ROOT)
OUT = os.path.join(_PUBLIC_ROOT, 'assets', 'social-preview.png')
W, H = 1280, 640


def font(size, bold=False):
    candidates = [
        os.path.join(ROOT, 'assets', 'fonts', 'Oswald.ttf'),
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def main(argv=None):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    im = Image.new('RGB', (W, H), '#070b12')
    d = ImageDraw.Draw(im)

    # Subtle grid: analytics without imitating Nansen brand assets.
    for x in range(0, W, 64):
        d.line((x, 0, x, H), fill='#0d1522', width=1)
    for y in range(0, H, 64):
        d.line((0, y, W, y), fill='#0d1522', width=1)

    # Accent rails.
    d.rectangle((0, 0, 18, H), fill='#21d4a7')
    d.rectangle((18, 0, 24, H), fill='#7b61ff')
    d.ellipse((1060, -160, 1420, 200), fill='#101d2f')
    d.ellipse((1105, -110, 1375, 160), outline='#21d4a7', width=4)

    d.text((78, 54), 'NANSEN UNDERTAKER', font=font(34, True), fill='#21d4a7')
    d.text((78, 117), 'A market says 78% YES.', font=font(64, True), fill='#f4f7fb')
    d.text((78, 197), 'But whose conviction is it?', font=font(64, True), fill='#f4f7fb')

    # Hero metric card; from sanitized live proof market 1130012.
    rounded(d, (78, 318, 752, 502), 28, '#101824', outline='#26374d', width=2)
    d.text((112, 345), '$500.4K', font=font(61, True), fill='#ffcc66')
    d.text((403, 355), '58%', font=font(50, True), fill='#ff6b81')
    d.text((112, 423), 'of $858.5K examined money', font=font(25), fill='#aebed2')
    d.text((403, 423), 'below 40% historical win rate', font=font(25), fill='#aebed2')

    # Composition motif: known / unexamined are visibly different, never silently merged.
    rounded(d, (790, 318, 1200, 502), 28, '#101824', outline='#26374d', width=2)
    d.text((824, 350), 'HOLDERS × HISTORY', font=font(27, True), fill='#f4f7fb')
    d.rectangle((824, 406, 1124, 432), fill='#1c2a3b')
    d.rectangle((824, 406, 1000, 432), fill='#ff6b81')
    d.text((824, 449), 'unknown is counted on neither side', font=font(19), fill='#8ea2ba')

    d.text((78, 555), 'Polymarket holder positions × lifetime wallet history',
           font=font(25), fill='#c8d5e5')
    d.text((890, 555), 'Powered by Nansen API', font=font(24, True), fill='#21d4a7')

    im.save(OUT, format='PNG', optimize=True)
    print('%s · %dx%d · %d bytes' % (OUT, W, H, os.path.getsize(OUT)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
