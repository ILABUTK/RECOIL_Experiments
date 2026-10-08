#!/usr/bin/env python3
"""Build the A4 context corpus: plain text of the original manuscript's Literature Review
(Section 2 of the R1 manuscript, git f39f2b9, before any R2 edits), used as stand-in 'retrieved documents'."""
import re, subprocess
from pathlib import Path
src = subprocess.run(["git", "show", "f39f2b9:Tex_CAIE/main.tex"], capture_output=True, text=True,
                     check=True, cwd=Path(__file__).resolve().parents[2]).stdout
body = src[src.index(r"\section{") + 1:]
lit = body[body.index("LITERATURE REVIEW"):body.index(r"\section{METHODOLOGY}")]
lit = re.sub(r"%.*", "", lit)
lit = re.sub(r"\\begin\{figure\*?\}.*?\\end\{figure\*?\}", "", lit, flags=re.S)
lit = re.sub(r"\\cite[pt]?\{[^}]*\}", "", lit)
lit = re.sub(r"\\(sub)*section\{([^}]*)\}", r"\n\2\n", lit)
lit = re.sub(r"\\item\[([^\]]*)\]", r"\1", lit)
lit = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?\{([^}]*)\}", r"\2", lit)
lit = re.sub(r"\\[a-zA-Z]+", "", lit)
lit = re.sub(r"[{}]", "", lit)
lit = re.sub(r"\n\s*\n+", "\n\n", lit).strip()
out = Path(__file__).parent / "data" / "context_corpus.txt"
out.write_text(lit)
print(len(lit), "chars ->", out)
