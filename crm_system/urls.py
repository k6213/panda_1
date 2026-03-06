from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from sales import views  

# ==============================================================================
# 🔄 Router 설정
# ==============================================================================
router = DefaultRouter()

# 1. 상담사 및 고객 관리
router.register(r'agents', views.UserViewSet)
router.register(r'customers', views.CustomerViewSet, basename='customer')

# 2. 설정 데이터 관리
router.register(r'platforms', views.PlatformViewSet)
router.register(r'failure_reasons', views.FailureReasonViewSet)
router.register(r'cancel_reasons', views.CancelReasonViewSet) # 추가 확인됨
router.register(r'custom_statuses', views.CustomStatusViewSet)
router.register(r'settlement_statuses', views.SettlementStatusViewSet)
router.register(r'sales_products', views.SalesProductViewSet)
router.register(r'logs', views.ConsultationLogViewSet)
router.register(r'ad_channels', views.AdChannelViewSet)
router.register(r'banks', views.BankViewSet)
router.register(r'clients', views.ClientViewSet)

# 3. 정책 및 공지사항 / 업무 관리
router.register(r'notices', views.NoticeViewSet)
router.register(r'policies', views.PolicyImageViewSet) # 👈 /api/policies/latest/ 생성 지점
router.register(r'todos', views.TodoTaskViewSet, basename='todos')

# ==============================================================================
# 🔗 URL 패턴 정의
# ==============================================================================
urlpatterns = [
    path('admin/', admin.site.urls),
    
    # API 공통 경로 (/api/...)
    path('api/', include([
        # 1. 인증 및 기기연결
        path('login/', views.login_api, name='login'),
        path('agents/set-token/', views.update_fcm_token_view, name='set-fcm-token'),

        # 2. 통계 및 설정
        path('stats/advanced/', views.StatisticsView.as_view(), name='advanced_stats'),
        path('dashboard/stats/', views.get_dashboard_stats, name='dashboard_stats'),
        path('system/config/', views.SystemConfigView.as_view(), name='system_config'),

        # 3. SMS 및 외부 유입
        path('sms/receive/', views.SMSReceiveView.as_view(), name='sms_receive'),
        path('sms/test_connection/', views.test_sms_connection),
        path('sms/history/<int:customer_id>/', views.get_sms_history, name='sms_history'),
        path('sales/manual-sms/', views.send_manual_sms, name='send_manual_sms'),
        path('leads/capture/', views.LeadCaptureView.as_view(), name='lead_capture'),

        # 4. 통화 관련
        path('call/popup/', views.CallPopupView.as_view(), name='call-popup'),
        path('call/record/', views.CallRecordSaveView.as_view(), name='call-record'),

        # 5. Router 자동 생성 URL 포함 (모든 ViewSet 경로)
        path('', include(router.urls)),
    ])),
]

# 미디어 파일 서빙 설정
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)