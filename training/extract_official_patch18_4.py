"""Extract factual before/after fields from Riot's patch 18.4 article HTML.

This keeps short numeric deltas, not the article's commentary. The output is
reference evidence; applying it to an internal variable requires review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup, Tag


URL = "https://teamfighttactics.leagueoflegends.com/en-us/news/game-updates/teamfight-tactics-patch-18-4/"


def direct_text(li):
    return " ".join(" ".join(part.stripped_strings) if isinstance(part, Tag)
                    else str(part).strip() for part in li.contents
                    if not isinstance(part, Tag) or part.name != "ul").strip()


def leaves(ul, parents=()):
    for li in ul.find_all("li", recursive=False):
        text = " ".join(direct_text(li).split())
        children = li.find("ul", recursive=False)
        if children is None:
            yield parents, text
        else:
            yield from leaves(children, parents + ((text,) if text else ()))


def extract(html):
    soup = BeautifulSoup(html, "html.parser")
    headings = soup.select("h4.change-detail-title")
    if len(headings) != 20 or headings[9].get_text(" ", strip=True) != "COMBAT ARRIVAL AND DEPARTURE":
        raise ValueError("Riot article structure changed; review extraction")
    result = []
    for heading in headings[9:]:
        section = heading.get_text(" ", strip=True)
        ul = None
        for sibling in heading.next_siblings:
            if isinstance(sibling, Tag) and sibling.name in {"hr", "h4"}:
                break
            if isinstance(sibling, Tag) and sibling.name == "ul":
                ul = sibling
                break
        if ul is None:
            continue
        for parents, text in leaves(ul):
            if "⇒" not in text:
                continue
            before, after = [part.strip() for part in text.split("⇒", 1)]
            if ":" in before:
                metric, before = [part.strip() for part in before.split(":", 1)]
            else:
                metric = parents[-1] if parents else section
            if not before or not after:
                raise ValueError("numeric delta missing before/after")
            subject = (parents[1] if len(parents) > 1 and
                       parents[0] in {"Wisps", "Re-enabled Augments"}
                       else parents[0] if parents else None)
            result.append(dict(section=section, subject=subject,
                               path=list(parents), metric=metric,
                               before=before, after=after,
                               binding_status="unmapped_official_fact"))
    if len(result) < 80:
        raise ValueError("too few patch deltas; review extraction")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.html.read_bytes()
    changes = extract(raw)
    document = dict(schema_version=1, set_key="TFTSet18", patch="18.4",
                    source_url=URL, source_html_sha256=hashlib.sha256(raw).hexdigest(),
                    extraction="numeric_before_after_only; nonnumeric rules reviewed separately",
                    changes=changes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False,
                                      sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(changes=len(changes), source_sha256=document["source_html_sha256"])))


if __name__ == "__main__":
    main()
