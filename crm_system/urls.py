from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from sales import views  # sales 앱 이름

# ==============================================================================
# 🔄 Router 설정 (ViewSet 자동 연결)
# ==============================================================================
router = DefaultRouter()

# 1. 상담사 및 고객 관리
router.register(r'agents', views.UserViewSet)
router.register(r'customers', views.CustomerViewSet, basename='customer')

# 2. 설정 데이터 관리
router.register(r'platforms', views.PlatformViewSet)           # 통신사/플랫폼
router.register(r'failure_reasons', views.FailureReasonViewSet) # 실패 사유
router.register(r'custom_statuses', views.CustomStatusViewSet)  # 상담 상태
router.register(r'settlement_statuses', views.SettlementStatusViewSet)
router.register(r'sales_products', views.SalesProductViewSet)
router.register(r'logs', views.ConsultationLogViewSet)

# 3. 관리자 페이지 에러 방지용 (필수)
router.register(r'ad_channels', views.AdChannelViewSet) # 광고 채널
router.register(r'banks', views.BankViewSet)           # 은행

# ==============================================================================
# 🔗 URL 패턴 정의
# ==============================================================================
urlpatterns = [
    # 1. 관리자 및 기본 인증
    path('admin/', admin.site.urls),
    path('api/login/', views.login_api, name='login'),

    # 2. 폰 연결 관련 (FCM 토큰 -> 기기 연결)
    path('api/agents/set-token/', views.update_fcm_token_view, name='set-fcm-token'),

    # 3. 대시보드 통계 (프론트엔드 경로와 일치시킴)
    path('api/dashboard/stats/', views.get_dashboard_stats, name='dashboard_stats'),

    # 4. 🔥 SMS 및 고객 유입 (핵심 경로)
    
    # [수신] 앱이 문자를 받았을 때 (Webhook)
    path('api/sms/receive/', views.SMSReceiveView.as_view(), name='sms_receive'),

    # [발신] 채팅창에서 수동 전송 (🚨 404 에러 해결: 주소 변경됨)
    path('api/sales/manual-sms/', views.send_manual_sms, name='send_manual_sms'),

    # [내역] 문자 히스토리 조회
    path('api/sms/history/<int:customer_id>/', views.get_sms_history, name='sms_history'),

    # [외부유입] 홍보 링크 / 지인 등록
    path('api/leads/capture/', views.LeadCaptureView.as_view(), name='lead_capture'),
    path('api/customers/referral/', views.LeadCaptureView.as_view(), name='customer_referral'),

    # 5. Router 등록 API 일괄 적용 (맨 마지막에 배치)
    path('api/', include(router.urls)),
]