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

def format_currency(usd_billions, country_name, decimals=1):
    info = CURRENCY_INFO.get(country_name, CURRENCY_INFO["United States"])
    local_value = usd_billions * info["rate_per_usd"] / info["unit_divisor"]
    return f"{info['symbol']}{local_value:,.{decimals}f}{info['unit_label']}"

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
    }
}

PARTY_PRESETS = {
    "Partai Rakyat Progresif": {
        "tagline": "Pajak besar untuk kelompok kaya, jaring pengaman sosial kuat.",
        "ideology": {"tax_high": 1, "welfare": 1, "security": -1},
    },
    "Partai Nasional Konservatif": {
        "tagline": "Pajak rendah, anggaran keamanan & pertahanan diprioritaskan.",
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
CABINET_POSITIONS = ["Menteri Pendidikan", "Menteri Kesehatan", "Menteri Infrastruktur", "Menteri Sosial", "Menteri Keamanan"]

ADVISOR_TIERS = {
    "Muda": {"bonus": 2.0, "hire_cost": 5.0, "salary": 1.0},
    "Berpengalaman": {"bonus": 4.0, "hire_cost": 15.0, "salary": 3.0},
    "Pakar": {"bonus": 7.0, "hire_cost": 35.0, "salary": 6.0},
}

ADVISOR_NAME_POOL = [
    "Dr. Siti Amelia", "Prof. Bambang Wirawan", "Dr. Kevin Halim", "Ratna Sari Dewi",
    "Prof. Agus Santoso", "Dr. Michelle Tanoto", "Hendra Wijaya", "Dr. Farah Nabila",
    "Prof. Yusuf Kartawijaya", "Dr. Grace Lim",
]

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
}

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
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('games','nation_history')")
    existing_tables = {row[0] for row in cursor.fetchall()}

    if 'games' in existing_tables:
        cursor.execute("PRAGMA table_info(games)")
        cols = {row[1] for row in cursor.fetchall()}
        if not {'country_name', 'party_name', 'sandbox_mode'}.issubset(cols):
            return True

    if 'nation_history' in existing_tables:
        cursor.execute("PRAGMA table_info(nation_history)")
        cols = {row[1] for row in cursor.fetchall()}
        if not {'pop_low', 'pop_mid', 'pop_high', 'pop_elder', 'tax_low', 'tax_mid', 'tax_high', 'opposition_strength', 'corruption_index', 'crime_rate', 'min_wage', 'export_tariff'}.issubset(cols):
            return True

    return False

def init_db(db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if _schema_is_stale(cursor):
        for table in ('crises', 'turn_events', 'nation_history', 'games'):
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
        education_index REAL NOT NULL,
        health_index REAL NOT NULL,
        infrastructure REAL NOT NULL,
        opposition_strength REAL NOT NULL,
        corruption_index REAL NOT NULL,

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
    initial_year = 2026

    gdp = preset["gdp"]
    b_ed = round(gdp * 0.02, 2)
    b_hl = round(gdp * 0.015, 2)
    b_inf = round(gdp * 0.015, 2)
    b_welf = round(gdp * 0.01, 2)
    b_sec = round(gdp * 0.01, 2)

    cursor.execute("""
    INSERT INTO nation_history (
        game_id, turn_year, treasury, gdp, pop_low, pop_mid, pop_high, pop_elder,
        employment_rate, crime_rate, happiness, education_index, health_index, infrastructure, opposition_strength, corruption_index,
        tax_low, tax_mid, tax_high,
        budget_education, budget_health, budget_infrastructure, budget_welfare, budget_security,
        min_wage, export_tariff
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        game_id, initial_year,
        preset["treasury"],
        gdp,
        preset["pop_low"],
        preset["pop_mid"],
        preset["pop_high"],
        preset["pop_elder"],
        0.80,
        0.44,
        55.0,
        50.0,
        50.0,
        50.0,
        15.0,
        0.0,
        preset["tax_low"],
        preset["tax_mid"],
        preset["tax_high"],
        b_ed, b_hl, b_inf, b_welf, b_sec,
        20.0, 0.0
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
    crises_data = [
        (game_id, "The Infrastructure Bottleneck", 0, 3, 0, 2, 'INACTIVE',
         "Rapid industrial growth has overloaded the nation's power grids and road systems.",
         "Keep Infrastructure budget at or above 1.5% of your total GDP for 2 turns during the crisis duration."),

        (game_id, "The Public Health Epidemic", 0, 4, 0, 3, 'INACTIVE',
         "A highly contagious virus is spreading due to public health underfunding.",
         "Keep Healthcare budget at or above 20% of your total budget AND low-bracket tax rate at or above 8% for 3 turns to build facilities and fund vaccines."),

        (game_id, "The Brain Drain Crisis", 0, 4, 0, 3, 'INACTIVE',
         "Your highly educated citizens are fleeing the nation due to high tax rates on the high-income bracket.",
         "Reduce Tax Rate on High-Income to below 20% AND keep Social Welfare budget at or above 10% of total spending for 3 turns to retain elite talent."),

        (game_id, "The Demographic Cliff", 0, 5, 0, 3, 'INACTIVE',
         "A record drop in birth rates has caused a severe aging crisis, putting strain on active workers.",
         "Keep Welfare budget above 3% of your GDP (family subsidies) OR keep combined Security & Infrastructure spending at 15% of total budget (to support high-skill immigration) for 3 turns."),

        (game_id, "The Carbon Transition Tariff", 0, 4, 0, 3, 'INACTIVE',
         "Global partners threat trade sanctions on the country's carbon emissions unless clean production targets are met.",
         "Keep Infrastructure budget above 2.0% of your GDP (green grid) AND Security budget above 0.5% of your GDP (emissions enforcement) for 3 turns."),

        (game_id, "Krisis Utang Nasional", 0, 4, 0, 3, 'INACTIVE',
         "Investor internasional mulai gelisah - rasio utang terhadap GDP negara Anda melewati batas aman, memicu spekulasi soal kemampuan bayar.",
         "Turunkan total belanja (Pendidikan+Kesehatan+Infrastruktur+Kesejahteraan+Keamanan) ke 8% atau kurang dari GDP selama 3 tahun untuk memulihkan kepercayaan kreditor."),

        (game_id, "Gelombang Kriminalitas", 0, 4, 0, 3, 'INACTIVE',
         "Lemahnya penegakan hukum memicu lonjakan kejahatan yang menekan produktivitas dan menakuti investor.",
         "Pertahankan anggaran Keamanan di atas 2% dari GDP selama 3 tahun untuk memulihkan ketertiban."),
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
               employment_rate, crime_rate, happiness, education_index, health_index, infrastructure, opposition_strength, corruption_index,
               tax_low, tax_mid, tax_high,
               budget_education, budget_health, budget_infrastructure, budget_welfare, budget_security,
               min_wage, export_tariff
        FROM nation_history
        WHERE game_id = ?
        ORDER BY turn_year DESC LIMIT 1
    """, (game_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        columns = [
            'history_id', 'turn_year', 'treasury', 'gdp', 'pop_low', 'pop_mid', 'pop_high', 'pop_elder',
            'employment_rate', 'crime_rate', 'happiness', 'education_index', 'health_index', 'infrastructure', 'opposition_strength', 'corruption_index',
            'tax_low', 'tax_mid', 'tax_high',
            'budget_education', 'budget_health', 'budget_infrastructure', 'budget_welfare', 'budget_security',
            'min_wage', 'export_tariff'
        ]
        return dict(zip(columns, row))
    return None

def get_history(game_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT turn_year, treasury, gdp, (pop_low + pop_mid + pop_high + pop_elder) as population,
               employment_rate, happiness, education_index, health_index, infrastructure,
               tax_low, tax_mid, tax_high, pop_low, pop_mid, pop_high, pop_elder, opposition_strength, corruption_index, crime_rate
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
        employment_rate, crime_rate, happiness, education_index, health_index, infrastructure, opposition_strength, corruption_index,
        tax_low, tax_mid, tax_high,
        budget_education, budget_health, budget_infrastructure, budget_welfare, budget_security,
        min_wage, export_tariff
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        game_id, data['turn_year'], data['treasury'], data['gdp'],
        data['pop_low'], data['pop_mid'], data['pop_high'], data['pop_elder'],
        data['employment_rate'], data['crime_rate'], data['happiness'], data['education_index'],
        data['health_index'], data['infrastructure'], data['opposition_strength'], data['corruption_index'],
        data['tax_low'], data['tax_mid'], data['tax_high'],
        data['budget_education'], data['budget_health'], data['budget_infrastructure'],
        data['budget_welfare'], data['budget_security'],
        data['min_wage'], data['export_tariff']
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

def get_events(game_id, turn_year=None, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    if turn_year:
        cursor.execute("""
            SELECT event_id, turn_year, event_type, title, description, impact_json
            FROM turn_events
            WHERE game_id = ? AND turn_year = ?
            ORDER BY event_id DESC
        """, (game_id, turn_year))
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

def hire_advisor(game_id, position, tier, db_path=DB_PATH):
    """
    Hires (or replaces) the advisor in the given cabinet position, paying the
    tier's hire_cost immediately from the current turn's treasury. The
    ongoing salary is deducted every subsequent turn by engine.py.
    """
    tier_info = ADVISOR_TIERS[tier]
    advisor_name = random.choice(ADVISOR_NAME_POOL)

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
    new_treasury = treasury - tier_info['hire_cost']

    cursor.execute("DELETE FROM cabinet WHERE game_id = ? AND position = ?", (game_id, position))
    cursor.execute("""
        INSERT INTO cabinet (game_id, position, advisor_name, tier, bonus_value, salary, hired_year)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (game_id, position, advisor_name, tier, tier_info['bonus'], tier_info['salary'], turn_year))
    cursor.execute("UPDATE nation_history SET treasury = ? WHERE history_id = ?", (new_treasury, history_id))
    conn.commit()
    conn.close()

    log_event(
        game_id, turn_year, 'SOCIAL', f"Menteri Baru: {position}",
        f"{advisor_name} ({tier}) dilantik sebagai {position}, menghabiskan ${tier_info['hire_cost']:.1f}B dari kas negara untuk biaya pelantikan.",
        db_path=db_path
    )
    return {'advisor_name': advisor_name, 'treasury': new_treasury}

def fire_advisor(game_id, position, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cabinet WHERE game_id = ? AND position = ?", (game_id, position))
    conn.commit()
    conn.close()

def create_pending_event(game_id, event_key, turn_year, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO pending_events (game_id, event_key, turn_year) VALUES (?, ?, ?)",
        (game_id, event_key, turn_year)
    )
    conn.commit()
    conn.close()

def get_pending_event(game_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT pending_id, event_key, turn_year FROM pending_events WHERE game_id = ? ORDER BY pending_id DESC LIMIT 1",
        (game_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return {'pending_id': row[0], 'event_key': row[1], 'turn_year': row[2]}
    return None

def resolve_pending_event(game_id, event_key, choice_label, db_path=DB_PATH):
    """
    Applies the chosen option's stat deltas to the current (not-yet-ended)
    turn's row in place - same pattern as apply_bribe/hire_advisor - then
    clears the pending decision so gameplay can continue.
    """
    effects = RANDOM_EVENTS[event_key]['choices'][choice_label]

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT history_id, turn_year, treasury, gdp, happiness, opposition_strength,
               corruption_index, infrastructure, health_index, education_index
        FROM nation_history WHERE game_id = ? ORDER BY turn_year DESC LIMIT 1
    """, (game_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    (history_id, turn_year, treasury, gdp, happiness, opposition_strength,
     corruption_index, infrastructure, health_index, education_index) = row

    new_treasury = treasury + effects.get('treasury', 0.0)
    new_gdp = max(10.0, gdp + effects.get('gdp', 0.0))
    new_happiness = max(0.0, min(100.0, happiness + effects.get('happiness', 0.0)))
    new_opposition = max(0.0, min(100.0, opposition_strength + effects.get('opposition_strength', 0.0)))
    new_corruption = max(0.0, min(100.0, corruption_index + effects.get('corruption_index', 0.0)))
    new_infrastructure = max(0.0, min(100.0, infrastructure + effects.get('infrastructure', 0.0)))
    new_health = max(0.0, min(100.0, health_index + effects.get('health_index', 0.0)))
    new_education = max(0.0, min(100.0, education_index + effects.get('education_index', 0.0)))

    cursor.execute("""
        UPDATE nation_history
        SET treasury = ?, gdp = ?, happiness = ?, opposition_strength = ?,
            corruption_index = ?, infrastructure = ?, health_index = ?, education_index = ?
        WHERE history_id = ?
    """, (new_treasury, new_gdp, new_happiness, new_opposition, new_corruption,
          new_infrastructure, new_health, new_education, history_id))

    cursor.execute("DELETE FROM pending_events WHERE game_id = ?", (game_id,))
    conn.commit()
    conn.close()

    event = RANDOM_EVENTS[event_key]
    log_event(
        game_id, turn_year, 'SOCIAL', f"Keputusan: {event['title']}",
        f"Anda memilih '{choice_label}'. {event['description']}",
        db_path=db_path
    )
    return {'treasury': new_treasury, 'happiness': new_happiness}
