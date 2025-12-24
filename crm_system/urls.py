from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from sales import views  # sales 앱 이름이 맞는지 확인해 주세요.

# ==============================================================================
# 🔄 Router 설정 (ViewSet 자동 연결)
# ==============================================================================
router = DefaultRouter()

# 1. 상담사 관리 (기본 CRUD)
router.register(r'agents', views.UserViewSet)

# 2. 고객 관리
router.register(r'customers', views.CustomerViewSet, basename='customer')

# 3. 설정 데이터 관리
router.register(r'platforms', views.PlatformViewSet)           # 통신사/플랫폼
router.register(r'failure_reasons', views.FailureReasonViewSet) # 실패 사유
router.register(r'custom_statuses', views.CustomStatusViewSet)  # 상담 상태
router.register(r'settlement_statuses', views.SettlementStatusViewSet)
router.register(r'sales_products', views.SalesProductViewSet)

# 4. 상담 로그 관리
router.register(r'logs', views.ConsultationLogViewSet)

# ==============================================================================
# 🔗 URL 패턴 정의
# ==============================================================================
urlpatterns = [
    # 1. 관리자 및 기본 인증
    path('admin/', admin.site.urls),
    path('api/login/', views.login_api, name='login'),

    # 2. 🔥 [중요] 폰 연결(FCM 토큰) 업데이트
    # Router가 agents/update_fcm_token을 ID로 착각하지 않도록 Router보다 위에 배치합니다.
    path('api/agents/set-token/', views.update_fcm_token_view, name='set-fcm-token'),

    # 3. 대시보드 통계
    path('api/stats/', views.get_dashboard_stats, name='dashboard_stats'),

    # 4. 🔥 SMS 양방향 연동 및 홍보링크 발송 경로
    # [수집 및 홍보링크 발송] 새 번호 입력 후 링크 보낼 때 호출
    path('api/leads/capture/', views.LeadCaptureView.as_view(), name='lead_capture'),
    
    # [수신] 핸드폰 게이트웨이 앱이 서버로 문자를 전달할 때 호출
    path('api/sms/receive/', views.SMSReceiveView.as_view(), name='sms_receive'),
    
    # [발신] 상담사가 채팅창에서 수동으로 문자를 보낼 때 호출
    path('api/sms/send-manual/', views.send_manual_sms, name='send_manual_sms'),

    # 5. Router 등록 API 일괄 적용
    # /api/agents/, /api/customers/ 등의 기본 경로들이 여기서 처리됩니다.
    path('api/', include(router.urls)),
]