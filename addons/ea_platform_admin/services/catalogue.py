"""What a firm can be built on, and what it is expected to cost.

Prices are from memory of Vultr's and Wasabi's public price lists and were NOT checked while this
was written (no call to either was allowed). They only drive the estimate shown before the owner
confirms. The owner confirms them on vultr.com and wasabi.com before the first real firm: see
docs/runbook/PREREQUISITES.md. Pure.
"""

PRICES_CONFIRMED = False

# Vultr region ids. Paris first: nearest with good links to Cameroon, to be confirmed by the owner.
REGIONS = {
    "cdg": "Paris (France)",
    "fra": "Frankfurt (Germany)",
    "ams": "Amsterdam (Netherlands)",
    "lhr": "London (United Kingdom)",
    "jnb": "Johannesburg (South Africa)",
}

# `standard` is the size the install log recommends for production.
SIZES = {
    "small": {
        "label": "Small: up to 10 users",
        "plan": "vc2-2c-4gb",
        "vcpu": 2,
        "ram_gb": 4,
        "disk_gb": 80,
        "monthly_usd": 20.0,
        "workers": 3,
        "limit_memory_hard_mb": 1100,
    },
    "standard": {
        "label": "Standard: up to 30 users",
        "plan": "vc2-4c-8gb",
        "vcpu": 4,
        "ram_gb": 8,
        "disk_gb": 160,
        "monthly_usd": 40.0,
        "workers": 5,
        "limit_memory_hard_mb": 1400,
    },
    "large": {
        "label": "Large: over 30 users",
        "plan": "vc2-6c-16gb",
        "vcpu": 6,
        "ram_gb": 16,
        "disk_gb": 320,
        "monthly_usd": 80.0,
        "workers": 9,
        "limit_memory_hard_mb": 1500,
    },
}

# Backups at Wasabi, pay as you go: about USD 7 per TB per month, so about USD 1 for a firm's
# 100 GB or so. The whole account pays at least 1 TB (about USD 7 a month) whatever the firms use,
# and a deleted file is billed as if kept 90 days: docs/runbook/WASABI.md. To confirm on wasabi.com.
STORAGE_MONTHLY_USD = 1.0

LANGUAGES = {
    "fr_FR": "French",
    "en_US": "English",
}


def selection(mapping):
    return [
        (key, value["label"] if isinstance(value, dict) else value)
        for key, value in mapping.items()
    ]


def monthly_cost(size):
    """(server, storage, total) in USD per month. Raises KeyError on an unknown size."""
    server = SIZES[size]["monthly_usd"]
    return server, STORAGE_MONTHLY_USD, server + STORAGE_MONTHLY_USD
