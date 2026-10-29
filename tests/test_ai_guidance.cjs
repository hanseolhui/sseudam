const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('app/static/app.js','utf8');const c=vm.createContext({});vm.runInContext(source.slice(source.indexOf('function aiGuidance('),source.indexOf('async function viewSettings(')),c);
function message(choice,extra={},plus={}) {return c.aiGuidance({choice,builtin:{supported:true,models:[]},...extra},plus)}
test('API key is not described as a successful connection',()=>{assert.match(message('gemini',{has_key:false}),/키가 없어요/);assert.match(message('gemini',{has_key:true}),/외부 AI API를 선택/)});
test('offline subscription is explicit, not a fresh approval',()=>assert.match(message('plus',{}, {offline:'offline',loggedIn:true,sub:{active:true}}),/마지막 상태/));
test('local missing and downloading models have actionable guidance',()=>{assert.match(message('builtin'),/내려받아/);assert.match(message('builtin',{builtin:{supported:true,models:[{download:{status:'downloading'}}]}}),/내려받고/)});
test('manual and remote-app paths disclose external transfers',()=>{assert.match(message('manual'),/붙여넣으면/);assert.match(message('external'),/원격 서버/)});
