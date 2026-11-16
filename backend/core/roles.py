"""Rôles et permissions, alignés sur la matrice de la console.

Un utilisateur Django obtient son rôle par son groupe (même nom que le rôle),
par son profil revendeur, ou comme super-utilisateur.
"""
ROLES = ['Super administrateur', 'Opérateur réseau', 'Caissier', 'Revendeur']
SUPER, NETWORK, CASHIER, RESELLER = range(4)

PERM_LABELS = [
    'Tableau de bord',
    'Sessions : déconnecter',
    'Utilisateurs : créer / modifier',
    'Forfaits : modifier les prix',
    'Vouchers : générer un lot',
    'Point de vente : vendre son stock',
    'Mobile Money : valider / rejeter',
    'Routeurs NAS : ajouter / secrets',
    'Rapports financiers',
    'Paramètres & administrateurs',
    'Publicité & campagnes',
    'Conformité : CDR et journaux web',
    'Réclamations clients : traiter',
]
DASHBOARD, SESSIONS, USERS, PLANS, VOUCHERS, POS, MOMO, NAS, FINANCE, SETTINGS, MARKETING, COMPLIANCE, COMPLAINTS = range(13)

DEFAULT_MATRIX = [
    [1, 1, 1, 0], [1, 1, 0, 0], [1, 1, 1, 0], [1, 0, 0, 0], [1, 1, 1, 0], [1, 0, 1, 1], [1, 0, 1, 0],
    [1, 1, 0, 0], [1, 0, 1, 0], [1, 0, 0, 0], [1, 0, 0, 0], [1, 1, 0, 0], [1, 1, 1, 0],
]


def matrix():
    from .models import SiteSettings
    m = SiteSettings.get().perms
    if not isinstance(m, list) or len(m) != len(DEFAULT_MATRIX):
        return [row[:] for row in DEFAULT_MATRIX]
    return m


def role_of(user):
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return SUPER
    names = set(user.groups.values_list('name', flat=True))
    for i, name in enumerate(ROLES):
        if name in names:
            return i
    if hasattr(user, 'reseller') and user.reseller is not None:
        return RESELLER
    return None


def can(user, perm):
    r = role_of(user)
    if r is None:
        return False
    if r == SUPER:
        return True
    return bool(matrix()[perm][r])
