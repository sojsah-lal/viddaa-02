"""Who's famous right now: trending Wikipedia people with a free-licensed Commons portrait.

Pipeline (all free, no keys):
  Wikipedia top-viewed articles (yesterday) -> Wikidata entity per article ->
  keep living adults whose occupation is athlete / musician / actor / creator / politician ->
  Commons portrait whose license is CC0 / public domain / CC BY / CC BY-SA -> download a small thumbnail.

Any network or data problem returns fewer (or zero) people; callers fall back to plain colored balls.
"""
import html
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

UA = {"User-Agent": "viddaa-02/1.0 (https://github.com/sojsah-lal/viddaa-02; daily simulation videos)"}
ROOT = Path(__file__).resolve().parent.parent
FACES = ROOT / "output" / "faces"

# Wikidata occupation ids (P106) that qualify.
OCCUPATIONS = {
    # sport
    "Q2066131", "Q937857", "Q3665646", "Q10833314", "Q12299841", "Q19204627", "Q11338576", "Q378622",
    "Q11607585", "Q10871364", "Q11774891", "Q11303721", "Q13381376", "Q13141064", "Q10843402", "Q4009406",
    # music
    "Q177220", "Q639669", "Q2252262", "Q488205", "Q753110", "Q36834", "Q130857", "Q855091", "Q386854",
    # screen
    "Q33999", "Q10800557", "Q10798782", "Q2405480", "Q947873", "Q245068", "Q2526255", "Q4610556",
    # creators
    "Q17125263", "Q15077007", "Q57414145", "Q94791573",
    # politics
    "Q82955", "Q30461", "Q48352", "Q83307", "Q372436",
}
FREE_LICENSE = re.compile(r"^(cc0|public domain|pd|cc[ -]by(-sa)?[ -]?\d)", re.I)
MAX_TRENDING = 2  # at most this many "in the news" people per race; the rest are SUPERSTARS
STAR_FAME = 180  # trending people must have articles in this many Wikipedia languages (household names)
# Always-recognizable fallback stars (English Wikipedia titles); same filters and license checks apply.
SUPERSTARS = [
    "Lionel_Messi", "Cristiano_Ronaldo", "Kylian_Mbappé", "Erling_Haaland", "Neymar", "Vinícius_Júnior",
    "LeBron_James", "Stephen_Curry", "Lewis_Hamilton", "Max_Verstappen", "Novak_Djokovic", "Carlos_Alcaraz",
    "Taylor_Swift", "Beyoncé", "Rihanna", "Ariana_Grande", "Billie_Eilish", "Bad_Bunny", "The_Weeknd",
    "Ed_Sheeran", "Lady_Gaga", "Justin_Bieber", "Selena_Gomez", "Dua_Lipa", "Lisa_(rapper)",
    "Jennie_(singer)", "Rosé_(singer)", "Jisoo", "Jungkook", "Jimin", "Dwayne_Johnson", "Tom_Cruise",
    "Zendaya", "Keanu_Reeves", "Tom_Holland", "MrBeast", "IShowSpeed", "Kai_Cenat",
]
SKIP_TITLE = re.compile(r"^(Main_Page|Special:|Wikipedia:|File:|Portal:|Help:|Template:|Category:|Talk:)")


def _get(url, **params):
    """GET JSON with a few retries: Wikimedia (and some home networks) have brief hiccups."""
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=20)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(1.5 * (attempt + 1))


def trending_titles(day: date, limit=250) -> list:
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/"
           f"{day:%Y}/{day:%m}/{day:%d}")
    items = _get(url)["items"][0]["articles"]
    return [a["article"] for a in items if not SKIP_TITLE.match(a["article"])][:limit]


def wikidata_ids(titles: list) -> dict:
    """title -> Qid (follows redirects)."""
    out = {}
    for i in range(0, len(titles), 50):
        data = _get("https://en.wikipedia.org/w/api.php", action="query", format="json", redirects=1,
                    prop="pageprops", ppprop="wikibase_item", titles="|".join(titles[i:i + 50]))
        q = data.get("query", {})
        back = {r["to"]: r["from"] for r in q.get("redirects", [])}
        back.update({n["to"]: n["from"] for n in q.get("normalized", [])})
        for page in q.get("pages", {}).values():
            qid = page.get("pageprops", {}).get("wikibase_item")
            if qid:
                title = page["title"]
                out[back.get(title, title).replace(" ", "_")] = qid
    return out


def _claim_ids(claims, prop):
    return [c["mainsnak"].get("datavalue", {}).get("value", {}).get("id")
            for c in claims.get(prop, []) if c["mainsnak"].get("snaktype") == "value"]


def _birth_year(claims):
    for c in claims.get("P569", []):
        v = c["mainsnak"].get("datavalue", {}).get("value", {}).get("time")
        if v:
            return int(v[1:5]) if v[0] in "+-" else int(v[:4])
    return None


def people(qids: list, today: date) -> list:
    """Filter entities to living adults in allowed occupations that have an image (P18)."""
    out = []
    for i in range(0, len(qids), 50):
        ents = _get("https://www.wikidata.org/w/api.php", action="wbgetentities", format="json",
                    ids="|".join(qids[i:i + 50]), props="claims|labels|sitelinks", languages="en")["entities"]
        for qid, e in ents.items():
            claims = e.get("claims", {})
            if "Q5" not in _claim_ids(claims, "P31"):          # human
                continue
            if claims.get("P570"):                              # has a date of death
                continue
            born = _birth_year(claims)
            if born is None or today.year - born < 19:          # adult (with a margin)
                continue
            if not OCCUPATIONS.intersection(_claim_ids(claims, "P106")):
                continue
            image = next((c["mainsnak"]["datavalue"]["value"] for c in claims.get("P18", [])
                          if c["mainsnak"].get("snaktype") == "value"), None)
            label = e.get("labels", {}).get("en", {}).get("value")
            if image and label:
                out.append({"qid": qid, "name": label, "file": image, "fame": len(e.get("sitelinks", {}))})
    return out


def _strip(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", s or "")).split())


def licensed_thumb(file: str, width=256):
    """Return (thumb_url, artist, license) if the Commons file is free-licensed, else None."""
    data = _get("https://commons.wikimedia.org/w/api.php", action="query", format="json",
                titles=f"File:{file}", prop="imageinfo", iiprop="url|extmetadata", iiurlwidth=width)
    page = next(iter(data["query"]["pages"].values()))
    info = (page.get("imageinfo") or [None])[0]
    if not info:
        return None
    meta = info.get("extmetadata", {})
    lic = _strip(meta.get("LicenseShortName", {}).get("value", ""))
    if not FREE_LICENSE.match(lic):
        return None
    artist = _strip(meta.get("Artist", {}).get("value", "")) or "Unknown author"
    return info.get("thumburl") or info.get("url"), artist[:60], lic


def fetch(n_max=12, exclude=(), day: date = None, seed: int = 0) -> list:
    """Up to n_max famous people as dicts: name, short, image (repo-relative path), credit.
    Household-name people trending yesterday come first, then a seeded shuffle of SUPERSTARS."""
    today = datetime.now(timezone.utc).date()
    day = day or today - timedelta(days=1)
    order, cands = [], {}
    try:
        titles = trending_titles(day)
        ids = wikidata_ids(titles)
        trending = list(dict.fromkeys(ids[t] for t in titles if t in ids))
        stars_ids = wikidata_ids(SUPERSTARS)
        stars = list(dict.fromkeys(stars_ids.values()))
        random.Random(seed).shuffle(stars)
        cands = {p["qid"]: p for p in people(list(dict.fromkeys(trending + stars)), today)}
        hot = [q for q in trending if q in cands and cands[q]["fame"] >= STAR_FAME][:MAX_TRENDING]
        order = hot + [q for q in stars if q in cands and q not in hot]
    except (requests.RequestException, KeyError, ValueError, IndexError) as e:
        print(f"[celebs] lookup failed: {e}")
        return []
    FACES.mkdir(parents=True, exist_ok=True)
    out = []
    for qid in order:
        p = cands[qid]
        if p["name"] in exclude:
            continue
        try:
            lic = licensed_thumb(p["file"])
            if not lic:
                continue
            url, artist, license_name = lic
            r = None
            for attempt in range(3):
                try:
                    r = requests.get(url, headers=UA, timeout=20)
                    r.raise_for_status()
                    break
                except requests.RequestException:
                    if attempt == 2:
                        raise
                    time.sleep(1.5)
            if not r.headers.get("Content-Type", "").startswith("image/"):
                continue
            path = FACES / f"{qid}{Path(url.split('?')[0]).suffix.lower() or '.jpg'}"
            path.write_bytes(r.content)
        except (requests.RequestException, KeyError, ValueError, StopIteration) as e:
            print(f"[celebs] skipping {p['name']}: {e}")
            continue
        short = p["name"].split()[-1] if len(p["name"].split()) > 1 else p["name"]
        out.append({"name": p["name"], "short": short[:14], "image": path.relative_to(ROOT).as_posix(),
                    "credit": f"{p['name']}: {artist}, {license_name}, via Wikimedia Commons"})
        if len(out) >= n_max:
            break
    return out


if __name__ == "__main__":
    for person in fetch():
        print(person["name"], "|", person["image"], "|", person["credit"])
