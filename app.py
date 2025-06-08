import traceback
import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from notion_client import Client
import time
from typing import List, Dict

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
        {"<b>Source:</b> <span style='color:" + loc['source']['color'] + "'>" + loc['source']['text'] + "</span><br>" if loc['source'] else ""}
        {"<b>Notes:</b> " + loc['notes'] + "<br>" if loc['notes'] else ""}
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

    st.empty()
    st.title('🍽️ Hundefreundliche Restaurants')
    st_folium(m, use_container_width=True)
