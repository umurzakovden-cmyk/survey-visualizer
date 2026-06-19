import io
from typing import List, Tuple

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from survey_data import SurveyDataset, MULTI_SEPARATOR, clean_text

st.set_page_config(
    page_title="Визуализатор опросов",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Кеширование загрузки данных ----------
@st.cache_data(show_spinner=False)
def load_dataset(file_bytes, file_name, sheet_name=None):
    """Загружает данные и возвращает SurveyDataset."""
    dataset = SurveyDataset()
    # Сохраняем во временный файл (для pd.ExcelFile / read_csv нужен путь)
    # Проще сохранить в BytesIO, но pandas умеет читать из bytes для CSV,
    # а для Excel нужен путь. Используем временный файл.
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

# ---------- Боковая панель: загрузка и листы ----------
with st.sidebar:
    st.header("📂 Данные")
    uploaded_file = st.file_uploader(
        "Загрузите Excel или CSV",
        type=["xlsx", "xls", "csv"],
        help="Поддерживаются файлы .xlsx, .xls, .csv",
    )

    if uploaded_file is not None:
        # Сохраняем в session_state, чтобы не терять при перезагрузке
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

        # Выбор листа (если есть)
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

        # Статистика
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

# Инициализация списка фильтров в сессии
if "filters" not in st.session_state:
    st.session_state.filters = []  # список словарей: {column, values}

def add_filter():
    st.session_state.filters.append({"column": display_names[0] if display_names else None, "values": []})

def remove_filter(idx):
    del st.session_state.filters[idx]

st.sidebar.button("➕ Добавить фильтр", on_click=add_filter)

# Отображаем все фильтры
filter_specs = []  # итоговые пары (column, values)
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
            st.button("❌", key=f"rm_{i}", on_click=remove_filter, args=(i,), help="Удалить фильтр")

        if filt["column"]:
            clean_name = dataset.to_clean_name(filt["column"])
            if clean_name in dataset.columns:
                all_vals = dataset.get_unique_values(filt["column"])
                # Сохраняем выбранные значения (только те, что ещё есть в all_vals)
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

# Кнопка сброса всех фильтров
if st.session_state.filters:
    if st.sidebar.button("Сбросить все фильтры"):
        st.session_state.filters = []
        st.rerun()

# ---------- Основные настройки визуализации ----------
st.subheader("Настройка графика")

col1, col2, col3, col4 = st.columns([2, 2, 1, 1])
with col1:
    primary = st.selectbox(
        "Основной вопрос",
        display_names,
        key="primary",
        help="Вопрос, распределение которого показываем",
    )
with col2:
    secondary_options = ["(нет)"] + display_names
    secondary = st.selectbox(
        "Разбивка по вопросу",
        secondary_options,
        key="secondary",
        help="Дополнительная разбивка (столбцы/тепловая карта)",
    )
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

# Применяем фильтры к данным
filtered_df = dataset.filter_dataframe(filter_specs)

# Обновляем информацию о количестве записей
st.caption(
    f"После фильтрации: **{len(filtered_df)}** из **{len(dataset.active_df)}** респондентов"
)

# ---------- Построение визуализации ----------
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
            st.dataframe(cross, use_container_width=True)

    elif chart_type == "Круговая":
        counts = dataset.distribution(filtered_df, primary, top_n=top_n, drop_missing=drop_missing)
        if not counts.empty:
            fig = px.pie(
                names=counts.index,
                values=counts.values,
                title=primary,
            )
            fig.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Нет данных для отображения.")

    elif chart_type == "Стековая":
        if secondary == "(нет)":
            counts = dataset.distribution(filtered_df, primary, top_n=top_n, drop_missing=drop_missing)
            if percent:
                total = counts.sum()
                if total > 0:
                    counts = counts / total * 100
                y_title = "Процент"
            else:
                y_title = "Количество"
            fig = px.bar(
                x=counts.index,
                y=counts.values,
                labels={"x": primary, "y": y_title},
                title=primary,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            cross = dataset.crosstab(filtered_df, primary, secondary, top_n_rows=top_n, top_n_cols=top_n)
            if drop_missing:
                cross = cross.drop(index=MISSING_VALUE_TOKEN, errors="ignore")
                cross = cross.drop(columns=MISSING_VALUE_TOKEN, errors="ignore")
            if cross.empty:
                st.warning("Нет данных")
            else:
                if percent:
                    cross = cross.div(cross.sum(axis=1), axis=0).fillna(0) * 100
                fig = px.bar(
                    cross,
                    barmode="stack",
                    labels={"value": "Процент" if percent else "Количество", "index": primary},
                    title=f"{primary} × {secondary}",
                )
                st.plotly_chart(fig, use_container_width=True)

    elif chart_type == "Тепловая карта":
        if secondary == "(нет)":
            st.info("Для тепловой карты выберите вопрос для разбивки.")
        else:
            cross = dataset.crosstab(filtered_df, primary, secondary, top_n_rows=top_n, top_n_cols=top_n)
            if drop_missing:
                cross = cross.drop(index=MISSING_VALUE_TOKEN, errors="ignore")
                cross = cross.drop(columns=MISSING_VALUE_TOKEN, errors="ignore")
            if cross.empty:
                st.warning("Нет данных")
            else:
                if percent:
                    cross = cross.div(cross.sum(axis=1), axis=0).fillna(0) * 100
                fig = px.imshow(
                    cross,
                    text_auto=".1f" if percent else ".0f",
                    aspect="auto",
                    labels=dict(x=secondary, y=primary, color="Процент" if percent else "Количество"),
                    title=f"{primary} × {secondary}",
                )
                st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.error(f"Ошибка при построении: {e}")
