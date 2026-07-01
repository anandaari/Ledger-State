import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import ledger_db as database
import engine
from i18n import t

# Page configuration
st.set_page_config(
    page_title="Ledger State: Macroeconomic Simulator",
    layout="wide",
    initial_sidebar_state="expanded"
)


# Main logic
def main():
    # Always verify/repair the DB schema on boot - not just when a new game is
    # created - so a stale ledger.db left over from an older deploy (missing
    # newer columns like corruption_index/crime_rate) can't crash the dashboard.
    database.init_db()

    if 'lang' not in st.session_state:
        st.session_state.lang = 'id'

    col_title, col_lang = st.columns([5, 1])
    with col_title:
        st.title("🏛️ LEDGER STATE")
    with col_lang:
        lang_choice = st.selectbox(
            t(st.session_state.lang, "language_label"),
            ["Bahasa Indonesia", "English"],
            index=0 if st.session_state.lang == 'id' else 1,
            label_visibility="collapsed"
        )
        st.session_state.lang = 'id' if lang_choice == "Bahasa Indonesia" else 'en'
    lang = st.session_state.lang

    st.write(t(lang, "app_tagline"))
    st.divider()

    # Session State Game Initialization
    if 'game_id' not in st.session_state:
        st.session_state.game_id = None

    if st.session_state.game_id is None:
        show_start_screen(lang)
    else:
        show_dashboard(st.session_state.game_id, lang)

def show_start_screen(lang):
    st.subheader(t(lang, "start_subheader"))
    st.write(t(lang, "start_description"))

    col1, col2 = st.columns(2)
    with col1:
        nation_name = st.text_input(t(lang, "label_regime_name"), value="Regime I", max_chars=30)
        country_name = st.selectbox(t(lang, "label_select_country"), ["Indonesia", "Singapore", "United States", "Japan", "Germany"])
        difficulty = st.selectbox(t(lang, "label_difficulty"), ["Easy", "Medium", "Hard"])

        # Display description of starting presets
        preset = database.COUNTRY_PRESETS[country_name]
        total_starting_pop = preset["pop_low"] + preset["pop_mid"] + preset["pop_high"] + preset["pop_elder"]

        treasury_status = t(lang, "surplus_reserves") if preset['treasury'] >= 0 else t(lang, "national_debt")
        st.markdown(f"""
        {t(lang, "country_briefing_title", country=country_name)}
        * {t(lang, "label_starting_population", value=total_starting_pop / 1000000)}
        * {t(lang, "label_starting_gdp", value=database.format_currency(preset['gdp'], country_name))}
        * {t(lang, "label_starting_treasury", value=database.format_currency(preset['treasury'], country_name), status=treasury_status)}
        * {t(lang, "label_demographics")}
          * {t(lang, "label_low_income")}: {preset['pop_low'] / total_starting_pop * 100:.1f}%
          * {t(lang, "label_mid_income")}: {preset['pop_mid'] / total_starting_pop * 100:.1f}%
          * {t(lang, "label_high_income")}: {preset['pop_high'] / total_starting_pop * 100:.1f}%
          * {t(lang, "label_pensioners")}: {preset['pop_elder'] / total_starting_pop * 100:.1f}%
        """)

        st.info(t(lang, "difficulty_info"))

    with col2:
        st.write(t(lang, "political_affiliation_header"))
        party_name = st.radio(t(lang, "label_choose_party"), list(database.PARTY_PRESETS.keys()))
        opposition_party = database.get_opposition_party(party_name)

        st.markdown(f"""
        **{party_name}** {t(lang, "your_party_suffix")}
        {database.PARTY_PRESETS[party_name]['tagline']}

        **{opposition_party}** {t(lang, "auto_opposition_suffix")}
        {database.PARTY_PRESETS[opposition_party]['tagline']}
        """)
        st.warning(t(lang, "opposition_warning"))

    if st.button(t(lang, "begin_button"), type="primary"):
        # Create a new game in DB and store id in session
        game_id = database.create_new_game(nation_name, country_name, difficulty, party_name)
        st.session_state.game_id = game_id
        st.rerun()

def show_dashboard(game_id, lang):
    # 1. Fetch current game state
    latest_state = database.get_latest_turn(game_id)
    if not latest_state:
        st.warning("Game data missing. Resetting game session.")
        st.session_state.game_id = None
        st.rerun()

    country_name = database.get_country_name(game_id)

    def fmt_money(amount, decimals=1, signed=False):
        s = database.format_currency(amount, country_name, decimals=decimals)
        return f"+{s}" if signed and amount >= 0 else s

    party_name = database.get_party_name(game_id)
    opposition_party = database.get_opposition_party(party_name)
    history = database.get_history(game_id)
    df_history = pd.DataFrame(history, columns=[
        'turn_year', 'treasury', 'gdp', 'population', 'employment_rate', 'happiness',
        'education_index', 'health_index', 'infrastructure', 'tax_low', 'tax_mid', 'tax_high',
        'pop_low', 'pop_mid', 'pop_high', 'pop_elder', 'opposition_strength', 'corruption_index', 'crime_rate'
    ])

    p_low = latest_state['pop_low']
    p_mid = latest_state['pop_mid']
    p_high = latest_state['pop_high']
    p_elder = latest_state['pop_elder']
    p_total = p_low + p_mid + p_high + p_elder

    # 2. Check Game Over / Win Conditions
    is_game_over = False
    game_over_reason = ""

    # Condition A: Sovereign Default (Debt > 150% of GDP)
    if latest_state['treasury'] < -(latest_state['gdp'] * 1.5):
        is_game_over = True
        game_over_reason = "bankruptcy"

    # Condition B: Coup / Revolution (Happiness drops below 20% two years in a row)
    if len(df_history) >= 2:
        last_two_happiness = df_history['happiness'].iloc[-2:].values
        if all(h < 20.0 for h in last_two_happiness):
            is_game_over = True
            game_over_reason = "coup"

    # Condition C: Vote of No Confidence (Opposition Strength >= 85% two years in a row)
    if len(df_history) >= 2:
        last_two_opposition = df_history['opposition_strength'].iloc[-2:].values
        if all(o >= 85.0 for o in last_two_opposition):
            is_game_over = True
            game_over_reason = "no_confidence"

    # Condition D: Election Defeat (every 5 years, Approval Rating < 40%)
    years_since_start = latest_state['turn_year'] - 2026
    if years_since_start > 0 and years_since_start % 5 == 0:
        approval_rating = 0.6 * latest_state['happiness'] + 0.4 * (100.0 - latest_state['opposition_strength'])
        if approval_rating < 40.0:
            is_game_over = True
            game_over_reason = "voted_out"

    # Condition E: Completed 50 Years (starting 2026, so 2076 is Turn 50) -
    # skipped once the player has opted into Sandbox Mode (unlimited years)
    sandbox_mode = database.get_sandbox_mode(game_id)
    if latest_state['turn_year'] >= 2076 and not sandbox_mode:
        is_game_over = True
        game_over_reason = "victory"

    if is_game_over:
        show_game_over_screen(latest_state, df_history, game_over_reason, country_name, game_id, lang)
        return

    # 3. Sidebar Inputs (Policy Control)
    st.sidebar.subheader(t(lang, "sidebar_cabinet_actions"))
    st.sidebar.write(t(lang, "sidebar_country", country=country_name))
    st.sidebar.write(t(lang, "sidebar_simulated_years", years=df_history['turn_year'].count() - 1))

    # Election countdown - term is 5 years for every difficulty
    years_since_start = latest_state['turn_year'] - 2026
    remainder = years_since_start % 5
    years_to_election = 5 - remainder if remainder != 0 else 5
    st.sidebar.info(t(lang, "election_countdown", years=years_to_election, year=latest_state['turn_year'] + years_to_election))

    # Fetch active crisis list to display warnings in Sidebar and Main Page
    crises = database.get_crises(game_id)
    active_crisis = next((c for c in crises if c['status'] == 'ACTIVE'), None)

    pending_event = database.get_pending_event(game_id)
    if pending_event:
        st.sidebar.warning(t(lang, "pending_event_sidebar_warning"))

    st.sidebar.divider()

    # Slider & inputs inside a Form
    with st.sidebar.form("budget_form"):
        st.write(t(lang, "tax_brackets_header"))
        tax_low_pct = st.slider(t(lang, "tax_low_label"), 0, 50, int(latest_state['tax_low'] * 100), step=1,
                                 help=t(lang, "tax_low_help"))
        tax_mid_pct = st.slider(t(lang, "tax_mid_label"), 0, 70, int(latest_state['tax_mid'] * 100), step=1,
                                 help=t(lang, "tax_mid_help"))
        tax_high_pct = st.slider(t(lang, "tax_high_label"), 0, 90, int(latest_state['tax_high'] * 100), step=1,
                                  help=t(lang, "tax_high_help"))

        tax_low = tax_low_pct / 100.0
        tax_mid = tax_mid_pct / 100.0
        tax_high = tax_high_pct / 100.0

        st.write(t(lang, "macro_policy_header"))
        min_wage = st.slider(
            t(lang, "min_wage_label"), 0, 100, int(latest_state['min_wage']), step=1,
            help=t(lang, "min_wage_help")
        )
        export_tariff = st.slider(
            t(lang, "export_tariff_label"), 0, 30, int(latest_state['export_tariff']), step=1,
            help=t(lang, "export_tariff_help")
        )

        st.write(t(lang, "spending_header"))
        # Range is 0 to GDP/2 for each allocation
        max_budget = float(latest_state['gdp'] / 2.0)
        b_ed = st.number_input(t(lang, "edu_budget_label"), min_value=0.0, max_value=max_budget, value=float(latest_state['budget_education']), step=0.1,
                                help=t(lang, "edu_budget_help"))
        b_hl = st.number_input(t(lang, "health_budget_label"), min_value=0.0, max_value=max_budget, value=float(latest_state['budget_health']), step=0.1,
                                help=t(lang, "health_budget_help"))
        b_inf = st.number_input(t(lang, "infra_budget_label"), min_value=0.0, max_value=max_budget, value=float(latest_state['budget_infrastructure']), step=0.1,
                                 help=t(lang, "infra_budget_help"))
        b_welf = st.number_input(t(lang, "welfare_budget_label"), min_value=0.0, max_value=max_budget, value=float(latest_state['budget_welfare']), step=0.1,
                                  help=t(lang, "welfare_budget_help"))
        b_sec = st.number_input(t(lang, "security_budget_label"), min_value=0.0, max_value=max_budget, value=float(latest_state['budget_security']), step=0.1,
                                 help=t(lang, "security_budget_help"))

        # Real-time balances
        total_spending = b_ed + b_hl + b_inf + b_welf + b_sec
        debt_interest = abs(latest_state['treasury']) * 0.06 if latest_state['treasury'] < 0 else 0.0
        total_outflow = total_spending + debt_interest

        # Approximate Revenue calculation
        tax_eff = 0.90 + 0.10 * (latest_state['education_index'] / 100.0)
        if active_crisis and active_crisis['name'] == "The Demographic Cliff":
            tax_eff *= 0.80

        emp = latest_state['employment_rate']
        rev_low = latest_state['gdp'] * (p_low / p_total) * tax_low * emp * 0.5
        rev_mid = latest_state['gdp'] * (p_mid / p_total) * tax_mid * emp * 1.0
        rev_high = latest_state['gdp'] * (p_high / p_total) * tax_high * emp * 2.5
        projected_rev = (rev_low + rev_mid + rev_high) * tax_eff

        export_dependency = database.COUNTRY_PRESETS[country_name]['export_dependency']
        projected_rev += latest_state['gdp'] * export_dependency * (export_tariff / 100.0) * 0.5

        projected_net = projected_rev - total_outflow

        st.write("---")
        st.write(t(lang, "projected_inflow", value=database.format_currency(projected_rev, country_name, decimals=2)))
        st.write(t(lang, "projected_outflow", value=database.format_currency(total_outflow, country_name, decimals=2)))

        if projected_net >= 0:
            st.success(t(lang, "surplus_label", value=database.format_currency(projected_net, country_name, decimals=2)))
        else:
            st.error(t(lang, "deficit_label", value=database.format_currency(abs(projected_net), country_name, decimals=2)))

        if pending_event:
            st.warning(t(lang, "pending_event_form_warning"))
        submit_btn = st.form_submit_button(t(lang, "end_fiscal_year_button", year=latest_state['turn_year']), disabled=bool(pending_event))

        if submit_btn and not pending_event:
            inputs = {
                'tax_low': tax_low,
                'tax_mid': tax_mid,
                'tax_high': tax_high,
                'budget_education': b_ed,
                'budget_health': b_hl,
                'budget_infrastructure': b_inf,
                'budget_welfare': b_welf,
                'budget_security': b_sec,
                'min_wage': min_wage,
                'export_tariff': export_tariff
            }
            engine.simulate_turn(game_id, inputs)
            st.rerun()

    st.sidebar.divider()
    st.sidebar.caption(t(lang, "bribe_caption"))
    bribe_key = f"bribed_{game_id}_{latest_state['turn_year']}"
    already_bribed = st.session_state.get(bribe_key, False)
    if st.sidebar.button(t(lang, "bribe_button", amount=fmt_money(100)), disabled=already_bribed):
        database.apply_bribe(game_id)
        st.session_state[bribe_key] = True
        st.rerun()
    if already_bribed:
        st.sidebar.caption(t(lang, "bribe_done_caption"))

    st.sidebar.divider()
    if st.sidebar.button(t(lang, "abandon_button"), type="secondary"):
        st.session_state.game_id = None
        st.rerun()

    # 4. Main UI Layout - Command Center (dense monitoring, minimal scrolling)

    # Pending Random Event - a discrete narrative choice that must be
    # resolved before the fiscal year can end. Shown prominently at the top;
    # the rest of the dashboard still renders below for context.
    if pending_event:
        event = database.RANDOM_EVENTS[pending_event['event_key']]
        st.warning(t(lang, "pending_event_header", title=event['title']))
        st.write(event['description'])
        choice_cols = st.columns(len(event['choices']))
        for i, choice_label in enumerate(event['choices'].keys()):
            with choice_cols[i]:
                if st.button(choice_label, key=f"event_choice_{i}", type="primary", width="stretch"):
                    database.resolve_pending_event(game_id, pending_event['event_key'], choice_label)
                    st.rerun()
        st.divider()

    st.subheader(t(lang, "year_header", country=country_name, year=latest_state['turn_year']))
    if sandbox_mode:
        st.caption(t(lang, "sandbox_caption"))

    # Row 1: Key Performance Indicators (KPIs)
    col1, col2, col3, col4 = st.columns(4)

    # Calculate differentials (deltas) from previous turns for visual metrics
    gdp_delta = 0.0
    treasury_delta = 0.0
    happiness_delta = 0.0
    pop_delta = 0.0

    if len(df_history) >= 2:
        gdp_delta = float(df_history['gdp'].iloc[-1] - df_history['gdp'].iloc[-2])
        treasury_delta = float(df_history['treasury'].iloc[-1] - df_history['treasury'].iloc[-2])
        happiness_delta = float(df_history['happiness'].iloc[-1] - df_history['happiness'].iloc[-2])
        pop_delta = int(df_history['population'].iloc[-1] - df_history['population'].iloc[-2])

    with col1:
        st.metric(t(lang, "kpi_gdp_label"),
                  fmt_money(latest_state['gdp']),
                  delta=f"{fmt_money(gdp_delta, signed=True)} ({((gdp_delta)/max(1.0, latest_state['gdp']-gdp_delta))*100:.1f}%)",
                  help=t(lang, "kpi_gdp_help"))
    with col2:
        st.metric(t(lang, "kpi_treasury_label"),
                  fmt_money(latest_state['treasury']),
                  delta=fmt_money(treasury_delta, signed=True),
                  delta_color="normal" if latest_state['treasury'] >= 0 else "inverse",
                  help=t(lang, "kpi_treasury_help"))
    with col3:
        st.metric(t(lang, "kpi_happiness_label"),
                  f"{latest_state['happiness']:.1f}%",
                  delta=f"{happiness_delta:+.1f}%",
                  delta_color="normal" if latest_state['happiness'] >= 40 else "inverse",
                  help=t(lang, "kpi_happiness_help"))
    with col4:
        st.metric(t(lang, "kpi_population_label"),
                  f"{p_total:,}",
                  delta=t(lang, "kpi_population_delta", value=pop_delta),
                  help=t(lang, "kpi_population_help"))

    st.divider()

    # Row 2: Monitoring Ekonomi, Sosial & Politik - one dense glance, no extra headers
    employment_pct = latest_state['employment_rate'] * 100.0
    crime_pct = latest_state['crime_rate'] * 100.0
    debt_to_gdp_pct = (latest_state['treasury'] / latest_state['gdp']) * 100.0
    opp_strength = latest_state['opposition_strength']
    corruption = latest_state['corruption_index']
    approval_rating = 0.6 * latest_state['happiness'] + 0.4 * (100.0 - opp_strength)

    employment_delta = 0.0
    crime_delta = 0.0
    debt_to_gdp_delta = 0.0
    approval_delta = 0.0
    if len(df_history) >= 2:
        employment_delta = float((df_history['employment_rate'].iloc[-1] - df_history['employment_rate'].iloc[-2]) * 100.0)
        crime_delta = float((df_history['crime_rate'].iloc[-1] - df_history['crime_rate'].iloc[-2]) * 100.0)
        prev_debt_to_gdp = (df_history['treasury'].iloc[-2] / df_history['gdp'].iloc[-2]) * 100.0
        debt_to_gdp_delta = debt_to_gdp_pct - prev_debt_to_gdp
        prev_approval = 0.6 * df_history['happiness'].iloc[-2] + 0.4 * (100.0 - df_history['opposition_strength'].iloc[-2])
        approval_delta = approval_rating - prev_approval

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.metric(t(lang, "monitor_employment_label"), f"{employment_pct:.1f}%", delta=f"{employment_delta:+.1f}%",
                   help=t(lang, "monitor_employment_help"))
    with col_m2:
        st.metric(t(lang, "monitor_crime_label"), f"{crime_pct:.1f}%", delta=f"{crime_delta:+.1f}%", delta_color="inverse",
                   help=t(lang, "monitor_crime_help"))
    with col_m3:
        st.metric(t(lang, "monitor_debt_gdp_label"), f"{debt_to_gdp_pct:.1f}%", delta=f"{debt_to_gdp_delta:+.1f}%",
                   help=t(lang, "monitor_debt_gdp_help"))
    with col_m4:
        st.metric(t(lang, "monitor_approval_label"), f"{approval_rating:.1f}%", delta=f"{approval_delta:+.1f}%",
                   help=t(lang, "monitor_approval_help"))

    opp_status = t(lang, "opposition_status_critical") if opp_strength >= 80 else (t(lang, "opposition_status_watch") if opp_strength >= 50 else t(lang, "opposition_status_ok"))
    corruption_status = t(lang, "corruption_status_severe") if corruption >= 50 else (t(lang, "corruption_status_watch") if corruption >= 20 else t(lang, "corruption_status_clean"))
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.progress(opp_strength / 100.0, text=t(lang, "opposition_progress_text", party=opposition_party, value=opp_strength, status=opp_status))
        st.caption(t(lang, "opposition_caption"))
    with col_p2:
        st.progress(corruption / 100.0, text=t(lang, "corruption_progress_text", value=corruption, status=corruption_status))
        st.caption(t(lang, "corruption_caption"))
    if opp_strength >= 80:
        st.error(t(lang, "opposition_critical_warning"))

    st.divider()

    # Row 3: Crisis and Alert Center
    if active_crisis:
        st.error(t(lang, "crisis_header", name=active_crisis['name']))
        st.write(t(lang, "crisis_briefing", desc=active_crisis['description']))
        st.write(t(lang, "crisis_required_policy", desc=active_crisis['requirement_desc']))

        # Render a progress bar visual
        progress_val = float(active_crisis['current_progress'] / active_crisis['target_progress'])
        st.progress(progress_val, text=t(lang, "crisis_progress_text", current=active_crisis['current_progress'], target=active_crisis['target_progress']))

        turns_left = active_crisis['duration_turns'] - (latest_state['turn_year'] - active_crisis['start_year'] + 1)
        st.write(t(lang, "crisis_years_remaining", years=max(0, turns_left)))
        st.divider()

    # Row 3: Sub-indices and Charts tabs
    tab_names = t(lang, "tab_names")
    tab1, tab2, tab3, tab4, tab5 = st.tabs(tab_names)

    with tab1:
        st.subheader(t(lang, "tab1_subheader"))
        # Line plot for GDP & Treasury
        fig_econ = go.Figure()
        fig_econ.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['gdp'], mode='lines+markers', name='GDP ($B)', line=dict(color='#00FFCC')))
        fig_econ.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['treasury'], mode='lines+markers', name='Treasury ($B)', line=dict(color='#FF5E5B')))
        fig_econ.update_layout(title=t(lang, "tab1_chart_title"), template="plotly_dark", hovermode="x unified")
        st.plotly_chart(fig_econ, width='stretch')

    with tab2:
        st.subheader(t(lang, "tab2_subheader"))

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric(t(lang, "edu_index_label"), f"{latest_state['education_index']:.1f}%",
                      help=t(lang, "edu_index_help"))
        with c2:
            st.metric(t(lang, "health_index_label"), f"{latest_state['health_index']:.1f}%",
                      help=t(lang, "health_index_help"))
        with c3:
            st.metric(t(lang, "infra_index_label"), f"{latest_state['infrastructure']:.1f}%",
                      help=t(lang, "infra_index_help"))

        fig_indices = go.Figure()
        fig_indices.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['education_index'], mode='lines', name='Education', line=dict(dash='dash', color='#FFD166')))
        fig_indices.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['health_index'], mode='lines', name='Healthcare', line=dict(dash='dash', color='#06D6A0')))
        fig_indices.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['infrastructure'], mode='lines', name='Infrastructure', line=dict(dash='dash', color='#118AB2')))
        fig_indices.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['happiness'], mode='lines+markers', name='Happiness (%)', line=dict(width=3, color='#EF476F')))
        fig_indices.update_layout(title=t(lang, "tab2_chart_title"), template="plotly_dark")
        st.plotly_chart(fig_indices, width='stretch')

    with tab3:
        st.subheader(t(lang, "tab3_subheader"))

        col_pie, col_table = st.columns([1, 1])
        with col_pie:
            # Pie Chart of Class Demographics
            labels = [t(lang, "label_low_income"), t(lang, "label_mid_income"), t(lang, "label_high_income"), t(lang, "label_pensioners")]
            values = [p_low, p_mid, p_high, p_elder]
            colors = ['#FF9F1C', '#FFD166', '#06D6A0', '#118AB2']

            fig_pie = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.3)])
            fig_pie.update_traces(hoverinfo='label+percent', textinfo='value+percent', textfont_size=12,
                                  marker=dict(colors=colors, line=dict(color='#000000', width=1)))
            fig_pie.update_layout(title=t(lang, "class_distribution_title"), template="plotly_dark")
            st.plotly_chart(fig_pie, width='stretch')

        with col_table:
            st.write(t(lang, "demographic_table_header"))
            st.write(t(lang, "total_workforce", value=(p_low + p_mid + p_high)))

            dem_data = pd.DataFrame({
                t(lang, "col_citizen_group"): [t(lang, "label_low_income"), t(lang, "label_mid_income"), t(lang, "label_high_income"), t(lang, "label_pensioners")],
                t(lang, "col_population_count"): [f"{p_low:,}", f"{p_mid:,}", f"{p_high:,}", f"{p_elder:,}"],
                t(lang, "col_ratio"): [
                    f"{(p_low / p_total) * 100:.1f}%",
                    f"{(p_mid / p_total) * 100:.1f}%",
                    f"{(p_high / p_total) * 100:.1f}%",
                    f"{(p_elder / p_total) * 100:.1f}%"
                ]
            })
            st.table(dem_data)

            # Show historical mobility chart
            fig_mobility = go.Figure()
            fig_mobility.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['pop_low'], mode='lines', name=t(lang, "label_low_income"), stackgroup='one', line=dict(color='#FF9F1C')))
            fig_mobility.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['pop_mid'], mode='lines', name=t(lang, "label_mid_income"), stackgroup='one', line=dict(color='#FFD166')))
            fig_mobility.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['pop_high'], mode='lines', name=t(lang, "label_high_income"), stackgroup='one', line=dict(color='#06D6A0')))
            fig_mobility.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['pop_elder'], mode='lines', name=t(lang, "label_pensioners"), stackgroup='one', line=dict(color='#118AB2')))
            fig_mobility.update_layout(title=t(lang, "mobility_chart_title"), template="plotly_dark")
            st.plotly_chart(fig_mobility, width='stretch')

    with tab4:
        st.subheader(t(lang, "tab4_subheader"))
        events = database.get_events(game_id)

        if not events:
            st.write(t(lang, "no_events_message"))
        else:
            for ev in events:
                year = ev['turn_year']
                title = ev['title']
                desc = ev['description']
                ev_type = ev['event_type']

                # Assign icons / formatting by event type
                if ev_type == 'CRISIS':
                    header = f"⚠️ [{year}] {title}"
                    st.error(f"**{header}** — {desc}")
                elif ev_type == 'ECONOMIC':
                    header = f"📈 [{year}] {title}"
                    st.info(f"**{header}** — {desc}")
                elif ev_type == 'SOCIAL':
                    header = f"👥 [{year}] {title}"
                    st.warning(f"**{header}** — {desc}")
                else:
                    header = f"ℹ️ [{year}] {title}"
                    st.write(f"**{header}** — {desc}")

    with tab5:
        st.subheader(t(lang, "tab5_subheader"))
        st.caption(t(lang, "tab5_caption"))

        cabinet = database.get_cabinet(game_id)
        cabinet_by_position = {c['position']: c for c in cabinet}

        for position in database.CABINET_POSITIONS:
            advisor = cabinet_by_position.get(position)
            st.write(f"#### {position}")
            if advisor:
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.write(t(
                        lang, "advisor_info",
                        name=advisor['advisor_name'], tier=advisor['tier'], bonus=advisor['bonus_value'],
                        salary=fmt_money(advisor['salary']), year=advisor['hired_year']
                    ))
                with col_b:
                    if st.button(t(lang, "fire_button"), key=f"fire_{position}"):
                        database.fire_advisor(game_id, position)
                        st.rerun()
            else:
                col_a, col_b, col_c = st.columns([2, 1, 1])
                with col_a:
                    st.write(t(lang, "vacant_label"))
                with col_b:
                    tier_choice = st.selectbox(
                        t(lang, "tier_label"), list(database.ADVISOR_TIERS.keys()),
                        key=f"tier_{position}", label_visibility="collapsed"
                    )
                with col_c:
                    tier_info = database.ADVISOR_TIERS[tier_choice]
                    if st.button(t(lang, "recruit_button", cost=fmt_money(tier_info['hire_cost'])), key=f"hire_{position}"):
                        database.hire_advisor(game_id, position, tier_choice)
                        st.rerun()
            st.divider()

def show_game_over_screen(latest_state, df_history, reason, country_name, game_id, lang):
    st.subheader(t(lang, "game_over_header"))
    st.divider()

    reason_keys = {
        "bankruptcy": ("bankruptcy_title", "bankruptcy_body"),
        "coup": ("coup_title", "coup_body"),
        "no_confidence": ("no_confidence_title", "no_confidence_body"),
        "voted_out": ("voted_out_title", "voted_out_body"),
        "victory": ("victory_title", "victory_body"),
    }
    if reason in reason_keys:
        title_key, body_key = reason_keys[reason]
        message = f"{t(lang, title_key)}\n{t(lang, body_key)}"
        if reason == "victory":
            st.success(message)
        else:
            st.error(message)

    # Stats summary
    st.write(t(lang, "final_achievements_header"))
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(t(lang, "final_gdp_label"), database.format_currency(latest_state['gdp'], country_name))
    with col2:
        st.metric(t(lang, "final_population_label"), f"{latest_state['pop_low'] + latest_state['pop_mid'] + latest_state['pop_high'] + latest_state['pop_elder']:,}")
    with col3:
        st.metric(t(lang, "final_education_label"), f"{latest_state['education_index']:.1f}%")

    # Grade Calculation
    score = float(latest_state['gdp'] * 0.1 + latest_state['happiness'] * 3.0 + latest_state['education_index'] * 2.0)
    grade = "F"

    if reason == "victory":
        if score >= 800:
            grade = "A+"
            comment = t(lang, "grade_comment_A+")
        elif score >= 600:
            grade = "A"
            comment = t(lang, "grade_comment_A")
        elif score >= 400:
            grade = "B"
            comment = t(lang, "grade_comment_B")
        elif score >= 250:
            grade = "C"
            comment = t(lang, "grade_comment_C")
        else:
            grade = "D"
            comment = t(lang, "grade_comment_D")
    else:
        grade = "F"
        comment = t(lang, "grade_comment_fail")

    st.markdown(f"""
    {t(lang, "grade_header", grade=grade)}
    *{comment}*
    """)

    # Offer retry - victory also offers an unlimited Sandbox continuation
    if reason == "victory":
        col_retry1, col_retry2 = st.columns(2)
        with col_retry1:
            if st.button(t(lang, "sandbox_continue_button"), type="primary", width="stretch"):
                database.set_sandbox_mode(game_id, True)
                st.rerun()
        with col_retry2:
            if st.button(t(lang, "back_to_menu_button"), type="secondary", width="stretch"):
                st.session_state.game_id = None
                st.rerun()
    else:
        if st.button(t(lang, "new_administration_button"), type="primary"):
            st.session_state.game_id = None
            st.rerun()

if __name__ == "__main__":
    main()
