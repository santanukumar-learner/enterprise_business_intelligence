const quote = value => `"${value.replaceAll('"', '""')}"`;

export function starterWidgets(dataset) {
  if (!dataset) return [];
  const table = quote(dataset.table_name);
  const numeric = dataset.columns.find(c => c.type === 'REAL' && /revenue|sales|amount|profit/i.test(c.name)) || dataset.columns.find(c => c.type === 'REAL');
  const category = dataset.columns.find(c => c.type === 'TEXT' && /region|product|category|department/i.test(c.name)) || dataset.columns.find(c => c.type === 'TEXT');
  const widgets = [{title: 'Total records', type: 'metric', sql: `SELECT COUNT(*) AS records FROM ${table}`}];
  if (numeric) {
    widgets.push({title: `Total ${numeric.name.replaceAll('_', ' ')}`, type: 'metric', sql: `SELECT ROUND(SUM(${quote(numeric.name)}), 2) AS total FROM ${table}`});
    if (category) widgets.push({title: `${numeric.name.replaceAll('_', ' ')} by ${category.name.replaceAll('_', ' ')}`, type: /date|month|year/i.test(category.name) ? 'line' : 'bar', sql: `SELECT ${quote(category.name)}, ROUND(SUM(${quote(numeric.name)}), 2) AS total FROM ${table} GROUP BY ${quote(category.name)} ORDER BY ${quote(category.name)} LIMIT 20`});
  }
  widgets.push({title: 'Data preview', type: 'table', sql: `SELECT * FROM ${table} LIMIT 100`});
  return widgets;
}
