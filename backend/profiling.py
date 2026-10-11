"""Deterministic profiling of the bounded, authorized dataset snapshot."""
import math
import statistics
from collections import Counter
from datetime import date


def profile_dataset(columns, rows):
    count = len(rows)
    duplicates = sum(n - 1 for n in Counter(tuple(row) for row in rows).values())
    profiles = []
    missing_cells = 0
    for index, column in enumerate(columns):
        values = [row[index] for row in rows]
        present = [v for v in values if v is not None and v != '']
        missing = count - len(present)
        missing_cells += missing
        item = {
            **column, 'missing_count': missing,
            'missing_percentage': round(100 * missing / count, 2) if count else 0,
            'unique_count': len(set(present)),
        }
        if column['type'] == 'REAL':
            numbers = [float(v) for v in present if math.isfinite(float(v))]
            item['invalid_count'] = len(present) - len(numbers)
            if numbers:
                ordered = sorted(numbers)
                # Inclusive interpolated quartiles; valid for small datasets too.
                def quantile(p):
                    position = (len(ordered) - 1) * p
                    lo = int(position)
                    hi = min(lo + 1, len(ordered) - 1)
                    return ordered[lo] * (hi - position) + ordered[hi] * (position - lo) if hi != lo else ordered[lo]
                q1, q3 = quantile(.25), quantile(.75)
                spread = q3 - q1
                item['numeric'] = {
                    'min': min(numbers), 'max': max(numbers),
                    'mean': statistics.mean(numbers), 'median': statistics.median(numbers),
                    'q1': q1, 'q3': q3,
                    'outlier_count': sum(v < q1 - 1.5 * spread or v > q3 + 1.5 * spread for v in numbers),
                }
        else:
            dates = []
            for value in present:
                try:
                    dates.append(date.fromisoformat(str(value)))
                except ValueError:
                    pass
            if dates and len(dates) == len(present):
                item['date_range'] = {'min': min(dates).isoformat(), 'max': max(dates).isoformat()}
        profiles.append(item)
    cells = count * len(columns)
    completeness = 1 - missing_cells / cells if cells else 1
    uniqueness = 1 - duplicates / count if count else 1
    return {
        'row_count': count, 'column_count': len(columns),
        'duplicate_rows': duplicates, 'missing_cells': missing_cells,
        'quality_score': round(100 * completeness * uniqueness, 2),
        'score_definition': '100 × cell completeness × row uniqueness; not a domain accuracy score',
        'columns': profiles,
    }
