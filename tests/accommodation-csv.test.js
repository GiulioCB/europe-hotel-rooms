import test from 'node:test';
import assert from 'node:assert/strict';
import {accommodationCsvCell as cell} from '../src/accommodation-csv.js';
test('mapping coordinates remain numbers while spreadsheet formulas in text remain escaped',()=>{
 assert.equal(cell(-33.87469552),'"-33.87469552"');assert.equal(cell(151.205568),'"151.205568"');
 assert.equal(cell('=1+1'),'"\'=1+1"');assert.equal(cell('-1+2'),'"\'-1+2"');assert.equal(cell('Hotel "A"'),'"Hotel ""A"""');
 assert.equal(cell(null),'""');assert.equal(cell(NaN),'""');assert.equal(cell(['H World Group','Jin Jiang International']),'"H World Group / Jin Jiang International"');
});
