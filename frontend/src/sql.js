export function previewSql(tableName) {
  return tableName ? `SELECT * FROM "${tableName.replaceAll('"', '""')}" LIMIT 100;` : 'SELECT 1 AS example;';
}
