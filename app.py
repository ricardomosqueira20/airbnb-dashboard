import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# --------- 1. Cargar datos desde archivo local con botón de recarga ---------
if st.button("🔄 Recargar datos"):
    st.cache_data.clear()

@st.cache_data
def load_data():
    df = pd.read_csv("/Users/ricardomosqueira/historico_reservas.csv")
    df['start_date'] = pd.to_datetime(df['start_date']).dt.date
    df['end_date'] = pd.to_datetime(df['end_date']).dt.date
    return df

reservas = load_data()

# --------- 2. Filtrar reservas reales por plataforma ---------
def filtrar_reservas(df):
    condiciones_airbnb = (df['source'] == 'Airbnb') & (
        df['summary'].str.contains("reserved|not available", case=False, na=False)
    )
    condiciones_booking = (df['source'] == 'Booking') & (
        df['summary'].str.contains("CLOSED", na=False)
    )
    condiciones_yourrentals = (df['source'] == 'YourRentals') & (
        df['summary'].str.len() == 6
    )
    return df[condiciones_airbnb | condiciones_booking | condiciones_yourrentals].copy()

reservas = filtrar_reservas(reservas)

# --------- 3. Expandir reservas por noche, eliminando solapamientos ---------
reservas_expandidas = reservas.copy()
reservas_expandidas['fecha_ocupada'] = reservas_expandidas.apply(
    lambda row: pd.date_range(row['start_date'], row['end_date'] - timedelta(days=1)), axis=1
)
reservas_expandidas = reservas_expandidas.explode('fecha_ocupada')
reservas_expandidas['mes'] = reservas_expandidas['fecha_ocupada'].dt.to_period("M")

# Para evitar solapamientos entre plataformas, nos quedamos con una reserva por suite y fecha
reservas_expandidas_unique = reservas_expandidas.sort_values(by='source').drop_duplicates(subset=['property_name', 'fecha_ocupada'])

# --------- 4. Formulario de búsqueda de disponibilidad ---------
st.title("🔎 Buscador de Disponibilidad de Suites")

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

# --------- 5. Módulo de ocupación mensual por suite ---------
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

    resumen_mes = resumen[(resumen['año'] == año_seleccionado) & (resumen['mes_número'] == mes_seleccionado)]
    st.dataframe(resumen_mes.sort_values(by='property_name'))

    # --------- 6. Detección de dobles reservas con solapamientos ---------
    st.title("⚠️ Posibles dobles reservas en el mes seleccionado")

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
                    plataformas = sorted([r1['source'], r2['source']])
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

    # --------- 7. Check-ins y Check-outs por día ---------
    st.title("🧾 Check-ins y Check-outs por día")
    fecha_consulta = st.date_input("Selecciona una fecha para ver los movimientos")

    # Eliminar duplicados por suite y fecha de inicio/fin
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

    # --------- 8. Alerta visual para suites con check-in y check-out el mismo día ---------
    st.title("🚨 Alertas de cambios el mismo día")
    ambas = set(check_ins_df['property_name']).intersection(set(check_outs_df['property_name']))
    if ambas:
        st.warning("Estas suites tienen tanto check-in como check-out en el mismo día:")
        for suite in sorted(ambas):
            st.markdown(f"- ⚠️ **{suite}**")
    else:
        st.success("Ninguna suite tiene check-in y check-out el mismo día.")

else:
    st.info("No hay datos de ocupación disponibles con los filtros actuales.")







