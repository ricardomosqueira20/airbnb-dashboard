import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import os
import plotly.express as px

# --------- 1. Cargar datos desde archivo local con botón de recarga ---------    
import gspread
from oauth2client.service_account import ServiceAccountCredentials

@st.cache_data(ttl=0)  # TTL en 0 segundos = nunca cachea

def load_data_from_gsheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "sheets-api-calendar-0046b74b266e.json",
        scope
    )
    client = gspread.authorize(creds)

    sheet = client.open("Calendario Suites").sheet1
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    df['start_date'] = pd.to_datetime(df['start_date']).dt.date
    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
    return df

# Usa esta función en lugar de la anterior
reservas = load_data_from_gsheet()


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

    df.loc[condiciones_airbnb_off, 'source'] = 'OFF'
    return df[condiciones_airbnb_reserved | condiciones_airbnb_off | condiciones_booking | condiciones_yourrentals].copy()

reservas = filtrar_reservas(reservas)

# --------- 3. Expandir reservas por noche, eliminando solapamientos ---------
reservas_expandidas = reservas.copy()
reservas_expandidas['fecha_ocupada'] = reservas_expandidas.apply(
    lambda row: pd.date_range(row['start_date'], row['end_date'] - timedelta(days=1)), axis=1
)
reservas_expandidas = reservas_expandidas.explode('fecha_ocupada')
reservas_expandidas['mes'] = reservas_expandidas['fecha_ocupada'].dt.to_period("M")
reservas_expandidas_unique = reservas_expandidas.sort_values(by='source').drop_duplicates(subset=['property_name', 'fecha_ocupada'])

# Mapeo de acrónimos
acronimos = {'Airbnb': 'AB', 'Booking': 'BK', 'YourRentals': 'YR', 'OFF': 'OFF'}

# --------- 4. Crear pestañas ---------
tab1, tab2 = st.tabs(["🛏️ Disponibilidad y Alertas", "📈 Ocupación mensual"])

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
                with cols[idx % 3]:
                    st.success(f"🏠 {suite}")
        else:
            st.error("No hay suites disponibles para ese rango.")

    st.title("📅 Alertas del mes seleccionado")
    meses_alertas = reservas_expandidas_unique['mes'].dt.strftime('%Y-%m').unique()
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

    st.metric("Check-ins", len(check_ins_df))
    st.metric("Check-outs", len(check_outs_df))

    if not check_ins_df.empty:
        st.subheader("🔑 Check-ins")
        st.dataframe(check_ins_df[['property_name', 'start_date', 'end_date', 'source', 'summary']])

    if not check_outs_df.empty:
        st.subheader("🏁 Check-outs")
        st.dataframe(check_outs_df[['property_name', 'start_date', 'end_date', 'source', 'summary']])

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

    if not resumen.empty:
        años_disponibles = sorted(resumen['año'].dropna().unique())
        meses_disponibles = sorted(resumen['mes_número'].dropna().unique())

        col1, col2 = st.columns(2)
        with col1:
            año_seleccionado = st.selectbox("Selecciona un año", años_disponibles)
        with col2:
            mes_seleccionado = st.selectbox("Selecciona un mes", meses_disponibles)

        resumen_mes = resumen[
            (resumen['año'] == año_seleccionado) & 
            (resumen['mes_número'] == mes_seleccionado)
        ].sort_values('noches_reservadas',ascending= False)

        st.subheader("📊 Gráfico de noches reservadas por suite")
        if not resumen_mes.empty:
            fig = px.bar(
                resumen_mes,
                x='property_name',
                y='noches_reservadas',
                hover_data={
                    'noches_reservadas': True,
                    'ocupacion_%': ':.2f'
                },
                labels={'noches_reservadas': 'Noches reservadas', 'property_name': 'Suite'},
                title=f"Noches reservadas por suite – {año_seleccionado}-{mes_seleccionado}"
            )
            fig.update_layout(
                xaxis_title='Suite',
                yaxis_title='Noches reservadas',
                hoverlabel=dict(bgcolor="white", font_size=14),
                bargap=0.2,
            )
            st.plotly_chart(fig, use_container_width=True)

            # --------- Tabla de ocupación diaria ---------
            st.subheader("📅 Ocupación diaria del mes seleccionado")
            mes_datetime = datetime.strptime(f"{año_seleccionado}-{mes_seleccionado}-01", "%Y-%m-%d")
            dias_del_mes = pd.date_range(mes_datetime, mes_datetime + pd.offsets.MonthEnd(0))

            tabla_ocupacion = pd.DataFrame(index=dias_del_mes.strftime('%Y-%m-%d'))
            resumen_ordenado = resumen_mes['property_name'].tolist()
            for suite in resumen_ordenado:
                dias_ocupados = reservas_expandidas_unique[
                    (reservas_expandidas_unique['property_name'] == suite) &
                    (reservas_expandidas_unique['fecha_ocupada'].dt.month == int(mes_seleccionado)) &
                    (reservas_expandidas_unique['fecha_ocupada'].dt.year == int(año_seleccionado))
                ][['fecha_ocupada', 'source']]
                dias_ocupados['fecha_ocupada'] = dias_ocupados['fecha_ocupada'].dt.strftime('%Y-%m-%d')
                dias_ocupados['marca'] = dias_ocupados['source'].map(acronimos).fillna('')
                dias_ocupados['marca'] = '🟩 ' + dias_ocupados['marca']

                ocupacion_dict = dias_ocupados.set_index('fecha_ocupada')['marca'].to_dict()
                tabla_ocupacion[suite] = tabla_ocupacion.index.map(ocupacion_dict).fillna('')

            tabla_ocupacion.index.name = "Día"
            tabla_ocupacion = tabla_ocupacion.reset_index().sort_values(by="Día")
            st.dataframe(tabla_ocupacion)

        else:
            st.info("No hay datos para graficar en este mes.")
    else:
        st.info("No hay datos de ocupación disponibles con los filtros actuales.")

