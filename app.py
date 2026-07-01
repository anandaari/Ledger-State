import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import ledger_db as database
import engine

# Page configuration
st.set_page_config(
    page_title="Ledger State: Macroeconomic Simulator",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling (Minimalist, dark-inspired sleek styling using markdown)
st.markdown("""
<style>
    .metric-card {
        background-color: #1E1E24;
        padding: 1.5rem;
        border-radius: 10px;
        border: 1px solid #2D2D34;
        color: white;
    }
    .metric-value {
        font-size: 2rem;
        font-weight: bold;
        color: #00FFCC;
    }
    .metric-label {
        font-size: 0.9rem;
        color: #8C8C96;
    }
</style>
""", unsafe_allow_html=True)

# Main logic
def main():
    st.title("🏛️ LEDGER STATE")
    st.write("Novus Macroeconomic Command & Control Ledger. Manage class brackets, control sovereign debt, survive the crises.")
    st.divider()

    # Session State Game Initialization
    if 'game_id' not in st.session_state:
        st.session_state.game_id = None

    if st.session_state.game_id is None:
        show_start_screen()
    else:
        show_dashboard(st.session_state.game_id)

def show_start_screen():
    st.subheader("Begin Your Administration")
    st.write("Configure the starting parameters of your technocratic regime.")
    
    col1, col2 = st.columns(2)
    with col1:
        nation_name = st.text_input("Name of Regime (e.g. Administration I)", value="Regime I", max_chars=30)
        country_name = st.selectbox("Select Country", ["Indonesia", "Singapore", "United States", "Japan", "Germany"])
        difficulty = st.selectbox("Difficulty Setting", ["Easy", "Medium", "Hard"])
        
        # Display description of starting presets
        preset = database.COUNTRY_PRESETS[country_name]
        total_starting_pop = preset["pop_low"] + preset["pop_mid"] + preset["pop_high"] + preset["pop_elder"]
        
        st.markdown(f"""
        ### Country Briefing: **{country_name}**
        * **Starting Population:** {total_starting_pop / 1000000:.1f} Million citizens
        * **Starting GDP:** ${preset['gdp']:.1f} Billion
        * **Starting Treasury:** ${preset['treasury']:.1f} Billion ({"Surplus Reserves" if preset['treasury'] >= 0 else "National Debt"})
        * **Citizen Demographics:**
          * Low-Income: {preset['pop_low'] / total_starting_pop * 100:.1f}%
          * Middle-Income: {preset['pop_mid'] / total_starting_pop * 100:.1f}%
          * High-Income: {preset['pop_high'] / total_starting_pop * 100:.1f}%
          * Pensioners / Elderly: {preset['pop_elder'] / total_starting_pop * 100:.1f}%
        """)
        
        st.info("""
        **Difficulty Multipliers:**
        * **Easy**: Starts with higher initial funds, smaller global shocks.
        * **Medium**: Default math formulas and standard crisis progression.
        * **Hard**: Shorter crisis windows, elevated interest rates, and higher budget decay.
        """)

    with col2:
        st.write("### 🎗️ Political Affiliation")
        party_name = st.radio("Pilih Partai Anda", list(database.PARTY_PRESETS.keys()))
        opposition_party = database.get_opposition_party(party_name)

        st.markdown(f"""
        **{party_name}** *(Partai Anda)*
        {database.PARTY_PRESETS[party_name]['tagline']}

        **{opposition_party}** *(Otomatis menjadi Oposisi)*
        {database.PARTY_PRESETS[opposition_party]['tagline']}
        """)
        st.warning("Semakin kebijakan Anda menyimpang dari ideologi partai sendiri (atau semakin rendah kebahagiaan rakyat), semakin kuat Oposisi. Oposisi yang terlalu kuat bisa menjatuhkan pemerintahan Anda lewat Mosi Tidak Percaya.")

    if st.button("Begin 50-Year Term", type="primary"):
        # Create a new game in DB and store id in session
        game_id = database.create_new_game(nation_name, country_name, difficulty, party_name)
        st.session_state.game_id = game_id
        st.rerun()

def show_dashboard(game_id):
    # 1. Fetch current game state
    latest_state = database.get_latest_turn(game_id)
    if not latest_state:
        st.warning("Game data missing. Resetting game session.")
        st.session_state.game_id = None
        st.rerun()
        
    country_name = database.get_country_name(game_id)
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

    # Condition D: Completed 50 Years (starting 2026, so 2076 is Turn 50)
    if latest_state['turn_year'] >= 2076:
        is_game_over = True
        game_over_reason = "victory"

    if is_game_over:
        show_game_over_screen(latest_state, df_history, game_over_reason)
        return

    # 3. Sidebar Inputs (Policy Control)
    st.sidebar.subheader("Cabinet Actions")
    st.sidebar.write(f"**Country:** {country_name}")
    st.sidebar.write(f"**Simulated Years:** {df_history['turn_year'].count() - 1} years")
    
    # Fetch active crisis list to display warnings in Sidebar and Main Page
    crises = database.get_crises(game_id)
    active_crisis = next((c for c in crises if c['status'] == 'ACTIVE'), None)
    
    st.sidebar.divider()
    
    # Slider & inputs inside a Form
    with st.sidebar.form("budget_form"):
        st.write("### 📊 Income Tax Brackets")
        tax_low_pct = st.slider("Low-Bracket Tax Rate (%)", 0, 50, int(latest_state['tax_low'] * 100), step=1)
        tax_mid_pct = st.slider("Mid-Bracket Tax Rate (%)", 0, 70, int(latest_state['tax_mid'] * 100), step=1)
        tax_high_pct = st.slider("High-Bracket Tax Rate (%)", 0, 90, int(latest_state['tax_high'] * 100), step=1)
        
        tax_low = tax_low_pct / 100.0
        tax_mid = tax_mid_pct / 100.0
        tax_high = tax_high_pct / 100.0
        
        st.write("### 💵 Spending Allocations ($ Billions)")
        # Range is 0 to GDP/2 for each allocation
        max_budget = float(latest_state['gdp'] / 2.0)
        b_ed = st.number_input("Education Budget", min_value=0.0, max_value=max_budget, value=float(latest_state['budget_education']), step=0.1)
        b_hl = st.number_input("Healthcare Budget", min_value=0.0, max_value=max_budget, value=float(latest_state['budget_health']), step=0.1)
        b_inf = st.number_input("Infrastructure Budget", min_value=0.0, max_value=max_budget, value=float(latest_state['budget_infrastructure']), step=0.1)
        b_welf = st.number_input("Social Welfare Budget", min_value=0.0, max_value=max_budget, value=float(latest_state['budget_welfare']), step=0.1)
        b_sec = st.number_input("Security & Defense Budget", min_value=0.0, max_value=max_budget, value=float(latest_state['budget_security']), step=0.1)
        
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
        
        projected_net = projected_rev - total_outflow
        
        st.write("---")
        st.write(f"**Projected Inflow:** ${projected_rev:.2f}B")
        st.write(f"**Projected Outflow:** ${total_outflow:.2f}B")
        
        if projected_net >= 0:
            st.success(f"Surplus: +${projected_net:.2f}B")
        else:
            st.error(f"Deficit: -${abs(projected_net):.2f}B")
            
        submit_btn = st.form_submit_button(f"End Fiscal Year {latest_state['turn_year']}")
        
        if submit_btn:
            inputs = {
                'tax_low': tax_low,
                'tax_mid': tax_mid,
                'tax_high': tax_high,
                'budget_education': b_ed,
                'budget_health': b_hl,
                'budget_infrastructure': b_inf,
                'budget_welfare': b_welf,
                'budget_security': b_sec
            }
            engine.simulate_turn(game_id, inputs)
            st.rerun()
            
    if st.sidebar.button("Abandon Current Administration", type="secondary"):
        st.session_state.game_id = None
        st.rerun()

    # 4. Main UI Layout
    # Header display
    st.subheader(f"Current Year: {latest_state['turn_year']} | {country_name}")
    
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
        st.metric("Gross Domestic Product (GDP)", 
                  f"${latest_state['gdp']:.1f}B", 
                  delta=f"{gdp_delta:+.1f}B ({((gdp_delta)/max(1.0, latest_state['gdp']-gdp_delta))*100:.1f}%)")
    with col2:
        st.metric("Treasury Reserves / Debt", 
                  f"${latest_state['treasury']:.1f}B", 
                  delta=f"{treasury_delta:+.1f}B",
                  delta_color="normal" if latest_state['treasury'] >= 0 else "inverse")
    with col3:
        st.metric("General Happiness", 
                  f"{latest_state['happiness']:.1f}%", 
                  delta=f"{happiness_delta:+.1f}%",
                  delta_color="normal" if latest_state['happiness'] >= 40 else "inverse")
    with col4:
        st.metric("Total Population", 
                  f"{p_total:,}", 
                  delta=f"{pop_delta:+,} citizens")
        
    st.divider()

    # Row 1.2: Monitoring Ekonomi & Sosial (percentage-based indicators)
    employment_pct = latest_state['employment_rate'] * 100.0
    crime_pct = latest_state['crime_rate'] * 100.0
    debt_to_gdp_pct = (latest_state['treasury'] / latest_state['gdp']) * 100.0

    employment_delta = 0.0
    crime_delta = 0.0
    debt_to_gdp_delta = 0.0
    if len(df_history) >= 2:
        employment_delta = float((df_history['employment_rate'].iloc[-1] - df_history['employment_rate'].iloc[-2]) * 100.0)
        crime_delta = float((df_history['crime_rate'].iloc[-1] - df_history['crime_rate'].iloc[-2]) * 100.0)
        prev_debt_to_gdp = (df_history['treasury'].iloc[-2] / df_history['gdp'].iloc[-2]) * 100.0
        debt_to_gdp_delta = debt_to_gdp_pct - prev_debt_to_gdp

    st.write("### 📉 Monitoring Ekonomi & Sosial")
    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        st.metric("Employment Rate", f"{employment_pct:.1f}%", delta=f"{employment_delta:+.1f}%")
    with col_m2:
        st.metric("Crime Rate", f"{crime_pct:.1f}%", delta=f"{crime_delta:+.1f}%", delta_color="inverse")
    with col_m3:
        st.metric("Rasio Utang/GDP", f"{debt_to_gdp_pct:.1f}%", delta=f"{debt_to_gdp_delta:+.1f}%")
        st.caption("Ambang bangkrut di -150%")
    st.divider()

    # Row 1.5: Political Climate (Ruling Party vs Opposition)
    opp_strength = latest_state['opposition_strength']
    opp_status = "🔴 Kritis" if opp_strength >= 80 else ("🟠 Waspada" if opp_strength >= 50 else "🟢 Terkendali")
    st.write(f"### 🎗️ Iklim Politik: {party_name} (Berkuasa) vs {opposition_party} (Oposisi)")
    st.progress(opp_strength / 100.0, text=f"Kekuatan Oposisi: {opp_strength:.1f}% — {opp_status}")
    if opp_strength >= 80:
        st.error("Oposisi sangat kuat. Dua tahun berturut-turut di atas 85% akan memicu Mosi Tidak Percaya dan menjatuhkan pemerintahan Anda.")

    corruption = latest_state['corruption_index']
    corruption_status = "🔴 Parah" if corruption >= 50 else ("🟠 Waspada" if corruption >= 20 else "🟢 Bersih")
    st.progress(corruption / 100.0, text=f"Indeks Korupsi: {corruption:.1f}% — {corruption_status} (mengurangi efisiensi pajak & kepercayaan publik)")

    bribe_key = f"bribed_{game_id}_{latest_state['turn_year']}"
    already_bribed = st.session_state.get(bribe_key, False)
    col_bribe1, col_bribe2 = st.columns([3, 1])
    with col_bribe1:
        st.caption("Butuh cara cepat meredam oposisi? Suap tokoh-tokoh politiknya (maksimal sekali per tahun) — tapi menaikkan Indeks Korupsi.")
    with col_bribe2:
        if st.button("💰 Bribe the Politician (-$100B)", disabled=already_bribed):
            database.apply_bribe(game_id)
            st.session_state[bribe_key] = True
            st.rerun()
    if already_bribed:
        st.caption("✅ Anda sudah menyuap politisi tahun ini.")
    st.divider()

    # Row 2: Crisis and Alert Center
    if active_crisis:
        st.error(f"### 🚨 ACTIVE CRISIS: {active_crisis['name']}")
        st.write(f"**Briefing:** {active_crisis['description']}")
        st.write(f"**Required Policy:** {active_crisis['requirement_desc']}")
        
        # Render a progress bar visual
        progress_val = float(active_crisis['current_progress'] / active_crisis['target_progress'])
        st.progress(progress_val, text=f"Progress toward resolution: {active_crisis['current_progress']} of {active_crisis['target_progress']} turns completed.")
        
        turns_left = active_crisis['duration_turns'] - (latest_state['turn_year'] - active_crisis['start_year'] + 1)
        st.write(f"*Years remaining to solve before failure:* **{max(0, turns_left)} years**")
        st.divider()

    # Row 3: Sub-indices and Charts tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 National Stats Visualizer", "📈 Structural Indices", "👥 Demographics & Classes", "📰 Ledger News Feed"])
    
    with tab1:
        st.subheader("Economic Trends")
        # Line plot for GDP & Treasury
        fig_econ = go.Figure()
        fig_econ.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['gdp'], mode='lines+markers', name='GDP ($B)', line=dict(color='#00FFCC')))
        fig_econ.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['treasury'], mode='lines+markers', name='Treasury ($B)', line=dict(color='#FF5E5B')))
        fig_econ.update_layout(title="GDP & Treasury Reserves Over Time", template="plotly_dark", hovermode="x unified")
        st.plotly_chart(fig_econ, width='stretch')
        
    with tab2:
        st.subheader("Development Asset Tracking")
        
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Education Index", f"{latest_state['education_index']:.1f}%")
        with c2:
            st.metric("Healthcare Index", f"{latest_state['health_index']:.1f}%")
        with c3:
            st.metric("Infrastructure Index", f"{latest_state['infrastructure']:.1f}%")
            
        fig_indices = go.Figure()
        fig_indices.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['education_index'], mode='lines', name='Education', line=dict(dash='dash', color='#FFD166')))
        fig_indices.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['health_index'], mode='lines', name='Healthcare', line=dict(dash='dash', color='#06D6A0')))
        fig_indices.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['infrastructure'], mode='lines', name='Infrastructure', line=dict(dash='dash', color='#118AB2')))
        fig_indices.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['happiness'], mode='lines+markers', name='Happiness (%)', line=dict(width=3, color='#EF476F')))
        fig_indices.update_layout(title="Asset & Citizen Happiness Progression", template="plotly_dark")
        st.plotly_chart(fig_indices, width='stretch')
        
    with tab3:
        st.subheader("Demographic Structure and Social Mobility")
        
        col_pie, col_table = st.columns([1, 1])
        with col_pie:
            # Pie Chart of Class Demographics
            labels = ['Low-Income', 'Middle-Income', 'High-Income', 'Pensioners']
            values = [p_low, p_mid, p_high, p_elder]
            colors = ['#FF9F1C', '#FFD166', '#06D6A0', '#118AB2']
            
            fig_pie = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.3)])
            fig_pie.update_traces(hoverinfo='label+percent', textinfo='value+percent', textfont_size=12,
                                  marker=dict(colors=colors, line=dict(color='#000000', width=1)))
            fig_pie.update_layout(title="Current Class Distribution", template="plotly_dark")
            st.plotly_chart(fig_pie, width='stretch')
            
        with col_table:
            st.write("### Demographic Population Tables")
            st.write(f"**Total Workforce size:** {(p_low + p_mid + p_high):,} active workers.")
            
            dem_data = pd.DataFrame({
                "Citizen Group": ["Low-Income", "Middle-Income", "High-Income", "Pensioners / Elderly"],
                "Population Count": [f"{p_low:,}", f"{p_mid:,}", f"{p_high:,}", f"{p_elder:,}"],
                "Ratio (%)": [
                    f"{(p_low / p_total) * 100:.1f}%",
                    f"{(p_mid / p_total) * 100:.1f}%",
                    f"{(p_high / p_total) * 100:.1f}%",
                    f"{(p_elder / p_total) * 100:.1f}%"
                ]
            })
            st.table(dem_data)
            
            # Show historical mobility chart
            fig_mobility = go.Figure()
            fig_mobility.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['pop_low'], mode='lines', name='Low-Income', stackgroup='one', line=dict(color='#FF9F1C')))
            fig_mobility.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['pop_mid'], mode='lines', name='Middle-Income', stackgroup='one', line=dict(color='#FFD166')))
            fig_mobility.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['pop_high'], mode='lines', name='High-Income', stackgroup='one', line=dict(color='#06D6A0')))
            fig_mobility.add_trace(go.Scatter(x=df_history['turn_year'], y=df_history['pop_elder'], mode='lines', name='Pensioners', stackgroup='one', line=dict(color='#118AB2')))
            fig_mobility.update_layout(title="Historical Class Distribution & Mobility", template="plotly_dark")
            st.plotly_chart(fig_mobility, width='stretch')
        
    with tab4:
        st.subheader("Yearly Historical Bulletins")
        events = database.get_events(game_id)
        
        if not events:
            st.write("No historical entries registered yet.")
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

def show_game_over_screen(latest_state, df_history, reason):
    st.subheader("🏛️ Administration Closed")
    st.divider()

    if reason == "bankruptcy":
        st.error(f"""
        ## 🚨 SOVEREIGN DEBT DEFAULT
        Your administration has defaulted on national obligations. Your sovereign debt exceeded 150% of your GDP.
        The International Monetary Fund (IMF) has suspended the local constitution, taken control of the ledger, and dismissed you from service.
        """)
    elif reason == "coup":
        st.error(f"""
        ## 💥 NATION REVOLUTION / COUP D'ÉTAT
        Citizen Happiness remained below 20% for consecutive years. Widespread civil unrest, protests, and general strikes culminated in a coup.
        The military has seized control of the government and dissolved the technocracy.
        """)
    elif reason == "no_confidence":
        st.error(f"""
        ## 🗳️ MOSI TIDAK PERCAYA
        Partai oposisi telah mengumpulkan kekuatan politik yang cukup untuk menggulingkan pemerintahan Anda melalui mosi tidak percaya di parlemen.
        Kebijakan Anda dinilai terlalu jauh menyimpang dari basis partai Anda sendiri, sehingga rakyat dan legislator beralih mendukung oposisi.
        """)
    elif reason == "victory":
        st.success(f"""
        ## 🏆 50-YEAR ADMINISTRATION COMPLETED
        Congratulations! You successfully navigated 50 turbulent years of fiscal management, progressive tax brackets, class divisions, and global shocks.
        Your name goes down in the historical annals.
        """)
        
    # Stats summary
    st.write("### Final Achievements & Records")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Final GDP", f"${latest_state['gdp']:.1f}B")
    with col2:
        st.metric("Final Population", f"{latest_state['pop_low'] + latest_state['pop_mid'] + latest_state['pop_high'] + latest_state['pop_elder']:,}")
    with col3:
        st.metric("Final Education Index", f"{latest_state['education_index']:.1f}%")
        
    # Grade Calculation
    score = float(latest_state['gdp'] * 0.1 + latest_state['happiness'] * 3.0 + latest_state['education_index'] * 2.0)
    grade = "F"
    comment = ""
    
    if reason == "victory":
        if score >= 800:
            grade = "A+"
            comment = "An economic miracle. You built a legendary technocratic utopia."
        elif score >= 600:
            grade = "A"
            comment = "Superb administration. Healthy economy, highly developed citizens, stable growth."
        elif score >= 400:
            grade = "B"
            comment = "Solid performance. Novus is secure, prosperous, and reasonably happy."
        elif score >= 250:
            grade = "C"
            comment = "Average status. You got by, but public services were stretched thin."
        else:
            grade = "D"
            comment = "Sub-optimal administration. The nation is stagnant, and your citizens are barely coping."
    else:
        grade = "F"
        comment = "Your administration fell before its 50-year term completed. The nation has failed to thrive."
        
    st.markdown(f"""
    ## Regime Performance Rating: **{grade}**
    *{comment}*
    """)
    
    # Offer retry
    if st.button("Establish New Administration", type="primary"):
        st.session_state.game_id = None
        st.rerun()

if __name__ == "__main__":
    main()
