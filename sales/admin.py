from django.contrib import admin
from .models import User, Customer

# 1. 사용자 관리 등록
admin.site.register(User)

# 2. 고객 DB 관리 등록 (화면에 예쁘게 보이게 설정)
@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    # 리스트에서 보여줄 항목들
    list_display = ('name', 'phone', 'status', 'upload_date', 'owner')
    # 검색 기능 추가 (이름, 번호로 검색 가능)
    search_fields = ('name', 'phone')
    # 필터 기능 추가 (상태별, 담당자별 보기)
    list_filter = ('status', 'owner')