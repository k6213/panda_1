from django.db import models
from django.contrib.auth.models import AbstractUser

# 1. 사용자 (상담원/관리자)
class User(AbstractUser):
    ROLE_CHOICES = (('ADMIN', '관리자'), ('AGENT', '상담원'))
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='AGENT')

# 2. 고객 통합 DB (엑셀 항목 완벽 반영)
class Customer(models.Model):
# --- 기본 정보 ---
    name = models.CharField(max_length=30)
    phone = models.CharField(max_length=20) # 중복 방지 Key
    platform = models.CharField(max_length=50, null=True, blank=True)
    upload_date = models.CharField(max_length=50, null=True, blank=True)

    as_reason = models.CharField(max_length=50, null=True, blank=True) # AS 신청 사유
    is_as_approved = models.BooleanField(default=False) # 관리자 승인 여부 (True면 DB 제외)
    
    # [NEW] 광고비 추가
    ad_cost = models.IntegerField(default=0) 

    # --- 상담 관리 ---
    status = models.CharField(max_length=50, default='미통건')
    callback_schedule = models.CharField(max_length=100, null=True, blank=True)
    last_memo = models.TextField(null=True, blank=True)
    detail_reason = models.CharField(max_length=50, null=True, blank=True)
    
    # [NEW] 진성도 (별점 1~5)
    rank = models.IntegerField(default=1) 

    # --- 매출 및 접수 ---
    product_info = models.CharField(max_length=200, null=True, blank=True)
    policy_amt = models.IntegerField(default=0)
    support_amt = models.IntegerField(default=0)
    installed_date = models.CharField(max_length=50, null=True, blank=True)
    additional_info = models.CharField(max_length=200, null=True, blank=True)

    # --- 시스템 ---
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # [NEW] 순수익 계산 (매출 - 광고비)
    @property
    def net_profit(self):
        revenue = (self.policy_amt - self.support_amt) * 10000
        return revenue - self.ad_cost

    def __str__(self):
        return f"{self.name} ({self.phone})"


    # [NEW] 상담 이력 (히스토리) 모델 추가
class ConsultationLog(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='logs') # 어느 고객의 로그인가?
    writer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True) # 누가 썼나?
    content = models.TextField() # 상담 내용
    created_at = models.DateTimeField(auto_now_add=True) # 작성 시간

    def __str__(self):
        return f"{self.customer.name} - {self.content[:20]}"

class Platform(models.Model):
    name = models.CharField(max_length=50, unique=True) # 플랫폼 이름 (네이버, 당근...)
    cost = models.IntegerField(default=0) # 단가 (30000, 20000...)

    def __str__(self):
        return f"{self.name} ({self.cost})"

class FailureReason(models.Model):
    reason = models.CharField(max_length=50, unique=True) # 사유 내용 (예: 요금부담)

    def __str__(self):
        return self.reason