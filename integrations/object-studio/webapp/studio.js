'use strict';
const $ = id => document.getElementById(id);
let jobs = [], selected = new URLSearchParams(location.search).get('job'), draft = null, draftUrl = null;
let busy = false, requestKey = crypto.randomUUID(), modelSrc = '', imported = null, pollBusy = false;
let librarySignature = '';
const durations = seconds => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
const show = (id, visible) => { $(id).hidden = !visible; };
function notice(message, success = false, action = null) {
  const box = $('notice'); box.replaceChildren(document.createTextNode(message));
  box.className = 'notice' + (success ? ' success' : ''); box.hidden = false;
  if (action) { const button = document.createElement('button'); button.textContent = action.label; button.onclick = action.run; box.append(button); }
}
async function api(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) { const detail = body.detail; const error = new Error(typeof detail === 'string' ? detail : detail?.message || 'The app could not complete this request. Please try again.'); error.activeJob = detail?.active_job_id; error.status = response.status; throw error; }
  return body;
}
function select(key) {
  selected = key; imported = null; $('sendBlender').textContent = 'Send to Blender ↗';
  history.replaceState(null, '', key ? '?job=' + encodeURIComponent(key) : location.pathname);
  show('notice', false); render(); if (key) refresh();
}
function newObject() { select(null); $('title').scrollIntoView({behavior:'smooth', block:'start'}); }
function renderLibrary() {
  const signature = JSON.stringify([selected, jobs.map(j => [j.id,j.name,j.stage,j.photo_url,j.created_at])]);
  if (signature === librarySignature) {
    jobs.filter(j => j.status === 'processing').forEach(j => {
      const card = document.querySelector('[data-job="' + j.id + '"] small');
      if (card) card.textContent = 'Working · ' + durations(j.elapsed_seconds);
    });
    return;
  }
  librarySignature = signature;
  $('count').textContent = jobs.length; $('jobList').replaceChildren();
  if (!jobs.length) { const empty = document.createElement('p'); empty.className = 'empty-library'; empty.textContent = 'Your first object starts with a photo. Finished models will appear here.'; $('jobList').append(empty); }
  jobs.forEach(job => {
    const card = document.createElement('button'); card.className = 'job-card' + (job.id === selected ? ' selected' : '');
    card.dataset.job = job.id;
    card.setAttribute('aria-label', job.name + ', ' + job.stage);
    const thumb = document.createElement(job.photo_url ? 'img' : 'span'); thumb.className = 'job-thumb';
    if (job.photo_url) { thumb.src = job.photo_url; thumb.alt = ''; thumb.loading = 'lazy'; } else thumb.textContent = '◈';
    const info = document.createElement('span'); const title = document.createElement('strong'); title.textContent = job.name;
    const subtitle = document.createElement('small'); subtitle.textContent = job.status === 'processing' ? 'Working · ' + durations(job.elapsed_seconds) : job.status === 'cancelled' ? 'Stopped' : job.status === 'failed' ? 'Needs attention' : 'Ready · ' + new Date(job.created_at * 1000).toLocaleDateString(undefined, {month:'short',day:'numeric'});
    info.append(title, subtitle); card.append(thumb, info); card.onclick = () => select(job.id); $('jobList').append(card);
  });
}
function render() {
  renderLibrary();
  const active = jobs.find(j => j.status === 'processing');
  show('activeBanner', Boolean(active && active.id !== selected));
  if (active && active.id !== selected) {
    $('activeBanner').replaceChildren(document.createTextNode(`${active.name} is working · ${durations(active.elapsed_seconds)} elapsed`));
    const button = document.createElement('button'); button.className = 'text-button'; button.textContent = 'Open job →'; button.onclick = () => select(active.id); $('activeBanner').append(button);
  }
  $('generate').disabled = !draft || busy || Boolean(active);
  $('generate').textContent = busy ? 'Saving your photo…' : active ? 'Forge is working on another object' : 'Generate object ↗';
  show('captureView', !selected); show('jobView', Boolean(selected)); show('backToCapture', Boolean(selected));
  if (!selected) { $('title').textContent = 'Make something tangible.'; $('subtitle').textContent = 'One clear photo. A textured object. Ready for Blender.'; $('workspaceEyebrow').textContent = 'FROM YOUR WORLD TO 3D'; return; }
  const job = jobs.find(j => j.id === selected); if (!job) return;
  $('title').textContent = job.name; $('workspaceEyebrow').textContent = 'YOUR OBJECT';
  $('subtitle').textContent = job.status === 'success' ? 'Take a look from every angle, then bring it into Blender.' : job.status === 'failed' ? 'Your source photo is saved. You can try again.' : 'Your photo is saved. We’ll keep working if you leave this page.';
  const ready = job.status === 'success', working = job.status === 'processing';
  $('jobBadge').textContent = ready ? 'Ready' : working ? (job.stop_requested?'Stopping':'In progress') : job.status==='cancelled'?'Stopped':'Needs attention';
  show('stopJob',working); $('stopJob').disabled=Boolean(job.stop_requested);
  $('stopJob').textContent=job.stop_requested?'Stopping on Forge…':'Stop job';
  if(job.status==='cancelled')$('subtitle').textContent='Stopped. Your photo and available checkpoints are saved.';
  show('workingView', !ready); show('modelViewer', ready); show('viewerSettings', ready); show('resetView', ready);
  show('sendBlender', ready); show('downloadModel', ready); show('retryJob', !working && job.has_photo); show('leaveJob', working); show('deleteJob', !working);
  $('retryJob').textContent = ready ? 'Regenerate from photo' : 'Retry saved photo'; $('retryJob').disabled = busy || Boolean(active);
  $('stage').textContent = job.stage; $('elapsed').textContent = durations(job.elapsed_seconds) + ' elapsed';
  $('workingHint').textContent = job.error || 'You can leave this page. Your job and photo are saved.'; show('workingIcon', working && !job.photo_url);
  show('stageSteps', working); const stage = /Checking/.test(job.stage) ? 2 : /Connecting/.test(job.stage) ? 0 : 1;
  [...$('stageSteps').children].forEach((el, i) => el.classList.toggle('done', i <= stage));
  for (const id of ['savedPhoto','workingPhoto']) { show(id, Boolean(job.photo_url)); if (job.photo_url && $(id).getAttribute('src') !== job.photo_url) $(id).src = job.photo_url; }
  $('sourceCaption').textContent = job.has_photo ? 'Saved source photo' : 'Source photo unavailable for this earlier model';
  $('jobDetails').textContent = `${job.preset === 'fast' ? 'Fast' : 'Detailed'} · ${new Date(job.created_at*1000).toLocaleString()}`;
  $('modelStats').textContent = ready ? job.metrics ? `${job.metrics.triangles.toLocaleString()} faces · ${(job.metrics.bytes/1048576).toFixed(1)} MB · ${durations(job.elapsed_seconds)}` : 'Saved GLB model' : 'One local job at a time';
  if (ready) {
    $('downloadModel').href = job.model_url; $('downloadModel').download = job.name + '.glb';
    if (modelSrc !== job.model_url) {
      modelSrc = job.model_url; $('modelViewer').src = modelSrc;
      $('modelViewer').setAttribute('camera-orbit','0deg 75deg auto');
    }
  }
  renderLiveBuild(job);
}
async function refresh() {
  if (pollBusy) return; pollBusy = true;
  try {
    const data = await api('/api/jobs'); jobs = data.jobs;
    $('connection').textContent = data.blender_connected ? 'Blender connected' : 'Blender not connected'; $('connection').classList.toggle('online', data.blender_connected);
    if (selected && !jobs.some(j => j.id === selected)) { selected = null; history.replaceState(null,'',location.pathname); notice('This job is unavailable. Choose an object from your workspace.'); }
    render();
  } catch (error) { $('connection').textContent = 'Reconnecting…'; $('connection').classList.remove('online'); }
  finally { pollBusy = false; }
}
async function setPhoto(file) {
  if (!file) return;
  if (file.size > 20*1024*1024) { notice('Choose a photo smaller than 20 MB.'); return; }
  if (!['image/png','image/jpeg','image/webp'].includes(file.type)) { notice('Choose a JPG, PNG or WebP photo. If your phone uses HEIC, use Take a photo or export it as JPEG.'); return; }
  try {
    const bitmap = await createImageBitmap(file); const width = bitmap.width, height = bitmap.height; bitmap.close();
    if (Math.min(width,height) < 32 || width*height > 40_000_000) throw new Error('Use a photo at least 32 pixels wide and under 40 megapixels.');
    if (draftUrl) URL.revokeObjectURL(draftUrl);
    draft = file; draftUrl = URL.createObjectURL(file); requestKey = crypto.randomUUID();
    $('sourcePreview').src = draftUrl; show('sourcePreview', true); show('emptyCapture', false); show('draftControls', true); show('notice', false);
    if (!$('objectName').value) $('objectName').value = file.name && !/^(image|photo|capture|[0-9a-f]{8}-[0-9a-f]{4}-)/i.test(file.name) ? file.name.replace(/\.[^.]+$/, '').slice(0,80) : '';
    select(null);
  } catch (error) { notice(error.message || 'This photo could not be opened. Try another image.'); }
}
async function transformPhoto(crop) {
  if (!draft) return;
  try {
    const image = await createImageBitmap(draft); const canvas = document.createElement('canvas'); const ctx = canvas.getContext('2d');
    if (crop) { const size = Math.min(image.width,image.height); canvas.width=canvas.height=size; ctx.drawImage(image,(image.width-size)/2,(image.height-size)/2,size,size,0,0,size,size); }
    else { canvas.width=image.height; canvas.height=image.width; ctx.translate(canvas.width/2,canvas.height/2); ctx.rotate(Math.PI/2); ctx.drawImage(image,-image.width/2,-image.height/2); }
    image.close(); const blob = await new Promise(resolve => canvas.toBlob(resolve,'image/png')); await setPhoto(blob);
  } catch (_) { notice('Could not edit this photo. Try choosing it again.'); }
}
async function submit() {
  if (!draft || busy) return; busy=true; render(); show('notice',false);
  const data = new FormData(); data.append('image', draft, 'photo.png'); data.append('request_key',requestKey); data.append('name',$('objectName').value || 'Untitled object'); data.append('preset',document.querySelector('input[name=quality]:checked').value);
  try { const result = await api('/generate3d',{method:'POST',body:data}); selected=result.job_id; history.replaceState(null,'','?job='+selected); await refresh(); }
  catch (error) { notice(error.message,false,error.activeJob ? {label:'Open running job',run:()=>select(error.activeJob)} : null); }
  finally { busy=false; render(); }
}
async function retry() {
  if (busy) return; busy=true; render();
  const data = new FormData(); data.append('request_key',crypto.randomUUID());
  try { const result=await api('/api/jobs/'+selected+'/retry',{method:'POST',body:data}); selected=result.job_id; history.replaceState(null,'','?job='+selected); await refresh(); }
  catch (error) { notice(error.message,false,error.activeJob ? {label:'Open running job',run:()=>select(error.activeJob)} : null); }
  finally { busy=false; render(); }
}
async function send() {
  const key=selected; $('sendBlender').disabled=true; $('sendBlender').textContent='Waiting for Blender…';
  try {
    const result=await api('/api/jobs/'+key+'/import',{method:'POST'});
    notice('Sending to Blender. Waiting for its import confirmation…');
    for (let i=0;i<95;i++) {
      const state=await api('/api/imports/'+result.request_id);
      if (state.status === 'success') { if(selected===key) { imported=key; notice(`Imported in Blender · ${state.meshes} mesh${state.meshes===1?'':'es'}.`,true); } return; }
      if(state.status !== 'pending') throw new Error(state.error || 'Blender could not import the model.');
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
    throw new Error('Import confirmation timed out. Check Blender before sending again.');
  } catch(error) { if(selected===key) notice(error.message); }
  finally { $('sendBlender').disabled=false; $('sendBlender').textContent=imported===selected?'Imported ✓':'Send to Blender ↗'; }
}
async function trash() {
  const key=selected;
  try { await api('/api/jobs/'+key,{method:'DELETE'}); select(null); await refresh(); notice('Moved to trash. Files are retained locally until you remove them.',false,{label:'Undo',run:async()=>{try{await api('/api/jobs/'+key+'/restore',{method:'POST'}); await refresh(); select(key);}catch(e){notice(e.message);}}}); }
  catch(error){notice(error.message);}
}
$('takePhoto').onclick=()=>$('cameraInput').click(); $('choosePhoto').onclick=()=>$('fileInput').click(); $('replacePhoto').onclick=()=>$('fileInput').click();
for(const id of ['cameraInput','fileInput']) $(id).onchange=event=>{setPhoto(event.target.files[0]); event.target.value='';};
$('rotatePhoto').onclick=()=>transformPhoto(false); $('cropPhoto').onclick=()=>transformPhoto(true);
$('generate').onclick=submit; $('newObject').onclick=newObject; $('backToCapture').onclick=newObject; $('leaveJob').onclick=newObject;
$('retryJob').onclick=retry; $('sendBlender').onclick=send; $('deleteJob').onclick=trash;
$('stopJob').onclick=async()=>{
  const key=selected; $('stopJob').disabled=true;
  try {await api('/api/jobs/'+key+'/stop',{method:'POST'});await refresh();}
  catch(error){notice(error.message);$('stopJob').disabled=false;}
};
document.querySelectorAll('input[name=quality]').forEach(input=>input.onchange=()=>{requestKey=crypto.randomUUID();});
$('dropZone').ondragover=event=>{event.preventDefault(); $('dropZone').classList.add('dragging');}; $('dropZone').ondragleave=()=>$('dropZone').classList.remove('dragging');
$('dropZone').ondrop=event=>{event.preventDefault(); $('dropZone').classList.remove('dragging'); setPhoto(event.dataTransfer.files[0]);};
$('lighting').oninput=event=>$('modelViewer').setAttribute('exposure',event.target.value);
$('rotateModel').onchange=event=>$('modelViewer').toggleAttribute('auto-rotate',event.target.checked);
$('resetView').onclick=()=>{$('modelViewer').setAttribute('camera-orbit','0deg 75deg auto'); $('modelViewer').setAttribute('camera-target','auto auto auto');};
$('modelViewer').addEventListener('error',()=>notice('The 3D preview could not load. Your saved model is still available to download or send to Blender.'));
$('buildMesh').addEventListener('error',()=>notice('This live mesh could not load. You can view another checkpoint; generation continues.'));
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
render(); refresh(); setInterval(()=>{if(!document.hidden)refresh();},3000);
