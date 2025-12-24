from django.contrib import admin
from .models import (
    User, Customer, ConsultationLog, SMSLog, 
    Platform, FailureReason, CustomStatus, 
    SettlementStatus, SalesProduct
)

# 1. 사용자 관리 (FCM 토큰 확인 및 연결 상태 시각화)
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'role', 'date_joined', 'has_fcm_token')
    list_filter = ('role',)

    # FCM 토큰이 있는지 여부를 O/X로 표시
    def has_fcm_token(self, obj):
        if obj.fcm_token:
            return "✅ 연결됨"
        return "❌ 미연결"
    has_fcm_token.short_description = "휴대폰 연결 상태"

# 2. 고객 DB 관리
@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'platform', 'status', 'owner', 'upload_date')
    search_fields = ('name', 'phone')
    list_filter = ('status', 'owner', 'platform', 'upload_date')
    ordering = ('-upload_date', '-created_at')

# 3. ⭐️ SMS 발송/수신 로그 관리 (양방향 확인 가능)
@admin.register(SMSLog)
class SMSLogAdmin(admin.ModelAdmin):
    # 'direction'을 추가하여 수신/발신을 구분합니다.
    list_display = ('customer', 'agent', 'direction_icon', 'content', 'status', 'created_at')
    list_filter = ('direction', 'status', 'agent', 'created_at')
    search_fields = ('customer__name', 'customer__phone', 'content')
    readonly_fields = ('created_at',) # 생성 시간은 수정 불가능하게 설정

    # 수신/발신을 아이콘으로 표시하여 가독성 증대
    def direction_icon(self, obj):
        if obj.direction == 'IN':
            return "📩 수신(고객->PC)"
        return "📤 발송(PC->고객)"
    direction_icon.short_description = "구분"

# 4. 기타 설정 데이터 관리
@admin.register(ConsultationLog)
class LogAdmin(admin.ModelAdmin):
    list_display = ('customer', 'writer', 'content', 'created_at')

@admin.register(Platform)
class PlatformAdmin(admin.ModelAdmin):
    list_display = ('name', 'cost')

@admin.register(SalesProduct)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('category', 'name', 'created_at')

# 나머지 모델 등록
admin.site.register(FailureReason)
admin.site.register(CustomStatus)
admin.site.register(SettlementStatus)