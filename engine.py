import random
import json
import ledger_db as database

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
                modifiers['infra_efficiency'] = 1.15 # 15% more efficient building
            elif c['name'] == "The Public Health Epidemic":
                modifiers['health_bonus'] = 15.0 # Health stays higher
            elif c['name'] == "The Brain Drain Crisis":
                modifiers['gdp_growth_mod'] += 0.015 # Unlock high tech (+1.5% GDP growth)
            elif c['name'] == "The Demographic Cliff":
                modifiers['pop_growth_mod'] += 0.01 # Younger workforce (+1% pop growth)
            elif c['name'] == "The Carbon Transition Tariff":
                modifiers['gdp_growth_mod'] += 0.03 # Green exports (+3% GDP growth)
                
        elif c['status'] == 'FAILED':
            if c['name'] == "The Infrastructure Bottleneck":
                modifiers['gdp_growth_mod'] -= 0.01 # Blackouts penalty
            elif c['name'] == "The Public Health Epidemic":
                modifiers['gdp_growth_mod'] -= 0.015 # Sick workforce
            elif c['name'] == "The Brain Drain Crisis":
                modifiers['gdp_growth_mod'] -= 0.02 # Brain drain penalty
            elif c['name'] == "The Demographic Cliff":
                modifiers['gdp_growth_mod'] -= 0.02 # Aging population penalty
            elif c['name'] == "The Carbon Transition Tariff":
                modifiers['gdp_growth_mod'] -= 0.03 # Sanctions penalty
                
    return modifiers

def simulate_turn(game_id, inputs):
    """
    Simulates a year (turn) of the nation based on player inputs and previous turn history.
    Now supports demographic cohorts (Low, Mid, High, Pensioners) and 3 tax brackets.
    """
    prev_state = database.get_latest_turn(game_id)
    if not prev_state:
        raise ValueError("No game state found. Please initialize the game first.")
    
    current_year = prev_state['turn_year']
    next_year = current_year + 1
    country_name = database.get_country_name(game_id)
    
    # 1. Gather Inputs (3 tax brackets, 5 budget allocations)
    tax_low = inputs['tax_low']
    tax_mid = inputs['tax_mid']
    tax_high = inputs['tax_high']
    b_ed = inputs['budget_education']
    b_hl = inputs['budget_health']
    b_inf = inputs['budget_infrastructure']
    b_welf = inputs['budget_welfare']
    b_sec = inputs['budget_security']
    
    total_spending = b_ed + b_hl + b_inf + b_welf + b_sec
    gdp = prev_state['gdp']
    
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
    
    # 3. Retrieve Crises
    crises = database.get_crises(game_id)
    active_crisis = None
    
    # Activate and check crises
    for c in crises:
        if next_year == c['start_year']:
            c['status'] = 'ACTIVE'
            database.update_crisis_state(c['crisis_id'], 0, 'ACTIVE')
            database.log_event(
                game_id, next_year, 'CRISIS', f"CRISIS START: {c['name']}",
                f"Your administration faces a structural crisis: {c['description']} Goal: {c['requirement_desc']}"
            )
        
        if c['status'] == 'ACTIVE':
            active_crisis = c
            
    # Apply active crisis rules & verify progress conditions
    crisis_penalty_text = ""
    crisis_progress_text = ""
    
    if active_crisis:
        met_condition = False
        name = active_crisis['name']
        
        if name == "The Infrastructure Bottleneck":
            # Requirement: Infrastructure budget >= 1.5% of GDP
            if b_inf >= 0.015 * gdp:
                met_condition = True
            crisis_penalty_text = "Infrastructure bottleneck limits maximum GDP growth to 1.5% and hurts happiness."
            
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
            # Requirement: Welfare budget >= 3% of GDP OR combined Security & Infrastructure spending >= 15% of total budget
            if (b_welf >= 0.03 * gdp) or ((b_sec + b_inf) >= 0.15 * total_spending):
                met_condition = True
            crisis_penalty_text = "Aging population reduces tax collection efficiency by 20% and inflates welfare costs."
            
        elif name == "The Carbon Transition Tariff":
            # Requirement: Infrastructure >= 2.0% of GDP AND Security >= 0.5% of GDP
            if (b_inf >= 0.02 * gdp) and (b_sec >= 0.005 * gdp):
                met_condition = True
            crisis_penalty_text = "Carbon tariffs are weighing heavily on GDP growth (-4.0% per turn)."
            
        # Update progress
        new_progress = active_crisis['current_progress']
        if met_condition:
            new_progress += 1
            crisis_progress_text = f"CRISIS UPDATE: Requirement met this year! Progress: {new_progress}/{active_crisis['target_progress']}."
            database.log_event(game_id, next_year, 'CRISIS', f"Crisis Progress: {active_crisis['name']}", crisis_progress_text)
        else:
            crisis_progress_text = f"CRISIS UPDATE: Objective NOT met this year. Progress: {new_progress}/{active_crisis['target_progress']}."
            database.log_event(game_id, next_year, 'CRISIS', f"Crisis Alert: {active_crisis['name']}", crisis_progress_text)
            
        # Check resolved or failed status at the end of the year
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
    education_decay = 0.95
    if active_crisis and active_crisis['name'] == "The Brain Drain Crisis":
        education_decay = 0.90 # Brain drain increases loss of skill
    education_index = prev_state['education_index'] * education_decay + 100 * ed_ratio
    education_index = max(0.0, min(100.0, education_index))
    
    health_decay = 0.95
    if active_crisis and active_crisis['name'] == "The Public Health Epidemic":
        health_decay = 0.85 # Epidemic decays health faster
    health_bonus = perm_mods['health_bonus']
    health_index = prev_state['health_index'] * health_decay + 100 * hl_ratio + health_bonus
    health_index = max(0.0, min(100.0, health_index))
    
    infra_efficiency = perm_mods['infra_efficiency']
    infrastructure = prev_state['infrastructure'] * 0.93 + 120 * inf_ratio * infra_efficiency
    infrastructure = max(0.0, min(100.0, infrastructure))
    
    # 5. Economic simulation
    # Calculate average tax rate weighted by population
    avg_tax_rate = r_low * tax_low + r_mid * tax_mid + r_high * tax_high
    
    # Base GDP growth
    growth_base = 0.045 * (education_index / 100.0) * (infrastructure / 100.0) - 0.16 * avg_tax_rate
    growth_base += perm_mods['gdp_growth_mod']
    
    if active_crisis and active_crisis['name'] == "The Carbon Transition Tariff":
        growth_base -= 0.04 # Carbon sanctions
        
    # Global economic market shock
    shock_event = None
    shock_value = 0.0
    shock_desc = ""
    rand_val = random.random()
    if rand_val < 0.10: # Global Recession
        shock_event = "Global Recession"
        shock_value = -0.03
        shock_desc = "A major contraction in global markets drops Novus's GDP growth by -3.0%."
    elif rand_val < 0.18: # Commodity Boom
        shock_event = "Resource Market Boom"
        shock_value = 0.02
        shock_desc = "High global demand for exports boosts Novus's GDP growth by +2.0%."
    elif rand_val < 0.22: # Cyber attack
        shock_event = "Cyber Ransom Attack"
        shock_value = -0.01
        # Stolen cash scales with GDP size
        stolen_cash = round(gdp * 0.03, 1) # 3% of GDP
        shock_desc = f"Hackers disrupt digital infrastructure, lowering GDP by -1.0% and stealing ${stolen_cash}B from treasury."
    elif rand_val < 0.27: # Tech boom
        shock_event = "AI Core Breakthrough"
        shock_value = 0.035
        shock_desc = "Local researchers invent an optimized automation algorithm. GDP growth surges by +3.5%!"
    else:
        # Standard slight volatility
        shock_value = random.uniform(-0.005, 0.005)
        
    gdp_growth = growth_base + shock_value
    
    # Cap growth during Infrastructure crisis
    if active_crisis and active_crisis['name'] == "The Infrastructure Bottleneck":
        gdp_growth = min(gdp_growth, 0.015)
        
    new_gdp = gdp * (1.0 + gdp_growth)
    new_gdp = max(10.0, new_gdp)
    
    # 6. Revenues (Class-based tax contributions)
    # Low-income generates less tax per capita; High-income generates much more.
    tax_eff = 0.90 + 0.10 * (education_index / 100.0)
    if active_crisis and active_crisis['name'] == "The Demographic Cliff":
        tax_eff *= 0.80 # 20% loss due to smaller active working class
        
    emp = prev_state['employment_rate']
    rev_low = new_gdp * r_low * tax_low * emp * 0.5
    rev_mid = new_gdp * r_mid * tax_mid * emp * 1.0
    rev_high = new_gdp * r_high * tax_high * emp * 2.5
    
    revenue = (rev_low + rev_mid + rev_high) * tax_eff
    
    # Debt Interest (6% per year on national debt)
    debt_interest = 0.0
    if prev_state['treasury'] < 0:
        debt_interest = abs(prev_state['treasury']) * 0.06
        
    total_costs = total_spending + debt_interest
    
    if shock_event == "Cyber Ransom Attack":
        total_costs += round(gdp * 0.03, 1)
        
    new_treasury = prev_state['treasury'] + revenue - total_costs
    
    # 7. Labor & Welfare Calculations
    new_employment = 0.82 + 0.4 * gdp_growth + 0.05 * (infrastructure / 100.0) - 0.12 * avg_tax_rate
    new_employment = max(0.40, min(0.98, new_employment))
    
    # Crime Factor
    target_security = new_gdp * 0.025
    sec_factor = min(1.0, b_sec / max(0.1, target_security))
    crime_factor = max(0.0, 1.0 - (0.6 * sec_factor + 0.4 * new_employment))
    
    # Welfare efficiency
    welf_efficiency = 1.0
    if active_crisis and active_crisis['name'] == "The Demographic Cliff":
        welf_efficiency = 1.3 # 30% higher demand / cost dilution
    welfare_ratio = (b_welf / welf_efficiency) / max(1.0, new_gdp * 0.05)
    
    # 8. Class-Specific Happiness
    # Low-income: highly sensitive to tax_low and welfare
    h_low = 35.0 + 35.0 * new_employment + 25.0 * min(1.0, welfare_ratio) - 50.0 * tax_low - 20.0 * crime_factor
    # Middle-income: balanced sensitivity
    h_mid = 45.0 + 30.0 * new_employment + 15.0 * min(1.0, welfare_ratio) - 40.0 * tax_mid - 12.0 * crime_factor
    # High-income: highly sensitive to high taxes
    h_high = 55.0 + 20.0 * new_employment - 60.0 * tax_high - 6.0 * crime_factor
    # Pensioners: highly sensitive to health and welfare
    h_elder = 30.0 + 35.0 * (health_index / 100.0) + 35.0 * min(1.0, welfare_ratio) - 10.0 * crime_factor
    
    # Weighted average happiness
    new_happiness = r_low * h_low + r_mid * h_mid + r_high * h_high + r_elder * h_elder
    
    if active_crisis:
        if active_crisis['name'] == "The Infrastructure Bottleneck":
            new_happiness -= 6.0
        elif active_crisis['name'] == "The Public Health Epidemic":
            new_happiness -= 8.0
            
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
    norm_welfare = min(1.0, (b_welf / new_gdp) / 0.06)
    norm_security = min(1.0, (b_sec / new_gdp) / 0.04)

    def _loyalty(axis_value, sign):
        return axis_value if sign > 0 else (1.0 - axis_value)

    own_party_score = (
        _loyalty(norm_tax_high, ideology['tax_high']) +
        _loyalty(norm_welfare, ideology['welfare']) +
        _loyalty(norm_security, ideology['security'])
    ) / 3.0
    divergence = 1.0 - own_party_score  # 0 = loyal to own base, 1 = fully aligned with opposition

    prev_opposition = prev_state['opposition_strength']
    opposition_strength = prev_opposition * 0.85 + divergence * 20.0 + max(0.0, (40.0 - new_happiness)) * 0.5
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

    # 9. Demographic Shifts & Mobility
    # Birth rate scales with happiness and healthcare index
    birth_rate = 0.012 + 0.008 * (new_happiness - 50.0) / 50.0
    birth_rate += 0.003 * (health_index - 50.0) / 50.0
    if active_crisis and active_crisis['name'] == "The Demographic Cliff":
        birth_rate -= 0.018 # Fertility drops drastically
        
    pop_growth = birth_rate - 0.008 # Subtract 0.8% mortality rate
    pop_growth += perm_mods['pop_growth_mod']
    
    # Brain drain (high tax leads to emigration of rich people)
    emigrate_high = 0
    if tax_high > 0.40:
        emigrate_high = int(p_high * 0.12 * (tax_high - 0.40) / 0.10)
        p_high = max(1000, p_high - emigrate_high)
        database.log_event(
            game_id, next_year, 'SOCIAL', "Brain Drain Warning",
            f"Excessive tax rates on high-income bracket (>40%) have triggered brain drain. {emigrate_high:,} wealthy professionals emigrated."
        )
        
    if active_crisis and active_crisis['name'] == "The Brain Drain Crisis":
        # Additional loss during active crisis
        emigrate_crisis_high = int(p_high * 0.02)
        emigrate_crisis_mid = int(p_mid * 0.01)
        p_high = max(1000, p_high - emigrate_crisis_high)
        p_mid = max(1000, p_mid - emigrate_crisis_mid)
        database.log_event(
            game_id, next_year, 'SOCIAL', "Talent Exodus",
            f"Talent flight: {emigrate_crisis_high:,} high-income and {emigrate_crisis_mid:,} middle-income citizens left Novus."
        )
        
    # Social Mobility: Education index promotes citizens upwards
    # Low-income promoted to Mid-income: up to 2.5% of low class per year
    promo_low_to_mid = int(p_low * 0.025 * (education_index / 100.0))
    p_low -= promo_low_to_mid
    p_mid += promo_low_to_mid
    
    # Mid-income promoted to High-income: up to 1.2% of mid class per year
    promo_mid_to_high = int(p_mid * 0.012 * (education_index / 100.0))
    p_mid -= promo_mid_to_high
    p_high += promo_mid_to_high
    
    # Demotions: if GDP growth is negative, some workers drop brackets
    if gdp_growth < 0:
        demote_high_to_mid = int(p_high * 0.03 * abs(gdp_growth))
        p_high -= demote_high_to_mid
        p_mid += demote_high_to_mid
        
        demote_mid_to_low = int(p_mid * 0.04 * abs(gdp_growth))
        p_mid -= demote_mid_to_low
        p_low += demote_mid_to_low
        
    # Aging: 1.2% of total working population (low+mid+high) retires and joins pensioners
    retirees = int((p_low + p_mid + p_high) * 0.012)
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
    deaths_elder = int(p_elder * 0.025) # 2.5% mortality rate for elderly
    deaths_workers = int((p_low + p_mid + p_high) * 0.005) # 0.5% mortality rate for workers
    
    p_elder = max(1000, p_elder - deaths_elder)
    # Distribute worker deaths
    p_low = max(1000, p_low + new_births - int(deaths_workers * r_low))
    p_mid = max(1000, p_mid - int(deaths_workers * r_mid))
    p_high = max(1000, p_high - int(deaths_workers * r_high))
    
    # 10. Log Events in DB
    if shock_event:
        impacts = {'gdp': shock_value}
        if shock_event == "Cyber Ransom Attack":
            impacts['treasury'] = -round(gdp * 0.03, 1)
        database.log_event(game_id, next_year, 'ECONOMIC', f"EVENT: {shock_event}", shock_desc, impacts)
        
    if new_treasury < 0:
        database.log_event(
            game_id, next_year, 'ECONOMIC', "Debt Accumulation", 
            f"{country_name} is running a sovereign debt of ${abs(new_treasury):.1f}B. Interest paid this year: ${debt_interest:.2f}B.",
            {'treasury_debt': debt_interest}
        )
        
    if new_happiness < 30:
        database.log_event(
            game_id, next_year, 'SOCIAL', "Widespread Protests", 
            f"Low general happiness ({new_happiness:.1f}%) has triggered widespread labor strikes, reducing work productivity."
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
        'happiness': round(new_happiness, 1),
        'education_index': round(education_index, 1),
        'health_index': round(health_index, 1),
        'infrastructure': round(infrastructure, 1),
        'opposition_strength': round(opposition_strength, 1),
        'tax_low': tax_low,
        'tax_mid': tax_mid,
        'tax_high': tax_high,
        'budget_education': b_ed,
        'budget_health': b_hl,
        'budget_infrastructure': b_inf,
        'budget_welfare': b_welf,
        'budget_security': b_sec
    }
    
    database.save_turn_state(game_id, new_state)
    return new_state
