import test from 'node:test';
import assert from 'node:assert/strict';
import {starterWidgets} from '../src/dashboards.js';

test('numeric data gets metrics and a grouped chart instead of SELECT * charts', () => {
  const widgets = starterWidgets({table_name:'sample_sales',columns:[{name:'month',type:'TEXT'},{name:'region',type:'TEXT'},{name:'revenue',type:'REAL'}]});
  assert.equal(widgets.length, 4);
  const chart = widgets.find(w=>w.type==='bar');
  assert.match(chart.sql, /SUM\("revenue"\)/);
  assert.match(chart.sql, /GROUP BY "region"/);
  assert.ok(widgets.every(w=>w.sql.includes('"sample_sales"')));
});
test('text-only datasets get a count and a table rather than a numeric chart', () => {
  assert.deepEqual(starterWidgets({table_name:'contacts',columns:[{name:'name',type:'TEXT'}]}).map(w=>w.type), ['metric','table']);
  assert.deepEqual(starterWidgets(null), []);
});
test('reserved SQL names are quoted and chronological fields use line charts', () => {
  const widgets = starterWidgets({table_name:'order',columns:[{name:'month',type:'TEXT'},{name:'total',type:'REAL'}]});
  const line = widgets.find(w=>w.type==='line');
  assert.match(line.sql, /FROM "order"/);
  assert.match(line.sql, /ORDER BY "month"/);
});
