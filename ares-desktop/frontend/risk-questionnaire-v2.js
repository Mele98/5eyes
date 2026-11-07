// H5 Risikoprofil (Dok. 105, Entscheide E1-E7): Ergaenzungen der Risikoprofil-
// Maske. Ausgelagert aus ares.html (Monolith-Budget, Toleranz 0); wird als
// klassisches synchrones Skript direkt nach goal-review-runtime.js geladen und
// nutzt die globalen Helfer des Monolithen erst beim Aufruf.
//
// Fragen 1-11 bleiben wortgleich und mit ihren Punkten unveraendert (Owner-
// Regel: Risikoprofil nach Vorlage, kein UX-Refactoring). Dieses Modul ergaenzt
// nur die beschlossenen Teile im Stil der bestehenden Fragen.
//
// H5a: Fussnote zu Frage 10 (Bandbreite ~80 % ueber ein Jahr). Rein textlich,
// ohne Score-Wirkung. Wortgleich zu services/pdf/components/eignungspruefung.py
// (Q10_BAND_FOOTNOTE); test_frontend_risk_questionnaire_v2.py prueft die Paritaet.
var RISK_Q10_BAND_FOOTNOTE='Hinweis zu Frage 10: Die genannte Bandbreite umfasst rund 80 % der zu '
  +'erwartenden Wertentwicklungen innerhalb eines Jahres. Mit je rund 10 % '
  +'Wahrscheinlichkeit fällt das Ergebnis besser bzw. schlechter aus – ein '
  +'Verlust kann also auch grösser sein als die untere Grenze der Bandbreite.';

function riskV2Sections(){
  return document.querySelectorAll('#r-rb .qsec');
}

function riskV2AddQ10Footnote(){
  var q10=riskV2Sections()[1];
  if(!q10||q10.querySelector('.rp-q10-note'))return;
  var note=document.createElement('div');
  note.className='rp-q10-note';
  note.style.cssText='padding-left:24px;margin-top:6px;font-size:9.5px;line-height:1.45;color:var(--n5)';
  note.textContent=RISK_Q10_BAND_FOOTNOTE;
  q10.appendChild(note);
}

riskV2AddQ10Footnote();
