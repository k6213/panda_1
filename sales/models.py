from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone

# ==============================================================================
# 1. 사용자 (상담사/관리자) 모델
# ==============================================================================
class User(AbstractUser):
    """
    Django 기본 User 모델을 확장하여 역할(role) 필드를 추가했습니다.
    """
    ROLE_CHOICES = (
        ('ADMIN', '관리자'),
        ('AGENT', '상담원'),
    )
    # 기본값은 상담원(AGENT)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='AGENT', verbose_name="역할")

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

# ==============================================================================
# 2. [설정 관리용 모델] - 관리자가 추가/수정/삭제 가능
# ==============================================================================

# (1) 통신사 (플랫폼) 관리 (예: SK, KT, LG, 헬로비전...)
class Platform(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="플랫폼명(통신사)")
    cost = models.IntegerField(default=0, verbose_name="기본 단가(원)")

    def __str__(self):
        return self.name

# ⭐️ (2) [신규 추가] 상품/요금제 관리 (상담사 팝업창용)
class SalesProduct(models.Model):
    CATEGORY_CHOICES = (
        ('INTERNET', '인터넷'),
        ('TV', 'TV'),
        ('STB', '셋탑박스'),
        ('MOBILE', '모바일/기타'),
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, verbose_name="카테고리")
    name = models.CharField(max_length=100, verbose_name="상품명")
    
    def __str__(self):
        return f"[{self.get_category_display()}] {self.name}"

# (3) 실패/취소 사유 관리
class FailureReason(models.Model):
    reason = models.CharField(max_length=100, unique=True, verbose_name="실패 사유")

    def __str__(self):
        return self.reason

# (4) 커스텀 상담 상태값 관리
class CustomStatus(models.Model):
    status = models.CharField(max_length=50, verbose_name="커스텀 상태명")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="생성일")

    def __str__(self):
        return self.status

# (5) 정산 상태값 관리 (예: 정산완료, 미정산, 환수예정)
class SettlementStatus(models.Model):
    status = models.CharField(max_length=50, verbose_name="정산 상태명")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.status

# ==============================================================================
# 3. 핵심: 고객(DB) 모델
# ==============================================================================
class Customer(models.Model):
    """상담 대상 고객 DB 정보"""
    
    # === 기본 정보 ===
    phone = models.CharField(max_length=20, verbose_name="전화번호 (고유값)")
    name = models.CharField(max_length=50, default="이름없음", verbose_name="고객명")
    upload_date = models.DateField(default=timezone.now, verbose_name="DB 업로드일 (배정 기준일)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="데이터 생성일시")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="최근 수정일시")

    # === 담당자 및 플랫폼 ===
    # 상담사가 삭제되더라도 DB는 남아야 하므로 SET_NULL 처리
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="my_customers", verbose_name="담당 상담사")
    # 플랫폼명은 검색 편의를 위해 문자열로 저장
    platform = models.CharField(max_length=50, blank=True, null=True, verbose_name="플랫폼(통신사)")

    # === 상담 상태 및 일정 관리 ===
    # 기본 상태 + 커스텀 상태 모두 문자열로 저장. 기본값 '미통건'
    status = models.CharField(max_length=50, default='미통건', verbose_name="진행 상태")
    callback_schedule = models.DateTimeField(null=True, blank=True, verbose_name="재통화 예정일시")
    last_memo = models.TextField(blank=True, default="", verbose_name="최근 상담 메모 (요약)")
    rank = models.IntegerField(default=1, verbose_name="진성도(중요도, 1~5)")

    # === 매출 및 정산 정보 (검수 기능 포함) ===
    # 1. 본사 확정 정책금 (관리자용, 정산 기준)
    policy_amt = models.IntegerField(default=0, verbose_name="본사 확정 정책금(단위:만원)")
    
    # 2. 상담사 입력 정책금 (비교 검수용)
    agent_policy = models.IntegerField(default=0, verbose_name="상담사 입력 정책금(단위:만원)")
    
    # 3. 지원금 (고객에게 나가는 돈)
    support_amt = models.IntegerField(default=0, verbose_name="지원금(단위:만원)")
    
    # 4. 광고비 (DB 단가)
    ad_cost = models.IntegerField(default=0, verbose_name="적용 광고비(단위:원)") 
    
    # 5. 설치일
    installed_date = models.DateField(null=True, blank=True, verbose_name="설치 완료일")

    # 6. 정산 예정일
    settlement_due_date = models.DateField(null=True, blank=True, verbose_name="정산예정일")

    # ⭐️ 7. [신규 추가] 정산 상태 (기본값: 미정산)
    # SettlementStatus 모델의 텍스트 값을 저장합니다.
    settlement_status = models.CharField(max_length=50, default='미정산', blank=True, verbose_name="정산 상태")

    # === 상품 및 기타 정보 ===
    # 접수완료 팝업에서 입력된 정보가 "KT / 500M / TV베이직" 형태로 저장됨
    product_info = models.TextField(blank=True, default="", verbose_name="가입 상품 정보") 
    usim_info = models.CharField(max_length=100, blank=True, default="", verbose_name="유심 정보")
    additional_info = models.TextField(blank=True, default="", verbose_name="후처리/특이사항")

    # === AS 및 실패 사유 ===
    as_reason = models.CharField(max_length=100, blank=True, default="", verbose_name="AS 요청 사유")
    is_as_approved = models.BooleanField(default=False, verbose_name="AS 승인 여부")
    # FailureReason 모델의 텍스트 값이 저장됨
    detail_reason = models.CharField(max_length=100, blank=True, null=True, verbose_name="실패/취소 상세 사유")

    # === 기타 체크리스트 (콤마로 구분된 문자열) ===
    checklist = models.CharField(max_length=200, blank=True, default="", verbose_name="체크리스트")

    def __str__(self):
        return f"[{self.status}] {self.name} ({self.phone})"

    class Meta:
        ordering = ['-created_at'] # 최신순 정렬

# ==============================================================================
# 4. 상담 이력(로그) 모델
# ==============================================================================
class ConsultationLog(models.Model):
    """고객별 상담 내역 히스토리"""
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="logs", verbose_name="관련 고객")
    writer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="작성자")
    content = models.TextField(verbose_name="상담 내용")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="작성일시 (자동 타임스탬프)")

    def __str__(self):
        writer_name = self.writer.username if self.writer else "알수없음"
        return f"Log: {self.customer.name} - {writer_name} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"
    
    class Meta:
        ordering = ['created_at'] # 과거 -> 최신순 (채팅처럼)