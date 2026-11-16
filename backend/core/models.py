from django.conf import settings
from django.db import models


class SiteSettings(models.Model):
    """Paramètres généraux (une seule ligne, pk=1)."""
    org = models.CharField('organisation', max_length=120, default='HotSpot Pro')
    currency = models.CharField('devise', max_length=40, default='CDF (Franc congolais)')
    portal_title = models.CharField('titre du portail', max_length=80, default='Wi-Fi HotSpot Pro')
    portal_msg = models.CharField("message d'accueil", max_length=200,
                                  default='Connectez-vous avec votre ticket ou payez par Mobile Money.')
    interim = models.PositiveIntegerField('intervalle de comptabilité (s)', default=300)
    idle = models.PositiveIntegerField('déconnexion après inactivité (s)', default=600)
    coa_port = models.PositiveIntegerField('port CoA des routeurs', default=3799)
    retention_months = models.PositiveIntegerField('conservation des journaux (mois)', default=12)
    operator_wallet = models.BigIntegerField('portefeuille opérateur (FC)', default=0)
    free_minutes = models.PositiveIntegerField('accès gratuit : minutes par jour', default=30)
    free_mb = models.PositiveIntegerField('accès gratuit : Mo par jour', default=100)
    aggregator = models.CharField('agrégateur Mobile Money', max_length=120, blank=True, default='')
    login_methods = models.JSONField('méthodes de connexion', default=dict, blank=True)
    perms = models.JSONField('matrice des permissions', default=list, blank=True)

    class Meta:
        verbose_name = 'paramètres'
        verbose_name_plural = 'paramètres'

    def __str__(self):
        return 'Paramètres'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Plan(models.Model):
    name = models.CharField('nom', max_length=80)
    price = models.PositiveIntegerField('prix (FC)')
    duration = models.PositiveIntegerField('durée de connexion (min)')
    validity = models.PositiveIntegerField('validité (jours)', default=1)
    quota = models.PositiveIntegerField('volume (Mo, 0 = illimité)', default=0)
    down = models.PositiveIntegerField('débit descendant (kbit/s)', default=4096)
    up = models.PositiveIntegerField('débit montant (kbit/s)', default=2048)
    shared = models.PositiveSmallIntegerField('appareils simultanés', default=1)
    is_free = models.BooleanField('accès gratuit sponsorisé', default=False)
    login_time = models.CharField('plage horaire (Login-Time)', max_length=60, blank=True, default='',
                                  help_text='Exemple : Al2200-0600 pour 22 h – 6 h tous les jours.')
    active = models.BooleanField('en vente', default=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'forfait'
        ordering = ['price']

    def __str__(self):
        return f'{self.name} — {self.price} FC'

    @property
    def group(self):
        return f'plan-{self.pk}'


class Distributor(models.Model):
    name = models.CharField('nom', max_length=120)
    zone = models.CharField('zones couvertes', max_length=200, blank=True, default='')
    phone = models.CharField('téléphone', max_length=30, blank=True, default='')
    wallet = models.BigIntegerField('portefeuille (FC)', default=0)
    share = models.PositiveSmallIntegerField('part sur les ventes (%)', default=12)

    class Meta:
        verbose_name = 'distributeur'

    def __str__(self):
        return self.name


class Reseller(models.Model):
    name = models.CharField('nom', max_length=120)
    zone = models.CharField(max_length=120, blank=True, default='')
    phone = models.CharField('téléphone', max_length=30, blank=True, default='')
    distributor = models.ForeignKey(Distributor, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='resellers', verbose_name='distributeur')
    balance = models.BigIntegerField('solde prépayé (FC)', default=0)
    commission = models.PositiveSmallIntegerField('commission (%)', default=10)
    sold = models.PositiveIntegerField('tickets vendus', default=0)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='reseller', verbose_name='compte de connexion')

    class Meta:
        verbose_name = 'revendeur'

    def __str__(self):
        return self.name


class Subscriber(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Actif'
        SUSPENDED = 'suspended', 'Suspendu'
        EXPIRED = 'expired', 'Expiré'

    class Source(models.TextChoices):
        VOUCHER = 'voucher', 'Voucher'
        MOMO = 'momo', 'Mobile Money'
        MANUAL = 'manual', 'Manuel'
        FREE = 'free', 'Gratuit (pub)'

    username = models.CharField("nom d'utilisateur", max_length=64, unique=True)
    password = models.CharField('mot de passe', max_length=64, blank=True, default='')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscribers', verbose_name='forfait')
    phone = models.CharField('téléphone', max_length=30, blank=True, default='')
    mac = models.CharField('adresse MAC liée', max_length=17, blank=True, default='')
    status = models.CharField('statut', max_length=10, choices=Status.choices, default=Status.ACTIVE)
    source = models.CharField('origine', max_length=10, choices=Source.choices, default=Source.MANUAL)
    created = models.DateTimeField('créé le', auto_now_add=True)
    expires_at = models.DateTimeField('expire le')
    used_mb = models.FloatField('consommé (Mo)', default=0)
    usage_offset = models.BigIntegerField('octets avant la période en cours', default=0)
    time_offset = models.BigIntegerField('secondes avant la période en cours', default=0)
    reseller = models.ForeignKey(Reseller, null=True, blank=True, on_delete=models.SET_NULL, related_name='subscribers')

    class Meta:
        verbose_name = 'utilisateur'
        ordering = ['-created']

    def __str__(self):
        return self.username


class Batch(models.Model):
    code = models.CharField(max_length=40, unique=True)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='batches')
    reseller = models.ForeignKey(Reseller, null=True, blank=True, on_delete=models.SET_NULL, related_name='batches')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'lot de tickets'
        verbose_name_plural = 'lots de tickets'
        ordering = ['-created']

    def __str__(self):
        return self.code


class Voucher(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = 'available', 'Disponible'
        SOLD = 'sold', 'Vendu'
        USED = 'used', 'Utilisé'
        CANCELLED = 'cancelled', 'Annulé'

    code = models.CharField(max_length=16, unique=True)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='vouchers')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='vouchers')
    reseller = models.ForeignKey(Reseller, null=True, blank=True, on_delete=models.SET_NULL, related_name='vouchers')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.AVAILABLE)
    created = models.DateTimeField(auto_now_add=True)
    sold_at = models.DateTimeField(null=True, blank=True)
    sold_phone = models.CharField(max_length=30, blank=True, default='')
    used_at = models.DateTimeField(null=True, blank=True)
    subscriber = models.ForeignKey(Subscriber, null=True, blank=True, on_delete=models.SET_NULL, related_name='vouchers')

    class Meta:
        verbose_name = 'ticket'
        ordering = ['-created']

    def __str__(self):
        return self.code


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'En attente'
        SUCCESS = 'success', 'Réussi'
        FAILED = 'failed', 'Échoué'

    ref = models.CharField('référence', max_length=40, unique=True)
    provider_tx = models.CharField('transaction opérateur', max_length=80, blank=True, default='')
    phone = models.CharField('téléphone', max_length=30)
    operator = models.CharField('opérateur', max_length=30)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='payments')
    amount = models.PositiveIntegerField('montant (FC)')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    source = models.CharField(max_length=20, default='portal')
    created = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    subscriber = models.ForeignKey(Subscriber, null=True, blank=True, on_delete=models.SET_NULL, related_name='payments')
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'paiement'
        ordering = ['-created']

    def __str__(self):
        return self.ref


class TopupRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'En attente'
        APPROVED = 'approved', 'Validée'
        REJECTED = 'rejected', 'Refusée'

    reseller = models.ForeignKey(Reseller, on_delete=models.CASCADE, related_name='topups')
    amount = models.PositiveIntegerField('montant (FC)')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name = 'demande de recharge'
        ordering = ['-created']


class Complaint(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', 'Ouverte'
        IN_PROGRESS = 'in_progress', 'En cours'
        RESOLVED = 'resolved', 'Résolue'

    class Priority(models.TextChoices):
        HIGH = 'high', 'Haute'
        NORMAL = 'normal', 'Normale'
        LOW = 'low', 'Basse'

    ref = models.CharField(max_length=20, unique=True)
    username = models.CharField("client (nom d'utilisateur)", max_length=64)
    subscriber = models.ForeignKey(Subscriber, null=True, blank=True, on_delete=models.SET_NULL, related_name='complaints')
    phone = models.CharField(max_length=30, blank=True, default='')
    category = models.CharField('problème', max_length=60)
    priority = models.CharField('priorité', max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    message = models.TextField('description')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='complaints', verbose_name='assigné à')
    created = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'réclamation'
        ordering = ['-created']

    def __str__(self):
        return self.ref


class ComplaintNote(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='notes')
    author = models.CharField(max_length=80)
    text = models.TextField()
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created']


class OtpCode(models.Model):
    phone = models.CharField(max_length=30, db_index=True)
    code_hash = models.CharField(max_length=64)
    created = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)


class AuditLog(models.Model):
    created = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.CharField(max_length=80)
    action = models.TextField()
    kind = models.CharField(max_length=10, default='info')

    class Meta:
        verbose_name = "entrée du journal d'audit"
        verbose_name_plural = "journal d'audit"
        ordering = ['-created']


class AccessPoint(models.Model):
    name = models.CharField('nom', max_length=80)
    nas = models.ForeignKey('radius.Nas', null=True, blank=True, on_delete=models.SET_NULL, related_name='access_points')
    model = models.CharField('modèle', max_length=80, blank=True, default='')
    mac = models.CharField(max_length=17, blank=True, default='')
    firmware = models.CharField(max_length=40, blank=True, default='')
    online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "point d'accès"
        verbose_name_plural = "points d'accès"


class Policy(models.Model):
    name = models.CharField('règle', max_length=120)
    scope = models.CharField("s'applique à", max_length=120, default='Tous les forfaits')
    rule = models.TextField('effet')
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'politique'


class Ad(models.Model):
    name = models.CharField('titre', max_length=120)
    sponsor = models.CharField('annonceur', max_length=120)
    kind = models.CharField('format', max_length=30, default='Image')
    slot = models.CharField('emplacement', max_length=60, default='Avant connexion')
    media_url = models.URLField('fichier (URL)', blank=True, default='')
    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    ends_at = models.DateTimeField('fin', null=True, blank=True)

    class Meta:
        verbose_name = 'publicité'


class Campaign(models.Model):
    name = models.CharField('nom', max_length=120)
    segment = models.CharField('cible', max_length=120)
    message = models.TextField()
    sent = models.PositiveIntegerField('envoyés', default=0)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'campagne SMS'
        ordering = ['-created']
