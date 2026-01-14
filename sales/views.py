import os
import json
import datetime
import re
import requests
from django.utils import timezone
from django.contrib.auth import authenticate
from django.db.models import Sum, Count, Q, F, Case, When, IntegerField, Value, FloatField
from django.db.models.functions import Coalesce, Cast
from django.shortcuts import get_object_or_404
from django.http import HttpResponse

# DRF 관련 임포트
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token
from rest_framework.parsers import MultiPartParser, FormParser
from requests.auth import HTTPBasicAuth

# 모델 및 시리얼라이저
from .models import (
    Customer, User, ConsultationLog, Platform, 
    FailureReason, CustomStatus, SettlementStatus, SalesProduct, SMSLog,
    AdChannel, Bank, Notice, PolicyImage
)
from .serializers import (
    CustomerSerializer, UserSerializer, PlatformSerializer, 
    ReasonSerializer, StatusSerializer, SettlementStatusSerializer, 
    SalesProductSerializer, LogSerializer,
    AdChannelSerializer, BankSerializer, NoticeSerializer, PolicyImageSerializer
)

from .system_config import CONFIG_DATA

# [유틸리티] 전화번호 정규화
def clean_phone(phone):
    if not phone: return ""
    cleaned = re.sub(r'[^0-9]', '', str(phone))
    if cleaned.startswith('82') and len(cleaned) > 10:
        cleaned = '0' + cleaned[2:]
    return cleaned

# ==============================================================================
# [핵심] 문자 발송 함수
# ==============================================================================
def send_traccar_cloud_sms(phone, sms_text):
    phone_ip = "192.168.35.2"
    port = "8080"
    username = "sms"
    password = "YmPQD1pa"
    url = f"http://{phone_ip}:{port}/message"
    payload = { "phoneNumbers": [phone], "message": sms_text }

    try:
        response = requests.post(url, json=payload, auth=HTTPBasicAuth(username, password), timeout=3)
        if response.status_code in [200, 201, 202]:
            return True
        else:
            return False
    except Exception as e:
        print(f"❌ 연결 실패: {e}")
        return False

# ==============================================================================
# 1. 인증 및 기기 연결
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
            'role': user.role,
            'fcm_token': user.fcm_token
        })
    return Response({'message': 'ID 또는 비밀번호가 틀립니다.'}, status=400)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_fcm_token_view(request):
    fcm_token = request.data.get('fcm_token')
    if not fcm_token:
        return Response({'message': '토큰값이 없습니다.'}, status=400)
    user = request.user
    user.fcm_token = fcm_token
    user.save()
    return Response({'status': 'success', 'message': '📱 기기 연동 완료!', 'agent': user.username})

# ==============================================================================
# 2. SMS 및 고객 유입
# ==============================================================================

class SMSReceiveView(APIView):
    permission_classes = [AllowAny] 
    def post(self, request):
        data = request.data
        if 'payload' in data:
            payload = data['payload']
            from_num = payload.get('phoneNumber')
            msg_content = payload.get('message')
        else:
            from_num = data.get('from') or data.get('sender')
            msg_content = data.get('message') or data.get('text') or data.get('content')

        if not from_num or not msg_content:
            return Response({"message": "데이터 부족"}, status=400)

        if SMSLog.objects.filter(content=msg_content, direction='IN', created_at__gte=timezone.now() - datetime.timedelta(seconds=10)).exists():
            return Response({"status": "ignored", "message": "중복 메시지"}, status=200)

        clean_num = clean_phone(from_num)
        customer = Customer.objects.filter(phone__contains=clean_num[-8:]).first()
        
        if not customer:
            customer = Customer.objects.create(
                phone=clean_num,
                name=f"신규문의({clean_num[-4:]})",
                status='미통건',
                owner=None, 
                upload_date=datetime.date.today()
            )

        SMSLog.objects.create(customer=customer, agent=customer.owner, content=msg_content, direction='IN', status='RECEIVED')
        if customer.status == '부재':
            customer.status = '재통'
            customer.save()

        return Response({"status": "success"}, status=200)

class LeadCaptureView(APIView):
    permission_classes = [AllowAny] 
    def post(self, request):
        phone = clean_phone(request.data.get('phone', ''))
        agent_id = request.data.get('agent_id')
        name = request.data.get('name', '신규문의')
        custom_message = request.data.get('message') 
        platform = request.data.get('platform', '기타')

        if not phone: return Response({"message": "연락처 필수"}, status=400)
        
        agent = None
        if agent_id: 
            agent = User.objects.filter(id=agent_id).first()
        
        customer, created = Customer.objects.get_or_create(
            phone=phone,
            defaults={'name': name, 'owner': agent, 'status': '미통건', 'platform': platform}
        )

        if custom_message:
            log = SMSLog.objects.create(customer=customer, agent=agent, content=custom_message, direction='OUT', status='PENDING')
            if send_traccar_cloud_sms(phone, custom_message):
                log.status = 'SUCCESS'; log.save()
            else:
                log.status = 'FAIL'; log.save()
        
        return Response({"message": "고객 등록 완료", "customer_id": customer.id}, status=201)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_manual_sms(request):
    customer_id = request.data.get('customer_id')
    sms_text = request.data.get('message')
    agent = request.user
    customer = get_object_or_404(Customer, id=customer_id)

    log = SMSLog.objects.create(customer=customer, agent=agent, content=sms_text, direction='OUT', status='PENDING')

    if send_traccar_cloud_sms(clean_phone(customer.phone), sms_text):
        log.status = 'SUCCESS'; log.save()
        return Response({"message": "전송 성공", "log_id": log.id}, status=200)
    else:
        log.status = 'FAIL'; log.save()
        return Response({"message": "발송 실패 (앱 연결 확인 필요)", "log_id": log.id}, status=200)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_sms_history(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    logs = SMSLog.objects.filter(customer=customer).order_by('created_at')
    data = [{'id': l.id, 'sender': 'me' if l.direction == 'OUT' else 'other', 'text': l.content, 'created_at': l.created_at.strftime("%Y-%m-%d %H:%M"), 'status': l.status} for l in logs]
    return Response(data)

# ==============================================================================
# 3. ⭐️ [업그레이드] 통계 및 데이터 분석 API (StatisticsView)
# ==============================================================================

class StatisticsView(APIView):
    """
    📊 통합 통계 API (플랫폼별 광고비 단가 적용)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        platform_filter = request.query_params.get('platform', 'ALL')
        
        queryset = Customer.objects.all()
        
        # 1. 기간 필터
        if start_date:
            if len(start_date) == 10:  # 일별
                if not end_date: end_date = start_date 
                queryset = queryset.filter(upload_date__range=[start_date, end_date])
            elif len(start_date) == 7: # 월별
                queryset = queryset.filter(upload_date__startswith=start_date)

        # 2. 플랫폼 필터
        if platform_filter != 'ALL':
            queryset = queryset.filter(platform=platform_filter)

        # 정책금 단위 보정
        agent_policy_val = Cast(Coalesce(F('agent_policy'), Value(0)), IntegerField())
        support_amt_val = Cast(Coalesce(F('support_amt'), Value(0)), IntegerField())
        revenue_expression = (agent_policy_val - support_amt_val) * 10000

        # 3. 데이터 집계
        raw_stats = queryset.values('owner', 'owner__username', 'platform').annotate(
            total_db=Count('id'),
            ad_target_count=Count('id', filter=~Q(status__in=['AS요청', '실패', '중복', '실패이관'])),
            accepted_count=Count('id', filter=Q(status__in=['접수완료', '설치완료', '해지진행'])),
            installed_count=Count('id', filter=Q(status='설치완료')),
            canceled_count=Count('id', filter=Q(status='접수취소')),
            accepted_revenue=Sum(Case(When(status__in=['접수완료', '설치완료', '해지진행'], then=revenue_expression), default=0, output_field=IntegerField())),
            installed_revenue=Sum(Case(When(status='설치완료', then=revenue_expression), default=0, output_field=IntegerField()))
        ).order_by('owner')

        # ⭐️ [핵심 수정] 광고 채널 단가 로드
        # 예: {'당근': 10000, '토스': 15000, ...}
        ad_costs = { ac.name: ac.cost for ac in AdChannel.objects.all() }

        # 모든 유저 기본값 세팅
        all_users = User.objects.all()
        agent_map = {
            str(u.id): {
                "id": str(u.id), "name": u.username, 
                "db": 0, "adTargetDb": 0, "accepted": 0, "installed": 0, "canceled": 0,
                "acceptedRevenue": 0, "installedRevenue": 0, 
                "adSpend": 0, # 🟢 서버에서 계산된 총 광고비
                "platformDetails": []
            } for u in all_users
        }
        agent_map['unknown'] = {
            "id": "unknown", "name": "미배정", 
            "db": 0, "adTargetDb": 0, "accepted": 0, "installed": 0, "canceled": 0,
            "acceptedRevenue": 0, "installedRevenue": 0, "adSpend": 0,
            "platformDetails": []
        }

        # 4. 집계 및 광고비 계산
        for row in raw_stats:
            owner_id = str(row['owner']) if row['owner'] else 'unknown'
            if owner_id not in agent_map: continue 

            agent = agent_map[owner_id]
            platform_name = row['platform'] or '기타'
            
            # 수치 합산
            db_count = (row['total_db'] or 0)
            ad_target_db = (row['ad_target_count'] or 0)

            agent['db'] += db_count
            agent['adTargetDb'] += ad_target_db
            agent['accepted'] += (row['accepted_count'] or 0)
            agent['installed'] += (row['installed_count'] or 0)
            agent['canceled'] += (row['canceled_count'] or 0)
            agent['acceptedRevenue'] += (row['accepted_revenue'] or 0)
            agent['installedRevenue'] += (row['installed_revenue'] or 0)

            # 🟢 [핵심] 플랫폼별 광고비 계산 (단가 * 유효DB수)
            # 단가가 없으면 기본 0원 처리
            unit_cost = ad_costs.get(platform_name, 0)
            platform_ad_spend = ad_target_db * unit_cost
            
            agent['adSpend'] += platform_ad_spend # 총 광고비에 누적

            agent['platformDetails'].append({
                "name": platform_name,
                "db": db_count,
                "adTargetDb": ad_target_db,
                "accepted": (row['accepted_count'] or 0),
                "installed": (row['installed_count'] or 0),
                "canceled": (row['canceled_count'] or 0),
                "acceptedRevenue": (row['accepted_revenue'] or 0),
                "installedRevenue": (row['installed_revenue'] or 0),
                "adSpend": platform_ad_spend # 플랫폼별 광고비
            })

        final_results = []

        # 5. 최종 마진/수익율 계산
        for agent in agent_map.values():
            # 순수익 = 설치매출 - 광고비
            agent['netProfit'] = agent['installedRevenue'] - agent['adSpend']
            agent['avgMargin'] = round(agent['acceptedRevenue'] / agent['accepted']) if agent['accepted'] > 0 else 0
            agent['acceptRate'] = round((agent['accepted'] / agent['db'] * 100), 1) if agent['db'] > 0 else 0
            
            total_receipts = agent['accepted'] + agent['canceled']
            agent['cancelRate'] = round((agent['canceled'] / total_receipts * 100), 1) if total_receipts > 0 else 0
            agent['netInstallRate'] = round((agent['accepted'] / agent['db'] * 100), 1) if agent['db'] > 0 else 0

            # 플랫폼별 데이터도 동일 로직 적용
            for pf in agent['platformDetails']:
                pf['netProfit'] = pf['installedRevenue'] - pf['adSpend']
                pf['avgMargin'] = round(pf['acceptedRevenue'] / pf['accepted']) if pf['accepted'] > 0 else 0
                pf['acceptRate'] = round((pf['accepted'] / pf['db'] * 100), 1) if pf['db'] > 0 else 0
                
                pf_total_receipts = pf['accepted'] + pf['canceled']
                pf['cancelRate'] = round((pf['canceled'] / pf_total_receipts * 100), 1) if pf_total_receipts > 0 else 0
                pf['netInstallRate'] = round((pf['accepted'] / pf['db'] * 100), 1) if pf['db'] > 0 else 0
                
                # 순이익율
                p_revenue = pf['acceptedRevenue'] + pf['installedRevenue']
                pf['netProfitMargin'] = round((pf['netProfit'] / p_revenue * 100), 1) if p_revenue > 0 else 0

            # DB수 많은 순으로 플랫폼 정렬
            agent['platformDetails'].sort(key=lambda x: x['db'], reverse=True)
            
            # 전체 순이익율
            t_revenue = agent['acceptedRevenue'] + agent['installedRevenue']
            agent['netProfitMargin'] = round((agent['netProfit'] / t_revenue * 100), 1) if t_revenue > 0 else 0

            final_results.append(agent)

        # 설치 매출 순으로 상담사 정렬
        final_results.sort(key=lambda x: x['installedRevenue'], reverse=True)

        return Response(final_results)

# ... (나머지 ViewSet들은 기존과 동일하므로 생략 가능, 위 StatisticsView가 핵심) ...
class SystemConfigView(APIView):
    permission_classes = [AllowAny]
    def get(self, request):
        response = Response(CONFIG_DATA)
        response['Cache-Control'] = 'public, max-age=86400' 
        return response

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by('-date_joined')
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    def create(self, request, *args, **kwargs):
        username = request.data.get('username')
        password = request.data.get('password')
        if User.objects.filter(username=username).exists(): return Response({'message': '중복된 아이디'}, status=400)
        User.objects.create_user(username=username, password=password, role='AGENT')
        return Response({'message': '등록 완료'}, status=201)

class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN': return Customer.objects.all().order_by('-upload_date', '-created_at')
        return Customer.objects.filter(Q(owner=user) | Q(owner__isnull=True)).order_by('-upload_date', '-created_at')
    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)
    @action(detail=True, methods=['post'])
    def add_log(self, request, pk=None):
        customer = self.get_object()
        ConsultationLog.objects.create(customer=customer, writer=request.user, content=request.data.get('content'))
        return Response({'status': 'success'})
    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        customer = self.get_object()
        target_user_id = request.data.get('user_id')
        if target_user_id: customer.owner = get_object_or_404(User, id=target_user_id)
        else: customer.owner = request.user
        customer.status = '재통'
        customer.save()
        return Response({'message': '배정 완료'})
    @action(detail=False, methods=['post'])
    def allocate(self, request):
        ids = request.data.get('customer_ids', [])
        agent_id = request.data.get('agent_id')
        if agent_id: agent = get_object_or_404(User, id=agent_id); Customer.objects.filter(id__in=ids).update(owner=agent, status='재통')
        else: Customer.objects.filter(id__in=ids).update(owner=request.user, status='재통')
        return Response({'message': '일괄 배정 완료'})
    @action(detail=False, methods=['post'])
    def bulk_upload(self, request):
        data = request.data.get('customers', []); cnt = 0
        for item in data:
            if not item.get('phone'): continue
            Customer.objects.create(phone=clean_phone(item['phone']), name=item.get('name','미상'), upload_date=datetime.date.today(), status='미통건', owner=None, platform=item.get('platform', '기타'))
            cnt += 1
        return Response({'message': f'{cnt}건 등록', 'count': cnt})
    @action(detail=False, methods=['post'])
    def referral(self, request):
        data = request.data
        user = request.user
        Customer.objects.create(name=data.get('name', '지인소개'), phone=clean_phone(data.get('phone')), platform=data.get('platform', '지인'), status='접수완료', owner=user, upload_date=datetime.date.today(), product_info=data.get('product_info', ''))
        return Response({'message': '지인 접수 등록 완료'}, status=201)

class NoticeViewSet(viewsets.ModelViewSet):
    queryset = Notice.objects.all().order_by('-is_important', '-created_at'); serializer_class = NoticeSerializer; permission_classes = [IsAuthenticated]
    def perform_create(self, serializer): serializer.save(writer=self.request.user)
class PolicyImageViewSet(viewsets.ModelViewSet):
    queryset = PolicyImage.objects.all(); serializer_class = PolicyImageSerializer; permission_classes = [IsAuthenticated]; parser_classes = (MultiPartParser, FormParser)
    @action(detail=False, methods=['get'])
    def latest(self, request):
        data = {}
        for p in ['KT', 'SK', 'LG', 'Sky']:
            img = PolicyImage.objects.filter(platform=p).order_by('-updated_at').first()
            if img: data[p] = request.build_absolute_uri(img.image.url)
        return Response(data)

class PlatformViewSet(viewsets.ModelViewSet): queryset = Platform.objects.all(); serializer_class = PlatformSerializer; permission_classes = [IsAuthenticated]
class FailureReasonViewSet(viewsets.ModelViewSet): queryset = FailureReason.objects.all(); serializer_class = ReasonSerializer; permission_classes = [IsAuthenticated]
class CustomStatusViewSet(viewsets.ModelViewSet): queryset = CustomStatus.objects.all(); serializer_class = StatusSerializer; permission_classes = [IsAuthenticated]
class SettlementStatusViewSet(viewsets.ModelViewSet): queryset = SettlementStatus.objects.all(); serializer_class = SettlementStatusSerializer; permission_classes = [IsAuthenticated]
class SalesProductViewSet(viewsets.ModelViewSet): queryset = SalesProduct.objects.all(); serializer_class = SalesProductSerializer; permission_classes = [IsAuthenticated]
class ConsultationLogViewSet(viewsets.ModelViewSet): queryset = ConsultationLog.objects.all(); serializer_class = LogSerializer; permission_classes = [IsAuthenticated]
class AdChannelViewSet(viewsets.ModelViewSet): queryset = AdChannel.objects.all(); serializer_class = AdChannelSerializer; permission_classes = [IsAuthenticated]
class BankViewSet(viewsets.ModelViewSet): queryset = Bank.objects.all(); serializer_class = BankSerializer; permission_classes = [IsAuthenticated]

class CallPopupView(APIView):
    permission_classes = [AllowAny] 
    def post(self, request):
        phone = clean_phone(request.data.get('phone')) 
        if not phone: return Response({'message': '전화번호가 없습니다.'}, status=400)
        customer = Customer.objects.filter(phone=phone).first()
        customer_name = customer.name if customer else "신규문의"
        print(f"📞 [전화 수신] {customer_name} ({phone})")
        return Response({'status': 'success', 'customer_name': customer_name, 'customer_id': customer.id if customer else None, 'message': 'PC 팝업 요청 확인'}, status=200)

class CallRecordSaveView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        phone = clean_phone(request.data.get('phone'))
        file_link = request.data.get('file_link') 
        if not phone or not file_link: return Response({'message': '데이터 부족'}, status=400)
        customer = Customer.objects.filter(phone=phone).first()
        if not customer: customer = Customer.objects.create(phone=phone, name=f"미등록({phone[-4:]})", status='미통건', owner=None, upload_date=datetime.date.today())
        ConsultationLog.objects.create(customer=customer, writer=customer.owner, content=f"[자동저장] 통화 녹취 파일: {file_link}")
        print(f"💾 [녹음 저장] {customer.name} - 링크 저장 완료")
        return Response({'status': 'success', 'message': '녹음 파일 연결 완료'}, status=201)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_stats(request): return Response({'message': 'Use /api/stats/advanced/ instead'})