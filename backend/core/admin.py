from django.contrib import admin

from . import services
from .models import (AccessPoint, Ad, AuditLog, Batch, Campaign, Complaint, ComplaintNote, Distributor, Payment,
                     Plan, Policy, Reseller, SiteSettings, Subscriber, TopupRequest, Voucher)

admin.site.site_header = 'HotSpot Pro — administration'
admin.site.site_title = 'HotSpot Pro'
admin.site.index_title = 'Gestion des données'


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'duration', 'validity', 'quota', 'down', 'up', 'shared', 'is_free', 'active')
    list_editable = ('active',)


@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):
    list_display = ('username', 'plan', 'status', 'phone', 'expires_at', 'used_mb', 'source')
    list_filter = ('status', 'source', 'plan')
    search_fields = ('username', 'phone', 'mac')
    readonly_fields = ('created', 'used_mb', 'usage_offset', 'time_offset')
    actions = ['suspend', 'activate', 'resync']

    @admin.action(description='Suspendre les comptes sélectionnés')
    def suspend(self, request, queryset):
        for sub in queryset:
            services.set_status(sub, Subscriber.Status.SUSPENDED, services.actor_of(request.user))

    @admin.action(description='Réactiver les comptes sélectionnés')
    def activate(self, request, queryset):
        for sub in queryset:
            services.set_status(sub, Subscriber.Status.ACTIVE, services.actor_of(request.user))

    @admin.action(description='Resynchroniser avec RADIUS')
    def resync(self, request, queryset):
        for sub in queryset:
            services.sync_subscriber(sub)


class VoucherInline(admin.TabularInline):
    model = Voucher
    extra = 0
    fields = ('code', 'status', 'sold_at', 'used_at')
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ('code', 'plan', 'reseller', 'created_by', 'created')
    inlines = [VoucherInline]


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ('code', 'plan', 'batch', 'reseller', 'status', 'sold_at', 'used_at')
    list_filter = ('status', 'plan', 'reseller')
    search_fields = ('code',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('ref', 'phone', 'operator', 'plan', 'amount', 'status', 'created')
    list_filter = ('status', 'operator')
    search_fields = ('ref', 'provider_tx', 'phone')


@admin.register(Reseller)
class ResellerAdmin(admin.ModelAdmin):
    list_display = ('name', 'distributor', 'zone', 'phone', 'balance', 'commission', 'sold', 'user')
    autocomplete_fields = ('user',)


class ComplaintNoteInline(admin.TabularInline):
    model = ComplaintNote
    extra = 0


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ('ref', 'username', 'category', 'priority', 'status', 'assignee', 'created')
    list_filter = ('status', 'priority', 'category')
    search_fields = ('ref', 'username', 'phone')
    inlines = [ComplaintNoteInline]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created', 'actor', 'action', 'kind')
    list_filter = ('kind', 'actor')
    search_fields = ('action', 'actor')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(Distributor, list_display=('name', 'zone', 'phone', 'wallet', 'share'))
admin.site.register(TopupRequest, list_display=('reseller', 'amount', 'status', 'created', 'decided_by'))
admin.site.register(AccessPoint, list_display=('name', 'nas', 'model', 'online', 'last_seen'))
admin.site.register(Policy, list_display=('name', 'scope', 'active'))
admin.site.register(Ad, list_display=('name', 'sponsor', 'slot', 'impressions', 'clicks', 'active'))
admin.site.register(Campaign, list_display=('name', 'segment', 'sent', 'created'))
