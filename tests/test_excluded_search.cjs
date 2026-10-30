const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app/static/app.js','utf8'),ctx={};vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('function matchesExcludedRecording('),source.indexOf('async function viewExcludedRecordings(')),ctx);
const match=ctx.matchesExcludedRecording;
test('search matches transcript or title with normalized Korean and case',()=>{
 const item={title:'회의',transcript:'상담 내용 ABC',recorded_at:'2026-10-30 23:59'};
 assert.ok(match(item,{query:'상담'.normalize('NFD')}));assert.ok(match(item,{query:'abc'}));assert.ok(match(item,{query:'회의'}));assert.ok(!match(item,{query:'없는말'}));
});
test('inclusive recording date bounds and combined search',()=>{
 const item={title:'회의',transcript:'상담',recorded_at:'2026-10-30 23:59'};
 assert.ok(match(item,{query:'상담',from:'2026-10-30',to:'2026-10-30'}));
 assert.ok(!match(item,{from:'2026-10-31'}));assert.ok(!match(item,{to:'2026-10-29'}));assert.ok(!match(item,{from:'2026-10-31',to:'2026-10-01'}));
 assert.ok(!match({title:'날짜 없음'},{from:'2026-10-01'}));assert.ok(match({title:'날짜 없음'},{}));
});
