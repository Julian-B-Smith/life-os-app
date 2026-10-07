#!/usr/bin/env python3
"""Adapt Endless Chiptunes' site build for mindlathe.xyz/endless-chiptunes/.

    python3 deploy/sites/endless-chiptunes/adapt.py <endless-chiptunes>/dist/endless-chiptunes-site.html OUT.html

Input is the project's own site build (`python3 tools/build_av.py --site`): the
generator with the visualizer embedded as its screen, export already hidden
(window.EC_EXPORT=false). The site changes one thing (owner, 2026-10-07): no
requests to anyone else, the domain's rule since mind-lathe D31/D34. So the
Google Fonts links are removed from both documents (the generator page and the
visualizer's, embedded as text and opened in a srcdoc iframe, so it needs its own
@font-face rules) and the families ship inline as WOFF2 subsets (fonts/: Latin +
the symbols the page uses; Pixelify Sans trimmed to weights 400-600). All SIL
OFL 1.1, licences alongside.

Every edit must match exactly once, so a changed upstream fails loudly instead
of half-applying; the last check refuses any output that still names an outside
host. Lives here, like Endless Trance's, until the project's own --site build
inlines its fonts (it is under git; see its HANDOFF.md).
"""
import base64, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")


def face(family, file, weight="400"):
    data = base64.b64encode(open(os.path.join(FONTS, file), "rb").read()).decode()
    return (f'@font-face{{font-family:"{family}";src:url(data:font/woff2;base64,{data}) format("woff2");'
            f'font-weight:{weight};font-style:normal;font-display:swap}}')


def licence_comment(dirs):
    # OFL requires the copyright notice and the licence with every copy; the
    # notices differ per family, the licence text is the same, so it appears once.
    notices, text = [], None
    for d in dirs:
        lines = open(os.path.join(FONTS, f"OFL-{d}.txt"), encoding="utf-8").read().strip().splitlines()
        cut = next(i for i, l in enumerate(lines) if l.startswith("This Font Software is licensed"))
        notices += [l for l in lines[:cut] if l.strip()]
        text = "\n".join(lines[cut:])
    return "<!--\nEmbedded fonts (mindlathe.xyz build). " + ("\n".join(notices) + "\n\n" + text).replace("--", "- -") + "\n-->\n"


def main(src, out):
    s = open(src, encoding="utf-8").read()

    def sub(old, new, label):
        nonlocal s
        n = s.count(old)
        if n != 1:
            sys.exit(f"adapt: {label}: expected 1 match, found {n}")
        s = s.replace(old, new)

    pre = '''<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
'''
    lic = licence_comment(["pressstart2p", "pixelifysans", "vt323"])
    common = face("Press Start 2P", "PressStart2P.woff2") + face("Pixelify Sans", "PixelifySans.woff2", "400 600")

    # 1. The generator page.
    sub(pre + '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Pixelify+Sans:wght@400;600&display=swap">\n',
        lic + "<style>" + common + "</style>\n", "generator head")
    # 2. The visualizer's document (inert text until opened in the iframe).
    sub(pre + '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Pixelify+Sans:wght@400;600&family=VT323&display=swap">\n',
        "<style>" + common + face("VT323", "VT323.woff2") + "</style>\n", "visualizer head")

    # 3. Nothing may still name an outside host. Exempt, never fetched: XML
    #    namespace URIs, and the licence comment above (URLs the OFL requires).
    hosts = set(re.findall(r"https?://([a-zA-Z0-9.-]+)", s.replace(lic, ""))) - {"www.w3.org"}
    if hosts:
        sys.exit(f"adapt: outside hosts still referenced: {sorted(hosts)}")

    with open(out, "w", encoding="utf-8") as fh:
        fh.write(s)
    print(f"adapt: {os.path.basename(src)} -> {out} ({len(s):,} bytes, no outside hosts)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    main(sys.argv[1], sys.argv[2])
