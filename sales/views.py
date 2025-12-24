import os
import json
import datetime
import re
import firebase_admin
from firebase_admin import credentials, messaging
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
# 🔥 Firebase Admin SDK 초기화 (환경 변수 또는 로컬 파일 대응)
# ==============================================================================
if not firebase_admin._apps:
    try:
        # 1. Render 환경 변수(FIREBASE_CONFIG) 확인
        fb_config_str = os.environ.get('FIREBASE_CONFIG')
        if fb_config_str:
            fb_config = json.loads(fb_config_str)
            cred = credentials.Certificate(fb_config)
            print("✅ Firebase: 환경 변수(FIREBASE_CONFIG)로 초기화 성공")
        # 2. 로컬 파일 확인
        elif os.path.exists("serviceAccountKey.json"):
            cred = credentials.Certificate("serviceAccountKey.json")
            print("🏠 Firebase: 로컬 파일로 초기화 성공")
        else:
            print("⚠️ Firebase: 인증 정보를 찾을 수 없습니다. SMS 발송이 제한됩니다.")
            cred = None
            
        if cred:
            firebase_admin.initialize_app(cred)
    except Exception as e:
        print(f"❌ Firebase 초기화 에러: {str(e)}")

# ==============================================================================
# [유틸리티] 전화번호 정규화 (국가코드 제거 및 숫자만 추출)
# ==============================================================================
def clean_phone(phone):
    if not phone: return ""
    # 숫자만 추출
    cleaned = re.sub(r'[^0-9]', '', str(phone))
    # 국가코드 82 제거 및 010 형태로 통일
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
# 2. 🔥 SMS 양방향 연동 (카카오톡 스타일 채팅 구현의 핵심)
# ==============================================================================

class SMSReceiveView(APIView):
    """ 고객이 보낸 문자를 수신 (Traccar 게이트웨이 앱의 Webhook) """
    permission_classes = [AllowAny] 

    def post(self, request):
        from_num = clean_phone(request.data.get('from', ''))
        msg_content = request.data.get('message', '')

        if not from_num or not msg_content:
            return Response({"message": "데이터 부족"}, status=400)

        # 번호 매칭 (뒤 8자리 비교가 가장 정확함)
        search_num = from_num[-8:]
        customer = Customer.objects.filter(phone__contains=search_num).first()

        if customer:
            # 수신 로그 기록 (방향: IN)
            SMSLog.objects.create(
                customer=customer, 
                agent=customer.owner, # 담당 상담사 매칭
                content=msg_content, 
                direction='IN', 
                status='RECEIVED'
            )
            # 수신 시 상담 상태를 '재통'으로 자동 변경하여 알림 효과 부여 (선택 사항)
            if customer.status == '부재':
                customer.status = '재통'
                customer.save()

            return Response({"status": "success"}, status=200)
        
        return Response({"status": "ignored", "message": "등록되지 않은 고객 번호"}, status=200)



class LeadCaptureView(APIView):
    """ 
    [홍보링크 발송 & 랜딩페이지 수집] 
    상담사가 신규 번호에 링크를 쏠 때와 고객이 직접 신청할 때 모두 사용
    """
    permission_classes = [AllowAny] 

    def post(self, request):
        phone = clean_phone(request.data.get('phone', ''))
        agent_id = request.data.get('agent_id')
        name = request.data.get('name', '신규문의')
        custom_message = request.data.get('message') # 프론트에서 보낸 홍보문구

        if not phone or not agent_id:
            return Response({"message": "필수 정보(번호/상담사)가 없습니다."}, status=400)

        agent = get_object_or_404(User, id=agent_id)
        
        # 1. 고객 등록 또는 기존 데이터 확보
        customer, created = Customer.objects.get_or_create(
            phone=phone,
            defaults={'name': name, 'owner': agent, 'status': '미통건'}
        )

        # 2. 발송할 텍스트 결정
        sms_text = custom_message if custom_message else f"[상담신청] {name}님 정보가 접수되었습니다."

        # 3. 발송 로그 생성 (방향: OUT)
        log = SMSLog.objects.create(
            customer=customer, agent=agent, content=sms_text, direction='OUT', status='PENDING'
        )

        # 4. 안드로이드 기기로 FCM 발송 명령 전달
        if agent.fcm_token:
            try:
                message = messaging.Message(
                    data={'to': phone, 'message': sms_text},
                    token=agent.fcm_token,
                )
                messaging.send(message)
                log.status = 'SUCCESS'; log.save()
                return Response({
                    "message": "발송 명령 완료", 
                    "customer_id": customer.id, 
                    "is_new": created
                }, status=201)
            except Exception as e:
                log.status = f'FAIL: {str(e)}'; log.save()
                return Response({"message": "기기 전송 실패", "customer_id": customer.id}, status=201)
        
        return Response({"message": "접수완료(기기 미연결)", "customer_id": customer.id}, status=201)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_manual_sms(request):
    """ 채팅창 하단 입력칸에서 상담사가 직접 문자를 보낼 때 실행 """
    customer_id = request.data.get('customer_id')
    sms_text = request.data.get('message')
    agent = request.user
    customer = get_object_or_404(Customer, id=customer_id)

    if not agent.fcm_token:
        return Response({'message': '연결된 안드로이드 기기가 없습니다.'}, status=400)

    try:
        # FCM 전송
        message = messaging.Message(
            data={'to': clean_phone(customer.phone), 'message': sms_text},
            token=agent.fcm_token,
        )
        messaging.send(message)
        
        # 발송 성공 로그 저장
        SMSLog.objects.create(
            customer=customer, agent=agent, content=sms_text, direction='OUT', status='SUCCESS'
        )
        return Response({"message": "전송 성공"})
    except Exception as e:
        return Response({"message": f"발송 에러: {str(e)}"}, status=500)

# ==============================================================================
# 3. 모델 기반 CRUD ViewSets
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
        # 관리자는 전체 DB, 상담사는 본인 담당 + 공유(미배정) DB만 조회
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
# 4. 통계 및 마스터 데이터 관리
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
    
    # 통계 기간 설정
    start_date = today.replace(day=1) if period == 'month' else today
    query = Q(upload_date__gte=start_date)
    
    if user_id == 'mine': query &= Q(owner=request.user)
    elif user_id and user_id != 'ALL': query &= Q(owner_id=user_id)
    
    target = Customer.objects.filter(query)
    revenue_status = ['접수완료', '설치완료']
    
    # 수익 계산 (단위: 원)
    net_profit = sum((int(c.agent_policy or 0) - int(c.support_amt or 0)) * 10000 for c in target.filter(status__in=revenue_status))

    return Response({
        'total_db': target.count(),
        'accept_count': target.filter(status__in=revenue_status).count(),
        'net_profit': net_profit,
        'period': period
    })