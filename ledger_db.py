import sqlite3
import json
import os
import random

DB_PATH = "ledger.db"

# Static/approximate USD exchange rates - display only, the simulation itself
# always runs in USD billions internally so saves and math stay consistent.
# unit_divisor+unit_label keep the displayed number in a readable range
# (e.g. Rupiah/Yen use "T" for trillion instead of a huge "B" figure).
CURRENCY_INFO = {
    "Indonesia": {"symbol": "Rp", "rate_per_usd": 15800, "unit_divisor": 1000, "unit_label": "T"},
    "Singapore": {"symbol": "S$", "rate_per_usd": 1.34, "unit_divisor": 1, "unit_label": "B"},
    "United States": {"symbol": "$", "rate_per_usd": 1.0, "unit_divisor": 1, "unit_label": "B"},
    "Japan": {"symbol": "¥", "rate_per_usd": 155, "unit_divisor": 1000, "unit_label": "T"},
    "Germany": {"symbol": "€", "rate_per_usd": 0.92, "unit_divisor": 1, "unit_label": "B"},
}

# Turns are quarterly (3 months each, 4 per calendar year) - turn_year is
# stored as a 0-based turn INDEX (not a literal calendar year) so every
# internal comparison (elections, crises, victory) stays simple integer
# arithmetic. get_calendar_label() derives the player-facing "2026 Q1" style
# label from that index.
GAME_START_YEAR = 2026
QUARTERS_PER_YEAR = 4
TOTAL_GAME_TURNS = 200  # 50 years x 4 quarters

def get_calendar_label(turn_index):
    year = GAME_START_YEAR + turn_index // QUARTERS_PER_YEAR
    quarter = (turn_index % QUARTERS_PER_YEAR) + 1
    return year, quarter

def format_currency(usd_billions, country_name, decimals=1):
    info = CURRENCY_INFO.get(country_name, CURRENCY_INFO["United States"])
    local_value = usd_billions * info["rate_per_usd"] / info["unit_divisor"]
    return f"{info['symbol']}{local_value:,.{decimals}f}{info['unit_label']}"

def to_local(usd_billions, country_name):
    """Raw local-currency-scaled number (no symbol/formatting) - for input widgets that need a plain float."""
    info = CURRENCY_INFO.get(country_name, CURRENCY_INFO["United States"])
    return usd_billions * info["rate_per_usd"] / info["unit_divisor"]

def from_local(local_value, country_name):
    """Inverse of to_local - converts a local-currency-scaled number back to USD billions for the simulation."""
    info = CURRENCY_INFO.get(country_name, CURRENCY_INFO["United States"])
    return local_value * info["unit_divisor"] / info["rate_per_usd"]

def currency_unit_suffix(country_name):
    """Short unit label for widget captions, e.g. 'Rp T' or '$ B'."""
    info = CURRENCY_INFO.get(country_name, CURRENCY_INFO["United States"])
    return f"{info['symbol']} {info['unit_label']}"

# Each country's dominant trade lever (whichever dependency is higher) earns
# a tariff-revenue bonus on that specific lever via TRADE_SPECIALIZATION_BONUS
# - a country "strong" in imports (like Indonesia) gets extra revenue when
# the player raises Import Tariff specifically, on top of the revenue it
# already collects from being import-dependent. This only touches the
# revenue side, not the GDP-growth/happiness costs of that tariff.
TRADE_SPECIALIZATION_BONUS = 1.25

COUNTRY_PRESETS = {
    "Singapore": {
        "pop_low": 900000,      # 15% of 6.0M
        "pop_mid": 3600000,     # 60%
        "pop_high": 900000,     # 15%
        "pop_elder": 600000,    # 10%
        "gdp": 500.0,           # $500B
        "treasury": 100.0,      # +$100B reserves
        "tax_low": 0.05,
        "tax_mid": 0.15,
        "tax_high": 0.22,
        "export_dependency": 0.70,  # highly trade-dependent economy
        "import_dependency": 0.65,  # trade hub, imports almost everything it consumes
        "trade_specialization": "export",  # entrepot trade hub, export-led
    },
    "Indonesia": {
        "pop_low": 140000000,   # 50% of 280M
        "pop_mid": 112000000,   # 40%
        "pop_high": 8400000,    # 3%
        "pop_elder": 19600000,  # 7%
        "gdp": 1400.0,          # $1,400B
        "treasury": -60.0,      # -$60B national debt
        "tax_low": 0.05,
        "tax_mid": 0.15,
        "tax_high": 0.30,
        "export_dependency": 0.25,
        "import_dependency": 0.30,
        "trade_specialization": "import",  # large consumer market, import-led
    },
    "United States": {
        "pop_low": 85000000,    # 25% of 340M
        "pop_mid": 187000000,   # 55%
        "pop_high": 34000000,   # 10%
        "pop_elder": 34000000,   # 10%
        "gdp": 28000.0,         # $28,000B (28T)
        "treasury": -34000.0,   # -$34,000B debt (34T)
        "tax_low": 0.10,
        "tax_mid": 0.22,
        "tax_high": 0.37,
        "export_dependency": 0.12,  # relatively closed, consumption-driven economy
        "import_dependency": 0.15,
        "trade_specialization": "import",  # consumption-driven economy, import-led
    },
    "Japan": {
        "pop_low": 24800000,    # 20% of 124M
        "pop_mid": 62000000,    # 50%
        "pop_high": 12400000,   # 10%
        "pop_elder": 24800000,  # 20% elderly ratio
        "gdp": 4200.0,          # $4,200B
        "treasury": -5000.0,    # -$5,000B debt (~119% of GDP - realistically high but still under the -150% bankruptcy line)
        "tax_low": 0.08,
        "tax_mid": 0.20,
        "tax_high": 0.45,
        "export_dependency": 0.35,
        "import_dependency": 0.40,  # heavily reliant on imported energy & raw materials
        "trade_specialization": "import",  # reliant on imported energy & raw materials
    },
    "Germany": {
        "pop_low": 12600000,    # 15% of 84M
        "pop_mid": 46200000,    # 55%
        "pop_high": 12600000,   # 15%
        "pop_elder": 12600000,  # 15%
        "gdp": 4500.0,          # $4,500B
        "treasury": -3100.0,    # -$3,100B debt
        "tax_low": 0.08,
        "tax_mid": 0.30,
        "tax_high": 0.42,
        "export_dependency": 0.50,  # major manufacturing exporter
        "import_dependency": 0.45,  # deeply embedded in EU supply chains
        "trade_specialization": "export",  # major manufacturing exporter
    }
}

PARTY_PRESETS = {
    "Partai Rakyat Progresif": {
        "tagline_key": "party_tagline_progresif",
        "ideology": {"tax_high": 1, "welfare": 1, "security": -1},
    },
    "Partai Nasional Konservatif": {
        "tagline_key": "party_tagline_konservatif",
        "ideology": {"tax_high": -1, "welfare": -1, "security": 1},
    },
}

def get_opposition_party(party_name):
    for name in PARTY_PRESETS:
        if name != party_name:
            return name
    return None

# Cabinet: one advisor can be hired per position. Higher tiers cost more to
# hire and to keep on payroll (salary is deducted from treasury every turn)
# but give a bigger bonus to the position's linked stat in engine.py.
CABINET_POSITIONS = ["Menteri Pendidikan", "Menteri Kesehatan", "Menteri Infrastruktur", "Menteri Sosial", "Menteri Keamanan", "Gubernur Bank Sentral"]

# bonus and salary are applied every turn, so both are quartered from their
# original per-year magnitude now that a turn is a quarter, not a year;
# hire_cost is a one-time cost and stays as-is.
ADVISOR_TIERS = {
    "Muda": {"bonus": 0.5, "hire_cost": 5.0, "salary": 0.25},
    "Berpengalaman": {"bonus": 1.0, "hire_cost": 15.0, "salary": 0.75},
    "Pakar": {"bonus": 1.75, "hire_cost": 35.0, "salary": 1.5},
}

# Odds that a hired advisor's unsolicited policy advice actually targets the
# real problem. Junior advisors are a coin flip; experts are nearly always
# right - this is the "hidden" quality difference beyond their flat bonus.
ADVISOR_ACCURACY = {
    "Muda": 0.50,
    "Berpengalaman": 0.75,
    "Pakar": 0.95,
}

# Which stat each cabinet position's advice targets, how much accepting a
# CORRECT tip moves that stat, and the flavor text shown to the player.
MINISTER_ADVICE_MAP = {
    "Menteri Pendidikan": {
        "target_field": "education_index",
        "effect_magnitude": 8.0,
        "advice_text": "Naikkan anggaran Pendidikan untuk mendorong kualitas SDM dan pertumbuhan jangka panjang.",
    },
    "Menteri Kesehatan": {
        "target_field": "health_index",
        "effect_magnitude": 8.0,
        "advice_text": "Naikkan anggaran Kesehatan untuk memperbaiki layanan publik dan kesejahteraan lansia.",
    },
    "Menteri Infrastruktur": {
        "target_field": "infrastructure",
        "effect_magnitude": 8.0,
        "advice_text": "Naikkan anggaran Infrastruktur untuk mendorong pertumbuhan ekonomi.",
    },
    "Menteri Sosial": {
        "target_field": "happiness",
        "effect_magnitude": 8.0,
        "advice_text": "Naikkan anggaran Kesejahteraan Sosial untuk menenangkan masyarakat.",
    },
    "Menteri Keamanan": {
        "target_field": "crime_rate",
        "effect_magnitude": -0.08,
        "advice_text": "Naikkan anggaran Keamanan untuk menekan tingkat kriminalitas.",
    },
    "Gubernur Bank Sentral": {
        "target_field": "inflation_rate",
        "effect_magnitude": -0.005,
        "advice_text": "Kendalikan laju kenaikan Upah Minimum dan Tarif Impor untuk meredam tekanan inflasi.",
    },
}
MINISTER_ADVICE_COST = 20.0

# Difficulty was previously stored but never actually read by the simulation
# (Hard behaved identically to Medium), which is why players reported Hard
# being easy to beat. These settings are read every turn from engine.py and
# at game/hire time from ledger_db.py to make each tier mechanically distinct.
# interest_rate_* are quartered from their original per-year figure since
# debt interest is now charged every quarter instead of once a year;
# crisis_duration_delta is in quarters now (x4 its old per-year value) so an
# "extra year" of grace on Easy still means an extra year, not an extra turn.
DIFFICULTY_SETTINGS = {
    "Easy": {
        "interest_rate_normal": 0.01,
        "interest_rate_crisis": 0.0175,
        "crisis_duration_delta": 4,
        "decay_modifier": 0.7,
        "shock_severity_mult": 0.7,
        "starting_funds_mult": 1.10,
        "opposition_growth_mult": 0.8,
        "election_mandate_threshold": 50.0,
        "election_narrow_threshold": 35.0,
        "minister_cost_mult": 0.85,
        "deficit_ceiling_pct": 5.0,
    },
    "Medium": {
        "interest_rate_normal": 0.015,
        "interest_rate_crisis": 0.0225,
        "crisis_duration_delta": 0,
        "decay_modifier": 1.0,
        "shock_severity_mult": 1.0,
        "starting_funds_mult": 1.0,
        "opposition_growth_mult": 1.0,
        "election_mandate_threshold": 55.0,
        "election_narrow_threshold": 40.0,
        "minister_cost_mult": 1.0,
        "deficit_ceiling_pct": 3.0,
    },
    "Hard": {
        "interest_rate_normal": 0.0225,
        "interest_rate_crisis": 0.0325,
        "crisis_duration_delta": -4,
        "decay_modifier": 1.3,
        "shock_severity_mult": 1.3,
        "starting_funds_mult": 0.90,
        "opposition_growth_mult": 1.25,
        "election_mandate_threshold": 60.0,
        "election_narrow_threshold": 45.0,
        "minister_cost_mult": 1.2,
        "deficit_ceiling_pct": 2.0,
    },
}

# Opposition Strength above this makes them contest your budget in parliament
# regardless of whether the deficit ceiling is respected. A Coalition Support
# score (built via apply_coalition_negotiation) offsets this check in app.py,
# but never affects the harder no-confidence/election game-over conditions.
BUDGET_OPPOSITION_CONTEST_THRESHOLD = 70.0

# Sovereign Credit Rating - derived fresh every turn (never stored) from the
# Debt/GDP ratio, downgraded one band further if Corruption is severe (>=50%).
# Feeds two things: a multiplier on the debt interest rate (engine.py) and the
# maximum size of a Sovereign Bond the player is allowed to issue (app.py).
CREDIT_RATING_BANDS = [
    (0.0, "AAA", 0.70, 0.15),
    (-20.0, "AA", 0.85, 0.12),
    (-50.0, "A", 1.00, 0.10),
    (-80.0, "BBB", 1.15, 0.07),
    (-120.0, "BB", 1.35, 0.04),
    (-150.0, "B", 1.60, 0.02),
]

def get_credit_rating(debt_to_gdp_pct, corruption_index):
    effective = debt_to_gdp_pct - (20.0 if corruption_index >= 50.0 else 0.0)
    for threshold, letter, interest_mod, bond_cap_pct in CREDIT_RATING_BANDS:
        if effective >= threshold:
            return {"letter": letter, "interest_modifier": interest_mod, "bond_cap_pct": bond_cap_pct}
    return {"letter": "D", "interest_modifier": 2.00, "bond_cap_pct": 0.0}

def get_difficulty(game_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT difficulty FROM games WHERE game_id = ?", (game_id,))
    row = cursor.fetchone()
    conn.close()
    difficulty = row[0] if row and row[0] else "Medium"
    return difficulty if difficulty in DIFFICULTY_SETTINGS else "Medium"

def get_difficulty_settings(game_id, db_path=DB_PATH):
    return DIFFICULTY_SETTINGS[get_difficulty(game_id, db_path)]

# Fictional (not real-world) advisor names, curated per country and per tier
# so the player picks a specific name when hiring instead of getting a random
# one - names lean on each country's naming conventions for flavor, and get
# more formal/academic titles at higher tiers (Muda = fresh graduate, Pakar =
# decorated expert). Deliberately avoids reusing any actual real politician's
# full name. Each tier pool holds 9 names (not just 3) so that
# get_advisor_name_choices can exclude whoever is already serving in another
# cabinet position - with 6 cabinet positions, worst case 5 are already
# filled at the same tier, still leaving >=3 free names to offer for the 6th.
ADVISOR_NAME_POOLS = {
    "Indonesia": {
        "Muda": ["Fajar Nugroho", "Dewi Anggraini", "Rizky Ramadhan", "Anisa Rahmawati", "Doni Kurniawan",
                 "Putri Wulandari", "Dimas Prakoso", "Intan Permata", "Reza Firmansyah"],
        "Berpengalaman": ["Ir. Bambang Wirawan", "Siti Amelia Putri, M.M.", "Hendra Wijaya", "Drs. Slamet Riyadi",
                          "Dra. Endang Suryani", "Dr. Kevin Halim", "Dr. Farah Nabila", "Ir. Kartika Sari, M.T.",
                          "Komisaris Besar Arman Hidayat"],
        "Pakar": ["Prof. Dr. Yusuf Kartawijaya", "Dr. Ratna Sari Dewi", "Prof. Dr. Agus Santoso", "Prof. Dr. Grace Lim",
                  "Prof. Ir. Dr. Wibisono Aditya", "Prof. Dr. Herman Susilo", "Jenderal (Purn.) Suryo Wibowo",
                  "Prof. Dr. dr. Bagus Kurniawan", "Prof. Dr. Anggraeni Puspitasari"],
    },
    "Singapore": {
        "Muda": ["Tan Wei Jie", "Nur Aisyah Binte Ismail", "Kevin Goh Junwei", "Jasmine Lee Hui Xin", "Amirul bin Rashid",
                 "Deepa Ramesh", "Marcus Chua Jun Hao", "Nurul Huda binte Zainal", "Karthik Subramaniam"],
        "Berpengalaman": ["Rajesh Kumar Pillai", "Michelle Tanoto", "Lim Kok Wei", "Serene Goh Li Ling",
                          "Zulkifli bin Ahmad", "Kavitha Raman", "Daniel Ong Wei Liang", "Fatimah binte Yusof",
                          "Major Kelvin Yeo Chin Hock"],
        "Pakar": ["Prof. Grace Lim Hui Min", "Dr. Ahmad Faizal bin Hassan", "Prof. Wong Kai Ming", "Prof. Dr. Chan Poh Lin",
                  "Prof. Dr. Ganesh Iyer", "Prof. Eng. Ho Cheng Huat", "Brigadier-General (Ret.) Ng Boon Huat",
                  "Prof. Dr. Koh Bee Choo", "Prof. Dr. Foo Kok Seng"],
    },
    "United States": {
        "Muda": ["Jake Thompson", "Emily Carter", "Marcus Reed", "Olivia Bennett", "Tyler Brooks", "Hannah Wallace",
                 "Nathan Price", "Grace Coleman", "Ethan Sanders"],
        "Berpengalaman": ["Sarah Mitchell", "Robert Jennings", "Angela Foster", "Dr. Karen Lewis", "Major Brian Coleman",
                          "Patricia Nguyen", "Dr. Steven Park", "Rachel Adams", "Colonel Frank Delgado"],
        "Pakar": ["Prof. Dr. David Whitman", "Dr. Linda Harrington", "Prof. Dr. Michael Chen", "Prof. Dr. Susan Blackwell",
                  "General (Ret.) James Calloway", "Prof. Dr. Rebecca Stone", "Prof. Dr. Thomas Reilly",
                  "Dr. Monica Alvarez", "Prof. Dr. William Ashford"],
    },
    "Japan": {
        "Muda": ["Yuki Sato", "Kenji Watanabe", "Aiko Kobayashi", "Sora Matsumoto", "Rina Endo", "Daiki Inoue",
                 "Hana Kimura", "Ren Saito", "Mio Shimizu"],
        "Berpengalaman": ["Hiroshi Tanaka", "Naoko Yamada", "Takeshi Nakamura", "Dr. Emiko Suzuki", "Yumiko Hayashi",
                          "Major Ichiro Mori", "Kazuki Ono", "Sachiko Fujita", "Colonel Takumi Abe"],
        "Pakar": ["Prof. Dr. Akira Fujimoto", "Prof. Dr. Nozomi Kato", "Prof. Dr. Ryota Ishikawa", "Prof. Dr. Michiko Kondo",
                  "General (Ret.) Kenta Yoshida", "Prof. Dr. Satoshi Aoki", "Prof. Dr. Yoko Nishimura",
                  "Dr. Haruto Kaneko", "Prof. Dr. Miyuki Ogawa"],
    },
    "Germany": {
        "Muda": ["Lukas Hoffmann", "Anna Fischer", "Jonas Weber", "Lena Schulz", "Felix Wagner", "Marie Becker",
                 "Paul Hartmann", "Laura Schuster", "Tim Neumann"],
        "Berpengalaman": ["Klaus Müller", "Helga Richter", "Stefan Braun", "Dr. Sabine Krüger", "Major Dieter Lange",
                          "Petra Vogel", "Dr. Matthias Keller", "Birgit Wolf", "Colonel Rainer Schmid"],
        "Pakar": ["Prof. Dr. Heinrich Bauer", "Dr. Ingrid Schneider", "Prof. Dr. Wolfgang Zimmermann",
                  "Prof. Dr. Gisela Hoffstetter", "General (Ret.) Manfred Kessler", "Prof. Dr. Renate Albrecht",
                  "Prof. Dr. Dieter Straub", "Dr. Christine Berger", "Prof. Dr. Werner Lindemann"],
    },
}

def get_advisor_name_choices(game_id, country_name, tier, db_path=DB_PATH):
    """
    Candidate advisor names the hiring UI should offer for this country/tier
    combo, excluding anyone already serving in ANOTHER cabinet position in
    this game - a named advisor can't simultaneously hold two ministries.
    Falls back to the full pool only in the unlikely case exclusion would
    leave zero choices (pool sizes are kept large enough to avoid this).
    """
    pool = ADVISOR_NAME_POOLS.get(country_name, ADVISOR_NAME_POOLS["Indonesia"])[tier]
    already_serving = {c['advisor_name'] for c in get_cabinet(game_id, db_path)}
    available = [name for name in pool if name not in already_serving]
    return available if available else pool

# Random Narrative Events: occasional turns present the player with a discrete
# choice (not a slider) that has immediate stat consequences, applied in-place
# to the current turn like apply_bribe/hire_advisor. 'condition' filters which
# events are eligible to appear given the just-simulated state. Effect dicts
# are additive deltas applied to (and clamped where relevant on) the current
# nation_history row: treasury, gdp, happiness, opposition_strength,
# corruption_index, infrastructure, health_index, education_index.
RANDOM_EVENTS = {
    "imf_loan": {
        "title": "Tawaran Pinjaman IMF",
        "description": "IMF menawarkan pinjaman darurat $150B untuk menstabilkan keuangan negara, dengan syarat program penghematan yang tidak populer.",
        "condition": lambda s: s['treasury'] < 0,
        "choices": {
            "Terima Pinjaman": {"treasury": 150.0, "happiness": -15.0, "opposition_strength": 5.0},
            "Tolak Pinjaman": {"happiness": 5.0},
        },
    },
    "cabinet_scandal": {
        "title": "Skandal Korupsi Menteri",
        "description": "Media mengungkap salah satu menteri Anda menerima suap dari kontraktor swasta.",
        "condition": lambda s: s['corruption_index'] > 30.0,
        "choices": {
            "Pecat & Investigasi": {"corruption_index": -20.0, "treasury": -30.0},
            "Tutupi Skandal": {"corruption_index": 15.0, "opposition_strength": 10.0},
        },
    },
    "foreign_investor": {
        "title": "Investor Asing Menawarkan Kesepakatan Besar",
        "description": "Sebuah konsorsium asing menawarkan investasi besar-besaran dengan syarat kelonggaran regulasi.",
        "condition": lambda s: True,
        "choices": {
            "Terima Investasi": {"treasury": 50.0, "gdp": 0.0, "corruption_index": 10.0},
            "Tolak, Jaga Kedaulatan Ekonomi": {"happiness": 10.0},
        },
    },
    "humanitarian_crisis": {
        "title": "Bencana Kemanusiaan di Negara Tetangga",
        "description": "Negara tetangga dilanda bencana besar dan meminta bantuan kemanusiaan dari Novus.",
        "condition": lambda s: True,
        "choices": {
            "Kirim Bantuan": {"treasury": -20.0, "happiness": 10.0},
            "Fokus ke Dalam Negeri": {"happiness": -5.0},
        },
    },
    "labor_strike": {
        "title": "Mogok Kerja Nasional",
        "description": "Serikat buruh di seluruh negeri melakukan mogok kerja massal menuntut kenaikan kesejahteraan.",
        "condition": lambda s: s['happiness'] < 55.0,
        "choices": {
            "Penuhi Tuntutan Buruh": {"treasury": -30.0, "happiness": 10.0},
            "Tindak Tegas": {"happiness": -15.0, "opposition_strength": 10.0},
        },
    },
    "resource_discovery": {
        "title": "Penemuan Sumber Daya Alam Baru",
        "description": "Survei geologi menemukan cadangan sumber daya alam besar yang belum dieksplorasi.",
        "condition": lambda s: True,
        "choices": {
            "Eksploitasi Cepat": {"treasury": 80.0, "health_index": -10.0},
            "Kembangkan Berkelanjutan": {"treasury": 30.0, "infrastructure": 5.0},
        },
    },
    "cyber_threat": {
        "title": "Ancaman Siber Skala Besar Terdeteksi",
        "description": "Badan intelijen mendeteksi rencana serangan siber besar terhadap infrastruktur digital negara sebelum terjadi.",
        "condition": lambda s: True,
        "choices": {
            "Bayar Tebusan Preventif": {"treasury": -40.0},
            "Perkuat Pertahanan Sendiri": {"infrastructure": -3.0},
        },
    },
    "market_confidence": {
        "title": "Krisis Kepercayaan Pasar",
        "description": "Pasar keuangan mulai gelisah akibat ketidakstabilan politik, memicu spekulasi dan pelarian modal.",
        "condition": lambda s: s['opposition_strength'] > 40.0,
        "choices": {
            "Intervensi Pasar": {"treasury": -50.0, "opposition_strength": -10.0},
            "Biarkan Pasar Menyesuaikan": {"happiness": -10.0, "opposition_strength": 5.0},
        },
    },
    "trade_war": {
        "title": "Ancaman Perang Dagang",
        "description": "Hubungan Luar Negeri anjlok ke titik kritis - mitra dagang utama mengancam menjatuhkan tarif balasan besar-besaran terhadap ekspor Anda.",
        "condition": lambda s: s['foreign_relations'] < 20.0,
        "choices": {
            "Buka Negosiasi Darurat": {"treasury": -30.0, "foreign_relations": 25.0},
            "Terima Risiko & Bertahan": {"happiness": -10.0, "opposition_strength": 8.0},
        },
    },

    # --- Struktural: satu event per pilar anggaran (Pendidikan, Kesehatan,
    # Infrastruktur, Kesejahteraan Sosial, Keamanan) sehingga kelimanya kini
    # punya narrative event sendiri, bukan cuma index yang dipantau pasif. ---
    "school_funding_gap": {
        "title": "Kesenjangan Dana Sekolah Terungkap",
        "description": "Investigasi media menemukan banyak sekolah negeri kekurangan dana operasional dasar, memicu kemarahan publik.",
        "condition": lambda s: s['education_index'] < 45.0,
        "choices": {
            "Suntik Dana Darurat": {"treasury": -40.0, "education_index": 8.0, "happiness": 5.0},
            "Janjikan Reformasi Bertahap": {"opposition_strength": 6.0, "happiness": -5.0},
        },
    },
    "health_worker_strike": {
        "title": "Mogok Kerja Tenaga Medis",
        "description": "Tenaga medis di rumah sakit pemerintah mogok kerja, menuntut kenaikan insentif dan perbaikan fasilitas.",
        "condition": lambda s: s['health_index'] < 45.0,
        "choices": {
            "Penuhi Tuntutan Insentif": {"treasury": -35.0, "health_index": 8.0, "happiness": 4.0},
            "Tunda, Anggaran Terbatas": {"health_index": -5.0, "opposition_strength": 5.0},
        },
    },
    "infrastructure_investment_offer": {
        "title": "Tawaran Investasi Infrastruktur Asing",
        "description": "Konsorsium asing menawarkan pendanaan proyek infrastruktur skala besar, dengan syarat kepemilikan sebagian aset.",
        "condition": lambda s: s['infrastructure'] < 55.0,
        "choices": {
            "Terima, Percepat Pembangunan": {"infrastructure": 10.0, "corruption_index": 5.0, "foreign_relations": 5.0},
            "Danai Mandiri, Jaga Kedaulatan": {"treasury": -45.0, "infrastructure": 8.0},
        },
    },
    "welfare_ngo_request": {
        "title": "LSM Kesejahteraan Sosial Minta Tambahan Anggaran",
        "description": "Koalisi LSM menuntut penambahan anggaran jaring pengaman sosial menyusul laporan kemiskinan yang meningkat.",
        "condition": lambda s: s['welfare_index'] < 45.0,
        "choices": {
            "Penuhi Sebagian Tuntutan": {"treasury": -35.0, "welfare_index": 8.0, "happiness": 5.0},
            "Tolak, Anggaran Sudah Ketat": {"opposition_strength": 7.0, "happiness": -5.0},
        },
    },
    "police_reform_demand": {
        "title": "Tuntutan Reformasi Kepolisian",
        "description": "Insiden kekerasan aparat memicu tuntutan reformasi menyeluruh terhadap institusi keamanan.",
        "condition": lambda s: s['public_safety_index'] < 40.0,
        "choices": {
            "Reformasi Menyeluruh": {"treasury": -30.0, "public_safety_index": 8.0, "corruption_index": -5.0},
            "Bela Institusi yang Ada": {"opposition_strength": 8.0, "happiness": -8.0},
        },
    },

    # --- Politik: koalisi, korupsi, diplomasi, dan tekanan oposisi. ---
    "coalition_partner_threat": {
        "title": "Partai Koalisi Ancam Keluar",
        "description": "Salah satu partai koalisi kecil mengancam menarik dukungan kecuali diberi jatah kursi menteri tambahan.",
        "condition": lambda s: s['coalition_support'] < 30.0,
        "choices": {
            "Beri Konsesi Kursi Menteri": {"treasury": -20.0, "coalition_support": 12.0, "corruption_index": 5.0},
            "Biarkan Mereka Pergi": {"coalition_support": -10.0, "opposition_strength": 8.0},
        },
    },
    "anti_corruption_probe": {
        "title": "Investigasi Anti-Korupsi Menyasar Lingkaran Dalam",
        "description": "Lembaga anti-korupsi membuka investigasi terhadap beberapa tokoh dekat pemerintahan Anda.",
        "condition": lambda s: s['corruption_index'] > 50.0,
        "choices": {
            "Kooperatif Penuh": {"corruption_index": -15.0, "treasury": -15.0, "happiness": 6.0},
            "Halangi Investigasi": {"corruption_index": 10.0, "opposition_strength": 12.0},
        },
    },
    "state_visit_invitation": {
        "title": "Undangan Kunjungan Kenegaraan",
        "description": "Kepala negara sahabat mengundang kunjungan resmi untuk mempererat hubungan bilateral.",
        "condition": lambda s: True,
        "choices": {
            "Terima Kunjungan": {"treasury": -10.0, "foreign_relations": 10.0},
            "Tolak, Fokus Domestik": {"happiness": 3.0},
        },
    },
    "referendum_proposal": {
        "title": "Oposisi Mengusulkan Referendum",
        "description": "Oposisi menuntut referendum langsung atas arah kebijakan pemerintah, mengklaim mewakili suara rakyat.",
        "condition": lambda s: s['opposition_strength'] > 55.0,
        "choices": {
            "Setujui Referendum": {"opposition_strength": -8.0, "coalition_support": -5.0},
            "Tolak Usulan": {"opposition_strength": 10.0, "happiness": -6.0},
        },
    },

    # --- Ekonomi Global: inflasi, kepercayaan investor, perdagangan, ketimpangan. ---
    "commodity_price_spike": {
        "title": "Lonjakan Harga Komoditas Global",
        "description": "Gejolak pasar komoditas dunia mendorong kenaikan harga barang kebutuhan pokok secara tajam.",
        "condition": lambda s: True,
        "choices": {
            "Subsidi Harga untuk Rakyat": {"treasury": -30.0, "inflation_rate": -0.008, "happiness": 5.0},
            "Biarkan Pasar Menyesuaikan": {"inflation_rate": 0.01, "happiness": -6.0},
        },
    },
    "capital_flight_risk": {
        "title": "Ancaman Pelarian Modal Asing",
        "description": "Investor asing mulai menarik dana keluar akibat rendahnya kepercayaan terhadap stabilitas ekonomi.",
        "condition": lambda s: s['investor_confidence'] < 40.0,
        "choices": {
            "Tawarkan Insentif Pajak Investasi": {"treasury": -25.0, "investor_confidence": 10.0},
            "Biarkan Terjadi": {"investor_confidence": -8.0, "treasury": -15.0},
        },
    },
    "trade_bloc_proposal": {
        "title": "Proposal Bergabung Blok Dagang Regional",
        "description": "Sebuah blok dagang regional menawarkan keanggotaan dengan janji akses pasar yang lebih luas.",
        "condition": lambda s: s['trade_balance'] < 0.0,
        "choices": {
            "Bergabung dengan Blok Dagang": {"treasury": -20.0, "trade_balance": 15.0, "foreign_relations": 8.0},
            "Tetap Independen": {"foreign_relations": -3.0},
        },
    },
    "inequality_protests": {
        "title": "Ketimpangan Ekonomi Memicu Gelombang Protes",
        "description": "Laporan ketimpangan ekonomi yang melebar memicu demonstrasi menuntut redistribusi kekayaan.",
        "condition": lambda s: s['inequality_index'] > 65.0,
        "choices": {
            "Umumkan Reformasi Pajak Progresif": {"inequality_index": -10.0, "treasury": -15.0, "happiness": 6.0},
            "Tolak Tuntutan Reformasi": {"opposition_strength": 10.0, "happiness": -8.0},
        },
    },
}

# Static "what to fix" tips shown under News Feed / Year Review entries.
# Keyed by the exact (mostly-static) event title strings logged throughout
# engine.py/ledger_db.py. Crisis lifecycle events are matched by prefix
# instead, since their titles are dynamic ("CRISIS START: <name>") - the
# advice there just reuses that crisis's own requirement_desc, already
# phrased as "what to change" to solve it.
EVENT_ADVICE_MAP = {
    "Debt Accumulation": "Naikkan salah satu bracket pajak atau kurangi belanja diskresi untuk menekan defisit sebelum bunga utang membengkak.",
    "Widespread Protests": "Naikkan Anggaran Kesejahteraan Sosial atau turunkan Pajak Kelas Rendah untuk memulihkan happiness.",
    "Korupsi Merajalela": "Hentikan aksi Suap Politisi - Indeks Korupsi hanya meluruh dengan sendirinya jika tidak terus ditambah.",
    "Momentum Oposisi Meningkat": "Sesuaikan kebijakan agar lebih dekat dengan ideologi partai Anda sendiri, atau redakan lewat Negosiasi Dukungan Koalisi.",
    "Oposisi di Ambang Kekuatan Penuh": "Segera redakan Kekuatan Oposisi lewat Suap Politisi atau Negosiasi Dukungan Koalisi sebelum memicu Mosi Tidak Percaya.",
    "Pemilu: Menang Tipis": "Naikkan happiness atau tekan Kekuatan Oposisi sebelum periode pemilu 5 tahun berikutnya.",
    "Brain Drain Warning": "Turunkan Pajak Kelas Atas di bawah 40% untuk menghentikan emigrasi kelompok kaya.",
    "Talent Exodus": "Turunkan Pajak Kelas Atas dan naikkan Anggaran Kesejahteraan Sosial untuk meredam krisis Brain Drain.",
    "Krisis Pendidikan Akut": "Naikkan Anggaran Pendidikan untuk memulihkan Education Index.",
    "Sistem Kesehatan Kolaps": "Naikkan Anggaran Kesehatan untuk memulihkan Healthcare Index.",
    "Pengangguran Massal": "Turunkan Upah Minimum atau naikkan Anggaran Infrastruktur untuk mendorong penyerapan tenaga kerja.",
    "Kriminalitas Meningkat": "Naikkan Anggaran Keamanan & Pertahanan untuk menekan tingkat kriminalitas.",
    "APBN Dipaksakan lewat Dekrit": "Revisi anggaran agar sesuai batas defisit legal, atau redakan Kekuatan Oposisi lebih dulu lewat Negosiasi Koalisi agar tidak perlu memaksakan lewat dekrit lagi.",
    "EVENT: Global Recession": "Pertimbangkan menahan belanja diskresi atau perkuat Perjanjian Dagang untuk meredam dampak resesi global.",
    "EVENT: Cyber Ransom Attack": "Naikkan Anggaran Keamanan atau Infrastruktur untuk memperkuat pertahanan digital negara.",
    "EVENT: Bencana Alam": "Naikkan Anggaran Infrastruktur untuk mempercepat pemulihan pasca-bencana.",
    "Inflasi Tinggi": "Turunkan Pajak Impor atau kendalikan kenaikan Upah Minimum untuk meredam inflasi; hindari menumpuk utang berlebihan.",
}

def get_event_advice(ev, crisis_requirements=None):
    """
    Returns a short actionable "what to fix" tip for a logged event, or None
    if the event is purely positive/informational and has nothing to fix.
    crisis_requirements: optional {crisis_name: requirement_desc} dict (e.g.
    built from get_crises()) so crisis-lifecycle events can surface that
    crisis's own win condition as the concrete fix.
    """
    title = ev['title']
    crisis_requirements = crisis_requirements or {}

    for prefix in ("CRISIS START:", "Crisis Alert:", "CRISIS FAILED:"):
        if title.startswith(prefix):
            crisis_name = title.split(":", 1)[1].strip()
            return crisis_requirements.get(
                crisis_name,
                "Sesuaikan alokasi anggaran agar memenuhi syarat penyelesaian krisis ini."
            )

    # Progress met / crisis solved / positive shocks - nothing to fix
    if title.startswith("Crisis Progress:") or title.startswith("CRISIS SOLVED:"):
        return None
    if title in ("EVENT: Resource Market Boom", "EVENT: AI Core Breakthrough", "EVENT: Investasi Asing Mengalir"):
        return None

    return EVENT_ADVICE_MAP.get(title)

# Field metadata used to turn a raw effects dict (as stored in RANDOM_EVENTS
# choices / minister advice) into a human-readable consequence summary, so a
# pending decision shows player what's actually at stake instead of a blind
# choice between two labels.
EFFECT_FIELD_META = {
    'treasury': {'icon': '💰', 'label': 'Treasury', 'is_currency': True},
    'gdp': {'icon': '📈', 'label': 'GDP', 'is_currency': True},
    'happiness': {'icon': '😊', 'label': 'Happiness', 'unit': '%'},
    'opposition_strength': {'icon': '🎗️', 'label': 'Oposisi', 'unit': '%'},
    'corruption_index': {'icon': '🕵️', 'label': 'Korupsi', 'unit': '%'},
    'infrastructure': {'icon': '🏗️', 'label': 'Infrastruktur', 'unit': '%'},
    'health_index': {'icon': '🏥', 'label': 'Kesehatan', 'unit': '%'},
    'education_index': {'icon': '🎓', 'label': 'Pendidikan', 'unit': '%'},
    'crime_rate': {'icon': '🚔', 'label': 'Kriminalitas', 'unit': '%', 'scale': 100},
    'foreign_relations': {'icon': '🌐', 'label': 'Hubungan LN', 'unit': '%'},
    'inflation_rate': {'icon': '💹', 'label': 'Inflasi', 'unit': '%', 'scale': 100},
    'welfare_index': {'icon': '🤝', 'label': 'Welfare Index', 'unit': '%'},
    'public_safety_index': {'icon': '🚨', 'label': 'Public Safety Index', 'unit': '%'},
    'coalition_support': {'icon': '🏛️', 'label': 'Koalisi', 'unit': '%'},
    'trade_balance': {'icon': '🚢', 'label': 'Neraca Dagang', 'is_currency': True},
    'investor_confidence': {'icon': '💼', 'label': 'Kepercayaan Investor', 'unit': '%'},
    'inequality_index': {'icon': '⚖️', 'label': 'Ketimpangan', 'unit': '%'},
}

def format_effects_summary(effects, country_name):
    """Turns {'treasury': 150.0, 'happiness': -15.0} into a one-line
    '💰 Treasury +Rp2,370.0T · 😊 Happiness -15.0%' consequence summary, or
    None if there are no nonzero effects to show."""
    parts = []
    for field, delta in effects.items():
        if not delta:
            continue
        meta = EFFECT_FIELD_META.get(field)
        if not meta:
            continue
        if meta.get('is_currency'):
            text = format_currency(delta, country_name, decimals=1)
            if delta >= 0:
                text = f"+{text}"
            parts.append(f"{meta['icon']} {meta['label']} {text}")
        else:
            val = delta * meta.get('scale', 1)
            sign = '+' if val >= 0 else ''
            parts.append(f"{meta['icon']} {meta['label']} {sign}{val:.1f}{meta['unit']}")
    return " · ".join(parts) if parts else None

def get_connection(db_path=DB_PATH):
    return sqlite3.connect(db_path)

def _schema_is_stale(cursor):
    """
    Detects leftover tables from an older data model (e.g. a single
    'population'/'tax_rate' column instead of per-class cohorts/brackets,
    or a 'games' table without 'country_name'). CREATE TABLE IF NOT EXISTS
    never updates an existing table, so without this check old databases
    would keep the incompatible schema forever and every game_id in them
    would fail with "no such column" errors.
    """
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('games','nation_history','pending_events')")
    existing_tables = {row[0] for row in cursor.fetchall()}

    if 'games' in existing_tables:
        cursor.execute("PRAGMA table_info(games)")
        cols = {row[1] for row in cursor.fetchall()}
        if not {'country_name', 'party_name', 'sandbox_mode'}.issubset(cols):
            return True

    if 'nation_history' in existing_tables:
        cursor.execute("PRAGMA table_info(nation_history)")
        cols = {row[1] for row in cursor.fetchall()}
        if not {'pop_low', 'pop_mid', 'pop_high', 'pop_elder', 'tax_low', 'tax_mid', 'tax_high', 'opposition_strength', 'corruption_index', 'crime_rate', 'min_wage', 'export_tariff', 'import_tariff', 'foreign_relations', 'coalition_support', 'happiness_low', 'happiness_mid', 'happiness_high', 'happiness_elder', 'inflation_rate', 'trade_balance', 'inequality_index', 'investor_confidence', 'welfare_index', 'public_safety_index'}.issubset(cols):
            return True

    if 'pending_events' in existing_tables:
        cursor.execute("PRAGMA table_info(pending_events)")
        cols = {row[1] for row in cursor.fetchall()}
        if 'event_data' not in cols:
            return True

    return False

def init_db(db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if _schema_is_stale(cursor):
        # Drop every table, not just games/nation_history - cabinet and
        # pending_events reference game_id too, and games.game_id resets
        # via AUTOINCREMENT on recreation, so leaving them behind risks a
        # brand new game silently inheriting another old game's rows.
        for table in ('pending_events', 'cabinet', 'crises', 'turn_events', 'nation_history', 'games'):
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()

    # 1. Games Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS games (
        game_id INTEGER PRIMARY KEY AUTOINCREMENT,
        nation_name TEXT NOT NULL,
        country_name TEXT NOT NULL,
        party_name TEXT NOT NULL,
        difficulty TEXT DEFAULT 'Medium',
        sandbox_mode INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # 2. Nation History Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS nation_history (
        history_id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        turn_year INTEGER NOT NULL,
        
        -- States
        treasury REAL NOT NULL,
        gdp REAL NOT NULL,
        pop_low INTEGER NOT NULL,
        pop_mid INTEGER NOT NULL,
        pop_high INTEGER NOT NULL,
        pop_elder INTEGER NOT NULL,
        employment_rate REAL NOT NULL,
        crime_rate REAL NOT NULL,
        happiness REAL NOT NULL,
        happiness_low REAL NOT NULL,
        happiness_mid REAL NOT NULL,
        happiness_high REAL NOT NULL,
        happiness_elder REAL NOT NULL,
        education_index REAL NOT NULL,
        health_index REAL NOT NULL,
        infrastructure REAL NOT NULL,
        opposition_strength REAL NOT NULL,
        corruption_index REAL NOT NULL,
        foreign_relations REAL NOT NULL,
        coalition_support REAL NOT NULL,
        inflation_rate REAL NOT NULL,
        trade_balance REAL NOT NULL,
        inequality_index REAL NOT NULL,
        investor_confidence REAL NOT NULL,
        welfare_index REAL NOT NULL,
        public_safety_index REAL NOT NULL,

        -- Inputs
        tax_low REAL NOT NULL,
        tax_mid REAL NOT NULL,
        tax_high REAL NOT NULL,
        budget_education REAL NOT NULL,
        budget_health REAL NOT NULL,
        budget_infrastructure REAL NOT NULL,
        budget_welfare REAL NOT NULL,
        budget_security REAL NOT NULL,
        min_wage REAL NOT NULL,
        export_tariff REAL NOT NULL,
        import_tariff REAL NOT NULL,

        FOREIGN KEY(game_id) REFERENCES games(game_id)
    )
    """)

    # 3. Turn Events Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS turn_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        turn_year INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        impact_json TEXT,
        FOREIGN KEY(game_id) REFERENCES games(game_id)
    )
    """)
    
    # 4. Crises Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS crises (
        crisis_id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        start_year INTEGER NOT NULL,
        duration_turns INTEGER NOT NULL,
        current_progress INTEGER DEFAULT 0,
        target_progress INTEGER NOT NULL,
        status TEXT DEFAULT 'INACTIVE',
        description TEXT NOT NULL,
        requirement_desc TEXT NOT NULL,
        FOREIGN KEY(game_id) REFERENCES games(game_id)
    )
    """)

    # 5. Cabinet Table - at most one advisor per position per game
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cabinet (
        cabinet_id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        position TEXT NOT NULL,
        advisor_name TEXT NOT NULL,
        tier TEXT NOT NULL,
        bonus_value REAL NOT NULL,
        salary REAL NOT NULL,
        hired_year INTEGER NOT NULL,
        FOREIGN KEY(game_id) REFERENCES games(game_id)
    )
    """)

    # 6. Pending Events - at most one unresolved narrative choice per game
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pending_events (
        pending_id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        event_key TEXT NOT NULL,
        turn_year INTEGER NOT NULL,
        event_data TEXT,
        FOREIGN KEY(game_id) REFERENCES games(game_id)
    )
    """)

    conn.commit()
    conn.close()

def create_new_game(nation_name, country_name, difficulty, party_name, db_path=DB_PATH):
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Insert new game
    cursor.execute("INSERT INTO games (nation_name, country_name, party_name, difficulty) VALUES (?, ?, ?, ?)",
                   (nation_name, country_name, party_name, difficulty))
    game_id = cursor.lastrowid

    # Lookup starting preset
    preset = COUNTRY_PRESETS.get(country_name, COUNTRY_PRESETS["Indonesia"])
    initial_year = 0  # turn index 0 = Year 2026 Q1, see get_calendar_label()

    diff_settings = DIFFICULTY_SETTINGS.get(difficulty, DIFFICULTY_SETTINGS["Medium"])
    funds_mult = diff_settings["starting_funds_mult"]
    gdp = round(preset["gdp"] * funds_mult, 2)
    if preset["treasury"] >= 0:
        treasury = round(preset["treasury"] * funds_mult, 2)
    else:
        treasury = round(preset["treasury"] / funds_mult, 2)  # worse difficulty deepens debt, not shrinks it

    # Starting budgets are quarterly amounts (a turn is now a quarter) - the
    # ratios still target the same annualized ~2%/1.5%/1.5%/1%/1% of GDP
    # split, just divided across 4 turns a year instead of committed in one.
    b_ed = round(gdp * 0.005, 2)
    b_hl = round(gdp * 0.00375, 2)
    b_inf = round(gdp * 0.00375, 2)
    b_welf = round(gdp * 0.0025, 2)
    b_sec = round(gdp * 0.0025, 2)

    cursor.execute("""
    INSERT INTO nation_history (
        game_id, turn_year, treasury, gdp, pop_low, pop_mid, pop_high, pop_elder,
        employment_rate, crime_rate, happiness, happiness_low, happiness_mid, happiness_high, happiness_elder,
        education_index, health_index, infrastructure, welfare_index, public_safety_index,
        opposition_strength, corruption_index,
        foreign_relations, coalition_support,
        inflation_rate, trade_balance, inequality_index, investor_confidence,
        tax_low, tax_mid, tax_high,
        budget_education, budget_health, budget_infrastructure, budget_welfare, budget_security,
        min_wage, export_tariff, import_tariff
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        game_id, initial_year,
        treasury,
        gdp,
        preset["pop_low"],
        preset["pop_mid"],
        preset["pop_high"],
        preset["pop_elder"],
        0.80,
        0.44,
        55.0,
        55.0,
        55.0,
        55.0,
        55.0,
        50.0,
        50.0,
        50.0,
        50.0, 50.0,
        15.0,
        0.0,
        50.0,
        0.0,
        0.005, 0.0, 40.0, 60.0,
        preset["tax_low"],
        preset["tax_mid"],
        preset["tax_high"],
        b_ed, b_hl, b_inf, b_welf, b_sec,
        20.0, 0.0, 0.0
    ))

    # Log initial info event
    opposition_party = get_opposition_party(party_name)
    cursor.execute("""
    INSERT INTO turn_events (game_id, turn_year, event_type, title, description, impact_json)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        game_id, initial_year, 'INFO', 'Inauguration Day',
        f'Welcome Minister! You are now managing the ledger of {country_name} ({nation_name}) as leader of {party_name}. Stabilize the debt, balance the social brackets, and survive.',
        json.dumps({})
    ))

    cursor.execute("""
    INSERT INTO turn_events (game_id, turn_year, event_type, title, description, impact_json)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        game_id, initial_year, 'SOCIAL', 'Oposisi Terbentuk',
        f'{opposition_party} kini menjadi partai oposisi resmi dan akan menantang setiap kebijakan Anda sepanjang masa pemerintahan.',
        json.dumps({})
    ))

    # Seed crises as INACTIVE with no start_year yet - engine.py triggers each
    # one dynamically once its matching economic/social indicator crosses a
    # critical level (see simulate_turn's "Dynamic Crisis Triggering" section),
    # instead of a fixed calendar year. start_year is filled in at that point.
    # duration_turns/target_progress are x4 their old per-year values (a turn
    # is now a quarter), and every GDP-ratio threshold quoted in the text is
    # /4 to match - budget amounts are quarterly now, so a quarterly figure
    # needs a quarterly-sized bar to still represent "the same annual effort".
    crises_data = [
        (game_id, "The Infrastructure Bottleneck", 0, 12, 0, 8, 'INACTIVE',
         "Rapid industrial growth has overloaded the nation's power grids and road systems.",
         "Keep Infrastructure budget at or above 0.375% of your quarterly GDP for 8 quarters during the crisis duration."),

        (game_id, "The Public Health Epidemic", 0, 16, 0, 12, 'INACTIVE',
         "A highly contagious virus is spreading due to public health underfunding.",
         "Keep Healthcare budget at or above 20% of your total budget AND low-bracket tax rate at or above 8% for 12 quarters to build facilities and fund vaccines."),

        (game_id, "The Brain Drain Crisis", 0, 16, 0, 12, 'INACTIVE',
         "Your highly educated citizens are fleeing the nation due to high tax rates on the high-income bracket.",
         "Reduce Tax Rate on High-Income to below 20% AND keep Social Welfare budget at or above 10% of total spending for 12 quarters to retain elite talent."),

        (game_id, "The Demographic Cliff", 0, 20, 0, 12, 'INACTIVE',
         "A record drop in birth rates has caused a severe aging crisis, putting strain on active workers.",
         "Keep Welfare budget above 0.75% of your quarterly GDP (family subsidies) OR keep combined Security & Infrastructure spending at 15% of total budget (to support high-skill immigration) for 12 quarters."),

        (game_id, "The Carbon Transition Tariff", 0, 16, 0, 12, 'INACTIVE',
         "Global partners threaten trade sanctions on the country's carbon emissions unless clean production targets are met.",
         "Keep Infrastructure budget above 0.5% of your quarterly GDP (green grid) AND Security budget above 0.125% of your quarterly GDP (emissions enforcement) for 12 quarters."),

        (game_id, "Krisis Utang Nasional", 0, 16, 0, 12, 'INACTIVE',
         "Investor internasional mulai gelisah - rasio utang terhadap GDP negara Anda melewati batas aman, memicu spekulasi soal kemampuan bayar.",
         "Turunkan total belanja (Pendidikan+Kesehatan+Infrastruktur+Kesejahteraan+Keamanan) ke 2% atau kurang dari GDP kuartalan selama 12 kuartal untuk memulihkan kepercayaan kreditor."),

        (game_id, "Gelombang Kriminalitas", 0, 16, 0, 12, 'INACTIVE',
         "Lemahnya penegakan hukum memicu lonjakan kejahatan yang menekan produktivitas dan menakuti investor.",
         "Pertahankan anggaran Keamanan di atas 0.5% dari GDP kuartalan selama 12 kuartal untuk memulihkan ketertiban."),
    ]

    # Hard shortens crisis windows, Easy lengthens them - never below
    # target_progress, or the crisis would be unwinnable even with perfect play.
    duration_delta = diff_settings["crisis_duration_delta"]
    crises_data = [
        (gid, name, start_year, max(target, duration + duration_delta), progress, target, status, desc, req)
        for (gid, name, start_year, duration, progress, target, status, desc, req) in crises_data
    ]

    cursor.executemany("""
    INSERT INTO crises (game_id, name, start_year, duration_turns, current_progress, target_progress, status, description, requirement_desc)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, crises_data)
    
    conn.commit()
    conn.close()
    return game_id

def get_latest_turn(game_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT history_id, turn_year, treasury, gdp, pop_low, pop_mid, pop_high, pop_elder,
               employment_rate, crime_rate, happiness, happiness_low, happiness_mid, happiness_high, happiness_elder,
               education_index, health_index, infrastructure, welfare_index, public_safety_index,
               opposition_strength, corruption_index,
               foreign_relations, coalition_support,
               inflation_rate, trade_balance, inequality_index, investor_confidence,
               tax_low, tax_mid, tax_high,
               budget_education, budget_health, budget_infrastructure, budget_welfare, budget_security,
               min_wage, export_tariff, import_tariff
        FROM nation_history
        WHERE game_id = ?
        ORDER BY turn_year DESC LIMIT 1
    """, (game_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        columns = [
            'history_id', 'turn_year', 'treasury', 'gdp', 'pop_low', 'pop_mid', 'pop_high', 'pop_elder',
            'employment_rate', 'crime_rate', 'happiness', 'happiness_low', 'happiness_mid', 'happiness_high', 'happiness_elder',
            'education_index', 'health_index', 'infrastructure', 'welfare_index', 'public_safety_index',
            'opposition_strength', 'corruption_index',
            'foreign_relations', 'coalition_support',
            'inflation_rate', 'trade_balance', 'inequality_index', 'investor_confidence',
            'tax_low', 'tax_mid', 'tax_high',
            'budget_education', 'budget_health', 'budget_infrastructure', 'budget_welfare', 'budget_security',
            'min_wage', 'export_tariff', 'import_tariff'
        ]
        return dict(zip(columns, row))
    return None

def get_history(game_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT turn_year, treasury, gdp, (pop_low + pop_mid + pop_high + pop_elder) as population,
               employment_rate, happiness, education_index, health_index, infrastructure,
               tax_low, tax_mid, tax_high, pop_low, pop_mid, pop_high, pop_elder, opposition_strength, corruption_index, crime_rate,
               happiness_low, happiness_mid, happiness_high, happiness_elder,
               inflation_rate, trade_balance, inequality_index, investor_confidence,
               welfare_index, public_safety_index
        FROM nation_history
        WHERE game_id = ?
        ORDER BY turn_year ASC
    """, (game_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def save_turn_state(game_id, data, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO nation_history (
        game_id, turn_year, treasury, gdp, pop_low, pop_mid, pop_high, pop_elder,
        employment_rate, crime_rate, happiness, happiness_low, happiness_mid, happiness_high, happiness_elder,
        education_index, health_index, infrastructure, welfare_index, public_safety_index,
        opposition_strength, corruption_index,
        foreign_relations, coalition_support,
        inflation_rate, trade_balance, inequality_index, investor_confidence,
        tax_low, tax_mid, tax_high,
        budget_education, budget_health, budget_infrastructure, budget_welfare, budget_security,
        min_wage, export_tariff, import_tariff
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        game_id, data['turn_year'], data['treasury'], data['gdp'],
        data['pop_low'], data['pop_mid'], data['pop_high'], data['pop_elder'],
        data['employment_rate'], data['crime_rate'], data['happiness'],
        data['happiness_low'], data['happiness_mid'], data['happiness_high'], data['happiness_elder'],
        data['education_index'],
        data['health_index'], data['infrastructure'], data['welfare_index'], data['public_safety_index'],
        data['opposition_strength'], data['corruption_index'],
        data['foreign_relations'], data['coalition_support'],
        data['inflation_rate'], data['trade_balance'], data['inequality_index'], data['investor_confidence'],
        data['tax_low'], data['tax_mid'], data['tax_high'],
        data['budget_education'], data['budget_health'], data['budget_infrastructure'],
        data['budget_welfare'], data['budget_security'],
        data['min_wage'], data['export_tariff'], data['import_tariff']
    ))
    conn.commit()
    conn.close()

def log_event(game_id, turn_year, event_type, title, description, impact_dict=None, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    impact_json = json.dumps(impact_dict if impact_dict else {})
    cursor.execute("""
    INSERT INTO turn_events (game_id, turn_year, event_type, title, description, impact_json)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (game_id, turn_year, event_type, title, description, impact_json))
    conn.commit()
    conn.close()

def get_events(game_id, turn_year=None, turn_year_from=None, turn_year_to=None, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    if turn_year is not None:
        cursor.execute("""
            SELECT event_id, turn_year, event_type, title, description, impact_json
            FROM turn_events
            WHERE game_id = ? AND turn_year = ?
            ORDER BY event_id DESC
        """, (game_id, turn_year))
    elif turn_year_from is not None and turn_year_to is not None:
        cursor.execute("""
            SELECT event_id, turn_year, event_type, title, description, impact_json
            FROM turn_events
            WHERE game_id = ? AND turn_year BETWEEN ? AND ?
            ORDER BY turn_year ASC, event_id DESC
        """, (game_id, turn_year_from, turn_year_to))
    else:
        cursor.execute("""
            SELECT event_id, turn_year, event_type, title, description, impact_json
            FROM turn_events
            WHERE game_id = ?
            ORDER BY turn_year DESC, event_id DESC
        """, (game_id,))
    rows = cursor.fetchall()
    conn.close()
    
    events = []
    for r in rows:
        events.append({
            'event_id': r[0],
            'turn_year': r[1],
            'event_type': r[2],
            'title': r[3],
            'description': r[4],
            'impact': json.loads(r[5]) if r[5] else {}
        })
    return events

def get_crises(game_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT crisis_id, name, start_year, duration_turns, current_progress, target_progress, status, description, requirement_desc
        FROM crises
        WHERE game_id = ?
    """, (game_id,))
    rows = cursor.fetchall()
    conn.close()
    
    crises = []
    columns = ['crisis_id', 'name', 'start_year', 'duration_turns', 'current_progress', 'target_progress', 'status', 'description', 'requirement_desc']
    for r in rows:
        crises.append(dict(zip(columns, r)))
    return crises

def update_crisis_state(crisis_id, current_progress, status, start_year=None, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    if start_year is not None:
        cursor.execute("""
            UPDATE crises
            SET current_progress = ?, status = ?, start_year = ?
            WHERE crisis_id = ?
        """, (current_progress, status, start_year, crisis_id))
    else:
        cursor.execute("""
            UPDATE crises
            SET current_progress = ?, status = ?
            WHERE crisis_id = ?
        """, (current_progress, status, crisis_id))
    conn.commit()
    conn.close()

def list_games(limit=10, db_path=DB_PATH):
    """
    Most recently created games, for the "Continue Administration" picker on
    the start screen - lets a player resume after their browser session gets
    dropped (e.g. the computer sleeps and the WebSocket connection resets,
    which loses st.session_state.game_id even though the game's data was
    never actually lost from this SQLite file).
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT g.game_id, g.nation_name, g.country_name, g.party_name, g.difficulty,
               (SELECT MAX(turn_year) FROM nation_history WHERE game_id = g.game_id) as latest_turn
        FROM games g
        ORDER BY g.game_id DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    columns = ['game_id', 'nation_name', 'country_name', 'party_name', 'difficulty', 'latest_turn']
    return [dict(zip(columns, r)) for r in rows if r[5] is not None]

def get_nation_name(game_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT nation_name FROM games WHERE game_id = ?", (game_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "Regime I"

def get_country_name(game_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT country_name FROM games WHERE game_id = ?", (game_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "Indonesia"

def get_party_name(game_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT party_name FROM games WHERE game_id = ?", (game_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] else next(iter(PARTY_PRESETS))

def get_sandbox_mode(game_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT sandbox_mode FROM games WHERE game_id = ?", (game_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row[0]) if row else False

def set_sandbox_mode(game_id, enabled, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE games SET sandbox_mode = ? WHERE game_id = ?", (1 if enabled else 0, game_id))
    conn.commit()
    conn.close()

def apply_bribe(game_id, db_path=DB_PATH):
    """
    Spends $100B from the treasury of the current (not-yet-ended) turn to
    buy off opposition figures, cutting Opposition Strength by 10 points.
    Updates the latest row in place instead of inserting a new turn, since
    this is an emergency action, not a full fiscal year.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT history_id, turn_year, treasury, opposition_strength, corruption_index
        FROM nation_history WHERE game_id = ? ORDER BY turn_year DESC LIMIT 1
    """, (game_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    history_id, turn_year, treasury, opposition_strength, corruption_index = row
    new_treasury = treasury - 100.0
    new_opposition = max(0.0, opposition_strength - 10.0)
    new_corruption = min(100.0, corruption_index + 8.0)

    cursor.execute("""
        UPDATE nation_history SET treasury = ?, opposition_strength = ?, corruption_index = ? WHERE history_id = ?
    """, (new_treasury, new_opposition, new_corruption, history_id))
    conn.commit()
    conn.close()

    log_event(
        game_id, turn_year, 'SOCIAL', "Suap Politisi",
        f"Anda menyuap tokoh-tokoh oposisi senilai $100B untuk meredam ketegangan politik. Kekuatan oposisi turun menjadi {new_opposition:.1f}%, namun Indeks Korupsi naik menjadi {new_corruption:.1f}%.",
        db_path=db_path
    )
    return {'treasury': new_treasury, 'opposition_strength': new_opposition, 'corruption_index': new_corruption}

def apply_forced_budget_penalty(game_id, db_path=DB_PATH):
    """
    Political cost of pushing a budget through by decree after parliament
    (i.e. the Opposition) contested it - either for breaching the legal
    deficit ceiling or simply because the Opposition is too strong to let it
    pass cleanly. Applied to the turn that was just created by simulate_turn.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT history_id, turn_year, opposition_strength, corruption_index
        FROM nation_history WHERE game_id = ? ORDER BY turn_year DESC LIMIT 1
    """, (game_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    history_id, turn_year, opposition_strength, corruption_index = row
    new_opposition = min(100.0, opposition_strength + 12.0)
    new_corruption = min(100.0, corruption_index + 10.0)

    cursor.execute("""
        UPDATE nation_history SET opposition_strength = ?, corruption_index = ? WHERE history_id = ?
    """, (new_opposition, new_corruption, history_id))
    conn.commit()
    conn.close()

    log_event(
        game_id, turn_year, 'CRISIS', "APBN Dipaksakan lewat Dekrit",
        f"Anda memaksakan pengesahan APBN tanpa persetujuan parlemen. Kekuatan Oposisi naik menjadi {new_opposition:.1f}% dan Indeks Korupsi naik menjadi {new_corruption:.1f}%.",
        db_path=db_path
    )
    return {'opposition_strength': new_opposition, 'corruption_index': new_corruption}

def apply_bond_issuance(game_id, amount_usd, db_path=DB_PATH):
    """
    Issues a sovereign bond for immediate cash, added directly to the current
    (not-yet-ended) turn's treasury - same in-place mutation pattern as
    apply_bribe. The added debt (or reduced surplus) then costs interest every
    subsequent turn via engine.py's normal debt-interest formula, scaled by
    whatever credit rating is in effect at that time.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT history_id, turn_year, treasury FROM nation_history
        WHERE game_id = ? ORDER BY turn_year DESC LIMIT 1
    """, (game_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    history_id, turn_year, treasury = row
    new_treasury = treasury + amount_usd

    cursor.execute("UPDATE nation_history SET treasury = ? WHERE history_id = ?", (new_treasury, history_id))
    conn.commit()
    conn.close()

    log_event(
        game_id, turn_year, 'ECONOMIC', "Obligasi Negara Diterbitkan",
        f"Pemerintah menerbitkan obligasi senilai ${amount_usd:.1f}B untuk menambah kas negara. Beban bunga tahun-tahun mendatang akan meningkat mengikuti peringkat kredit saat ini.",
        db_path=db_path
    )
    return {'treasury': new_treasury}

def apply_trade_agreement(game_id, db_path=DB_PATH):
    """
    Spends a small diplomatic negotiation budget to strengthen a trade
    agreement, raising Foreign Relations. Higher relations give a small GDP
    growth bonus in engine.py; letting relations collapse instead risks the
    "trade_war" narrative event.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT history_id, turn_year, treasury, foreign_relations FROM nation_history
        WHERE game_id = ? ORDER BY turn_year DESC LIMIT 1
    """, (game_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    history_id, turn_year, treasury, foreign_relations = row
    new_treasury = treasury - 15.0
    new_relations = min(100.0, foreign_relations + 15.0)

    cursor.execute("UPDATE nation_history SET treasury = ?, foreign_relations = ? WHERE history_id = ?",
                   (new_treasury, new_relations, history_id))
    conn.commit()
    conn.close()

    log_event(
        game_id, turn_year, 'ECONOMIC', "Perjanjian Dagang Diperkuat",
        f"Delegasi diplomatik memperkuat perjanjian dagang dengan mitra internasional, menghabiskan $15.0B biaya negosiasi. Hubungan Luar Negeri naik menjadi {new_relations:.1f}%.",
        db_path=db_path
    )
    return {'treasury': new_treasury, 'foreign_relations': new_relations}

def apply_coalition_negotiation(game_id, db_path=DB_PATH):
    """
    Spends political capital to buy support from minor parties in parliament,
    raising Coalition Support. app.py offsets Opposition Strength by a
    fraction of this score when checking whether the Opposition contests the
    APBN - it does NOT affect the harder no-confidence/election thresholds.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT history_id, turn_year, treasury, coalition_support FROM nation_history
        WHERE game_id = ? ORDER BY turn_year DESC LIMIT 1
    """, (game_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    history_id, turn_year, treasury, coalition_support = row
    new_treasury = treasury - 25.0
    new_coalition = min(100.0, coalition_support + 20.0)

    cursor.execute("UPDATE nation_history SET treasury = ?, coalition_support = ? WHERE history_id = ?",
                   (new_treasury, new_coalition, history_id))
    conn.commit()
    conn.close()

    log_event(
        game_id, turn_year, 'SOCIAL', "Koalisi Parlemen Diperkuat",
        f"Anda menegosiasikan dukungan partai-partai kecil di parlemen, menghabiskan $25.0B dana politik. Dukungan Koalisi naik menjadi {new_coalition:.1f}%.",
        db_path=db_path
    )
    return {'treasury': new_treasury, 'coalition_support': new_coalition}

def get_cabinet(game_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT cabinet_id, position, advisor_name, tier, bonus_value, salary, hired_year
        FROM cabinet WHERE game_id = ?
    """, (game_id,))
    rows = cursor.fetchall()
    conn.close()
    columns = ['cabinet_id', 'position', 'advisor_name', 'tier', 'bonus_value', 'salary', 'hired_year']
    return [dict(zip(columns, r)) for r in rows]

def get_adjusted_tier_info(game_id, tier, db_path=DB_PATH):
    """Advisor tier cost/salary after applying this game's difficulty multiplier - what the UI should display before hiring."""
    cost_mult = get_difficulty_settings(game_id, db_path)["minister_cost_mult"]
    base = ADVISOR_TIERS[tier]
    return {
        'bonus': base['bonus'],
        'hire_cost': round(base['hire_cost'] * cost_mult, 2),
        'salary': round(base['salary'] * cost_mult, 2),
    }

def hire_advisor(game_id, position, tier, advisor_name, db_path=DB_PATH):
    """
    Hires (or replaces) the advisor in the given cabinet position, paying the
    tier's hire_cost immediately from the current turn's treasury. The
    ongoing salary is deducted every subsequent turn by engine.py. advisor_name
    is picked by the player from get_advisor_name_choices(), not randomized.
    """
    tier_info = ADVISOR_TIERS[tier]
    cost_mult = get_difficulty_settings(game_id, db_path)["minister_cost_mult"]
    hire_cost = round(tier_info['hire_cost'] * cost_mult, 2)
    salary = round(tier_info['salary'] * cost_mult, 2)

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT history_id, turn_year, treasury FROM nation_history
        WHERE game_id = ? ORDER BY turn_year DESC LIMIT 1
    """, (game_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    history_id, turn_year, treasury = row
    new_treasury = treasury - hire_cost

    cursor.execute("DELETE FROM cabinet WHERE game_id = ? AND position = ?", (game_id, position))
    cursor.execute("""
        INSERT INTO cabinet (game_id, position, advisor_name, tier, bonus_value, salary, hired_year)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (game_id, position, advisor_name, tier, tier_info['bonus'], salary, turn_year))
    cursor.execute("UPDATE nation_history SET treasury = ? WHERE history_id = ?", (new_treasury, history_id))
    conn.commit()
    conn.close()

    log_event(
        game_id, turn_year, 'SOCIAL', f"Menteri Baru: {position}",
        f"{advisor_name} ({tier}) dilantik sebagai {position}, menghabiskan ${hire_cost:.1f}B dari kas negara untuk biaya pelantikan.",
        db_path=db_path
    )
    return {'advisor_name': advisor_name, 'treasury': new_treasury}

def fire_advisor(game_id, position, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cabinet WHERE game_id = ? AND position = ?", (game_id, position))
    conn.commit()
    conn.close()

def create_pending_event(game_id, event_key, turn_year, event_data=None, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO pending_events (game_id, event_key, turn_year, event_data) VALUES (?, ?, ?, ?)",
        (game_id, event_key, turn_year, json.dumps(event_data) if event_data is not None else None)
    )
    conn.commit()
    conn.close()

def get_pending_event(game_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT pending_id, event_key, turn_year, event_data FROM pending_events WHERE game_id = ? ORDER BY pending_id DESC LIMIT 1",
        (game_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            'pending_id': row[0], 'event_key': row[1], 'turn_year': row[2],
            'event_data': json.loads(row[3]) if row[3] else None
        }
    return None

def create_minister_advice_event(game_id, turn_year, db_path=DB_PATH):
    """
    Has a random hired minister volunteer policy advice targeting their
    domain's stat. Whether the advice is actually correct is rolled now
    (based on the minister's tier accuracy) and frozen into event_data, so
    the outcome doesn't change no matter when the player resolves it.
    """
    cabinet = get_cabinet(game_id, db_path)
    if not cabinet:
        return
    advisor = random.choice(cabinet)
    mapping = MINISTER_ADVICE_MAP.get(advisor['position'])
    if not mapping:
        return

    accuracy = ADVISOR_ACCURACY.get(advisor['tier'], 0.5)
    is_correct = random.random() < accuracy

    event_data = {
        "advisor_name": advisor['advisor_name'],
        "tier": advisor['tier'],
        "position": advisor['position'],
        "advice_text": mapping['advice_text'],
        "target_field": mapping['target_field'],
        "effect_magnitude": mapping['effect_magnitude'],
        "cost": MINISTER_ADVICE_COST,
        "is_correct": is_correct,
    }
    create_pending_event(game_id, "minister_advice", turn_year, event_data=event_data, db_path=db_path)

def resolve_pending_event(game_id, event_key, choice_label, db_path=DB_PATH):
    """
    Applies the chosen option's stat deltas to the current (not-yet-ended)
    turn's row in place - same pattern as apply_bribe/hire_advisor - then
    clears the pending decision so gameplay can continue.
    """
    if event_key == "minister_advice":
        pending = get_pending_event(game_id, db_path)
        data = pending['event_data'] if pending else {}
        effects = {}
        if choice_label == "Terima Saran":
            effects['treasury'] = -data.get('cost', MINISTER_ADVICE_COST)
            if data.get('is_correct'):
                effects[data['target_field']] = data['effect_magnitude']
            feedback = (
                f"Saran terbukti tepat sasaran — {data.get('target_field')} membaik."
                if data.get('is_correct') else
                "Sayangnya saran tersebut kurang tepat sasaran, dana yang dikeluarkan tidak memberikan dampak berarti."
            )
        else:
            feedback = "Anda memilih mengabaikan saran tersebut."
        event_title = f"Saran Menteri: {data.get('position', '')}"
        event_desc = f"{data.get('advisor_name', '')} ({data.get('tier', '')}) menyarankan: \"{data.get('advice_text', '')}\" {feedback}"
    else:
        effects = RANDOM_EVENTS[event_key]['choices'][choice_label]
        event_title = RANDOM_EVENTS[event_key]['title']
        event_desc = RANDOM_EVENTS[event_key]['description']

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT history_id, turn_year, treasury, gdp, happiness, opposition_strength,
               corruption_index, infrastructure, health_index, education_index, crime_rate, foreign_relations,
               inflation_rate, welfare_index, public_safety_index, coalition_support, trade_balance,
               investor_confidence, inequality_index
        FROM nation_history WHERE game_id = ? ORDER BY turn_year DESC LIMIT 1
    """, (game_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    (history_id, turn_year, treasury, gdp, happiness, opposition_strength,
     corruption_index, infrastructure, health_index, education_index, crime_rate, foreign_relations,
     inflation_rate, welfare_index, public_safety_index, coalition_support, trade_balance,
     investor_confidence, inequality_index) = row

    new_treasury = treasury + effects.get('treasury', 0.0)
    new_gdp = max(10.0, gdp + effects.get('gdp', 0.0))
    new_happiness = max(0.0, min(100.0, happiness + effects.get('happiness', 0.0)))
    new_opposition = max(0.0, min(100.0, opposition_strength + effects.get('opposition_strength', 0.0)))
    new_corruption = max(0.0, min(100.0, corruption_index + effects.get('corruption_index', 0.0)))
    new_infrastructure = max(0.0, min(100.0, infrastructure + effects.get('infrastructure', 0.0)))
    new_health = max(0.0, min(100.0, health_index + effects.get('health_index', 0.0)))
    new_education = max(0.0, min(100.0, education_index + effects.get('education_index', 0.0)))
    new_crime = max(0.0, min(1.0, crime_rate + effects.get('crime_rate', 0.0)))
    new_relations = max(0.0, min(100.0, foreign_relations + effects.get('foreign_relations', 0.0)))
    new_inflation = max(-0.01, min(0.06, inflation_rate + effects.get('inflation_rate', 0.0)))
    new_welfare = max(0.0, min(100.0, welfare_index + effects.get('welfare_index', 0.0)))
    new_safety = max(0.0, min(100.0, public_safety_index + effects.get('public_safety_index', 0.0)))
    new_coalition = max(0.0, min(100.0, coalition_support + effects.get('coalition_support', 0.0)))
    new_trade_balance = trade_balance + effects.get('trade_balance', 0.0)
    new_confidence = max(0.0, min(100.0, investor_confidence + effects.get('investor_confidence', 0.0)))
    new_inequality = max(0.0, min(100.0, inequality_index + effects.get('inequality_index', 0.0)))

    cursor.execute("""
        UPDATE nation_history
        SET treasury = ?, gdp = ?, happiness = ?, opposition_strength = ?,
            corruption_index = ?, infrastructure = ?, health_index = ?, education_index = ?, crime_rate = ?,
            foreign_relations = ?, inflation_rate = ?, welfare_index = ?, public_safety_index = ?,
            coalition_support = ?, trade_balance = ?, investor_confidence = ?, inequality_index = ?
        WHERE history_id = ?
    """, (new_treasury, new_gdp, new_happiness, new_opposition, new_corruption,
          new_infrastructure, new_health, new_education, new_crime, new_relations, new_inflation,
          new_welfare, new_safety, new_coalition, new_trade_balance, new_confidence, new_inequality, history_id))

    cursor.execute("DELETE FROM pending_events WHERE game_id = ?", (game_id,))
    conn.commit()
    conn.close()

    log_event(
        game_id, turn_year, 'SOCIAL', f"Keputusan: {event_title}",
        f"Anda memilih '{choice_label}'. {event_desc}",
        db_path=db_path
    )
    return {'treasury': new_treasury, 'happiness': new_happiness}
