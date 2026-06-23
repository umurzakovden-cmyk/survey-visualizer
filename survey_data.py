from __future__ import annotations

import html
import re
import textwrap
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

MULTI_SEPARATOR = ";"
MISSING_VALUE_TOKEN = "(Пусто)"
AUTO_IGNORE_MAX_NON_NULL = 1  # скрываем столбцы, где ≤ 1 непустое значение


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def wrap_label(text: str, width: int = 24) -> str:
    text = clean_text(text)
    if not text:
        return text
    return "\n".join(
        textwrap.wrap(text, width=width, break_long_words=False, replace_whitespace=False)
    )


def natural_sort_key(value: object) -> Tuple:
    text = clean_text(value)
    if not text:
        return ((2, ""),)

    parts = re.split(r"(\d+(?:\.\d+)?)", text)
    key: List[Tuple[int, object]] = []
    for part in parts:
        if not part:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", part):
            key.append((0, float(part)))
        else:
            key.append((1, part.lower()))
    return tuple(key)


@dataclass
class DataColumn:
    raw_name: str
    clean_name: str
    display_name: str
    series: pd.Series
    is_multiselect: bool
    is_numeric: bool
    non_null_count: int


@dataclass
class SurveyDataset:
    path: Optional[str] = None
    sheet_name: Optional[str] = None
    raw_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    active_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    columns: Dict[str, DataColumn] = field(default_factory=dict)
    display_to_clean: Dict[str, str] = field(default_factory=dict)
    clean_to_display: Dict[str, str] = field(default_factory=dict)
    ignored_columns: List[str] = field(default_factory=list)
    multi_columns: set = field(default_factory=set)
    sheet_names: List[str] = field(default_factory=list)

    def load(self, path: str, sheet_name: Optional[str] = None) -> None:
        self.path = path
        if path.lower().endswith(".csv"):
            self.sheet_names = ["CSV"]
            self.sheet_name = "CSV"
            self.raw_df = self._read_csv_any(path)
            self._prepare_columns()
            return

        excel_file = pd.ExcelFile(path)
        self.sheet_names = excel_file.sheet_names
        if not self.sheet_names:
            raise ValueError("В файле не найдено ни одного листа")
        if sheet_name is None:
            sheet_name = self.sheet_names[0]
        self.sheet_name = sheet_name
        self.raw_df = pd.read_excel(path, sheet_name=sheet_name)
        self._prepare_columns()

    def switch_sheet(self, sheet_name: str) -> None:
        if not self.path:
            return
        self.load(self.path, sheet_name)

    def _prepare_columns(self) -> None:
        df = self.raw_df.copy()
        df.columns = [
            clean_text(col) or f"Колонка {idx + 1}"
            for idx, col in enumerate(df.columns)
        ]
        self.columns = {}
        self.display_to_clean = {}
        self.clean_to_display = {}
        self.ignored_columns = []
        self.multi_columns = set()
        display_counts: Dict[str, int] = {}

        for idx, col in enumerate(df.columns):
            series = df.iloc[:, idx]
            series = series.map(
                lambda x: np.nan if clean_text(x) == "" else clean_text(x)
            )
            non_null = int(series.notna().sum())
            if non_null <= AUTO_IGNORE_MAX_NON_NULL:
                self.ignored_columns.append(col)
                continue

            non_null_values = series.dropna()
            multiselect_ratio = (
                float(
                    non_null_values.str.contains(
                        re.escape(MULTI_SEPARATOR), regex=True
                    ).mean()
                )
                if not non_null_values.empty
                else 0.0
            )
            is_multiselect = multiselect_ratio >= 0.05
            is_numeric = False
            if not is_multiselect and not non_null_values.empty:
                converted = pd.to_numeric(non_null_values, errors="coerce")
                is_numeric = bool(converted.notna().mean() >= 0.9)

            clean_name = col
            display_name = clean_name
            display_counts.setdefault(display_name, 0)
            display_counts[display_name] += 1
            if display_counts[display_name] > 1:
                display_name = f"{display_name} ({display_counts[display_name]})"

            column = DataColumn(
                raw_name=col,
                clean_name=clean_name,
                display_name=display_name,
                series=series,
                is_multiselect=is_multiselect,
                is_numeric=is_numeric,
                non_null_count=non_null,
            )
            self.columns[clean_name] = column
            self.display_to_clean[display_name] = clean_name
            self.clean_to_display[clean_name] = display_name
            if is_multiselect:
                self.multi_columns.add(clean_name)

        prepared: Dict[str, pd.Series] = {
            cn: self.columns[cn].series for cn in self.columns
        }
        self.active_df = pd.DataFrame(prepared)

    @staticmethod
    def _read_csv_any(path: str) -> pd.DataFrame:
        encodings = ["utf-8-sig", "utf-8", "cp1251", "latin-1"]
        last_exc = None
        for encoding in encodings:
            try:
                return pd.read_csv(path, encoding=encoding)
            except Exception as exc:
                last_exc = exc
        if last_exc:
            raise last_exc
        raise ValueError("Не удалось прочитать CSV")

    @property
    def chartable_columns(self) -> List[str]:
        return list(self.columns.keys())

    def get_display_names(self) -> List[str]:
        return [self.clean_to_display[col] for col in self.chartable_columns]

    def to_clean_name(self, display_or_clean: str) -> str:
        return self.display_to_clean.get(display_or_clean, display_or_clean)

    def is_multiselect(self, column_name: str) -> bool:
        return self.to_clean_name(column_name) in self.multi_columns

    def get_unique_values(
        self, column_name: str, include_missing: bool = True
    ) -> List[str]:
        clean_name = self.to_clean_name(column_name)
        column = self.columns[clean_name]
        values = column.series.dropna()
        if column.is_multiselect:
            items: List[str] = []
            for cell in values:
                items.extend(self._split_multiselect(cell))
            unique_values = sorted(set(items), key=natural_sort_key)
        else:
            unique_values = sorted(
                {clean_text(v) for v in values}, key=natural_sort_key
            )
        if include_missing and column.series.isna().any():
            unique_values.append(MISSING_VALUE_TOKEN)
        return unique_values

    def filter_dataframe(
        self, filters: Sequence[Tuple[str, Sequence[str]]]
    ) -> pd.DataFrame:
        df = self.active_df.copy()
        if df.empty:
            return df
        mask = pd.Series(True, index=df.index)
        for display_or_clean, selected_values in filters:
            clean_name = self.to_clean_name(display_or_clean)
            values = [clean_text(v) for v in selected_values if clean_text(v)]
            if not values:
                continue
            series = self.columns[clean_name].series
            if self.columns[clean_name].is_multiselect:
                selected_set = {v for v in values if v != MISSING_VALUE_TOKEN}
                part_mask = series.fillna("").map(
                    lambda cell: bool(
                        selected_set.intersection(self._split_multiselect(cell))
                    )
                )
                if MISSING_VALUE_TOKEN in values:
                    part_mask = part_mask | series.isna()
            else:
                part_mask = series.isin(
                    [v for v in values if v != MISSING_VALUE_TOKEN]
                )
                if MISSING_VALUE_TOKEN in values:
                    part_mask = part_mask | series.isna()
            mask = mask & part_mask
        return df.loc[mask].copy()

    def distribution(
        self,
        df: pd.DataFrame,
        column_name: str,
        top_n: Optional[int] = None,
        drop_missing: bool = False,
    ) -> pd.Series:
        clean_name = self.to_clean_name(column_name)
        series = df[clean_name]
        column = self.columns[clean_name]
        if column.is_multiselect:
            values: List[str] = []
            for cell in series.dropna():
                values.extend(self._split_multiselect(cell))
            counts = pd.Series(values, dtype="object").value_counts()
        else:
            counts = series.fillna(MISSING_VALUE_TOKEN).value_counts()
        if drop_missing and MISSING_VALUE_TOKEN in counts.index:
            counts = counts.drop(index=MISSING_VALUE_TOKEN)
        counts = counts.sort_values(ascending=False)
        if top_n and len(counts) > top_n:
            top = counts.iloc[:top_n].copy()
            other_sum = counts.iloc[top_n:].sum()
            if other_sum:
                other_label = "Прочее"
                if other_label in top.index:
                    other_label = "Прочее (объединено)"
                top.loc[other_label] = other_sum
            counts = top
        return counts

    def free_text_answers(
        self,
        df: pd.DataFrame,
        column_name: str,
        drop_missing: bool = True,
    ) -> List[str]:
        clean_name = self.to_clean_name(column_name)
        series = df[clean_name]
        if drop_missing:
            series = series.dropna()
        else:
            series = series.fillna(MISSING_VALUE_TOKEN)
        answers = [str(value) for value in series.tolist()]
        if drop_missing:
            answers = [answer for answer in answers if clean_text(answer)]
        return answers

    def crosstab(
        self,
        df: pd.DataFrame,
        row_column: str,
        col_column: str,
        top_n_rows: Optional[int] = None,
        top_n_cols: Optional[int] = None,
    ) -> pd.DataFrame:
        row_name = self.to_clean_name(row_column)
        col_name = self.to_clean_name(col_column)
        work = df[[row_name, col_name]].copy()
        work[row_name] = work[row_name].fillna(MISSING_VALUE_TOKEN)
        work[col_name] = work[col_name].fillna(MISSING_VALUE_TOKEN)

        if self.columns[row_name].is_multiselect:
            work[row_name] = work[row_name].map(
                self._split_multiselect_with_missing
            )
            work = work.explode(row_name)
        if self.columns[col_name].is_multiselect:
            work[col_name] = work[col_name].map(
                self._split_multiselect_with_missing
            )
            work = work.explode(col_name)

        table = pd.crosstab(work[row_name], work[col_name])
        if top_n_rows and len(table.index) > top_n_rows:
            row_order = (
                table.sum(axis=1)
                .sort_values(ascending=False)
                .index[:top_n_rows]
            )
            table = table.loc[row_order]
        if top_n_cols and len(table.columns) > top_n_cols:
            col_order = (
                table.sum(axis=0)
                .sort_values(ascending=False)
                .index[:top_n_cols]
            )
            table = table.loc[:, col_order]

        # Защита от случайных дубликатов (после всех манипуляций)
        if table.index.duplicated().any():
            table = table.loc[~table.index.duplicated()]
        if table.columns.duplicated().any():
            table = table.loc[:, ~table.columns.duplicated()]
        return table

    @staticmethod
    def _split_multiselect(value: object) -> List[str]:
        text = clean_text(value)
        if not text:
            return []
        return [
            item.strip() for item in text.split(MULTI_SEPARATOR) if item.strip()
        ]

    @staticmethod
    def _split_multiselect_with_missing(value: object) -> List[str]:
        items = SurveyDataset._split_multiselect(value)
        return items if items else [MISSING_VALUE_TOKEN]
