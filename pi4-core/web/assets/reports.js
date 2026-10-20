const BANDS={GREEN:"#34d27b",BLUE:"#4c8dff",YELLOW:"#f2c230",RED:"#ff4a3d",PURPLE:"#b45cff"};
const $=(s)=>document.querySelector(s);
const esc=(s)=>String(s==null?"":s).replace(/[&<>"]/g,(c)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const hms=(ts)=>new Date(ts*1000).toLocaleTimeString("en-GB",{hour12:false});
const dmy=(ts)=>new Date(ts*1000).toLocaleString("en-GB",{hour12:false,day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"});

async function load(hours){
  let r;
  try{ r=await fetch("/api/report?hours="+hours,{cache:"no-store"}); }catch{ document.body.innerHTML="<p style='padding:30px'>Cannot reach the server.</p>";return; }
  if(r.status===401){ location.href="/"; return; }
  const d=await r.json();
  $("#h1").textContent = hours==5 ? "These are the events that happened in the last 5 hours"
    : "Events in the last "+(hours==1?"hour":hours+" hours");
  // tiles
  const tiles=[["Events",d.events.length],["Incidents",d.incidents.length],
    ["Peak score",Math.round(d.peak)],["Critical",d.sev_counts.critical||0],
    ["Scans",(d.counts.portscan||0)+(d.counts.arpsweep||0)+(d.counts.pingsweep||0)],
    ["E-mails",(d.counts.mail||0)]];
  $("#tiles").innerHTML=tiles.map(([k,v])=>`<div class="tile"><b>${v}</b><span>${k}</span></div>`).join("");
  drawBand(d.series);
  bandBar(d.band_time);
  // incidents
  const ib=$("#incidents");
  if(!d.incidents.length) ib.innerHTML='<div class="empty">No incidents in this window — nothing crossed RED.</div>';
  else ib.innerHTML=d.incidents.map((i)=>`<div class="inc ${i.state}"><h3>${esc(i.title||"Incident")}</h3>
    <div class="meta">${dmy(i.opened)} · ${esc(i.state)} · peak ${Math.round(i.peak||0)}/100${i.device?" · "+esc(i.device):""}</div>
    ${(i.timeline&&i.timeline.length)?"<ol>"+i.timeline.map((t)=>`<li>${hms(t.ts)} — ${esc(t.what)}</li>`).join("")+"</ol>":""}</div>`).join("");
  // rows
  const rows=d.events.slice().sort((a,b)=>b.ts-a.ts);
  $("#rows").innerHTML = rows.length ? rows.map((e)=>`<tr><td class="t">${hms(e.ts)}</td>
    <td><span class="sev s-${e.sev}"></span>${esc(e.sev)}</td><td>${esc(e.title)}</td>
    <td class="t">${esc(e.node||e.kind)}${e.src?" · "+esc(e.src):""}</td></tr>`).join("")
    : '<tr><td colspan="4" class="empty">No events logged in this window.</td></tr>';
}

function drawBand(series){
  const cv=$("#band"),g=cv.getContext("2d"),w=cv.width,h=cv.height;
  g.clearRect(0,0,w,h);
  if(series.length<2){g.fillStyle="#6f6354";g.font="14px sans-serif";g.fillText("Not enough samples yet.",16,h/2);return;}
  const t0=series[0][0],t1=series[series.length-1][0],sp=Math.max(t1-t0,1);
  const X=(t)=>(t-t0)/sp*w,Y=(v)=>h-v/100*(h-10)-5;
  [30,70].forEach((v)=>{g.strokeStyle="#ffffff18";g.setLineDash([3,4]);g.beginPath();g.moveTo(0,Y(v));g.lineTo(w,Y(v));g.stroke();});
  g.setLineDash([]);g.lineWidth=1.8;
  for(let i=1;i<series.length;i++){g.strokeStyle=BANDS[series[i][2]]||"#34d27b";g.beginPath();
    g.moveTo(X(series[i-1][0]),Y(series[i-1][1]));g.lineTo(X(series[i][0]),Y(series[i][1]));g.stroke();}
}
function bandBar(bt){
  const total=Object.values(bt).reduce((a,b)=>a+b,0)||1;
  const order=["GREEN","BLUE","YELLOW","RED","PURPLE"];
  $("#bandbar").innerHTML=order.filter((b)=>bt[b]).map((b)=>{
    const pct=(bt[b]/total*100);
    return `<b style="flex:${bt[b]};background:${BANDS[b]}" title="${b} ${Math.round(pct)}%">${pct>8?b:""}</b>`;
  }).join("")||'<b style="flex:1;background:#34d27b">GREEN</b>';
}
$("#range").addEventListener("change",(e)=>load(e.target.value));
load(5); setInterval(()=>load($("#range").value),30000);
