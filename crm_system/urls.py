from django.contrib import admin
from django.urls import path
from sales import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/customers/', views.get_customers),
    path('api/customers/<int:customer_id>/assign/', views.assign_customer),
    path('api/login/', views.login_api),
    path('api/customers/<int:customer_id>/update/', views.update_customer),
    path('api/customers/<int:customer_id>/add_log/', views.add_consultation_log),
    path('api/customers/bulk_upload/', views.bulk_upload),
    path('api/stats/', views.get_dashboard_stats),
    path('api/agents/', views.manage_agents),
    path('api/agents/<int:agent_id>/', views.delete_agent),
    path('api/platforms/', views.manage_platforms),
    path('api/platforms/<int:platform_id>/', views.manage_platforms),
    path('api/failure_reasons/', views.manage_failure_reasons),
    path('api/failure_reasons/<int:reason_id>/', views.manage_failure_reasons),
    path('api/my_stats/', views.get_my_stats),
    path('api/platforms/apply_all/', views.apply_platform_costs),
    path('api/customers/allocate/', views.allocate_customers),
]