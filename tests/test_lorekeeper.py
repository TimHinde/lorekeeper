"""End-to-end and unit tests for the lorekeeper scripts. Run: python -m unittest discover -v"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import build_digest  # noqa: E402
import build_index  # noqa: E402
import lk  # noqa: E402
import make_fixture  # noqa: E402
import pdftools  # noqa: E402
import upsert_entity  # noqa: E402
import validate  # noqa: E402
import vaultlib as v  # noqa: E402

SRC = "the-salt-wake"

FRAG_CH1 = f"""---
type: npc
name: Maren Holt
summary: Brinemouth's stern harbourmaster; her son was aboard the missing trawler.
tags: [brinemouth]
role: harbourmaster
location: location/brinemouth
---
## Description
- Stern; keeps a ledger of every boat. [{SRC} p.2]

## In play
- Offers 20 silver to search the wreck of the [[Gull's Promise]]. [{SRC} p.3]

---
type: location
name: Brinemouth
summary: Fishing town on stilts above a tidal marsh.
kind: settlement
---
- Built on stilts over a tidal marsh. [{SRC} p.2]

## Read-aloud
> [!read-aloud] [{SRC} p.2]
> Fog rolls in off the marsh, thick enough to taste.

---
type: item
name: Gull's Promise
summary: The missing trawler.
---
## Description
- Trawler whose wreck Maren pays the party to search. [{SRC} p.3]
"""

FRAG_CH3 = f"""---
type: npc
name: Maren Holt
summary: A different summary that must not win.
role: harbour master
tags: [captive-son]
---
## Description
- Stern; keeps a ledger of every boat. [{SRC} p.2]

## Wants
- Her son back from the [[faction/brine-choir]]. [{SRC} p.6]

---
type: faction
name: The Brine Choir
summary: Tide-worshipping cult that stole the chapel bell.
leader: npc/brother-calloway
---
## Goals
- Ring the stolen bell three times at low water. [{SRC} p.6]

---
type: npc
name: Brother Calloway
summary: Former chapel warden who leads the Brine Choir.
faction: faction/brine-choir
---
## Wants
- Return the marsh to the sea. [{SRC} p.6]

---
type: creature
name: Silt Lurker
summary: Pale eel-like mud ambusher.
threat: low
---
## Stat block
```statblock system=any source={SRC} page=4
Silt Lurker
Threat: low. Hits: 9.
```
"""


def run_cli(*args) -> tuple[int, str]:
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            lk.main([str(a) for a in args])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return code, buf.getvalue()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="lk-test-"))
        cls.pdf = make_fixture.build(cls.tmp / "salt.pdf")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.vault = self.tmp / f"vault-{self._testMethodName}"
        if self.vault.exists():
            shutil.rmtree(self.vault)
        v.init_vault(self.vault, "Test")
        pdftools.probe(self.pdf, self.vault, max_pages=2)

    def write_frag(self, name: str, text: str) -> Path:
        p = self.vault / ".ingest" / "fragments" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def ingest_both(self):
        return upsert_entity.upsert_files(self.vault, [self.write_frag("001.md", FRAG_CH1),
                                                       self.write_frag("003.md", FRAG_CH3)])

    def errors(self):
        return [i for i in validate.validate(self.vault) if i.level == "error"]


class TestIdentity(unittest.TestCase):
    def test_slug_and_id(self):
        self.assertEqual(v.slugify("Gull's Promise"), "gulls-promise")
        self.assertEqual(v.slugify("Café  Noir!"), "cafe-noir")
        self.assertEqual(v.make_id("faction", "The Brine Choir"), "faction/brine-choir")
        self.assertEqual(v.make_id("location", "Theatre"), "location/theatre")

    def test_citations(self):
        c = v.citations_in("a [x-y p.3] b [x-y pp.4–6] c [x-y pp.7-8]")
        self.assertEqual(c, [("x-y", 3, 3), ("x-y", 4, 6), ("x-y", 7, 8)])

    def test_blocks(self):
        lines = ["- one [s p.1]", "  continued", "- two", "", "para line", "more", "", "```x", "- not", "```",
                 "> [!read-aloud] [s p.1]", "> text", "| a | b |"]
        kinds = [b.kind for b in v.iter_blocks(lines)]
        self.assertEqual(kinds, ["bullet", "bullet", "para", "fence", "callout", "table"])


class TestPdf(Base):
    def test_probe_plan(self):
        m = v.read_manifest(self.vault)["sources"][SRC]
        names = [c["name"] for c in m["chunks"]]
        self.assertIn("Chapter 1: Brinemouth", names)
        self.assertEqual(m["pages"], 6)
        self.assertTrue((self.vault / "sources" / f"{SRC}.md").exists())

    def test_probe_resumes(self):
        run_cli("mark", "--vault", self.vault, "--source", SRC, "--chunk", "2", "--status", "done")
        res = pdftools.probe(self.pdf, self.vault, max_pages=2)
        self.assertTrue(res["resumed"])
        self.assertEqual(res["chunks"][1]["status"], "done")

    def test_split_large_chapters(self):
        doc = pdftools.pymupdf.open(self.pdf)
        chunks = pdftools.plan_chunks(doc, max_pages=1)
        self.assertTrue(all(c.pages[1] - c.pages[0] + 1 <= 1 for c in chunks))

    def test_extract_layout(self):
        res = pdftools.extract(self.pdf, self.vault, SRC, 1, 6)
        text = Path(res["text_file"]).read_text()
        self.assertNotIn("THE SALT WAKE", text)                      # running head dropped
        self.assertIn("> Fog rolls in", text)                         # boxed text quoted
        self.assertIn("**Maren Holt.**", text)                        # bold lead kept
        self.assertLess(text.index("Maren Holt"), text.index("Lantern House"))  # left column first
        self.assertEqual([f["page"] for f in res["flagged"]], [5])    # image-only page
        self.assertTrue(Path(res["flagged"][0]["image"]).exists())
        self.assertIn(5, v.read_manifest(self.vault)["sources"][SRC]["flagged_pages"])

    def test_hyphen_resolution(self):
        s = pdftools.SOFT
        self.assertEqual(pdftools._resolve_hyphens(f"suc{s}ceed"), "succeed")
        self.assertEqual(pdftools._resolve_hyphens(f"tide{s}worship and tide-worship"),
                         "tide-worship and tide-worship")


class TestUpsert(Base):
    def test_create_merge_and_links(self):
        res = self.ingest_both()
        self.assertEqual(res.rejected, [])
        maren = v.read_doc(self.vault / "canon" / "npc" / "maren-holt.md")
        fm, body = maren
        self.assertEqual(fm["summary"], "Brinemouth's stern harbourmaster; her son was aboard the missing trawler.")
        self.assertEqual(fm["tags"], ["brinemouth", "captive-son"])
        self.assertEqual(fm["sources"], [{"source": SRC, "pages": [2, 3, 6]}])
        self.assertEqual(body.count("keeps a ledger"), 1)             # duplicate bullet dropped
        self.assertIn("Sources disagree on `role`", body)
        self.assertIn("[[item/gulls-promise|Gull's Promise]]", body)  # name link resolved
        self.assertTrue((self.vault / "canon" / "faction" / "brine-choir.md").exists())
        self.assertEqual(res.unresolved, {})
        sections = [s.heading for s in v.parse_sections(body)]
        self.assertEqual(sections, ["Description", "Wants", "In play", "Notes"])  # canonical order
        self.assertEqual(self.errors(), [])

    def test_rejects(self):
        p = self.write_frag("bad.md", "---\ntype: npc\nname: Nobody\nsummary: x\n---\n- uncited\n"
                                      "---\ntype: wizard\nname: X\n---\n- y [the-salt-wake p.1]\n")
        res = upsert_entity.upsert_files(self.vault, [p])
        self.assertEqual(len(res.rejected), 2)
        self.assertEqual(res.created, [])

    def test_near_duplicate_goes_to_review_and_merges(self):
        self.ingest_both()
        p = self.write_frag("dup.md", "---\ntype: npc\nname: Maren\nsummary: x\n---\n- Harbourmaster. [the-salt-wake p.2]\n")
        res = upsert_entity.upsert_files(self.vault, [p])
        self.assertEqual(res.created, ["npc/maren"])
        self.assertTrue(res.review)
        upsert_entity.merge_duplicate(self.vault, "npc/maren", "npc/maren-holt")
        self.assertFalse((self.vault / "canon" / "npc" / "maren.md").exists())
        fm, body = v.read_doc(self.vault / "canon" / "npc" / "maren-holt.md")
        self.assertIn("Maren", fm["aliases"])
        self.assertIn("Harbourmaster.", body)

    def test_ideas_layer(self):
        self.ingest_both()
        p = self.write_frag("idea.md", "---\ntype: scene\nname: Pier Ambush\nsummary: Lookouts strike.\n"
                                       "based_on: [faction/brine-choir]\n---\n## Setup\n- Two lookouts.\n")
        res = upsert_entity.upsert_files(self.vault, [p], default_layer="ideas")
        self.assertEqual(res.created, ["scene/pier-ambush"])
        fm, _ = v.read_doc(self.vault / "ideas" / "scene" / "pier-ambush.md")
        self.assertEqual(fm["status"], "draft")
        self.assertNotIn("sources", fm)
        self.assertEqual(self.errors(), [])

    def test_upsert_is_idempotent(self):
        self.ingest_both()
        res = upsert_entity.upsert_files(self.vault, [self.vault / ".ingest" / "fragments" / "001.md"])
        self.assertEqual(res.created, [])
        self.assertEqual(res.updated, [])


class TestValidate(Base):
    def test_catches_problems(self):
        self.ingest_both()
        bad = self.vault / "canon" / "lore" / "bad.md"
        bad.write_text("---\nid: lore/wrong\ntype: lore\nname: Bad\nlayer: canon\nsummary: s\n"
                       "sources: [{source: the-salt-wake, pages: [99]}]\nrelated: [npc/ghost]\n---\n"
                       "## Summary\n- uncited\n- out of range [the-salt-wake p.99]\n- unknown [nope p.1]\n")
        msgs = " | ".join(i.message for i in self.errors())
        for expected in ("should live at", "uncited fact", "outside 1–6", "unknown source", "does not exist"):
            self.assertIn(expected, msgs)

    def test_canon_cannot_point_at_ideas(self):
        self.ingest_both()
        p = self.write_frag("idea.md", "---\ntype: npc\nname: Invented Guy\nsummary: s\n---\n- x\n")
        upsert_entity.upsert_files(self.vault, [p], default_layer="ideas")
        f = self.vault / "canon" / "npc" / "brother-calloway.md"
        fm, body = v.read_doc(f)
        fm["related"] = ["npc/invented-guy"]
        f.write_text(v.dump_document(fm, body))
        self.assertTrue(any("exists only in ideas" in i.message for i in self.errors()))


class TestOutputs(Base):
    def test_index_digest_pack(self):
        self.ingest_both()
        run_cli("note", "npc/maren-holt", "--vault", self.vault)
        run_cli("session", "--vault", self.vault, "--title", "Fog")
        build_index.build(self.vault)
        npc_index = (self.vault / "_index" / "npc.md").read_text()
        self.assertIn("npc/maren-holt", npc_index)
        self.assertIn("✎", npc_index)
        self.assertIn("npc/brother-calloway", (self.vault / "_index" / "backlinks.md").read_text())
        res = build_digest.build(self.vault, self.tmp / "digest")
        names = [f["file"] for f in res["files"]]
        self.assertIn("canon-npc.md", names)
        self.assertIn("table.md", names)
        self.assertTrue((self.tmp / "digest" / "PROJECT-INSTRUCTIONS.md").exists())
        code, out = run_cli("pack", "--vault", self.vault, "--out", self.tmp / "v.zip")
        self.assertEqual(code, 0)
        code, out = run_cli("unpack", self.tmp / "v.zip", "--dest", self.tmp / "unz")
        self.assertTrue(v.is_vault(Path(json.loads(out)["vault"])))

    def test_find_and_show(self):
        self.ingest_both()
        code, out = run_cli("find", "bell", "--vault", self.vault)
        self.assertTrue(out.splitlines()[0].startswith("faction/brine-choir"))
        code, out = run_cli("show", "Maren Holt", "--vault", self.vault)
        self.assertIn("id: npc/maren-holt", out)

    def test_next_and_chunk_marking(self):
        p = self.write_frag("001.md", FRAG_CH1)
        code, out = run_cli("upsert", p, "--vault", self.vault, "--source", SRC, "--chunk", "2")
        self.assertEqual(code, 0)
        code, out = run_cli("next", "--vault", self.vault)
        self.assertEqual(json.loads(out)["chunk"], 1)
        chunks = v.read_manifest(self.vault)["sources"][SRC]["chunks"]
        self.assertEqual(chunks[1]["status"], "done")


if __name__ == "__main__":
    unittest.main()
