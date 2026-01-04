from django.contrib import admin
from .models import (
    User, Customer, ConsultationLog, SMSLog, 
    Platform, FailureReason, CustomStatus, 
    SettlementStatus, SalesProduct,
    AdChannel, Bank  # ⭐️ [추가] 누락되었던 모델 추가
)

# 1. 사용자 관리 (상담사 & FCM 연결 상태)
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'role', 'date_joined', 'has_fcm_token')
    list_filter = ('role',)

    # FCM 토큰 유무로 핸드폰 연결 상태 표시
    def has_fcm_token(self, obj):
        if obj.fcm_token:
            return "✅ 연결됨"
        return "❌ 미연결"
    has_fcm_token.short_description = "휴대폰 연결 상태"

# 2. 고객 DB 관리
@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'platform', 'status', 'owner', 'upload_date')
    search_fields = ('name', 'phone', 'owner__username') # 상담사 이름으로도 검색 가능
    list_filter = ('status', 'platform', 'upload_date', 'owner')
    ordering = ('-upload_date', '-created_at')

# 3. ⭐️ SMS 발송/수신 로그 관리 (가장 중요)
@admin.register(SMSLog)
class SMSLogAdmin(admin.ModelAdmin):
    list_display = ('get_direction_icon', 'customer', 'short_content', 'agent', 'status', 'created_at')
    list_filter = ('direction', 'status', 'agent', 'created_at')
    search_fields = ('customer__name', 'customer__phone', 'content')
    readonly_fields = ('created_at',)

    # 수신/발신 아이콘 표시
    def get_direction_icon(self, obj):
        if obj.direction == 'IN':
            return "📩 수신 (고객→PC)"
        return "📤 발송 (PC→고객)"
    get_direction_icon.short_description = "구분"

    # 내용이 길면 잘라서 보여주기
    def short_content(self, obj):
        return obj.content[:30] + "..." if len(obj.content) > 30 else obj.content
    short_content.short_description = "내용"

# 4. 상담 로그 관리
@admin.register(ConsultationLog)
class LogAdmin(admin.ModelAdmin):
    list_display = ('customer', 'writer', 'content_preview', 'created_at')
    
    def content_preview(self, obj):
        return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content
    content_preview.short_description = "내용"

# 5. 설정 데이터 관리
@admin.register(Platform)
class PlatformAdmin(admin.ModelAdmin):
    list_display = ('name', 'cost')

@admin.register(SalesProduct)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('category', 'name', 'created_at')

# ⭐️ [추가] 누락되었던 모델들 등록 (에러 방지)
@admin.register(AdChannel)
class AdChannelAdmin(admin.ModelAdmin):
    list_display = ('name',)

@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = ('name',)

# 나머지 모델 등록
admin.site.register(FailureReason)
admin.site.register(CustomStatus)
admin.site.register(SettlementStatus)