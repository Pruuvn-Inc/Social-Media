#!/usr/bin/env python3
"""Generate Pruuvn LinkedIn card images from posts.yml.

Reads posts.yml, renders each post's card using the matching template,
and writes PNGs to cards/.

Usage:
    python scripts/generate_cards.py [--only 01]
"""

import argparse
import pathlib
import sys
import yaml
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

ROOT     = pathlib.Path(__file__).resolve().parent.parent
FONTS    = ROOT / "fonts"
TPLS     = ROOT / "templates"
CARDS    = ROOT / "cards"
ARCHIVO  = str(FONTS / "Archivo.ttf")
MONO_SB  = str(FONTS / "PlexMono-SemiBold.ttf")
WHITE    = (255, 255, 255)

CARDS.mkdir(exist_ok=True)

# ── typography helpers ────────────────────────────────────────────────────────

def bold(s, w=750, wd=100):
    f = ImageFont.truetype(ARCHIVO, s); f.set_variation_by_axes([w, wd]); return f

def semib(s, w=600, wd=100):
    f = ImageFont.truetype(ARCHIVO, s); f.set_variation_by_axes([w, wd]); return f

def mono(s):
    return ImageFont.truetype(MONO_SB, s)

def wrap(d, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= max_w: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines

# ── background patching ───────────────────────────────────────────────────────

def blend_fill(im, box):
    x0, y0, x1, y1 = box
    h = im.size[1]
    top = np.array([im.getpixel((x, max(y0-20,0))) for x in range(x0,x1)], float)
    bot = np.array([im.getpixel((x, min(y1+30,h-5))) for x in range(x0,x1)], float)
    hh = y1-y0
    p = Image.new("RGB",(x1-x0,hh)); px=p.load()
    for yy in range(hh):
        t = yy/max(hh-1,1)
        row=(top*(1-t)+bot*t).astype(int)
        for i in range(x1-x0): px[i,yy]=tuple(row[i])
    im.paste(p.filter(ImageFilter.GaussianBlur(1.2)),(x0,y0))

def extrapolate_fill(im, box, ref_a, ref_b):
    x0,y0,x1,y1 = box
    a = np.array([im.getpixel((x,ref_a)) for x in range(x0,x1)],float)
    b = np.array([im.getpixel((x,ref_b)) for x in range(x0,x1)],float)
    slope = (b-a)/float(ref_b-ref_a)
    p = Image.new("RGB",(x1-x0,y1-y0)); px=p.load()
    for yy in range(y1-y0):
        row=np.clip(b+slope*((y0+yy)-ref_b),0,255).astype(int)
        for i in range(x1-x0): px[i,yy]=tuple(row[i])
    p = p.filter(ImageFilter.GaussianBlur(2.0))
    fade=60; mask=Image.new("L",(x1-x0,y1-y0),255); mk=mask.load()
    for yy in range(min(fade,y1-y0)):
        v=int(255*yy/fade)
        for i in range(x1-x0): mk[i,yy]=v
    im.paste(p,(x0,y0),mask)

def restripe(im, rgb):
    ImageDraw.Draw(im).rectangle([0,0,9,im.size[1]],fill=rgb)

def pill(d,x,y,text,fg,bg,font,px_=20,py=12,r=18):
    w=d.textlength(text,font=font)
    d.rounded_rectangle([x,y,x+w+px_*2,y+font.size+py*2],radius=r,fill=bg)
    d.text((x+px_,y+py-2),text,font=font,fill=fg)

# ── standard layout ───────────────────────────────────────────────────────────

def apply_statement(im, headline, sub, accent, tag, tag_fg, tag_bg, tags,
                    patch_boxes=None, extra_fn=None):
    if patch_boxes:
        for b in patch_boxes:
            blend_fill(im, b)
    blend_fill(im, (0,355,1200,590))
    if extra_fn:
        extra_fn(im)
    blend_fill(im, (0,1095,1200,1200))
    d = ImageDraw.Draw(im)
    hf = bold(42); y=385
    for ln in wrap(d,headline,hf,1050):
        d.text((64,y),ln,font=hf,fill=WHITE); y+=54
    y+=14
    d.line([(64,y),(128,y)],fill=accent,width=4); y+=26
    sf = semib(23)
    for ln in wrap(d,sub,sf,1080):
        d.text((64,y),ln,font=sf,fill=accent); y+=32
    d2=ImageDraw.Draw(im)
    pill(d2,64,1108,tag,tag_fg,tag_bg,bold(19))
    d2.text((64,1163),tags,font=semib(20),fill=(140,155,180))

# ── card catalogue (maps template field to render logic) ──────────────────────

CATALOGUE = {
    "nts-intro": {
        "template": "Product_Feature_Template.png",
        "accent":   (247,197,106),
        "tag":      "THE STANDARD",
        "tag_fg":   (30,20,5),
        "tag_bg":   (247,197,106),
        "tags":     "#NTS #Pruuvn #TrustInfrastructure",
        "patch_extra": lambda im: (
            blend_fill(im,(0,770,1200,985)),
        ),
    },
    "human-network": {
        "template": "AI_Agents_Template_01_Instagram.png",
        "accent":   (108,132,255),
        "tag":      "TRUST NETWORK",
        "tag_fg":   (255,255,255),
        "tag_bg":   (74,95,232),
        "tags":     "#NTS #Pruuvn #TrustInfrastructure",
        "stripe":   (74,95,232),
    },
    "ai-agents": {
        "template": "AI_Agents_Template_01_Instagram.png",
        "accent":   (56,208,235),
        "tag":      "AI AGENTS",
        "tag_fg":   (5,30,35),
        "tag_bg":   (56,208,235),
        "tags":     "#NTSforAI #Pruuvn #TrustInfrastructure",
    },
    "enterprise": {
        "template": "EnterpriseTech_Template.png",
        "accent":   (236,110,190),
        "tag":      "ENTERPRISE / TECH",
        "tag_fg":   (255,255,255),
        "tag_bg":   (196,60,150),
        "tags":     "#NTS #Pruuvn #TrustInfrastructure",
        "stripe":   (236,110,190),
    },
    "fleet": {
        "template": "Fleet___Logistics_Template.png",
        "accent":   (245,140,60),
        "tag":      "FLEET & LOGISTICS",
        "tag_fg":   (30,15,0),
        "tag_bg":   (245,140,60),
        "tags":     "#NTS #Pruuvn #TrustInfrastructure",
        "stripe":   (245,140,60),
    },
    "thought-leadership": {
        "template": "Thought_Leadership_Template.png",
        "accent":   (150,130,255),
        "tag":      "THOUGHT LEADERSHIP",
        "tag_fg":   (255,255,255),
        "tag_bg":   (108,86,235),
        "tags":     "#NTS #Pruuvn #TrustInfrastructure",
        "patch_extra": lambda im: extrapolate_fill(im,(0,1040,1200,1200),700,790),
    },
    "nts-ai-feature": {
        "template": "NTS_for_AI_Agents_Feature_Template.png",
        "accent":   (56,208,235),
        "tag":      "NTS FOR AI AGENTS",
        "tag_fg":   (5,30,35),
        "tag_bg":   (56,208,235),
        "tags":     "#NTSforAI #Pruuvn #TrustInfrastructure",
        "patch_boxes": [(0,170,1200,250),(0,915,460,990)],
    },
    "cta": {
        "template": "Call_to_Action_Template.png",
        "accent":   (247,216,90),
        "tag":      "GET CREDENTIALED",
        "tag_fg":   (25,22,5),
        "tag_bg":   (247,216,90),
        "tags":     "#NTS #Pruuvn #TrustInfrastructure",
        "patch_boxes": [(0,160,1200,260)],
    },
    "trust-center": {
        "template": "Product_Feature_Template.png",
        "accent":   (110,200,255),
        "tag":      "TRUST CENTER",
        "tag_fg":   (8,26,45),
        "tag_bg":   (110,200,255),
        "tags":     "#NTS #Pruuvn #TrustInfrastructure",
        "patch_boxes": [(0,770,1200,985)],
    },
    "why-now": {
        "template": "Fleet___Logistics_Template.png",
        "accent":   (247,197,106),
        "tag":      "WHY NOW",
        "tag_fg":   (30,20,5),
        "tag_bg":   (247,197,106),
        "tags":     "#NTS #Pruuvn #TrustInfrastructure",
        "stripe":   (247,197,106),
    },
}


def render(post_id, card_type, headline, subline):
    spec = CATALOGUE.get(card_type)
    if not spec:
        print(f"[{post_id}] unknown card_type {card_type!r}, skipping")
        return None

    im = Image.open(TPLS / spec["template"]).convert("RGB")

    if spec.get("stripe"):
        restripe(im, spec["stripe"])

    extra_fn = spec.get("patch_extra")
    patch_boxes = spec.get("patch_boxes", [])

    apply_statement(
        im,
        headline, subline,
        spec["accent"],
        spec["tag"], spec["tag_fg"], spec["tag_bg"],
        spec["tags"],
        patch_boxes=patch_boxes,
        extra_fn=extra_fn,
    )

    out = CARDS / f"pruuvn-linkedin-{post_id}-{card_type}.png"
    im.save(out)
    print(f"[{post_id}] wrote {out.name}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    data = yaml.safe_load((ROOT / "posts.yml").read_text())
    posts = data["posts"]
    if args.only:
        posts = [p for p in posts if str(p["id"]) == args.only]
        if not posts:
            sys.exit(f"No post id {args.only!r}")

    for p in posts:
        render(str(p["id"]).zfill(2), p["card_type"], p["headline"], p["subline"])


if __name__ == "__main__":
    main()
