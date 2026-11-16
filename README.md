# HotSpot Pro — Gestion de hotspots Wi-Fi sur RADIUS

Plateforme de gestion et d'administration de hotspots Wi-Fi : console d'administration, portail captif, tickets, Mobile Money RDC, revendeurs, et serveur FreeRADIUS. Interface en français, prix en francs congolais.

Le dépôt contient deux choses :

| | Quoi | Pour quoi faire |
|---|---|---|
| `index.html` | La console seule, avec des données d'exemple | Voir et essayer l'interface, sans rien installer |
| `backend/`, `freeradius/`, `docker-compose.yml` | Le serveur complet | Gérer de vrais routeurs, clients, tickets et paiements |

---

## 1. Essayer la démo (sans installation)

Ouvrez `index.html` dans Chrome, Edge ou Firefox. Tout fonctionne dans le navigateur avec des données d'exemple.

---

## 2. Lancer le serveur complet en local

### Prérequis

- **Docker Desktop** (Windows ou macOS) ou Docker Engine + Compose (Linux).
- Les ports 8000 (TCP), 1812 et 1813 (UDP) libres.

### Démarrage

```bash
git clone https://github.com/kams77/HOTSPOT_GED.git
cd HOTSPOT_GED
cp .env.example .env        # sous Windows : copy .env.example .env
# Ouvrez .env et changez au moins DB_PASSWORD, DJANGO_SECRET_KEY et DJANGO_SUPERUSER_PASSWORD
docker compose up --build
```

Le premier démarrage télécharge les images et prend quelques minutes. C'est prêt quand les journaux affichent `Installation prête.` puis `Ready to process requests` (FreeRADIUS).

| Adresse | Contenu |
|---|---|
| http://localhost:8000 | Console d'administration (connexion avec le compte de `.env`) |
| http://localhost:8000/portal/ | Portail captif vu par les clients |
| http://localhost:8000/admin/ | Administration Django (toutes les données, comptes du personnel) |
| UDP 1812 / 1813 | Serveur RADIUS (authentification / comptabilité) |

Avec `LOAD_DEMO=1` (valeur par défaut de `.env.example`), des données de test sont créées :

| Compte | Mot de passe | Rôle |
|---|---|---|
| valeur de `DJANGO_SUPERUSER_USERNAME` | valeur de `DJANGO_SUPERUSER_PASSWORD` | Super administrateur |
| `operateur` | `operateur12345` | Opérateur réseau |
| `caisse` | `caisse12345` | Caissier |
| `kiosque` | `kiosque12345` | Revendeur (Kiosque Victoire, 20 tickets en stock) |
| `test` | `test1234` | Client Wi-Fi (RADIUS), forfait Express 1 h |

Changez ces mots de passe avant toute mise en ligne.

### Vérifier que RADIUS répond

Depuis le conteneur RADIUS (le client `localhost` / `testing123` est préconfiguré) :

```bash
docker compose exec radius radtest test test1234 localhost 0 testing123
```

Vous devez obtenir `Received Access-Accept`, avec le débit du forfait (`WISPr-Bandwidth-Max-Down`…) et le temps restant (`Session-Timeout`). Essayez un mauvais mot de passe pour voir `Access-Reject`. Le détail de chaque requête s'affiche dans `docker compose logs -f radius`.

Testez aussi un ticket : connectez-vous en `kiosque`, vendez un ticket dans **Point de vente**, puis :

```bash
docker compose exec radius radtest CODEDUTICKET CODEDUTICKET localhost 0 testing123
```

Le ticket doit d'abord être activé une fois sur le portail (http://localhost:8000/portal/) : c'est à ce moment que le compte RADIUS est créé.

### Simuler une session (comptabilité)

```bash
docker compose exec radius sh -c 'printf "User-Name=test\nAcct-Status-Type=Start\nAcct-Session-Id=essai1\nFramed-IP-Address=10.10.1.50\nCalling-Station-Id=AA-BB-CC-DD-EE-01\nNAS-IP-Address=127.0.0.1\n" | radclient localhost:1813 acct testing123'
```

La session apparaît dans **Sessions actives** de la console (actualisation toutes les 15 secondes).

### Tester le paiement Mobile Money

Avec `MOMO_PROVIDER=demo`, ouvrez le portail, onglet **Acheter**, saisissez un numéro : le paiement est confirmé automatiquement après quelques secondes, le compte est créé et le SMS (simulé) apparaît dans le **Journal d'audit**.

### Lancer les tests automatiques

```bash
docker compose exec web python manage.py test
```

---

## 3. Brancher un vrai routeur

1. Dans la console, **Routeurs (NAS)** → **Ajouter un routeur** : nom, adresse IP du routeur telle que le serveur la voit, secret partagé.
2. Redémarrez RADIUS pour qu'il lise la nouvelle liste : `docker compose restart radius`.
3. Sur le routeur, configurez :
   - Serveur RADIUS : l'adresse IP de la machine qui fait tourner Docker
   - Ports 1812 (authentification) et 1813 (comptabilité), même secret partagé
   - Mise à jour de comptabilité (interim) : 300 s
   - Page de connexion externe (portail) : `http://IP-DU-SERVEUR:8000/portal/` avec les paramètres ci-dessous
   - « Walled garden » (sites accessibles sans connexion) : l'adresse du serveur et celles de votre agrégateur de paiement
   - Port CoA / Disconnect : 3799, pour que la console puisse déconnecter un client

| Routeur | Adresse du portail à configurer |
|---|---|
| MikroTik | `http://IP:8000/portal/?preset=mikrotik&login_url=$(link-login-only)&mac=$(mac)&dst=$(link-orig)` (activer HTTP PAP dans le profil hotspot) |
| pfSense | `http://IP:8000/portal/?preset=pfsense&login_url=$PORTAL_ACTION$&redirurl=$PORTAL_REDIRURL$&mac=$CLIENT_MAC$` |
| Autre (OpenWrt, Omada, UniFi…) | `http://IP:8000/portal/?login_url=URL_DE_CONNEXION_DU_ROUTEUR&mac=MAC_DU_CLIENT` : le portail envoie `username` et `password` en POST à cette URL |

Après une connexion réussie (ticket, Mobile Money, SMS ou accès gratuit), le portail renvoie automatiquement les identifiants au routeur, qui interroge RADIUS.

---

## 4. Passer en production

- `DJANGO_DEBUG=0`, un `DJANGO_SECRET_KEY` long et aléatoire, de vrais mots de passe.
- Un nom de domaine avec HTTPS devant le port 8000 (Nginx, Caddy ou Traefik), et `DJANGO_ALLOWED_HOSTS` / `DJANGO_CSRF_TRUSTED_ORIGINS` / `PUBLIC_URL` à jour.
- RADIUS sans débogage : dans `docker-compose.yml`, remplacez `command: ["-X"]` par `command: ["-f", "-l", "stdout"]`.
- `LOAD_DEMO=0`.
- **Mobile Money réel** : `MOMO_PROVIDER=http`, puis adaptez `backend/core/momo.py` au format de votre agrégateur. Il doit appeler `PUBLIC_URL/api/momo/webhook/` avec une signature HMAC (`MOMO_WEBHOOK_SECRET`).
- **SMS réels** : `SMS_BACKEND=http`, puis adaptez `backend/core/sms.py` à votre fournisseur.
- Sauvegardez le volume PostgreSQL (`pgdata`).

---

## 5. Architecture

```
Client Wi-Fi ──► Routeur / point d'accès ──RADIUS 1812/1813──► FreeRADIUS ──SQL──► PostgreSQL
                      │  redirection                                              ▲
                      ▼                                                           │
                 Portail captif (Django /portal/) ────────────────────────────────┤
                 Console (/console/) + API (/api/) + Admin (/admin/) ─────────────┤
                 Celery worker + beat (expirations, quotas, routeurs) ── Redis ───┘
```

| Dossier | Contenu |
|---|---|
| `backend/radius/` | Tables FreeRADIUS (`radcheck`, `radreply`, `radgroupcheck`, `radgroupreply`, `radusergroup`, `radacct`, `radpostauth`, `nas`) créées par migration Django |
| `backend/core/` | Forfaits, utilisateurs, tickets, paiements, revendeurs, réclamations ; synchronisation RADIUS (`services.py`) ; API de la console (`api.py`) ; tâches Celery (`tasks.py`) |
| `backend/portal/` | Portail captif : ticket, Mobile Money, code SMS, accès gratuit, identifiant |
| `freeradius/` | Configuration FreeRADIUS : module SQL, compteur de temps, serveur virtuel |
| `index.html` | La console. Servie par Django, elle passe en mode connecté et utilise l'API |

### Comment un forfait devient des règles RADIUS

| Forfait | Attribut RADIUS |
|---|---|
| Durée de connexion (cumulée) | `Max-All-Session` (vérifié par `noresetcounter`), le routeur reçoit le temps restant |
| Validité | `Expiration` |
| Débit | `WISPr-Bandwidth-Max-Down/Up`, `Mikrotik-Rate-Limit` |
| Volume | `ChilliSpot-Max-Total-Octets` par session ; coupure globale par la tâche `refresh_usage` |
| Appareils simultanés | `Simultaneous-Use` |
| Plage horaire | `Login-Time` |
| Compte suspendu ou expiré | `Auth-Type := Reject` |

### Rôles

Les comptes du personnel se créent dans `/admin/` et reçoivent un groupe : **Super administrateur**, **Opérateur réseau**, **Caissier** ou **Revendeur**. Un revendeur doit aussi être lié à son point de vente (fiche revendeur, champ « compte de connexion »). La matrice des permissions se règle dans la console, page **Paramètres**.

---

## 6. État du projet

Ce qui est relié au serveur : utilisateurs, sessions et déconnexion (CoA), forfaits, tickets et lots, point de vente, Mobile Money, distribution et recharges, routeurs, réclamations, paramètres, permissions, journal d'audit, historique des connexions, recettes et fréquentation.

Ce qui reste en démonstration dans la console : publicités et campagnes, politiques et filtrage web, inventaire des points d'accès, types d'appareils. Les modèles existent côté serveur et se gèrent dans `/admin/`, mais ils n'ont pas encore de logique ni d'écran relié.

Le serveur n'a pas encore été testé avec du matériel réel. Commencez par les tests `radtest` ci-dessus, puis avec un seul routeur.
