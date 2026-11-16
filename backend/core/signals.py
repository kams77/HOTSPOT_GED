"""Garde les tables RADIUS alignées sur les forfaits et les utilisateurs,
quelle que soit l'origine de la modification (console, admin, portail)."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from . import services
from .models import Plan, Subscriber


@receiver(post_save, sender=Plan)
def plan_saved(sender, instance, **kwargs):
    services.sync_plan(instance)


@receiver(post_delete, sender=Plan)
def plan_deleted(sender, instance, **kwargs):
    services.drop_plan(instance.pk)


@receiver(post_save, sender=Subscriber)
def subscriber_saved(sender, instance, **kwargs):
    services.sync_subscriber(instance)


@receiver(post_delete, sender=Subscriber)
def subscriber_deleted(sender, instance, **kwargs):
    services.drop_subscriber(instance.username)
