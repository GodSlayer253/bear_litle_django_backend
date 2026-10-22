const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const auth = $('#auth'), dashboard = $('#dashboard'), authForm = $('#authForm');
const usernameInput = $('#username'), emailInput = $('#email'), passwordInput = $('#password');
const termsInput = $('#terms'), toast = $('#toast');
const DEPOSIT_ADDRESS = '0x4139d16c595fDEdbf0df47b171D11005B360e6C7';
let mode = 'login', logged = false, account = null, accountState = null;
const activeGames = new Map();
let toastTimer;

function notify(text) { toast.textContent=text; toast.classList.add('show'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>toast.classList.remove('show'),3500); }
function getCookie(name) { const match=document.cookie.match(new RegExp('(?:^|; )'+name.replace(/([.$?*|{}()[\]\\/+^])/g,'\\$1')+'=([^;]*)')); return match ? decodeURIComponent(match[1]) : ''; }
async function request(path, data=null, method=null) {
  const verb=method || (data===null?'GET':'POST');
  const options={method:verb,credentials:'same-origin',headers:{'X-CSRFToken':getCookie('csrftoken')}};
  if(data!==null){options.headers['Content-Type']='application/json';options.body=JSON.stringify(data);}
  const response=await fetch(path,options); let result={}; try{result=await response.json();}catch(_){}
  if(!response.ok){const e=new Error(result.message||'No se pudo completar la solicitud.');e.data=result;e.status=response.status;throw e;} return result;
}
function setMode(next) {
  mode=next; const register=mode==='register';
  $('#loginTab').classList.toggle('active',!register); $('#registerTab').classList.toggle('active',register);
  $('#authTitle').textContent=register?'Crea tu cuenta':'¡Bienvenido de nuevo!';
  $('#authSubtitle').textContent=register?'Regístrate para crear tu perfil.':'Inicia sesión para acceder a tu perfil.';
  $('#usernameWrap').classList.toggle('hidden',!register); usernameInput.required=register;
  $('#investmentNotice').classList.toggle('hidden',!register); termsInput.required=register;
  passwordInput.autocomplete=register?'new-password':'current-password';
  $('#submitAuth').innerHTML=register?'Crear cuenta <span>↗</span>':'Iniciar sesión <span>↗</span>';
  $('#message').textContent='';
}
function showAuth(next='login') { dashboard.classList.add('hidden'); auth.classList.remove('hidden'); $('#hero').classList.remove('hidden'); $('#features').classList.remove('hidden'); setMode(next); auth.scrollIntoView({behavior:'smooth',block:'start'}); }
function showDashboard(view='tasksView') {
  if(!logged){showAuth('login');$('#message').textContent='Inicia sesión o crea una cuenta para continuar.';notify('Necesitas iniciar sesión.');return;}
  auth.classList.add('hidden');$('#hero').classList.add('hidden');$('#features').classList.add('hidden');dashboard.classList.remove('hidden');setView(view);dashboard.scrollIntoView({behavior:'smooth',block:'start'});
}
function setView(id){$$('.panel-view').forEach(v=>v.classList.toggle('hidden',v.id!==id));$$('.dash-tab').forEach(t=>t.classList.toggle('active',t.dataset.view===id));}
function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function showLoggedIn(){ $('#guestActions').classList.add('hidden');$('#userActions').classList.remove('hidden');$('#headerUser').textContent=account?.username||'';$('#greetingName').textContent=account?.username||'minero'; }
function showLoggedOut(){ $('#guestActions').classList.remove('hidden');$('#userActions').classList.add('hidden'); }
function renderHistory(transactions=[]){
  const el=$('#historyList');
  if(!transactions.length){el.innerHTML='<p class="empty-history">Todavía no hay movimientos registrados.</p>';return;}
  const labels={deposit:'Depósito',withdrawal:'Retiro',game_reward:'Recompensa de minijuego'};
  el.innerHTML=transactions.map(t=>`<article class="history-item"><span class="history-icon">${t.kind==='deposit'?'💳':t.kind==='withdrawal'?'↗':'🎮'}</span><div><b>${escapeHtml(t.description||labels[t.kind]||t.kind)}</b><small>${escapeHtml(labels[t.kind]||t.kind)} · ${escapeHtml(new Date(t.created_at).toLocaleString())} · ${escapeHtml(t.status)}</small></div><strong>${t.kind==='withdrawal'?'−':'+'}${Number(t.amount).toFixed(2)} USDT</strong></article>`).join('');
}
function formatDuration(seconds){seconds=Math.max(0,seconds|0);return `${Math.floor(seconds/3600)}h ${Math.floor((seconds%3600)/60)}m ${seconds%60}s`;}
function renderDailyTasks(data){
  const list=$('#dailyTasksList'); if(!list)return;
  $('#taskPlanBadge').textContent=data.plan==='VIP'?'PLAN VIP':'PLAN NORMAL';
  $('#taskPlanDescription').textContent=data.plan==='VIP'?'VIP: 4 tareas diarias de 5 USDT cada una (máximo previsto 20 USDT).':'Normal: 2 tareas diarias de 1 USDT cada una (máximo previsto 2 USDT).';
  list.innerHTML=(data.tasks||[]).map(t=>`<article class="history-item"><span class="history-icon">${t.completed?'✅':'⛏️'}</span><div><b>${escapeHtml(t.title)}</b><small>${t.completed?'Completada hoy':'Tarea diaria · '+escapeHtml(data.date)}</small></div><strong>${Number(t.reward).toFixed(2)} USDT</strong><button class="button ${t.completed?'button-ghost':'button-green'} task-claim" data-slot="${t.slot}" ${t.completed?'disabled':''}>${t.completed?'Completada':'Completar'}</button></article>`).join('');
  $$('.task-claim').forEach(btn=>btn.addEventListener('click',async()=>{btn.disabled=true;try{const result=await request('/api/tasks/claim/',{slot:Number(btn.dataset.slot)});notify(result.message+' +'+Number(result.reward).toFixed(2)+' USDT');await loadAccount();}catch(e){notify(e.message);btn.disabled=false;}}));
}
function renderReferral(data){
  const code=data.wallet?.referral_code||account?.referral_code; if(!code)return;
  const url=new URL(window.location.origin+'/');url.searchParams.set('ref',code);
  $('#referralLink').value=url.toString();
  $('#referralStats').textContent=`Referidos acreditados: ${data.wallet.referral_count||0} · Recompensas: ${Number(data.wallet.referral_rewards||0).toFixed(2)} USDT`;
}

function renderAccount(data){
  accountState=data;const w=data.wallet; renderDailyTasks(data.daily_tasks||{plan:w.vip_active?"VIP":"Normal",date:"",tasks:[]}); renderReferral(data);
  $('#balance').textContent=`${Number(w.balance).toFixed(2)} USDT`;
  $('#withdrawBalance').textContent=`${Number(w.balance).toFixed(2)} USDT`;
  $('#membershipStatus').textContent=w.vip_active?'VIP ⭐':'Básica';
  $('#investedLabel').textContent=`Inversión verificada: ${Number(w.total_invested).toFixed(2)} USDT`;
  $('#vipBadge').textContent=w.vip_active?'VIP ACTIVADO':'NO ACTIVADO';
  $('#withdrawRule').textContent=`Mínimo 2 USDT. Límite por retiro: ${Number(w.withdrawal_limit).toFixed(2)} USDT. Requiere inversión inicial verificada de 10 USDT y espera de 24 horas entre solicitudes.`;
  $('#withdrawSubmit').disabled=!w.initial_investment_met || w.withdrawal_wait_seconds>0;
  $('#withdrawStatus').textContent=!w.initial_investment_met?'INVERSIÓN REQUERIDA':w.withdrawal_wait_seconds>0?'EN ESPERA':'DISPONIBLE';
  $('#withdrawCountdown').textContent=w.withdrawal_wait_seconds>0?`Disponible en ${formatDuration(w.withdrawal_wait_seconds)}.`:'';
  $('#withdrawAmount').max=w.withdrawal_limit;
  $('#walletAddress').value=DEPOSIT_ADDRESS;
  renderHistory(data.transactions);
  const pendingDeposit=(data.transactions||[]).find(t=>t.kind==='deposit'&&t.status==='pending');
  if(pendingDeposit){ $('#depositCountdown').textContent=`Depósito pendiente de revisión. Tiempo estimado restante: ${formatDuration(pendingDeposit.review_wait_seconds||0)}.`; } else { $('#depositCountdown').textContent=''; }
  const pendingWithdrawal=(data.transactions||[]).find(t=>t.kind==='withdrawal'&&t.status==='pending');
  $('#withdrawReviewCountdown').textContent=pendingWithdrawal?`Revisión manual del retiro: ${formatDuration(pendingWithdrawal.review_wait_seconds||0)} restantes. El administrador podrá procesarlo al terminar el plazo.`:'';
}
async function loadAccount(){const data=await request('/api/account/',null,'GET');renderAccount(data);}
async function checkSession(){try{const data=await request('/api/me/',null,'GET');if(data.authenticated){logged=true;account=data.user;showLoggedIn();await loadAccount();showDashboard('tasksView');}}catch(_){}}

$('#headerLogin').addEventListener('click',()=>showAuth('login'));
$('#headerRegister').addEventListener('click',()=>showAuth('register'));
$('#headerProfile').addEventListener('click',()=>showDashboard('historyView'));
$('#heroRegister').addEventListener('click',()=>showAuth('register'));
$('#heroTasks').addEventListener('click',()=>showDashboard('tasksView'));
$('#loginTab').addEventListener('click',()=>setMode('login'));
$('#registerTab').addEventListener('click',()=>setMode('register'));
$('#togglePassword').addEventListener('click',()=>{const visible=passwordInput.type==='password';passwordInput.type=visible?'text':'password';$('#togglePassword').textContent=visible?'Ocultar':'Ver';});

authForm.addEventListener('submit',async event=>{
  event.preventDefault();if(!authForm.reportValidity())return;
  const button=$('#submitAuth');button.disabled=true;button.textContent=mode==='register'?'Creando cuenta…':'Verificando…';$('#message').textContent='';
  try{
    let result;
    if(mode==='register'){
      if(!termsInput.checked){$('#message').textContent='Confirma que comprendes el proceso de verificación de depósitos.';return;}
      result=await request('/api/register/',{username:usernameInput.value.trim(),email:emailInput.value.trim(),password:passwordInput.value});
    }else result=await request('/api/login/',{email:emailInput.value.trim(),password:passwordInput.value});
    logged=true;account=result.user;showLoggedIn();await loadAccount();notify(mode==='register'?'Cuenta creada correctamente.':'Sesión iniciada.');showDashboard('tasksView');
  }catch(error){const errors=error.data?.errors;$('#message').textContent=errors?Object.values(errors).flat().join(' '):error.message;notify(error.message);}
  finally{button.disabled=false;button.innerHTML=mode==='register'?'Crear cuenta <span>↗</span>':'Iniciar sesión <span>↗</span>';}
});

$$('.dash-tab').forEach(tab=>tab.addEventListener('click',()=>setView(tab.dataset.view)));
$('#vipInvestButton').addEventListener('click',()=>{ $('#depositAmount').value='60.00';$('#depositAmountLabel').textContent='60.00 USDT';$('#depositPlanHint').textContent='Solicitud de inversión para alcanzar el nivel VIP; requiere verificación manual.';setView('depositView');$('#depositAmountLabel').scrollIntoView({behavior:'smooth',block:'center'}); });
$('#basicPlanButton').addEventListener('click',()=>{setView('depositView');$('#depositAmount').value='10.00';$('#depositAmountLabel').textContent='10.00 USDT';$('#depositPlanHint').textContent='Inversión inicial mínima: 10 USDT.';});
$('#depositForm').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.submitter||event.target.querySelector('button[type="submit"]');button.disabled=true;$('#depositMessage').textContent='Registrando solicitud…';
  try{const result=await request('/api/deposit/',{amount:$('#depositAmount').value});$('#depositMessage').textContent=result.message;$('#depositCountdown').textContent=`El administrador revisará la solicitud. Tiempo estimado: ${formatDuration(result.transaction?.review_wait_seconds||7200)}.`;await loadAccount();notify('Solicitud de depósito registrada.');}
  catch(e){$('#depositMessage').textContent=e.message;notify(e.message);}finally{button.disabled=false;}
});
$('#copyAddress').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(DEPOSIT_ADDRESS);notify('Dirección copiada. Verifica la red BEP20 antes de enviar.');}catch(_){$('#walletAddress').select();notify('Selecciona y copia la dirección manualmente.');}});
$('#withdrawForm').addEventListener('submit',async event=>{
  event.preventDefault();const button=$('#withdrawSubmit');button.disabled=true;$('#withdrawMessage').textContent='Enviando solicitud…';
  try{const result=await request('/api/withdraw/',{amount:$('#withdrawAmount').value,destination:$('#withdrawDestination').value.trim()});$('#withdrawMessage').textContent=result.message;$('#withdrawDestination').value='';await loadAccount();notify('Solicitud de retiro registrada.');}
  catch(e){$('#withdrawMessage').textContent=e.message;notify(e.message);await loadAccount().catch(()=>{});}finally{button.disabled=!(accountState?.wallet?.initial_investment_met)&&true;}
});

$$('.game-start').forEach(button=>button.addEventListener('click',async()=>{
  if(!logged){showAuth('login');return;}const type=button.dataset.game;button.disabled=true;
  try{
    const game=await request('/api/game/start/',{game_type:type});activeGames.set(type,game);
    const box=$(`#gameBox-${type}`);box.classList.remove('hidden');$(`#question-${type}`).textContent=game.question;
    const bar=$(`#bar-${type}`);bar.style.width='0%';const status=$(`#status-${type}`);const form=$(`.game-answer[data-game="${type}"]`);const input=$(`#answer-${type}`);const submit=form.querySelector('button');input.value='';submit.disabled=true;
    let elapsed=0;const interval=setInterval(()=>{elapsed++;bar.style.width=`${Math.min(100,elapsed/game.wait_seconds*100)}%`;status.textContent=elapsed>=game.wait_seconds?'Tiempo completado. Responde para reclamar.':`Espera ${game.wait_seconds-elapsed} s…`;if(elapsed>=game.wait_seconds){clearInterval(interval);submit.disabled=false;input.focus();}},1000);
    activeGames.set(type,{...game,interval});
  }catch(e){notify(e.message);button.disabled=false;}
}));
$$('.game-answer').forEach(form=>form.addEventListener('submit',async event=>{
  event.preventDefault();const type=form.dataset.game;const game=activeGames.get(type);if(!game)return;const submit=form.querySelector('button');submit.disabled=true;
  try{const result=await request('/api/game/claim/',{game_id:game.game_id,answer:$(`#answer-${type}`).value});$(`#status-${type}`).textContent=`${result.message} +${Number(result.reward).toFixed(2)} USDT`;$(`#bar-${type}`).style.width='100%';$(`.game-start[data-game="${type}"]`).textContent='Reto completado ✓';activeGames.delete(type);await loadAccount();notify(`Recompensa acreditada: ${Number(result.reward).toFixed(2)} USDT`);}
  catch(e){$(`#status-${type}`).textContent=e.message;submit.disabled=false;notify(e.message);}
}));

$('#logout').addEventListener('click',async()=>{try{await request('/api/logout/',{});}catch(_){}logged=false;account=null;accountState=null;showLoggedOut();authForm.reset();dashboard.classList.add('hidden');showAuth('login');$('#hero').classList.remove('hidden');$('#features').classList.remove('hidden');notify('Sesión cerrada.');});
$('#navTasks').addEventListener('click',event=>{event.preventDefault();showDashboard('tasksView');});
$('#navHome').addEventListener('click',event=>{event.preventDefault();auth.classList.add('hidden');dashboard.classList.add('hidden');$('#hero').classList.remove('hidden');$('#features').classList.remove('hidden');$('#inicio').scrollIntoView({behavior:'smooth'});});
$('#navLearn').addEventListener('click',event=>{event.preventDefault();$('#seguridad').scrollIntoView({behavior:'smooth'});});
$('.brand').addEventListener('click',event=>{event.preventDefault();$('#navHome').click();});
$('#menuToggle').addEventListener('click',()=>logged?showDashboard('tasksView'):showAuth('login'));
let accountRefreshTicks=0;
setInterval(()=>{if(accountState?.wallet?.withdrawal_wait_seconds>0){accountState.wallet.withdrawal_wait_seconds--;$('#withdrawCountdown').textContent=`Disponible en ${formatDuration(accountState.wallet.withdrawal_wait_seconds)}.`;if(accountState.wallet.withdrawal_wait_seconds===0){$('#withdrawSubmit').disabled=!accountState.wallet.initial_investment_met;$('#withdrawStatus').textContent='DISPONIBLE';}}
  for(const [selector,prefix] of [['#depositCountdown','Depósito pendiente de revisión. Tiempo estimado restante: '],['#withdrawReviewCountdown','Revisión manual del retiro: ']]){const el=$(selector);if(!el||!el.textContent)continue;const match=el.textContent.match(/(\d+)h (\d+)m (\d+)s/);if(match){let sec=Math.max(0,Number(match[1])*3600+Number(match[2])*60+Number(match[3])-1);el.textContent=selector==='#depositCountdown'?`${prefix}${formatDuration(sec)}.`:`${prefix}${formatDuration(sec)} restantes. El administrador podrá procesarlo al terminar el plazo.`;}}
  accountRefreshTicks++;if(logged&&accountRefreshTicks%60===0){loadAccount().catch(()=>{});}
},1000);
$('#copyReferral')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('#referralLink').value);notify('Enlace de referido copiado.');}catch(_){$('#referralLink').select();notify('Copia el enlace seleccionado.');}});
$('#shareWhatsApp')?.addEventListener('click',()=>{const text=encodeURIComponent('¡Únete a bear.litle! Si creas una cuenta nueva con mi enlace, puedo recibir una recompensa de referido de 1 USDT cuando el registro sea válido: '+$('#referralLink').value);window.open('https://wa.me/?text='+text,'_blank','noopener');});
$('#shareTelegram')?.addEventListener('click',()=>{const url=encodeURIComponent($('#referralLink').value);const text=encodeURIComponent('¡Únete a bear.litle! Recompensa de referido de 1 USDT para quien invita, tras un registro válido.');window.open('https://t.me/share/url?url='+url+'&text='+text,'_blank','noopener');});
checkSession();
