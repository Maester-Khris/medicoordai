#!/usr/bin/env python3
"""
Test Geoapify Places API for facility enrichment.
Fetches place search + details using GEOAPIFY_API_KEY.
"""
import os
import json
import requests

API_KEY = os.environ.get("GEOAPIFY_API_KEY") or os.environ.get("VITE_GEOAPIFY_API_KEY")

if not API_KEY:
    raise ValueError("GEOAPIFY_API_KEY not found in environment.")

def search_facility(name: str, address: str = ""):
    query = f"{name} {address}".strip()
    url = "https://api.geoapify.com/v1/geocode/search"
    params = {
        "text": query,
        "apiKey": API_KEY,
        "limit": 1
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", [])
    if not features:
        return None
    return features[0]["properties"]

def fetch_place_details(place_id: str):
    url = "https://api.geoapify.com/v2/place-details"
    params = {
        "id": place_id,
        "apiKey": API_KEY
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", [])
    if not features:
        return None
    return features[0]["properties"]

def parse_facility_fields(props: dict) -> dict:
    """Extract standard facility enrichment fields from Geoapify properties."""
    contact = props.get("contact", {})
    phone = contact.get("phone") or props.get("phone")
    
    # Opening hours
    opening_hours = props.get("opening_hours")
    
    # Address
    formatted_address = props.get("formatted")
    
    # Operational status (Geoapify includes raw properties or tags)
    categories = props.get("categories", [])
    
    return {
        "place_id": props.get("place_id"),
        "name": props.get("name") or props.get("address_line1"),
        "phone": phone,
        "weekday_hours": opening_hours,
        "formatted_address": formatted_address,
        "categories": categories,
        "lat": props.get("lat"),
        "lon": props.get("lon")
    }

if __name__ == "__main__":
    facilities = [
        {"name": "Toronto General Hospital", "address": "200 Elizabeth St, Toronto"},
        {"name": "Appletree Medical Centre", "address": "275 Yonge St, Toronto"}
    ]
    for fac in facilities:
        print(f"\nTesting Geoapify for: {fac['name']}...")
        props = search_facility(fac["name"], fac["address"])
        if not props:
            print("No results found.")
            continue
        place_id = props.get("place_id")
        details = fetch_place_details(place_id) if place_id else props
        enriched = parse_facility_fields(details or props)
        print("Enriched Facility Data:")
        print(json.dumps(enriched, indent=2))

