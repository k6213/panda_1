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
    AdChannel, Bank, Notice, PolicyImage, TodoTask, CancelReason, Client
)
from .serializers import (
    CustomerSerializer, UserSerializer, PlatformSerializer, 
    ReasonSerializer, StatusSerializer, SettlementStatusSerializer, 
    SalesProductSerializer, LogSerializer,
    AdChannelSerializer, BankSerializer, NoticeSerializer, PolicyImageSerializer, TodoTaskSerializer, CancelReasonSerializer, ClientSerializer
)

from .system_config import CONFIG_DATA




# sales/views.py 에 추가

@api_view(['GET'])
@permission_classes([AllowAny]) # 누구나 (고객 폰이) 접속해서 봐야 하므로 AllowAny
def image_preview_page(request, log_id):
    """
    고객이 문자의 링크를 눌렀을 때 보여줄 페이지
    동시에 스마트폰이 미리보기(OG)를 긁어가는 페이지
    """
    sms_log = get_object_or_404(SMSLog, id=log_id)
    
    if not sms_log.image:
        return HttpResponse("이미지를 찾을 수 없습니다.", status=404)

    # 실제 이미지 파일의 절대 경로 (Render 주소로 보정)
    raw_img_url = request.build_absolute_uri(sms_log.image.url)
    full_img_url = raw_img_url.replace("http://127.0.0.1:8000", "https://panda-1-hd18.onrender.com")

    # Open Graph 태그가 포함된 HTML 작성
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        
        <meta property="og:title" content="상담 사진 확인">
        <meta property="og:description" content="보내드린 사진을 확인하시려면 클릭하세요.">
        <meta property="og:image" content="{full_img_url}">
        <meta property="og:type" content="website">
        
        <style>
            body {{ margin: 0; display: flex; justify-content: center; background: #000; }}
            img {{ max-width: 100%; height: auto; }}
        </style>
    </head>
    <body>
        <img src="{full_img_url}" alt="상담이미지">
    </body>
    </html>
    """
    return HttpResponse(html_content)
    
# [유틸리티] 전화번호 정규화
def clean_phone(phone):
    if not phone: return ""
    cleaned = re.sub(r'[^0-9]', '', str(phone))
    if cleaned.startswith('82') and len(cleaned) > 10:
        cleaned = '0' + cleaned[2:]
    return cleaned


# 2. 문자 발송 엔진 (공식 문서 규격 100% 일치 버전)
def send_traccar_cloud_sms(phone, sms_text, token, image_url=None):
    url = "https://www.traccar.org/sms/"
    
    if not token:
        print("❌ 토큰이 없습니다.")
        return False

    # 1. 전화번호 포맷팅
    raw_num = re.sub(r'[^0-9]', '', str(phone))
    formatted_phone = '+82' + raw_num[1:] if raw_num.startswith('0') else '+82' + raw_num

    # 2. 인증 헤더 (중괄호 하나만 사용!)
    headers = {
        "Authorization": token, 
        "Content-Type": "application/json"
    }

    # 3. 데이터 구성 (중괄호 하나만 사용!)
    payload = {
        "to": formatted_phone, 
        "message": sms_text
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        print(f"📡 Traccar 요청 결과: {response.status_code}")
        return response.status_code in [200, 201, 202]
    except Exception as e:
        print(f"❌ SMS 발송 중 예외 발생: {e}")
        return False

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_sms_connection(request):
    # 1. 리액트가 보낸 데이터에서 'token'을 직접 꺼냄
    phone = request.data.get('phone')
    token = request.data.get('token') # 👈 gateway_config 대신 token으로 변경

    if not phone or not token:
        return Response({"message": "번호나 토큰값이 없습니다."}, status=400)

    # 2. 수정된 엔진 함수 실행
    test_msg = "[연동테스트] 서버와 휴대폰이 연결되었습니다."
    success = send_traccar_cloud_sms(clean_phone(phone), test_msg, token)

    if success:
        return Response({"message": "테스트 문자 발송 성공!"})
    else:
        return Response({"message": "발송 실패! 토큰을 확인하세요."}, status=400)
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

# sales/views.py 내의 SMSReceiveView 클래스 수정

# views.py 내의 SMSReceiveView 클래스 수정

class SMSReceiveView(APIView):
    permission_classes = [AllowAny] 
    # 사진 파일을 처리하기 위해 파서 추가
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        data = request.data
        # 게이트웨이 앱에서 보낸 이미지 파일 확인
        incoming_image = request.FILES.get('image') or request.FILES.get('file')
        
        print(f"📥 웹훅 수신 데이터: {data}") 

        # 1. 데이터 추출 (텍스트 및 번호)
        if 'payload' in data:
            payload = data.get('payload', {})
            from_num = payload.get('phoneNumber')
            msg_content = payload.get('message', '')
        else:
            from_num = data.get('from') or data.get('sender')
            msg_content = data.get('message', '') or data.get('text', '')

        if not from_num:
            return Response({"message": "발신 번호가 없습니다."}, status=400)

        clean_num = clean_phone(from_num)
        customer = Customer.objects.filter(phone__contains=clean_num[-8:]).first()
        
        if customer:
            # 2. 📸 수신된 사진과 메시지를 DB에 저장
            sms_log = SMSLog.objects.create(
                customer=customer, 
                agent=customer.owner, 
                content=msg_content if msg_content else "(사진 수신)", 
                image=incoming_image, # 👈 여기에 고객이 보낸 사진이 저장됩니다.
                direction='IN', # 수신
                status='RECEIVED'
            )
            
            # 부재중이었으면 상태 변경
            if customer.status == '부재':
                customer.status = '재통'
                customer.save()
            
            print(f"✅ {customer.name}님의 사진/답장 저장 완료! (Log ID: {sms_log.id})")
            return Response({"status": "success"}, status=200)
        
        return Response({"status": "ignored"}, status=200)

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
    # 1. 데이터 추출
    customer_id = request.data.get('customer_id')
    sms_text = request.data.get('message', '').strip()
    image_file = request.FILES.get('image')
    token = request.data.get('token')

    if not customer_id or not token:
        return Response({"message": "고객 ID와 인증 토큰이 필요합니다."}, status=400)

    agent = request.user
    customer = get_object_or_404(Customer, id=customer_id)

    # 2. DB 로그 생성 (ID를 먼저 따야 미리보기 주소를 만들 수 있습니다)
    log = SMSLog.objects.create(
        customer=customer, 
        agent=agent, 
        content=sms_text if sms_text else "(사진 첨부)", 
        image=image_file,
        direction='OUT', 
        status='PENDING'
    )

    # 3. 🚀 [핵심] 자동 미리보기를 위한 URL 생성 로직
    final_sms_text = sms_text # 기본값은 입력한 텍스트
    
    if log.image:
        # 파일 경로(.jpg)가 아니라, 우리가 만든 HTML 뷰 페이지 주소를 생성합니다.
        preview_page_url = request.build_absolute_uri(f"/api/sms/view/{log.id}/")
        
        # 실서버 주소로 보정
        preview_page_url = preview_page_url.replace("http://127.0.0.1:8000", "https://panda-1-hd18.onrender.com")
        
        # ⭐️ 중요: 스마트폰이 '자동 변환'을 하게 하려면 URL만 단독으로 보내는 게 가장 좋습니다.
        # 만약 텍스트와 같이 보내고 싶다면 preview_page_url을 맨 앞에 두세요.
        if sms_text:
            final_sms_text = f"{preview_page_url}\n\n{sms_text}"
        else:
            final_sms_text = preview_page_url

    # 4. 최종 발송 실행
    # (이미지 주소를 media 인자로 따로 주지 않아도, 폰이 URL을 해석해서 이미지를 띄웁니다)
    if send_traccar_cloud_sms(customer.phone, final_sms_text, token):
        log.status = 'SUCCESS'
        log.save()
        return Response({"message": "전송 성공", "log_id": log.id}, status=200)
    else:
        log.status = 'FAIL'
        log.save()
        return Response({"message": "발송 실패 (기기 연결 상태 또는 토큰 확인)"}, status=200)

# 1. 미리보기 페이지 (가장 위나 적당한 곳에 두세요)
@api_view(['GET'])
@permission_classes([AllowAny]) 
def image_preview_page(request, log_id):
    sms_log = get_object_or_404(SMSLog, id=log_id)
    if not sms_log.image:
        return HttpResponse("이미지를 찾을 수 없습니다.", status=404)

    # 실제 이미지 경로 (Render 주소로 강제 변환)
    img_url = request.build_absolute_uri(sms_log.image.url).replace(
        "http://127.0.0.1:8000", "https://panda-1-hd18.onrender.com"
    )

    # 🖼️ 스마트폰이 긁어갈 '사진 카드' 정보
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta property="og:title" content="상담 사진 확인">
        <meta property="og:description" content="클릭하여 원본 사진을 확인하세요.">
        <meta property="og:image" content="{img_url}">
        <meta property="og:type" content="website">
        <style>body {{ background:#000; margin:0; display:flex; justify-content:center; align-items:center; height:100vh; }} img {{ max-width:100%; }}</style>
    </head>
    <body><img src="{img_url}"></body>
    </html>
    """
    return HttpResponse(html_content)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_sms_history(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    logs = SMSLog.objects.filter(customer=customer).order_by('created_at')
    
    data = []
    for l in logs:
        image_url = None
        if l.image:
            # 상대 경로를 절대 경로로 변환 (Render 주소 적용)
            raw_url = request.build_absolute_uri(l.image.url)
            image_url = raw_url.replace("http://127.0.0.1:8000", "https://panda-1-hd18.onrender.com")

        data.append({
            'id': l.id,
            'sender': 'me' if l.direction == 'OUT' else 'other', # 'other'가 고객
            'text': l.content,
            'image': image_url, # 👈 수신된 사진 URL 포함
            'created_at': l.created_at.strftime("%Y-%m-%d %H:%M"),
            'status': l.status
        })
        
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
        data = request.data.get('customers', [])
        cnt = 0
        
        for item in data:
            if not item.get('phone'): continue
            
            # 🟢 [수정됨] 프론트엔드에서 보낸 담당자(owner_id)와 상태(status) 받기
            owner_id = item.get('owner_id')
            status_val = item.get('status', '미통건') # 값이 없으면 '미통건' 기본값
            last_memo = item.get('last_memo')         # 엑셀의 상담 내용

            # 담당자 객체 찾기 (ID가 있을 경우)
            owner_obj = None
            if owner_id:
                try:
                    owner_obj = User.objects.get(id=owner_id)
                except User.DoesNotExist:
                    owner_obj = None

            # 🟢 [수정됨] DB 생성 시 담당자와 상태값 적용
            customer = Customer.objects.create(
                phone=clean_phone(item['phone']), 
                name=item.get('name', '미상'), 
                upload_date=datetime.date.today(), 
                status=status_val,        # 👈 탭에 맞는 상태 (접수완료/장기가망 등)
                owner=owner_obj,          # 👈 탭에 맞는 담당자 (나)
                platform=item.get('platform', '기타')
            )

            # 🟢 [수정됨] 상담 메모가 있다면 로그와 함께 저장
            if last_memo:
                customer.last_memo = last_memo
                customer.save()
                ConsultationLog.objects.create(
                    customer=customer,
                    writer=owner_obj if owner_obj else request.user, # 담당자 혹은 업로더
                    content=f"[초기메모] {last_memo}"
                )

            cnt += 1
            
        return Response({'message': f'{cnt}건 등록 완료', 'count': cnt})

    @action(detail=False, methods=['post'])
    def referral(self, request):
        data = request.data
        user = request.user
        Customer.objects.create(name=data.get('name', '지인소개'), phone=clean_phone(data.get('phone')), platform=data.get('platform', '지인'), status='접수완료', owner=user, upload_date=datetime.date.today(), product_info=data.get('product_info', ''))
        return Response({'message': '지인 접수 등록 완료'}, status=201)
        
    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        customer = self.get_object()
        
        # related_name='logs'로 설정되어 있다고 가정 (ConsultationLog 모델 등)
        # 만약 에러나면 customer.consultationlog_set.all() 로 변경 시도
        logs = customer.logs.all().order_by('-created_at') 
        
        from .serializers import LogSerializer
        serializer = LogSerializer(logs, many=True)
        
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def start_chat(self, request):
        """
        📱 번호를 입력받아 채팅방을 조회하거나 새로 생성함
        """
        raw_phone = request.data.get('phone')
        phone = clean_phone(raw_phone) # 하이픈 제거 및 정규화
        
        if not phone or len(phone) < 10:
            return Response({"message": "유효한 전화번호를 입력해주세요."}, status=400)

        # 1. 기존 고객이 있는지 확인 (전체 DB 기준)
        customer = Customer.objects.filter(phone=phone).first()

        if customer:
            # 2-1. 이미 있다면: 담당자 확인
            if not customer.owner:
                # 담당자가 없다면 나에게 배정
                customer.owner = request.user
                customer.save()
                message = "미배정 DB를 나에게 배정하고 채팅방을 열었습니다."
            elif customer.owner == request.user:
                message = "기존 상담중인 채팅방을 열었습니다."
            else:
                # 다른 사람의 담당인 경우 안내만 하고 정보 반환
                return Response({
                    "message": f"이미 {customer.owner.username}님이 상담 중인 번호입니다.",
                    "customer": CustomerSerializer(customer).data,
                    "is_other_owner": True
                }, status=200)
        else:
            # 2-2. 없다면: 새로 생성하고 나에게 배정
            customer = Customer.objects.create(
                phone=phone,
                name=request.data.get('name', f"신규_{phone[-4:]}"),
                owner=request.user,
                status='미통건',
                platform='기타',
                upload_date=datetime.date.today(),
                last_memo="채팅 검색을 통해 새 방이 생성되었습니다."
            )
            # 로그 생성
            ConsultationLog.objects.create(
                customer=customer,
                writer=request.user,
                content="[시스템] 신규 번호 입력을 통해 채팅방 개설"
            )
            message = "새로운 채팅방이 생성되었습니다."

        serializer = self.get_serializer(customer)
        return Response({
            "message": message,
            "customer": serializer.data
        }, status=200)
        

class NoticeViewSet(viewsets.ModelViewSet):
    queryset = Notice.objects.all().order_by('-is_important', '-created_at'); serializer_class = NoticeSerializer; permission_classes = [IsAuthenticated]
    def perform_create(self, serializer): serializer.save(writer=self.request.user)

class PolicyImageViewSet(viewsets.ModelViewSet):
    queryset = PolicyImage.objects.all()
    serializer_class = PolicyImageSerializer
    permission_classes = [IsAuthenticated] # 필요시 주석 해제

    # sales/views.py 파일의 해당 부분

    @action(detail=False, methods=['get'])
    def latest(self, request):
        data = {}
        platforms = PolicyImage.objects.values_list('platform', flat=True).distinct()
        
        for p in platforms:
            images = PolicyImage.objects.filter(platform=p).order_by('-updated_at')
            data[p] = [
                {
                    "id": img.id, 
                    "url": request.build_absolute_uri(img.image.url) if img.image else None
                } 
                for img in images if img.image
            ]
        return Response(data)

    # 📤 [업로드] 여러 장의 이미지를 한 번에 저장
    def create(self, request, *args, **kwargs):
        platform = request.data.get('platform')
        images = request.FILES.getlist('image')

        if not images:
            return Response({"message": "업로드할 이미지가 없습니다."}, status=status.HTTP_400_BAD_REQUEST)

        created_count = 0
        for img in images:
            PolicyImage.objects.create(
                platform=platform,
                image=img
            )
            created_count += 1

        return Response({
            "message": f"{created_count}장의 이미지가 성공적으로 업로드되었습니다.",
            "status": "success"
        }, status=status.HTTP_201_CREATED)

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



class TodoTaskViewSet(viewsets.ModelViewSet):
    queryset = TodoTask.objects.all()
    serializer_class = TodoTaskSerializer

    def perform_create(self, serializer):
        serializer.save(sender=self.request.user)

    # 관리자용: 내가 지시한 업무 목록 조회
    @action(detail=False, methods=['get'])
    def assigned(self, request):
        # 내가 보낸 것 or 전체 공지
        tasks = TodoTask.objects.all().order_by('-created_at')
        serializer = self.get_serializer(tasks, many=True)
        return Response(serializer.data)

class CancelReasonViewSet(viewsets.ModelViewSet): 
    queryset = CancelReason.objects.all().order_by('-created_at')
    serializer_class = CancelReasonSerializer
    permission_classes = [IsAuthenticated]
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_stats(request): return Response({'message': 'Use /api/stats/advanced/ instead'})


class ClientViewSet(viewsets.ModelViewSet):
    queryset = Client.objects.all().order_by('name')
    serializer_class = ClientSerializer