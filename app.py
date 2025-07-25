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
st.markdown(f"#### 🔄 Última actualización de datos: {ultima_actualizacion}")

# --------- 2. Filtrar reservas reales por plataforma ---------
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

    # Reetiquetar "Airbnb (Not available)" como OFF
    df.loc[condiciones_airbnb_off, 'source'] = 'OFF'

    # Filtrar
    df_filtrado = df[
        condiciones_airbnb_reserved |
        condiciones_airbnb_off |
        condiciones_booking |
        condiciones_yourrentals |
        condiciones_offline
    ].copy()

    # Asignar prioridad para deduplicación
    prioridad = {
        'Offline': 1,
        'OFF': 2,
        'Airbnb': 3,
        'Booking': 4,
        'YourRentals': 5
    }
    df_filtrado['prioridad'] = df_filtrado['source'].map(prioridad)

    # Ordenar por prioridad y eliminar duplicados
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
reservas_expandidas['mes'] = reservas_expandidas['fecha_ocupada'].dt.to_period("M")
reservas_expandidas_unique = reservas_expandidas.sort_values(by='source').drop_duplicates(subset=['property_name', 'fecha_ocupada'])
reservas_expandidas_unique = reservas_expandidas_unique.dropna(subset=['fecha_ocupada', 'mes'])

# Mapeo de acrónimos
acronimos = {'Airbnb': 'AB', 'Booking': 'BK', 'YourRentals': 'YR', 'OFF': 'OFF','Offline':'OFF'}

# --------- 4. Crear pestañas ---------
tab1, tab2 = st.tabs(["🛎️ Disponibilidad y Alertas", "📈 Ocupación mensual"])

# --------- 5. Pestaña 1: Disponibilidad + Alertas ---------
with tab1:
    st.title("🔍 Disponibilidad de Suites")

    check_in = st.date_input("Fecha de llegada")
    check_out = st.date_input("Fecha de salida")

    if check_in >= check_out:
        st.warning("La fecha de salida debe ser posterior a la de entrada.")
    else:
        rango_solicitado = pd.date_range(check_in, check_out - timedelta(days=1))
        ocupadas_en_rango = reservas_expandidas_unique[reservas_expandidas_unique['fecha_ocupada'].isin(rango_solicitado)]
        suites_ocupadas = ocupadas_en_rango['property_name'].unique()
        todas_las_suites = reservas['property_name'].unique()
        suites_disponibles = [s for s in todas_las_suites if s not in suites_ocupadas]

        st.subheader("Suites disponibles:")
        if len(suites_disponibles) > 0:
            cols = st.columns(3)
            for idx, suite in enumerate(suites_disponibles):
                pull = reservas[reservas['property_name'] == suite]['pull_rentas'].iloc[0]
                with cols[idx % 3]:
                    st.success(f"🏠 {suite} — {pull}")
        else:
            st.error("No hay suites disponibles para ese rango.")

    st.title("📅 Alertas del mes seleccionado")
    meses_alertas = reservas_expandidas_unique['mes'].astype(str).unique()
    mes_alerta = st.selectbox("Selecciona un mes para ver alertas", sorted(meses_alertas))
    año_seleccionado, mes_seleccionado = mes_alerta.split('-')

    st.subheader("⚠️ Posibles dobles reservas")
    reservas_mes = reservas[
        (pd.to_datetime(reservas['start_date']).dt.year == int(año_seleccionado)) &
        (pd.to_datetime(reservas['start_date']).dt.month == int(mes_seleccionado))
    ]

    posibles_dobles = []
    for propiedad in reservas_mes['property_name'].unique():
        subset = reservas_mes[reservas_mes['property_name'] == propiedad].sort_values(by='start_date')
        for i in range(len(subset)):
            for j in range(i+1, len(subset)):
                r1 = subset.iloc[i]
                r2 = subset.iloc[j]
                if r1['source'] != r2['source'] and r1['end_date'] > r2['start_date'] and r1['start_date'] < r2['end_date']:
                    posibles_dobles.append({
                        "property_name": propiedad,
                        "rango1": f"{r1['start_date']} a {r1['end_date']} ({r1['source']})",
                        "rango2": f"{r2['start_date']} a {r2['end_date']} ({r2['source']})",
                        "fecha_solapada": max(r1['start_date'], r2['start_date'])
                    })

    if posibles_dobles:
        df_dobles = pd.DataFrame(posibles_dobles)
        st.dataframe(df_dobles.sort_values(by=['property_name', 'fecha_solapada']))
    else:
        st.success("No se detectaron dobles reservas con solapamiento en el mes seleccionado.")

    st.subheader("🧾 Check-ins y Check-outs por día")
    fecha_consulta = st.date_input("Selecciona una fecha para ver los movimientos")

    check_ins_df = reservas.sort_values(by='source').drop_duplicates(subset=['property_name', 'start_date'])
    check_outs_df = reservas.sort_values(by='source').drop_duplicates(subset=['property_name', 'end_date'])

    check_ins_df = check_ins_df[check_ins_df['start_date'] == fecha_consulta]
    check_outs_df = check_outs_df[check_outs_df['end_date'] == fecha_consulta]

    # Pasajes: días intermedios entre check-in y check-out
    pasajes_df = reservas[(reservas['start_date'] < fecha_consulta) & (reservas['end_date'] > fecha_consulta) & (reservas['summary']!='Airbnb (Not available)')]
    st.metric("Check-ins", len(check_ins_df))
    st.metric("Check-outs", len(check_outs_df))
    st.metric("Pasajes (limpieza)", len(pasajes_df))

    if not check_ins_df.empty:
        st.subheader("🔑 Check-ins")
        st.dataframe(check_ins_df[['property_name', 'start_date', 'end_date', 'source', 'summary']])

    if not check_outs_df.empty:
        st.subheader("🏁 Check-outs")
        st.dataframe(check_outs_df[['property_name', 'start_date', 'end_date', 'source', 'summary']])
    
    # Sección pasajes
    if not pasajes_df.empty:
        st.subheader("🧹 Pasajes (días intermedios con limpieza)")
        st.dataframe(pasajes_df[['property_name', 'start_date', 'end_date', 'source', 'summary']])
    else:
        st.info("No hay pasajes en esta fecha.")

    st.subheader("🚨 Alertas de cambios el mismo día")
    ambas = set(check_ins_df['property_name']).intersection(set(check_outs_df['property_name']))
    if ambas:
        st.warning("Estas suites tienen tanto check-in como check-out en el mismo día:")
        for suite in sorted(ambas):
            st.markdown(f"- ⚠️ **{suite}**")
    else:
        st.success("Ninguna suite tiene check-in y check-out el mismo día.")

# --------- 6. Pestaña 2: Ocupación mensual ---------
with tab2:
    st.markdown("### 📈 Esta es la pestaña 2: Ocupación mensual")
    st.title("📊 Ocupación mensual por suite")

    ocupacion = reservas_expandidas_unique.groupby(['property_name', 'mes']).size().reset_index(name='noches_reservadas')
    meses = ocupacion['mes'].unique()
    suites = ocupacion['property_name'].unique()

    base = []
    for suite in suites:
        for mes in meses:
            dias_en_mes = mes.to_timestamp().days_in_month
            base.append({
                "property_name": suite,
                "mes": mes,
                "noches_disponibles": dias_en_mes
            })
    base_df = pd.DataFrame(base)

    resumen = pd.merge(base_df, ocupacion, how='left', on=['property_name', 'mes'])
    resumen['noches_reservadas'] = resumen['noches_reservadas'].fillna(0)
    resumen['ocupacion_%'] = (resumen['noches_reservadas'] / resumen['noches_disponibles']) * 100
    resumen['mes'] = resumen['mes'].astype(str)
    resumen['año'] = resumen['mes'].str[:4]
    resumen['mes_número'] = resumen['mes'].str[5:7]

###Dividiendo en dos segmentos

    resumen_ls = resumen[resumen['property_name'].isin(
    reservas[reservas['pull_rentas'] == 'acapulco_suites_ls']['property_name'].unique())]

    resumen_ext = resumen[resumen['property_name'].isin(
    reservas[reservas['pull_rentas'] == 'external_owners']['property_name'].unique()
)]

    if not resumen.empty:
        años_disponibles = sorted(resumen['año'].dropna().unique())
        meses_disponibles = sorted(resumen['mes_número'].dropna().unique())

        col1, col2 = st.columns(2)
        with col1:
            año_seleccionado = st.selectbox("Selecciona un año", años_disponibles)
        with col2:
            mes_seleccionado = st.selectbox("Selecciona un mes", meses_disponibles)

        # ---- Gráfico 1: acapulco_suites_ls ----
        st.subheader("🏡 Acapulco Suites LS")
        resumen_mes_ls = resumen_ls[
            (resumen_ls['año'] == año_seleccionado) &
            (resumen_ls['mes_número'] == mes_seleccionado)
        ]

        suites_ls = resumen_mes_ls['property_name'].unique()
        suites_seleccionadas_ls = st.multiselect("Selecciona suites de Acapulco Suites LS", suites_ls, default=suites_ls)
        df_grafico_ls = resumen_mes_ls[resumen_mes_ls['property_name'].isin(suites_seleccionadas_ls)]

        if not df_grafico_ls.empty:
            fig_ls = px.bar(
                df_grafico_ls,
                x='property_name',
                y='noches_reservadas',
                hover_data={'noches_reservadas': True, 'ocupacion_%': ':.2f'},
                labels={'noches_reservadas': 'Noches reservadas', 'property_name': 'Suite'},
                title=f"Noches reservadas – {año_seleccionado}-{mes_seleccionado} – Acapulco Suites LS"
            )
            st.plotly_chart(fig_ls, use_container_width=True)
        else:
            st.info("No hay datos para mostrar en Acapulco Suites LS.")

        # ---- Gráfico 2: external_owners ----
        st.subheader("🏠 External Owners")
        resumen_mes_ext = resumen_ext[
            (resumen_ext['año'] == año_seleccionado) &
            (resumen_ext['mes_número'] == mes_seleccionado)
        ]

        suites_ext = resumen_mes_ext['property_name'].unique()
        suites_seleccionadas_ext = st.multiselect("Selecciona suites de External Owners", suites_ext, default=suites_ext)
        df_grafico_ext = resumen_mes_ext[resumen_mes_ext['property_name'].isin(suites_seleccionadas_ext)]

        if not df_grafico_ext.empty:
            fig_ext = px.bar(
                df_grafico_ext,
                x='property_name',
                y='noches_reservadas',
                hover_data={'noches_reservadas': True, 'ocupacion_%': ':.2f'},
                labels={'noches_reservadas': 'Noches reservadas', 'property_name': 'Suite'},
                title=f"Noches reservadas – {año_seleccionado}-{mes_seleccionado} – External Owners"
            )
            st.plotly_chart(fig_ext, use_container_width=True)
        else:
            st.info("No hay datos para mostrar en External Owners.")
