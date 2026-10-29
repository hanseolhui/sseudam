// Execute the production polling functions with a fake API and deterministic timers.
const {test}=require('node:test'); const assert=require('node:assert/strict');
const fs=require('node:fs'), vm=require('node:vm');
function harness() {
 const source=fs.readFileSync('app/static/app.js','utf8');
 let resolve, reject, calls=0, renders=0, timers=0;
 const element={classList:{add(){}},innerHTML:'',className:''};
 const c=vm.createContext({state:{jobsActive:1,lastJobIds:'1'},api:()=>{calls++;return new Promise((a,b)=>{resolve=a;reject=b})},$:()=>element,renderJobsPanel(){},toast(){},refreshCurrent(){renders++},isRecent:()=>true,clearTimeout(){},setTimeout(){timers++;return timers}});
 vm.runInContext(source.slice(source.indexOf('let pollTimer,'),source.indexOf('function isRecent(')),c);
 return {c,get calls(){return calls},get renders(){return renders},get timers(){return timers},resolve:d=>resolve(d),reject:()=>reject(Error('offline'))};
}
test('overlapping triggers share a request; completion refreshes once',async()=>{
 const h=harness(),a=vm.runInContext('pollJobs()',h.c),b=vm.runInContext('pollJobs()',h.c);
 assert.equal(a,b);assert.equal(h.calls,1);
 h.resolve({active:0,jobs:[{id:2,status:'완료',label:'test'}]});await a;
 assert.equal(h.renders,1);assert.equal(h.timers,1);
});
test('network failure releases the runner and preserves retry',async()=>{
 const h=harness(),a=vm.runInContext('pollJobs()',h.c);h.reject();await a;
 assert.equal(h.timers,1);
 const b=vm.runInContext('pollJobs()',h.c);assert.equal(h.calls,2);
 h.resolve({active:0,jobs:[]});await b;assert.equal(h.timers,2);
});
