import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import ledger_db as database
import engine
import leaderboard
from i18n import t

# Page configuration
st.set_page_config(
    page_title="Ledger State: Macroeconomic Simulator",
    layout="wide",
    initial_sidebar_state="expanded"
)

def render_language_selector(container, lang, key):
    """Renders the id/en selectbox into whichever container (main area on the
    start screen, sidebar on the dashboard) and updates st.session_state.lang.
    Shared so both screens stay in sync without duplicating the mapping."""
    lang_choice = container.selectbox(
        t(lang, "language_label"),
        ["Bahasa Indonesia", "English"],
        index=0 if lang == 'id' else 1,
        label_visibility="collapsed",
        key=key,
    )
    st.session_state.lang = 'id' if lang_choice == "Bahasa Indonesia" else 'en'


# Main logic
def main():
    # Always verify/repair the DB schema on boot - not just when a new game is
    # created - so a stale ledger.db left over from an older deploy (missing
    # newer columns like corruption_index/crime_rate) can't crash the dashboard.
    database.init_db()

    # Slider thumbs otherwise rely solely on the theme's primaryColor fill,
    # which can read as low-contrast against a dark track/background - add a
    # visible ring so the handle is legible regardless of the accent color.
    st.markdown("""
    <style>
    div[data-baseweb="slider"] div[role="slider"] {
        box-shadow: 0 0 0 3px rgba(250,250,250,0.18);
        border: 2px solid #FAFAFA !important;
    }
    div[data-testid="stSlider"] {
        padding-top: 6px;
    }
    </style>
    """, unsafe_allow_html=True)

    if 'lang' not in st.session_state:
        st.session_state.lang = 'id'

    # The title banner + language selector widget itself lives in whichever
    # screen is active (a full banner on the start screen, a compact sidebar
    # control on the dashboard) so returning players get a clean, title-free
    # monitoring view instead of a repeated banner eating vertical space.
    lang = st.session_state.lang

    # Session State Game Initialization
    if 'game_id' not in st.session_state:
        st.session_state.game_id = None

    # Auto-resume: st.session_state is in-memory and tied to the browser's
    # WebSocket connection - if that drops (e.g. the computer sleeps), a
    # reconnect looks like a brand new session and game_id would otherwise
    # reset to None even though the game's data was never actually lost from
    # ledger.db. Stashing game_id in the URL survives that reconnect.
    if st.session_state.game_id is None:
        url_game_id = st.query_params.get("game_id")
        if url_game_id:
            try:
                candidate_id = int(url_game_id)
                if database.get_latest_turn(candidate_id):
                    st.session_state.game_id = candidate_id
            except (ValueError, TypeError):
                pass

    if st.session_state.game_id is None:
        st.query_params.pop("game_id", None)
        show_start_screen(lang)
    else:
        show_dashboard(st.session_state.game_id, lang)

def show_start_screen(lang):
    col_title, col_lang = st.columns([5, 1])
    with col_title:
        st.title("🏛️ LEDGER STATE")
    with col_lang:
        render_language_selector(st, lang, key="start_lang_selector")
    lang = st.session_state.lang

    st.write(t(lang, "app_tagline"))
    st.divider()

    # Continue Administration - the game's actual data lives in ledger.db and
    # is never lost, but st.session_state.game_id (which game THIS browser
    # tab is looking at) resets if the connection drops - e.g. the computer
    # sleeps. This is the manual way back in when the URL auto-resume (see
    # main()) doesn't apply, or when picking among several ongoing games.
    existing_games = database.list_games()
    if existing_games:
        st.subheader(t(lang, "continue_header"))
        for g in existing_games:
            cal_year, cal_quarter = database.get_calendar_label(g['latest_turn'])
            col_info, col_btn = st.columns([4, 1])
            with col_info:
                st.write(t(
                    lang, "continue_row",
                    nation=g['nation_name'], country=g['country_name'], party=g['party_name'],
                    difficulty=g['difficulty'], year=cal_year, quarter=cal_quarter
                ))
            with col_btn:
                if st.button(t(lang, "continue_button_label"), key=f"continue_{g['game_id']}", width="stretch"):
                    st.session_state.game_id = g['game_id']
                    st.query_params["game_id"] = str(g['game_id'])
                    st.rerun()
        st.divider()

    st.subheader(t(lang, "start_subheader"))
    st.write(t(lang, "start_description"))

    col1, col2 = st.columns(2)
    with col1:
        username = st.text_input(t(lang, "label_username"), value=st.session_state.get("username", ""), max_chars=30)
        nation_name = st.text_input(t(lang, "label_regime_name"), value="Regime I", max_chars=30)
        country_name = st.selectbox(t(lang, "label_select_country"), ["Indonesia", "Singapore", "United States", "Japan", "Germany"])
        difficulty = st.selectbox(t(lang, "label_difficulty"), ["Easy", "Medium", "Hard"])

        # Display description of starting presets
        preset = database.COUNTRY_PRESETS[country_name]
        total_starting_pop = preset["pop_low"] + preset["pop_mid"] + preset["pop_high"] + preset["pop_elder"]

        treasury_status = t(lang, "surplus_reserves") if preset['treasury'] >= 0 else t(lang, "national_debt")
        specialization = preset.get('trade_specialization')
        specialization_label = t(lang, "trade_spec_export") if specialization == 'export' else t(lang, "trade_spec_import")
        specialization_bonus_pct = (database.TRADE_SPECIALIZATION_BONUS - 1.0) * 100
        st.markdown(f"""
        {t(lang, "country_briefing_title", country=country_name)}
        * {t(lang, "label_starting_population", value=total_starting_pop / 1000000)}
        * {t(lang, "label_starting_gdp", value=database.format_currency(preset['gdp'], country_name))}
        * {t(lang, "label_starting_treasury", value=database.format_currency(preset['treasury'], country_name), status=treasury_status)}
        * {t(lang, "label_trade_specialization", type=specialization_label, bonus=specialization_bonus_pct)}
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
        {t(lang, database.PARTY_PRESETS[party_name]['tagline_key'])}

        **{opposition_party}** {t(lang, "auto_opposition_suffix")}
        {t(lang, database.PARTY_PRESETS[opposition_party]['tagline_key'])}
        """)
        st.warning(t(lang, "opposition_warning"))

    if st.button(t(lang, "begin_button"), type="primary"):
        # Create a new game in DB and store id in session
        st.session_state.username = username
        game_id = database.create_new_game(nation_name, country_name, difficulty, party_name)
        st.session_state.game_id = game_id
        st.query_params["game_id"] = str(game_id)
        st.rerun()

    st.divider()
    st.subheader(t(lang, "leaderboard_header"))
    try:
        top_entries = leaderboard.get_top(10)
        if top_entries.empty:
            st.caption(t(lang, "leaderboard_empty"))
        else:
            display_df = top_entries.rename(columns={
                'username': t(lang, "leaderboard_col_username"),
                'nation_name': t(lang, "leaderboard_col_nation"),
                'country': t(lang, "leaderboard_col_country"),
                'difficulty': t(lang, "leaderboard_col_difficulty"),
                'grade': t(lang, "leaderboard_col_grade"),
                'score': t(lang, "leaderboard_col_score"),
            })
            cols_to_show = [t(lang, "leaderboard_col_username"), t(lang, "leaderboard_col_nation"),
                             t(lang, "leaderboard_col_country"), t(lang, "leaderboard_col_difficulty"),
                             t(lang, "leaderboard_col_grade"), t(lang, "leaderboard_col_score")]
            st.dataframe(display_df[cols_to_show], hide_index=True, width='stretch')
    except Exception:
        st.caption(t(lang, "leaderboard_unavailable"))

# Desaturated/lightened semantic palette (Tailwind's "-400" shades) - chosen
# over pure red/amber/green because fully saturated colors vibrate/glare on
# a dark background even when their raw contrast ratio passes WCAG.
STATUS_BAR_COLORS = {
    "danger": "#F87171",
    "caution": "#FBBF24",
    "good": "#34D399",
    "neutral": "#94A3B8",
}

def render_status_bar(label_text, value_pct, tier):
    """Custom HTML progress bar with a semantic color (red/amber/green/gray)
    instead of st.progress's fixed theme-accent fill, so severity is legible
    at a glance instead of every bar looking visually identical."""
    color = STATUS_BAR_COLORS[tier]
    clamped = max(0.0, min(100.0, value_pct))
    st.markdown(f"""
    <div style="font-size:0.875rem; margin-bottom:3px;">{label_text}</div>
    <div style="background-color:#262B36; border-radius:6px; height:10px; width:100%; overflow:hidden;">
        <div style="background-color:{color}; width:{clamped}%; height:100%; border-radius:6px;"></div>
    </div>
    """, unsafe_allow_html=True)

def apply_compact_chart_layout(fig, title, hovermode="x unified"):
    """
    Shared compact styling for every trend chart in the dashboard - shorter
    height, tighter margins, and a horizontal legend instead of Plotly's
    bulkier defaults, so a tab's charts fit with noticeably less scrolling.
    Pass hovermode=None for non-timeseries charts (e.g. the demographics pie).
    """
    layout_kwargs = dict(
        title=title,
        template="plotly_dark",
        height=260,
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10)),
    )
    if hovermode:
        layout_kwargs["hovermode"] = hovermode
    fig.update_layout(**layout_kwargs)
    return fig

def check_game_over(state, recent_happiness, recent_opposition, diff_settings, sandbox_mode):
    """
    Central game-over rule set, shared by the normal per-render check and the
    Auto-Advance fast-forward loop so both stay perfectly in sync.
    recent_happiness/recent_opposition: lists ending with the CURRENT state's
    value, oldest-to-newest (need >=8 entries for the coup/no-confidence checks).
    """
    if state['treasury'] < -(state['gdp'] * 1.5):
        return True, "bankruptcy"

    if len(recent_happiness) >= 8 and all(h < 20.0 for h in recent_happiness[-8:]):
        return True, "coup"

    if len(recent_opposition) >= 8 and all(o >= 85.0 for o in recent_opposition[-8:]):
        return True, "no_confidence"

    quarters_since_start = state['turn_year']
    if quarters_since_start > 0 and quarters_since_start % engine.ELECTION_TERM_QUARTERS == 0:
        approval_rating = 0.6 * state['happiness'] + 0.4 * (100.0 - state['opposition_strength'])
        if approval_rating < diff_settings["election_narrow_threshold"]:
            return True, "voted_out"

    if state['turn_year'] >= database.TOTAL_GAME_TURNS and not sandbox_mode:
        return True, "victory"

    return False, None

def compute_budget_projection(game_id, country_name, state, inputs, diff_settings, active_crisis):
    """
    Mirrors engine.py simulate_turn's actual revenue/cost formulas so the
    sidebar's live budget preview (and the Auto-Advance fast-forward loop)
    matches what simulate_turn will really produce - these constants must
    stay in sync with simulate_turn's Section 6 (Revenues).
    """
    p_low, p_mid, p_high, p_elder = state['pop_low'], state['pop_mid'], state['pop_high'], state['pop_elder']
    p_total = p_low + p_mid + p_high + p_elder

    total_spending = (inputs['budget_education'] + inputs['budget_health'] + inputs['budget_infrastructure']
                       + inputs['budget_welfare'] + inputs['budget_security'])
    cabinet_salaries_total = sum(c['salary'] for c in database.get_cabinet(game_id))
    debt_interest = abs(state['treasury']) * diff_settings["interest_rate_normal"] if state['treasury'] < 0 else 0.0
    mandatory_spending = debt_interest + cabinet_salaries_total
    total_outflow = total_spending + mandatory_spending

    tax_eff = 0.90 + 0.10 * (state['education_index'] / 100.0)
    if active_crisis and active_crisis['name'] == "The Demographic Cliff":
        tax_eff *= 0.80

    emp = state['employment_rate']
    rev_low = state['gdp'] * (p_low / p_total) * inputs['tax_low'] * emp * 0.125
    rev_mid = state['gdp'] * (p_mid / p_total) * inputs['tax_mid'] * emp * 0.25
    rev_high = state['gdp'] * (p_high / p_total) * inputs['tax_high'] * emp * 0.625
    projected_rev = (rev_low + rev_mid + rev_high) * tax_eff

    country_preset = database.COUNTRY_PRESETS[country_name]
    trade_specialization = country_preset.get('trade_specialization')
    export_bonus = database.TRADE_SPECIALIZATION_BONUS if trade_specialization == 'export' else 1.0
    import_bonus = database.TRADE_SPECIALIZATION_BONUS if trade_specialization == 'import' else 1.0
    projected_rev += state['gdp'] * country_preset['export_dependency'] * (inputs['export_tariff'] / 100.0) * 0.125 * export_bonus
    projected_rev += state['gdp'] * country_preset['import_dependency'] * (inputs['import_tariff'] / 100.0) * 0.125 * import_bonus

    projected_net = projected_rev - total_outflow
    deficit_pct_of_gdp = max(0.0, -projected_net / state['gdp'] * 100.0)
    deficit_ceiling = diff_settings["deficit_ceiling_pct"]

    effective_opposition = max(0.0, state['opposition_strength'] - state['coalition_support'] * 0.3)
    deficit_exceeded = deficit_pct_of_gdp > deficit_ceiling
    opposition_contests = effective_opposition >= database.BUDGET_OPPOSITION_CONTEST_THRESHOLD

    return {
        'total_spending': total_spending,
        'mandatory_spending': mandatory_spending,
        'total_outflow': total_outflow,
        'projected_rev': projected_rev,
        'projected_net': projected_net,
        'deficit_pct_of_gdp': deficit_pct_of_gdp,
        'deficit_ceiling': deficit_ceiling,
        'triggers_crisis': deficit_exceeded or opposition_contests,
        'crisis_reason': 'deficit' if deficit_exceeded else ('opposition' if opposition_contests else None),
    }

def render_event_entry(ev, lang, show_year=True, crisis_requirements=None):
    cal_year, cal_quarter = database.get_calendar_label(ev['turn_year'])
    title = ev['title']
    desc = ev['description']
    ev_type = ev['event_type']
    prefix = f"[{cal_year} Q{cal_quarter}] " if show_year else ""

    if ev_type == 'CRISIS':
        st.error(f"**⚠️ {prefix}{title}** — {desc}")
    elif ev_type == 'ECONOMIC':
        st.info(f"**📈 {prefix}{title}** — {desc}")
    elif ev_type == 'SOCIAL':
        st.warning(f"**👥 {prefix}{title}** — {desc}")
    else:
        st.write(f"**ℹ️ {prefix}{title}** — {desc}")

    advice = database.get_event_advice(ev, crisis_requirements)
    if advice:
        st.caption(f"{t(lang, 'event_advice_prefix')}: {advice}")

def show_dashboard(game_id, lang):
    # 1. Fetch current game state
    latest_state = database.get_latest_turn(game_id)
    if not latest_state:
        st.warning("Game data missing. Resetting game session.")
        st.session_state.game_id = None
        st.query_params.pop("game_id", None)
        st.rerun()

    country_name = database.get_country_name(game_id)
    current_cal_year, current_cal_quarter = database.get_calendar_label(latest_state['turn_year'])

    def fmt_money(amount, decimals=1, signed=False):
        s = database.format_currency(amount, country_name, decimals=decimals)
        return f"+{s}" if signed and amount >= 0 else s

    party_name = database.get_party_name(game_id)
    opposition_party = database.get_opposition_party(party_name)
    history = database.get_history(game_id)
    df_history = pd.DataFrame(history, columns=[
        'turn_year', 'treasury', 'gdp', 'population', 'employment_rate', 'happiness',
        'education_index', 'health_index', 'infrastructure', 'tax_low', 'tax_mid', 'tax_high',
        'pop_low', 'pop_mid', 'pop_high', 'pop_elder', 'opposition_strength', 'corruption_index', 'crime_rate',
        'happiness_low', 'happiness_mid', 'happiness_high', 'happiness_elder',
        'inflation_rate', 'trade_balance', 'inequality_index', 'investor_confidence',
        'welfare_index', 'public_safety_index'
    ])
    # Each row is now a quarter, not a year - charts use this readable
    # "2026 Q1" label as the x-axis instead of the raw turn index.
    df_history['period_label'] = df_history['turn_year'].apply(
        lambda t: "{} Q{}".format(*database.get_calendar_label(t))
    )

    p_low = latest_state['pop_low']
    p_mid = latest_state['pop_mid']
    p_high = latest_state['pop_high']
    p_elder = latest_state['pop_elder']
    p_total = p_low + p_mid + p_high + p_elder

    # 2. Check Game Over / Win Conditions (shared with the Auto-Advance
    # fast-forward loop via check_game_over so both stay in sync)
    diff_settings = database.get_difficulty_settings(game_id)
    debt_to_gdp_pct = (latest_state['treasury'] / latest_state['gdp']) * 100.0
    rating_info = database.get_credit_rating(debt_to_gdp_pct, latest_state['corruption_index'])
    sandbox_mode = database.get_sandbox_mode(game_id)

    is_game_over, game_over_reason = check_game_over(
        latest_state, df_history['happiness'].tolist(), df_history['opposition_strength'].tolist(),
        diff_settings, sandbox_mode
    )

    if is_game_over:
        show_game_over_screen(latest_state, df_history, game_over_reason, country_name, game_id, lang)
        return

    # 3. Sidebar Inputs (Policy Control)
    # Compact brand/language row instead of the start screen's full banner -
    # once a game is running, the main content area is dedicated entirely to
    # monitoring data (no title/tagline taking up space above it).
    col_brand, col_lang = st.sidebar.columns([3, 2])
    with col_brand:
        st.markdown("#### 🏛️ Ledger State")
    with col_lang:
        render_language_selector(st, lang, key="dashboard_lang_selector")
    lang = st.session_state.lang

    st.sidebar.subheader(t(lang, "sidebar_cabinet_actions"))
    st.sidebar.write(t(lang, "sidebar_country", country=country_name))
    quarters_played = df_history['turn_year'].count() - 1
    st.sidebar.write(t(lang, "sidebar_simulated_years", quarters=quarters_played, years=quarters_played / 4.0))

    # Election countdown - term is 20 quarters (5 years) for every difficulty
    quarters_since_start = latest_state['turn_year']
    remainder = quarters_since_start % engine.ELECTION_TERM_QUARTERS
    quarters_to_election = engine.ELECTION_TERM_QUARTERS - remainder if remainder != 0 else engine.ELECTION_TERM_QUARTERS
    election_year, election_quarter = database.get_calendar_label(latest_state['turn_year'] + quarters_to_election)
    st.sidebar.info(t(lang, "election_countdown", quarters=quarters_to_election, year=election_year, quarter=election_quarter))

    # Fetch active crisis list to display warnings in Sidebar and Main Page
    crises = database.get_crises(game_id)
    active_crisis = next((c for c in crises if c['status'] == 'ACTIVE'), None)
    crisis_requirements = {c['name']: c['requirement_desc'] for c in crises}

    pending_event = database.get_pending_event(game_id)
    budget_crisis = st.session_state.get(f'budget_crisis_{game_id}')
    form_locked = bool(pending_event) or bool(budget_crisis)

    # Consolidated attention banner - previously pending_event, budget_crisis,
    # and the active crisis were flagged in separate scattered spots (or not
    # flagged in the sidebar at all); one glance here now covers everything
    # that needs the player's attention this turn.
    attention_items = []
    if pending_event:
        attention_items.append(t(lang, "attention_pending_event"))
    if budget_crisis:
        attention_items.append(t(lang, "attention_budget_crisis"))
    if active_crisis:
        attention_items.append(t(lang, "attention_active_crisis", name=active_crisis['name']))
    if attention_items:
        st.sidebar.warning(t(lang, "attention_banner_header") + "\n" + "\n".join(f"- {item}" for item in attention_items))

    # Formula & Parameter Guide - collapsed by default like Political Actions;
    # explains cross-cutting causal links (e.g. inflation -> stagflation) that
    # a single st.metric help= tooltip can't hold, so a slider-curious player
    # can check it before touching the budget form below.
    with st.sidebar.expander(t(lang, "help_expander_label"), expanded=False):
        st.caption(t(lang, "help_intro"))
        st.markdown(t(lang, "help_section_growth"))
        st.markdown(t(lang, "help_section_inflation"))
        st.markdown(t(lang, "help_section_trade"))
        st.markdown(t(lang, "help_section_inequality"))
        st.markdown(t(lang, "help_section_confidence"))
        st.markdown(t(lang, "help_section_welfare_safety"))

    # Football-Manager-style flow: ending a fiscal year doesn't just silently
    # jump to the next dashboard - a "Year in Review" popup summarizes what
    # happened first, and if a narrative decision fired that same turn, a
    # second blocking popup demands a choice before play can continue. The
    # review is stored as a (from_turn, to_turn) range so Auto-Advance can
    # fast-forward several quarters and still show everything that happened.
    review_year_key = f'year_review_{game_id}'
    pending_review_range = st.session_state.get(review_year_key)

    if pending_review_range:
        review_from, review_to = pending_review_range
        is_multi_turn = review_to > review_from
        if is_multi_turn:
            review_events = database.get_events(game_id, turn_year_from=review_from, turn_year_to=review_to)
        else:
            review_events = database.get_events(game_id, turn_year=review_from)
        review_cal_year_from, review_cal_quarter_from = database.get_calendar_label(review_from)

        if is_multi_turn:
            review_cal_year_to, review_cal_quarter_to = database.get_calendar_label(review_to)
            dialog_title_text = t(
                lang, "year_review_title_range",
                year_from=review_cal_year_from, quarter_from=review_cal_quarter_from,
                year_to=review_cal_year_to, quarter_to=review_cal_quarter_to
            )
        else:
            dialog_title_text = t(lang, "year_review_title", year=review_cal_year_from, quarter=review_cal_quarter_from)

        @st.dialog(dialog_title_text, dismissible=False)
        def _year_review_dialog():
            if not review_events:
                st.write(t(lang, "no_events_message"))
            else:
                for ev in review_events:
                    render_event_entry(ev, lang, show_year=is_multi_turn, crisis_requirements=crisis_requirements)
            st.divider()
            if st.button(t(lang, "continue_button"), type="primary", width="stretch", key="year_review_continue"):
                del st.session_state[review_year_key]
                st.rerun()

        _year_review_dialog()

    elif pending_event:
        if pending_event['event_key'] == "minister_advice":
            data = pending_event['event_data']
            dialog_title = f"Saran Menteri: {data['position']}"
            event_description = f"{data['advisor_name']} ({data['tier']}) menyarankan: \"{data['advice_text']}\" (Biaya implementasi: {fmt_money(data['cost'])})"
            choice_labels = ["Terima Saran", "Abaikan Saran"]
            field_meta = database.EFFECT_FIELD_META.get(data['target_field'], {})
            potential_val = data['effect_magnitude'] * field_meta.get('scale', 1)
            potential_text = f"{field_meta.get('icon', '')} {field_meta.get('label', data['target_field'])} {'+' if potential_val >= 0 else ''}{potential_val:.1f}{field_meta.get('unit', '')}"
            choice_captions = [
                t(lang, "minister_advice_accept_caption", potential=potential_text, cost=fmt_money(data['cost']), tier=data['tier']),
                t(lang, "minister_advice_ignore_caption"),
            ]
        else:
            event = database.RANDOM_EVENTS[pending_event['event_key']]
            dialog_title = event['title']
            event_description = event['description']
            choice_labels = list(event['choices'].keys())
            choice_captions = [database.format_effects_summary(event['choices'][label], country_name) for label in choice_labels]

        @st.dialog(t(lang, "pending_event_header", title=dialog_title), dismissible=False)
        def _pending_event_dialog():
            st.write(event_description)
            choice_cols = st.columns(len(choice_labels))
            for i, choice_label in enumerate(choice_labels):
                with choice_cols[i]:
                    if st.button(choice_label, key=f"event_choice_{i}", type="primary", width="stretch"):
                        database.resolve_pending_event(game_id, pending_event['event_key'], choice_label)
                        st.rerun()
                    if choice_captions[i]:
                        st.caption(choice_captions[i])

        _pending_event_dialog()

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

        st.caption(t(lang, "class_happiness_caption",
                     low=latest_state['happiness_low'], mid=latest_state['happiness_mid'],
                     high=latest_state['happiness_high'], elder=latest_state['happiness_elder']))

        st.write(t(lang, "macro_policy_header"))
        min_wage = st.slider(
            t(lang, "min_wage_label"), 0, 100, int(latest_state['min_wage']), step=1,
            help=t(lang, "min_wage_help")
        )
        export_tariff = st.slider(
            t(lang, "export_tariff_label"), 0, 30, int(latest_state['export_tariff']), step=1,
            help=t(lang, "export_tariff_help")
        )
        import_tariff = st.slider(
            t(lang, "import_tariff_label"), 0, 30, int(latest_state['import_tariff']), step=1,
            help=t(lang, "import_tariff_help")
        )

        country_specialization = database.COUNTRY_PRESETS.get(country_name, {}).get('trade_specialization')
        spec_label = t(lang, "trade_spec_export") if country_specialization == 'export' else t(lang, "trade_spec_import")
        specialization_bonus_pct = (database.TRADE_SPECIALIZATION_BONUS - 1.0) * 100
        st.caption(t(lang, "trade_specialization_caption", country=country_name, type=spec_label, bonus=specialization_bonus_pct))

        currency_unit = database.currency_unit_suffix(country_name)
        st.write(f"{t(lang, 'spending_header')} ({currency_unit})")
        # Range is 0 to GDP/8 for each allocation (a quarterly budget capped
        # at 50% of ANNUAL GDP if maxed out every quarter) - shown/entered in
        # local currency, converted back to USD billions before reaching the engine.
        max_budget = float(latest_state['gdp'] / 8.0)
        max_budget_local = database.to_local(max_budget, country_name)
        budget_step = max(0.01, database.to_local(0.1, country_name))

        b_ed_local = st.number_input(t(lang, "edu_budget_label"), min_value=0.0, max_value=max_budget_local,
                                      value=database.to_local(latest_state['budget_education'], country_name), step=budget_step,
                                      help=t(lang, "edu_budget_help"))
        b_hl_local = st.number_input(t(lang, "health_budget_label"), min_value=0.0, max_value=max_budget_local,
                                      value=database.to_local(latest_state['budget_health'], country_name), step=budget_step,
                                      help=t(lang, "health_budget_help"))
        b_inf_local = st.number_input(t(lang, "infra_budget_label"), min_value=0.0, max_value=max_budget_local,
                                       value=database.to_local(latest_state['budget_infrastructure'], country_name), step=budget_step,
                                       help=t(lang, "infra_budget_help"))
        b_welf_local = st.number_input(t(lang, "welfare_budget_label"), min_value=0.0, max_value=max_budget_local,
                                        value=database.to_local(latest_state['budget_welfare'], country_name), step=budget_step,
                                        help=t(lang, "welfare_budget_help"))
        b_sec_local = st.number_input(t(lang, "security_budget_label"), min_value=0.0, max_value=max_budget_local,
                                       value=database.to_local(latest_state['budget_security'], country_name), step=budget_step,
                                       help=t(lang, "security_budget_help"))

        b_ed = database.from_local(b_ed_local, country_name)
        b_hl = database.from_local(b_hl_local, country_name)
        b_inf = database.from_local(b_inf_local, country_name)
        b_welf = database.from_local(b_welf_local, country_name)
        b_sec = database.from_local(b_sec_local, country_name)

        current_inputs = {
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
        projection = compute_budget_projection(game_id, country_name, latest_state, current_inputs, diff_settings, active_crisis)

        st.write("---")
        st.caption(t(lang, "mandatory_vs_discretionary",
                     mandatory=database.format_currency(projection['mandatory_spending'], country_name, decimals=2),
                     discretionary=database.format_currency(projection['total_spending'], country_name, decimals=2)))
        st.write(t(lang, "projected_inflow", value=database.format_currency(projection['projected_rev'], country_name, decimals=2)))
        st.write(t(lang, "projected_outflow", value=database.format_currency(projection['total_outflow'], country_name, decimals=2)))

        if projection['projected_net'] >= 0:
            st.success(t(lang, "surplus_label", value=database.format_currency(projection['projected_net'], country_name, decimals=2)))
        else:
            st.error(t(lang, "deficit_label", value=database.format_currency(abs(projection['projected_net']), country_name, decimals=2)))

        st.caption(t(lang, "deficit_ceiling_note", value=projection['deficit_ceiling']))

        if form_locked:
            st.warning(t(lang, "pending_event_form_warning"))
        submit_btn = st.form_submit_button(
            t(lang, "end_fiscal_year_button", year=current_cal_year, quarter=current_cal_quarter),
            disabled=form_locked
        )

        if submit_btn and not form_locked:
            if projection['triggers_crisis']:
                st.session_state[f'budget_crisis_{game_id}'] = {
                    'inputs': current_inputs,
                    'reason': projection['crisis_reason'],
                    'deficit_pct': projection['deficit_pct_of_gdp'],
                    'ceiling': projection['deficit_ceiling'],
                }
            else:
                new_state = engine.simulate_turn(game_id, current_inputs)
                st.session_state[f'year_review_{game_id}'] = (new_state['turn_year'], new_state['turn_year'])
            st.rerun()

    # Auto-Advance: quarterly turns mean up to 200 manual clicks for a full
    # 50-year term - this repeats the CURRENT form's policy for N quarters in
    # a row, stopping early (and letting the normal blocking dialogs take
    # over) the moment anything needs the player's attention, so it never
    # silently skips a decision.
    st.sidebar.caption(t(lang, "auto_advance_caption"))
    auto_advance_n = st.sidebar.select_slider(t(lang, "auto_advance_quarters_label"), options=[1, 4, 8, 12, 20], value=4)
    if st.sidebar.button(t(lang, "auto_advance_button", n=auto_advance_n), disabled=form_locked):
        recent_happiness = df_history['happiness'].tolist()
        recent_opposition = df_history['opposition_strength'].tolist()
        current_state = latest_state
        start_turn = current_state['turn_year']
        turns_done = 0
        for _ in range(auto_advance_n):
            crises_now = database.get_crises(game_id)
            active_crisis_now = next((c for c in crises_now if c['status'] == 'ACTIVE'), None)
            step_projection = compute_budget_projection(game_id, country_name, current_state, current_inputs, diff_settings, active_crisis_now)
            if step_projection['triggers_crisis']:
                st.session_state[f'budget_crisis_{game_id}'] = {
                    'inputs': current_inputs,
                    'reason': step_projection['crisis_reason'],
                    'deficit_pct': step_projection['deficit_pct_of_gdp'],
                    'ceiling': step_projection['deficit_ceiling'],
                }
                break
            new_state = engine.simulate_turn(game_id, current_inputs)
            turns_done += 1
            current_state = new_state
            recent_happiness.append(new_state['happiness'])
            recent_opposition.append(new_state['opposition_strength'])
            is_over, _ = check_game_over(new_state, recent_happiness, recent_opposition, diff_settings, sandbox_mode)
            if is_over:
                break

            # Minister advice is a zero-cost-to-decline flavor notification,
            # not a real decision - auto-declining it during Auto-Advance
            # keeps the loop moving instead of interrupting almost every
            # quarter once a full cabinet is hired (was stopping ~90% of the
            # time). Genuine narrative events (RANDOM_EVENTS) still stop the
            # loop below since those have real, distinct consequences.
            pending = database.get_pending_event(game_id)
            if pending and pending['event_key'] == "minister_advice":
                database.resolve_pending_event(game_id, "minister_advice", "Abaikan Saran")
                pending = None

            if pending:
                break
        if turns_done > 0:
            st.session_state[f'year_review_{game_id}'] = (start_turn + 1, current_state['turn_year'])
        st.rerun()

    st.sidebar.divider()
    # Collapsed by default - bribery/diplomacy/coalition actions are touched
    # far less often than the budget form, so hiding them behind one label
    # cuts a big chunk of permanent sidebar scroll without losing any power.
    with st.sidebar.expander(t(lang, "political_actions_expander_label"), expanded=False):
        st.caption(t(lang, "bribe_caption"))
        bribe_key = f"bribed_{game_id}_{latest_state['turn_year']}"
        already_bribed = st.session_state.get(bribe_key, False)
        if st.button(t(lang, "bribe_button", amount=fmt_money(100)), disabled=already_bribed):
            database.apply_bribe(game_id)
            st.session_state[bribe_key] = True
            st.rerun()
        if already_bribed:
            st.caption(t(lang, "bribe_done_caption"))

        st.divider()
        st.write(t(lang, "diplomacy_header"))

        # Sovereign Bond - size capped by the current Credit Rating
        bond_cap_usd = rating_info['bond_cap_pct'] * latest_state['gdp']
        bond_cap_local = database.to_local(bond_cap_usd, country_name)
        st.caption(t(lang, "credit_rating_caption", rating=rating_info['letter'], cap=fmt_money(bond_cap_usd)))
        bond_key = f"bonded_{game_id}_{latest_state['turn_year']}"
        already_bonded = st.session_state.get(bond_key, False)
        bond_amount_local = st.number_input(
            t(lang, "bond_amount_label"), min_value=0.0, max_value=max(0.01, bond_cap_local), value=0.0,
            step=max(0.01, database.to_local(1.0, country_name)), disabled=already_bonded or bond_cap_local <= 0
        )
        if st.button(t(lang, "issue_bond_button"), disabled=already_bonded or bond_amount_local <= 0):
            bond_amount_usd = database.from_local(bond_amount_local, country_name)
            database.apply_bond_issuance(game_id, bond_amount_usd)
            st.session_state[bond_key] = True
            st.rerun()
        if already_bonded:
            st.caption(t(lang, "bond_done_caption"))

        # Trade Agreement - raises Foreign Relations
        st.caption(t(lang, "trade_agreement_caption"))
        trade_key = f"traded_{game_id}_{latest_state['turn_year']}"
        already_traded = st.session_state.get(trade_key, False)
        if st.button(t(lang, "trade_agreement_button", amount=fmt_money(15)), disabled=already_traded):
            database.apply_trade_agreement(game_id)
            st.session_state[trade_key] = True
            st.rerun()
        if already_traded:
            st.caption(t(lang, "trade_agreement_done_caption"))

        # Coalition Negotiation - raises Coalition Support
        st.caption(t(lang, "coalition_caption"))
        coalition_key = f"coalition_{game_id}_{latest_state['turn_year']}"
        already_coalition = st.session_state.get(coalition_key, False)
        if st.button(t(lang, "coalition_button", amount=fmt_money(25)), disabled=already_coalition):
            database.apply_coalition_negotiation(game_id)
            st.session_state[coalition_key] = True
            st.rerun()
        if already_coalition:
            st.caption(t(lang, "coalition_done_caption"))

    st.sidebar.divider()
    if st.sidebar.button(t(lang, "abandon_button"), type="secondary"):
        st.session_state.game_id = None
        st.query_params.pop("game_id", None)
        st.rerun()

    # 4. Main UI Layout - Command Center (dense monitoring, minimal scrolling)

    # Budget Confrontation - the proposed APBN either breaches the legal
    # deficit ceiling or the Opposition is strong enough to contest it in
    # parliament outright. Forcing it through by decree works, but at a
    # real political cost (this is the "wrong choice" consequence).
    if budget_crisis:
        if budget_crisis['reason'] == 'deficit':
            reason_text = t(lang, "budget_crisis_deficit_reason", deficit=budget_crisis['deficit_pct'], ceiling=budget_crisis['ceiling'])
        else:
            reason_text = t(lang, "budget_crisis_opposition_reason", opposition=opposition_party)

        st.error(t(lang, "budget_crisis_header"))
        st.write(reason_text)
        col_bc1, col_bc2 = st.columns(2)
        with col_bc1:
            if st.button(t(lang, "revise_budget_button"), key="budget_crisis_revise", width="stretch"):
                del st.session_state[f'budget_crisis_{game_id}']
                st.rerun()
            st.caption(t(lang, "revise_budget_caption"))
        with col_bc2:
            if st.button(t(lang, "force_decree_button"), key="budget_crisis_force", type="primary", width="stretch"):
                new_state = engine.simulate_turn(game_id, budget_crisis['inputs'])
                database.apply_forced_budget_penalty(game_id)
                st.session_state[f'year_review_{game_id}'] = (new_state['turn_year'], new_state['turn_year'])
                del st.session_state[f'budget_crisis_{game_id}']
                st.rerun()
            st.caption(t(lang, "force_decree_caption"))
        st.divider()

    st.subheader(t(lang, "year_header", country=country_name, year=current_cal_year, quarter=current_cal_quarter))
    if sandbox_mode:
        st.caption(t(lang, "sandbox_caption"))

    # Row 1: Key Performance Indicators (KPIs) + Row 2: Monitoring - merged
    # into a single bordered card (reusing the same container object across
    # both `with` blocks below) instead of two separate boxes, so the two
    # most-glanced-at rows read as one compact block with less border/
    # padding overhead between them.
    top_metrics_container = st.container(border=True)
    with top_metrics_container:
        st.caption(t(lang, "kpi_card_label"))
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

    # Row 2: Monitoring Ekonomi, Sosial & Politik - one dense glance, no extra headers
    employment_pct = latest_state['employment_rate'] * 100.0
    crime_pct = latest_state['crime_rate'] * 100.0
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

    with top_metrics_container:
        st.divider()
        col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
        with col_m1:
            st.metric(t(lang, "monitor_employment_label"), f"{employment_pct:.1f}%", delta=f"{employment_delta:+.1f}%",
                       help=t(lang, "monitor_employment_help"))
        with col_m2:
            st.metric(t(lang, "monitor_crime_label"), f"{crime_pct:.1f}%", delta=f"{crime_delta:+.1f}%", delta_color="inverse",
                       help=t(lang, "monitor_crime_help"))
        with col_m3:
            # A positive treasury/GDP ratio is a SURPLUS, not debt - showing
            # it under a fixed "Debt/GDP" label with an unsigned number read
            # as "debt going up" even while the country was actually running
            # a growing surplus. Label, help text, and the sign now follow
            # the actual treasury position.
            if latest_state['treasury'] >= 0:
                debt_gdp_label = t(lang, "monitor_surplus_gdp_label")
                debt_gdp_help = t(lang, "monitor_surplus_gdp_help")
            else:
                debt_gdp_label = t(lang, "monitor_debt_gdp_label")
                debt_gdp_help = t(lang, "monitor_debt_gdp_help")
            st.metric(debt_gdp_label, f"{debt_to_gdp_pct:+.1f}%", delta=f"{debt_to_gdp_delta:+.1f}%",
                       help=debt_gdp_help)
        with col_m4:
            st.metric(t(lang, "monitor_approval_label"), f"{approval_rating:.1f}%", delta=f"{approval_delta:+.1f}%",
                       help=t(lang, "monitor_approval_help", mandate=diff_settings["election_mandate_threshold"], narrow=diff_settings["election_narrow_threshold"]))
        with col_m5:
            st.metric(t(lang, "monitor_credit_rating_label"), rating_info['letter'],
                       help=t(lang, "monitor_credit_rating_help"))

    # Economic Indicators row - Inflation/Trade Balance/Inequality/Investor
    # Confidence, the 4 metrics newly added alongside the Formula Guide above.
    inflation_delta = 0.0
    trade_balance_delta = 0.0
    inequality_delta = 0.0
    confidence_delta = 0.0
    if len(df_history) >= 2:
        inflation_delta = float((df_history['inflation_rate'].iloc[-1] - df_history['inflation_rate'].iloc[-2]) * 100.0)
        trade_balance_delta = float(df_history['trade_balance'].iloc[-1] - df_history['trade_balance'].iloc[-2])
        inequality_delta = float(df_history['inequality_index'].iloc[-1] - df_history['inequality_index'].iloc[-2])
        confidence_delta = float(df_history['investor_confidence'].iloc[-1] - df_history['investor_confidence'].iloc[-2])

    with st.container(border=True):
        col_e1, col_e2, col_e3, col_e4 = st.columns(4)
        with col_e1:
            st.metric(t(lang, "kpi_inflation_label"), f"{latest_state['inflation_rate'] * 100:.2f}%",
                       delta=f"{inflation_delta:+.2f}%", delta_color="inverse",
                       help=t(lang, "kpi_inflation_help"))
        with col_e2:
            st.metric(t(lang, "kpi_trade_balance_label"), fmt_money(latest_state['trade_balance']),
                       delta=fmt_money(trade_balance_delta, signed=True),
                       help=t(lang, "kpi_trade_balance_help"))
        with col_e3:
            st.metric(t(lang, "kpi_inequality_label"), f"{latest_state['inequality_index']:.1f}",
                       delta=f"{inequality_delta:+.1f}", delta_color="inverse",
                       help=t(lang, "kpi_inequality_help"))
        with col_e4:
            st.metric(t(lang, "kpi_investor_confidence_label"), f"{latest_state['investor_confidence']:.1f}",
                       delta=f"{confidence_delta:+.1f}",
                       help=t(lang, "kpi_investor_confidence_help"))

        foreign_relations = latest_state['foreign_relations']
        coalition_support = latest_state['coalition_support']
        opp_tier = "danger" if opp_strength >= 80 else ("caution" if opp_strength >= 50 else "good")
        corruption_tier = "danger" if corruption >= 50 else ("caution" if corruption >= 20 else "good")
        relations_tier = "good" if foreign_relations >= 70 else ("caution" if foreign_relations >= 30 else "danger")
        coalition_tier = "good" if coalition_support >= 50 else ("caution" if coalition_support >= 20 else "neutral")
        opp_status = t(lang, "opposition_status_critical") if opp_strength >= 80 else (t(lang, "opposition_status_watch") if opp_strength >= 50 else t(lang, "opposition_status_ok"))
        corruption_status = t(lang, "corruption_status_severe") if corruption >= 50 else (t(lang, "corruption_status_watch") if corruption >= 20 else t(lang, "corruption_status_clean"))
        relations_status = t(lang, "relations_status_friendly") if foreign_relations >= 70 else (t(lang, "relations_status_neutral") if foreign_relations >= 30 else t(lang, "relations_status_tense"))
        coalition_status = t(lang, "coalition_status_strong") if coalition_support >= 50 else (t(lang, "coalition_status_weak") if coalition_support >= 20 else t(lang, "coalition_status_none"))
        col_p1, col_p2, col_p3, col_p4 = st.columns(4)
        with col_p1:
            render_status_bar(t(lang, "opposition_progress_text", party=opposition_party, value=opp_strength, status=opp_status), opp_strength, opp_tier)
            st.caption(t(lang, "opposition_caption"))
        with col_p2:
            render_status_bar(t(lang, "corruption_progress_text", value=corruption, status=corruption_status), corruption, corruption_tier)
            st.caption(t(lang, "corruption_caption"))
        with col_p3:
            render_status_bar(t(lang, "relations_progress_text", value=foreign_relations, status=relations_status), foreign_relations, relations_tier)
            st.caption(t(lang, "relations_caption"))
        with col_p4:
            render_status_bar(t(lang, "coalition_progress_text", value=coalition_support, status=coalition_status), coalition_support, coalition_tier)
            st.caption(t(lang, "coalition_progress_caption"))
        if opp_strength >= 80:
            st.error(t(lang, "opposition_critical_warning"))

    # Row 3: Crisis and Alert Center
    if active_crisis:
        with st.container(border=True):
            st.error(t(lang, "crisis_header", name=active_crisis['name']))
            st.write(t(lang, "crisis_briefing", desc=active_crisis['description']))
            st.write(t(lang, "crisis_required_policy", desc=active_crisis['requirement_desc']))

            # Render a progress bar visual
            progress_val = float(active_crisis['current_progress'] / active_crisis['target_progress'])
            st.progress(progress_val, text=t(lang, "crisis_progress_text", current=active_crisis['current_progress'], target=active_crisis['target_progress']))

            turns_left = active_crisis['duration_turns'] - (latest_state['turn_year'] - active_crisis['start_year'] + 1)
            st.write(t(lang, "crisis_years_remaining", quarters=max(0, turns_left)))

    # Row 3: Sub-indices and Charts tabs
    tab_names = t(lang, "tab_names")
    tab1, tab2, tab3, tab4, tab5 = st.tabs(tab_names)

    with tab1:
        st.subheader(t(lang, "tab1_subheader"))
        # Line plot for GDP & Treasury - values and legend shown in local currency
        gdp_local_series = database.to_local(df_history['gdp'], country_name)
        treasury_local_series = database.to_local(df_history['treasury'], country_name)
        fig_econ = go.Figure()
        fig_econ.add_trace(go.Scatter(x=df_history['period_label'], y=gdp_local_series, mode='lines', name=f"GDP ({currency_unit})", line=dict(color='#00FFCC')))
        fig_econ.add_trace(go.Scatter(x=df_history['period_label'], y=treasury_local_series, mode='lines', name=f"Treasury ({currency_unit})", line=dict(color='#FF5E5B')))
        apply_compact_chart_layout(fig_econ, t(lang, "tab1_chart_title"))
        st.plotly_chart(fig_econ, width='stretch')

        # Inflation trend
        fig_inflation = go.Figure()
        fig_inflation.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['inflation_rate'] * 100.0,
                                            mode='lines', name="Inflasi (%)", line=dict(color='#FFD166')))
        apply_compact_chart_layout(fig_inflation, t(lang, "tab1_chart_inflation_title"))
        st.plotly_chart(fig_inflation, width='stretch')

        # Trade Balance trend - local currency, like the GDP/Treasury chart
        trade_balance_local_series = database.to_local(df_history['trade_balance'], country_name)
        fig_trade = go.Figure()
        fig_trade.add_trace(go.Scatter(x=df_history['period_label'], y=trade_balance_local_series,
                                        mode='lines', name=f"Neraca Dagang ({currency_unit})", line=dict(color='#06D6A0')))
        apply_compact_chart_layout(fig_trade, t(lang, "tab1_chart_trade_title"))
        st.plotly_chart(fig_trade, width='stretch')

        # Inequality Index & Investor Confidence trend - both already 0-100 scale
        fig_stability = go.Figure()
        fig_stability.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['inequality_index'],
                                            mode='lines', name="Indeks Ketimpangan", line=dict(color='#EF476F')))
        fig_stability.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['investor_confidence'],
                                            mode='lines', name="Kepercayaan Investor", line=dict(color='#118AB2')))
        apply_compact_chart_layout(fig_stability, t(lang, "tab1_chart_stability_title"))
        st.plotly_chart(fig_stability, width='stretch')

    with tab2:
        st.subheader(t(lang, "tab2_subheader"))

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.metric(t(lang, "edu_index_label"), f"{latest_state['education_index']:.1f}%",
                      help=t(lang, "edu_index_help"))
        with c2:
            st.metric(t(lang, "health_index_label"), f"{latest_state['health_index']:.1f}%",
                      help=t(lang, "health_index_help"))
        with c3:
            st.metric(t(lang, "infra_index_label"), f"{latest_state['infrastructure']:.1f}%",
                      help=t(lang, "infra_index_help"))
        with c4:
            st.metric(t(lang, "welfare_index_label"), f"{latest_state['welfare_index']:.1f}%",
                      help=t(lang, "welfare_index_help"))
        with c5:
            st.metric(t(lang, "public_safety_index_label"), f"{latest_state['public_safety_index']:.1f}%",
                      help=t(lang, "public_safety_index_help"))

        fig_indices = go.Figure()
        fig_indices.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['education_index'], mode='lines', name='Education', line=dict(dash='dash', color='#FFD166')))
        fig_indices.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['health_index'], mode='lines', name='Healthcare', line=dict(dash='dash', color='#06D6A0')))
        fig_indices.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['infrastructure'], mode='lines', name='Infrastructure', line=dict(dash='dash', color='#118AB2')))
        fig_indices.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['happiness'], mode='lines', name='Happiness (%)', line=dict(width=3, color='#EF476F')))
        apply_compact_chart_layout(fig_indices, t(lang, "tab2_chart_title"))
        st.plotly_chart(fig_indices, width='stretch')

        fig_welfare_safety = go.Figure()
        fig_welfare_safety.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['welfare_index'],
                                                  mode='lines', name='Welfare Index', line=dict(color='#FF9F1C')))
        fig_welfare_safety.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['public_safety_index'],
                                                  mode='lines', name='Public Safety Index', line=dict(color='#8338EC')))
        apply_compact_chart_layout(fig_welfare_safety, t(lang, "tab2_chart2_title"))
        st.plotly_chart(fig_welfare_safety, width='stretch')

    with tab3:
        st.subheader(t(lang, "tab3_subheader"))

        ch1, ch2, ch3, ch4 = st.columns(4)
        with ch1:
            st.metric(t(lang, "class_happiness_low_label"), f"{latest_state['happiness_low']:.1f}%",
                      help=t(lang, "class_happiness_low_help"))
        with ch2:
            st.metric(t(lang, "class_happiness_mid_label"), f"{latest_state['happiness_mid']:.1f}%",
                      help=t(lang, "class_happiness_mid_help"))
        with ch3:
            st.metric(t(lang, "class_happiness_high_label"), f"{latest_state['happiness_high']:.1f}%",
                      help=t(lang, "class_happiness_high_help"))
        with ch4:
            st.metric(t(lang, "class_happiness_elder_label"), f"{latest_state['happiness_elder']:.1f}%",
                      help=t(lang, "class_happiness_elder_help"))

        col_pie, col_table = st.columns([1, 1])
        with col_pie:
            # Pie Chart of Class Demographics
            labels = [t(lang, "label_low_income"), t(lang, "label_mid_income"), t(lang, "label_high_income"), t(lang, "label_pensioners")]
            values = [p_low, p_mid, p_high, p_elder]
            colors = ['#FF9F1C', '#FFD166', '#06D6A0', '#118AB2']

            fig_pie = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.3)])
            fig_pie.update_traces(hoverinfo='label+percent', textinfo='value+percent', textfont_size=12,
                                  marker=dict(colors=colors, line=dict(color='#000000', width=1)))
            apply_compact_chart_layout(fig_pie, t(lang, "class_distribution_title"), hovermode=None)
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
            fig_mobility.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['pop_low'], mode='lines', name=t(lang, "label_low_income"), stackgroup='one', line=dict(color='#FF9F1C')))
            fig_mobility.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['pop_mid'], mode='lines', name=t(lang, "label_mid_income"), stackgroup='one', line=dict(color='#FFD166')))
            fig_mobility.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['pop_high'], mode='lines', name=t(lang, "label_high_income"), stackgroup='one', line=dict(color='#06D6A0')))
            fig_mobility.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['pop_elder'], mode='lines', name=t(lang, "label_pensioners"), stackgroup='one', line=dict(color='#118AB2')))
            apply_compact_chart_layout(fig_mobility, t(lang, "mobility_chart_title"))
            st.plotly_chart(fig_mobility, width='stretch')

        fig_class_happiness = go.Figure()
        fig_class_happiness.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['happiness_low'], mode='lines', name=t(lang, "label_low_income"), line=dict(color='#FF9F1C')))
        fig_class_happiness.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['happiness_mid'], mode='lines', name=t(lang, "label_mid_income"), line=dict(color='#FFD166')))
        fig_class_happiness.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['happiness_high'], mode='lines', name=t(lang, "label_high_income"), line=dict(color='#06D6A0')))
        fig_class_happiness.add_trace(go.Scatter(x=df_history['period_label'], y=df_history['happiness_elder'], mode='lines', name=t(lang, "label_pensioners"), line=dict(color='#118AB2')))
        apply_compact_chart_layout(fig_class_happiness, t(lang, "class_happiness_chart_title"))
        st.plotly_chart(fig_class_happiness, width='stretch')

    with tab4:
        st.subheader(t(lang, "tab4_subheader"))
        events = database.get_events(game_id)

        if not events:
            st.write(t(lang, "no_events_message"))
        else:
            for ev in events:
                render_event_entry(ev, lang, show_year=True, crisis_requirements=crisis_requirements)

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
                col_a, col_b, col_c, col_d = st.columns([2, 1, 2, 1])
                with col_a:
                    st.write(t(lang, "vacant_label"))
                with col_b:
                    tier_choice = st.selectbox(
                        t(lang, "tier_label"), list(database.ADVISOR_TIERS.keys()),
                        key=f"tier_{position}", label_visibility="collapsed"
                    )
                with col_c:
                    name_choices = database.get_advisor_name_choices(game_id, country_name, tier_choice)
                    name_choice = st.selectbox(
                        t(lang, "advisor_name_label"), name_choices,
                        key=f"name_{position}_{tier_choice}", label_visibility="collapsed"
                    )
                with col_d:
                    tier_info = database.get_adjusted_tier_info(game_id, tier_choice)
                    if st.button(t(lang, "recruit_button", cost=fmt_money(tier_info['hire_cost'])), key=f"hire_{position}"):
                        database.hire_advisor(game_id, position, tier_choice, name_choice)
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
        # voted_out_body's threshold varies by difficulty (Easy 35% / Medium
        # 40% / Hard 45%) - a hardcoded "40%" would be wrong on Easy or Hard.
        body_kwargs = {}
        if reason == "voted_out":
            body_kwargs['threshold'] = database.get_difficulty_settings(game_id)["election_narrow_threshold"]
        message = f"{t(lang, title_key)}\n{t(lang, body_key, **body_kwargs)}"
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

    # Record this finished administration to the shared online leaderboard,
    # once per game_id - show_game_over_screen re-renders on every rerun
    # while parked on this screen, so without this guard every button click
    # here would append a duplicate row.
    recorded_key = f'leaderboard_recorded_{game_id}'
    if not st.session_state.get(recorded_key, False):
        try:
            leaderboard.record_entry(
                username=st.session_state.get("username", ""),
                nation_name=database.get_nation_name(game_id),
                country=country_name,
                party=database.get_party_name(game_id),
                difficulty=database.get_difficulty(game_id),
                final_gdp=latest_state['gdp'],
                final_happiness=latest_state['happiness'],
                final_education=latest_state['education_index'],
                grade=grade,
                score=score,
            )
            st.session_state[recorded_key] = True
            st.caption(t(lang, "leaderboard_recorded_caption"))
        except Exception:
            st.caption(t(lang, "leaderboard_record_failed_caption"))

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
                st.query_params.pop("game_id", None)
                st.rerun()
    else:
        if st.button(t(lang, "new_administration_button"), type="primary"):
            st.session_state.game_id = None
            st.query_params.pop("game_id", None)
            st.rerun()

if __name__ == "__main__":
    main()
