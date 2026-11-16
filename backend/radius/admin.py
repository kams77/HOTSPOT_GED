from django.contrib import admin

from .models import Nas, RadAcct, RadCheck, RadGroupCheck, RadGroupReply, RadPostAuth, RadReply, RadUserGroup


@admin.register(Nas)
class NasAdmin(admin.ModelAdmin):
    list_display = ('shortname', 'nasname', 'vendor', 'zone', 'online', 'last_seen')
    search_fields = ('shortname', 'nasname', 'zone')
    list_filter = ('online', 'vendor')


@admin.register(RadAcct)
class RadAcctAdmin(admin.ModelAdmin):
    list_display = ('username', 'nasipaddress', 'framedipaddress', 'callingstationid',
                    'acctstarttime', 'acctstoptime', 'acctinputoctets', 'acctoutputoctets')
    search_fields = ('username', 'callingstationid', 'framedipaddress')
    list_filter = ('nasipaddress',)
    date_hierarchy = 'acctstarttime'

    def has_add_permission(self, request):
        return False


@admin.register(RadPostAuth)
class RadPostAuthAdmin(admin.ModelAdmin):
    list_display = ('username', 'reply', 'callingstationid', 'authdate')
    search_fields = ('username', 'callingstationid')
    list_filter = ('reply',)
    exclude = ('password',)

    def has_add_permission(self, request):
        return False


for model in (RadCheck, RadReply):
    admin.site.register(model, list_display=('username', 'attribute', 'op', 'value'), search_fields=('username',))
for model in (RadGroupCheck, RadGroupReply):
    admin.site.register(model, list_display=('groupname', 'attribute', 'op', 'value'), search_fields=('groupname',))
admin.site.register(RadUserGroup, list_display=('username', 'groupname', 'priority'), search_fields=('username',))
