import datetime
from django.utils import timezone
from django.contrib.auth import authenticate
from django.db.models import Sum, Q
from django.views.decorators.csrf import csrf_exempt

# DRF 관련 임포트
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token

# 모델 및 시리얼라이저 임포트
from .models import (
    Customer, User, ConsultationLog, Platform, 
    FailureReason, CustomStatus, SettlementStatus, SalesProduct
)
from .serializers import (
    CustomerSerializer, UserSerializer, PlatformSerializer, 
    ReasonSerializer, StatusSerializer, SettlementStatusSerializer, 
    SalesProductSerializer, LogSerializer
)

# ==============================================================================
# 1. 인증 (로그인)
# ==============================================================================
@api_view(['POST'])
@permission_classes([AllowAny])
def login_api(request):
    username = request.data.get('username')
    password = request.data.get('password')
    user = authenticate(username=username, password=password)
    
    if user is not None:
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'message': '로그인 성공!', 
            'token': token.key,
            'user_id': user.id, 
            'username': user.username, 
            'role': user.role
        })
    else:
        return Response({'message': '정보가 틀립니다.'}, status=400)

# ==============================================================================
# 2. 사용자(상담사) 관리 ViewSet
# ==============================================================================
class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.filter(role='AGENT').order_by('-date_joined')
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        username = request.data.get('username')
        password = request.data.get('password')
        if User.objects.filter(username=username).exists():
            return Response({'message': '중복 ID'}, status=400)
        User.objects.create_user(username=username, password=password, role='AGENT')
        return Response({'message': '등록 완료'}, status=201)

# ==============================================================================
# 3. 설정 데이터 관리 ViewSet
# ==============================================================================

# (1) 플랫폼(통신사) 관리
class PlatformViewSet(viewsets.ModelViewSet):
    queryset = Platform.objects.all()
    serializer_class = PlatformSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def apply_all(self, request):
        """변경된 단가를 기존 DB에 일괄 적용"""
        for p in Platform.objects.all():
            Customer.objects.filter(platform=p.name, ad_cost=0).update(ad_cost=p.cost)
        return Response({'message': '단가 일괄 적용 완료'})

# (2) 실패 사유 관리
class FailureReasonViewSet(viewsets.ModelViewSet):
    queryset = FailureReason.objects.all()
    serializer_class = ReasonSerializer
    permission_classes = [IsAuthenticated]

# (3) 상담 상태값 관리
class CustomStatusViewSet(viewsets.ModelViewSet):
    queryset = CustomStatus.objects.all()
    serializer_class = StatusSerializer
    permission_classes = [IsAuthenticated]

# (4) 정산 상태값 관리
class SettlementStatusViewSet(viewsets.ModelViewSet):
    queryset = SettlementStatus.objects.all().order_by('created_at')
    serializer_class = SettlementStatusSerializer
    permission_classes = [IsAuthenticated]

# (5) 상품/요금제 관리
class SalesProductViewSet(viewsets.ModelViewSet):
    queryset = SalesProduct.objects.all().order_by('category', 'name')
    serializer_class = SalesProductSerializer
    permission_classes = [IsAuthenticated]

# ==============================================================================
# 4. 상담 로그 관리
# ==============================================================================
class ConsultationLogViewSet(viewsets.ModelViewSet):
    queryset = ConsultationLog.objects.all()
    serializer_class = LogSerializer
    permission_classes = [IsAuthenticated]

# ==============================================================================
# 5. 고객(Customer) 관리
# ==============================================================================
class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return Customer.objects.all().order_by('-upload_date', '-created_at')
        else:
            return (Customer.objects.filter(owner=user) | Customer.objects.filter(owner=None)).order_by('-upload_date', '-created_at')

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        customer = self.get_object()
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'message': '상담사 ID가 필요합니다.'}, status=400)
        try:
            user = User.objects.get(pk=user_id)
            customer.owner = user
            customer.status = '재통'
            customer.save()
            return Response({'message': f'{user.username}님에게 배정되었습니다.'})
        except User.DoesNotExist:
            return Response({'message': '존재하지 않는 상담사입니다.'}, status=404)

    @action(detail=False, methods=['post'])
    def allocate(self, request):
        customer_ids = request.data.get('customer_ids', [])
        agent_id = request.data.get('agent_id')
        if not customer_ids or not agent_id:
            return Response({'message': '대상과 상담사를 선택해주세요.'}, status=400)
        try:
            agent = User.objects.get(id=agent_id)
            updated_count = Customer.objects.filter(id__in=customer_ids).update(owner=agent)
            return Response({'message': f'{updated_count}건 일괄 배정 완료'})
        except:
            return Response({'message': '배정 실패'}, status=500)

    @action(detail=True, methods=['post'])
    def handle_as(self, request, pk=None):
        customer = self.get_object()
        action = request.data.get('action')
        if action == 'approve':
            customer.is_as_approved = True
            customer.status = 'AS승인'
            customer.as_reason = f"[승인] {customer.as_reason}"
        else:
            customer.is_as_approved = False
            customer.status = '미통건'
            customer.as_reason = f"[반려] {customer.as_reason}"
        customer.save()
        return Response({'message': '처리 완료'})

    @action(detail=False, methods=['post'])
    def bulk_upload(self, request):
        if getattr(request.user, 'role', None) != 'ADMIN' and not request.user.is_superuser:
            return Response({'message': '관리자 권한이 필요합니다.'}, status=403)

        data_list = request.data.get('customers', [])
        success = 0
        errors = 0
        p_map = {p.name: p.cost for p in Platform.objects.all()}

        for item in data_list:
            try:
                phone = str(item.get('phone', '')).strip()
                if not phone: continue
                name = str(item.get('name', '이름없음')).strip()
                p_name = str(item.get('platform', '기타')).strip()
                
                raw_policy = item.get('policy', 0)
                agent_policy_val = int(raw_policy) if raw_policy else 0
                raw_cost = item.get('ad_cost', 0)
                final_cost = int(raw_cost) if raw_cost else p_map.get(p_name, 0)
                
                Customer.objects.create(
                    phone=phone, name=name, platform=p_name,
                    last_memo=item.get('last_memo', ''),
                    ad_cost=final_cost,
                    agent_policy=agent_policy_val,
                    policy_amt=0,
                    upload_date=datetime.date.today(),
                    status='미통건',
                    owner=None,
                    settlement_status='미정산'
                )
                success += 1
            except Exception as e:
                print(f"업로드 에러: {e}")
                errors += 1
        return Response({'message': f'성공 {success}건 / 실패 {errors}건', 'success': success})

    def update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return super().update(request, *args, **kwargs)


# ==============================================================================
# 6. 통계 API (대시보드용) - ⭐️ [순수익 계산식 수정 완료]
# ==============================================================================
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_stats(request):
    period = request.query_params.get('period', 'month')
    user_id = request.query_params.get('user_id')
    
    today = timezone.now().date()
    start_date = today
    end_date = today

    if period == 'today':
        start_date = today
    elif period == 'week':
        start_date = today - datetime.timedelta(days=today.weekday())
    elif period == 'month':
        start_date = today.replace(day=1)
    elif period == 'all':
        start_date = datetime.date(2000, 1, 1)
    
    query = Q(upload_date__gte=start_date) & Q(upload_date__lte=end_date)
    if user_id:
        query &= Q(owner_id=user_id)
        
    target_customers = Customer.objects.filter(query)

    total_db = target_customers.count()
    
    success_status = ['접수완료', '설치완료', '해지진행']
    revenue_status = ['접수완료', '설치완료'] # 수익 계산 대상
    cancel_status = ['접수취소', '해지진행']
    
    accept_count = target_customers.filter(status__in=success_status).count()
    accept_rate = round((accept_count / total_db * 100), 1) if total_db > 0 else 0
    
    # 설치 매출
    installed_qs = target_customers.filter(status='설치완료')
    installed_revenue = sum([c.policy_amt * 10000 for c in installed_qs])

    # ⭐️ [핵심 수정] 예상 순수익 (본사정책 - 지원금)
    revenue_qs = target_customers.filter(status__in=revenue_status)
    net_profit = 0
    for c in revenue_qs:
        policy = c.policy_amt or 0
        support = c.support_amt or 0
        
        # 기존: (support - policy) -> 역순이라 음수 발생
        # 수정: (policy - support) -> 정상 (70 - 20 = 50)
        margin = (policy - support) * 10000
        net_profit += margin

    total_ad_cost = target_customers.aggregate(Sum('ad_cost'))['ad_cost__sum'] or 0
    final_profit = net_profit - total_ad_cost

    cancel_count = target_customers.filter(status__in=cancel_status).count()
    install_count = installed_qs.count()
    total_try = accept_count + cancel_count
    cancel_rate = round((cancel_count / total_try * 100), 1) if total_try > 0 else 0
    install_rate = round((install_count / total_try * 100), 1) if total_try > 0 else 0

    # 플랫폼 통계
    platform_stats = []
    platforms = target_customers.values_list('platform', flat=True).distinct()
    for p_name in platforms:
        if not p_name: continue
        p_qs = target_customers.filter(platform=p_name)
        p_count = p_qs.count()
        p_success = p_qs.filter(status__in=success_status).count()
        p_rate = round((p_success / p_count * 100), 1) if p_count > 0 else 0
        p_ad_cost = p_qs.aggregate(Sum('ad_cost'))['ad_cost__sum'] or 0
        
        p_margin = 0
        for c in p_qs.filter(status__in=revenue_status):
            pol = c.policy_amt or 0
            sup = c.support_amt or 0
            p_margin += (pol - sup) * 10000 # 여기도 동일하게 수정
            
        platform_stats.append({
            'platform': p_name, 'count': p_count, 'success': p_success, 'rate': p_rate,
            'adCost': p_ad_cost, 'margin': p_margin
        })

    # 상담사 랭킹
    team_stats = []
    agents = User.objects.filter(role='AGENT')
    for agent in agents:
        a_qs = target_customers.filter(owner=agent)
        if not a_qs.exists(): continue
        a_total = a_qs.count()
        a_success = a_qs.filter(status__in=success_status).count()
        a_rate = round((a_success / a_total * 100), 1) if a_total > 0 else 0
        a_revenue = 0
        for c in a_qs.filter(status__in=revenue_status):
            pol = c.policy_amt or 0
            sup = c.support_amt or 0
            a_revenue += (pol - sup) * 10000 # 여기도 동일하게 수정
            
        team_stats.append({
            'id': agent.id, 'name': agent.username, 'total': a_total,
            'success': a_success, 'rate': a_rate, 'revenue': a_revenue
        })
    
    team_stats.sort(key=lambda x: x['revenue'], reverse=True)

    return Response({
        'period': period,
        'month': today.month,
        'total_db': total_db,
        'accept_count': accept_count,
        'accept_rate': accept_rate,
        'installed_revenue': installed_revenue,
        'net_profit': net_profit,
        'total_ad_cost': total_ad_cost,
        'final_profit': final_profit,
        'cancel_rate': cancel_rate,
        'install_rate': install_rate,
        'platform_stats': platform_stats,
        'team_stats': team_stats
    })