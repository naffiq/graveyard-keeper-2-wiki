"""Extract crafting recipes from the wiki's wikitext.

The Graveyard Keeper 2 wiki records recipes with templates (see
recipe_templates): {{Recipe}} for crafting at a workstation and
{{Recipe/Blueprint}} for what a structure costs to build. Plain
"Material | Quantity" tables (material_table) and the Graveyard Keeper 1 table
formats below are parsed as a fallback, e.g. on an item page:

    !colspan="3"|{{Item|Furnace}}          <- station header row
    |-
    |{{Item|Iron ingot|1}}                 <- product cell
    |{{Item|Iron ore|1}}                   <- materials cell
    |2:30<br>{{Fuel|-|25}}

and on structure pages a ==Cost== table whose row has an icon cell followed
by the materials needed to build the page's subject. Product rows prefixed
with "*" need a perk.
"""
import re

ITEM_RE = re.compile(r"\{\{\s*[Ii]tem\s*\|([^{}|]+?)(?:\|\s*([\d.,]+)\s*)?(?:\|[^{}]*)?\}\}")
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
UPGRADE_RE = re.compile(r"\[\[([^\]|#]+)\|\s*Upgrade to [^\]]*\]\]", re.I)
TOOL_RE = re.compile(r"pickaxe|\baxe\b|shovel|fishing rod|\bhoe\b", re.I)
COST_SECTIONS = re.compile(r"^(cost|costs|construction|building|build|price|requirements?|materials?|crafting cost)$", re.I)


def norm(name):
    name = re.sub(r"\s+", " ", name.replace("_", " ")).strip()
    return name[:1].upper() + name[1:]


def items_in(cell):
    out = []
    for m in ITEM_RE.finditer(cell):
        qty = m.group(2)
        try:
            qty = float(qty.replace(",", ".")) if qty else 1.0
        except ValueError:
            qty = 1.0
        out.append((norm(re.sub(r"^\s*1\s*=", "", m.group(1))), qty))
    return out


def split_tables(text):
    """Yield (section_heading, table_text) for every top-level wikitable."""
    heading, depth, start = "", 0, None
    lines = text.split("\n")
    buf = []
    for line in lines:
        s = line.strip()
        if depth == 0:
            h = re.match(r"^(=+)\s*(.*?)\s*\1\s*$", s)
            if h:
                heading = h.group(2)
        if s.startswith("{|"):
            depth += 1
            if depth == 1:
                buf = []
        if depth:
            buf.append(line)
        if s.startswith("|}") and depth:
            depth -= 1
            if depth == 0:
                yield heading, "\n".join(buf)


def parse_rows(table):
    """Return rows as lists of (is_header, cell_text); nested tables are kept in cells."""
    rows, row, cell, depth = [], [], None, 0

    def flush_cell():
        nonlocal cell
        if cell is not None:
            row.append(cell)
        cell = None

    for line in table.split("\n")[1:]:
        s = line.strip()
        if depth:
            cell = (cell[0], cell[1] + "\n" + line)
            if s.startswith("{|"):
                depth += 1
            elif s.startswith("|}"):
                depth -= 1
            continue
        if s.startswith("{|"):
            depth += 1
            cell = (cell[0], cell[1] + "\n" + line) if cell else (False, line)
            continue
        if s.startswith("|}"):
            break
        if s.startswith("|-"):
            flush_cell()
            if row:
                rows.append(row)
            row = []
            continue
        if s.startswith("|+"):
            continue
        if s.startswith("!") or s.startswith("|"):
            flush_cell()
            header = s.startswith("!")
            parts = re.split(r"!!|\|\|", s[1:]) if header else s[1:].split("||")
            for i, part in enumerate(parts):
                # strip cell attributes: 'style="..."|content' (but not template pipes)
                m = re.match(r'^\s*((?:[\w-]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s|]+)\s*)+)\|(?!\|)(.*)$', part)
                content = m.group(2) if m else part
                if i < len(parts) - 1:
                    row.append((header, content))
                else:
                    cell = (header, content)
            continue
        if cell is not None:
            cell = (cell[0], cell[1] + "\n" + line)
    flush_cell()
    if row:
        rows.append(row)
    return rows


def station_of(cell):
    items = items_in(cell)
    if items:
        return " / ".join(n for n, _ in items)
    links = [norm(m.group(1)) for m in LINK_RE.finditer(cell)
             if not m.group(1).lower().startswith(("file:", "image:", "category:"))]
    return " / ".join(links)


QTY_HEADERS = ("quantity", "amount", "qty", "count", "number")


def plain(cell):
    """Item name from a cell: the link target if linked, else the bare text."""
    m = LINK_RE.search(cell)
    if m and not m.group(1).lower().startswith(("file:", "image:", "category:")):
        return norm(m.group(1))
    text = re.sub(r"\{\{[^{}]*\}\}|<[^>]+>|'{2,}|\[\[[^\]]*\]\]", "", cell)
    return norm(text)


def material_table(rows):
    """GK2 style cost table for the page's own subject:

        !Material
        !Quantity
        |-
        |Wood Plank
        |4
    """
    cols = None
    materials = []
    for row in rows:
        cells = [c for _, c in row]
        if cols is None:
            if all(h for h, _ in row):
                low = [plain(c).lower() for c in cells]
                mat = next((i for i, c in enumerate(low)
                            if c.startswith("material") or c in ("item", "resource")), None)
                qty = next((i for i, c in enumerate(low) if c.startswith(QTY_HEADERS)), None)
                if mat is not None and qty is not None:
                    cols = (mat, qty)
            continue
        if len(cells) <= max(cols):
            continue
        name = plain(cells[cols[0]])
        m = re.search(r"\d+(?:[.,]\d+)?", cells[cols[1]])
        if name and m:
            materials.append((name, float(m.group().replace(",", "."))))
    return materials


def templates(text, names):
    """Yield (name, params) for each call of the given templates.

    Handles nested {{...}} and [[...]] inside parameter values; positional
    parameters are keyed "1", "2", ...
    """
    wanted = {n.lower() for n in names}
    i = 0
    while True:
        i = text.find("{{", i)
        if i < 0:
            return
        depth, j = 0, i
        while j < len(text):
            if text.startswith("{{", j):
                depth += 1
                j += 2
            elif text.startswith("}}", j):
                depth -= 1
                j += 2
                if depth == 0:
                    break
            else:
                j += 1
        body = text[i + 2:j - 2]
        # split on top-level pipes only
        parts, buf, d = [], "", 0
        k = 0
        while k < len(body):
            two = body[k:k + 2]
            if two in ("{{", "[["):
                d += 1
                buf += two
                k += 2
            elif two in ("}}", "]]"):
                d -= 1
                buf += two
                k += 2
            elif body[k] == "|" and d == 0:
                parts.append(buf)
                buf = ""
                k += 1
            else:
                buf += body[k]
                k += 1
        parts.append(buf)
        name = parts[0].strip()
        if name.lower() in wanted:
            params, pos = {}, 0
            for p in parts[1:]:
                key, eq, val = p.partition("=")
                if eq and re.fullmatch(r"\s*[\w ]+\s*", key):
                    params[key.strip()] = val.strip()
                else:
                    pos += 1
                    params[str(pos)] = p.strip()
            yield name, params
            i = j
        else:
            i += 2  # look inside: the wanted template may be nested


def _qty(value, default=1.0):
    m = re.search(r"\d+(?:[.,]\d+)?", value or "")
    return float(m.group().replace(",", ".")) if m else default


def recipe_templates(title, text):
    """{{Recipe|blueprint=Furnace II|result=Iron Ingot|resultQ=3|item1=Iron Ore|item1Q=3|...}}
    and {{Recipe/Blueprint|location=General|result=Simple Chest|item1=Wooden Plank|item1Q=4|...}}."""
    out = []
    for name, p in templates(text, ["Recipe", "Recipe/Blueprint"]):
        materials = []
        for n in range(1, 10):
            item = p.get(f"item{n}", "").strip()
            if item:
                materials.append((norm(item), _qty(p.get(f"item{n}Q"))))
        if not materials:
            continue
        product = norm(p.get("result") or title)
        if name.lower() == "recipe/blueprint":
            loc = p.get("location", "").strip()
            stations = ["Any location" if loc.lower() in ("", "general") else norm(loc)]
            out.append(dict(product=product, qty=1.0, materials=materials,
                            station=" / ".join(stations), perk=False, source=title, building=True))
        else:
            stations = [norm(s) for s in (p.get("blueprint"), p.get("extension")) if s and s.strip()]
            out.append(dict(product=product, qty=_qty(p.get("resultQ")), materials=materials,
                            station=" / ".join(stations), perk=False, source=title))
    return out


def extract(title, text, in_place=None):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\{\{\s*(?:lc:|ucfirst:)?\s*\{\{\s*PAGENAME\s*\}\}\s*\}\}", title, text, flags=re.I)
    text = re.sub(r"\{\{\s*PAGENAME\s*\}\}", title, text, flags=re.I)
    recipes = recipe_templates(title, text)
    is_item_page = re.search(r"\{\{\s*Item Infobox", text, re.I) is not None
    is_station_page = re.search(r"\{\{\s*Workstation-Infobox", text, re.I) is not None
    is_tech = re.search(r"\[\[\s*Category\s*:\s*Tech\s*\]\]", text, re.I) is not None
    for heading, table in split_tables(text):
        rows = parse_rows(table)
        mats = material_table(rows)
        if mats and all(m != norm(title) for m, _ in mats):
            recipes.append(dict(product=norm(title), qty=1.0, materials=mats,
                                station="Build" if is_tech else "", perk=False,
                                source=title, building=is_tech))
            continue
        station = ""
        cost_table = bool(COST_SECTIONS.match(heading.strip()))
        cost_rows = 0
        for row in rows:
            data = [c for h, c in row if not h]
            if all(h for h, _ in row):
                # A lone header cell naming a workstation sets the station for following rows.
                if len(row) == 1:
                    st = station_of(row[0][1])
                    if st:
                        station = st
                continue
            if len(data) < 2:
                continue
            first, second = data[0], data[1]
            products = items_in(first)
            materials = items_in(second)
            perk = first.lstrip().startswith("*")
            known_station = bool(station) or is_station_page
            if products and materials and (len(products) == 1 or (known_station and len(products) <= 3)):
                # A row may yield several things at once (burning a corpse gives a
                # Burial certificate, Salt and Ash): one recipe per output, the
                # others listed as by-products. Long multi-item rows without a
                # station are quest/trade tables, not crafts.
                for name, qty in products:
                    if any(m == name for m, _ in materials):
                        # e.g. embalming: Corpse + injection -> Corpse. The item is
                        # modified, not made, so it should stay a raw material.
                        if in_place is not None:
                            in_place.add(name)
                        continue
                    recipes.append(dict(product=name, qty=qty, materials=materials,
                                        station=station or (title if is_station_page else ""),
                                        perk=perk, source=title,
                                        also=[(n, q) for n, q in products if n != name]))
                continue
            up = UPGRADE_RE.search(first)
            if up and materials:
                # Upgrading consumes the current structure.
                recipes.append(dict(product=norm(up.group(1)), qty=1.0,
                                    materials=[(norm(title), 1.0)] + materials,
                                    station=title, perk=False, source=title, building=True))
                continue
            if (cost_table and not is_item_page and not products and materials and cost_rows == 0
                    and all(m != norm(title) for m, _ in materials)):
                # Structure cost: icon cell + materials for the page's own subject.
                cost_rows += 1
                recipes.append(dict(product=norm(title), qty=1.0, materials=materials,
                                    station="Build", perk=False, source=title, building=True))
    return recipes


def build(wikitext):
    """Merge recipes found on all pages.

    The same recipe is usually listed on the product page, the workstation page
    and some guides; those are merged into one entry with the union of stations.
    Recipes from the product's own page come first, in page order (that is the
    wiki's tier order, e.g. Wooden anvil, Anvil, Anvil II).
    """
    merged, in_place = {}, set()
    pages = sorted(wikitext.items(), key=lambda kv: kv[0])
    extracted = [(title, extract(title, text, in_place)) for title, text in pages
                 if not title.startswith("Category:")]
    for title, found in extracted:
        for i, r in enumerate(found):
            if r["product"] in in_place and not r.get("building"):
                continue
            # "*" marks both perk-only recipes and perk bonuses, so a recipe also
            # listed without "*" elsewhere is treated as not needing the perk.
            mats = list(dict.fromkeys(r["materials"]))  # drop repeated cells
            if not r["station"] and any(TOOL_RE.search(m) for m, _ in mats):
                continue  # gathering with a tool, not a recipe
            r["materials"] = mats
            key = (r["product"], r["qty"], tuple(sorted(r["materials"])))
            stations = [s for s in r["station"].split(" / ") if s]
            rank = (0 if r["source"] == r["product"] else 1, i)
            if key in merged:
                m = merged[key]
                for s in stations:
                    if s not in m["stations"]:
                        m["stations"].append(s)
                m["building"] = m["building"] or r.get("building", False)
                m["perk"] = m["perk"] and r["perk"]
                m["rank"] = min(m["rank"], rank)
                continue
            merged[key] = dict(product=r["product"], qty=r["qty"], materials=r["materials"],
                               stations=stations, perk=r["perk"],
                               building=r.get("building", False), rank=rank,
                               also=r.get("also", []))
    # Default recipe = first one: no perk, known station, product's own page order.
    recipes = sorted(merged.values(),
                     key=lambda r: (r["product"], r["perk"], not r["stations"], r["rank"]))
    for r in recipes:
        del r["rank"]
    return recipes


SPRITE_RE = re.compile(r'<a href="/wiki/[^"]*" title="([^"]+)"[^>]*>\s*<span class="sprite item-sprite" '
                       r'style="background-position:\s*(-?\d+)px\s+(-?\d+)px')


IMG_ICON_RE = re.compile(r'<a href="/wiki/[^"]*" title="([^"]+)"[^>]*>\s*<img [^>]*?'
                         r'(?:data-src|src)="(https://static\.wikia\.nocookie\.net/[^"]+)"[^>]*'
                         r'width="(\d+)"')


def image_icons(parsed_pages):
    """Item name -> small image URL, for items drawn with a file instead of a sprite."""
    icons = {}
    for p in parsed_pages:
        for name, url, width in IMG_ICON_RE.findall(p.get("text", "")):
            if int(width) <= 48:
                icons.setdefault(norm(name), url)
    return icons


def sprite_positions(parsed_pages):
    """Item name -> (x, y) offset in ItemSprite.png, read from rendered pages."""
    icons = {}
    for p in parsed_pages:
        for name, x, y in SPRITE_RE.findall(p.get("text", "")):
            icons.setdefault(norm(name), (int(x), int(y)))
    return icons
