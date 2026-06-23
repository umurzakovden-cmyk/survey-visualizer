import io
import traceback
from typing import List, Tuple

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from survey_data import SurveyDataset, MULTI_SEPARATOR, clean_text, MISSING_VALUE_TOKEN

st.set_page_config(
    page_title="Визуализатор опросов",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------- Кеширование загрузки данных ----------
@st.cache_data(show_spinner=False)
def load_dataset(file_bytes, file_name, sheet_name=None):
    dataset = SurveyDataset()
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        dataset.load(tmp_path, sheet_name=sheet_name)
    finally:
        import os
        os.unlink(tmp_path)
    return dataset


# ---------- Боковая панель ----------
with st.sidebar:
    st.header("📂 Данные")
    uploaded_file = st.file_uploader(
        "Загрузите Excel или CSV",
        type=["xlsx", "xls", "csv"],
    )

    if uploaded_file is not None:
        if "uploaded_file_name" not in st.session_state or st.session_state.uploaded_file_name != uploaded_file.name:
            st.session_state.dataset = None
            st.session_state.uploaded_file_name = uploaded_file.name
            st.session_state.sheet_name = None

        if st.session_state.get("dataset") is None:
            with st.spinner("Читаем файл..."):
                try:
                    dataset = load_dataset(
                        uploaded_file.getvalue(),
                        uploaded_file.name,
                        sheet_name=st.session_state.get("sheet_name"),
                    )
                    st.session_state.dataset = dataset
                    st.session_state.sheet_name = dataset.sheet_name
                except Exception as e:
                    st.error(f"Ошибка загрузки: {e}")
                    st.stop()
        else:
            dataset = st.session_state.dataset

        if dataset.sheet_names and len(dataset.sheet_names) > 1:
            selected_sheet = st.selectbox(
                "Лист",
                dataset.sheet_names,
                index=dataset.sheet_names.index(dataset.sheet_name)
                if dataset.sheet_name in dataset.sheet_names
                else 0,
            )
            if selected_sheet != dataset.sheet_name:
                with st.spinner("Меняем лист..."):
                    try:
                        dataset.switch_sheet(selected_sheet)
                        st.session_state.dataset = dataset
                        st.session_state.sheet_name = selected_sheet
                    except Exception as e:
                        st.error(f"Ошибка смены листа: {e}")
        else:
            st.write(f"Лист: **{dataset.sheet_name or 'CSV'}**")

        st.write(f"Строк: {len(dataset.active_df):,}")
        st.write(f"Вопросов: {len(dataset.columns)}")
        st.write(f"Мультивыбор: {len(dataset.multi_columns)}")
    else:
        st.info("👆 Загрузите файл, чтобы начать")
        st.stop()


# ---------- Основная область ----------
st.title("📊 Визуализатор опросов")

if "dataset" not in st.session_state or st.session_state.dataset is None:
    st.stop()

dataset = st.session_state.dataset
display_names = dataset.get_display_names()

# ---------- Фильтры ----------
st.sidebar.header("🔍 Фильтры")

if "filters" not in st.session_state:
    st.session_state.filters = []

def add_filter():
    st.session_state.filters.append({
        "column": display_names[0] if display_names else None,
        "values": []
    })

def remove_filter(idx):
    del st.session_state.filters[idx]

st.sidebar.button("➕ Добавить фильтр", on_click=add_filter)

filter_specs = []
for i, filt in enumerate(st.session_state.filters):
    with st.sidebar.expander(f"Фильтр {i+1}", expanded=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            if display_names:
                filt["column"] = st.selectbox(
                    "Вопрос",
                    display_names,
                    index=display_names.index(filt["column"]) if filt["column"] in display_names else 0,
                    key=f"flt_col_{i}"
                )
            else:
                filt["column"] = None
        with col2:
            st.button("❌", key=f"rm_{i}", on_click=remove_filter, args=(i,))
        if filt["column"]:
            clean_name = dataset.to_clean_name(filt["column"])
            if clean_name in dataset.columns:
                all_vals = dataset.get_unique_values(filt["column"])
                valid_defaults = [v for v in filt["values"] if v in all_vals]
                filt["values"] = st.multiselect(
                    "Значения",
                    options=all_vals,
                    default=valid_defaults,
                    key=f"flt_vals_{i}",
                )
            else:
                filt["values"] = []
        if filt["column"] and filt["values"]:
            filter_specs.append((filt["column"], filt["values"]))

if st.session_state.filters:
    if st.sidebar.button("Сбросить все фильтры"):
        st.session_state.filters = []
        st.rerun()


# ---------- Настройки визуализации ----------
st.subheader("Настройка графика")

col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
with col1:
    primary = st.selectbox("Основной вопрос", display_names, key="primary")
with col2:
    secondary_options = ["(нет)"] + display_names
    secondary = st.selectbox("Разбивка по вопросу", secondary_options, key="secondary")
with col3:
    chart_type = st.selectbox(
        "Тип графика",
        ["Круговая", "Стековая", "Тепловая карта", "Таблица", "Свободные ответы"],
        key="chart_type",
    )
with col4:
    top_n = st.number_input("Топ категорий", min_value=3, max_value=100, value=12, step=1)
    percent = st.checkbox("Проценты", value=False)
    drop_missing = st.checkbox("Скрыть пустые", value=True)


filtered_df = dataset.filter_dataframe(filter_specs)
st.caption(f"После фильтрации: **{len(filtered_df)}** из **{len(dataset.active_df)}** респондентов")


# ---------- Визуализация ----------
try:
    if chart_type == "Свободные ответы":
        answers = dataset.free_text_answers(filtered_df, primary, drop_missing=drop_missing)
        if answers:
            df_answers = pd.DataFrame({"№": range(1, len(answers)+1), "Ответ": answers})
            st.dataframe(df_answers, use_container_width=True, height=600)
        else:
            st.info("Нет ответов, соответствующих условиям.")

    elif chart_type == "Таблица":
        if secondary == "(нет)":
            counts = dataset.distribution(filtered_df, primary, top_n=top_n, drop_missing=drop_missing)
            df_table = pd.DataFrame({"Категория": counts.index, "Количество": counts.values})
            if counts.sum() > 0:
                df_table["Доля, %"] = (counts.values / counts.sum() * 100).round(1)
            st.dataframe(df_table, use_container_width=True, hide_index=True)
        else:
            cross = dataset.crosstab(filtered_df, primary, secondary, top_n_rows=top_n, top_n_cols=top_n)
            if drop_missing:
                cross = cross.drop(index=MISSING_VALUE_TOKEN, errors="ignore")
                cross = cross.drop(columns=MISSING_VALUE_TOKEN, errors="ignore")
            # Принудительно удаляем любые дубликаты индексов и колонок
            cross = cross.loc[~cross.index.duplicated()]
            cross = cross.loc[:, ~cross.columns.duplicated()]
            st.dataframe(cross, use_container_width=True)

    elif chart_type == "Круговая":
        counts = dataset.distribution(filtered_df, primary, top_n=top_n, drop_missing=drop_missing)
        if not counts.empty:
            fig = px.pie(names=counts.index.astype(str), values=counts.values, title=primary)
            fig.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Нет данных для отображения.")

    elif chart_type == "Стековая":
        if secondary == "(нет)":
            counts = dataset.distribution(filtered_df, primary, top_n=top_n, drop_missing=drop_missing)
            if counts.empty:
                st.warning("Нет данных")
            else:
                if percent:
                    total = counts.sum()
                    if total > 0:
                        counts = counts / total * 100
                fig = px.bar(x=counts.index.astype(str), y=counts.values,
                             labels={"x": primary, "y": "%" if percent else "Количество"},
                             title=primary)
                st.plotly_chart(fig, use_container_width=True)
        else:
            cross = dataset.crosstab(filtered_df, primary, secondary, top_n_rows=top_n, top_n_cols=top_n)
            if drop_missing:
                cross = cross.drop(index=MISSING_VALUE_TOKEN, errors="ignore")
                cross = cross.drop(columns=MISSING_VALUE_TOKEN, errors="ignore")
            cross = cross.loc[~cross.index.duplicated()]
            cross = cross.loc[:, ~cross.columns.duplicated()]
            if cross.empty:
                st.warning("Нет данных")
            else:
                if percent:
                    cross = cross.div(cross.sum(axis=1), axis=0).fillna(0) * 100
                # Превращаем в длинный формат, никаких конфликтов индексов
                melted = cross.reset_index().melt(id_vars=cross.index.name or "index")
                melted.columns = [primary, secondary, "value"]
                fig = px.bar(melted, x=primary, y="value", color=secondary,
                             barmode="stack",
                             labels={"value": "%" if percent else "Количество"},
                             title=f"{primary} × {secondary}")
                st.plotly_chart(fig, use_container_width=True)

    elif chart_type == "Тепловая карта":
        if secondary == "(нет)":
            st.info("Для тепловой карты выберите вопрос для разбивки.")
        else:
            cross = dataset.crosstab(filtered_df, primary, secondary, top_n_rows=top_n, top_n_cols=top_n)
            if drop_missing:
                cross = cross.drop(index=MISSING_VALUE_TOKEN, errors="ignore")
                cross = cross.drop(columns=MISSING_VALUE_TOKEN, errors="ignore")
            cross = cross.loc[~cross.index.duplicated()]
            cross = cross.loc[:, ~cross.columns.duplicated()]
            if cross.empty:
                st.warning("Нет данных")
            else:
                if percent:
                    cross = cross.div(cross.sum(axis=1), axis=0).fillna(0) * 100

                # ---------- Обрезаем длинные подписи ----------
                max_label_len = 25  # символов, после которых обрезаем и добавляем "..."

                def shorten(text: str) -> str:
                    s = str(text)
                    return s if len(s) <= max_label_len else s[:max_label_len-3] + "..."

                y_labels_full = cross.index.astype(str).tolist()
                x_labels_full = cross.columns.astype(str).tolist()

                y_labels_short = [shorten(lbl) for lbl in y_labels_full]
                x_labels_short = [shorten(lbl) for lbl in x_labels_full]

                # ---------- Рассчитываем размеры ----------
                # Базовая высота: по 30 пикселей на строку, минимум 500
                height = max(500, 30 * len(cross.index) + 100)
                # Ширина: по 50 пикселей на столбец, минимум 600, максимум 1600
                width = min(1600, max(600, 50 * len(cross.columns) + 200))

                # ---------- Создаём аннотированную тепловую карту ----------
                fig = go.Figure(data=go.Heatmap(
                    z=cross.values,
                    x=x_labels_short,
                    y=y_labels_short,
                    texttemplate="%{z:.1f}" if percent else "%{z:d}",
                    textfont={"size": 10},
                    colorscale="Viridis",
                    customdata=[[f"{row} × {col}" for col in x_labels_full] for row in y_labels_full],
                    hovertemplate="<b>%{customdata}</b><br>Значение: %{z}<extra></extra>"
                ))

                fig.update_layout(
                    title=f"{primary} × {secondary}",
                    xaxis_title=secondary,
                    yaxis_title=primary,
                    xaxis_tickangle=-45,
                    height=height,
                    width=width,
                    margin=dict(l=180, r=30, t=60, b=100),
                    font=dict(size=10),
                    hoverlabel=dict(font_size=12)
                )

                fig.update_xaxes(
                    automargin=True,
                    tickfont=dict(size=9),
                    title_standoff=15
                )
                fig.update_yaxes(
                    automargin=True,
                    tickfont=dict(size=9),
                    title_standoff=20
                )

                st.plotly_chart(fig, use_container_width=False)

except Exception as e:
    # Показываем полную трассировку
    st.exception(e)
