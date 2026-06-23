import html as html_mod
import tempfile
import os
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
    with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        dataset.load(tmp_path, sheet_name=sheet_name)
    finally:
        os.unlink(tmp_path)
    return dataset


# ---------- Инициализация session_state ----------
if "dataset" not in st.session_state:
    st.session_state.dataset = None
if "filters" not in st.session_state:
    st.session_state.filters = []
if "filter_specs" not in st.session_state:
    st.session_state.filter_specs = []


# ---------- Боковая панель ----------
with st.sidebar:
    st.header("📂 Данные")
    uploaded_file = st.file_uploader(
        "Загрузите Excel или CSV",
        type=["xlsx", "xls", "csv"],
    )

    if uploaded_file is not None:
        # Загрузка нового файла сбрасывает всё
        if "uploaded_file_name" not in st.session_state or st.session_state.uploaded_file_name != uploaded_file.name:
            st.session_state.dataset = None
            st.session_state.filters = []
            st.session_state.filter_specs = []
            st.session_state.uploaded_file_name = uploaded_file.name

        if st.session_state.dataset is None:
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

        # Выбор листа, если есть
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
                        st.session_state.filters = []
                        st.session_state.filter_specs = []
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

if st.session_state.dataset is None:
    st.stop()

dataset = st.session_state.dataset
display_names = dataset.get_display_names()

# ---------- Фильтры (с отложенным применением) ----------
st.sidebar.header("🔍 Фильтры")

# Кнопки добавления/сброса фильтров (вне формы, чтобы не отправлять её)
col_add, col_clear = st.sidebar.columns(2)
with col_add:
    if st.button("➕ Добавить фильтр"):
        st.session_state.filters.append({
            "column": display_names[0] if display_names else None,
            "values": []
        })
        st.rerun()
with col_clear:
    if st.button("Сбросить все"):
        st.session_state.filters = []
        st.session_state.filter_specs = []
        st.rerun()

# Форма с фильтрами
with st.sidebar.form("filters_form"):
    for i, filt in enumerate(st.session_state.filters):
        cols = st.columns([4, 1])
        with cols[0]:
            if display_names:
                current_col = filt.get("column")
                idx = display_names.index(current_col) if current_col in display_names else 0
                filt["column"] = st.selectbox(
                    "Вопрос",
                    display_names,
                    index=idx,
                    key=f"flt_col_{i}"
                )
            else:
                filt["column"] = None
        with cols[1]:
            # Кнопка удаления этого фильтра (внутри формы, вызывает submit)
            st.form_submit_button("❌", key=f"rm_btn_{i}")

        if filt["column"]:
            clean_name = dataset.to_clean_name(filt["column"])
            if clean_name in dataset.columns:
                all_vals = dataset.get_unique_values(filt["column"])
                # Сохраняем выбранные значения, используя актуальный ключ
                default = [v for v in filt.get("values", []) if v in all_vals]
                filt["values"] = st.multiselect(
                    "Значения",
                    options=all_vals,
                    default=default,
                    key=f"flt_vals_{i}"
                )

    # Главная кнопка применения
    applied = st.form_submit_button("🔍 Применить фильтры")

# Обработка нажатий кнопок удаления (отдельно от главного применения)
# Если была нажата любая кнопка удаления – удаляем фильтр и сбрасываем применённые спецификации
any_remove = any(
    st.session_state.get(f"rm_btn_{i}", False)
    for i in range(len(st.session_state.filters))
)
if any_remove:
    # Удаляем фильтры, у которых была нажата кнопка
    new_filters = []
    for i, filt in enumerate(st.session_state.filters):
        if not st.session_state.get(f"rm_btn_{i}", False):
            new_filters.append(filt)
        else:
            # сбрасываем флаг, чтобы он не остался на следующий рендер
            st.session_state[f"rm_btn_{i}"] = False
    st.session_state.filters = new_filters
    st.session_state.filter_specs = []   # сброс фильтрации после удаления
    st.rerun()

# Если нажата кнопка «Применить фильтры» – сохраняем выбранные спецификации
if applied:
    specs = []
    for filt in st.session_state.filters:
        if filt.get("column") and filt.get("values"):
            specs.append((filt["column"], filt["values"]))
    st.session_state.filter_specs = specs
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


filtered_df = dataset.filter_dataframe(st.session_state.filter_specs)
st.caption(f"После фильтрации: **{len(filtered_df)}** из **{len(dataset.active_df)}** респондентов")


# ---------- Визуализация ----------
try:
    if chart_type == "Свободные ответы":
        answers = dataset.free_text_answers(filtered_df, primary, drop_missing=drop_missing)
        if answers:
            # HTML-таблица с компактным оформлением
            html_table = (
                "<style>"
                "  .free-answers-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }"
                "  .free-answers-table td, .free-answers-table th { padding: 4px 8px; border: 1px solid #ddd; vertical-align: top; }"
                "  .free-answers-table td:nth-child(2) { white-space: pre-wrap; word-break: break-word; max-width: 800px; line-height: 1.4; }"
                "  .free-answers-table th { background-color: #f0f2f6; color: #262730; font-weight: 600; }"
                "</style>"
                "<table class='free-answers-table'>"
                "<tr><th>№</th><th>Ответ</th></tr>"
            )
            for idx, answer in enumerate(answers, start=1):
                safe_answer = html_mod.escape(str(answer))
                html_table += f"<tr><td>{idx}</td><td>{safe_answer}</td></tr>"
            html_table += "</table>"
            st.markdown(html_table, unsafe_allow_html=True)
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

                # Обрезаем длинные подписи
                max_label_len = 25
                def shorten(text: str) -> str:
                    s = str(text)
                    return s if len(s) <= max_label_len else s[:max_label_len-3] + "..."

                y_full = cross.index.astype(str).tolist()
                x_full = cross.columns.astype(str).tolist()
                y_short = [shorten(lbl) for lbl in y_full]
                x_short = [shorten(lbl) for lbl in x_full]

                # Вычисляем адекватные размеры
                height = max(500, 30 * len(y_full) + 100)
                width = min(1600, max(600, 50 * len(x_full) + 200))

                fig = go.Figure(data=go.Heatmap(
                    z=cross.values,
                    x=x_short,
                    y=y_short,
                    texttemplate="%{z:.1f}" if percent else "%{z:d}",
                    textfont={"size": 10},
                    colorscale="Viridis",
                    customdata=[[f"{row} × {col}" for col in x_full] for row in y_full],
                    hovertemplate="<b>%{customdata}</b><br>Значение: %{z}<extra></extra>"
                ))

                fig.update_layout(
                    title=f"{primary} × {secondary}",
                    xaxis_title=secondary,
                    yaxis_title=primary,
                    xaxis_tickangle=-45,
                    height=height,
                    width=width,
                    margin=dict(l=180, r=30, t=90, b=100),  # t=90 вместо 60
                    font=dict(size=10),
                    hoverlabel=dict(font_size=12),
                    title_pad=dict(t=20)   # дополнительный отступ заголовка от верха
                )
                fig.update_xaxes(automargin=True, tickfont=dict(size=9), title_standoff=25)
                fig.update_yaxes(automargin=True, tickfont=dict(size=9), title_standoff=35)  # 35 вместо 20

                st.plotly_chart(fig, use_container_width=False)

except Exception as e:
    st.exception(e)
