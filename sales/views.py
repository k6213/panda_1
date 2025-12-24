import os
import json
import datetime
import re
import requests  # 🔥 Firebase 대신 HTTP 요청을 위해 추가
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

# 모델 및 시리얼라이저 임포트
from .models import (
    Customer, User, ConsultationLog, Platform, 
    FailureReason, CustomStatus, SettlementStatus, SalesProduct, SMSLog
)
from .serializers import (
    CustomerSerializer, UserSerializer, PlatformSerializer, 
    ReasonSerializer, StatusSerializer, SettlementStatusSerializer, 
    SalesProductSerializer, LogSerializer
)

# ==============================================================================
# [유틸리티] Traccar 클라우드 API 발송 함수
# ==============================================================================
def send_traccar_cloud_sms(phone, sms_text):
    """
    Traccar 공식 클라우드 서버를 통해 안드로이드 기기로 발송 명령을 전달합니다.
    """
    url = "https://www.traccar.org/sms/"  # 파워쉘에서 성공한 주소
    
    # 사진에서 확인된 사용자님의 클라우드 토큰
    # 보안을 위해 실제 배포 시에는 os.environ.get('TRACCAR_TOKEN') 사용을 권장합니다.
    cloud_token = "eb8CCImGSFe3AEUIUkobAZ:APA91bEwtQEoN2nuqw8iBKY9jYc4KLbc1_pFny56kVGPcCB8jUbR-XBqXcLY2MXK_FVW7QyCHBvhnQ7RYNrh5WV037HOuczDvej2aBgsobpuKR2P0w-_wnA"

    headers = {
        "Authorization": cloud_token,
        "Content-Type": "application/json"
    }

    payload = {
        "to": phone,
        "message": sms_text
    }

    try:
        # POST 요청을 통해 Traccar 중계 서버로 전달
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        # 응답 확인 (파워쉘 결과와 동일하게 successCount가 포함된 JSON 반환)
        if response.status_code == 200:
            result = response.json()
            if result.get('successCount', 0) > 0:
                print(f"✅ SMS 발송 요청 성공: {phone}")
                return True
        print(f"⚠️ SMS 서버 응답 오류: {response.status_code} - {response.text}")
        return False
    except Exception as e:
        print(f"❌ SMS API 호출 실패: {str(e)}")
        return False

# [유틸리티] 전화번호 정규화
def clean_phone(phone):
    if not phone: return ""
    cleaned = re.sub(r'[^0-9]', '', str(phone))
    if cleaned.startswith('82'):
        cleaned = '0' + cleaned[2:]
    return cleaned

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
    """ 상담사의 핸드폰 FCM 토큰을 서버에 등록 (기기 연결) """
    fcm_token = request.data.get('fcm_token')
    if not fcm_token:
        return Response({'message': '토큰값이 없습니다.'}, status=400)
    
    user = request.user
    user.fcm_token = fcm_token
    user.save()
    
    return Response({
        'status': 'success',
        'message': '📱 기기 연동 완료!',
        'agent': user.username
    })

# ==============================================================================
# 2. 🔥 SMS 양방향 연동 (Traccar API 적용 버전)
# ==============================================================================

class SMSReceiveView(APIView):
    """ 고객이 보낸 문자를 수신 (Traccar 게이트웨이 앱의 Webhook) """
    permission_classes = [AllowAny] 

    def post(self, request):
        from_num = clean_phone(request.data.get('from', ''))
        msg_content = request.data.get('message', '')

        if not from_num or not msg_content:
            return Response({"message": "데이터 부족"}, status=400)

        search_num = from_num[-8:]
        customer = Customer.objects.filter(phone__contains=search_num).first()

        if customer:
            SMSLog.objects.create(
                customer=customer, 
                agent=customer.owner, 
                content=msg_content, 
                direction='IN', 
                status='RECEIVED'
            )
            if customer.status == '부재':
                customer.status = '재통'
                customer.save()
            return Response({"status": "success"}, status=200)
        
        return Response({"status": "ignored", "message": "등록되지 않은 고객 번호"}, status=200)


class LeadCaptureView(APIView):
    """ [홍보링크 발송 & 랜딩페이지 수집] """
    permission_classes = [AllowAny] 

    def post(self, request):
        phone = clean_phone(request.data.get('phone', ''))
        agent_id = request.data.get('agent_id')
        name = request.data.get('name', '신규문의')
        custom_message = request.data.get('message')

        if not phone or not agent_id:
            return Response({"message": "필수 정보(번호/상담사)가 없습니다."}, status=400)

        agent = get_object_or_404(User, id=agent_id)
        customer, created = Customer.objects.get_or_create(
            phone=phone,
            defaults={'name': name, 'owner': agent, 'status': '미통건'}
        )

        sms_text = custom_message if custom_message else f"[상담신청] {name}님 정보가 접수되었습니다."

        # 발송 로그 생성
        log = SMSLog.objects.create(
            customer=customer, agent=agent, content=sms_text, direction='OUT', status='PENDING'
        )

        # 🔥 수정됨: Firebase 직접 전송 대신 Traccar Cloud API 호출
        if send_traccar_cloud_sms(phone, sms_text):
            log.status = 'SUCCESS'
            log.save()
            return Response({"message": "발송 명령 완료", "customer_id": customer.id}, status=201)
        else:
            log.status = 'FAIL'
            log.save()
            return Response({"message": "기기 전송 실패(Traccar 서버 응답 없음)"}, status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_manual_sms(request):
    """ 채팅창 하단 입력칸에서 상담사가 직접 문자를 보낼 때 실행 """
    customer_id = request.data.get('customer_id')
    sms_text = request.data.get('message')
    agent = request.user
    customer = get_object_or_404(Customer, id=customer_id)

    # 🔥 수정됨: Traccar Cloud API 호출
    if send_traccar_cloud_sms(clean_phone(customer.phone), sms_text):
        SMSLog.objects.create(
            customer=customer, agent=agent, content=sms_text, direction='OUT', status='SUCCESS'
        )
        return Response({"message": "전송 성공"})
    else:
        return Response({"message": "발송 에러: Traccar 서버에 도달할 수 없습니다."}, status=500)

# ==============================================================================
# 3. 모델 기반 CRUD ViewSets (기존 로직 유지)
# ==============================================================================

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.filter(role='AGENT').order_by('-date_joined')
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        username = request.data.get('username')
        password = request.data.get('password')
        if User.objects.filter(username=username).exists():
            return Response({'message': '중복된 아이디입니다.'}, status=400)
        User.objects.create_user(username=username, password=password, role='AGENT')
        return Response({'message': '상담사 등록 완료'}, status=201)

class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'ADMIN':
            return Customer.objects.all().order_by('-upload_date', '-created_at')
        return Customer.objects.filter(Q(owner=user) | Q(owner__isnull=True)).order_by('-upload_date', '-created_at')

    @action(detail=True, methods=['post'])
    def add_log(self, request, pk=None):
        customer = self.get_object()
        ConsultationLog.objects.create(customer=customer, writer=request.user, content=request.data.get('content'))
        return Response({'status': 'success'})

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        customer = self.get_object()
        customer.owner = request.user
        customer.status = '재통'
        customer.save()
        return Response({'message': '내 담당으로 배정되었습니다.'})

    @action(detail=False, methods=['post'])
    def bulk_upload(self, request):
        data_list = request.data.get('customers', [])
        success = 0
        for item in data_list:
            phone = clean_phone(item.get('phone', ''))
            if not phone: continue
            Customer.objects.create(
                phone=phone, 
                name=item.get('name', '이름없음'), 
                platform=item.get('platform', '기타'), 
                upload_date=datetime.date.today(), 
                status='미통건'
            )
            success += 1
        return Response({'message': f'총 {success}건 등록 완료', 'count': success})

# ==============================================================================
# 4. 마스터 데이터 및 통계 관리 (기존 로직 유지)
# ==============================================================================

class PlatformViewSet(viewsets.ModelViewSet):
    queryset = Platform.objects.all(); serializer_class = PlatformSerializer; permission_classes = [IsAuthenticated]
class FailureReasonViewSet(viewsets.ModelViewSet):
    queryset = FailureReason.objects.all(); serializer_class = ReasonSerializer; permission_classes = [IsAuthenticated]
class CustomStatusViewSet(viewsets.ModelViewSet):
    queryset = CustomStatus.objects.all(); serializer_class = StatusSerializer; permission_classes = [IsAuthenticated]
class SettlementStatusViewSet(viewsets.ModelViewSet):
    queryset = SettlementStatus.objects.all(); serializer_class = SettlementStatusSerializer; permission_classes = [IsAuthenticated]
class SalesProductViewSet(viewsets.ModelViewSet):
    queryset = SalesProduct.objects.all(); serializer_class = SalesProductSerializer; permission_classes = [IsAuthenticated]
class ConsultationLogViewSet(viewsets.ModelViewSet):
    queryset = ConsultationLog.objects.all(); serializer_class = LogSerializer; permission_classes = [IsAuthenticated]

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_stats(request):
    period = request.query_params.get('period', 'month')
    user_id = request.query_params.get('user_id')
    today = timezone.now().date()
    
    start_date = today.replace(day=1) if period == 'month' else today
    query = Q(upload_date__gte=start_date)
    
    if user_id == 'mine': query &= Q(owner=request.user)
    elif user_id and user_id != 'ALL': query &= Q(owner_id=user_id)
    
    target = Customer.objects.filter(query)
    revenue_status = ['접수완료', '설치완료']
    
    net_profit = sum((int(c.agent_policy or 0) - int(c.support_amt or 0)) * 10000 for c in target.filter(status__in=revenue_status))

    return Response({
        'total_db': target.count(),
        'accept_count': target.filter(status__in=revenue_status).count(),
        'net_profit': net_profit,
        'period': period
    })