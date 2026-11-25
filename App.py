import time
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Limitless Card Tournament Finder", layout="wide")

LIMITLESS_API = "https://play.limitlesstcg.com/api"
TCGDEX_API = "https://api.tcgdex.net/v2/en"


def is_card_enabled(name: str, set_code: str, number: str) -> bool:
    ignored = {"", "n/a", "na", "none", "null"}
    return (
        str(name).strip().lower() not in ignored
        and str(set_code).strip().lower() not in ignored
        and str(number).strip().lower() not in ignored
    )


@st.cache_data(ttl=3600)
def fetch_card_details(name: str, set_code: str, number: str) -> dict | None:
    """Fetches card image and game text from TCGdex, with a Limitless image fallback."""
    clean_num = str(number).strip().lstrip("0")
    padded_num = clean_num.zfill(3)
    target_set = set_code.strip().upper()
    fallback_img = f"https://limitlesstcg.nyc3.cdn.digitaloceanspaces.com/tpci/{target_set}/{target_set}_{padded_num}_R_EN_LG.png"

    try:
        resp = requests.get(f"{TCGDEX_API}/cards", params={"name": name.strip()}, timeout=10)
        if resp.status_code == 200:
            candidates = resp.json()
            for item in candidates:
                if str(item.get("localId", "")).lstrip("0") != clean_num:
                    continue

                detail_resp = requests.get(f"{TCGDEX_API}/cards/{item['id']}", timeout=10)
                if detail_resp.status_code != 200:
                    continue

                card = detail_resp.json()
                set_info = card.get("set", {})
                tcg_online = str(set_info.get("tcgOnline") or "").upper()
                set_id = str(set_info.get("id") or "").upper()

                if target_set in (tcg_online, set_id) or len(candidates) == 1:
                    # Append /high.webp if TCGdex has an image, otherwise use fallback
                    if card.get("image"):
                        card["resolved_image"] = f"{card['image']}/high.webp"
                    else:
                        card["resolved_image"] = fallback_img
                    return card
    except requests.RequestException:
        pass

    return {"name": name, "resolved_image": fallback_img}


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


def render_card_panel(card_data: dict | None, fallback_name: str, set_code: str, number: str):
    """Renders a clean Limitless-style card header without pricing."""
    col_img, col_info = st.columns([1, 2], gap="large")

    with col_img:
        if card_data and card_data.get("resolved_image"):
            st.image(card_data["resolved_image"], use_container_width=True)
        else:
            st.info(f"Card preview unavailable for {fallback_name} ({set_code} {number}).")

    with col_info:
        if not card_data:
            st.subheader(f"{fallback_name} ({set_code.upper()} #{number})")
            st.caption("Set/card metadata not found in image database, still searching Limitless tournaments.")
            return

        hp_text = f" - {card_data['hp']} HP" if card_data.get("hp") else ""
        types = ", ".join(card_data.get("types", []))
        type_text = f" - {types}" if types else ""
        st.subheader(f"{card_data.get('name', fallback_name)}{type_text}{hp_text}")

        category = card_data.get("category", "")
        stage = card_data.get("stage", "")
        evolves = f" - Evolves from {card_data['evolveFrom']}" if card_data.get("evolveFrom") else ""
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

        st.divider()

        weaknesses = ", ".join(f"{w['type']} {w['value']}" for w in card_data.get("weaknesses", [])) or "None"
        resistances = ", ".join(f"{r['type']} {r['value']}" for r in card_data.get("resistances", [])) or "None"
        retreat = card_data.get("retreat", "None")
        st.markdown(f"**Weakness:** {weaknesses} &nbsp;|&nbsp; **Resistance:** {resistances} &nbsp;|&nbsp; **Retreat:** {retreat}")

        set_info = card_data.get("set", {})
        set_name = set_info.get("name", set_code.upper())
        rarity = card_data.get("rarity", "")
        st.info(f"**{set_name} ({set_code.upper()})** — #{number} • {rarity}")


# --- UI LAYOUT ---
st.title("Limitless Online Tournament Card Finder")

with st.form("search_form"):
    st.markdown("#### Primary Card (Required)")
    c1, c2, c3 = st.columns([2, 1, 1])
    card1_name = c1.text_input("Card Name", value="Cacturne")
    card1_set = c2.text_input("Set Code", value="DLR")
    card1_num = c3.text_input("Card Number", value="5")

    st.markdown("#### Second Card Filter (Optional — leave as `n/a` to ignore)")
    s1, s2, s3 = st.columns([2, 1, 1])
    card2_name = s1.text_input("Card 2 Name", value="n/a")
    card2_set = s2.text_input("Card 2 Set Code", value="n/a")
    card2_num = s3.text_input("Card 2 Number", value="n/a")

    st.markdown("#### Tournament Filters")
    f1, f2, f3, f4 = st.columns([1, 1, 1, 1.5])
    num_tournaments = f1.number_input("Last X Tournaments", min_value=1, max_value=200, value=20)
    min_players = f2.number_input("Min Players", min_value=0, max_value=2000, value=32)
    fmt_filter = f3.selectbox("Format", ["STANDARD", "EXPANDED", "ALL"])
    api_key = f4.text_input("Limitless API Key (Optional)", type="password")

    submitted = st.form_submit_button("Search Tournaments", type="primary", use_container_width=True)

if submitted:
    use_card_2 = is_card_enabled(card2_name, card2_set, card2_num)

    # 1. Display Card Visual & Info Section (like Limitless, without prices)
    st.markdown("---")
    card1_info = fetch_card_details(card1_name, card1_set, card1_num)
    if use_card_2:
        left_card, right_card = st.columns(2, gap="large")
        with left_card:
            render_card_panel(card1_info, card1_name, card1_set, card1_num)
        with right_card:
            card2_info = fetch_card_details(card2_name, card2_set, card2_num)
            render_card_panel(card2_info, card2_name, card2_set, card2_num)
    else:
        render_card_panel(card1_info, card1_name, card1_set, card1_num)

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

            c1_count = deck_contains_card(decklist, card1_name, card1_set, card1_num)
            if c1_count == 0:
                continue

            c2_count = "n/a"
            if use_card_2:
                c2_val = deck_contains_card(decklist, card2_name, card2_set, card2_num)
                if c2_val == 0:
                    continue
                c2_count = c2_val

            matches.append({
                "Date": t_date,
                "Place": entry.get("placing"),
                "Player": entry.get("name", "Unknown"),
                "Tournament": t_name,
                "Players": t_players,
                f"{card1_name} Copies": c1_count,
                **({f"{card2_name} Copies": c2_count} if use_card_2 else {}),
                "Decklist": f"https://play.limitlesstcg.com/tournament/{t_id}/player/{entry.get('player')}/decklist",
            })

        time.sleep(delay)

    progress.empty()

    if not matches:
        st.warning("No tournament decklists found matching your filters.")
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
