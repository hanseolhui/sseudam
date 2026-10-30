const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('app/static/app.js','utf8');const c=vm.createContext({});vm.runInContext(source.slice(source.indexOf('function aiGuidance('),source.indexOf('async function viewSettings(')),c);
test('free workflow includes returning and saving the external result',()=>{const s=c.aiGuidance({draft:'manual'},{});assert.match(s,/결과 붙여넣기/);assert.match(s,/저장·수정/);assert.match(s,/플러스 전용/)});
test('paid draft discloses cloud transmission and review',()=>{const s=c.aiGuidance({draft:'gemini'},{});assert.match(s,/외부 AI로 전송/);assert.match(s,/기록과 대조/)});
test('offline state offers manual workflow, never local fallback',()=>assert.match(c.aiGuidance({draft:'gemini'},{offline:true}),/외부에서 작성하고 결과를 저장/));
