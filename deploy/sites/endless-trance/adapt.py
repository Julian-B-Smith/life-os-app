#!/usr/bin/env python3
"""Adapt Endless Trance's published page for mindlathe.xyz/endless-trance/.

    python3 deploy/sites/endless-trance/adapt.py <endless-trance>/dist/endless-trance-av.html OUT.html

Input is the page Endless Trance's own build writes (`tools/build_av.py`):
generator + embedded visualizer, made to run as a claude.ai artifact. The site
takes it unchanged except for one thing (owner, 2026-10-05): it must make no
requests to anyone else, the same rule as the domain root (mind-lathe D31/D34).
So:

  * Google Fonts links are removed from both documents (the generator page and
    the visualizer's, which is embedded as text and opened in a srcdoc iframe,
    so it needs its own @font-face rules), and the five families ship inline as
    WOFF2 subsets (fonts/: Latin + the symbols the page uses; variable fonts
    trimmed to the weights it uses). All SIL OFL 1.1; licences alongside.
  * (The iPhone audio fixes this script used to patch in, input inside the
    gesture, unlock on touchend/click, phone latency, close on pagehide, are
    upstream since Endless Trance v22: integrations/mindlathe-site reply 002.)
  * JSZip from cdnjs is removed, not inlined: export is already off in this
    build (EXPORT_ON=false hides the tab and panel, owner's choice for the site),
    and the visualizer's zip import is hidden in hosted mode, so nothing reaches
    it. Its on-demand loader now rejects instead of fetching.

Every edit must match exactly once, so a changed upstream fails loudly instead
of half-applying (the update is then here, not in Endless Trance). The last
check refuses any output that still names an outside host.

Lives in life-os-app because Endless Trance is not yet under version control;
when it is spun up, this belongs there as a "site" build target.
"""
import base64, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")


def face(family, file, weight="400"):
    data = base64.b64encode(open(os.path.join(FONTS, file), "rb").read()).decode()
    return (f'@font-face{{font-family:"{family}";src:url(data:font/woff2;base64,{data}) format("woff2");'
            f'font-weight:{weight};font-style:normal;font-display:swap}}')


def licence_comment(dirs):
    # OFL requires the copyright notice and the licence with every copy. The
    # notices differ per family; the licence text is the same, so it appears once.
    notices = []
    text = None
    for d in dirs:
        lines = open(os.path.join(FONTS, f"OFL-{d}.txt"), encoding="utf-8").read().strip().splitlines()
        cut = next(i for i, l in enumerate(lines) if l.startswith("This Font Software is licensed"))
        notices += [l for l in lines[:cut] if l.strip()]
        text = "\n".join(lines[cut:])
    body = "\n".join(notices) + "\n\n" + text
    return "<!--\nEmbedded fonts (mindlathe.xyz build). " + body.replace("--", "- -") + "\n-->\n"


def main(src, out):
    s = open(src, encoding="utf-8").read()

    def sub(old, new, label):
        nonlocal s
        n = s.count(old)
        if n != 1:
            sys.exit(f"adapt: {label}: expected 1 match, found {n}")
        s = s.replace(old, new)

    # 1. The generator page: its font links and the JSZip script.
    lic = licence_comment(["vt323", "michroma", "manrope", "jetbrainsmono", "sharetechmono"])
    sub('''<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=VT323&family=Michroma&family=Manrope:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap">
<script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>
''', lic + "<style>"
        + face("VT323", "VT323.woff2") + face("Michroma", "Michroma.woff2")
        + face("Manrope", "Manrope.woff2", "400 700") + face("JetBrains Mono", "JetBrainsMono.woff2", "400 600")
        + "</style>\n", "generator head")

    # 2. The visualizer's document (inert text until opened in the iframe).
    sub('''<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=VT323&family=Share+Tech+Mono&display=swap">
''', "<style>" + face("VT323", "VT323.woff2") + face("Share Tech Mono", "ShareTechMono.woff2") + "</style>\n",
        "visualizer head")
    sub("""sc.src='https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js'; sc.onload=res; sc.onerror=()=>rej(new Error('Could not load the zip reader')); document.head.appendChild(sc);""",
        """rej(new Error('Zip import is not available on this page'));""", "visualizer zip loader")

    # 3. Nothing may still name an outside host. Two exemptions, both never
    #    fetched: XML namespace URIs (identifiers), and the font licence comment
    #    inserted above (its project and licence URLs are text the OFL requires).
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
