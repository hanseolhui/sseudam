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
ctx.esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
vm.runInContext(source.slice(source.indexOf('function excludedTextMatch('),source.indexOf('async function viewExcludedRecordings(')),ctx);
test('excerpt centers on first transcript match and escapes HTML',()=>{
 const original='앞'.repeat(100)+'<script>협력</script>'+'뒤'.repeat(100);
 const result=ctx.excludedSnippet(original,'협력');
 assert.ok(result.startsWith('…'));assert.ok(result.endsWith('…'));assert.ok(result.includes('<mark class="excluded-match">협력</mark>'));
 assert.ok(!result.includes('<script>'));assert.ok(result.length<300);assert.equal(original.includes('<script>'),true);
});
test('preview highlights literal repeated matches, handles empty and title-only queries',()=>{
 assert.equal((ctx.excludedHighlighted('A+B a+b','a+b').match(/<mark /g)||[]).length,2);
 assert.equal((ctx.excludedHighlighted('협력 협력','협력'.normalize('NFD')).match(/<mark /g)||[]).length,2);
 assert.equal(ctx.excludedHighlighted('<b>',''),'&lt;b&gt;');assert.equal(ctx.excludedSnippet('text',''),'');
 assert.ok(ctx.excludedSnippet('text','other').includes('제목에서 일치'));assert.ok(ctx.excludedSnippet('','query').includes('전사문 없음'));
});
