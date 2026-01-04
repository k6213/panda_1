import os
import json
import datetime
import re
import requests
from django.utils import timezone
from django.contrib.auth import authenticate
from django.db.models import Sum, Q
from django.shortcuts import get_object_or_404
from django.http import HttpResponse

# DRF 관련 임포트
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token
from requests.auth import HTTPBasicAuth

# 모델 및 시리얼라이저
from .models import (
    Customer, User, ConsultationLog, Platform, 
    FailureReason, CustomStatus, SettlementStatus, SalesProduct, SMSLog,
    AdChannel, Bank
)
from .serializers import (
    CustomerSerializer, UserSerializer, PlatformSerializer, 
    ReasonSerializer, StatusSerializer, SettlementStatusSerializer, 
    SalesProductSerializer, LogSerializer,
    AdChannelSerializer, BankSerializer
)

# [유틸리티] 전화번호 정규화
def clean_phone(phone):
    if not phone: return ""
    cleaned = re.sub(r'[^0-9]', '', str(phone))
    if cleaned.startswith('82') and len(cleaned) > 10:
        cleaned = '0' + cleaned[2:]
    return cleaned

# ==============================================================================
# [핵심] 문자 발송 함수 (핸드폰 앱 연동)
# ==============================================================================
def send_traccar_cloud_sms(phone, sms_text):
    phone_ip = "192.168.35.2"   # 핸드폰 IP
    port = "8080"               # 앱 포트
    username = "sms"            # 앱 아이디
    password = "YmPQD1pa"       # 앱 비밀번호

    url = f"http://{phone_ip}:{port}/message"
    
    payload = {
        "phoneNumbers": [phone],
        "message": sms_text
    }

    try:
        response = requests.post(
            url, 
            json=payload, 
            auth=HTTPBasicAuth(username, password),
            timeout=3
        )
        if response.status_code in [200, 201, 202]:
            print(f"✅ 문자 발송 성공: {phone}")
            return True
        else:
            print(f"⚠️ 앱 거부 ({response.status_code}): {response.text}")
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
# 2. 🔥 SMS 및 고객 유입 (중복 방지 & 자동 등록 적용됨)
# ==============================================================================

class SMSReceiveView(APIView):
    """ 핸드폰 앱 -> PC 문자 수신 처리 (통합 버전) """
    permission_classes = [AllowAny] 

    def post(self, request):
        data = request.data
        print(f"📩 [수신 데이터 분석]: {data}")

        # 1. 데이터 파싱 (payload 구조 대응)
        if 'payload' in data:
            payload = data['payload']
            from_num = payload.get('phoneNumber')
            msg_content = payload.get('message')
        else:
            from_num = data.get('from') or data.get('sender')
            msg_content = data.get('message') or data.get('text') or data.get('content')

        if not from_num or not msg_content:
            return Response({"message": "데이터 부족"}, status=400)

        # 2. ⭐️ 중복 수신 방지 (최근 10초 내 동일 내용 차단)
        if SMSLog.objects.filter(content=msg_content, direction='IN', created_at__gte=timezone.now() - datetime.timedelta(seconds=10)).exists():
            print(f"🛡️ 중복 문자 차단됨: {msg_content}")
            return Response({"status": "ignored", "message": "중복 메시지"}, status=200)

        # 3. 고객 찾기 및 자동 등록
        clean_num = clean_phone(from_num)
        
        # 번호 뒷 8자리로 검색해보고 없으면 새로 만듦
        customer = Customer.objects.filter(phone__contains=clean_num[-8:]).first()
        
        if not customer:
            # 🚨 DB에 없는 번호면 '신규문의'로 자동 생성!
            print(f"🆕 새로운 고객 자동 등록: {from_num}")
            customer = Customer.objects.create(
                phone=clean_num,
                name=f"신규문의({clean_num[-4:]})", # 예: 신규문의(1234)
                status='미통건',
                upload_date=datetime.date.today()
            )

        # 4. 문자 저장
        SMSLog.objects.create(
            customer=customer, 
            agent=customer.owner, 
            content=msg_content, 
            direction='IN', 
            status='RECEIVED'
        )
        print(f"✅ DB 저장 완료: {customer.name} - {msg_content}")
        
        # 상태 업데이트 (부재 -> 재통)
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
        if agent_id: agent = User.objects.filter(id=agent_id).first()
        if not agent: agent = User.objects.first()

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
    """ 수동 문자 전송 """
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
# 3. 모델 ViewSets
# ==============================================================================

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.filter(role='AGENT').order_by('-date_joined')
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    def create(self, request, *args, **kwargs):
        username = request.data.get('username'); password = request.data.get('password')
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

    @action(detail=True, methods=['post'])
    def add_log(self, request, pk=None):
        customer = self.get_object()
        ConsultationLog.objects.create(customer=customer, writer=request.user, content=request.data.get('content'))
        return Response({'status': 'success'})
    
    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        customer = self.get_object(); customer.owner = request.user; customer.status = '재통'; customer.save()
        return Response({'message': '배정 완료'})

    @action(detail=False, methods=['post'])
    def allocate(self, request):
        ids = request.data.get('customer_ids', []); agent_id = request.data.get('agent_id')
        agent = get_object_or_404(User, id=agent_id)
        Customer.objects.filter(id__in=ids).update(owner=agent, status='재통')
        return Response({'message': '일괄 배정 완료'})
        
    @action(detail=False, methods=['post'])
    def bulk_upload(self, request):
        data = request.data.get('customers', []); cnt = 0
        for item in data:
            if not item.get('phone'): continue
            Customer.objects.create(phone=clean_phone(item['phone']), name=item.get('name','미상'), upload_date=datetime.date.today(), status='미통건')
            cnt += 1
        return Response({'message': f'{cnt}건 등록', 'count': cnt})

class PlatformViewSet(viewsets.ModelViewSet): queryset = Platform.objects.all(); serializer_class = PlatformSerializer; permission_classes = [IsAuthenticated]
class FailureReasonViewSet(viewsets.ModelViewSet): queryset = FailureReason.objects.all(); serializer_class = ReasonSerializer; permission_classes = [IsAuthenticated]
class CustomStatusViewSet(viewsets.ModelViewSet): queryset = CustomStatus.objects.all(); serializer_class = StatusSerializer; permission_classes = [IsAuthenticated]
class SettlementStatusViewSet(viewsets.ModelViewSet): queryset = SettlementStatus.objects.all(); serializer_class = SettlementStatusSerializer; permission_classes = [IsAuthenticated]
class SalesProductViewSet(viewsets.ModelViewSet): queryset = SalesProduct.objects.all(); serializer_class = SalesProductSerializer; permission_classes = [IsAuthenticated]
class ConsultationLogViewSet(viewsets.ModelViewSet): queryset = ConsultationLog.objects.all(); serializer_class = LogSerializer; permission_classes = [IsAuthenticated]
class AdChannelViewSet(viewsets.ModelViewSet): queryset = AdChannel.objects.all(); serializer_class = AdChannelSerializer; permission_classes = [IsAuthenticated]
class BankViewSet(viewsets.ModelViewSet): queryset = Bank.objects.all(); serializer_class = BankSerializer; permission_classes = [IsAuthenticated]

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_stats(request):
    period = request.query_params.get('period', 'month'); user_id = request.query_params.get('user_id')
    today = timezone.now().date(); start = today.replace(day=1) if period == 'month' else today
    q = Q(upload_date__gte=start)
    if user_id == 'mine': q &= Q(owner=request.user)
    elif user_id and user_id != 'ALL': q &= Q(owner_id=user_id)
    target = Customer.objects.filter(q)
    profit = sum((int(c.agent_policy or 0)-int(c.support_amt or 0))*10000 for c in target.filter(status__in=['접수완료','설치완료']))
    return Response({'total_db': target.count(), 'accept_count': target.filter(status__in=['접수완료','설치완료']).count(), 'net_profit': profit})