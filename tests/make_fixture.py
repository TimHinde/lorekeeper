"""Build a small, invented adventure PDF for tests. All content here is original.

Layout features exercised: a TOC with two levels, two-column pages, a boxed
read-aloud passage, larger heading fonts, bold lead-ins, running heads and page
numbers, a stat block, and one image-only page.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

W, H = 595, 842
M = 50
COL_W = (W - 2 * M - 20) / 2

PAGES = [
    # (heading, left column paragraphs, right column paragraphs, boxed text or None)
    ("The Salt Wake", ["A short adventure for three to five characters, written for any fantasy system."],
     [], None),
    ("Chapter 1: Brinemouth",
     ["Brinemouth is a fishing town built on stilts above a tidal marsh. Its people distrust outsiders but "
      "love gossip.",
      "**Maren Holt.** The harbourmaster is a stern woman who keeps a ledger of every boat. She wants the "
      "missing trawler found because her son was aboard it."],
     ["**The Lantern House.** A tavern on the highest stilts. Its owner, Ottilie Fenn, pays for news of the "
      "drowned bell.",
      "Rumour has it that the Brine Choir, a cult of tide-worshippers, meets beneath the pier at low water."],
     "Fog rolls in off the marsh, thick enough to taste. Somewhere below the boardwalk a bell tolls once, "
     "though no bell has hung in Brinemouth for forty years."),
    ("Chapter 1: Brinemouth (continued)",
     ["Maren will offer the characters twenty silver coins to search the wreck of the trawler Gull's Promise."],
     ["If the characters ask Ottilie about the bell, she admits the Brine Choir stole it from the old chapel."],
     None),
    ("Chapter 2: The Sunken Chapel",
     ["The chapel lies half-submerged at the marsh edge. Its nave floods at high tide.",
      "**Silt Lurker.** A pale, eel-like creature that hides in the mud of the nave and strikes at ankles."],
     ["Silt Lurker", "Threat: low. Armour: as leather. Hits: 9.", "Bite: grabs and drags the target under water.",
      "Tactics: flees when wounded by fire."],
     None),
    (None, [], [], None),   # image-only page
    ("Chapter 3: Low Water",
     ["At low water the Brine Choir gathers beneath the pier to ring the stolen bell and call the Salt Wake, "
      "a vast drowned thing.",
      "**Brother Calloway.** The Choir's leader, a former chapel warden. He believes the Wake will return the "
      "marsh to the sea."],
     ["If the bell is rung three times the Salt Wake rises. Maren's son is held captive among the Choir.",
      "Destroying or silencing the bell ends the ritual."],
     None),
]


def build(path: Path) -> Path:
    doc = pymupdf.open()
    for i, (heading, left, right, boxed) in enumerate(PAGES, 1):
        page = doc.new_page(width=W, height=H)
        if heading is None:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), False)
            pix.set_rect(pix.irect, (120, 140, 160))
            page.insert_image(pymupdf.Rect(M, M, W - M, H - M), pixmap=pix)
            continue
        page.insert_text((M, 25), "THE SALT WAKE", fontsize=7, fontname="helv")
        page.insert_text((W / 2, H - 20), str(i), fontsize=8, fontname="helv")
        page.insert_textbox(pymupdf.Rect(M, M, W - M, M + 40), heading, fontsize=20, fontname="hebo")
        y = M + 50
        if boxed:
            r = pymupdf.Rect(M, y, W - M, y + 70)
            page.draw_rect(r, color=(0, 0, 0), fill=(0.9, 0.9, 0.85))
            page.insert_textbox(r + (8, 8, -8, -8), boxed, fontsize=10, fontname="tiit")
            y += 85
        for col, paras in ((0, left), (1, right)):
            x0 = M + col * (COL_W + 20)
            cy = y
            for para in paras:
                html = para
                if para.startswith("**"):
                    end = para.index("**", 2)
                    html = f"<b>{para[2:end]}</b> {para[end + 2:].strip()}"
                rect = pymupdf.Rect(x0, cy, x0 + COL_W, cy + 200)
                page.insert_htmlbox(rect, f"<p style='font-size:10px;font-family:sans-serif'>{html}</p>")
                lines = max(1, int(pymupdf.get_text_length(para, fontsize=10) / COL_W) + 1)
                cy += lines * 13 + 16
    toc = [
        [1, "The Salt Wake", 1],
        [1, "Chapter 1: Brinemouth", 2],
        [2, "The Lantern House", 2],
        [2, "The Job", 3],
        [1, "Chapter 2: The Sunken Chapel", 4],
        [1, "Chapter 3: Low Water", 6],
    ]
    doc.set_toc(toc)
    doc.set_metadata({"title": "The Salt Wake"})
    doc.save(path)
    return path


if __name__ == "__main__":
    print(build(Path(sys.argv[1] if len(sys.argv) > 1 else "salt-wake.pdf")))
