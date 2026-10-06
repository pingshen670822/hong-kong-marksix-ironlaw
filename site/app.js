document.querySelectorAll('nav button').forEach((button,index)=>{if(!index)button.classList.add('on');button.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(tab=>tab.classList.remove('active'));document.querySelectorAll('nav button').forEach(item=>item.classList.remove('on'));document.getElementById(button.dataset.tab)?.classList.add('active');button.classList.add('on');window.scrollTo({top:0,behavior:'smooth'})})});
const pageHash=document.querySelector('meta[name="report-version"]')?.content||'';
const refreshButton=document.getElementById('manual-refresh');
const repairButton=document.getElementById('emergency-repair');
const actionStatus=document.getElementById('cloud-action-status');
const lastManualUpdate=document.getElementById('last-manual-update');
const manualUpdateKey='marksix-last-manual-update';
const rescueUrl='https://github.com/pingshen670822/hong-kong-marksix-ironlaw/actions/workflows/cloud-self-repair.yml';
function taipeiNow(){return new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date())}
function setStatus(message,state=''){if(!actionStatus)return;actionStatus.textContent=message;actionStatus.className='cloud-action-status'+(state?' '+state:'')}
function setBusy(busy){[refreshButton,repairButton].forEach(button=>{if(button)button.disabled=busy})}
function readManualRecord(){try{return JSON.parse(localStorage.getItem(manualUpdateKey)||'null')}catch(error){return null}}
function renderManualRecord(record=readManualRecord()){if(!lastManualUpdate)return;if(record?.completedAt){lastManualUpdate.textContent=`${record.completedAt}（${record.date||'日期待確認'}／${record.period||'期別待確認'}）`}}
function saveManualRecord(snapshot){const draw=snapshot.analysis?.latest_draw||{};const record={completedAt:taipeiNow(),date:draw.date||'',period:draw.period||'',hash:snapshot.version?.hash||pageHash};try{localStorage.setItem(manualUpdateKey,JSON.stringify(record))}catch(error){}renderManualRecord(record);return record}
async function fetchJson(path){const response=await fetch(`${path}?t=${Date.now()}`,{cache:'no-store'});if(!response.ok)throw new Error(`${path}:${response.status}`);return response.json()}
async function fetchVersion(){return fetchJson('version.json')}
async function cloudSnapshot(){const [version,analysis]=await Promise.all([fetchVersion(),fetchJson('latest_analysis.json')]);let health=null;try{health=await fetchJson('health_status.json')}catch(error){}return {version,analysis,health}}
function reloadWith(key,value){const url=new URL(location.href);url.searchParams.set(key,value);location.replace(url.toString())}
async function checkVersion(){try{const version=await fetchVersion();if(version.hash&&version.hash!==pageHash){reloadWith('v',version.hash)}return version}catch(error){return null}}
async function manualRefresh(){setBusy(true);setStatus('正在強制檢查雲端最新開獎資料…');try{const snapshot=await cloudSnapshot();const record=saveManualRecord(snapshot);const draw=snapshot.analysis.latest_draw||{};if(snapshot.version.hash&&snapshot.version.hash!==pageHash){setStatus(`更新完成：${record.completedAt}，發現新版，正在載入…`,'ok');setTimeout(()=>reloadWith('v',snapshot.version.hash),300);return}const healthText=snapshot.health?.healthy===false?'；健康檢測需修復':'；系統健康';setStatus(`更新完成：${record.completedAt}；最新 ${draw.date||'日期待確認'}／${draw.period||'期別待確認'}${healthText}`,'ok')}catch(error){setStatus(`更新失敗：${taipeiNow()}；暫時無法連接雲端，請按「當機立即修復」。`,'error')}finally{setBusy(false)}}
async function resetClient(){if('caches'in window){const keys=await caches.keys();await Promise.allSettled(keys.map(key=>caches.delete(key)))}if('serviceWorker'in navigator){const registrations=await navigator.serviceWorker.getRegistrations();await Promise.allSettled(registrations.map(registration=>registration.unregister()))}}
async function emergencyRepair(){setBusy(true);setStatus('正在清除失效快取並重新連接雲端…');try{await resetClient();const snapshot=await cloudSnapshot();const record=saveManualRecord(snapshot);sessionStorage.setItem('marksix-repair-result',`當機修復完成：${record.completedAt}；已重新連接 ${snapshot.analysis?.latest_draw?.period||'最新戰報'}。`);reloadWith('repair',String(Date.now()))}catch(error){sessionStorage.setItem('marksix-repair-result','本機快取已清除；雲端來源仍無法連線，已開啟第二層救援頁。');const rescue=window.open(rescueUrl,'_blank','noopener,noreferrer');if(!rescue)location.href=rescueUrl;else reloadWith('repair',String(Date.now()))}finally{setBusy(false)}}
refreshButton?.addEventListener('click',manualRefresh);
repairButton?.addEventListener('click',emergencyRepair);
renderManualRecord();
const repairResult=sessionStorage.getItem('marksix-repair-result');if(repairResult){sessionStorage.removeItem('marksix-repair-result');setStatus(repairResult,'ok')}
checkVersion();setInterval(checkVersion,60000);addEventListener('pageshow',checkVersion);addEventListener('visibilitychange',()=>{if(!document.hidden)checkVersion()});if('serviceWorker'in navigator)navigator.serviceWorker.register('service-worker.js').then(registration=>registration.update()).catch(()=>setStatus('背景快取未啟用；即時雲端資料仍可使用。','error'));