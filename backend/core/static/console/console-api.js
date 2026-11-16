/* HotSpot Pro : branche la console (index.html) sur le serveur Django.
 * Chargé uniquement quand la console est servie par /console/.
 * L'état réel remplace les données de démonstration et les actions passent par l'API.
 */
(function () {
  'use strict';
  if (!window.HOTSPOT_API) return;
  var API = window.HOTSPOT_API;

  // Pas de sauvegarde locale de la démo en mode connecté
  SKIPSAVE = true;
  try { localStorage.removeItem(KEY); } catch (e) {}

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : (window.HOTSPOT_CSRF || '');
  }

  function call(method, path, body) {
    return fetch(API + path, {
      method: method,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.status === 401 && j.login) { location.href = '/accounts/login/?next=/console/'; throw new Error(j.error); }
        if (!r.ok) throw new Error(j.error || ('Erreur serveur (' + r.status + ')'));
        return j;
      });
    });
  }
  var post = function (path, body) { return call('POST', path, body || {}); };

  function apply(st) {
    Object.assign(S, st);
    window.HOTSPOT_ME = st.me;
  }

  function load() {
    return call('GET', '/console/state/').then(function (st) { apply(st); return st; });
  }

  function run(promise, fallback) {
    return promise.then(function (r) {
      return load().then(function () { draw(); toast(r.message || fallback || 'Enregistré'); return r; });
    }).catch(function (e) { toast(e.message); throw e; });
  }

  // Capture la fenêtre ouverte par l'action d'origine et remplace son enregistrement par un appel API.
  var realModal = modal;
  function viaModal(name, handler) {
    var orig = A[name];
    if (!orig) return;
    A[name] = function (id, el) {
      window.modal = function (title, body, kind, fn, label) {
        window.modal = realModal;
        realModal(title, body, kind, function (d) { run(handler(d, id)).catch(function () {}); }, label);
      };
      try { orig(id, el); } finally { window.modal = realModal; }
    };
  }
  function direct(name, handler) {
    A[name] = function (id, el) { return run(handler(id, el)).catch(function () {}); };
  }

  var pdvId = function () { var r = pdvR(); return r ? r.id : null; };

  viaModal('uadd', function (d) { return post('/subscribers/create/', d); });
  viaModal('ubulk', function (d) { return post('/subscribers/bulk/', d); });
  viaModal('uedit', function (d, id) { return post('/subscribers/' + id + '/update/', d); });
  viaModal('udel', function (d, id) { return post('/subscribers/' + id + '/delete/'); });
  viaModal('urenew', function (d, id) { return post('/subscribers/' + id + '/renew/', d); });
  viaModal('kick', function (d, id) { return post('/sessions/' + id + '/disconnect/'); });
  viaModal('kickall', function (d) { return post('/sessions/disconnect-nas/', d); });
  viaModal('padd', function (d) { return post('/plans/create/', d); });
  viaModal('pedit', function (d, id) { return post('/plans/' + id + '/update/', d); });
  viaModal('pdel', function (d, id) { return post('/plans/' + id + '/delete/'); });
  viaModal('vgen', function (d) { return post('/batches/create/', d); });
  viaModal('vbatchcancel', function (d, b) { return post('/batches/cancel/', { batch: b }); });
  viaModal('payko', function (d, id) { return post('/payments/' + id + '/reject/'); });
  viaModal('paysim', function (d) { return post('/payments/manual/', d); });
  viaModal('radd', function (d) { return post('/resellers/create/', d); });
  viaModal('rtop', function (d, id) { return post('/resellers/' + id + '/topup/', d); });
  viaModal('rgive', function (d, id) { return post('/resellers/' + id + '/assign/', d); });
  viaModal('dadd', function (d) { return post('/distributors/create/', d); });
  viaModal('dcredit', function (d, id) { return post('/distributors/' + id + '/credit/', d); });
  viaModal('nadd', function (d) { return post('/nas/create/', d); });
  viaModal('ndel', function (d, id) { return post('/nas/' + id + '/delete/'); });
  viaModal('tedit', function (d, id) { return post('/complaints/' + id + '/update/', d); });
  viaModal('tadd', function (d) { return post('/complaints/create/', d); });
  viaModal('pdvreq', function (d) { d.reseller = pdvId(); return post('/topups/create/', d); });

  direct('utoggle', function (id) { return post('/subscribers/' + id + '/toggle/'); });
  direct('upw', function (id) { return post('/subscribers/' + id + '/password/'); });
  direct('umac', function (id) { return post('/subscribers/' + id + '/unbind-mac/'); });
  direct('ukick', function (id) { return post('/subscribers/' + id + '/disconnect/'); });
  direct('usms', function (id) { return post('/subscribers/' + id + '/send-credentials/'); });
  direct('vcancel', function (id) { return post('/vouchers/' + id + '/cancel/'); });
  direct('payok', function (id) { return post('/payments/' + id + '/approve/'); });
  direct('topok', function (id) { return post('/topups/' + id + '/approve/'); });
  direct('topko', function (id) { return post('/topups/' + id + '/reject/'); });
  direct('ntest', function (id) { return post('/nas/' + id + '/test/'); });
  direct('atoggle', function (id) { return post('/admins/' + id + '/toggle/'); });
  direct('perm', function (k, el) {
    var p = k.split('_');
    return post('/perms/', { i: +p[0], j: +p[1], on: el.checked });
  });
  direct('login', function (k, el) { var o = {}; o[k] = el.checked; return post('/settings/', { login: o }); });
  direct('psave', function () { return post('/settings/', { portalTitle: $('#pt_title').value, portalMsg: $('#pt_msg').value }); });
  direct('retsave', function () { return post('/settings/', { retention: $('#ret').value }); });
  direct('ssave', function () {
    var g = function (id) { var e = $('#' + id); return e ? e.value : undefined; };
    return post('/settings/', { org: g('s_org'), currency: g('s_cur'), coa: g('s_coa'), interim: g('s_int'),
      idle: g('s_idle'), aggregator: g('s_agg') });
  });
  A.aadd = function () { location.href = '/admin/auth/user/add/'; };
  A.reset = function () { load().then(function () { draw(); toast('Données actualisées'); }); };

  // Vente au point de vente
  window.addEventListener('submit', function (e) {
    if (!e.target || e.target.id !== 'pdvsell') return;
    e.preventDefault();
    e.stopImmediatePropagation();
    var f = e.target;
    post('/pos/sell/', { reseller: pdvId(), plan: f.plan.value, phone: f.phone.value })
      .then(function (r) { PDVRES = r; return load(); })
      .then(function () { draw(); })
      .catch(function (err) { toast(err.message); });
  }, true);

  // Le portail de la console reste une simulation : on renvoie vers le vrai.
  var portail = VIEWS.portail;
  VIEWS.portail = function () {
    return '<p class="note">Le vrai portail captif est à l\'adresse <a href="/portal/" target="_blank" rel="noopener">/portal/</a>. ' +
      'Ouvrez-le pour tester un ticket ou un paiement réel. L\'aperçu ci-dessous ne modifie pas le serveur.</p>' + portail();
  };
  ['analytique', 'points-acces', 'marketing', 'politiques'].forEach(function (k) {
    var v = VIEWS[k];
    if (!v) return;
    VIEWS[k] = function () {
      var note = k === 'analytique'
        ? 'Fréquentation et heures calculées depuis la comptabilité RADIUS. Types d\'appareils : données d\'exemple.'
        : 'Module en démonstration : ces données ne sont pas encore enregistrées sur le serveur (voir l\'administration Django).';
      return '<p class="note">' + note + '</p>' + v();
    };
  });

  // Barre du haut : session réelle
  var top = $('#topbar');
  if (top) {
    var role = $('#role');
    if (role) { role.disabled = true; role.value = String(S.role); role.title = 'Rôle défini par votre compte'; }
    var btn = top.querySelector('[data-act=reset]');
    if (btn) {
      btn.textContent = 'Actualiser';
      var form = document.createElement('form');
      form.method = 'post';
      form.action = '/accounts/logout/';
      form.style.display = 'contents';
      form.innerHTML = '<input type="hidden" name="csrfmiddlewaretoken" value="' + esc(csrf()) + '">' +
        '<button class="btn" type="submit">Déconnexion (' + esc((window.HOTSPOT_STATE.me || {}).login || '') + ')</button>';
      btn.after(form);
    }
  }

  // Premier affichage avec l'état fourni par la page, puis actualisation régulière
  apply(window.HOTSPOT_STATE || {});
  if (!canView(cur)) location.hash = '#' + firstView(); else draw();
  setInterval(function () {
    var a = document.activeElement;
    if (!$('#ov').hidden || DU || (a && /INPUT|TEXTAREA|SELECT/.test(a.tagName))) return;
    load().then(function () { refresh(); }).catch(function () {});
  }, 15000);
})();
