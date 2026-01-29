from rest_framework import serializers
from .models import (
    Customer, User, ConsultationLog, 
    Platform, FailureReason, CustomStatus, 
    SettlementStatus, SalesProduct, AdChannel, Bank,
    Notice, PolicyImage, TodoTask, CancelReason, Client # ⭐️ 신규 모델 임포트
)

# ==============================================================================
# 1. 사용자 (User) 시리얼라이저
# ==============================================================================
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'role', 'last_login']

# ==============================================================================
# 2. 상담 로그 (Log) 시리얼라이저
# ==============================================================================
class LogSerializer(serializers.ModelSerializer):
    writer_name = serializers.ReadOnlyField(source='writer.username') # 작성자 이름
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M", read_only=True) # 날짜 포맷팅

    class Meta:
        model = ConsultationLog
        fields = ['id', 'writer_name', 'content', 'created_at']

# ==============================================================================
# 3. 설정 데이터 (플랫폼, 사유, 상태 등) 시리얼라이저
# ==============================================================================
class PlatformSerializer(serializers.ModelSerializer):
    class Meta:
        model = Platform
        fields = '__all__'

class ReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = FailureReason
        fields = '__all__'

class StatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomStatus
        fields = '__all__'

# ⭐️ [신규] 정산 상태값 시리얼라이저
class SettlementStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = SettlementStatus
        fields = '__all__'

# ⭐️ [신규] 판매 상품(요금제) 시리얼라이저
class SalesProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesProduct
        fields = '__all__'

# ==============================================================================
# 4. 고객 (Customer) 시리얼라이저 - 핵심
# ==============================================================================
class CustomerSerializer(serializers.ModelSerializer):
    # 상담 로그를 포함해서 가져옴 (읽기 전용)
    logs = LogSerializer(many=True, read_only=True)
    
    # 💰 [순수익 자동 계산 필드] (정책금 - 지원금) * 10000
    net_profit = serializers.SerializerMethodField()

    # 👤 담당자 이름 (읽기 전용, 편의성)
    owner_name = serializers.ReadOnlyField(source='owner.username')

    class Meta:
        model = Customer
        # ⭐️ 새로 추가한 모든 필드를 명시합니다.
        fields = [
            'id', 'name', 'phone', 'platform', 
            'status', 'rank', 'callback_schedule','client',
            
            # --- 정산 관련 ---
            'policy_amt',   # 본사 확정
            'agent_policy', # 상담사 입력
            'support_amt',  # 지원금
            'ad_cost',      # 광고비
            'installed_date', 'net_profit', # 순수익
            'settlement_due_date', # ⭐️ 정산예정일
            'settlement_status',   # ⭐️ 정산 상태
            'settlement_complete_date',
            
            # --- 기타 정보 ---
            'product_info', 'usim_info', 'additional_info',
            'owner', 'owner_name', 'upload_date', 'last_memo', 'checklist',
            
            # --- ⭐️ [신규] 관리자 확인 요청 필드 ---
            'request_status', 
            'request_message',

            # --- 사유 및 로그 ---
            'detail_reason', 'as_reason', 'is_as_approved',
            'logs', 
            'created_at', 'updated_at',
            'settlement_memo',
        ]

    # 순수익 계산 로직: (본사정책 - 지원금) * 10000
    def get_net_profit(self, obj):
        policy = obj.policy_amt or 0
        support = obj.support_amt or 0
        # 만약 순수익에서 광고비까지 빼고 싶다면 아래 주석을 해제하세요
        # ad_cost = obj.ad_cost or 0
        # return (policy - support) * 10000 - ad_cost
        
        return (policy - support) * 10000


class AdChannelSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdChannel
        fields = '__all__'

# ⭐️ [추가] 은행 시리얼라이저
class BankSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bank
        fields = '__all__'


class NoticeSerializer(serializers.ModelSerializer):
    writer_name = serializers.ReadOnlyField(source='writer.username')
    created_at = serializers.DateTimeField(format="%Y-%m-%d", read_only=True)

    class Meta:
        model = Notice
        fields = '__all__'

class PolicyImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolicyImage
        fields = '__all__'


# sales/serializers.py 맨 아래

# 🟢 [추가] 업무 지시(Todo) 시리얼라이저
class TodoTaskSerializer(serializers.ModelSerializer):
    sender_name = serializers.ReadOnlyField(source='sender.username')       # 보낸 사람 이름 표시
    assigned_to_name = serializers.ReadOnlyField(source='assigned_to.username') # 담당자 이름 표시

    sender = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = TodoTask
        fields = '__all__'

class CancelReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = CancelReason
        fields = '__all__'


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = '__all__'