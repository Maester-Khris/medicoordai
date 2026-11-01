#!/usr/bin/env python3
"""Fetch place details for Chartwell Avondale Retirement Residence
via Foursquare Places API (places-api.foursquare.com)
Auth: Bearer service API key
Version: 2025-06-17
"""

import json
import os
import urllib.request
import urllib.parse
import urllib.error

API_KEY    = os.environ["FOURSQUARE_API_KEY"]  # via doppler run --
PLACE_NAME = "Chartwell Avondale Retirement Residence"
BASE       = "https://places-api.foursquare.com"
API_VER    = "2025-06-17"

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {API_KEY}",
    "X-Places-Api-Version": API_VER,
}

def get(path: str, params: dict = None) -> dict:
    qs = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{BASE}{path}{qs}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode(errors="replace")
        except Exception:
            body = "(unreadable)"
        return None, f"HTTP {e.code}: {body}"
    except Exception as ex:
        return None, str(ex)

def p(label: str, value):
    print(f"  {label:<40} {value}")

def main():
    print("=" * 65)
    print(f"Query   : {PLACE_NAME}")
    print(f"Base URL: {BASE}")
    print(f"Version : {API_VER}")
    print("=" * 65)

    # --- Step 1: Search ---
    print("\n[1/2] Searching…")
    result, err = get("/places/search", {
        "query": PLACE_NAME,
        "near": "Toronto, ON, Canada",
        "limit": 5,
    })
    if err:
        print(f"  ERROR: {err}")
        return

    results = result.get("results", [])
    if not results:
        print("  No results. Raw response:")
        print(json.dumps(result, indent=2))
        return

    # Pick best match by name
    best = next(
        (r for r in results if "avondale" in r.get("name", "").lower()),
        results[0]
    )

    # New Places API schema: fsq_place_id, latitude/longitude at top level
    fsq_id  = best.get("fsq_place_id")
    loc0    = best.get("location", {})
    ext_loc = best.get("extended_location", {})
    lat     = best.get("latitude")
    lng     = best.get("longitude")
    cats0   = [c.get("name","") for c in best.get("categories", [])]

    print(f"  Found {len(results)} result(s) — using best match:")
    p("FSQ Place ID:",  fsq_id)
    p("Name:",          best.get("name", "N/A"))
    p("Address:",       loc0.get("formatted_address", "N/A"))
    p("Lat/Lng:",       f"{lat}, {lng}")
    p("Phone:",         best.get("tel", "N/A"))
    p("Email:",         best.get("email", "N/A"))
    p("Website:",       best.get("website", "N/A"))
    p("Categories:",    ", ".join(cats0))

    if not fsq_id:
        print("  No fsq_id in result — cannot fetch details.")
        return

    # --- Step 2: Place Details ---
    # Details endpoint path uses fsq_place_id
    print(f"\n[2/2] Fetching details for {fsq_id}…")
    detail, err2 = get(f"/places/{fsq_id}")
    if err2:
        print(f"  ERROR: {err2}")
        print("\n  Trying /places/ask fallback…")
        ask_result, err3 = get("/places/ask", {"query": PLACE_NAME})
        if err3:
            print(f"  /places/ask ERROR: {err3}")
        else:
            print("  /places/ask raw response:")
            print(json.dumps(ask_result, indent=2))
        return

    # Detail response — also uses top-level lat/lng and fsq_place_id
    d   = detail
    loc  = d.get("location", {})
    lat2 = d.get("latitude")
    lng2 = d.get("longitude")
    oh   = d.get("hours", {})
    st   = d.get("stats", {})
    soc  = d.get("social_media", {})
    cats = [c.get("name","") for c in d.get("categories", [])]

    print("\n" + "─" * 65)
    print("PLACE DETAILS")
    print("─" * 65)

    p("FSQ Place ID:",            d.get("fsq_place_id", "N/A"))
    p("Name:",                    d.get("name", "N/A"))
    p("Verified:",                d.get("verified", "N/A"))
    p("Description:",             d.get("description", "N/A"))
    p("Rating (0–10):",           d.get("rating", "N/A"))
    p("Rating Signals:",          d.get("rating_signals", "N/A"))
    p("Popularity:",              d.get("popularity", "N/A"))
    p("Price Tier (1–4):",        d.get("price", "N/A"))

    print()
    p("Formatted Address:",       loc.get("formatted_address", "N/A"))
    p("Street:",                  loc.get("address", "N/A"))
    p("City:",                    loc.get("locality", "N/A"))
    p("Region/Province:",         loc.get("region", "N/A"))
    p("Postal Code:",             loc.get("postcode", "N/A"))
    p("Country:",                 loc.get("country", "N/A"))
    p("Latitude:",                lat2)
    p("Longitude:",               lng2)

    print()
    p("Phone:",                   d.get("tel", "N/A"))
    p("Email:",                   d.get("email", "N/A"))
    p("Website:",                 d.get("website", "N/A"))
    p("Facebook:",                soc.get("facebook_id", "N/A"))
    p("Instagram:",               soc.get("instagram", "N/A"))
    p("Twitter:",                 soc.get("twitter", "N/A"))

    print()
    p("Categories:",              ", ".join(cats))
    p("Primary Type:",            d.get("primary_type", "N/A"))
    p("Total Check-ins:",         st.get("total_checkins", "N/A"))
    p("Total Tips:",              st.get("total_tips", "N/A"))
    p("Total Photos:",            st.get("total_photos", "N/A"))
    p("Total Ratings:",           st.get("total_ratings", "N/A"))

    # Hours
    p("\nOpen Now:",              oh.get("open_now", "N/A"))
    for line in oh.get("display", []):
        print(f"    {line}")

    # Photos
    photos = d.get("photos", [])
    p("\nPhotos available:",      len(photos))
    for ph in photos[:2]:
        prefix = ph.get("prefix","")
        suffix = ph.get("suffix","")
        if prefix and suffix:
            print(f"    {prefix}800x600{suffix}")

    # Tips / Reviews
    tips = d.get("tips", [])
    if tips:
        print(f"\n  Tips ({len(tips)}):")
        for t in tips[:3]:
            author = t.get("author", {})
            name   = f"{author.get('firstName','')} {author.get('lastName','')}".strip()
            text   = t.get("text","")[:120]
            agrees = t.get("agreeCount", 0)
            print(f"    [{agrees}👍] {name or 'Anon'}: {text}")

    print("\n" + "=" * 65)
    print("RAW JSON (excluding photos/tips):")
    print("=" * 65)
    raw = {k: v for k, v in d.items() if k not in ("photos", "tips")}
    print(json.dumps(raw, indent=2))

if __name__ == "__main__":
    main()
