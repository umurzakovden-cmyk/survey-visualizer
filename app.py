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
            # Гарантированно убираем любые дубликаты индексов/колонок
            cross = cross.loc[~cross.index.duplicated(), ~cross.columns.duplicated()]
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
            # Дополнительная чистка дубликатов
            cross = cross.loc[~cross.index.duplicated(), ~cross.columns.duplicated()]
            if cross.empty:
                st.warning("Нет данных")
            else:
                if percent:
                    cross = cross.div(cross.sum(axis=1), axis=0).fillna(0) * 100
                # Плавкий «длинный» формат без конфликтов индексов
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
            cross = cross.loc[~cross.index.duplicated(), ~cross.columns.duplicated()]
            if cross.empty:
                st.warning("Нет данных")
            else:
                if percent:
                    cross = cross.div(cross.sum(axis=1), axis=0).fillna(0) * 100
                # Тепловая карта через go.Heatmap — никаких DataFrame в Plotly
                fig = go.Figure(data=go.Heatmap(
                    z=cross.values,
                    x=cross.columns.astype(str).tolist(),
                    y=cross.index.astype(str).tolist(),
                    texttemplate="%{z:.1f}" if percent else "%{z:d}",
                    textfont={"size": 10},
                    colorscale="Viridis"
                ))
                fig.update_layout(
                    title=f"{primary} × {secondary}",
                    xaxis_title=secondary,
                    yaxis_title=primary,
                    xaxis_tickangle=-30
                )
                st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    # Вместо короткой ошибки показываем полный трейс
    st.exception(e)
