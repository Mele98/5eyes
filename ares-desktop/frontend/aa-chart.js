// H6 Asset-Allocation-Grafik (SOLL-Torte, Legende, SOLL-Quoten mit Bandbreite).
// Teil des Monolithen (ausgelagert, siehe tests/monolith_source.py): klassisches
// Skript, globale Funktionen, keine Abhaengigkeit ausser Chart.js (vendor).
// Fachlich neutral: Gewichte (bps), Betraege und Bandbreiten kommen unveraendert
// aus der Engine; hier wird nur sortiert, gerundet (Rest-Rundung auf 100 %) und
// gezeichnet.

// Feste Reihenfolge der Anlageklassen -- nur Gleichstands-Regel beim Sortieren.
function aaChartClassRank(key){
  var i=['eq','bd','re','alt','liq','oth'].indexOf(String(key||''));
  return i<0?99:i;
}
function aaChartKey(label){
  return typeof assetClassKey==='function'?assetClassKey(label):'oth';
}
// Rest-Rundung (Hare/Niemeyer): ganze bps -> Zehntelprozent, deren Summe genau
// round(Summe/10) ergibt (bei 10'000 bps also exakt 100.0 %). Optional ein
// vorgegebenes Ziel in Zehnteln (Unterklassen ergeben so genau ihre Klasse).
function aaChartRoundTenths(weights,targetTenths){
  var w=(weights||[]).map(function(v){var n=Number(v);return isFinite(n)&&n>0?n:0;});
  var total=w.reduce(function(a,b){return a+b;},0);
  if(!(total>0))return w.map(function(){return 0;});
  var target=targetTenths!=null?Math.max(0,Math.round(Number(targetTenths)||0)):Math.round(total/10);
  var raw=w.map(function(v){return v*target/total;});
  var out=raw.map(function(v){return Math.floor(v+1e-9);});
  var rest=target-out.reduce(function(a,b){return a+b;},0);
  var order=raw.map(function(v,i){return i;}).sort(function(a,b){
    return ((raw[b]-out[b])-(raw[a]-out[a]))||(w[b]-w[a])||(a-b);
  });
  for(var k=0;k<order.length&&rest>0;k++){if(w[order[k]]>0){out[order[k]]++;rest--;}}
  return out;
}
function aaChartPctText(tenths){
  var n=Math.round(Number(tenths)||0);
  return (n<0?'−':'')+Math.floor(Math.abs(n)/10)+'.'+(Math.abs(n)%10)+' %';
}
function aaChartChf(chf){
  var n=Math.round(Number(chf)||0);
  return 'CHF '+(typeof fmtLocaleCH==='function'?fmtLocaleCH(n):String(n));
}
// items: [{name,bps,color,amountChf?,band?:{min,max},subs?:[{name,bps,note}]}]
// -> neue, nach Gewicht absteigend sortierte Zeilen mit tenths/pct; Unterklassen
// ebenfalls sortiert und so gerundet, dass sie genau ihre Klasse ergeben.
function aaChartPrepare(items){
  var rows=(items||[]).map(function(it,idx){
    var key=it.key||aaChartKey(it.name);
    return {name:String(it.name||''),key:key,bps:Math.max(0,Math.round(Number(it.bps)||0)),color:it.color,
      cssColor:it.cssColor||(typeof assetClassCssVar==='function'?assetClassCssVar(it.name):it.color),amountChf:it.amountChf,band:it.band||null,groupKey:it.groupKey||null,
      expanded:!!it.expanded,_i:idx,subs:(it.subs||[]).map(function(s,j){
        return {name:String(s.name||''),bps:Math.max(0,Math.round(Number(s.bps)||0)),note:s.note||'',_j:j};
      })};
  }).filter(function(r){return r.bps>0;});
  rows.sort(function(a,b){return (b.bps-a.bps)||(aaChartClassRank(a.key)-aaChartClassRank(b.key))||(a._i-b._i);});
  var tenths=aaChartRoundTenths(rows.map(function(r){return r.bps;}));
  rows.forEach(function(r,i){
    r.tenths=tenths[i];r.pct=aaChartPctText(r.tenths);
    r.subs=r.subs.filter(function(s){return s.bps>0;});
    r.subs.sort(function(a,b){return (b.bps-a.bps)||(a._j-b._j);});
    var subTotal=r.subs.reduce(function(a,s){return a+s.bps;},0);
    var st=aaChartRoundTenths(r.subs.map(function(s){return s.bps;}),subTotal===r.bps?r.tenths:null);
    r.subs.forEach(function(s,j){s.tenths=st[j];s.pct=aaChartPctText(st[j]);s.shade=aaChartShadeStep(j,r.subs.length);});
  });
  return rows;
}
// Unterklassen: groesste in der Klassenfarbe, weitere schrittweise heller
// (Anteil der Flaechenfarbe 0..0.5) -- gleiche Stufe in Canvas und HTML.
function aaChartShadeStep(idx,count){
  return count>1?Math.round(idx/(count-1)*50)/100:0;
}
function aaChartMix(hex,toHex,t){
  var p=function(h){h=String(h||'').replace('#','');return h.length===6?[0,2,4].map(function(i){return parseInt(h.slice(i,i+2),16);}):null;};
  var a=p(hex),b=p(toHex);
  if(!a||!b)return hex;
  return '#'+a.map(function(v,i){var m=Math.round(v+(b[i]-v)*t);return (m<16?'0':'')+m.toString(16);}).join('').toUpperCase();
}
function aaChartCssMix(cssColor,t){
  if(!(t>0))return cssColor;
  return 'color-mix(in srgb, '+cssColor+' '+Math.round((1-t)*100)+'%, var(--surface))';
}
function aaChartSurface(){
  try{var v=getComputedStyle(document.documentElement).getPropertyValue('--surface').trim();if(/^#[0-9a-f]{6}$/i.test(v))return v;}catch(e){}
  return '#FFFFFF';
}
function aaChartReducedMotion(){
  try{return !!(window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches);}catch(e){return false;}
}
// Datensaetze: innen die Anlageklassen (Hauptring), aussen ein schmaler Ring der
// Unterklassen, deckungsgleich zur jeweiligen Klasse. Ohne Strategie ein ruhiger
// neutraler Ring ohne Fuge.
function aaChartDonutDatasets(rows,surface){
  if(!rows||!rows.length){
    return [{data:[100],backgroundColor:['rgba(122,130,153,0.22)'],borderWidth:0,hoverOffset:0,_aaPending:true}];
  }
  var cls={data:[],backgroundColor:[],_aaLabels:[],_aaPct:[],_aaAmt:[],borderColor:surface,borderWidth:2,hoverOffset:5,weight:1,_aaRing:'class'};
  var sub={data:[],backgroundColor:[],_aaLabels:[],_aaPct:[],_aaAmt:[],_aaRow:[],borderColor:surface,borderWidth:1.5,hoverOffset:3,weight:0.3,_aaRing:'sub'};
  var hasSubs=false;
  rows.forEach(function(r,i){
    cls.data.push(r.bps);cls.backgroundColor.push(r.color);cls._aaLabels.push(r.name);cls._aaPct.push(r.pct);
    cls._aaAmt.push(r.amountChf>0?aaChartChf(r.amountChf):'');
    var subs=r.subs.length?r.subs:[{name:r.name,bps:r.bps,pct:r.pct,shade:0}];
    var used=0;
    subs.forEach(function(s){
      if(r.subs.length)hasSubs=true;
      used+=s.bps;
      sub.data.push(s.bps);sub.backgroundColor.push(aaChartMix(r.color,surface,s.shade));
      sub._aaLabels.push(r.subs.length?(r.name+' · '+s.name):r.name);sub._aaPct.push(s.pct);sub._aaAmt.push('');sub._aaRow.push(i);
    });
    if(used<r.bps){
      // Unterklassen decken die Klasse nicht ganz ab: Rest neutral, keine Zuordnung erfinden.
      sub.data.push(r.bps-used);sub.backgroundColor.push(aaChartMix(r.color,surface,0.8));
      sub._aaLabels.push(r.name+' · ohne Unterklasse');sub._aaPct.push('');sub._aaAmt.push('');sub._aaRow.push(i);
    }
  });
  return hasSubs?[sub,cls]:[cls];
}
function aaChartDonutConfig(){
  return {type:'doughnut',
    data:{labels:['Strategie ausstehend'],datasets:aaChartDonutDatasets([],'#FFFFFF')},
    options:{responsive:true,maintainAspectRatio:false,cutout:'64%',
      animation:aaChartReducedMotion()?false:{duration:450,easing:'easeOutCubic'},
      layout:{padding:6},
      plugins:{legend:{display:false},
        tooltip:{
          filter:function(item){return !(item.dataset&&item.dataset._aaPending);},
          backgroundColor:'rgba(15,30,52,0.92)',padding:8,cornerRadius:6,boxWidth:8,boxHeight:8,boxPadding:4,
          titleFont:{size:11,weight:'600'},bodyFont:{size:11},displayColors:true,
          callbacks:{
            title:function(){return '';},
            label:function(ctx){
              var ds=ctx.dataset||{},i=ctx.dataIndex;
              var parts=[(ds._aaLabels&&ds._aaLabels[i])||String(ctx.label||'')];
              if(ds._aaPct&&ds._aaPct[i])parts.push(ds._aaPct[i]);
              if(ds._aaAmt&&ds._aaAmt[i])parts.push(ds._aaAmt[i]);
              return parts.join(' · ');
            }}}},
      onHover:function(evt,active){aaChartMarkLegend(active&&active.length?aaChartRowOfActive(this,active[0]):-1);}
    }};
}
function aaChartRowOfActive(chart,el){
  var ds=chart&&chart.data&&chart.data.datasets?chart.data.datasets[el.datasetIndex]:null;
  if(!ds)return -1;
  return ds._aaRing==='sub'?ds._aaRow[el.index]:(ds._aaRing==='class'?el.index:-1);
}
function aaChartMarkLegend(rowIdx){
  try{
    document.querySelectorAll('#dnleg [data-aa-row]').forEach(function(n){
      n.classList.toggle('is-active',String(n.getAttribute('data-aa-row'))===String(rowIdx));
    });
  }catch(e){}
}
// Legende -> Torte: Segment hervorheben (Maus und Tastaturfokus).
function aaChartBindLegend(chart){
  var host=document.getElementById('dnleg');
  if(!host||!chart||host.dataset.aaBound==='1')return;
  host.dataset.aaBound='1';
  var on=function(evt){
    var row=evt.target&&evt.target.closest?evt.target.closest('[data-aa-row]'):null;
    var ds=chart.data&&chart.data.datasets||[];
    var ci=-1;ds.forEach(function(d,k){if(d._aaRing==='class')ci=k;});
    try{
      if(!row||ci<0){chart.setActiveElements([]);if(chart.tooltip)chart.tooltip.setActiveElements([],{x:0,y:0});aaChartMarkLegend(-1);}
      else{var idx=Number(row.getAttribute('data-aa-row'));var a=[{datasetIndex:ci,index:idx}];chart.setActiveElements(a);
        if(chart.tooltip)chart.tooltip.setActiveElements(a,{x:chart.width/2,y:chart.height/2});aaChartMarkLegend(idx);}
      chart.update('none');
    }catch(e){}
  };
  host.addEventListener('mouseover',on);host.addEventListener('focusin',on);
  host.addEventListener('mouseleave',function(){on({target:null});});
  host.addEventListener('focusout',function(){on({target:null});});
}
// Torte aus dem Allokationsstand (alloc + Unterklassen) neu befuellen.
function aaChartApplyDonut(chart,hasStrategy){
  if(!chart||!chart.data)return;
  var surface=aaChartSurface();
  var rows=hasStrategy?aaChartPrepare(aaChartAllocItems()):[];
  chart.data.labels=rows.length?rows.map(function(r){return r.name;}):['Strategie ausstehend'];
  chart.data.datasets=aaChartDonutDatasets(rows,surface);
  aaChartBindLegend(chart);
}
// Gemeinsame Eingabe fuer Torte und SOLL-Quoten aus den Monolith-Globals.
function aaChartAllocItems(){
  var list=typeof alloc!=='undefined'&&Array.isArray(alloc)?alloc:[];
  var buckets=(typeof strategyState!=='undefined'&&strategyState&&strategyState.allocation&&strategyState.allocation.buckets)||[];
  var base=typeof allocationReserveBreakdown==='function'&&typeof strategyState!=='undefined'&&strategyState&&strategyState.allocation?allocationReserveBreakdown(strategyState.allocation).strategyBaseRappen:0;
  return list.map(function(r){
    // Betrag wie in der Legende: Engine-Zielbetrag, sonst Quote x Strategiebasis.
    var amount=Number(r.chfTarget||0);
    if(!(amount>0))amount=Math.round((base/100)*Number(r.soll||0)/100);
    var band=null;
    buckets.forEach(function(b){
      var n=typeof assetDisplayName==='function'?assetDisplayName(String(b.asset_class||'')):String(b.asset_class||'');
      if(n===r.n&&(Number(b.band_max_bps)>0))band={min:Number(b.band_min_bps||0),max:Number(b.band_max_bps||0)};
    });
    var subs=typeof allocationSubAllocationsForBucket==='function'?allocationSubAllocationsForBucket(r.n):[];
    var gk=typeof allocationTableGroupKey==='function'?allocationTableGroupKey(r.n):String(r.n||'');
    return {name:r.n,bps:Math.round(Number(r.soll||0)*100),color:r.c,amountChf:amount,
      band:band,groupKey:gk,
      expanded:typeof allocationSuballocExpanded!=='undefined'&&!!allocationSuballocExpanded[gk],
      subs:(subs||[]).map(function(s){return {name:s.sub_asset_class||'Baustein',bps:s.target_weight_bps,note:s.rationale||''};})};
  });
}
function aaChartHasSubs(){
  var a=typeof strategyState!=='undefined'&&strategyState&&strategyState.allocation;
  return !!(a&&Array.isArray(a.sub_allocations)&&a.sub_allocations.some(function(x){return Number(x&&x.target_weight_bps)>0;}));
}
function aaChartEsc(v){
  var t=String(v==null?'':v);
  if(typeof escapeHtml==='function')return escapeHtml(t);
  return t.split('').map(function(c){return '&<>\x22\x27'.indexOf(c)>=0?('&#'+c.charCodeAt(0)+';'):c;}).join('');
}
// Legende: sortiert, Farbe + Name + Anteilsbalken + % + CHF; Reserve separat.
function aaChartLegendHtml(items,rb){
  var rows=aaChartPrepare(items);
  var html='<div class="aa-leg-head" aria-hidden="true"><span>Anlageklasse</span><span>Anteil</span><span>Betrag</span></div>'+rows.map(function(r,i){
    return '<div class="aa-leg-row" data-aa-row="'+i+'" tabindex="0" style="--aa-c:'+aaChartEsc(r.cssColor||r.color)+'">'
      +'<span class="aa-leg-sw" aria-hidden="true"></span><span class="aa-leg-name">'+aaChartEsc(r.name)+'</span>'
      +'<span class="aa-leg-bar" aria-hidden="true"><i style="width:'+(r.tenths/10)+'%"></i></span>'
      +'<span class="aa-leg-pct">'+aaChartEsc(r.pct)+'</span>'
      +'<span class="aa-leg-amt">'+(r.amountChf>0?aaChartEsc(aaChartChf(r.amountChf)):'')+'</span></div>';
  }).join('');
  if(aaChartHasSubs())html+='<div class="aa-leg-ring">Innenring: Anlageklassen · Aussenring: Subanlageklassen (Details unter «SOLL-Quoten»)</div>';
  if(rb&&rb.reserveRappen>0){
    var fr=typeof formatRappen==='function'?formatRappen:function(x){return aaChartChf(Number(x||0)/100);};
    html+='<div class="aa-leg-row aa-leg-reserve" id="alloc-legend-reserve"><span class="aa-leg-sw" aria-hidden="true"></span>'
      +'<span class="aa-leg-name">Liquiditätsreserve (ausserhalb der Anlagestrategie)</span><span class="aa-leg-bar" aria-hidden="true"></span>'
      +'<span class="aa-leg-pct">–</span><span class="aa-leg-amt">'+aaChartEsc(aaChartChf(rb.reserveRappen/100))+'</span></div>'
      +'<div class="aa-leg-note">Quoten in % der Strategiebasis '+aaChartEsc(fr(rb.strategyBaseRappen))
      +'; zusammen mit der Reserve ergibt sich das Beratungsvermögen '+aaChartEsc(fr(rb.advisoryRappen))+'.</div>';
  }
  return html;
}
// Bandbreite als horizontaler Balken: Skala 0-100 %, Band min-max, Ziel-Marker.
function aaChartBandHtml(band,bps,label){
  if(!band||!(band.max>0))return '';
  var mn=Math.max(0,Math.min(10000,band.min)),mx=Math.max(mn,Math.min(10000,band.max)),t=Math.max(0,Math.min(10000,bps));
  var tx=function(v){return aaChartPctText(Math.round(v/10));};
  var txt='Bandbreite '+(mn===mx?tx(mn):(tx(mn).replace(' %','')+'–'+tx(mx)));
  return '<span class="aa-band" role="img" aria-label="'+aaChartEsc(label+': '+txt+', Ziel '+tx(t))+'">'
    +'<span class="aa-band-track"><span class="aa-band-range" style="left:'+(mn/100)+'%;width:'+((mx-mn)/100)+'%"></span>'
    +'<span class="aa-band-mark" style="left:'+(t/100)+'%"></span></span><span class="aa-band-txt">'+aaChartEsc(txt)+'</span></span>';
}
// SOLL-Quoten-Liste: gleiche Sortierung/Rundung wie die Torte, Unterklassen
// aufklappbar (Zustand allocationSuballocExpanded, Klick wie bisher).
function aaChartQuotaHtml(items){
  return aaChartPrepare(items).map(function(r){
    var n=r.subs.length,gk=String(r.groupKey||r.name);
    var head='<button type="button" class="aa-q-row"'+(n?(' data-allocation-group="'+aaChartEsc(encodeURIComponent(gk))+'" aria-expanded="'+(r.expanded?'true':'false')
      +'" onclick="event.stopPropagation();toggleAllocationTableGroup(decodeURIComponent(this.getAttribute(\'data-allocation-group\')));"'):' aria-disabled="true"')
      +' style="--aa-c:'+aaChartEsc(r.cssColor||r.color)+'"><span class="aa-q-sw" aria-hidden="true"></span>'
      +'<span class="aa-q-main"><span class="aa-q-name">'+aaChartEsc(r.name)+'</span>'
      +(n?'<span class="aa-q-meta">'+n+(n===1?' Subanlageklasse':' Subanlageklassen')+'</span>':'')+'</span>'
      +aaChartBandHtml(r.band,r.bps,r.name)
      +'<span class="aa-q-pct">'+aaChartEsc(r.pct)+'</span><span class="aa-q-chev" aria-hidden="true"></span></button>';
    var subs=(n&&r.expanded)?'<div class="aa-q-subs">'+r.subs.map(function(s){
      return '<div class="aa-q-sub"><span class="aa-q-sw" aria-hidden="true" style="background:'+aaChartEsc(aaChartCssMix(r.cssColor||r.color,s.shade))+'"></span>'
        +'<span class="aa-q-main"><span class="aa-q-name">'+aaChartEsc(s.name)+'</span>'+(s.note?'<span class="aa-q-meta">'+aaChartEsc(s.note)+'</span>':'')+'</span>'
        +'<span class="aa-q-pct">'+aaChartEsc(s.pct)+'</span></div>';
    }).join('')+'</div>':'';
    return '<div class="aa-q'+(r.expanded?' is-open':'')+'">'+head+subs+'</div>';
  }).join('');
}
