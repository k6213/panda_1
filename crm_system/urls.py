from django.contrib import admin
from django.urls import path, include
from django.conf import settings             # ⭐️ 미디어 파일 설정을 위해 필요
from django.conf.urls.static import static   # ⭐️ 미디어 파일 서빙을 위해 필요
from rest_framework.routers import DefaultRouter

# ⚠️ 앱 이름이 'api'라면 'from api import views'로 수정하세요.
# 현재 기준으로는 'sales'로 되어 있어 유지합니다.
from sales import views  


# ==============================================================================
# 🔄 Router 설정 (ViewSet 자동 연결)
# ==============================================================================
router = DefaultRouter()

# 1. 상담사 및 고객 관리
# CustomerViewSet 내부의 @action(referral, assign 등)들은 자동으로 URL이 생성됩니다.
router.register(r'agents', views.UserViewSet)
router.register(r'customers', views.CustomerViewSet, basename='customer')

# 2. 설정 데이터 관리
router.register(r'platforms', views.PlatformViewSet)            # 통신사/플랫폼
router.register(r'failure_reasons', views.FailureReasonViewSet) # 실패 사유
router.register(r'custom_statuses', views.CustomStatusViewSet)  # 상담 상태
router.register(r'settlement_statuses', views.SettlementStatusViewSet)
router.register(r'sales_products', views.SalesProductViewSet)
router.register(r'logs', views.ConsultationLogViewSet)

# 3. 관리자 페이지 에러 방지용 (필수)
router.register(r'ad_channels', views.AdChannelViewSet) # 광고 채널
router.register(r'banks', views.BankViewSet)            # 은행

# 4. 정책 및 공지사항 관리
router.register(r'notices', views.NoticeViewSet)        # 공지사항
router.register(r'policies', views.PolicyImageViewSet)  # 정책 이미지

# 🟢 [추가됨] 5. 업무 및 To-Do 관리
# 이 부분이 추가되어야 /api/todos/ 및 /api/todos/assigned/ 경로가 생성됩니다.
router.register(r'todos', views.TodoTaskViewSet, basename='todos')

router.register(r'cancel_reasons', views.CancelReasonViewSet)

router.register(r'clients', views.ClientViewSet)

# ==============================================================================
# 🔗 URL 패턴 정의
# ==============================================================================
urlpatterns = [
    # 1. 관리자 및 기본 인증
    path('admin/', admin.site.urls),
    path('api/login/', views.login_api, name='login'),

    path('', include(router.urls)),

    # 2. 폰 연결 관련 (FCM 토큰 -> 기기 연결)
    path('api/agents/set-token/', views.update_fcm_token_view, name='set-fcm-token'),

    # 3. 대시보드 통계
    # (구버전) 간단 통계 - 하단 배너용 등으로 유지
    path('api/dashboard/stats/', views.get_dashboard_stats, name='dashboard_stats'),
    
    # ⭐️ [핵심] 상세 통합 통계 API (상담사별/월별/플랫폼별 분석용)
    path('api/stats/advanced/', views.StatisticsView.as_view(), name='advanced_stats'),

    # 4. 🔥 SMS 및 고객 유입
    # [수신] 앱이 문자를 받았을 때 (Webhook)
    path('api/sms/receive/', views.SMSReceiveView.as_view(), name='sms_receive'),

    # [발신] 채팅창에서 수동 전송
    path('api/sales/manual-sms/', views.send_manual_sms, name='send_manual_sms'),

    # [내역] 문자 히스토리 조회
    path('api/sms/history/<int:customer_id>/', views.get_sms_history, name='sms_history'),

    # [외부유입] 홍보 링크 (랜딩페이지 등에서 사용)
    path('api/leads/capture/', views.LeadCaptureView.as_view(), name='lead_capture'),
    
    # 5. 📞 통화 녹취 및 팝업
    path('api/call/popup/', views.CallPopupView.as_view(), name='call-popup'),
    path('api/call/record/', views.CallRecordSaveView.as_view(), name='call-record'),

    # 6. ⭐️ [신규] 시스템 설정 데이터 로드 (프론트엔드 캐싱용)
    path('api/system/config/', views.SystemConfigView.as_view(), name='system_config'),

    # 7. Router 등록 API 일괄 적용 (맨 마지막에 배치)
    # router.register로 등록한 모든 경로가 여기로 연결됩니다.
    path('api/', include(router.urls)),
]

# ⭐️ [중요] 개발 모드에서 업로드된 이미지(Media) 파일 접근 허용
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)