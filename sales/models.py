from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone

# ==============================================================================
# 1. 사용자 (상담사/관리자) 모델
# ==============================================================================
class User(AbstractUser):
    ROLE_CHOICES = (
        ('ADMIN', '관리자'),
        ('AGENT', '상담원'),
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='AGENT', verbose_name="역할")
    
    # 안드로이드 중계기 앱의 FCM 토큰 (핸드폰 식별자)
    fcm_token = models.TextField(null=True, blank=True, verbose_name="안드로이드 FCM 토큰")

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

# ==============================================================================
# 2. 설정 관리용 모델 (Platform, SalesProduct 등 기존과 동일)
# ==============================================================================
class Platform(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="플랫폼명(통신사)")
    cost = models.IntegerField(default=0, verbose_name="기본 단가(원)")
    def __str__(self): return self.name

class SalesProduct(models.Model):
    CATEGORY_CHOICES = (('INTERNET', '인터넷'), ('TV', 'TV'), ('STB', '셋탑박스'), ('MOBILE', '모바일/기타'))
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, verbose_name="카테고리")
    name = models.CharField(max_length=100, verbose_name="상품명")
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return f"[{self.get_category_display()}] {self.name}"

class FailureReason(models.Model):
    reason = models.CharField(max_length=100, unique=True, verbose_name="실패 사유")
    def __str__(self): return self.reason

class CustomStatus(models.Model):
    status = models.CharField(max_length=50, verbose_name="커스텀 상태명")
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.status

class SettlementStatus(models.Model):
    status = models.CharField(max_length=50, verbose_name="정산 상태명")
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.status

# ==============================================================================
# 3. 고객(DB) 모델 - ⭐️ 수정됨 (확인 요청 필드 추가)
# ==============================================================================
class Customer(models.Model):
    phone = models.CharField(max_length=20, verbose_name="전화번호 (고유값)")
    name = models.CharField(max_length=50, default="이름없음", verbose_name="고객명")
    upload_date = models.DateField(default=timezone.now, verbose_name="DB 업로드일")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="my_customers", verbose_name="담당 상담사")
    platform = models.CharField(max_length=50, blank=True, null=True, verbose_name="플랫폼")
    status = models.CharField(max_length=50, default='미통건', verbose_name="진행 상태")
    callback_schedule = models.DateTimeField(null=True, blank=True, verbose_name="재통화 예정일")
    last_memo = models.TextField(blank=True, default="", verbose_name="최근 메모")
    rank = models.IntegerField(default=1, verbose_name="진성도")
    policy_amt = models.IntegerField(default=0)
    agent_policy = models.IntegerField(default=0)
    support_amt = models.IntegerField(default=0)
    ad_cost = models.IntegerField(default=0)
    installed_date = models.DateField(null=True, blank=True)
    settlement_due_date = models.DateField(null=True, blank=True)
    settlement_status = models.CharField(max_length=50, default='미정산', blank=True)
    product_info = models.TextField(blank=True, default="") 
    usim_info = models.CharField(max_length=100, blank=True, default="")
    additional_info = models.TextField(blank=True, default="")
    as_reason = models.CharField(max_length=100, blank=True, default="")
    is_as_approved = models.BooleanField(default=False)
    detail_reason = models.CharField(max_length=100, blank=True, null=True)
    checklist = models.CharField(max_length=200, blank=True, default="")

    # ⬇️ [핵심 추가] 관리자 확인 요청 기능용 필드
    request_status = models.CharField(
        max_length=20, 
        null=True, 
        blank=True, 
        default=None,
        help_text="REQUESTED(요청됨), PROCESSING(처리중), COMPLETED(완료)"
    )
    request_message = models.TextField(
        null=True, 
        blank=True, 
        help_text="관리자가 보낸 확인 요청 메시지"
    )

    def __str__(self):
        return f"[{self.status}] {self.name} ({self.phone})"

# ==============================================================================
# 4. 상담 이력 및 양방향 문자 로그
# ==============================================================================
class ConsultationLog(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="logs")
    writer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    content = models.TextField(verbose_name="상담 내용")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

class SMSLog(models.Model):
    DIRECTION_CHOICES = (
        ('OUT', '발신 (PC->고객)'),
        ('IN', '수신 (고객->PC)'),
    )
    STATUS_CHOICES = (
        ('PENDING', '발송대기'),
        ('SUCCESS', '전송성공'),
        ('FAIL', '전송실패'),
        ('RECEIVED', '수신완료'),
    )
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name="수신 고객", related_name="sms_messages")
    agent = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="담당 상담사")
    content = models.TextField(verbose_name="문자 내용")
    direction = models.CharField(max_length=5, choices=DIRECTION_CHOICES, default='OUT', verbose_name="방향")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING', verbose_name="상태")
    
    sent_at = models.DateTimeField(auto_now_add=True, verbose_name="발송 시간")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="생성 시간")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_direction_display()}] {self.customer.name}: {self.content[:20]}"


# [추가] 광고 채널 관리
class AdChannel(models.Model):
    name = models.CharField(max_length=50, unique=True)
    cost = models.IntegerField(default=0)  # 단가
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

# [추가] 은행 목록 관리
class Bank(models.Model):
    name = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name



# ⭐️ [신규] 공지사항 모델
class Notice(models.Model):
    title = models.CharField(max_length=200, verbose_name="제목")
    content = models.TextField(verbose_name="내용")
    is_important = models.BooleanField(default=False, verbose_name="중요 공지")
    created_at = models.DateTimeField(auto_now_add=True)
    writer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return self.title

# ⭐️ [신규] 요금표/정책 이미지 모델
class PolicyImage(models.Model):
    PLATFORM_CHOICES = (('KT', 'KT'), ('SK', 'SK'), ('LG', 'LG'), ('Sky', 'Sky'))
    platform = models.CharField(max_length=10, choices=PLATFORM_CHOICES)
    image = models.ImageField(upload_to='policy_images/', verbose_name="정책 이미지")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.platform} 정책 ({self.updated_at})"