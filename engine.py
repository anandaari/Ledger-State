import random
import json
import ledger_db as database

# A turn is now one fiscal quarter (3 months), not a full year - 4 turns per
# calendar year. Every constant below that used to represent an ANNUAL rate
# (growth, decay, interest, demographic change) is divided by 4 so the same
# real-world pace is preserved across 4 turns; GDP-to-budget thresholds are
# also divided by 4 since budget inputs are now quarterly amounts. Constants
# that represent LEVELS (current equilibrium given current conditions, not
# accumulated flows) or ONE-TIME discrete action costs are left untouched.
ELECTION_TERM_QUARTERS = 20  # 5 years
CRISIS_COOLDOWN_QUARTERS = 12  # 3 years

def get_permanent_modifiers(game_id):
    """
    Scans historical crises to apply permanent rewards/penalties to GDP growth and other factors.
    """
    crises = database.get_crises(game_id)
    modifiers = {
        'gdp_growth_mod': 0.0,
        'pop_growth_mod': 0.0,
        'infra_efficiency': 1.0,
        'health_bonus': 0.0,
    }

    for c in crises:
        if c['status'] == 'SOLVED':
            if c['name'] == "The Infrastructure Bottleneck":
                modifiers['infra_efficiency'] = 1.15 # 15% more efficient building (ratio, not a rate - unscaled)
            elif c['name'] == "The Public Health Epidemic":
                modifiers['health_bonus'] = 3.75 # Health stays higher (was +15/year, now applied every quarter)
            elif c['name'] == "The Brain Drain Crisis":
                modifiers['gdp_growth_mod'] += 0.00375 # Unlock high tech (was +1.5%/year GDP growth)
            elif c['name'] == "The Demographic Cliff":
                modifiers['pop_growth_mod'] += 0.0025 # Younger workforce (was +1%/year pop growth)
            elif c['name'] == "The Carbon Transition Tariff":
                modifiers['gdp_growth_mod'] += 0.0075 # Green exports (was +3%/year GDP growth)
            elif c['name'] == "Krisis Utang Nasional":
                modifiers['gdp_growth_mod'] += 0.0025 # Restored credit trust
            elif c['name'] == "Gelombang Kriminalitas":
                modifiers['gdp_growth_mod'] += 0.0025 # Safer streets, more investment

        elif c['status'] == 'FAILED':
            if c['name'] == "The Infrastructure Bottleneck":
                modifiers['gdp_growth_mod'] -= 0.0025 # Blackouts penalty
            elif c['name'] == "The Public Health Epidemic":
                modifiers['gdp_growth_mod'] -= 0.00375 # Sick workforce
            elif c['name'] == "The Brain Drain Crisis":
                modifiers['gdp_growth_mod'] -= 0.005 # Brain drain penalty
            elif c['name'] == "The Demographic Cliff":
                modifiers['gdp_growth_mod'] -= 0.005 # Aging population penalty
            elif c['name'] == "The Carbon Transition Tariff":
                modifiers['gdp_growth_mod'] -= 0.0075 # Sanctions penalty
            elif c['name'] == "Krisis Utang Nasional":
                modifiers['gdp_growth_mod'] -= 0.005 # Lingering credit downgrade
            elif c['name'] == "Gelombang Kriminalitas":
                modifiers['gdp_growth_mod'] -= 0.00375 # Chronic insecurity penalty

    return modifiers

def simulate_turn(game_id, inputs):
    """
    Simulates one fiscal quarter of the nation based on player inputs and
    previous turn history. Supports demographic cohorts (Low, Mid, High,
    Pensioners) and 3 tax brackets.
    """
    prev_state = database.get_latest_turn(game_id)
    if not prev_state:
        raise ValueError("No game state found. Please initialize the game first.")

    current_year = prev_state['turn_year']
    next_year = current_year + 1
    country_name = database.get_country_name(game_id)
    diff_settings = database.get_difficulty_settings(game_id)


    # 1. Gather Inputs (3 tax brackets, 5 budget allocations, min wage, export tariff)
    tax_low = inputs['tax_low']
    tax_mid = inputs['tax_mid']
    tax_high = inputs['tax_high']
    b_ed = inputs['budget_education']
    b_hl = inputs['budget_health']
    b_inf = inputs['budget_infrastructure']
    b_welf = inputs['budget_welfare']
    b_sec = inputs['budget_security']
    min_wage = inputs['min_wage']          # 0-100 policy intensity, not a literal wage figure
    export_tariff = inputs['export_tariff']  # 0-30% tax on exported goods
    import_tariff = inputs['import_tariff']  # 0-30% duty on imported goods

    total_spending = b_ed + b_hl + b_inf + b_welf + b_sec
    gdp = prev_state['gdp']
    country_preset = database.COUNTRY_PRESETS.get(country_name, database.COUNTRY_PRESETS["Indonesia"])
    export_dependency = country_preset['export_dependency']
    import_dependency = country_preset['import_dependency']

    # Ratios to GDP
    ed_ratio = b_ed / gdp
    hl_ratio = b_hl / gdp
    inf_ratio = b_inf / gdp

    # Demographic state
    p_low = prev_state['pop_low']
    p_mid = prev_state['pop_mid']
    p_high = prev_state['pop_high']
    p_elder = prev_state['pop_elder']
    p_total = p_low + p_mid + p_high + p_elder

    r_low = p_low / p_total
    r_mid = p_mid / p_total
    r_high = p_high / p_total
    r_elder = p_elder / p_total

    # 2. Retrieve Permanent Modifiers
    perm_mods = get_permanent_modifiers(game_id)

    # 2b. Retrieve Cabinet - each hired advisor boosts their linked stat every
    # turn and costs an ongoing salary, deducted from treasury like any other
    # spending line.
    cabinet = database.get_cabinet(game_id)
    cabinet_bonus = {c['position']: c['bonus_value'] for c in cabinet}
    cabinet_salaries = sum(c['salary'] for c in cabinet)

    # 2c. Foreign Relations & Coalition Support - both drift without upkeep.
    # Foreign Relations mean-reverts toward a neutral 50 (diplomacy fades
    # without renewal via apply_trade_agreement); Coalition Support decays
    # outright since minor-party backing must be actively re-bought via
    # apply_coalition_negotiation. Decay factors are the 4th root of their
    # old per-year value so the same real-time drift speed is preserved.
    foreign_relations = prev_state['foreign_relations'] * 0.9872 + 50.0 * 0.0128
    foreign_relations = max(0.0, min(100.0, foreign_relations))
    coalition_support = max(0.0, prev_state['coalition_support'] * 0.9686)

    # 3. Retrieve Crises (crises trigger dynamically once a matching economic
    # indicator crosses a critical level - see "Dynamic Crisis Triggering"
    # near the end of this function - instead of a fixed calendar year)
    crises = database.get_crises(game_id)
    active_crisis = next((c for c in crises if c['status'] == 'ACTIVE'), None)

    # Apply active crisis rules & verify progress conditions
    crisis_penalty_text = ""
    crisis_progress_text = ""

    if active_crisis:
        met_condition = False
        name = active_crisis['name']

        if name == "The Infrastructure Bottleneck":
            # Requirement: Infrastructure budget >= 0.375% of quarterly GDP
            if b_inf >= 0.00375 * gdp:
                met_condition = True
            crisis_penalty_text = "Infrastructure bottleneck limits maximum GDP growth and hurts happiness."

        elif name == "The Public Health Epidemic":
            # Requirement: Healthcare budget >= 20% of total budget AND tax rate low >= 8%
            if (b_hl >= 0.20 * total_spending) and (tax_low >= 0.08):
                met_condition = True
            crisis_penalty_text = "Public Health Epidemic drains citizen wellness and reduces productivity."

        elif name == "The Brain Drain Crisis":
            # Requirement: Tax Rate on High-income < 20% AND Social Welfare >= 10% of total spending
            if (tax_high < 0.20) and (b_welf >= 0.10 * total_spending):
                met_condition = True
            crisis_penalty_text = "Wealthy and elite workers are fleeing. Education decay is doubled."

        elif name == "The Demographic Cliff":
            # Requirement: Welfare budget >= 0.75% of quarterly GDP OR combined Security & Infrastructure spending >= 15% of total budget
            if (b_welf >= 0.0075 * gdp) or ((b_sec + b_inf) >= 0.15 * total_spending):
                met_condition = True
            crisis_penalty_text = "Aging population reduces tax collection efficiency by 20% and inflates welfare costs."

        elif name == "The Carbon Transition Tariff":
            # Requirement: Infrastructure >= 0.5% of quarterly GDP AND Security >= 0.125% of quarterly GDP
            if (b_inf >= 0.005 * gdp) and (b_sec >= 0.00125 * gdp):
                met_condition = True
            crisis_penalty_text = "Carbon tariffs are weighing heavily on GDP growth."

        elif name == "Krisis Utang Nasional":
            # Requirement: total spending <= 2% of quarterly GDP (austerity) to rebuild credit trust
            if total_spending <= 0.02 * gdp:
                met_condition = True
            crisis_penalty_text = "Kepercayaan kreditor internasional anjlok, menaikkan suku bunga utang."

        elif name == "Gelombang Kriminalitas":
            # Requirement: Security budget >= 0.5% of quarterly GDP
            if b_sec >= 0.005 * gdp:
                met_condition = True
            crisis_penalty_text = "Kriminalitas merajalela menekan produktivitas dan kepercayaan investor."

        # Update progress
        new_progress = active_crisis['current_progress']
        if met_condition:
            new_progress += 1
            crisis_progress_text = f"CRISIS UPDATE: Requirement met this quarter! Progress: {new_progress}/{active_crisis['target_progress']}."
            database.log_event(game_id, next_year, 'CRISIS', f"Crisis Progress: {active_crisis['name']}", crisis_progress_text)
        else:
            crisis_progress_text = f"CRISIS UPDATE: Objective NOT met this quarter. Progress: {new_progress}/{active_crisis['target_progress']}."
            database.log_event(game_id, next_year, 'CRISIS', f"Crisis Alert: {active_crisis['name']}", crisis_progress_text)

        # Check resolved or failed status at the end of the quarter
        turns_elapsed = next_year - active_crisis['start_year'] + 1

        if new_progress >= active_crisis['target_progress']:
            active_crisis['status'] = 'SOLVED'
            database.update_crisis_state(active_crisis['crisis_id'], new_progress, 'SOLVED')
            database.log_event(
                game_id, next_year, 'CRISIS', f"CRISIS SOLVED: {active_crisis['name']}",
                f"Novus has successfully navigated the crisis. Reward unlocked."
            )
            active_crisis = None
        elif turns_elapsed >= active_crisis['duration_turns']:
            active_crisis['status'] = 'FAILED'
            database.update_crisis_state(active_crisis['crisis_id'], new_progress, 'FAILED')
            database.log_event(
                game_id, next_year, 'CRISIS', f"CRISIS FAILED: {active_crisis['name']}",
                f"Novus failed to address the crisis in time. Permanent economic sanctions and structural penalties applied."
            )
            active_crisis = None
        else:
            database.update_crisis_state(active_crisis['crisis_id'], new_progress, 'ACTIVE')
            active_crisis['current_progress'] = new_progress

    # 4. Education, Health, and Infrastructure Indices
    # decay_modifier scales how much of each index is lost every turn if not
    # reinvested in - Hard makes standing still actively costly, Easy forgives it.
    # Each decay factor is annualized-then-4th-rooted so the SAME per-year
    # decay pace applies whether checked once a year or once a quarter; the
    # budget injection terms (100*ed_ratio etc.) need no separate rescaling
    # since ed_ratio/hl_ratio/inf_ratio already shrunk 4x from quarterly budgets.
    decay_mod = diff_settings["decay_modifier"]

    base_education_decay = 0.90 if (active_crisis and active_crisis['name'] == "The Brain Drain Crisis") else 0.95
    education_decay = (1.0 - (1.0 - base_education_decay) * decay_mod) ** 0.25
    education_index = prev_state['education_index'] * education_decay + 100 * ed_ratio
    education_index += cabinet_bonus.get("Menteri Pendidikan", 0.0)
    education_index = max(0.0, min(100.0, education_index))

    base_health_decay = 0.85 if (active_crisis and active_crisis['name'] == "The Public Health Epidemic") else 0.95
    health_decay = (1.0 - (1.0 - base_health_decay) * decay_mod) ** 0.25
    health_bonus = perm_mods['health_bonus']
    health_index = prev_state['health_index'] * health_decay + 100 * hl_ratio + health_bonus
    health_index += cabinet_bonus.get("Menteri Kesehatan", 0.0)
    health_index = max(0.0, min(100.0, health_index))

    infra_efficiency = perm_mods['infra_efficiency']
    infra_decay = (1.0 - (1.0 - 0.93) * decay_mod) ** 0.25
    infrastructure = prev_state['infrastructure'] * infra_decay + 120 * inf_ratio * infra_efficiency
    infrastructure += cabinet_bonus.get("Menteri Infrastruktur", 0.0)
    infrastructure = max(0.0, min(100.0, infrastructure))

    # 5. Economic simulation
    # Calculate average tax rate weighted by population
    avg_tax_rate = r_low * tax_low + r_mid * tax_mid + r_high * tax_high

    # Base GDP growth (all rates quartered from their per-year figure)
    growth_base = 0.01125 * (education_index / 100.0) * (infrastructure / 100.0) - 0.04 * avg_tax_rate
    growth_base += perm_mods['gdp_growth_mod']

    # Minimum wage raises labor costs; export tariffs hurt competitiveness in
    # proportion to how export-dependent the country's economy is. Import
    # tariffs also raise costs for domestic producers reliant on imported
    # inputs, though more mildly than export tariffs hurt competitiveness -
    # their main bite lands on consumer happiness instead (see below).
    growth_base -= (min_wage / 100.0) * 0.005
    growth_base -= export_dependency * (export_tariff / 100.0) * 0.0125
    growth_base -= import_dependency * (import_tariff / 100.0) * 0.005

    # Foreign Relations: strong diplomatic standing (>50, neutral) gives a
    # small GDP growth bonus from smoother trade access; collapsed relations
    # (<50) drag growth down and can eventually trigger the "trade_war" event.
    growth_base += (foreign_relations - 50.0) / 50.0 * 0.0025

    if active_crisis and active_crisis['name'] == "The Carbon Transition Tariff":
        growth_base -= 0.01 # Carbon sanctions

    # Global economic market shock - probability bands are per-turn (i.e. now
    # checked 4x more often per year, deliberately making quarterly play more
    # eventful); magnitudes are quartered so the annualized shock size matches
    # what a single yearly turn used to deliver.
    shock_event = None
    shock_value = 0.0
    shock_desc = ""
    rand_val = random.random()
    if rand_val < 0.08: # Global Recession
        shock_event = "Global Recession"
        shock_value = -0.0075
        shock_desc = "A major contraction in global markets drops Novus's GDP growth this quarter."
    elif rand_val < 0.15: # Commodity Boom
        shock_event = "Resource Market Boom"
        shock_value = 0.005
        shock_desc = "High global demand for exports boosts Novus's GDP growth this quarter."
    elif rand_val < 0.19: # Cyber attack
        shock_event = "Cyber Ransom Attack"
        shock_value = -0.0025
        # Stolen cash scales with GDP size and difficulty severity
        stolen_cash = round(gdp * 0.0075 * diff_settings["shock_severity_mult"], 1)
        shock_desc = f"Hackers disrupt digital infrastructure, lowering GDP growth and stealing ${stolen_cash}B from treasury."
    elif rand_val < 0.24: # Tech boom
        shock_event = "AI Core Breakthrough"
        shock_value = 0.00875
        shock_desc = "Local researchers invent an optimized automation algorithm. GDP growth surges this quarter!"
    elif rand_val < 0.29: # Natural disaster
        shock_event = "Bencana Alam"
        shock_value = -0.00375
        shock_desc = "Bencana alam besar merusak infrastruktur dan memaksa pengeluaran dana darurat untuk pemulihan."
    elif rand_val < 0.35: # Foreign investment windfall
        shock_event = "Investasi Asing Mengalir"
        shock_value = 0.00375
        shock_desc = "Investor asing menanamkan modal besar-besaran, mendorong pertumbuhan ekonomi dan menyuntik kas negara."
    else:
        # Standard slight volatility
        shock_value = random.uniform(-0.00125, 0.00125)

    shock_value *= diff_settings["shock_severity_mult"]  # Hard hits harder, Easy softens every shock

    gdp_growth = growth_base + shock_value

    if shock_event == "Bencana Alam":
        infrastructure = max(0.0, infrastructure - 1.25 * diff_settings["shock_severity_mult"])  # damage carries into next quarter's baseline

    # Cap growth during Infrastructure crisis
    if active_crisis and active_crisis['name'] == "The Infrastructure Bottleneck":
        gdp_growth = min(gdp_growth, 0.00375)

    new_gdp = gdp * (1.0 + gdp_growth)
    new_gdp = max(10.0, new_gdp)

    # 5b. Corruption Dynamics
    # Corruption only grows through corrupt actions (e.g. bribing the opposition)
    # applied directly to the DB by apply_bribe(); here it just decays slowly
    # each turn (anti-corruption reform/attrition) and drags down tax efficiency.
    # 0.9794 is the 4th root of the old 0.92 per-year decay factor.
    prev_corruption = prev_state['corruption_index']
    corruption_index = max(0.0, min(100.0, prev_corruption * 0.9794))
    corruption_penalty = (corruption_index / 100.0) * 0.30  # up to -30% tax efficiency at 100

    if corruption_index >= 50.0 and prev_corruption < 50.0:
        database.log_event(
            game_id, next_year, 'SOCIAL', "Korupsi Merajalela",
            "Indeks Korupsi melewati 50%, secara signifikan menggerus efisiensi penerimaan pajak dan kepercayaan publik."
        )

    # 6. Revenues (Class-based tax contributions) - scaling constants are
    # quartered since this revenue is now collected 4x a year instead of once.
    # Low-income generates less tax per capita; High-income generates much more.
    tax_eff = 0.90 + 0.10 * (education_index / 100.0)
    if active_crisis and active_crisis['name'] == "The Demographic Cliff":
        tax_eff *= 0.80 # 20% loss due to smaller active working class
    tax_eff *= (1.0 - corruption_penalty)

    emp = prev_state['employment_rate']
    rev_low = new_gdp * r_low * tax_low * emp * 0.125
    rev_mid = new_gdp * r_mid * tax_mid * emp * 0.25
    rev_high = new_gdp * r_high * tax_high * emp * 0.625

    revenue = (rev_low + rev_mid + rev_high) * tax_eff

    # Export Tariff revenue - scales with how export-dependent the economy is
    tariff_revenue = new_gdp * export_dependency * (export_tariff / 100.0) * 0.125
    revenue += tariff_revenue

    # Import Tariff revenue - scales with how import-dependent the economy is
    import_tariff_revenue = new_gdp * import_dependency * (import_tariff / 100.0) * 0.125
    revenue += import_tariff_revenue

    # Debt Interest - rate depends on difficulty and the Sovereign Credit
    # Rating (derived from last quarter's Debt/GDP ratio and Corruption),
    # elevated further during an active debt crisis. diff_settings rates are
    # already quarterly (see DIFFICULTY_SETTINGS).
    debt_interest = 0.0
    if prev_state['treasury'] < 0:
        prev_debt_to_gdp_pct = (prev_state['treasury'] / gdp) * 100.0
        rating_info = database.get_credit_rating(prev_debt_to_gdp_pct, prev_state['corruption_index'])
        interest_rate = diff_settings["interest_rate_normal"]
        if active_crisis and active_crisis['name'] == "Krisis Utang Nasional":
            interest_rate = diff_settings["interest_rate_crisis"]  # credit downgrade
        interest_rate *= rating_info['interest_modifier']
        debt_interest = abs(prev_state['treasury']) * interest_rate

    total_costs = total_spending + debt_interest + cabinet_salaries

    if shock_event == "Cyber Ransom Attack":
        total_costs += round(gdp * 0.0075 * diff_settings["shock_severity_mult"], 1)
    elif shock_event == "Bencana Alam":
        total_costs += round(gdp * 0.005 * diff_settings["shock_severity_mult"], 1)  # emergency relief spending

    new_treasury = prev_state['treasury'] + revenue - total_costs

    if shock_event == "Investasi Asing Mengalir":
        new_treasury += round(gdp * 0.005 * diff_settings["shock_severity_mult"], 1)

    # 7. Labor & Welfare Calculations
    # Employment is a LEVEL (recomputed fresh each turn, not accumulated), so
    # it should react to the ANNUALIZED pace of growth, not the raw quarterly
    # figure - gdp_growth is multiplied back up by 4 before feeding in here.
    annualized_gdp_growth = gdp_growth * 4.0
    new_employment = 0.82 + 0.4 * annualized_gdp_growth + 0.05 * (infrastructure / 100.0) - 0.12 * avg_tax_rate
    new_employment -= (min_wage / 100.0) * 0.08  # higher labor cost prices some workers out of jobs
    new_employment = max(0.40, min(0.98, new_employment))

    # Crime Factor - target_security threshold is quartered to match quarterly b_sec
    target_security = new_gdp * 0.00625
    sec_factor = min(1.0, b_sec / max(0.1, target_security))
    crime_factor = max(0.0, 1.0 - (0.6 * sec_factor + 0.4 * new_employment))
    if active_crisis and active_crisis['name'] == "Gelombang Kriminalitas":
        crime_factor = min(1.0, crime_factor + 0.15)
    crime_factor = max(0.0, crime_factor - cabinet_bonus.get("Menteri Keamanan", 0.0) / 100.0)

    # Welfare efficiency - threshold quartered to match quarterly b_welf
    welf_efficiency = 1.0
    if active_crisis and active_crisis['name'] == "The Demographic Cliff":
        welf_efficiency = 1.3 # 30% higher demand / cost dilution
    welfare_ratio = (b_welf / welf_efficiency) / max(1.0, new_gdp * 0.0125)

    # 8. Class-Specific Happiness (all LEVEL formulas - no rescaling needed,
    # since they react to the current quarter's conditions, not a flow)
    # Low-income: highly sensitive to tax_low and welfare
    h_low = 35.0 + 35.0 * new_employment + 25.0 * min(1.0, welfare_ratio) - 50.0 * tax_low - 20.0 * crime_factor
    h_low += (min_wage / 100.0) * 15.0  # higher minimum wage directly raises low-income living standards
    # Middle-income: balanced sensitivity
    h_mid = 45.0 + 30.0 * new_employment + 15.0 * min(1.0, welfare_ratio) - 40.0 * tax_mid - 12.0 * crime_factor
    # High-income: highly sensitive to high taxes
    h_high = 55.0 + 20.0 * new_employment - 60.0 * tax_high - 6.0 * crime_factor
    # Pensioners: highly sensitive to health and welfare
    h_elder = 30.0 + 35.0 * (health_index / 100.0) + 35.0 * min(1.0, welfare_ratio) - 10.0 * crime_factor

    # Clamped copies for storage/display only - the weighted average below
    # intentionally keeps using the raw (unclamped) values so existing game
    # balance doesn't shift.
    h_low_stored = max(0.0, min(100.0, h_low))
    h_mid_stored = max(0.0, min(100.0, h_mid))
    h_high_stored = max(0.0, min(100.0, h_high))
    h_elder_stored = max(0.0, min(100.0, h_elder))

    # Weighted average happiness
    new_happiness = r_low * h_low + r_mid * h_mid + r_high * h_high + r_elder * h_elder

    if active_crisis:
        if active_crisis['name'] == "The Infrastructure Bottleneck":
            new_happiness -= 6.0
        elif active_crisis['name'] == "The Public Health Epidemic":
            new_happiness -= 8.0

    new_happiness -= corruption_index * 0.05  # public distrust from corruption, up to -5 at 100%
    new_happiness -= import_dependency * (import_tariff / 100.0) * 15.0  # cost-of-living hit from pricier imported goods
    new_happiness += cabinet_bonus.get("Menteri Sosial", 0.0)

    new_happiness = max(0.0, min(100.0, new_happiness))

    # 8b. Political Opposition Dynamics
    # Every policy lever pulls you closer to your own party's ideology or the
    # opposition's. Straying from your own base to appease the opposition
    # (or letting happiness sink) lets the opposition gain ground; staying
    # loyal and keeping citizens content lets their momentum fade over time.
    party_name = database.get_party_name(game_id)
    opposition_party = database.get_opposition_party(party_name)
    ideology = database.PARTY_PRESETS[party_name]['ideology']

    norm_tax_high = tax_high / 0.90
    norm_welfare = min(1.0, (b_welf / new_gdp) / 0.015)
    norm_security = min(1.0, (b_sec / new_gdp) / 0.01)

    def _loyalty(axis_value, sign):
        return axis_value if sign > 0 else (1.0 - axis_value)

    own_party_score = (
        _loyalty(norm_tax_high, ideology['tax_high']) +
        _loyalty(norm_welfare, ideology['welfare']) +
        _loyalty(norm_security, ideology['security'])
    ) / 3.0
    divergence = 1.0 - own_party_score  # 0 = loyal to own base, 1 = fully aligned with opposition

    # 0.9601 is the 4th root of the old 0.85 per-year pull-toward-current-
    # equilibrium factor; the injection magnitude is quartered to match.
    prev_opposition = prev_state['opposition_strength']
    opp_growth_mult = diff_settings["opposition_growth_mult"]
    opposition_strength = prev_opposition * 0.9601 + (divergence * 5.0 + max(0.0, (40.0 - new_happiness)) * 0.125) * opp_growth_mult
    opposition_strength = max(0.0, min(100.0, opposition_strength))

    if opposition_strength >= 50.0 and prev_opposition < 50.0:
        database.log_event(
            game_id, next_year, 'SOCIAL', "Momentum Oposisi Meningkat",
            f"{opposition_party} mulai mendapatkan dukungan publik akibat arah kebijakan Anda yang menjauh dari basis partai sendiri."
        )
    if opposition_strength >= 80.0 and prev_opposition < 80.0:
        database.log_event(
            game_id, next_year, 'SOCIAL', "Oposisi di Ambang Kekuatan Penuh",
            f"{opposition_party} kini sangat kuat dan mengancam menjatuhkan pemerintahan Anda melalui mosi tidak percaya."
        )

    # 8c. Election Cycle - every 20 turns / 5 years (all difficulties),
    # Approval Rating decides the outcome. app.py independently re-derives
    # the same formula from the saved state to decide the "voted_out"
    # game-over condition, so a strong mandate here (which lowers
    # opposition_strength) also keeps that check from failing right after
    # winning. turn_year is a 0-based turn index, so no offset is needed.
    quarters_since_start = next_year
    if quarters_since_start > 0 and quarters_since_start % ELECTION_TERM_QUARTERS == 0:
        approval_rating = 0.6 * new_happiness + 0.4 * (100.0 - opposition_strength)
        if approval_rating >= diff_settings["election_mandate_threshold"]:
            opposition_strength = max(0.0, opposition_strength - 15.0)
            database.log_event(
                game_id, next_year, 'SOCIAL', "Pemilu: Mandat Kuat",
                f"Rakyat memberikan mandat kuat untuk melanjutkan pemerintahan {party_name} dengan Approval Rating {approval_rating:.1f}%. Kekuatan oposisi mereda."
            )
        elif approval_rating >= diff_settings["election_narrow_threshold"]:
            database.log_event(
                game_id, next_year, 'SOCIAL', "Pemilu: Menang Tipis",
                f"{party_name} kembali terpilih dengan Approval Rating {approval_rating:.1f}%, namun koalisi pemerintahan rapuh dan oposisi tetap kuat."
            )
        else:
            database.log_event(
                game_id, next_year, 'SOCIAL', "Pemilu: Kalah",
                f"Approval Rating anjlok ke {approval_rating:.1f}%. Rakyat memilih {opposition_party} untuk memimpin pemerintahan baru."
            )

    # 9. Demographic Shifts & Mobility (all annual rates quartered)
    # Birth rate scales with happiness and healthcare index
    birth_rate = 0.003 + 0.002 * (new_happiness - 50.0) / 50.0
    birth_rate += 0.00075 * (health_index - 50.0) / 50.0
    if active_crisis and active_crisis['name'] == "The Demographic Cliff":
        birth_rate -= 0.0045 # Fertility drops drastically

    pop_growth = birth_rate - 0.002 # Subtract quarterly mortality rate
    pop_growth += perm_mods['pop_growth_mod']

    # Brain drain (high tax leads to emigration of rich people)
    emigrate_high = 0
    if tax_high > 0.40:
        emigrate_high = int(p_high * 0.03 * (tax_high - 0.40) / 0.10)
        p_high = max(1000, p_high - emigrate_high)
        database.log_event(
            game_id, next_year, 'SOCIAL', "Brain Drain Warning",
            f"Excessive tax rates on high-income bracket (>40%) have triggered brain drain. {emigrate_high:,} wealthy professionals emigrated."
        )

    if active_crisis and active_crisis['name'] == "The Brain Drain Crisis":
        # Additional loss during active crisis
        emigrate_crisis_high = int(p_high * 0.005)
        emigrate_crisis_mid = int(p_mid * 0.0025)
        p_high = max(1000, p_high - emigrate_crisis_high)
        p_mid = max(1000, p_mid - emigrate_crisis_mid)
        database.log_event(
            game_id, next_year, 'SOCIAL', "Talent Exodus",
            f"Talent flight: {emigrate_crisis_high:,} high-income and {emigrate_crisis_mid:,} middle-income citizens left Novus."
        )

    # Social Mobility: Education index promotes citizens upwards
    # Low-income promoted to Mid-income: up to 0.625% of low class per quarter
    promo_low_to_mid = int(p_low * 0.00625 * (education_index / 100.0))
    p_low -= promo_low_to_mid
    p_mid += promo_low_to_mid

    # Mid-income promoted to High-income: up to 0.3% of mid class per quarter
    promo_mid_to_high = int(p_mid * 0.003 * (education_index / 100.0))
    p_mid -= promo_mid_to_high
    p_high += promo_mid_to_high

    # Demotions: if GDP growth is negative, some workers drop brackets. No
    # separate rescaling needed here - gdp_growth is already quarterly-sized,
    # so the linear product naturally preserves the same annual total.
    if gdp_growth < 0:
        demote_high_to_mid = int(p_high * 0.03 * abs(gdp_growth))
        p_high -= demote_high_to_mid
        p_mid += demote_high_to_mid

        demote_mid_to_low = int(p_mid * 0.04 * abs(gdp_growth))
        p_mid -= demote_mid_to_low
        p_low += demote_mid_to_low

    # Aging: 0.3% of total working population (low+mid+high) retires and joins pensioners
    retirees = int((p_low + p_mid + p_high) * 0.003)
    # Distribute retirees proportionally
    ret_low = int(retirees * r_low)
    ret_mid = int(retirees * r_mid)
    ret_high = int(retirees * r_high)

    p_low = max(1000, p_low - ret_low)
    p_mid = max(1000, p_mid - ret_mid)
    p_high = max(1000, p_high - ret_high)
    p_elder += retirees

    # New births enter the low-income pool (or dependent child pool, mapped to low)
    new_births = int(p_total * birth_rate)
    # Deaths occur proportionally in all brackets, especially pensioners
    deaths_elder = int(p_elder * 0.00625) # quarterly mortality rate for elderly
    deaths_workers = int((p_low + p_mid + p_high) * 0.00125) # quarterly mortality rate for workers

    p_elder = max(1000, p_elder - deaths_elder)
    # Distribute worker deaths
    p_low = max(1000, p_low + new_births - int(deaths_workers * r_low))
    p_mid = max(1000, p_mid - int(deaths_workers * r_mid))
    p_high = max(1000, p_high - int(deaths_workers * r_high))

    new_p_total = p_low + p_mid + p_high + p_elder
    new_elder_ratio = p_elder / new_p_total

    # 9b. Dynamic Crisis Triggering
    # Instead of a fixed calendar year, each crisis fires once its matching
    # indicator crosses a critical level - different playthroughs run into
    # different crises depending on how the economy is actually managed.
    # A cooldown after the last crisis ends keeps them from stacking.
    if active_crisis is None:
        ended_years = [c['start_year'] + c['duration_turns'] for c in crises if c['status'] in ('SOLVED', 'FAILED') and c['start_year']]
        last_crisis_end = max(ended_years) if ended_years else -999
        if next_year - last_crisis_end >= CRISIS_COOLDOWN_QUARTERS:
            trigger_checks = [
                ("The Infrastructure Bottleneck", infrastructure < 35.0),
                ("The Public Health Epidemic", health_index < 35.0),
                ("The Brain Drain Crisis", tax_high >= 0.50),
                ("The Demographic Cliff", new_elder_ratio >= 0.22),
                ("The Carbon Transition Tariff", infrastructure >= 70.0),
                ("Krisis Utang Nasional", new_treasury < -(new_gdp * 0.80)),
                ("Gelombang Kriminalitas", crime_factor >= 0.45),
            ]
            for crisis_name, condition_met in trigger_checks:
                if not condition_met:
                    continue
                candidate = next((c for c in crises if c['name'] == crisis_name and c['status'] == 'INACTIVE'), None)
                if candidate is None:
                    continue
                database.update_crisis_state(candidate['crisis_id'], 0, 'ACTIVE', start_year=next_year)
                database.log_event(
                    game_id, next_year, 'CRISIS', f"CRISIS START: {crisis_name}",
                    f"Your administration faces a structural crisis: {candidate['description']} Goal: {candidate['requirement_desc']}"
                )
                break  # only one new crisis per turn

    # 10. Log Events in DB
    if shock_event:
        impacts = {'gdp': shock_value}
        if shock_event == "Cyber Ransom Attack":
            impacts['treasury'] = -round(gdp * 0.0075 * diff_settings["shock_severity_mult"], 1)
        elif shock_event == "Bencana Alam":
            impacts['treasury'] = -round(gdp * 0.005 * diff_settings["shock_severity_mult"], 1)
        elif shock_event == "Investasi Asing Mengalir":
            impacts['treasury'] = round(gdp * 0.005 * diff_settings["shock_severity_mult"], 1)
        database.log_event(game_id, next_year, 'ECONOMIC', f"EVENT: {shock_event}", shock_desc, impacts)

    if new_treasury < 0:
        database.log_event(
            game_id, next_year, 'ECONOMIC', "Debt Accumulation",
            f"{country_name} is running a sovereign debt of ${abs(new_treasury):.1f}B. Interest paid this quarter: ${debt_interest:.2f}B.",
            {'treasury_debt': debt_interest}
        )

    if new_happiness < 30:
        database.log_event(
            game_id, next_year, 'SOCIAL', "Widespread Protests",
            f"Low general happiness ({new_happiness:.1f}%) has triggered widespread labor strikes, reducing work productivity."
        )

    # 10b. News Feed Milestones - flavor & informational events tied to
    # economic/social indicators crossing a meaningful threshold this turn.
    # The GDP growth headline threshold is quartered to match the new
    # per-quarter growth scale.
    if gdp_growth >= 0.0125:
        database.log_event(
            game_id, next_year, 'ECONOMIC', "Ledakan Pertumbuhan Ekonomi",
            f"Pertumbuhan GDP mencapai {gdp_growth * 100:.1f}% kuartal ini, salah satu yang tertinggi dalam sejarah {country_name}."
        )

    if prev_state['treasury'] < 0 and new_treasury >= 0:
        database.log_event(
            game_id, next_year, 'ECONOMIC', "Utang Nasional Lunas!",
            f"Setelah bertahun-tahun defisit, treasury {country_name} kembali positif sebesar ${new_treasury:.1f}B."
        )

    if prev_state['education_index'] < 80.0 <= education_index:
        database.log_event(
            game_id, next_year, 'ECONOMIC', "Bangsa Terpelajar",
            "Indeks Pendidikan melampaui 80%, menempatkan tenaga kerja di jajaran paling terampil di dunia."
        )
    if prev_state['education_index'] >= 20.0 > education_index:
        database.log_event(
            game_id, next_year, 'SOCIAL', "Krisis Pendidikan Akut",
            "Indeks Pendidikan jatuh di bawah 20%, sekolah-sekolah kekurangan dana secara kronis."
        )

    if prev_state['health_index'] < 80.0 <= health_index:
        database.log_event(
            game_id, next_year, 'ECONOMIC', "Layanan Kesehatan Unggul",
            "Indeks Kesehatan melampaui 80%, harapan hidup warga meningkat signifikan."
        )
    if prev_state['health_index'] >= 20.0 > health_index:
        database.log_event(
            game_id, next_year, 'SOCIAL', "Sistem Kesehatan Kolaps",
            "Indeks Kesehatan jatuh di bawah 20%, rumah sakit kewalahan menangani pasien."
        )

    if prev_state['employment_rate'] < 0.95 <= new_employment:
        database.log_event(
            game_id, next_year, 'ECONOMIC', "Lapangan Kerja Penuh Tercapai",
            "Tingkat pengangguran mendekati nol, hampir seluruh angkatan kerja terserap."
        )
    if prev_state['employment_rate'] >= 0.50 > new_employment:
        database.log_event(
            game_id, next_year, 'SOCIAL', "Pengangguran Massal",
            "Tingkat kerja anjlok di bawah 50%, memicu keresahan sosial luas."
        )

    if crime_factor >= 0.30:
        database.log_event(
            game_id, next_year, 'SOCIAL', "Kriminalitas Meningkat",
            f"Indeks kriminalitas naik ke level mengkhawatirkan ({crime_factor * 100:.0f}%), warga menuntut penambahan anggaran keamanan."
        )

    if r_elder < 0.15 <= new_elder_ratio:
        database.log_event(
            game_id, next_year, 'SOCIAL', "Populasi Mulai Menua",
            "Proporsi warga lanjut usia melampaui 15% dari populasi, menandakan pergeseran struktur demografi."
        )

    total_promotions = promo_low_to_mid + promo_mid_to_high
    if total_promotions >= 0.00375 * new_p_total:
        database.log_event(
            game_id, next_year, 'ECONOMIC', "Mobilitas Sosial Pesat",
            f"{total_promotions:,} warga naik kelas ekonomi kuartal ini, didorong oleh investasi pendidikan yang kuat."
        )

    # Commit changes
    new_state = {
        'turn_year': next_year,
        'treasury': round(new_treasury, 2),
        'gdp': round(new_gdp, 2),
        'pop_low': p_low,
        'pop_mid': p_mid,
        'pop_high': p_high,
        'pop_elder': p_elder,
        'employment_rate': round(new_employment, 3),
        'crime_rate': round(crime_factor, 3),
        'happiness': round(new_happiness, 1),
        'happiness_low': round(h_low_stored, 1),
        'happiness_mid': round(h_mid_stored, 1),
        'happiness_high': round(h_high_stored, 1),
        'happiness_elder': round(h_elder_stored, 1),
        'education_index': round(education_index, 1),
        'health_index': round(health_index, 1),
        'infrastructure': round(infrastructure, 1),
        'opposition_strength': round(opposition_strength, 1),
        'corruption_index': round(corruption_index, 1),
        'foreign_relations': round(foreign_relations, 1),
        'coalition_support': round(coalition_support, 1),
        'tax_low': tax_low,
        'tax_mid': tax_mid,
        'tax_high': tax_high,
        'budget_education': b_ed,
        'budget_health': b_hl,
        'budget_infrastructure': b_inf,
        'budget_welfare': b_welf,
        'budget_security': b_sec,
        'min_wage': min_wage,
        'export_tariff': export_tariff,
        'import_tariff': import_tariff
    }

    database.save_turn_state(game_id, new_state)

    # 11. Random Narrative Event or Minister Advice - occasionally presents a
    # discrete choice (not a slider) with immediate consequences, resolved on
    # the next dashboard load before the player can end another fiscal
    # quarter. Only one pending decision fires per turn.
    if random.random() < 0.12:
        eligible = [key for key, ev in database.RANDOM_EVENTS.items() if ev['condition'](new_state)]
        if eligible:
            database.create_pending_event(game_id, random.choice(eligible), next_year)
    elif cabinet and random.random() < 0.35:
        database.create_minister_advice_event(game_id, next_year)

    return new_state
