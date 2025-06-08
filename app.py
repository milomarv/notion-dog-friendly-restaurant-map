import traceback
import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from notion_client import Client
import time
from typing import List, Dict
import pandas as pd
import html

# --- Notion config ---
NOTION_API_KEY = st.secrets['NOTION_API_KEY']
DATABASE_ID = st.secrets['DATABASE_ID']

notion = Client(auth=NOTION_API_KEY)

# --- Geocoder ---
geolocator = Nominatim(user_agent='notion-map')

st.set_page_config(layout='wide')


def get_color(color_string: str) -> str:
    if color_string == 'yellow':
        return 'orange'
    elif color_string == 'pink':
        return 'magenta'
    elif color_string == 'blue':
        return 'cadetblue'
    elif color_string == 'red':
        return 'darkred'
    elif color_string == 'green':
        return 'darkgreen'
    return color_string


@st.cache_data(show_spinner='Fetching locations from Notion and geocoding addresses...')
def fetch_locations() -> List[Dict]:
    response = notion.databases.query(database_id=DATABASE_ID)
    rows = response['results']

    locations = []
    seen_coords = set()
    for row in rows:
        try:
            row_props = row['properties']

            name = row_props['Name']['title'][0]['text']['content']

            address = row_props['Adresse']['rich_text'][0]['text']['content']
            location = geolocator.geocode(address)
            if not location:
                st.warning(
                    f'Could not geocode address "{address}" for "{name}". Please check the address in Notion.'
                )
                continue

            inaccurate_address = row_props['Ungenaue Adresse']['checkbox']
            location_string_wo_zip_code = ','.join(
                location.raw['display_name'].split(',')[:-2]
            )

            if not any(char.isdigit() for char in location_string_wo_zip_code):
                if not inaccurate_address:
                    st.warning(
                        f'"{name}" does not have a house number in the address "{location_string_wo_zip_code}". This location may not be accurate.'
                    )

            status = {
                'text': row_props['Status']['status']['name'],
                'color': get_color(row_props['Status']['status']['color']),
            }

            source_content = row_props['Quelle']['multi_select']
            if len(source_content):
                source = {
                    'text': row_props['Quelle']['multi_select'][0]['name'],
                    'color': get_color(row_props['Quelle']['multi_select'][0]['color']),
                }
            else:
                source = None

            notes_content = row_props['Notes']['rich_text']
            if len(notes_content):
                notes = notes_content[0]['plain_text']
            else:
                notes = None

            maps_url = row_props['Google Maps']['formula']['string']

            if location:
                lat, lon = location.latitude, location.longitude
                while (lat, lon) in seen_coords:
                    lat += 0.0005
                    lon += 0.0005
                seen_coords.add((lat, lon))

                locations.append(
                    {
                        'name': name,
                        'address': address,
                        'lat': lat,
                        'lon': lon,
                        'status': status,
                        'source': source,
                        'notes': notes,
                        'maps_url': maps_url,
                    }
                )
            time.sleep(0.25)  # Rate limit
        except Exception as e:
            st.error(
                f"Error processing row: {row.get('id', 'unknown')}. Error: {str(e)}"
            )
            st.write(traceback.format_exc())
            continue
    return locations


def make_html_table(df) -> str:
    html_table = "<table style='width:100%; border-collapse:collapse;'>"
    # Header
    html_table += (
        '<tr>'
        '<th>📍 Name</th>'
        '<th>ℹ️ Status</th>'
        '<th>🗺️ Address</th>'
        '<th>💡 Source</th>'
        '<th>📝 Notes</th>'
        '<th>🔗 Google Maps</th>'
        '</tr>'
    )
    # Rows
    for _, row in df.iterrows():
        html_table += '<tr>'
        html_table += f"<td>{html.escape(str(row['Name']))}</td>"
        html_table += (
            f"<td style='background-color:{row['StatusColor']};color:white'>"
            f"{html.escape(str(row['Status']))}</td>"
        )
        html_table += f"<td>{html.escape(str(row['Address']))}</td>"
        html_table += (
            f"<td style='background-color:{row['SourceColor']};color:white'>"
            f"{html.escape(str(row['Source']))}</td>"
        )
        html_table += f"<td>{html.escape(str(row['Notes']))}</td>"
        if row['Google Maps']:
            html_table += f"<td><a href='{row['Google Maps']}' target='_blank'>{row['Name']} Maps</a></td>"
        else:
            html_table += '<td></td>'
        html_table += '</tr>'
    html_table += '</table>'
    return html_table


# --- Build map ---
locations = fetch_locations()

if not locations:
    st.error('No locations found.')
else:
    # Calculate bounds
    lats = [loc['lat'] for loc in locations]
    lons = [loc['lon'] for loc in locations]
    sw = [min(lats), min(lons)]
    ne = [max(lats), max(lons)]

    # Center on the average, but we'll fit bounds after adding markers
    m = folium.Map(
        location=[sum(lats) / len(lats), sum(lons) / len(lons)], zoom_start=5
    )

    for loc in locations:
        popup_content = f"""
        <b>{loc['name']}</b><br>
        <i>{loc['address']}</i><br>
        <b>Status:</b> <span style='color:{loc['status']['color']}'>{loc['status']['text']}</span><br>
        {"<b>Quelle:</b> <span style='color:" + loc['source']['color'] + "'>" + loc['source']['text'] + "</span><br>" if loc['source'] else ""}
        {"<b>Notes:</b> " + loc['notes'] + "<br>" if loc['notes'] else ""}
        <a href="{loc['maps_url']}" target="_blank">Open in Google Maps</a>
        """
        folium.Marker(
            location=[loc['lat'], loc['lon']],
            icon=folium.Icon(
                color=loc['status']['color'],
                icon='cutlery',
                prefix='fa',
            ),
            popup=folium.Popup(popup_content, max_width=300),
            tooltip=loc['name'],
        ).add_to(m)

    # Fit map to bounds
    m.fit_bounds([sw, ne])

    # Show locations in a table

    table_data = []
    for loc in locations:
        row = {
            'Name': loc['name'],
            'Address': loc['address'],
            'Status': loc['status']['text'],
            'StatusColor': loc['status']['color'],
            'Source': loc['source']['text'] if loc['source'] else '',
            'SourceColor': loc['source']['color'] if loc['source'] else '',
            'Notes': loc['notes'] if loc['notes'] else '',
            'Google Maps': loc['maps_url'],
        }
        table_data.append(row)

    df = pd.DataFrame(table_data)
    df = df.sort_values(by='Name')

    st.subheader('🐶 Hundefreundliche Restaurants 🍽️')
    st.markdown(make_html_table(df), unsafe_allow_html=True)

    st_folium(m, height=600, use_container_width=True)

    # Impressum
    st.markdown(
        '[Impressum](https://marvin-milojevic.notion.site/Imprint-c4891e91b9484e9e99dab7964bb47cb3)'
    )
