from django.urls import path

from . import views

app_name = 'portal'
urlpatterns = [
    path('', views.index, name='index'),
    path('voucher/', views.voucher, name='voucher'),
    path('login/', views.login_user, name='login'),
    path('momo/', views.momo_start, name='momo'),
    path('momo/<str:ref>/', views.momo_wait, name='momo_wait'),
    path('momo/<str:ref>/status/', views.momo_status, name='momo_status'),
    path('sms/send/', views.sms_send, name='sms_send'),
    path('sms/verify/', views.sms_verify, name='sms_verify'),
    path('free/', views.free, name='free'),
]
