const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const src=fs.readFileSync('app/static/app.js','utf8');
const ctx={};vm.createContext(ctx);
vm.runInContext(src.slice(src.indexOf('function profileOptions('),src.indexOf('function bindProfile(')),ctx);
test('organization-specific options include relevant targets and custom entry',()=>{
 for(const org of ['학교','유치원·어린이집','학원·교습소','과외','PT·필라테스','방과후·돌봄','기타 기관']) {
  const c=ctx.profileOptions(org);assert.equal(c.length,10);assert.ok(c[3].includes('직접 입력'));
 }
 assert.ok(ctx.profileOptions('유치원·어린이집')[3].includes('영아'));
 assert.ok(ctx.profileOptions('PT·필라테스')[3].includes('시니어'));
 assert.equal(ctx.profileOptions('학원·교습소')[4],'반 운영 방식');
 assert.equal(ctx.profileOptions('과외')[5][1],'개인 과외');
});
