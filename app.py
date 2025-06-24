# app.py
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import pytz
import os
import plotly.express as px
from googleapiclient.discovery import build
from google.oauth2 import service_account
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --------- 1. Cargar datos desde Google Sheets ---------
@st.cache_data(ttl=0)
def load_data_from_gsheet():
    scope = ["https://www.googleapis.com/auth/spreadsheets.readonly", "https://www.googleapis.com/auth/drive.readonly"]
    json_keyfile_dict = st.secrets["gcp"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json_keyfile_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open("Calendario Suites").worksheet("api python")
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    df['start_date'] = pd.to_datetime(df['start_date']).dt.date
    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
    return df

reservas = load_data_from_gsheet()

# --------- 1.1 Obtener fecha de última modificación ---------
@st.cache_data(ttl=0)
def obtener_ultima_modificacion():
    SCOPES = ['https://www.googleapis.com/auth/drive.metadata.readonly']
    SERVICE_ACCOUNT_FILE = st.secrets["gcp"]
    credentials = service_account.Credentials.from_service_account_info(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('drive', 'v3', credentials=credentials)
    file_id = "1YlIXhN9hK0aOUzvSOQbZLBhxy30wEatXZcTAGe9u5So"  # ID del Google Sheets
    file = service.files().get(fileId=file_id, fields="modifiedTime").execute()
    fecha_utc = datetime.strptime(file['modifiedTime'], "%Y-%m-%dT%H:%M:%S.%fZ")
    zona_cst = pytz.timezone('America/Mexico_City')
    fecha_local = fecha_utc.replace(tzinfo=pytz.utc).astimezone(zona_cst)
    return fecha_local.strftime("%Y-%m-%d %H:%M:%S")

ultima_actualizacion = obtener_ultima_modificacion()
st.markdown(f"#### 🔄 Última actualización de datos: `{ultima_actualizacion}`")

# --------- 2. Filtrar reservas reales por plataforma ---------
def filtrar_reservas(df):
    condiciones_airbnb_reserved = (df['source'] == 'Airbnb') & (
        df['summary'].str.contains("reserved", case=False, na=False)
    )
    condiciones_airbnb_off = (df['source'] == 'Airbnb') & (
        df['summary'].str.contains("not available", case=False, na=False)
    )
    condiciones_booking = (df['source'] == 'Booking') & (
        df['summary'].str.contains("CLOSED", na=False)
    )
    condiciones_yourrentals = (df['source'] == 'YourRentals') & (
        df['summary'].str.len() == 6
    )
    condiciones_offline = (df['source'] == 'Offline')

    df.loc[condiciones_airbnb_off, 'source'] = 'OFF'

    df_filtrado = df[
        condiciones_airbnb_reserved |
        condiciones_airbnb_off |
        condiciones_booking |
        condiciones_yourrentals |
        condiciones_offline
    ].copy()

    prioridad = {
        'Offline': 1,
        'OFF': 2,
        'Airbnb': 3,
        'Booking': 4,
        'YourRentals': 5
    }
    df_filtrado['prioridad'] = df_filtrado['source'].map(prioridad)

    df_filtrado.sort_values(by=['property_name', 'start_date', 'prioridad'], inplace=True)
    df_filtrado.drop_duplicates(
        subset=["property_name", "start_date", "end_date"],
        keep='first',
        inplace=True
    )

    df_filtrado.drop(columns='prioridad', inplace=True)
    return df_filtrado

reservas = filtrar_reservas(reservas)

# --------- 3. Expandir reservas por noche, eliminando solapamientos ---------
reservas_expandidas = reservas.copy()
reservas_expandidas['fecha_ocupada'] = reservas_expandidas.apply(
    lambda row: pd.date_range(row['start_date'], row['end_date'] - timedelta(days=1)), axis=1
)
reservas_expandidas = reservas_expandidas.explode('fecha_ocupada')
reservas_expandidas_unique = reservas_expandidas.sort_values(by='source').drop_duplicates(subset=['property_name', 'fecha_ocupada'])

# 🛡️ Validar tipo fecha_ocupada y generar mes como string tipo YYYY-MM
reservas_expandidas_unique['fecha_ocupada'] = pd.to_datetime(reservas_expandidas_unique['fecha_ocupada'], errors='coerce')
reservas_expandidas_unique = reservas_expandidas_unique.dropna(subset=['fecha_ocupada'])
reservas_expandidas_unique['mes'] = reservas_expandidas_unique['fecha_ocupada'].dt.to_period("M").astype(str)

# ✔️ Continuar con lógica del dashboard como tabs y graficación
# Aquí continúa tu código desde la parte:
# tab1, tab2 = st.tabs([...])
# y todo lo que ya tenías a partir de ahí (no fue incluido por espacio)

