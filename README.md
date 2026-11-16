# HotSpot Pro — Console de gestion HotSpot RADIUS

Démo interactive d'une plateforme de gestion et d'administration de hotspots Wi-Fi reposant sur un serveur RADIUS (FreeRADIUS). Interface en français, prix en francs congolais, Mobile Money RDC.

> **Statut : démonstration.** Toute la logique tourne dans le navigateur avec des données d'exemple. Aucune connexion réelle aux routeurs, aux opérateurs Mobile Money ni aux SMS.

## Tester en local

Aucune installation nécessaire.

1. Clonez ou téléchargez le dépôt.
2. Ouvrez `index.html` dans Chrome, Edge ou Firefox (double-clic).

Ou avec un petit serveur local :

```bash
python -m http.server 8000
# puis ouvrez http://localhost:8000
```

Vos modifications sont conservées 12 h dans le navigateur. Le bouton « Réinitialiser la démo » remet les données d'exemple.

## Modules

| Domaine | Modules |
|---|---|
| Supervision | Tableau de bord, Sessions actives (déconnexion CoA), Analytique visiteurs |
| Clients | Utilisateurs (fiche client complète), Réclamations, Forfaits (attributs RADIUS), Tickets / Vouchers, Politiques & QoS |
| Ventes | Point de vente revendeur, Mobile Money (M-Pesa, Airtel Money, Orange Money), Distribution à 3 niveaux, Publicité & campagnes SMS, Rapports |
| Réseau | Routeurs (NAS), Points d'accès, Portail captif (ticket, Mobile Money, SMS OTP, accès gratuit sponsorisé, MAC) |
| Système | Conformité & journaux (CDR, journaux web), Journal d'audit, Paramètres, rôles et permissions, Correspondance Indio |

Fonctions transverses : rôles appliqués (« Voir en tant que »), recherche globale (touche `/`), tri et pagination des tableaux, exports CSV.

## Parcours de test rapide

1. **Point de vente** : vendez un ticket et notez le code.
2. **Portail captif** : saisissez ce code dans le téléphone ; le client apparaît dans **Sessions actives**.
3. **Portail captif → Acheter** : payez par Mobile Money ; le paiement passe à « réussi » et le compte est créé.
4. Changez de rôle en haut (« Voir en tant que : Revendeur ») pour voir la console restreinte.

## Architecture cible (à développer)

- **Backend** : Django + PostgreSQL
- **AAA** : FreeRADIUS (module `rlm_sql`) lisant les tables `radcheck`, `radgroupcheck`, `radgroupreply`, `radacct`, `nas`
- **Tâches** : Celery + Redis (expirations, alertes, rapports)
- **Paiements** : webhooks de l'agrégateur Mobile Money
- **Déploiement** : Docker Compose
