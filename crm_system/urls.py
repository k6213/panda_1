from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from sales import views

# ==============================================================================
# 🔄 Router 설정 (ViewSet 자동 연결)
# ==============================================================================
router = DefaultRouter()

# 1. 상담사 관리
router.register(r'agents', views.UserViewSet)

# 2. 고객 관리 (핵심 로직)
# basename='customer'는 get_queryset을 오버라이딩 했을 때 필수입니다.
router.register(r'customers', views.CustomerViewSet, basename='customer')

# 3. 설정 데이터 관리 (관리자용)
router.register(r'platforms', views.PlatformViewSet)           # 통신사
router.register(r'failure_reasons', views.FailureReasonViewSet) # 실패 사유
router.register(r'custom_statuses', views.CustomStatusViewSet)  # 상담 상태

# ⭐️ [신규] 정산 상태값 & 상품(요금제) 관리
router.register(r'settlement_statuses', views.SettlementStatusViewSet)
router.register(r'sales_products', views.SalesProductViewSet)

# 4. 상담 로그
router.register(r'logs', views.ConsultationLogViewSet)

# ==============================================================================
# 🔗 URL 패턴 정의
# ==============================================================================
urlpatterns = [
    # 관리자 페이지
    path('admin/', admin.site.urls),

    # 로그인 (함수형 뷰)
    path('api/login/', views.login_api),

    # 통계 (함수형 뷰)
    path('api/stats/', views.get_dashboard_stats),
    
    # Router가 만든 API 주소들 일괄 등록 (/api/...)
    path('api/', include(router.urls)),
]