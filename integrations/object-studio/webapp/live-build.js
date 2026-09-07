/* The gallery contains real outputs from one inference. No simulated mesh growth. */
let liveJob = null, liveChoice = 'auto';
let liveToken = '', meshSeenAt = 0, liveTimer = null, replaying = false;
const liveNames = {photo:'Original',cutout:'Cutout',mesh:'Surface',wire:'Wireframe',final:'Finished'};
function renderLiveBuild(job) {
  const hasHistory = job.has_photo;
  show('buildNavigation',hasHistory);
  if (!hasHistory) { show('buildPreview',false); return; }
  if (liveJob !== job.id) {
    clearTimeout(liveTimer); liveJob=job.id; liveChoice='auto'; liveToken=''; meshSeenAt=0; replaying=false;
  }
  const checkpoints=job.checkpoints || {}, ready=job.status==='success';
  const available = {photo:job.photo_url,cutout:checkpoints.cutout?.url,mesh:checkpoints.mesh?.url,wire:checkpoints.wire?.url,final:ready?job.model_url:null};
  const token=JSON.stringify([job.status,job.stage,Object.keys(checkpoints)]);
  if (liveToken!==token) { liveToken=token; liveChoice='auto'; replaying=false; }
  if (available.mesh && !meshSeenAt) {
    meshSeenAt=Date.now();
    const key=job.id;
    clearTimeout(liveTimer);
    liveTimer=setTimeout(()=>{if(liveJob===key && liveChoice==='auto')render();},3500);
  }
  const autoChoice=ready?'final':available.wire && (!available.mesh || Date.now()-meshSeenAt>=3500)?'wire':available.mesh?'mesh':available.cutout?'cutout':'photo';
  const choice=liveChoice==='auto' ? autoChoice : liveChoice;
  const validChoice=available[choice]?choice:'photo';
  for (const [key,label] of Object.entries(liveNames)) {
    const button=$('build-'+key); button.disabled=!available[key];
    button.setAttribute('aria-pressed',String(validChoice===key));
    const seconds=key==='photo'?0:key==='final'?(ready?job.elapsed_seconds:null):checkpoints[key]?.seconds;
    button.textContent=label+(seconds==null?'':` · ${Math.round(seconds)}s`);
    button.onclick=()=>{clearTimeout(liveTimer); replaying=false; liveChoice=key; render();};
  }
  $('followBuild').textContent=ready?(replaying?'Stop replay':'Replay build ▶'):(liveChoice==='auto'?'Auto-advancing':'Resume auto');
  $('followBuild').setAttribute('aria-pressed',String(ready?replaying:liveChoice==='auto'));
  show('followBuild',job.status==='processing' || ready);
  $('followBuild').onclick=()=>{
    clearTimeout(liveTimer);
    if (!ready || replaying) {replaying=false;liveChoice='auto';render();return;}
    replaying=true;
    const steps=Object.keys(liveNames).filter(key=>available[key]), key=job.id;
    let index=0;
    function advance() {
      if(liveJob!==key || !replaying)return;
      liveChoice=steps[index++];render();
      if(index<steps.length)liveTimer=setTimeout(advance,2500);
      else {replaying=false;liveChoice='auto';render();}
    }
    advance();
  };
  const final=validChoice==='final', mesh=['mesh','wire'].includes(validChoice);
  show('workingView',false); show('buildPreview',!final); show('modelViewer',final);
  show('viewerSettings',final); show('resetView',final);
  show('buildPhoto',!mesh); show('buildMesh',mesh);
  if (!final) {
    const element=mesh?$('buildMesh'):$('buildPhoto');
    const url=available[validChoice];
    if(element.getAttribute('src')!==url) element.setAttribute('src',url);
    $('buildPhoto').alt=validChoice==='cutout'?'Actual background-removal result':'Original source photo';
    $('buildCaption').textContent=mesh?(job.preview_method==='vertex-cluster-48'?'Actual decoded mesh · simplified for live viewing. Fine detail and final topology arrive in the finished model.':'Actual decoded mesh · sampled faces for a lightweight preview. Gaps here are not the final topology.'):validChoice==='cutout'?'The actual isolated object used by this generation.':'Your saved input to this generation.';
    $('buildStage').textContent=job.status==='processing'?`${job.stage} · ${durations(job.elapsed_seconds)} elapsed`:['failed','cancelled'].includes(job.status)?(job.error || 'Generation stopped. Available checkpoints are saved.'):'Saved build checkpoint';
  }
  $('buildNote').textContent=job.preview_warning || (!checkpoints.cutout && job.status!=='processing'?'No intermediate outputs were recorded for this run.':'Real checkpoints from this build. Live geometry is simplified; the finished model keeps full output detail.');
}
