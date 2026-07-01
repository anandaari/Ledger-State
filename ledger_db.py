import sqlite3
import json
import os

DB_PATH = "ledger.db"

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
        if not {'country_name', 'party_name'}.issubset(cols):
            return True

    if 'nation_history' in existing_tables:
        cursor.execute("PRAGMA table_info(nation_history)")
        cols = {row[1] for row in cursor.fetchall()}
        if not {'pop_low', 'pop_mid', 'pop_high', 'pop_elder', 'tax_low', 'tax_mid', 'tax_high', 'opposition_strength', 'corruption_index', 'crime_rate'}.issubset(cols):
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
        budget_education, budget_health, budget_infrastructure, budget_welfare, budget_security
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        b_ed, b_hl, b_inf, b_welf, b_sec
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
               budget_education, budget_health, budget_infrastructure, budget_welfare, budget_security
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
            'budget_education', 'budget_health', 'budget_infrastructure', 'budget_welfare', 'budget_security'
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
        budget_education, budget_health, budget_infrastructure, budget_welfare, budget_security
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        game_id, data['turn_year'], data['treasury'], data['gdp'],
        data['pop_low'], data['pop_mid'], data['pop_high'], data['pop_elder'],
        data['employment_rate'], data['crime_rate'], data['happiness'], data['education_index'],
        data['health_index'], data['infrastructure'], data['opposition_strength'], data['corruption_index'],
        data['tax_low'], data['tax_mid'], data['tax_high'],
        data['budget_education'], data['budget_health'], data['budget_infrastructure'],
        data['budget_welfare'], data['budget_security']
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
