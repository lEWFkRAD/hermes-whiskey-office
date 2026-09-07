const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync(__dirname+'/office-context-plugin.js','utf8').replace(/^import .*;$/mg,'').replace(/export default /,'globalThis.plugin = ').replace(/export (async )?function /g,'$1function ');
const sandbox={setTimeout,clearTimeout,Date,JSON};vm.createContext(sandbox);vm.runInContext(source,sandbox);
const now=Date.now()/1000,cwd='/office/workspace';
const scene={schema:1,running:true,workspace:cwd,updated_at:now,windows:[{id:'hermes',title:'Hermes',active:true,position_m:[1,2,3]}],podium:'amber chair'};
let enabled=true,session='one',currentCwd=cwd,raw=scene;
const deps={enabled:()=>enabled,session:()=>session,cwd:()=>currentCwd,read:async()=>({text:JSON.stringify(raw),byteSize:100}),now:()=>now};
const draft={text:'What is on the podium?',attachments:[{id:'preserve'}]};
(async()=>{
 const good=await sandbox.enrich(draft,deps);assert(good.text.includes('amber chair'));assert.equal(good.attachments,draft.attachments);
 for(const altered of [{...scene,updated_at:now-4},{...scene,updated_at:now+5},{...scene,running:false},{...scene,workspace:'/other'},{...scene,schema:2},{...scene,windows:Array(9).fill({})}]){raw=altered;assert.equal(await sandbox.enrich(draft,deps),draft);}
 raw=scene;enabled=false;assert.equal(await sandbox.enrich(draft,deps),draft);enabled=true;
 assert.equal((await sandbox.enrich({text:'/help'},deps)).text,'/help');
 assert.equal(await sandbox.enrich(draft,{...deps,read:async()=>{throw Error('offline')}}),draft);
 assert.equal(await sandbox.enrich(draft,{...deps,read:async()=>({text:'bad JSON'})}),draft);
 assert.equal(await sandbox.enrich(draft,{...deps,read:async()=>{session='two';return {text:JSON.stringify(scene)}}}),draft);
 session='one';assert.equal(await sandbox.enrich(draft,{...deps,read:async()=>{currentCwd='/other';return {text:JSON.stringify(scene)}}}),draft);currentCwd=cwd;
 assert.equal(await sandbox.enrich(draft,{...deps,read:()=>new Promise(()=>{})}),draft);
 const selected=sandbox.sceneFacts({...scene,secret:'MUST NOT APPEAR',microphone:'listening'},cwd,now);assert(!JSON.stringify(selected).includes('MUST NOT APPEAR'));assert(!Object.hasOwn(selected,'microphone'));
 const atom=value=>({get:()=>value});let registrations=[];
 sandbox.host={state:{cwd:atom('/another/project'),focusedSessionId:atom('one'),connectionId:atom('local'),focusedSessionProfile:atom('default')}};
 sandbox.window={hermesDesktop:{sanitizeWorkspaceCwd:async()=>({cwd}),readFileText:async path=>{assert.equal(path,cwd+'/.hermes-office-context.json');return {text:JSON.stringify({...scene,updated_at:Date.now()/1000})};}}};
 sandbox.plugin.register({storage:{get:()=>true},register:item=>registrations.push(item)});
 await Promise.resolve();
 const integrated=await registrations.find(r=>r.area==='composer.middleware').data.handler(draft);
 assert(integrated.text.includes('amber chair'));
 console.log('HERMES_OFFICE_CONTEXT_TESTS: 17 checks passed');
})().catch(e=>{console.error(e);process.exit(1)});
