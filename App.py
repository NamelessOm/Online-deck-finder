import time
import pandas as pd
import requests
import streamlit as st
from streamlit_searchbox import st_searchbox

st.set_page_config(page_title="Limitless Card Tournament Finder", layout="wide")

LIMITLESS_API = "https://play.limitlesstcg.com/api"
TCGDEX_API = "https://api.tcgdex.net/v2/en"


@st.cache_data(ttl=86400)
def load_set_code_map() -> dict[str, str]:
    """Maps TCGdex set IDs (e.g., 'sv04') to Limitless/PTCGL set codes (e.g., 'PAR')."""
    mapping = {}
    try:
        resp = requests.get(f"{TCGDEX_API}/sets", timeout=15)
        if resp.status_code == 200:
            for s in resp.json():
                set_id = str(s.get("id", "")).lower()
                # Fetch brief/tcgOnline code if available, otherwise fallback to uppercase ID
                tcg_code = str(s.get("tcgOnline") or set_id).upper()
                mapping[set_id] = tcg_code
    except requests.RequestException:
        pass
    return mapping


@st.cache_data(ttl=3600)
def search_card_suggestions(searchterm: str) -> list[tuple[str, dict]]:
    """Queries TCGdex as the user types and returns (label, card_dict) tuples for the dropdown."""
    query = searchterm.strip()
    if len(query) < 2:
        return []

    set_map = load_set_code_map()
    results = []

    try:
        resp = requests.get(f"{TCGDEX_API}/cards", params={"name": query}, timeout=8)
        if resp.status_code != 200:
            return []

        matches = resp.json()[:20]  # Limit dropdown to top 20 matches for speed
        for item in matches:
            card_id = item.get("id", "")
            name = item.get("name", "Unknown")
            local_id = str(item.get("localId", ""))
            raw_set_id = card_id.split("-")[0].lower() if "-" in card_id else ""
            set_code = set_map.get(raw_set_id, raw_set_id.upper())

            label = f"{name} ({set_code} #{local_id})"
            payload = {
                "id": card_id,
                "name": name,
                "set_code": set_code,
                "number": local_id,
                "image": item.get("image", ""),
            }
            results.append((label, payload))
    except requests.RequestException:
        return []

    return results


@st.cache_data(ttl=3600)
def fetch_full_card_details(selected_card: dict) -> dict:
    """Fetches full card stats/attacks and resolves the high-res image (no pricing)."""
    card_id = selected_card.get("id", "")
    set_code = selected_card.get("set_code", "").upper()
    number = str(selected_card.get("number", "")).lstrip("0")
    padded_num = number.zfill(3)
    fallback_img = f"https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/tpci/{set_code}/{set_code}_{padded_num}_R_EN_LG.png"

    try:
        if card_id:
            resp = requests.get(f"{TCGDEX_API}/cards/{card_id}", timeout=10)
            if resp.status_code == 200:
                card = resp.json()
                # Ensure we use the official tcgOnline set code if TCGdex provides it on the full card
                tcg_online = str(card.get("set", {}).get("tcgOnline") or "").upper()
                if tcg_online:
                    card["resolved_set_code"] = tcg_online
                else:
                    card["resolved_set_code"] = set_code

                if card.get("image"):
                    card["resolved_image"] = f"{card['image']}/high.webp"
                else:
                    card["resolved_image"] = fallback_img
                return card
    except requests.RequestException:
        pass

    return {
        "name": selected_card.get("name", "Unknown"),
        "resolved_set_code": set_code,
        "resolved_image": fallback_img,
    }


@st.cache_data(ttl=600)
def get_recent_tournaments(limit: int, fmt: str | None, api_key: str) -> list[dict]:
    headers = {"X-Access-Key": api_key} if api_key else {}
    delay = 0.15 if api_key else 0.5
    tournaments = []
    page = 1

    while len(tournaments) < limit:
        params = {"game": "PTCG", "limit": 50, "page": page}
        if fmt and fmt != "ALL":
            params["format"] = fmt
        resp = requests.get(f"{LIMITLESS_API}/tournaments", params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        tournaments.extend(batch)
        page += 1
        time.sleep(delay)

    return tournaments[:limit]


def deck_contains_card(decklist: dict | list, name: str, set_code: str, number: str) -> int:
    target_name = name.strip().lower()
    target_set = set_code.strip().upper()
    target_num = str(number).strip().lstrip("0")

    cards = []
    if isinstance(decklist, dict):
        for group in decklist.values():
            if isinstance(group, list):
                cards.extend(group)
    elif isinstance(decklist, list):
        cards = decklist

    for card in cards:
        c_name = str(card.get("name", "")).strip().lower()
        c_set = str(card.get("set", "")).strip().upper()
        c_num = str(card.get("number", "")).strip().lstrip("0")
        if target_name in c_name and c_set == target_set and c_num == target_num:
            return int(card.get("count", 1))
    return 0


def render_card_panel(card_data: dict, number: str):
    """Renders a clean Limitless-style card panel without pricing."""
    col_img, col_info = st.columns([1, 2], gap="large")
    set_code = card_data.get("resolved_set_code", "")

    with col_img:
        if card_data.get("resolved_image"):
            st.image(card_data["resolved_image"], use_container_width=True)

    with col_info:
        hp_text = f" - {card_data['hp']} HP" if card_data.get("hp") else ""
        types = ", ".join(card_data.get("types", []))
        type_text = f" - {types}" if types else ""
        st.subheader(f"{card_data.get('name', 'Unknown')}{type_text}{hp_text}")

        category = card_data.get("category", "")
        stage = card_data.get("stage", "")
        evolves = f" - Evolves from {card_data['evolveFrom']}" if card_data.get("evolveFrom") else ""
        if category or stage:
            st.caption(f"{category} {('• ' + stage) if stage else ''}{evolves}")

        st.divider()

        for ability in card_data.get("abilities", []):
            st.markdown(f"**Ability — {ability.get('name')}**")
            st.write(ability.get("effect", ""))

        for atk in card_data.get("attacks", []):
            cost = "".join(f"[{c}]" for c in atk.get("cost", []))
            dmg = atk.get("damage", "")
            st.markdown(f"**{cost} {atk.get('name')}** `{dmg}`")
            if atk.get("effect"):
                st.write(atk["effect"])

        if card_data.get("weaknesses") or card_data.get("retreat") is not None:
            st.divider()
            weaknesses = ", ".join(f"{w['type']} {w['value']}" for w in card_data.get("weaknesses", [])) or "None"
            resistances = ", ".join(f"{r['type']} {r['value']}" for r in card_data.get("resistances", [])) or "None"
            retreat = card_data.get("retreat", "None")
            st.markdown(f"**Weakness:** {weaknesses} &nbsp;|&nbsp; **Resistance:** {resistances} &nbsp;|&nbsp; **Retreat:** {retreat}")

        set_info = card_data.get("set", {})
        set_name = set_info.get("name", set_code)
        rarity = card_data.get("rarity", "")
        st.info(f"**{set_name} ({set_code})** — #{number} {('• ' + rarity) if rarity else ''}")


# --- UI LAYOUT ---
st.title("Limitless Online Tournament Card Finder")

col_search1, col_search2 = st.columns(2, gap="large")

with col_search1:
    st.markdown("#### 1. Primary Card (Required)")
    selected_card_1 = st_searchbox(
        search_card_suggestions,
        placeholder="Start typing a card name (e.g. Golisopod, Cacturne)...",
        key="card1_searchbox",
        clear_on_submit=False,
    )

with col_search2:
    st.markdown("#### 2. Second Card Combo Filter (Optional)")
    selected_card_2 = st_searchbox(
        search_card_suggestions,
        placeholder="Leave empty for single-card search, or type a 2nd card...",
        key="card2_searchbox",
        clear_on_submit=False,
    )

st.markdown("#### Tournament Filters")
f1, f2, f3, f4 = st.columns([1, 1, 1, 1.5])
num_tournaments = f1.number_input("Last X Tournaments", min_value=1, max_value=200, value=20)
min_players = f2.number_input("Min Players", min_value=0, max_value=2000, value=32)
fmt_filter = f3.selectbox("Format", ["STANDARD", "EXPANDED", "ALL"])
api_key = f4.text_input("Limitless API Key (Optional)", type="password")

run_search = st.button("Search Tournaments", type="primary", use_container_width=True)

if run_search:
    if not selected_card_1:
        st.error("Please select a primary card from the dropdown menu first.")
        st.stop()

    card1_full = fetch_full_card_details(selected_card_1)
    c1_name = card1_full.get("name", selected_card_1["name"])
    c1_set = card1_full.get("resolved_set_code", selected_card_1["set_code"])
    c1_num = selected_card_1["number"]

    card2_full = None
    if selected_card_2:
        card2_full = fetch_full_card_details(selected_card_2)
        c2_name = card2_full.get("name", selected_card_2["name"])
        c2_set = card2_full.get("resolved_set_code", selected_card_2["set_code"])
        c2_num = selected_card_2["number"]

    # 1. Display Card Visual & Info Section
    st.markdown("---")
    if card2_full:
        left_card, right_card = st.columns(2, gap="large")
        with left_card:
            render_card_panel(card1_full, c1_num)
        with right_card:
            render_card_panel(card2_full, c2_num)
    else:
        render_card_panel(card1_full, c1_num)

    # 2. Scan Limitless Tournaments
    st.markdown("---")
    st.subheader("Decklists That Include This Card")

    headers = {"X-Access-Key": api_key} if api_key else {}
    delay = 0.15 if api_key else 0.5
    tournaments = get_recent_tournaments(int(num_tournaments), fmt_filter, api_key)

    progress = st.progress(0, text="Scanning tournaments...")
    matches = []

    for idx, t in enumerate(tournaments, start=1):
        t_id = t.get("id")
        t_name = t.get("name", "Unknown")
        t_date = t.get("date", "")[:10]
        t_players = int(t.get("players") or 0)

        progress.progress(idx / len(tournaments), text=f"Checking {idx}/{len(tournaments)}: {t_name}")

        if t_players < min_players:
            continue

        resp = requests.get(f"{LIMITLESS_API}/tournaments/{t_id}/standings", headers=headers, timeout=15)
        if resp.status_code != 200:
            continue

        for entry in resp.json():
            decklist = entry.get("decklist")
            if not decklist:
                continue

            c1_count = deck_contains_card(decklist, c1_name, c1_set, c1_num)
            if c1_count == 0:
                continue

            c2_count = None
            if card2_full:
                c2_val = deck_contains_card(decklist, c2_name, c2_set, c2_num)
                if c2_val == 0:
                    continue
                c2_count = c2_val

            matches.append({
                "Date": t_date,
                "Place": entry.get("placing"),
                "Player": entry.get("name", "Unknown"),
                "Tournament": t_name,
                "Players": t_players,
                f"{c1_name} Copies": c1_count,
                **({f"{c2_name} Copies": c2_count} if card2_full else {}),
                "Decklist": f"https://play.limitlesstcg.com/tournament/{t_id}/player/{entry.get('player')}/decklist",
            })

        time.sleep(delay)

    progress.empty()

    if not matches:
        st.warning(f"No decklists found for {c1_name} ({c1_set} #{c1_num}) with those filters.")
    else:
        df = pd.DataFrame(matches)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Decklist": st.column_config.LinkColumn("Decklist Link", display_text="View Decklist")
            },
        )
        st.download_button(
            "Download Results as CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="limitless_card_results.csv",
            mime="text/csv",
        )
