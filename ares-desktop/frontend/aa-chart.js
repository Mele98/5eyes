// H6 Asset-Allocation-Grafik (SOLL-Torte, Legende, SOLL-Quoten mit Bandbreite).
// Teil des Monolithen (ausgelagert, siehe tests/monolith_source.py): klassisches
// Skript, globale Funktionen, keine Abhaengigkeit ausser Chart.js (vendor).
// Fachlich neutral: Gewichte (bps), Betraege und Bandbreiten kommen unveraendert
// aus der Engine; hier wird nur sortiert, gerundet und gezeichnet.
//
// Rundung: G7 (presentation-rounding.js), Anteile apportioniert wie im PDF.

// Feste Reihenfolge der Anlageklassen -- nur Gleichstands-Regel beim Sortieren.
function aaChartClassRank(key){
  var i=['eq','bd','re','alt','liq','oth'].indexOf(String(key||''));
  return i<0?99:i;
}
function aaChartKey(label){
  return typeof assetClassKey==='function'?assetClassKey(label):'oth';
}
// Einzelwert (Bandbreiten, Ziel-Marker): bps -> "12.3 %" (Half-up, wie fmtPct).
function aaChartPctText(bps){
  return AresRounding.formatPercentBps(Math.round(Number(bps)||0),1,{typography:'screen'});
}
// G7: Betraege in Mandatswaehrung (Exponent explizit).
function aaChartCurrency(){var a=typeof strategyState!=='undefined'&&strategyState&&strategyState.allocation,m=typeof currentMandateData!=='undefined'&&currentMandateData;return String((a&&a.base_currency)||(m&&m.base_currency)||'CHF').toUpperCase();}
function aaChartMoney(minor,cur){return AresRounding.formatStoredAmount(Number(minor)||0,cur||aaChartCurrency(),0,{typography:'screen'});}
function aaChartChf(chf,cur){return aaChartMoney(Math.round((Number(chf)||0)*100),cur);}
// Gruppe gemeinsam apportionieren: list = Objekte mit .bps in kanonischer
// Reihenfolge; setzt .pct (Anzeige) je Objekt. targetDisplay optional.
function aaChartApportion(list,targetDisplay){
  if(!list.length)return;
  var shown=AresRounding.formatApportionedPercentBps(list.map(function(x){return x.bps;}),1,{typography:'screen',targetDisplay:targetDisplay});
  list.forEach(function(x,k){x.pct=shown[k];});
}
function aaChartPctNumber(pct){return String(pct||'').replace(/[^0-9.]/g,'');}
// items [{name,bps,color,amountChf?,currency?,band?,subs?}] -> Zeilen nach Gewicht,
// pct apportioniert, Segment-Indizes (s.seg, r.restSeg, r.soloSeg). 0-%-Klassen
// (N-882-01) nur in den SOLL-Quoten mit Band (keepZeroWithBand), ohne Segment.
function aaChartPrepare(items,keepZeroWithBand){
  var rows=(items||[]).map(function(it,idx){
    var key=it.key||aaChartKey(it.name);
    return {name:String(it.name||''),key:key,bps:Math.max(0,Math.round(Number(it.bps)||0)),color:it.color,
      cssColor:it.cssColor||(typeof assetClassCssVar==='function'?assetClassCssVar(it.name):it.color),amountChf:it.amountChf,currency:it.currency||null,band:it.band||null,groupKey:it.groupKey||null,
      expanded:!!it.expanded,_i:idx,subs:(it.subs||[]).map(function(s,j){
        return {name:String(s.name||''),bps:Math.max(0,Math.round(Number(s.bps)||0)),note:s.note||'',_j:j};
      })};
  }).filter(function(r){return r.bps>0||(keepZeroWithBand&&r.band&&r.band.max>0);});
  // Klassen: Apportionierung in kanonischer Reihenfolge (Gleichstandsregel).
  aaChartApportion(rows.slice().sort(function(a,b){return (aaChartClassRank(a.key)-aaChartClassRank(b.key))||(a._i-b._i);}));
  rows.sort(function(a,b){return (b.bps-a.bps)||(aaChartClassRank(a.key)-aaChartClassRank(b.key))||(a._i-b._i);});
  var seg=0;
  rows.forEach(function(r){
    r.subs=r.subs.filter(function(s){return s.bps>0;});
    var subBps=r.subs.reduce(function(a,s){return a+s.bps;},0);
    // Unterklassen (+ Rest ohne Unterklasse) auf den angezeigten Klassenwert;
    // Gleichstand nach Name (Codepoint), der Rest zuletzt.
    var group=r.subs.slice().sort(function(a,b){return a.name<b.name?-1:(a.name>b.name?1:(a._j-b._j));});
    var rest=(r.subs.length&&subBps<r.bps)?{bps:r.bps-subBps}:null;
    if(rest)group.push(rest);
    if(group.length)aaChartApportion(group,subBps<=r.bps?aaChartPctNumber(r.pct):null);
    r.restPct=rest?rest.pct:'';
    r.subs.sort(function(a,b){return (b.bps-a.bps)||(a._j-b._j);});
    r.subs.forEach(function(s,j){
      s.shade=aaChartShadeStep(j,r.subs.length);s.seg=seg++;
    });
    r.restSeg=rest?seg++:null;
    r.soloSeg=(r.subs.length||!r.bps)?null:seg++;
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
// Innen Anlageklassen, aussen Unterklassen (Reihenfolge s.seg); ohne Strategie neutral.
function aaChartDonutDatasets(rows,surface){
  if(!rows||!rows.length){
    return [{data:[100],backgroundColor:['rgba(122,130,153,0.22)'],borderWidth:0,hoverOffset:0,_aaPending:true}];
  }
  var cls={data:[],backgroundColor:[],_aaLabels:[],_aaPct:[],_aaAmt:[],borderColor:surface,borderWidth:2,hoverOffset:5,weight:1,_aaRing:'class'};
  var sub={data:[],backgroundColor:[],_aaLabels:[],_aaPct:[],_aaAmt:[],_aaRow:[],borderColor:surface,borderWidth:1.5,hoverOffset:3,weight:0.3,_aaRing:'sub'};
  var push=function(i,bps,color,label,pct){sub.data.push(bps);sub.backgroundColor.push(color);sub._aaLabels.push(label);sub._aaPct.push(pct);sub._aaAmt.push('');sub._aaRow.push(i);};
  var hasSubs=false;
  rows.forEach(function(r,i){
    cls.data.push(r.bps);cls.backgroundColor.push(r.color);cls._aaLabels.push(r.name);cls._aaPct.push(r.pct);
    cls._aaAmt.push(r.amountChf>0?aaChartChf(r.amountChf,r.currency):'');
    r.subs.forEach(function(s){hasSubs=true;push(i,s.bps,aaChartMix(r.color,surface,s.shade),r.name+' › '+s.name,s.pct);});
    // Unterklassen decken die Klasse nicht ganz ab: Rest neutral, keine Zuordnung erfinden.
    if(r.restSeg!=null){var rest=r.bps-r.subs.reduce(function(a,s){return a+s.bps;},0);push(i,rest,aaChartMix(r.color,surface,0.8),r.name+' › ohne Unterklasse',r.restPct);}
    if(r.soloSeg!=null)push(i,r.bps,r.color,r.name+' (keine Unterklassen)',r.pct);
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
          titleFont:{size:10,weight:'600'},bodyFont:{size:11},displayColors:true,
          callbacks:{
            labelColor:function(ctx){var c=ctx.dataset&&ctx.dataset.backgroundColor;c=Array.isArray(c)?c[ctx.dataIndex]:c;return {borderColor:c,backgroundColor:c,borderWidth:0};},
            title:function(items){
              var ds=items&&items[0]&&items[0].dataset;
              return ds&&ds._aaRing==='sub'?'Subanlageklasse (Aussenring)':(ds&&ds._aaRing==='class'?'Anlageklasse':'');
            },
            label:function(ctx){
              var ds=ctx.dataset||{},i=ctx.dataIndex;
              var parts=[(ds._aaLabels&&ds._aaLabels[i])||String(ctx.label||'')];
              if(ds._aaPct&&ds._aaPct[i])parts.push(ds._aaPct[i]);
              if(ds._aaAmt&&ds._aaAmt[i])parts.push(ds._aaAmt[i]);
              return parts.join(' · ');
            }}}},
      onHover:function(evt,active){
        var el=active&&active.length?active[0]:null;
        var ds=el&&this.data&&this.data.datasets?this.data.datasets[el.datasetIndex]:null;
        aaChartMarkLegend(ds?(ds._aaRing==='sub'?ds._aaRow[el.index]:el.index):-1,ds&&ds._aaRing==='sub'?el.index:-1);
      }
    }};
}
// Markiert die passende Legenden-/Quotenzeile (Klasse) bzw. Unterklassenzeile.
function aaChartMarkLegend(rowIdx,segIdx){
  try{
    document.querySelectorAll('#dnleg [data-aa-row], #at [data-aa-row]').forEach(function(n){
      n.classList.toggle('is-active',String(n.getAttribute('data-aa-row'))===String(rowIdx));
    });
    document.querySelectorAll('#at [data-aa-seg]').forEach(function(n){
      n.classList.toggle('is-active',String(n.getAttribute('data-aa-seg'))===String(segIdx));
    });
  }catch(e){}
}
// Legende/SOLL-Quoten -> Torte: Segment hervorheben (Maus und Tastaturfokus).
// Unterklassenzeilen markieren ihr Segment im Aussenring.
// N-882-07: nur existierende Ring-Indizes aktivieren, sonst Markierungen zuruecksetzen.
function aaChartHoverTarget(datasets,rowAttr,segAttr){
  var ci=-1,si=-1,res={active:[],row:-1,seg:-1};
  (datasets||[]).forEach(function(d,k){if(d&&d._aaRing==='class')ci=k;if(d&&d._aaRing==='sub')si=k;});
  var ok=function(v,k){var n=Number(v);return v!=null&&v!==''&&k>=0&&Math.floor(n)===n&&n>=0&&n<((datasets[k].data||[]).length);};
  if(segAttr!=null){
    if(ok(segAttr,si)){res.seg=Number(segAttr);res.row=datasets[si]._aaRow?datasets[si]._aaRow[res.seg]:-1;res.active=[{datasetIndex:si,index:res.seg}];}
  }else if(ok(rowAttr,ci)){
    res.row=Number(rowAttr);res.active=[{datasetIndex:ci,index:res.row}];
  }
  return res;
}
function aaChartBindHover(hostId,chart){
  var host=document.getElementById(hostId);
  if(!host||!chart||host.dataset.aaBound==='1')return;
  host.dataset.aaBound='1';
  var on=function(evt){
    var t=evt.target&&evt.target.closest?evt.target:null;
    var segEl=t?t.closest('[data-aa-seg]'):null,rowEl=segEl?null:(t?t.closest('[data-aa-row]'):null);
    var h=aaChartHoverTarget(chart.data&&chart.data.datasets,rowEl?rowEl.getAttribute('data-aa-row'):null,segEl?segEl.getAttribute('data-aa-seg'):null);
    // Markierung immer setzen bzw. zuruecksetzen, auch wenn Chart.js wirft.
    aaChartMarkLegend(h.row,h.seg);
    try{
      chart.setActiveElements(h.active);
      if(chart.tooltip)chart.tooltip.setActiveElements(h.active,{x:chart.width/2,y:chart.height/2});
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
  aaChartBindHover('dnleg',chart);aaChartBindHover('at',chart);
  // N-882-05: Maus verlaesst die Torte -> Hervorhebung in Legende/Quoten zuruecksetzen.
  var cv=chart.canvas;
  if(cv&&cv.addEventListener&&cv.dataset&&cv.dataset.aaLeave!=='1'){
    cv.dataset.aaLeave='1';
    cv.addEventListener('mouseleave',function(){
      try{chart.setActiveElements([]);if(chart.tooltip)chart.tooltip.setActiveElements([],{x:0,y:0});chart.update('none');}catch(e){}
      aaChartMarkLegend(-1,-1);
    });
  }
}
// Gemeinsame Eingabe fuer Torte und SOLL-Quoten aus den Monolith-Globals.
function aaChartAllocItems(){
  var list=typeof alloc!=='undefined'&&Array.isArray(alloc)?alloc:[];
  var a=typeof strategyState!=='undefined'&&strategyState&&strategyState.allocation;
  var buckets=(a&&a.buckets)||[],cur=aaChartCurrency(),dn=function(x){x=String(x||'');return typeof assetDisplayName==='function'?assetDisplayName(x):x;};
  var rb=a&&typeof allocationReserveBreakdown==='function'?allocationReserveBreakdown(a):{advisoryRappen:0,strategyBaseRappen:0};
  // G7: Betraege wie im PDF (presentationAmounts: Basis Half-up, Largest Remainder).
  var pos=buckets.filter(function(b){return Number(b.target_weight_bps)>0;});
  var pa=AresRounding.presentationAmounts(rb.advisoryRappen,rb.strategyBaseRappen,pos.map(function(b){return b.target_weight_bps;}),pos.map(function(b){return b.asset_class;}),2);
  return list.map(function(r){
    var amount=pos.length?0:Math.round((rb.strategyBaseRappen/100)*Number(r.soll||0)/100),band=null;
    pos.forEach(function(b,i){if(dn(b.asset_class)===r.n)amount=pa.buckets[i];});
    buckets.forEach(function(b){
      if(dn(b.asset_class)===r.n&&(Number(b.band_max_bps)>0))band={min:Number(b.band_min_bps||0),max:Number(b.band_max_bps||0)};
    });
    var subs=typeof allocationSubAllocationsForBucket==='function'?allocationSubAllocationsForBucket(r.n):[];
    var gk=typeof allocationTableGroupKey==='function'?allocationTableGroupKey(r.n):String(r.n||'');
    return {name:r.n,bps:Math.round(Number(r.soll||0)*100),color:r.c,amountChf:amount,currency:cur,
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
// Legende: sortiert, Farbe, Name, Balken, %, Betrag; Reserve separat.
function aaChartLegendHtml(items,rb){
  var rows=aaChartPrepare(items);
  var html='<div class="aa-leg-head" aria-hidden="true"><span>Anlageklasse</span><span>Anteil</span><span>Betrag</span></div>'+rows.map(function(r,i){
    return '<div class="aa-leg-row" data-aa-row="'+i+'" tabindex="0" style="--aa-c:'+aaChartEsc(r.cssColor||r.color)+'">'
      +'<span class="aa-leg-sw" aria-hidden="true"></span><span class="aa-leg-name">'+aaChartEsc(r.name)+'</span>'
      +'<span class="aa-leg-bar" aria-hidden="true"><i style="width:'+(r.bps/100)+'%"></i></span>'
      +'<span class="aa-leg-pct">'+aaChartEsc(r.pct)+'</span>'
      +'<span class="aa-leg-amt">'+(r.amountChf>0?aaChartEsc(aaChartChf(r.amountChf,r.currency)):'')+'</span></div>';
  }).join('');
  if(aaChartHasSubs())html+='<div class="aa-leg-ring">Innenring: Anlageklassen · Aussenring: Subanlageklassen (Farbe wie in «SOLL-Quoten», Name im Tooltip)</div>';
  if(rb&&rb.reserveRappen>0){
    var u=AresRounding.presentationAmounts(rb.advisoryRappen,rb.strategyBaseRappen,[],[],2),fr=function(x){return aaChartChf(x);};
    html+='<div class="aa-leg-row aa-leg-reserve" id="alloc-legend-reserve"><span class="aa-leg-sw" aria-hidden="true"></span>'
      +'<span class="aa-leg-name">Liquiditätsreserve (ausserhalb der Anlagestrategie)</span><span class="aa-leg-bar" aria-hidden="true"></span>'
      +'<span class="aa-leg-pct">–</span><span class="aa-leg-amt">'+aaChartEsc(aaChartChf(u.reserve))+'</span></div>'
      +'<div class="aa-leg-note">Quoten in % der Strategiebasis '+aaChartEsc(fr(u.base))
      +'; zusammen mit der Reserve ergibt sich das Beratungsvermögen '+aaChartEsc(fr(u.advisory))+'.</div>';
  }
  return html;
}
// Leerzustand: Grund + Aktion (berechnet wird erst auf Klick).
// o: {notice, riskReady, baseText}
function aaChartPendingHtml(o){
  o=o||{};
  var title=!o.riskReady?'Risikoprofil fehlt':(o.notice?'Strategie veraltet':'Soll-Allokation noch nicht berechnet');
  var text=!o.riskReady?'Ohne aktuelles Risikoprofil kann keine Soll-Allokation berechnet werden.'
    :(o.notice?String(o.notice):'Die Soll-Allokation erscheint nach der nächsten Berechnung.');
  var btn=o.riskReady?'<button type="button" class="btn-p" onclick="calculateInvestmentStrategy()">Strategie neu berechnen</button>'
    :'<button type="button" class="btn" onclick="go(\'rp\')">Zum Risikoprofil</button>';
  return '<div class="aa-pending" role="status"><div class="aa-pending-t">'+aaChartEsc(title)+'</div>'
    +'<div class="aa-pending-x">'+aaChartEsc(text)+' Strategiebasis aktuell: '+aaChartEsc(o.baseText||'Beratungsvermögen noch offen')+'.</div>'
    +'<div class="aa-pending-a">'+btn+'</div></div>';
}
// Kennzahlen-Karte unter der Legende (Zeilen).
// o: Rappen-Werte {rein, found, nonPos, uncovered, ber, base, reserve}; f: Formatter.
function aaChartContextHtml(o,f){
  var row=function(label,value,sub){
    return '<div class="aa-ctx-row'+(sub?' aa-ctx-sub':'')+'"><span>'+aaChartEsc(label)+'</span><strong>'+aaChartEsc(f(value))+'</strong></div>';
  };
  var html=row('Reinvermögen (gesamt, netto aller Verbindlichkeiten)',o.rein,false)
    +(o.found>0?row('davon Eigenheim-Fundament',o.found,true):'');
  if(o.nonPos||o.uncovered>0){
    html+='<div class="aa-ctx-warn">Verbindlichkeiten übersteigen die Aktiven'
      +(o.uncovered>0?' – ungedeckte Schulden '+aaChartEsc(f(o.uncovered)):'')+'. Kein positives Reinvermögen.</div>';
  }
  html+=o.reserve>0
    ?row('Beratungsvermögen',o.ber,false)+row('davon in der Anlagestrategie (diese Torte)',o.base,true)
      +row('Liquiditätsreserve ausserhalb der Anlagestrategie',o.reserve,true)
    :row('Optimierbares Beratungsvermögen (diese Torte)',o.ber,false);
  return html;
}
// Bandbreite als horizontaler Balken: Skala 0-100 %, Band min-max, Ziel-Marker.
function aaChartBandHtml(band,bps,label){
  if(!band||!(band.max>0))return '';
  var mn=Math.max(0,Math.min(10000,band.min)),mx=Math.max(mn,Math.min(10000,band.max)),t=Math.max(0,Math.min(10000,bps));
  var txt='Bandbreite '+(mn===mx?aaChartPctText(mn):(aaChartPctText(mn).replace(' %','')+'–'+aaChartPctText(mx)));
  return '<span class="aa-band" role="img" aria-label="'+aaChartEsc(label+': '+txt+', Ziel '+aaChartPctText(t))+'">'
    +'<span class="aa-band-track"><span class="aa-band-range" style="left:'+(mn/100)+'%;width:'+((mx-mn)/100)+'%"></span>'
    +'<span class="aa-band-mark" style="left:'+(t/100)+'%"></span></span><span class="aa-band-txt">'+aaChartEsc(txt)+'</span></span>';
}
// SOLL-Quoten-Liste: gleiche Sortierung/Rundung wie die Torte, Unterklassen
// aufklappbar (Zustand allocationSuballocExpanded, Klick wie bisher). Farbfeld
// der Unterklasse = ihr Segment im Aussenring (Hover markiert es).
function aaChartQuotaHtml(items){
  var rows=aaChartPrepare(items,true);
  var html=rows.map(function(r,i){
    var n=r.subs.length,gk=String(r.groupKey||r.name);
    var head='<button type="button" class="aa-q-row" data-aa-row="'+i+'"'+(n?(' data-allocation-group="'+aaChartEsc(encodeURIComponent(gk))+'" aria-expanded="'+(r.expanded?'true':'false')
      +'" onclick="event.stopPropagation();toggleAllocationTableGroup(decodeURIComponent(this.getAttribute(\'data-allocation-group\')));"'):' aria-disabled="true"')
      +' style="--aa-c:'+aaChartEsc(r.cssColor||r.color)+'"><span class="aa-q-sw" aria-hidden="true"></span>'
      +'<span class="aa-q-main"><span class="aa-q-name">'+aaChartEsc(r.name)+'</span>'
      +(n?'<span class="aa-q-meta">'+n+(n===1?' Subanlageklasse':' Subanlageklassen')+' · Aussenring der Torte</span>':'')+'</span>'
      +aaChartBandHtml(r.band,r.bps,r.name)
      +'<span class="aa-q-pct">'+aaChartEsc(r.pct)+'</span><span class="aa-q-chev" aria-hidden="true"></span></button>';
    var subs=(n&&r.expanded)?'<div class="aa-q-subs">'+r.subs.map(function(s){
      return '<div class="aa-q-sub" data-aa-seg="'+s.seg+'"><span class="aa-q-sw aa-q-sw-ring" aria-hidden="true" style="background:'+aaChartEsc(aaChartCssMix(r.cssColor||r.color,s.shade))+'"></span>'
        +'<span class="aa-q-main"><span class="aa-q-name">'+aaChartEsc(s.name)+'</span>'+(s.note?'<span class="aa-q-meta">'+aaChartEsc(s.note)+'</span>':'')+'</span>'
        +'<span class="aa-q-pct">'+aaChartEsc(s.pct)+'</span></div>';
    }).join('')+'</div>':'';
    return '<div class="aa-q'+(r.expanded?' is-open':'')+'">'+head+subs+'</div>';
  }).join('');
  return html;
}
