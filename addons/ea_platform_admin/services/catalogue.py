"""What a firm can be built on, and what it is expected to cost.

Prices are from memory of Vultr's public price list and were NOT checked against Vultr while this
was written (no call to Vultr was allowed). They only drive the estimate shown before the owner
confirms. The owner confirms them on vultr.com before the first real firm: see
docs/runbook/PREREQUISITES.md. Pure.
"""

PRICES_CONFIRMED = False

# Vultr region ids. Paris first: nearest with good links to Cameroon, to be confirmed by the owner.
REGIONS = {
    "cdg": "Paris (France)",
    "fra": "Francfort (Allemagne)",
    "ams": "Amsterdam (Pays-Bas)",
    "lhr": "Londres (Royaume-Uni)",
    "jnb": "Johannesburg (Afrique du Sud)",
}

# `standard` is the size the install log recommends for production.
SIZES = {
    "small": {
        "label": "Petit : jusqu'à 10 utilisateurs",
        "plan": "vc2-2c-4gb",
        "vcpu": 2,
        "ram_gb": 4,
        "disk_gb": 80,
        "monthly_usd": 20.0,
        "workers": 3,
        "limit_memory_hard_mb": 1100,
    },
    "standard": {
        "label": "Standard : jusqu'à 30 utilisateurs",
        "plan": "vc2-4c-8gb",
        "vcpu": 4,
        "ram_gb": 8,
        "disk_gb": 160,
        "monthly_usd": 40.0,
        "workers": 5,
        "limit_memory_hard_mb": 1400,
    },
    "large": {
        "label": "Grand : plus de 30 utilisateurs",
        "plan": "vc2-6c-16gb",
        "vcpu": 6,
        "ram_gb": 16,
        "disk_gb": 320,
        "monthly_usd": 80.0,
        "workers": 9,
        "limit_memory_hard_mb": 1500,
    },
}

# One storage subscription per firm, because a Vultr access key opens a whole subscription.
STORAGE_MONTHLY_USD = 18.0

LANGUAGES = {
    "fr_FR": "Français",
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
