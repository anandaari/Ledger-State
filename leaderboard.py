import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# Column order must match the header row already set up in the Google Sheet -
# 'final_happyness' keeps the exact (misspelled) header the sheet already
# uses rather than forcing a manual re-edit of the spreadsheet.
WORKSHEET_NAME = "Sheet1"
LEADERBOARD_COLUMNS = [
    'date', 'username', 'nation_name', 'country', 'party', 'difficulty',
    'final_gdp', 'final_happyness', 'final_education', 'grade', 'score'
]

def get_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def record_entry(username, nation_name, country, party, difficulty,
                  final_gdp, final_happiness, final_education, grade, score):
    """Appends one finished-game row to the shared Google Sheet leaderboard."""
    conn = get_connection()
    existing = conn.read(worksheet=WORKSHEET_NAME, ttl=0)
    if existing is None:
        existing = pd.DataFrame(columns=LEADERBOARD_COLUMNS)

    new_row = {
        'date': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'username': username or "Anonim",
        'nation_name': nation_name,
        'country': country,
        'party': party,
        'difficulty': difficulty,
        'final_gdp': round(final_gdp, 1),
        'final_happyness': round(final_happiness, 1),
        'final_education': round(final_education, 1),
        'grade': grade,
        'score': round(score, 1),
    }
    updated = pd.concat([existing, pd.DataFrame([new_row])], ignore_index=True)
    conn.update(worksheet=WORKSHEET_NAME, data=updated[LEADERBOARD_COLUMNS])

def get_top(n=10):
    """Returns the top n entries by score, or an empty DataFrame if the sheet
    is empty/unreachable - callers should treat that as 'no leaderboard yet',
    not an error."""
    conn = get_connection()
    df = conn.read(worksheet=WORKSHEET_NAME, ttl=5)
    if df is None or df.empty:
        return pd.DataFrame(columns=LEADERBOARD_COLUMNS)
    df = df.dropna(subset=['score'])
    return df.sort_values('score', ascending=False).head(n)
