"""Which region and country each shop belongs to.

The Kenya regions are the ones the deal posters ("Hot Deals Energy") are
printed for; Uganda and Sinza (Dar es Salaam) are their own countries.
"""
from __future__ import annotations

KENYA, UGANDA, TANZANIA = "Kenya", "Uganda", "Tanzania"

REGIONS = {
    "Nairobi": {"hazina", "hilton", "ktda", "starmall"},
    "Nairobi Metropolitan": {"kitengela", "thika", "rongai"},
    "Rift Valley": {"eldoret", "nakuru"},
    "Western and Nyanza": {"kakamega", "busia", "kisumu", "kisii"},
    "Central": {"meru", "nanyuki", "nyeri"},
    "Coastal": {"mombasa"},
    "Online": {"website", "jumia"},
}
_COUNTRY = {"uganda": UGANDA, "sinza": TANZANIA}


def country_of(location: str) -> str:
    return _COUNTRY.get(str(location).strip().lower(), KENYA)


def region_of(location: str) -> str:
    """A Kenya shop's region; outside Kenya the country is the region."""
    key = str(location).strip().lower()
    if key in _COUNTRY:
        return _COUNTRY[key]
    return next((r for r, shops in REGIONS.items() if key in shops), "Other")


if __name__ == "__main__":
    assert region_of("Ktda") == "Nairobi" and region_of("Kisii") == "Western and Nyanza"
    assert country_of("Sinza") == TANZANIA and region_of("Uganda") == UGANDA
    assert country_of("Mombasa") == KENYA and region_of("Staff POS") == "Other"
    print("regions ok")
